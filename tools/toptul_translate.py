#!/usr/bin/env python3
"""Переклад характеристик TOPTUL на українську — словником, не по картках.

Замір 21.08.2026: у фіді 33757 характеристик, з них **45% мають російську
назву** (15256 вживань), а різних назв лише 319. Значень російською 6950.
Тобто перекладати треба словник унікальних рядків, а не кожне вживання —
319 запитів замість 15 тисяч.

Чому хмарна модель тут дозволена: асортимент — інструменти, обмеження щодо
18+ на TOPTUL не поширюється (перевірено, NVIDIA обробляє без відмов).

Захист від вигадок: модель повертає рядки ПОРЯДКОВО, і кількість рядків у
відповіді мусить збігатися з кількістю на вході. Не збіглась — партія
відхиляється цілком, а не «підганяється».

Запуск:
    python3 tools/toptul_translate.py --names --dry
    python3 tools/toptul_translate.py --names --values
"""
import argparse
import collections
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2.extras  # noqa: E402
from loguru import logger  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402

FEED = os.getenv('TOPTUL_FEED_FILE', '/tmp/toptul.xml')
API = 'https://integrate.api.nvidia.com/v1/chat/completions'
# Доступ до КОНКРЕТНОЇ моделі зникає без попередження: 21.08.2026 о 06:20
# nemotron-120b обробила 30 запитів поспіль, а о 06:58 почала віддавати
# HTTP 404 із порожнім тілом, тоді як решта моделей працювала. Тому не одна
# модель, а перелік: на 404 переходимо до наступної й далі працюємо нею.
MODELS = [m for m in (os.getenv('NOIRE_TRANSLATE_MODEL'),
                      'nvidia/nemotron-3-super-120b-a12b',
                      'mistralai/mistral-nemotron',
                      'deepseek-ai/deepseek-v4-flash-0731') if m]
_active = [0]
BATCH = 15

# ── Дві РІЗНІ ознаки російської, бо в них різна ціна помилки ──────────────
#
# Коментар над попередньою версією стверджував, що спільних для обох мов слів
# у переліку немає, — і це було неправдою: `ширина`, `рукоятк*`, `привод*`,
# `момент*`, `числ*`, `шестигранн*` однакові в українській. Через них
# самоперевірка генератора рахувала «26 назв російською, 1203 вживання» на
# рядках «Ширина», «Матеріал рукоятки», «Вид приводу інструмента» — уже
# перекладених. Число було фактом про регекс, не про фід.
#
# RU — СТРОГА ознака, тільки для замірів «скільки лишилось російського».
# Хибна тривога тут робить число нечитаним, тож її не має бути зовсім.
# RU_WIDE — ШИРОКА, тільки для ВІДБОРУ рядків на переклад. Тут навпаки:
# зайвий рядок у партії коштує кількох токенів (модель поверне його без
# змін), а пропущений — російського рядка у фіді назавжди.
#
# Замір на контролі 22.08.2026 (`output/noire_rozetka.xml`, 592721 слововживань
# української прози): RU спрацювала 181 раз, і ЖОДНОГО хибно — усі влучення
# справді російські залишки («Трендовая», «Размер», «эластан», «цвет»).
# Позитивний контроль — `--selftest` нижче.

# Закінчення, яких українська словозміна не утворює (укр. -ія, -ення, -ість).
# Мінімальна основа для -ое і -ой саме 3 літери: на 2 туди потрапляють
# українське «алое» (178 вживань у контролі) і «герой».
_RU_END = (r'[а-яіїєґ]{2,}(?:ие|ия|ая|ость|ости)\b'
           r'|[а-яіїєґ]{3,}ое\b'
           r'|[а-яіїєґ]{3,}(?<!гер)(?<!конв)(?<!ковб)ой\b')

# Основи, де російська форма відрізняється від української написанням
# (диаметр/діаметр, материал/матеріал) або словом (длина/довжина).
# `привода`/`момента` — саме родовий відмінок: називний «привод», «момент»
# спільний для обох мов, а «приводу»/«моменту» вже українські.
_RU_STEM = (r'отвертк\w*|съемник\w*|трещоточн\w*|удлинитель\w*|переходник\w*|'
            r'размер\w*|материал\w*|цвет\b|количество|инструмент\w*|ед\.|'
            r'длина|высота|вес\b|диаметр|давлени\w*|напряжени\w*|мощност\w*|'
            r'скорост\w*|привода\b|момента\b')

RU = re.compile(r'[ыэъё]|' + _RU_END + r'|\b(?:' + _RU_STEM + r')', re.I)

# Основи, однакові в обох мовах: для замірів непридатні, для відбору корисні —
# «Ширина зажима» і «Шестигранник привода» російські, але жодної строгої
# ознаки не мають.
RU_WIDE = re.compile(RU.pattern + r'|\b(?:рукоятк\w*|ширина|шестигранн\w*|'
                     r'привод\w*|момент\w*|числ\w*)', re.I)

# Позитивний контроль: перевірка, яка нічого не ловить, дає нуль, не
# помиляючись. Пари підібрані так, щоб кожен рядок LEFT відрізнявся від
# RIGHT лише мовою.
SELFTEST_RU = [
    'Ширина зажима', 'Дополнительная рукоятка', 'Тип привода',
    'Передаточное число', 'Ключ шестигранный', 'Диаметр колес',
    'Материал изделия', 'Прямой', 'Накидной', 'Назначение', 'Питание',
    'Комплектация', 'Погрешность, +/-', 'Мощность лампы', '12 ед.',
    'Трещоточная викрутка-бітотримач', 'Ключ накидной силовой односторонний',
]
SELFTEST_UK = [
    'Ширина', 'Матеріал рукоятки', 'Вид приводу інструмента',
    'Ширина полотна', 'Ширина губок', 'Додаткова рукоятка',
    'Довжина рукоятки', 'Передаточне число', 'Шестигранник', 'Шестигранні',
    'Ключ шестигранний', 'Тип приводу', 'з прямим приводом',
    'Максимальний крутний момент', 'Діаметр коліс', 'Матеріал виробу',
    'Призначення', 'Живлення', 'Потужність лампи', 'Комплектація',
    'Набір ключів', 'Головка торцева', 'алое', 'герой',
]


def selftest() -> int:
    """0 = обидві ознаки поводяться як задумано."""
    bad = 0
    for s in SELFTEST_RU:
        if not RU_WIDE.search(s):
            logger.error(f'RU_WIDE НЕ впізнала російське: {s!r}')
            bad += 1
    for s in SELFTEST_UK:
        m = RU.search(s)
        if m:
            logger.error(f'RU хибно спрацювала на українському: {s!r} '
                         f'через {m.group(0)!r}')
            bad += 1
    # RU строга: скільки з відомо російських вона бачить без спільних основ
    seen = sum(1 for s in SELFTEST_RU if RU.search(s))
    logger.info(f'RU (строга) впізнає {seen}/{len(SELFTEST_RU)} російських; '
                f'решту добирає лише RU_WIDE — так і задумано')
    if bad:
        logger.error(f'самоперевірка ознаки мови: {bad} розбіжностей')
    else:
        logger.success(f'самоперевірка ознаки мови: {len(SELFTEST_RU)} '
                       f'російських впізнано, 0 хибних на '
                       f'{len(SELFTEST_UK)} українських')
    return bad

# Прив'язка за ПОРЯДКОМ рядків виявилась крихкою: модель розбивала
# багатослівні значення на кілька рядків, і партія на 25 позицій приходила
# як 27 або 34 — відхилялась цілком. Тому кожен рядок несе свій оригінал,
# і зіставлення йде за ним, а не за позицією. Зайві рядки ігноруються.
PROMPT = """Переклади українською терміни з каталогу інструментів.

ФОРМАТ ВІДПОВІДІ — по одному рядку на кожен термін:
оригінал ||| переклад

ПРАВИЛА:
- зліва від ||| постав оригінал ТОЧНО як у переліку, без змін;
- якщо термін уже українською — праворуч повтори його без змін;
- бренди, моделі, артикули, одиниці виміру НЕ перекладай;
- без нумерації, без пояснень, без порожніх рядків.

ПЕРЕЛІК ({n}):
{items}"""


def ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS toptul_translation (
        kind TEXT, src TEXT, dst TEXT, uses INT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (kind, src))""")


def translate(items: list, key: str) -> dict:
    """{оригінал: переклад}. Зіставлення за рядком, не за позицією."""
    wanted = set(items)
    # Читаємо ТІЛЬКИ content. Резервне читання reasoning_content, доречне в
    # класифікації, тут отруйне: у міркуванні сотні рядків, і партія на 40
    # позицій відхилялась як «198 рядків замість 40». Порожній content
    # означає лише брак токенів — повторюємо з більшим бюджетом.
    txt = ''
    for tokens in (1500, 3000):
        while _active[0] < len(MODELS):
            model = MODELS[_active[0]]
            body = {'model': model, 'temperature': 0, 'max_tokens': tokens,
                    'messages': [{'role': 'user', 'content': PROMPT.format(
                        n=len(items), items='\n'.join(items))}]}
            try:
                r = requests.post(API, headers={'Authorization': f'Bearer {key}'},
                                  json=body, timeout=240)
            except Exception as e:
                logger.warning(f'{type(e).__name__}')
                return {}
            if r.status_code == 404:
                logger.warning(f'модель {model} недоступна (404) — переходжу далі')
                _active[0] += 1
                continue
            try:
                txt = (r.json()['choices'][0]['message'].get('content') or '').strip()
            except Exception:
                logger.warning(f'нечитана відповідь HTTP {r.status_code}')
                return {}
            break
        if _active[0] >= len(MODELS):
            logger.error('усі моделі недоступні')
            return {}
        if txt:
            break
    if not txt:
        logger.warning('порожній content навіть на 12000 токенів')
        return {}
    pairs = {}
    for line in txt.split('\n'):
        if '|||' not in line:
            continue
        src, _, dst = line.partition('|||')
        src = re.sub(r'^\s*\d+[\.\)]\s*', '', src.strip())
        dst = dst.strip()
        if src in wanted and dst:
            pairs[src] = dst
    if not pairs:
        logger.warning('жодної пари з роздільником у відповіді')
    return pairs


# Третій вид рядків — НАЗВА ТОВАРУ. Вона не лежить у `<param>`, тому
# окрема гілка: беремо той самий тег, який обирає генератор, і перекладаємо
# СИРУ назву постачальника. Не побудовану: `build_name()` викидає бренд,
# артикул і пунктуацію, тож побудована назва — похідна, і словник із неї
# розсипався б від будь-якої зміни правил побудови.
KINDS = ('name', 'value', 'title')
TITLE_TAGS = ('name_ua', 'name')


def title_tag(offers: list) -> str:
    """Тег назви не вгадується (крок 1 правила позитивного контролю).

    У фіді TOPTUL є ОБИДВА теги, і вони різні за мовою: `name` російський
    у 5688 випадках із 6895, `name_ua` — у 238. Взяти не той означало б
    «перекласти» 5,7 тис. рядків, яких у фіді Rozetka немає взагалі.
    """
    for t in TITLE_TAGS:
        if any((o.findtext(t) or '').strip() for o in offers):
            return t
    return TITLE_TAGS[0]


def collect(kind: str) -> collections.Counter:
    root = ET.parse(FEED).getroot()
    offers = root.find('shop').find('offers').findall('offer')
    c = collections.Counter()
    if kind == 'title':
        tag = title_tag(offers)
        for o in offers:
            s = (o.findtext(tag) or '').strip()
            # Відбір — ШИРОКОЮ ознакою (див. нижче), тому сюди потрапляють і
            # вже українські назви на кшталт «Вороток з рукояткою». Модель
            # повертає їх без змін, і це дешевше за пропущений російський рядок.
            if s and RU_WIDE.search(s):
                c[s] += 1
        return c
    for o in offers:
        for p in o.findall('param'):
            s = (p.get('name') if kind == 'name' else (p.text or '')).strip()
            # Відбір — ШИРОКОЮ ознакою: краще віддати моделі зайвий
            # український рядок, ніж лишити російський неперекладеним.
            if s and RU_WIDE.search(s):
                c[s] += 1
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--names', action='store_true')
    ap.add_argument('--values', action='store_true')
    ap.add_argument('--titles', action='store_true',
                    help='назви товарів (сирий тег фіду, не побудована назва)')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--selftest', action='store_true',
                    help='позитивний контроль ознаки мови, без мережі й БД')
    a = ap.parse_args()

    if a.selftest:
        sys.exit(1 if selftest() else 0)

    key = os.getenv('NVIDIA_API_KEY')
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()

    for kind in [k for k, on in (('name', a.names), ('value', a.values),
                                 ('title', a.titles)) if on]:
        src = collect(kind)
        cur.execute('SELECT src FROM toptul_translation WHERE kind=%s', (kind,))
        done = {r['src'] for r in cur.fetchall()}
        todo = [s for s in src if s not in done]
        logger.info(f'модель {MODELS[_active[0]]}');logger.info(f'{kind}: різних {len(src)}, вживань {sum(src.values())}, '
                    f'до перекладу {len(todo)}')
        if a.dry:
            for s in todo[:10]:
                print(f'   {src[s]:5}  {s}')
            continue
        ok = 0
        for i in range(0, len(todo), BATCH):
            part = todo[i:i + BATCH]
            out = translate(part, key)
            if not out:
                continue
            for s, d in out.items():
                cur.execute("""INSERT INTO toptul_translation (kind, src, dst, uses)
                               VALUES (%s,%s,%s,%s)
                               ON CONFLICT (kind, src) DO UPDATE SET dst=EXCLUDED.dst""",
                            (kind, s, d, src[s]))
            conn.commit()
            ok += len(out)
            logger.info(f'  {kind}: {ok}/{len(todo)}')
            time.sleep(0.3)
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
