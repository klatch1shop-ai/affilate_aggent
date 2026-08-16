#!/usr/bin/env python3
"""Категорії, які Prom НАСПРАВДІ присвоїв нашим товарам.

Звіт імпорту 16.08.2026: «Для 949 товарів автоматично визначена категорія».
Порівняння фіду з відповіддю API показало 337 розбіжностей — Prom
перекласифікував товари сам.

Чому беремо його рішення за істину, а не наполягаємо на своєму: у довідці
«Як формується видача на маркетплейсі» сказано, що для каталогу ProSale
основний критерій — правильна категорія. Prom класифікує за власним
алгоритмом, дивлячись на назву й характеристики; наш мапінг іде через два
шари (sexopt → epicentr → prom) і на межових товарах помиляється.
Розбіжність означає, що товар лежить не там, де його шукатимуть.

Пише в prom_actual_category; генератор бере звідти portal_category_id,
якщо запис є.

Запуск:
    python3 tools/prom_actual_categories.py            # оновити з API
    python3 tools/prom_actual_categories.py --report
"""
import argparse
import collections
import os
import sys
import time

import psycopg2.extras
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
from shared.utils.db import get_connection  # noqa: E402

API = 'https://my.prom.ua/api/v1/products/list'


def ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS prom_actual_category (
        sku TEXT PRIMARY KEY,
        category_id TEXT NOT NULL,
        category_name TEXT,
        updated_at TIMESTAMPTZ DEFAULT NOW())""")


def fetch(token: str) -> list:
    head = {'Authorization': f'Bearer {token}'}
    out, last = [], 0
    while True:
        params = {'limit': 100}
        if last:
            params['last_id'] = last
        r = requests.get(API, headers=head, params=params, timeout=60)
        if r.status_code != 200:
            print(f'HTTP {r.status_code}: {r.text[:120]}')
            break
        ps = r.json().get('products') or []
        if not ps:
            break
        out += ps
        last = ps[-1]['id']
        time.sleep(0.3)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()

    if a.report:
        cur.execute("""SELECT category_name, count(*) c FROM prom_actual_category
                       GROUP BY category_name ORDER BY c DESC LIMIT 15""")
        for r in cur.fetchall():
            print(f"   {r['c']:5}  {r['category_name']}")
        return

    token = os.getenv('PROM_API_TOKEN')
    if not token:
        sys.exit('PROM_API_TOKEN не заданий у .env')
    products = fetch(token)
    rows = [(p.get('sku'), str((p.get('category') or {}).get('id') or ''),
             (p.get('category') or {}).get('caption'))
            for p in products
            if p.get('sku') and (p.get('category') or {}).get('id')]
    print(f'товарів з API: {len(products)}, із категорією: {len(rows)}')
    psycopg2.extras.execute_values(cur, """
        INSERT INTO prom_actual_category (sku, category_id, category_name)
        VALUES %s ON CONFLICT (sku) DO UPDATE SET
          category_id=EXCLUDED.category_id,
          category_name=EXCLUDED.category_name, updated_at=NOW()""", rows)
    conn.commit()
    top = collections.Counter(r[2] for r in rows)
    print('найбільші категорії за версією Prom:')
    for name, n in top.most_common(8):
        print(f'   {n:5}  {name}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
