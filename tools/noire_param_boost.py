#!/usr/bin/env python3
"""
Доповнення характеристик до мінімуму Rozetka (3 на товар).

Чому окремий модуль, а не правки в noire_param_extractor.py:
той екстрактор пише параметри під Єпіцентр, де кожне значення мусить
збігатися з valuecode із довідника PIM. Rozetka приймає вільні пари
«назва — значення» (тег <param>), тому тут доречні характеристики, які
для Єпіцентру не підійшли б: колір з назви, розмір, стать, комплектація.

Пишемо з source='rozetka_boost' — щоб генератор Єпіцентру їх не підхопив
і щоб будь-коли можна було прибрати одним DELETE.

Запуск:
    python3 tools/noire_param_boost.py --dry      # показати, нічого не писати
    python3 tools/noire_param_boost.py            # застосувати
"""
import argparse
import os
import re
import sys
import collections

import psycopg2
import psycopg2.extras
from psycopg2.extras import execute_values
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

MIN_PARAMS = 3
SOURCE = 'rozetka_boost'

# ── Колір ───────────────────────────────────────────────────────────────────
COLORS = [
    (r'\bblack\b|\bчорн|\bnero\b|\bчерн', 'чорний'),
    (r'\bwhite\b|\bбіл(ий|а|е)\b|\bбел', 'білий'),
    (r'\bred\b|\bчервон|\bкрасн|\bwine\b|\bbordo', 'червоний'),
    (r'\bpink\b|\bрожев|\bроз(овый|овая)\b|\brose\b|\bfuchsia', 'рожевий'),
    (r'\bblue\b|\bсин(ій|я|є)\b|\bблакитн|\bnavy\b|\baqua\b|\bteal\b', 'синій'),
    (r'\bgreen\b|\bзелен|\bolive\b|\bmint\b', 'зелений'),
    (r'\bpurple\b|\bviolet\b|\bфіолетов|\bлілов|\bбузков|\blilac\b', 'фіолетовий'),
    (r'\bgold\b|\bзолот|\bgolden\b|\bchampagne\b', 'золотий'),
    (r'\bsilver\b|\bсрібн|\bсеребр', 'сріблястий'),
    (r'\bbeige\b|\bбежев|\bnude\b|\bvanilla\b|\bflesh\b|\btelesn', 'бежевий'),
    (r'\bbrown\b|\bкоричнев|\bcaramel\b|\bcoffee\b', 'коричневий'),
    (r'\byellow\b|\bжовт|\borange\b|\bпомаранчев', 'жовтий'),
    (r'\bgrey\b|\bgray\b|\bсір(ий|а)\b|\bсер(ый|ая)\b', 'сірий'),
    (r'\btransparent\b|\bпрозор|\bclear\b', 'прозорий'),
]

# ── Розмір ──────────────────────────────────────────────────────────────────
SIZE_RULES = [
    (r'\bone\s*size\b|\bуніверсальн|\bos\b(?![a-z])', 'One Size'),
    (r'\b(xxxl|3xl)\b', 'XXXL'),
    (r'\b(xxl|2xl)\b', 'XXL'),
    (r'\bxl\b', 'XL'),
    (r'\bxs\b', 'XS'),
    (r'\b([sml])\s*/\s*([sml])\b', None),      # S/M, M/L — беремо як є
    (r'\bl\b(?![a-z])', 'L'),
    (r'\bm\b(?![a-z])', 'M'),
    (r'\bs\b(?![a-z])', 'S'),
]

# ── Стать / для кого ────────────────────────────────────────────────────────
GENDER_RULES = [
    (r'чоловіч|\bmen\b|\bmale\b|для чоловіків|пеніс|член\b', 'для чоловіків'),
    (r'жіноч|\bwomen\b|\bfemale\b|для жінок|вагін|клітор', 'для жінок'),
    (r'для пар|\bcouple', 'для пар'),
    (r'унісекс|\bunisex\b', 'унісекс'),
]

# ── Тип виробу за назвою (перше значуще слово) ──────────────────────────────
TYPE_RULES = [
    (r'^бодістокінг|бодістокінг', 'бодістокінг'),
    (r'^комплект|комплект білизни', 'комплект білизни'),
    (r'^сукня|сукн', 'сукня'),
    (r'^спідниц', 'спідниця'),
    (r'^пеньюар', 'пеньюар'),
    (r'^сорочка|сорочк', 'сорочка'),
    (r'^боді\b|\bбоді\b', 'боді'),
    (r'^корсет|корсет', 'корсет'),
    (r'^трусик|^труси\b|стрінг', 'трусики'),
    (r'^панчох|панчох', 'панчохи'),
    (r'^колготк', 'колготки'),
    (r'^костюм|рольов', 'рольовий костюм'),
    (r'^маска|\bмаска\b', 'маска'),
    (r'^гра\b|^набір.{0,20}гра|кубик', 'еротична гра'),
    (r'^наручник', 'наручники'),
    (r'^фіксатор|^розтяжка', 'фіксатор'),
    (r'^мастурбатор|онахол', 'мастурбатор'),
    (r'^вібратор', 'вібратор'),
    (r'^лубрикант|^змазк|^гель-?змазк', 'лубрикант'),
    (r'^презерватив', 'презерватив'),
    (r'^масажн.{0,12}олі|^олія', 'масажна олія'),
    (r'^свічк', 'масажна свічка'),
    (r'^набір|^комплект', 'набір'),
]

STOP_VALUES = {'', '-', 'немає', 'none'}


def first_match(rules, text):
    for rx, val in rules:
        m = re.search(rx, text, re.I)
        if m:
            return val if val is not None else m.group(0).upper()
    return None


def extract_qty(name: str):
    m = re.search(r'(\d+)\s*(?:шт|предмет|елемент|pcs)', name, re.I)
    return f'{m.group(1)} шт' if m else None


def extract_volume(name: str):
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(мл|ml|г\b|гр\b|мг)', name, re.I)
    if not m:
        return None
    unit = {'ml': 'мл', 'гр': 'г', 'мг': 'мг'}.get(m.group(2).lower(), m.group(2))
    return f'{m.group(1).replace(",", ".")} {unit}'


def brand_country(vendor: str):
    m = re.search(r'\(([^)]+)\)', vendor or '')
    return m.group(1).strip() if m else None


def boost(name: str, vendor: str, cat_name: str, have: set) -> dict:
    """Характеристики, яких ще немає у товару."""
    text = f'{name} {cat_name}'
    out = {}

    def add(k, v):
        if v and k not in have and str(v).lower() not in STOP_VALUES:
            out[k] = str(v)[:500]          # Rozetka: максимум 500 символів

    add('Колір', first_match(COLORS, name))
    add('Розмір', first_match(SIZE_RULES, name))
    add('Для кого', first_match(GENDER_RULES, text))
    add('Тип', first_match(TYPE_RULES, name))
    add('Кількість в упаковці', extract_qty(name))
    add('Об\'єм', extract_volume(name))
    add('Країна бренду', brand_country(vendor))
    if vendor:
        add('Бренд', re.sub(r'\s*\(.*?\)', '', vendor).strip())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--limit', type=int)
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT p.sku, p.name, p.vendor,
               COALESCE(m.sexopt_category_name,'') AS cat,
               COALESCE(c.n, 0) AS np
        FROM sexopt_products p
        LEFT JOIN epicentr_category_mapping m ON m.sexopt_category_id = p.category_id
        LEFT JOIN (SELECT sku, count(*) n FROM sexopt_extracted_params
                   GROUP BY sku) c ON c.sku = p.sku
        WHERE p.available IS TRUE AND COALESCE(c.n,0) < %s
        ORDER BY p.sku
    """, (MIN_PARAMS,))
    rows = cur.fetchall()
    if a.limit:
        rows = rows[:a.limit]
    logger.info(f'Товарів з < {MIN_PARAMS} характеристик: {len(rows)}')

    cur.execute("""SELECT sku, param_name FROM sexopt_extracted_params
                   WHERE sku = ANY(%s)""", ([r['sku'] for r in rows],))
    existing = collections.defaultdict(set)
    for r in cur.fetchall():
        existing[r['sku']].add(r['param_name'])

    batch, stat = [], collections.Counter()
    after = collections.Counter()
    for r in rows:
        have = existing[r['sku']]
        add = boost(r['name'], r['vendor'], r['cat'], have)
        for k, v in add.items():
            batch.append((r['sku'], k, '', v, SOURCE))
            stat[k] += 1
        after[min(r['np'] + len(add), 9)] += 1

    logger.info(f'Нових значень: {len(batch)}')
    print('\nЩО ДОДАЄТЬСЯ:')
    for k, v in stat.most_common():
        print(f'   {k:24} {v}')
    ok = sum(v for k, v in after.items() if k >= MIN_PARAMS)
    print(f'\nДосягнуть {MIN_PARAMS}+ характеристик: {ok} з {len(rows)}')
    print(f'Залишаться нижче порога: {len(rows) - ok}')

    if a.dry:
        print('\n(--dry: у базу нічого не записано)')
        return
    if batch:
        execute_values(cur, """
            INSERT INTO sexopt_extracted_params (sku, param_name, param_code,
                                                 param_value, source)
            VALUES %s
            ON CONFLICT (sku, param_name) DO NOTHING
        """, batch, page_size=1000)
        conn.commit()
        logger.success(f'Записано {len(batch)} характеристик')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
