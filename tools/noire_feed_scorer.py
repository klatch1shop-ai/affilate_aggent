#!/usr/bin/env python3
"""Оцінка якості фіду: один бал 0-100 на кожен SKU і зведення по каталогу.

Замінює ручні разові перевірки «чи стало краще». Досі після кожної хвилі
правок доводилось писати окремий скрипт під конкретне питання — скільки
характеристик, скільки габаритів, чи не повернувся дубль. Тут усі перевірки
зібрані в одну шкалу, результат зберігається, і наступний запуск показує
різницю сам.

Шкала свідомо зважена, а не «кожна перевірка по 1 балу»: заповненість
портальних характеристик важить більше за наявність фото, бо саме вона
визначає, чи потрапить товар у фільтри каталогу (SKILL-14.1), і саме там
у нас була найбільша прогалина.

Prom — перший майданчик. Rozetka й Єпіцентр підключаються заміною
`FIELDS` і `load_expected()`: решта логіки від майданчика не залежить.

Запуск:
    python3 tools/noire_feed_scorer.py                     # оцінити й зберегти
    python3 tools/noire_feed_scorer.py --no-save           # без запису в БД
    python3 tools/noire_feed_scorer.py --worst 30          # довший список
    python3 tools/noire_feed_scorer.py --history           # історія запусків
"""
import argparse
import collections
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime

import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

FEED = os.path.join(BASE_DIR, 'output', 'noire_prom.xml')
MARKETPLACE = 'prom'

# Ліміти майданчика — з офіційної специфікації (SKILL-13)
MAX_NAME = 110
MAX_KEYWORDS = 1024
# Літери, яких у полі цієї мови бути не повинно: суто українські в
# російському полі й навпаки. Поодинокі допускаються — назва товару
# постачальника інколи сама змішана.
WRONG_LANG = {'keywords': re.compile(r'[іїєґ]'),
              'keywords_ua': re.compile(r'[ыъэё]')}
MAX_PICTURES = 10
MIN_DESC = 30

# Ваги. Сума = 100. Порядок відображає вплив на видимість товару, а не
# зручність перевірки: характеристики й keywords вирішують, чи знайдуть
# картку взагалі, фото й опис — чи клікнуть на вже знайдену.
WEIGHTS = {
    'portal_params': 30,   # % заповнення портальних характеристик категорії
    'custom_params': 5,    # хоч щось поза портальними
    'keywords_ua': 15,
    'keywords_ru': 15,
    'dimensions': 10,
    'description': 15,
    'name': 5,
    'photos': 0,           # див. нижче
    'price': 5,
}
# Фото важать НУЛЬ. Підтримка Prom, лист 14.08.2026: «кількість фотографій
# не впливає на алгоритми ранжування та видимості товарів у видачі… 2-3
# якісних фотографій можуть бути цілком достатніми». Доти скорер знімав
# бали з 580 товарів за «2 фото із 3» — тобто міряв неіснуючу проблему.
# Перевірка лишається однією: товар БЕЗ жодного фото (таких зараз 0).


def _is_all_caps(name: str) -> bool:
    """Те саме визначення, що у валідаторі Prom — інакше бали розійдуться."""
    words = (name or '').split()
    if len(words) <= 3:
        return False
    upper = [w for w in words
             if re.search(r'[А-ЯЁІЇЄA-Z]', w) and not re.search(r'[а-яёіїєa-z]', w)]
    return len(upper) > 3


def load_expected(cur) -> dict:
    """portal_category_id → множина портальних характеристик категорії.

    Знаменник для оцінки заповненості. Без нього можна порахувати лише
    «≥2 характеристики», що нічого не каже: у категорії з 13 полями дві
    заповнені — це 15 %, а в категорії з 5 полями — 40 %.
    """
    cur.execute("""SELECT prom_category_id pid, attr_name a
                   FROM prom_category_attributes""")
    out = collections.defaultdict(set)
    for r in cur.fetchall():
        out[str(r['pid'])].add(r['a'])
    return out


def load_rrc(cur) -> dict:
    cur.execute("""SELECT sku, price_retail::float p FROM sexopt_products
                   WHERE price_retail > 0""")
    return {r['sku']: r['p'] for r in cur.fetchall()}


def score_offer(o, expected: dict, rrc: dict) -> tuple:
    """Бал 0-100 і перелік того, чого бракує."""
    miss, pts = [], 0.0
    sku = o.findtext('vendorCode') or o.get('id')
    pid = o.findtext('portal_category_id') or ''
    params = {p.get('name'): (p.text or '') for p in o.findall('param')}
    portal = expected.get(pid, set())

    # ── портальні характеристики: частка від можливих у цій категорії ──
    if portal:
        filled = len([k for k in params if k in portal])
        share = filled / len(portal)
        pts += WEIGHTS['portal_params'] * share
        if share < 1:
            miss.append(f'портальні {filled}/{len(portal)}')
    else:
        # категорії немає в довіднику — не штрафуємо за те, чого не існує
        pts += WEIGHTS['portal_params']

    # ── користувацькі: будь-що поза портальним переліком ──
    if [k for k in params if k not in portal]:
        pts += WEIGHTS['custom_params']
    else:
        miss.append('немає користувацьких характеристик')

    # ── пошукові запити, окремо по мовах ──
    for tag, key, label in (('keywords_ua', 'keywords_ua', 'keywords укр'),
                            ('keywords', 'keywords_ru', 'keywords рос')):
        v = (o.findtext(tag) or '').strip()
        if not v:
            miss.append(f'{label} порожні')
        elif len(v) > MAX_KEYWORDS:
            miss.append(f'{label} {len(v)} символів (ліміт {MAX_KEYWORDS})')
            pts += WEIGHTS[key] * 0.5
        else:
            # ціль — 8 фраз на мову (лист підтримки Prom 14.08.2026);
            # раніше метрика насичувалась на трьох і не бачила різниці
            n = len([x for x in v.split(',') if x.strip()])
            share = min(n / 8, 1.0)
            # Кількість фраз нічого не варта, якщо вони не тією мовою.
            # Реальний випадок: мовне куки Prom підмінило російську видачу
            # українською, 105 українських фраз пішли в поле keywords — і
            # скорер порахував їх повноцінними, бал не зрушив ні на бал.
            # Чужа мова коштує половини ваги поля.
            wrong = (WRONG_LANG[tag].findall(v))
            if len(wrong) > 2:
                share *= 0.5
                miss.append(f'{label}: чужа мова ({len(wrong)} літер)')
            pts += WEIGHTS[key] * share
            if n < 8:
                miss.append(f'{label}: {n} фраз із 8')

    # ── габарити: чотири поля або нічого ──
    d = o.find('dimensions')
    have = {c.tag for c in d} if d is not None else set()
    need = {'weight', 'width', 'height', 'length'}
    pts += WEIGHTS['dimensions'] * (len(have & need) / len(need))
    if have & need != need:
        miss.append('габарити ' + ('відсутні' if not have
                                   else f'{len(have & need)}/4'))

    # ── опис: довжина і відсутність дубля рос/укр ──
    du = re.sub(r'<[^>]+>', ' ', o.findtext('description_ua') or '')
    dr = re.sub(r'<[^>]+>', ' ', o.findtext('description') or '')
    du, dr = du.strip(), dr.strip()
    if not du:
        miss.append('немає опису')
    else:
        # довжина: до 400 символів росте лінійно, далі повний бал —
        # довший опис не гірший, але й не кращий за метрикою
        pts += WEIGHTS['description'] * 0.6 * min(len(du) / 400, 1.0)
        if len(du) < MIN_DESC:
            miss.append(f'опис {len(du)} символів (мін {MIN_DESC})')
        if dr and dr != du:
            pts += WEIGHTS['description'] * 0.4
        else:
            # регресія, яку вже ловили: російське поле = копія українського
            miss.append('опис рос = укр (дубль)')

    # ── назва ──
    name = o.findtext('name_ua') or o.findtext('name') or ''
    npts = WEIGHTS['name']
    if not name:
        miss.append('немає назви')
        npts = 0
    else:
        if len(name) > MAX_NAME:
            miss.append(f'назва {len(name)} символів (ліміт {MAX_NAME})')
            npts -= WEIGHTS['name'] * 0.4
        if _is_all_caps(name):
            miss.append('назва ALL CAPS')
            npts -= WEIGHTS['name'] * 0.3
        vendor = (o.findtext('vendor') or '').strip()
        if vendor and vendor.lower() not in name.lower():
            miss.append('бренду немає в назві')
            npts -= WEIGHTS['name'] * 0.3
    pts += max(npts, 0)

    # ── фото: лише факт наявності ──
    pics = len(o.findall('picture'))
    if not pics:
        miss.append('немає фото')
    elif pics > MAX_PICTURES:
        miss.append(f'фото {pics} (ліміт {MAX_PICTURES})')

    # ── ціна: наша домовленість — рівно РРЦ постачальника ──
    try:
        price = float(o.findtext('price') or 0)
    except ValueError:
        price = 0
    base = rrc.get(sku)
    if price <= 0:
        miss.append('немає ціни')
    elif base and abs(price - round(base + 0.4999)) > 1:
        miss.append(f'ціна {price:g} ≠ РРЦ {base:g}')
        pts += WEIGHTS['price'] * 0.5
    else:
        pts += WEIGHTS['price']

    return round(min(pts, 100), 1), miss


def ensure_tables(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feed_score_runs (
            run_at      TIMESTAMPTZ PRIMARY KEY,
            marketplace TEXT NOT NULL,
            offers      INTEGER,
            avg_score   NUMERIC,
            b90         INTEGER,
            b70         INTEGER,
            b_low       INTEGER,
            note        TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feed_score_items (
            run_at TIMESTAMPTZ NOT NULL,
            sku    TEXT NOT NULL,
            score  NUMERIC,
            missing JSONB,
            PRIMARY KEY (run_at, sku)
        )
    """)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--feed', default=FEED)
    ap.add_argument('--worst', type=int, default=10)
    ap.add_argument('--no-save', action='store_true')
    ap.add_argument('--history', action='store_true')
    ap.add_argument('--note', default='')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure_tables(cur)
    conn.commit()

    if a.history:
        cur.execute("""SELECT * FROM feed_score_runs
                       ORDER BY run_at DESC LIMIT 20""")
        print(f'{"дата":20} {"офф.":>6} {"бал":>6} {"90+":>6} {"70-89":>6} {"<70":>6}  нотатка')
        for r in cur.fetchall():
            print(f"{r['run_at']:%Y-%m-%d %H:%M}     {r['offers']:6} "
                  f"{r['avg_score']:6} {r['b90']:6} {r['b70']:6} {r['b_low']:6}"
                  f"  {r['note'] or ''}")
        return

    expected = load_expected(cur)
    rrc = load_rrc(cur)
    root = ET.parse(a.feed).getroot()
    offers = root.findall('.//offer')

    rows, miss_freq = [], collections.Counter()
    for o in offers:
        s, m = score_offer(o, expected, rrc)
        rows.append((o.findtext('vendorCode') or o.get('id'), s, m,
                     o.findtext('name_ua') or ''))
        miss_freq.update(x.split(':')[0].split(' ')[0] if False else x for x in m)

    n = len(rows)
    avg = sum(r[1] for r in rows) / n
    b90 = sum(1 for r in rows if r[1] >= 90)
    b70 = sum(1 for r in rows if 70 <= r[1] < 90)
    low = n - b90 - b70

    print(f'══ ЯКІСТЬ ФІДУ {MARKETPLACE.upper()} ══')
    print(f'офферів            : {n}')
    print(f'середній бал       : {avg:.1f} / 100')
    print(f'   90-100%         : {b90:5}  ({b90 * 100 // n}%)')
    print(f'   70-89%          : {b70:5}  ({b70 * 100 // n}%)')
    print(f'   нижче 70%       : {low:5}  ({low * 100 // n}%)')

    print(f'\nнайчастіші прогалини:')
    for k, v in miss_freq.most_common(12):
        print(f'   {v:5}  {k}')

    print(f'\n── ТОП-{a.worst} найгірших ──')
    for sku, s, m, nm in sorted(rows, key=lambda x: x[1])[:a.worst]:
        print(f'{s:5.1f}  {sku:10} {nm[:44]}')
        print(f'        бракує: {"; ".join(m)[:130]}')

    # ── порівняння з попереднім запуском ──
    cur.execute("""SELECT * FROM feed_score_runs WHERE marketplace=%s
                   ORDER BY run_at DESC LIMIT 1""", (MARKETPLACE,))
    prev = cur.fetchone()
    if prev:
        d = avg - float(prev['avg_score'])
        print(f'\n── проти запуску {prev["run_at"]:%Y-%m-%d %H:%M} ──')
        print(f'   бал   {prev["avg_score"]} → {avg:.1f}   ({d:+.1f})')
        print(f'   90+   {prev["b90"]} → {b90}   ({b90 - prev["b90"]:+d})')
        print(f'   <70   {prev["b_low"]} → {low}   ({low - prev["b_low"]:+d})')
    else:
        print('\n(попереднього запуску немає — це baseline)')

    if not a.no_save:
        now = datetime.now()
        cur.execute("""INSERT INTO feed_score_runs
            (run_at, marketplace, offers, avg_score, b90, b70, b_low, note)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (now, MARKETPLACE, n, round(avg, 1), b90, b70, low, a.note))
        psycopg2.extras.execute_values(cur, """
            INSERT INTO feed_score_items (run_at, sku, score, missing)
            VALUES %s""",
            [(now, r[0], r[1], psycopg2.extras.Json(r[2])) for r in rows],
            page_size=500)
        conn.commit()
        print(f'\nзбережено: {now:%Y-%m-%d %H:%M}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
