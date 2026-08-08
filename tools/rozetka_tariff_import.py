#!/usr/bin/env python3
"""Імпорт офіційного тарифного файла Rozetka у rozetka_cpa_rates.

Джерело: кабінет продавця → «Мій баланс» → «Історія тарифів».
Файл лежить у data/rozetka/ і зберігається довгостроково — ставки
переглядаються, і мати під рукою попередню редакцію потрібно, щоб
пояснити зміну цін заднім числом.

Структура аркуша (одна таблиця, два блоки поруч):
    B  ID категорії      E  діапазон (стара редакція)   F  ставка %
    C  назва укр         I  діапазон (нова редакція)    J  ставка %
Значення «без змін» у колонці J означає, що нова ставка дорівнює старій.

Ставки в колонках K/L — з ПДВ (ставка × 1,08). У розрахунок ціни беремо
БЕЗ ПДВ: саме стільки Rozetka утримує з неплатника ПДВ.

Рядок з діапазоном «-» — базова ставка. Вона діє на все, що не покрито
явними діапазонами, тобто від нуля до початку найнижчого з них.

Запуск:
    python3 tools/rozetka_tariff_import.py --file data/rozetka/rozetka_tariffs_2026-08-15.xlsx
    python3 tools/rozetka_tariff_import.py --dry
"""
import argparse
import os
import re
import sys
import collections

import openpyxl
import psycopg2
import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

DEFAULT_FILE = os.path.join(BASE_DIR, 'data', 'rozetka',
                            'rozetka_tariffs_2026-08-15.xlsx')
VALID_FROM = '2026-08-15'
TOP = 999999999


def _num(v):
    if v is None or v == '':
        return None
    try:
        return float(str(v).replace(',', '.'))
    except ValueError:
        return None


def _range(v):
    """«1400-3999» → (1400, 3999); «-» або порожньо → None (базова ставка)."""
    s = str(v or '').strip()
    m = re.fullmatch(r'(\d+)\s*-\s*(\d+)', s)
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse(path: str) -> dict:
    """→ {cat_id: {'name', 'old': [(lo,hi,rate)], 'new': [...]}}"""
    ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    acc = collections.defaultdict(
        lambda: {'name': '', 'old_base': None, 'new_base': None,
                 'old': [], 'new': []})

    for row in ws.iter_rows(values_only=True):
        cid = _num(row[1])
        if cid is None:
            continue
        cid = str(int(cid))
        rec = acc[cid]
        rec['name'] = rec['name'] or str(row[2] or '').strip()

        old_rate, new_raw = _num(row[5]), str(row[9] or '').strip()
        new_rate = old_rate if new_raw == 'без змін' else _num(row[9])

        rng_old, rng_new = _range(row[4]), _range(row[8])
        if old_rate is not None:
            (rec['old'].append((*rng_old, old_rate)) if rng_old
             else rec.update(old_base=old_rate))
        if new_rate is not None:
            (rec['new'].append((*rng_new, new_rate)) if rng_new
             else rec.update(new_base=new_rate))

    # базова ставка покриває все нижче найдешевшого явного діапазону
    for rec in acc.values():
        for key, base in (('old', rec['old_base']), ('new', rec['new_base'])):
            if base is None:
                continue
            lo = min((r[0] for r in rec[key]), default=None)
            rec[key].insert(0, (0, lo - 1 if lo else TOP, base))
            rec[key].sort()
    return acc


def ensure_columns(cur):
    """Стара і нова редакції живуть поруч — файл містить обидві."""
    cur.execute("""
        ALTER TABLE rozetka_cpa_rates
            ADD COLUMN IF NOT EXISTS price_ranges_new  JSONB,
            ADD COLUMN IF NOT EXISTS base_commission_new NUMERIC,
            ADD COLUMN IF NOT EXISTS valid_from        DATE,
            ADD COLUMN IF NOT EXISTS source_file       TEXT,
            ADD COLUMN IF NOT EXISTS source            TEXT
    """)


# Батьківські категорії, від яких успадковують ставку наші шість.
# Записуємо ТІЛЬКИ їх. Таблиця rozetka_cpa_rates спільна з Carvol, і рядки
# авто-гілки (4627858, 4660244, …) належать йому — чіпати їх не можна.
# Наші рядки позначені source='noire', як і в rozetka_category_mapping.
NOIRE_PARENTS = {
    '4629305': "Краса та здоров'я",
    '2033137': 'Одяг',
    '1162030': 'Одяг, взуття та аксесуари',
}
SOURCE = 'noire'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', default=DEFAULT_FILE)
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    data = parse(a.file)
    logger.info(f'Категорій у файлі: {len(data)}, до запису: {len(NOIRE_PARENTS)}')

    conn = get_connection()
    cur = conn.cursor()

    # Додати колонки треба до перевірки — сама перевірка читає source.
    # ADD COLUMN IF NOT EXISTS лише розширює схему й не змінює жодного
    # наявного рядка, тож Carvol-записів це не торкається.
    if not a.dry:
        ensure_columns(cur)
        conn.commit()

    # Захист від зачіпання чужих рядків: якщо категорія вже є в таблиці
    # і належить не нам — не чіпаємо її і кажемо про це вголос.
    try:
        cur.execute('SELECT category_id, source FROM rozetka_cpa_rates '
                    'WHERE category_id = ANY(%s)', (list(NOIRE_PARENTS),))
        foreign = [r['category_id'] for r in cur.fetchall()
                   if (r['source'] or '') != SOURCE]
    except psycopg2.Error:          # колонки ще немає — отже й рядків наших
        conn.rollback()
        foreign = []
    if foreign:
        logger.error(f'Ці категорії вже зайняті іншим джерелом: {foreign}. '
                     f'Запис скасовано.')
        return

    rows = []
    for cid in NOIRE_PARENTS:
        rec = data.get(cid)
        if not rec:
            logger.warning(f'{cid} у файлі не знайдено')
            continue
        rows.append((cid, rec['name'] or NOIRE_PARENTS[cid],
                     rec['old_base'], psycopg2.extras.Json(
                         [list(r) for r in rec['old']]),
                     rec['new_base'], psycopg2.extras.Json(
                         [list(r) for r in rec['new']]),
                     VALID_FROM, os.path.basename(a.file), SOURCE))
        print(f"\n{cid} {rec['name']}")
        print(f"   стара: {rec['old']}")
        print(f"   нова : {rec['new']}")

    if a.dry:
        print(f'\n(--dry: {len(rows)} рядків не записано)')
        return

    ensure_columns(cur)
    for r in rows:
        cur.execute("""
            UPDATE rozetka_cpa_rates
               SET category_name=%s, base_commission=%s, price_ranges=%s,
                   base_commission_new=%s, price_ranges_new=%s,
                   valid_from=%s, source_file=%s, source=%s
             WHERE category_id=%s AND source=%s
        """, (*r[1:], r[0], SOURCE))
        if cur.rowcount == 0:
            cur.execute("""
                INSERT INTO rozetka_cpa_rates
                  (category_id, category_name, base_commission, price_ranges,
                   base_commission_new, price_ranges_new, valid_from,
                   source_file, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, r)
    conn.commit()
    logger.success(f'Записано {len(rows)} категорій з source={SOURCE}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
