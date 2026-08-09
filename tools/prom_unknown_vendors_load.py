#!/usr/bin/env python3
"""Бренди, невідомі базі виробників Prom → prom_unknown_vendors.

Prom імпортує виробника лише якщо він є в базі маркетплейсу; інакше у звіті
про імпорт зʼявляється «Невідомий виробник», і товар публікується без бренду.
Це попередження, а не помилка — імпорт не блокується.

Визначити цей список програмно неможливо: публічної вигрузки бази виробників
немає, API акаунта віддає 401. Єдине достовірне джерело — звіт про імпорт
з кабінету. Тому список наповнюється звідти, а не здогадками: спроба
вирахувати «невідомі» бренди за рідкістю дала б 270 SKU при порозі ≤10,
але під заміну потрапили б Nexus, Svakom та інші цілком реальні марки.

Після наповнення генератор підміняє ці бренди на «Без бренда» — той самий
принцип, що застосований до запчастин без TecDoc-ідентифікації.

Запуск:
    # зі списку назв (по одній у рядку або через кому)
    python3 tools/prom_unknown_vendors_load.py --file report_vendors.txt
    python3 tools/prom_unknown_vendors_load.py --names "Alive, Wooomy, LOCKINK"

    # з файла звіту імпорту (xlsx/csv) — шукає колонку з виробником
    python3 tools/prom_unknown_vendors_load.py --from-report import_report.xlsx

    python3 tools/prom_unknown_vendors_load.py --list
    python3 tools/prom_unknown_vendors_load.py --clear
"""
import argparse
import os
import re
import sys

import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

VENDOR_COL = re.compile(r'виробник|производит|vendor|бренд|торгов', re.I)


def ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prom_unknown_vendors (
            vendor     TEXT PRIMARY KEY,
            note       TEXT,
            added_at   TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def from_report(path: str) -> list:
    """Витягти назви виробників зі звіту імпорту (xlsx або csv)."""
    names = []
    if path.lower().endswith(('.xlsx', '.xls')):
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        head = [str(c or '') for c in rows[0]]
        idx = next((i for i, h in enumerate(head) if VENDOR_COL.search(h)), None)
        if idx is None:
            logger.error(f'Колонки з виробником не знайдено. Заголовки: {head}')
            return []
        names = [str(r[idx]).strip() for r in rows[1:]
                 if idx < len(r) and r[idx]]
    else:
        import csv
        with open(path, encoding='utf-8-sig', newline='') as f:
            rd = csv.reader(f)
            head = next(rd, [])
            idx = next((i for i, h in enumerate(head) if VENDOR_COL.search(h)), 0)
            names = [r[idx].strip() for r in rd if idx < len(r) and r[idx].strip()]
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', help='текстовий список назв')
    ap.add_argument('--names', help='через кому')
    ap.add_argument('--from-report', dest='report', help='xlsx/csv звіту імпорту')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--clear', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure_table(cur)
    conn.commit()

    if a.list:
        cur.execute('SELECT vendor, note FROM prom_unknown_vendors ORDER BY vendor')
        rows = cur.fetchall()
        print(f'Невідомих брендів: {len(rows)}')
        for r in rows:
            print(f"   {r['vendor']}")
        return
    if a.clear:
        cur.execute('DELETE FROM prom_unknown_vendors')
        conn.commit()
        logger.success('Список очищено')
        return

    names = []
    if a.report:
        names = from_report(a.report)
    elif a.file:
        names = re.split(r'[\n,;]+', open(a.file, encoding='utf-8').read())
    elif a.names:
        names = a.names.split(',')
    else:
        ap.error('вкажи --from-report, --file, --names, --list або --clear')

    names = sorted({n.strip() for n in names if n and n.strip()})
    if not names:
        logger.warning('Жодної назви не розпізнано')
        return

    # Показуємо, скільки SKU у фіді зачепить кожна назва
    cur.execute("""SELECT regexp_replace(vendor,'\\s*\\(.*\\)','') v, count(*) n
                   FROM sexopt_products
                   WHERE available IS TRUE AND quantity > 1
                     AND NOT damaged_stock AND price_retail > 0
                   GROUP BY 1""")
    have = {r['v'].strip().lower(): r['n'] for r in cur.fetchall()}

    total = 0
    print(f"{'бренд':34} {'SKU у пулі':>11}")
    for n in names:
        cnt = have.get(n.lower(), 0)
        total += cnt
        print(f'   {n[:32]:34} {cnt:>8}'
              + ('   ← у нашому пулі немає' if not cnt else ''))
    print(f'\nбрендів {len(names)}, зачеплених SKU {total}')

    psycopg2.extras.execute_values(cur, """
        INSERT INTO prom_unknown_vendors (vendor, note) VALUES %s
        ON CONFLICT (vendor) DO NOTHING
    """, [(n, 'зі звіту імпорту Prom') for n in names])
    conn.commit()
    logger.success(f'Записано {len(names)} брендів. '
                   f'Наступна генерація підмінить їх на «Без бренда».')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
