#!/usr/bin/env python3
"""Генерує output/eva_cosmetics.xml із exports/eva_feed_items_20260925.json
(готує їх tools/eva_build_items.py) через content/eva_feed.py.

    python3 tools/eva_build_items.py       # спершу — нормалізує прайс
    python3 tools/eva_generate_feed.py     # потім — збирає XML
"""
import datetime
import json
import os
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from content.eva_feed import build_feed  # noqa: E402

CATEGORIES = {'100212': 'Крем для тіла'}   # фолбек-категорія; уточнюється з менеджером EVA
SHOP_NAME, SHOP_COMPANY, SHOP_URL = 'klatch1 shop', '3721108', 'https://cs4053918.prom.ua/'


def main():
    items = json.load(open(os.path.join(BASE, 'exports', 'eva_feed_items_20260925.json'),
                           encoding='utf-8'))
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    xml, skipped = build_feed(items, CATEGORIES, shop_name=SHOP_NAME, shop_company=SHOP_COMPANY,
                              shop_url=SHOP_URL, now=now, return_skipped=True)
    print('офферів у фіді:', xml.count('<offer '))
    print('пропущено (нема категорії):', len(skipped))

    out = os.path.join(BASE, 'output', 'eva_cosmetics.xml')
    open(out, 'w', encoding='utf-8').write(xml)
    ET.fromstring(xml)                  # кидає — якщо документ структурно невалідний
    print('записано:', out, os.path.getsize(out), 'байт · XML валідний')


if __name__ == '__main__':
    main()
