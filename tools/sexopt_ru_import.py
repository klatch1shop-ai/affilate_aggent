#!/usr/bin/env python3
"""Імпорт російськомовного контенту SexOpt у sexopt_products_ru.

Постачальник віддає два окремі фіди на той самий асортимент: україномовний
(з нього живе весь проєкт) і російськомовний. Другий не використовувався від
початку, через що у Prom-фіді name == name_ua і description == description_ua
на всіх 5495 позиціях — тобто російська версія картки була україномовною
копією.

Тут тільки завантаження та зберігання. Генератор Prom цю таблицю ще не
читає — підключення окремим кроком, після узгодження плану.

Запуск:
    python3 tools/sexopt_ru_import.py            # завантажити й записати
    python3 tools/sexopt_ru_import.py --report   # стан таблиці
"""
import argparse
import io
import os
import re
import sys
import xml.etree.ElementTree as ET

import requests
import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

RU_FEED = 'https://smtm.com.ua/_prices/import-retail-2.xml'
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
# ознака того, що «російський» текст насправді український
UA_LETTERS = re.compile(r'[іїєґІЇЄҐ]')


def ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sexopt_products_ru (
            sku         TEXT PRIMARY KEY,
            name_ru     TEXT,
            description_ru TEXT,
            is_ru       BOOLEAN,
            fetched_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def fetch(url: str) -> bytes:
    r = requests.get(url, headers={'User-Agent': UA}, timeout=180)
    r.raise_for_status()
    logger.info(f'Завантажено {len(r.content) / 1e6:.1f} МБ')
    return r.content


def parse(blob: bytes) -> list:
    root = ET.parse(io.BytesIO(blob)).getroot()
    rows = []
    for o in root.findall('.//offer'):
        sku = (o.findtext('vendorCode') or o.get('id') or '').strip()
        if not sku:
            continue
        name = (o.findtext('name') or '').strip()
        desc = (o.findtext('description') or '').strip()
        # Позначаємо, чи текст справді російський: у частини позицій
        # постачальник і в «російському» фіді лишив українську.
        is_ru = bool(name) and not UA_LETTERS.search(name)
        rows.append((sku, name, desc, is_ru))
    return rows


def cmd_report(cur):
    cur.execute("""SELECT count(*) n,
                          count(*) FILTER (WHERE is_ru) ru,
                          count(*) FILTER (WHERE description_ru <> '') d,
                          max(fetched_at) at
                   FROM sexopt_products_ru""")
    r = cur.fetchone()
    print(f"позицій: {r['n']} | справді російських назв: {r['ru']} | "
          f"з описом: {r['d']} | оновлено: {r['at']}")
    cur.execute("""SELECT p.sku FROM sexopt_products p
                   LEFT JOIN sexopt_products_ru r ON r.sku = p.sku
                   WHERE r.sku IS NULL LIMIT 5""")
    miss = [x['sku'] for x in cur.fetchall()]
    print(f"наших SKU без RU-відповідника: {'немає' if not miss else miss}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure_table(cur)
    conn.commit()

    if a.report:
        cmd_report(cur)
    else:
        rows = parse(fetch(RU_FEED))
        logger.info(f'Розібрано позицій: {len(rows)}')
        psycopg2.extras.execute_values(cur, """
            INSERT INTO sexopt_products_ru (sku, name_ru, description_ru, is_ru)
            VALUES %s
            ON CONFLICT (sku) DO UPDATE SET
              name_ru=EXCLUDED.name_ru,
              description_ru=EXCLUDED.description_ru,
              is_ru=EXCLUDED.is_ru, fetched_at=NOW()
        """, rows, page_size=500)
        conn.commit()
        logger.success(f'Записано {len(rows)} позицій')
        cmd_report(cur)
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
