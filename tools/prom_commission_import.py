#!/usr/bin/env python3
"""Імпорт офіційних комісій Prom.ua для гілки «Інтимні товари».

Джерело: кабінет продавця → тарифи, файл Комісія Prom.xlsx.
Зберігається в data/prom/ довгостроково — ставки переглядаються, і мати
попередню редакцію потрібно, щоб пояснити зміну цін заднім числом.

Аркуш «Категорії з комісією за замовлення»: 4554 рядки, 5 рівнів категорій.
Колонки: рівень, ID категорії, назва, далі чотири ставки — «Економ»,
«Єдина комісія», «Більше продажів», «Турбо». Нам потрібна ЄДИНА КОМІСІЯ:
це режим «Звичайний», підтверджений власником.

Другий аркуш («комісія за перехід») — оплата за клік, не наш випадок.

Ставки у файлі — частки (0.1888), у таблицю пишемо відсотки (18.88).

Файл вивантажений з Google Sheets, тому формули збережені як
__xludf.DUMMYFUNC — читаємо data_only=True, тобто кешовані значення.

Запуск:
    python3 tools/prom_commission_import.py --dry
    python3 tools/prom_commission_import.py
"""
import argparse
import os
import sys

import openpyxl
import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

DEFAULT_FILE = os.path.join(BASE_DIR, 'data', 'prom',
                            'prom_commission_2026-08.xlsx')
SOURCE = 'noire'
MODE = 'Єдина комісія'          # режим «Звичайний»

# Категорії поза гілкою «Інтимні товари», які використовує мапінг:
# для феромонної парфумерії Prom має точнішу категорію в «Красі та здоровʼї».
EXTRA_CATEGORIES = [
    '161610',    # парфумерія з феромонами
    # категорії поза гілкою, куди Prom обґрунтовано переносить наші товари
    '161018', '16221301', '170702', '15131004', '161217', '1507',
    '63719', '70811', '63010', '330619', '330623', '330622', '331502',
]

COL_LEVEL, COL_ID, COL_NAME = 5, 6, 7
COL_ECONOM, COL_SINGLE, COL_MORE, COL_TURBO = 8, 9, 10, 11


def parse(path: str) -> dict:
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    out = {}
    for row in ws.iter_rows(min_row=5, values_only=True):
        if not row or len(row) <= COL_TURBO:
            continue
        cid = row[COL_ID]
        if cid is None or not str(cid).strip().isdigit():
            continue

        def pct(i):
            v = row[i]
            return round(float(v) * 100, 2) if isinstance(v, (int, float)) else None

        out[str(cid).strip()] = {
            'name': str(row[COL_NAME] or '').strip(),
            'path': ' > '.join(str(row[i]) for i in range(5)
                               if row[i] and str(row[i]).strip()),
            'level': row[COL_LEVEL],
            'econom': pct(COL_ECONOM), 'single': pct(COL_SINGLE),
            'more': pct(COL_MORE), 'turbo': pct(COL_TURBO),
        }
    return out


def ensure_columns(cur):
    """Розширюємо наявну таблицю, не ламаючи Toptul-рядки."""
    cur.execute("""
        ALTER TABLE prom_cpa_rates
            ADD COLUMN IF NOT EXISTS category_id   TEXT,
            ADD COLUMN IF NOT EXISTS category_path TEXT,
            ADD COLUMN IF NOT EXISTS rate_econom   NUMERIC,
            ADD COLUMN IF NOT EXISTS rate_single   NUMERIC,
            ADD COLUMN IF NOT EXISTS rate_more     NUMERIC,
            ADD COLUMN IF NOT EXISTS rate_turbo    NUMERIC,
            ADD COLUMN IF NOT EXISTS source        TEXT,
            ADD COLUMN IF NOT EXISTS source_file   TEXT
    """)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', default=DEFAULT_FILE)
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    data = parse(a.file)
    logger.info(f'Категорій у файлі: {len(data)}')

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT category_id, name, full_path FROM prom_categories
                   WHERE full_path ILIKE 'Інтимні товари%%'
                      OR category_id::text = ANY(%s)""", (EXTRA_CATEGORIES,))
    # category_id у prom_categories — bigint, у файлі — рядок: зводимо до str
    ours = {str(r['category_id']): r for r in cur.fetchall()}
    logger.info(f'Наших категорій (гілка + додаткові): {len(ours)}')

    rows, missing = [], []
    for cid, meta in ours.items():
        rec = data.get(cid)
        if not rec or rec['single'] is None:
            missing.append((cid, meta['name']))
            continue
        rows.append((cid, rec['name'] or meta['name'], rec['path'],
                     rec['econom'], rec['single'], rec['more'], rec['turbo'],
                     rec['single'], SOURCE, os.path.basename(a.file)))

    print(f"\n{'ID':>10} {'категорія':44} {'Економ':>7} {'ЄДИНА':>7} "
          f"{'Більше':>7} {'Турбо':>7}")
    for r in sorted(rows, key=lambda x: -x[4]):
        print(f"{r[0]:>10} {r[1][:42]:44} {r[3]:>6.2f}% {r[4]:>6.2f}% "
              f"{r[5]:>6.2f}% {r[6]:>6.2f}%")
    if missing:
        print(f'\nНЕМАЄ У ТАРИФНОМУ ФАЙЛІ ({len(missing)}):')
        for cid, nm in missing:
            print(f'   {cid:>10} {nm[:56]}')

    if a.dry:
        print(f'\n(--dry: {len(rows)} рядків не записано)')
        return

    ensure_columns(cur)
    for r in rows:
        cur.execute("""UPDATE prom_cpa_rates SET category_name=%s,
                         category_path=%s, rate_econom=%s, rate_single=%s,
                         rate_more=%s, rate_turbo=%s, cpa_rate=%s,
                         source=%s, source_file=%s
                       WHERE category_id=%s AND source=%s""",
                    (*r[1:], r[0], SOURCE))
        if cur.rowcount == 0:
            cur.execute("""INSERT INTO prom_cpa_rates
                (category_id, category_name, category_path, rate_econom,
                 rate_single, rate_more, rate_turbo, cpa_rate, source,
                 source_file)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", r)
    conn.commit()
    logger.success(f'Записано {len(rows)} категорій, source={SOURCE}, '
                   f'режим «{MODE}»')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
