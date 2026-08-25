#!/usr/bin/env python3
"""Перелік товарів TOPTUL, які генератор НЕ пускає у фід Rozetka через категорію.

Рішення власника 25.08.2026: товари, для яких відповідника в каталозі Rozetka
немає, у фіді не тримати. Вибуття робить сам генератор
(`toptul_rozetka_generator.py`, лічильники «пропущено: категорія …»), а цей
скрипт відповідає на друге питання того ж пункту черги: ЩО САМЕ прибрано і з
якої причини — `docs/toptul_rozetka_dropped.md`.

Правило категорій НЕ переписується тут удруге: `ALLOWED_TIERS` і
`load_categories()` імпортуються з генератора. Два власні визначення «довіреної
категорії» неминуче розійшлись би, і звіт описував би не той фід, що на виході
— рівно так 23.08.2026 «в Rozetka немає такої категорії» означало насправді
«конкурент такого не возить».

Дві причини вибуття розділені, бо вони різні за суттю й за подальшим рішенням:
  * `rz_id IS NULL` — пари в Rozetka немає (перевірено по всіх 4762 категоріях
    офіційного каталогу, `docs/toptul_rozetka_unmapped.md`);
  * `tier='review'` — пара Є, але це відхилена здогадка нечіткого зіставлення
    («Інструмент для пайки → Набори інструментів», score 0.55). За SKILL-04
    хибна категорія гірша за відсутню.

Звіт себе перевіряє (правило позитивного контролю):
  * жоден перелічений артикул не мусить бути у виданому фіді;
  * артикули ЗАЛИШЕНИХ категорій навпаки мусять там бути — інакше перевірка
    «немає у фіді» просто зламана й давала б нуль на будь-чому.
Не збіглось — код виходу 1 і звіт не переписується.

Запуск (на сервері, де лежить фід постачальника):
    venv/bin/python3 tools/toptul_rozetka_dropped_report.py
    venv/bin/python3 tools/toptul_rozetka_dropped_report.py --check   # без запису
"""
import argparse
import collections
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
import psycopg2.extras  # noqa: E402
from loguru import logger  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402
from toptul_rozetka_generator import (ALLOWED_TIERS, FEED, MIN_PARAMS,  # noqa: E402
                                      OUT, collect_params, load_categories,
                                      load_translations, pictures,
                                      resolve_fields, _txt)

DOC = os.path.join(BASE_DIR, 'docs', 'toptul_rozetka_dropped.md')

REASON_NONE = 'немає пари в каталозі Rozetka'
REASON_REVIEW = 'пара є, але це відхилена здогадка (tier=review)'
REASON_ABSENT = 'категорії немає в таблиці мапінгу'


def classify(cid: str, cats: dict, blocked: dict):
    """Те саме рішення, що й у генераторі, тільки з назвою причини."""
    if cid in cats:
        return None
    if cid not in blocked:
        return REASON_ABSENT
    tier, rz_id, _ = blocked[cid]
    return REASON_NONE if rz_id is None else REASON_REVIEW


def feed_ids(path: str) -> set:
    """Артикули, які реально вийшли у фід Rozetka."""
    if not os.path.exists(path):
        return set()
    return {o.get('id') for o in ET.parse(path).getroot().iter('offer')
            if o.get('id')}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--feed', default=FEED, help='фід постачальника')
    ap.add_argument('--out', default=OUT, help='виданий фід Rozetka')
    ap.add_argument('--check', action='store_true',
                    help='лише перевірити, файл не переписувати')
    a = ap.parse_args()

    if not os.path.exists(a.feed):
        sys.exit(f'Фід постачальника не знайдено: {a.feed}')

    offers = ET.parse(a.feed).getroot().find('shop/offers').findall('offer')
    fields = resolve_fields(offers)
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cats, blocked = load_categories(cur)
    tr = load_translations(cur)
    cur.close()
    conn.close()

    # cid → {'reason', 'name', 'guess', 'items': [(sku, name, fit)]}
    dropped, kept_ids, fit_total = {}, [], 0
    for o in offers:
        cid = _txt(o, fields['cat'])
        sku = (o.get('id') or '').strip()
        reason = classify(cid, cats, blocked)
        if reason is None:
            if sku:
                kept_ids.append(sku)
            continue
        tier, rz_id, cname = blocked.get(cid, (None, None, None))
        rec = dropped.setdefault(cid, {
            'reason': reason, 'name': cname or f'(немає в мапінгу) {cid}',
            'guess': None, 'items': []})
        if reason == REASON_REVIEW:
            rec['guess'] = _guess_name(cid)
        # Скільки з прибраного ми справді втрачаємо. Категорія — не єдина
        # причина вибуття: 144 з 205 не мають і трьох характеристик, тобто
        # випали б і без цього рішення. Без цього числа «прибрано 205»
        # перебільшує наслідок рішення власника втричі.
        fit = _would_pass(o, fields, tr)
        fit_total += fit
        rec['items'].append((sku, _txt(o, fields['name']) or '', fit))

    drop_ids = {sku for r in dropped.values() for sku, _, _ in r['items'] if sku}
    published = feed_ids(a.out)

    # ── позитивний контроль: перевірка мусить уміти повернути й ненуль ──────
    leaked = sorted(drop_ids & published)
    kept_present = len(set(kept_ids) & published)
    logger.info(f'категорій без пари/недовірених: {len(dropped)}, '
                f'товарів у них: {sum(len(r["items"]) for r in dropped.values())}')
    logger.info(f'з них лишились у виданому фіді: {len(leaked)}')
    logger.info(f'артикулів довірених категорій у виданому фіді: '
                f'{kept_present} з {len(set(kept_ids))}')

    if not published:
        logger.error(f'Виданого фіду немає: {a.out} — перевірити нічим')
        return 1
    if kept_present == 0:
        logger.error('ЖОДНОГО артикула довіреної категорії не знайдено у фіді '
                     '— зламана сама перевірка присутності, а не дані')
        return 1
    if leaked:
        logger.error(f'У фіді лишились артикули прибраних категорій: '
                     f'{", ".join(leaked[:20])}')
        return 1

    if a.check:
        logger.success('Перевірка пройдена, файл не переписувався')
        return 0

    logger.info(f'з них пройшли б решту перевірок генератора: {fit_total}')
    _write(DOC, dropped, len(offers), kept_present, a.out, fit_total)
    logger.success(f'Записано: {DOC}')
    return 0


def _would_pass(offer, fields, tr) -> bool:
    """Чи пройшов би оффер решту перевірок генератора, якби категорія була.

    Порядок і пороги — ті самі, що в `generate()`, бо функції ті самі:
    `pictures()`, `collect_params()`, `MIN_PARAMS`. Переписані «схожі»
    перевірки розійшлись би з генератором, і число втрати було б вигаданим.
    """
    try:
        price = float((_txt(offer, fields['price']) or '0').replace(',', '.'))
    except ValueError:
        return False
    if price <= 0 or not pictures(offer, collections.Counter()):
        return False
    return len(collect_params(offer, tr)) >= MIN_PARAMS


_GUESS = {}


def _guess_name(cid: str) -> str:
    """Назва відхиленої здогадки — щоб у звіті було видно, ЩО саме відхилено."""
    if not _GUESS:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""SELECT toptul_id, rz_name, score FROM
                       toptul_rozetka_category_map WHERE tier NOT IN %s""",
                    (tuple(ALLOWED_TIERS),))
        for r in cur.fetchall():
            if r['rz_name']:
                _GUESS[r['toptul_id']] = (
                    f'{r["rz_name"]} (score {float(r["score"] or 0):.2f})')
        cur.close()
        conn.close()
    return _GUESS.get(cid, '')


def _write(path, dropped, total, kept_present, out_feed, fit_total):
    by_reason = collections.defaultdict(list)
    for cid, rec in dropped.items():
        by_reason[rec['reason']].append((cid, rec))
    n_items = sum(len(r['items']) for r in dropped.values())

    L = [f'# TOPTUL → Rozetka: що прибрано з фіду через категорію',
         '',
         f'Складено `tools/toptul_rozetka_dropped_report.py` '
         f'{datetime.now():%d.%m.%Y %H:%M}. Джерело — фід постачальника '
         f'({total} офферів) і той самий довідник категорій, що читає '
         f'генератор.', '',
         f'**Прибрано {n_items} товарів у {len(dropped)} категоріях.** '
         f'Рішення власника 25.08.2026: товари, для яких відповідника в '
         f'Rozetka немає, у фіді не тримати.', '',
         'Причин дві, і плутати їх не можна — до 25.08.2026 генератор рахував '
         'їх одним числом «категорія без rz_id: 205», хоча в 77 випадках '
         '`rz_id` є:', '']
    for reason in (REASON_NONE, REASON_REVIEW, REASON_ABSENT):
        rows = by_reason.get(reason)
        if rows:
            L.append(f'* **{reason}** — {sum(len(r["items"]) for _, r in rows)} '
                     f'товарів у {len(rows)} категоріях;')
    L += ['',
          f'**Реальна втрата менша за 205.** Категорія — не єдина причина '
          f'вибуття: решту перевірок генератора (ціна, фото, щонайменше '
          f'{MIN_PARAMS} характеристики) пройшли б лише **{fit_total}** із '
          f'{n_items}; інші {n_items - fit_total} випали б і без цього '
          f'рішення. Такі позиції позначені нижче «✓».', '',
          'Перевірка звіту, а не декларація: жоден із перелічених артикулів у '
          f'`{os.path.relpath(out_feed, BASE_DIR)}` не знайдений, тоді як '
          f'артикулів довірених категорій там {kept_present}. Тобто перевірка '
          '«немає у фіді» вміє повернути й ненуль, і нуль тут — факт про дані.',
          '']

    for reason in (REASON_NONE, REASON_REVIEW, REASON_ABSENT):
        rows = by_reason.get(reason)
        if not rows:
            continue
        L += [f'## {reason}', '']
        if reason == REASON_NONE:
            L += ['Перевірено по офіційному каталогу Rozetka (4762 категорії, '
                  '`market-categories/search`), а не по дереву конкурента. '
                  'Розгорнуті причини по кожній — '
                  '`docs/toptul_rozetka_unmapped.md`.', '']
        elif reason == REASON_REVIEW:
            L += ['Пара була підібрана нечітким зіставленням і відхилена '
                  '23.08.2026: за SKILL-04 хибна категорія гірша за відсутню — '
                  'товар лягає туди, де його не шукають, і фільтри до нього не '
                  'застосовуються.', '']
        for cid, rec in sorted(rows, key=lambda x: -len(x[1]['items'])):
            fit = sum(1 for _, _, f in rec['items'] if f)
            L += [f'### {rec["name"]} — {len(rec["items"])} товарів '
                  f'(готових до фіду: {fit})', '',
                  f'`{cid}`' + (f' · відхилена здогадка: {rec["guess"]}'
                                if rec.get('guess') else ''), '']
            for sku, name, f in sorted(rec['items'], key=lambda x: x[0]):
                L.append(f'* {"✓" if f else "·"} `{sku}` — {name}')
            L.append('')

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))


if __name__ == '__main__':
    sys.exit(main())
