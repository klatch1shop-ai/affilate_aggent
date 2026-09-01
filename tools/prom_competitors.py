#!/usr/bin/env python3
"""Реєстр прямих конкурентів і порівняння з ними.

Замір дублів описів (`prom_dup_check.py`) виявив те, що робить цей реєстр
особливо цінним: конкуренти, чиї картки збігаються з нашими на 86-100%, —
це **дропшипери того самого постачальника SexOpt**. Товар ідентичний,
закупівельна ціна теж (у нас вона тепер відома — `sexopt_dropship_price`).

Отже різницю робить виключно те, що ми контролюємо: ціна, опис, кількість
фото, характеристики, позиція у видачі. Це рідкісна ситуація — порівняння
без сторонніх змінних.

Що дає реєстр:
  • **ціновий орієнтир.** Ми знаємо свою закупівлю й мінімальний роздріб.
    Побачивши ціни конкурентів на ті самі артикули, знаємо, де маємо запас,
    а де продаємо дорожче за ринок.
  • **контентний орієнтир.** Довжина опису, кількість фото, кількість
    характеристик — усе видно на їхніх картках. Ціль не «зробити добре», а
    «зробити краще за конкретного продавця з конкретними числами».
  • **хто нас обходить.** Той самий товар, той самий постачальник — якщо
    вони стоять вище, причина в рейтингу, ProSale або контенті, і це
    вимірюється.

Запуск:
    python3 tools/prom_competitors.py --collect     # із звіту про дублі
    python3 tools/prom_competitors.py --compare     # порівняння по позиціях
    python3 tools/prom_competitors.py --report
"""
import argparse
import collections
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

import psycopg2.extras

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
from shared.utils.db import get_connection  # noqa: E402

REPORT = os.path.join(BASE_DIR, 'docs', 'prom_duplicate_report.json')
FEED = os.path.join(BASE_DIR, 'output', 'noire_prom.xml')


def ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS prom_competitors (
        seller      TEXT PRIMARY KEY,
        shop_url    TEXT,
        products_seen INTEGER DEFAULT 0,
        avg_overlap NUMERIC,
        first_seen  TIMESTAMPTZ DEFAULT NOW(),
        note        TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS prom_competitor_offers (
        seller     TEXT NOT NULL,
        sku        TEXT NOT NULL,
        url        TEXT,
        price      NUMERIC,
        desc_len   INTEGER,
        overlap    NUMERIC,
        similarity NUMERIC,
        checked_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (seller, sku))""")


def shop_of(url: str) -> str:
    m = re.match(r'https?://([\w\-]+)\.prom\.ua', url or '')
    return f'https://{m.group(1)}.prom.ua' if m else ''


def collect(cur, conn):
    data = json.load(open(REPORT, encoding='utf-8'))
    # Один продавець може трапитись двічі на тому самому артикулі (різні
    # картки того самого товару) — беремо кращий збіг, інакше вставка падає
    # на дублях первинного ключа.
    best, sellers = {}, collections.defaultdict(list)
    for r in data:
        for c in r['competitors']:
            key = (c['seller'], r['sku'])
            prev = best.get(key)
            if prev is None or c['overlap'] > prev[5]:
                best[key] = (c['seller'], r['sku'], c['url'], None,
                             len(c['desc']), c['overlap'], c.get('similarity'))
            sellers[c['seller']].append((c['overlap'], c['url']))
    offers = list(best.values())
    psycopg2.extras.execute_values(cur, """
        INSERT INTO prom_competitor_offers
          (seller, sku, url, price, desc_len, overlap, similarity)
        VALUES %s ON CONFLICT (seller, sku) DO UPDATE SET
          overlap=EXCLUDED.overlap, similarity=EXCLUDED.similarity,
          desc_len=EXCLUDED.desc_len, checked_at=NOW()""", offers)
    rows = [(s, shop_of(v[0][1]), len(v),
             round(sum(x for x, _ in v) / len(v), 1), None)
            for s, v in sellers.items()]
    psycopg2.extras.execute_values(cur, """
        INSERT INTO prom_competitors
          (seller, shop_url, products_seen, avg_overlap, note)
        VALUES %s ON CONFLICT (seller) DO UPDATE SET
          products_seen=EXCLUDED.products_seen,
          avg_overlap=EXCLUDED.avg_overlap,
          shop_url=COALESCE(EXCLUDED.shop_url, prom_competitors.shop_url)""",
        rows)
    conn.commit()
    print(f'продавців: {len(rows)}, їхніх карток: {len(offers)}')


def compare(cur):
    """Наш контент проти конкурентів на тих самих артикулах."""
    root = ET.parse(FEED).getroot()
    ours = {}
    for o in root.findall('.//offer'):
        ours[o.findtext('vendorCode')] = {
            'desc': len(re.sub('<[^>]+>', '', o.findtext('description_ua') or '')),
            'pics': len(o.findall('picture')),
            'params': len(o.findall('param')),
            'price': float(o.findtext('price') or 0)}
    cur.execute("""SELECT sku, count(*) n, round(avg(desc_len)) d,
                          round(avg(overlap), 1) ov
                   FROM prom_competitor_offers GROUP BY sku ORDER BY sku""")
    print(f"{'SKU':10} {'наш опис':>9} {'їхній':>7} {'фото':>5} "
          f"{'характ.':>8} {'збіг':>6}")
    tot_d = tot_t = 0
    for r in cur.fetchall():
        o = ours.get(r['sku'])
        if not o:
            continue
        tot_d += o['desc']
        tot_t += r['d'] or 0
        print(f"{r['sku']:10} {o['desc']:9} {int(r['d'] or 0):7} "
              f"{o['pics']:5} {o['params']:8} {r['ov']:6}")
    print(f'\nсередня довжина опису: наша {tot_d // 18}, конкурентів {tot_t // 18}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--collect', action='store_true')
    ap.add_argument('--compare', action='store_true')
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()

    if a.collect:
        collect(cur, conn)
    if a.compare:
        compare(cur)
    if a.report or not (a.collect or a.compare):
        cur.execute("""SELECT seller, shop_url, products_seen, avg_overlap
                       FROM prom_competitors ORDER BY products_seen DESC""")
        for r in cur.fetchall():
            print(f"   {r['products_seen']:3} карток | збіг {r['avg_overlap']:5}% | "
                  f"{r['seller'][:30]:32} {r['shop_url'] or ''}")
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
