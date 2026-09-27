#!/usr/bin/env python3
"""Генерує фід EVA із exports/eva_feed_items_<профіль>.json через content/eva_feed.py.

    python3 tools/eva_build_items.py   --profile cosmetics
    python3 tools/eva_generate_feed.py --profile cosmetics   # → output/eva_cosmetics.xml

Профілі: `cosmetics` — лише косметика, `full` — увесь асортимент.
Перелік категорій для тега <categories> будується з тих, що реально трапились
у товарах, а назви беруться з content/eva_category_rules.NAMES (слаги EVA
транслітеровані російською, у фід їх віддавати не можна).
"""
import argparse
import datetime
import json
import os
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from content.eva_feed import build_feed  # noqa: E402
from content.eva_category_rules import NAMES  # noqa: E402

SHOP_NAME, SHOP_COMPANY, SHOP_URL = 'klatch1 shop', '3721108', 'https://cs4053918.prom.ua/'
OUT_NAME = {'cosmetics': 'eva_cosmetics.xml', 'full': 'eva_full.xml'}


def main(profile='cosmetics'):
    items = json.load(open(os.path.join(BASE, 'exports', f'eva_feed_items_{profile}.json'),
                           encoding='utf-8'))
    used = sorted({i['category_id'] for i in items})
    missing = [c for c in used if c not in NAMES]
    if missing:
        raise SystemExit(f'немає української назви для категорій: {missing}')
    categories = {c: NAMES[c] for c in used}

    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    xml, skipped = build_feed(items, categories, shop_name=SHOP_NAME, shop_company=SHOP_COMPANY,
                              shop_url=SHOP_URL, now=now, return_skipped=True)
    print(f'профіль: {profile} · категорій: {len(categories)}')
    print('офферів у фіді:', xml.count('<offer '))
    print('пропущено (нема категорії):', len(skipped))

    out = os.path.join(BASE, 'output', OUT_NAME[profile])
    open(out, 'w', encoding='utf-8').write(xml)
    ET.fromstring(xml)                  # кидає — якщо документ структурно невалідний
    print('записано:', out, os.path.getsize(out), 'байт · XML валідний')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile', choices=['cosmetics', 'full'], default='cosmetics')
    main(ap.parse_args().profile)
