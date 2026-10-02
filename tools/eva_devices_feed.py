#!/usr/bin/env python3
"""Фід EVA з девайсами: будується з бази постачальника, а не з прайсу косметики.

Косметичний фід (`eva_build_items.py`) читає xls SMTM і покриває лише
косметику. Девайси — вібратори, мастурбатори, БДСМ, костюми — живуть у
`sexopt_products`, і категорії для них узято з живого довідника EVA
(`content/eva_device_map.py`).

Стоп-бренди й стоп-країни EVA застосовуються так само, як у косметичному фіді.

    python3 tools/eva_devices_feed.py -o output/eva_devices.xml
"""
import argparse
import datetime
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

import psycopg2
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))
from content.eva_feed import build_feed            # noqa: E402
from content.eva_device_map import MAP             # noqa: E402

SHOP = ('klatch1 shop', '3721108', 'https://cs4053918.prom.ua/')


def https(url):
    return re.sub(r'^http://', 'https://', (url or '').strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--out', default=os.path.join(BASE, 'output', 'eva_devices.xml'))
    ap.add_argument('--items', default=os.path.join(BASE, 'exports', 'eva_feed_items_devices.json'))
    a = ap.parse_args()

    cats = json.load(open(os.path.join(BASE, 'exports', 'eva_categories_20260925.json'),
                          encoding='utf-8'))
    stop_brands = set()
    for lst in cats['stop_brands'].values():
        stop_brands.update(b.strip().lower() for b in lst)
    stop_countries = {c.strip().lower() for c in cats.get('stop_countries', [])}

    conn = psycopg2.connect(host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT'),
                            dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
                            password=os.getenv('DB_PASSWORD'), connect_timeout=15)
    cur = conn.cursor()
    cur.execute("""
        select p.sku, p.name, p.description_html, p.price_retail, p.quantity,
               p.vendor, p.pictures, p.country, m.epicentr_category_code,
               r.name_ru, r.description_ru
          from sexopt_products p
          join prom_source_category_mapping m
            on m.sexopt_category_id::text = p.category_id::text
          left join sexopt_products_ru r on r.sku = p.sku
         where p.available and m.epicentr_category_code::text = any(%s)
    """, (list(MAP),))

    items, skipped = [], {'стоп-бренд': 0, 'стоп-країна': 0, 'без фото': 0, 'без ціни': 0}
    for (sku, name, desc, price, qty, vendor, pics, country, code,
         name_ru, desc_ru) in cur.fetchall():
        brand = re.sub(r'\s*\([^)]*\)\s*$', '', vendor or '').strip()
        if brand.lower() in stop_brands:
            skipped['стоп-бренд'] += 1
            continue
        if (country or '').strip().lower() in stop_countries:
            skipped['стоп-країна'] += 1
            continue
        photos = [https(p) for p in (pics or []) if p]
        if not photos:
            skipped['без фото'] += 1
            continue
        if not price or float(price) <= 0:
            skipped['без ціни'] += 1
            continue
        eva_id, _ = MAP[str(code)]
        params = {}
        if country:
            params['Країна виробництва'] = country
        items.append({'sku': sku, 'name_ru': (name_ru or name), 'name_ua': name,
                      'price': float(price), 'qty': float(qty or 0),
                      'vendor': brand or 'NOIRE', 'category_id': eva_id,
                      'pictures': photos[:10],
                      'description_ru': (desc_ru or desc or ''),
                      'description_ua': (desc or ''), 'params': params})

    used = sorted({i['category_id'] for i in items})
    names = {}
    for code, (eva_id, title) in MAP.items():
        names[eva_id] = title
    categories = {c: names[c] for c in used}

    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    xml, dropped = build_feed(items, categories, shop_name=SHOP[0], shop_company=SHOP[1],
                              shop_url=SHOP[2], now=now, return_skipped=True)
    print(f'товарів: {len(items)} · категорій: {len(categories)}')
    print('пропущено:', skipped, '· без категорії:', len(dropped))
    open(a.out, 'w', encoding='utf-8').write(xml)
    ET.fromstring(xml)
    json.dump(items, open(a.items, 'w', encoding='utf-8'), ensure_ascii=False)
    print('записано:', a.out, os.path.getsize(a.out), 'байт · XML валідний')


if __name__ == '__main__':
    main()
