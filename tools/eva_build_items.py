#!/usr/bin/env python3
"""Нормалізує вигрузку SMTM-косметики у список товарів для фіду EVA.

Вхід: exports/eva_categories_20260925.json (стоп-бренди EVA) і сирий прайс
SMTM `/tmp/smtm_cosmetic.xls` (`https://smtm.com.ua/_prices/import-retail-cosmetic.xls`,
завантажується окремо, не лежить у git). Виключає позиції без залишку та
зі стоп-брендом EVA.

Пастка, на якій уже спіймався 25.09: колонка «Фото» розділяє кілька URL
через `;\n`, НЕ через кому — з комою половина фото зливається в один тег
<picture>, і EVA отримала б биту адресу замість кількох окремих.

    python3 tools/eva_build_items.py
"""
import json
import os
import re

import xlrd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XLS = '/tmp/smtm_cosmetic.xls'
OUT_ITEMS = os.path.join(BASE, 'exports', 'eva_feed_items_20260925.json')
OUT_SKIPPED = os.path.join(BASE, 'exports', 'eva_feed_skipped_stopbrand.json')
FALLBACK_CATEGORY = '100212'            # «Крем для тіла» — уточнюється з менеджером EVA


def main():
    cats = json.load(open(os.path.join(BASE, 'exports', 'eva_categories_20260925.json'),
                          encoding='utf-8'))
    stop_brands = set()
    for lst in cats['stop_brands'].values():
        stop_brands.update(b.strip().lower() for b in lst)

    wb = xlrd.open_workbook(XLS)
    ws = wb.sheet_by_index(0)
    headers = ws.row_values(0)
    idx = {h: i for i, h in enumerate(headers)}
    vol_col = idx["Об'єм (мл)"]

    items, skipped = [], []
    for i in range(1, ws.nrows):
        r = ws.row_values(i)
        sku = r[0]
        brand = re.sub(r'\s*\([^)]*\)\s*$', '', r[9] or '').strip()
        qty = r[2] or 0
        if not qty or float(qty) <= 0:
            continue
        if brand.lower() in stop_brands:
            skipped.append((sku, brand))
            continue
        photos = [p.strip() for p in (r[6] or '').replace('\n', '').split(';') if p.strip()]
        params = {}
        if r[idx['Косметика: вид']]:
            params['Косметика: вид'] = r[idx['Косметика: вид']]
        if r[idx['Косметика: дія']]:
            params['Косметика: дія'] = r[idx['Косметика: дія']]
        if r[vol_col]:
            params['Обʼєм'] = f'{r[vol_col]:g} мл'
        if r[idx['Країна надходження']]:
            params['Країна'] = r[idx['Країна надходження']]
        items.append({'sku': sku, 'name_ru': r[1], 'name_ua': r[1], 'price': float(r[3]),
                      'qty': float(qty), 'vendor': brand or 'NOIRE',
                      'category_id': FALLBACK_CATEGORY, 'pictures': photos,
                      'description_ru': r[5], 'description_ua': r[5], 'params': params})

    print(f'придатних позицій: {len(items)} · виключено (стоп-бренд): {len(skipped)}')
    print(f'без опису: {sum(1 for x in items if not x["description_ru"])} · '
          f'без параметрів: {sum(1 for x in items if not x["params"])}')
    json.dump(items, open(OUT_ITEMS, 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(skipped, open(OUT_SKIPPED, 'w', encoding='utf-8'), ensure_ascii=False)
    print('записано:', OUT_ITEMS)


if __name__ == '__main__':
    main()
