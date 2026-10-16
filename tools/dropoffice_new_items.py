#!/usr/bin/env python3
"""Товари dropoffice, яких ми ще НЕ продаємо на Rozetka, з розрахунком маржі.

З 1358 позицій прайсу на Rozetka стоять 894. Решта — те, що можна завести.
Для кожної рахуємо, за якою ціною її варто ставити, щоб маржа була не
меншою за поріг, і чи витримує це РРЦ постачальника.

Ставку комісії беремо з уже відомих позицій ТІЄЇ Ж категорії прайсу; якщо
категорія нова — медіану по всьому магазину. Це оцінка, а не факт, тому в
файлі є колонка «ставка_звідки».

    venv/bin/python tools/dropoffice_new_items.py --прайс /шлях/price.xlsx
"""
import argparse
import collections
import csv
import json
import os
import statistics as st
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from tools.dropoffice_margin import прайс, число, ДОСТАВКА, КОЕФ   # noqa: E402

КОМ = os.path.join(BASE, 'data', 'rozetka_commissions.json')
OUT = os.path.join(BASE, 'exports', 'dropoffice_нові_позиції.csv')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--прайс', required=True)
    ap.add_argument('--маржа', type=float, default=40.0)
    a = ap.parse_args()
    п = прайс(a.прайс)
    ком = {(x.get('item_article') or '').strip(): x
           for x in json.load(open(КОМ, encoding='utf-8'))}

    # ставка комісії за категорією прайсу — з позицій, які вже продаються
    по_кат = collections.defaultdict(list)
    усі = []
    for арт, д in п.items():
        it = ком.get(арт)
        if it:
            с = число(it['commission'])
            по_кат[д['категорія']].append(с)
            усі.append(с)
    медіана_всіх = st.median(усі) if усі else 15.0

    рядки = []
    for арт, д in п.items():
        if арт in ком or not д['закупівля']:
            continue
        у_кат = по_кат.get(д['категорія'])
        ставка = st.median(у_кат) if у_кат else медіана_всіх
        звідки = f'категорія ({len(у_кат)} позицій)' if у_кат else 'медіана магазину'
        дільник = 1 - ставка * КОЕФ / 100
        потрібна = (д['закупівля'] + ДОСТАВКА + a.маржа) / дільник if дільник > 0 else 0
        маржа_за_ррц = (д['ррц'] - д['закупівля'] - д['ррц'] * ставка * КОЕФ / 100
                        - ДОСТАВКА) if д['ррц'] else None
        рядки.append({
            'артикул': арт, 'назва': д['назва'], 'категорія': д['категорія'],
            'наявність': д['наявність'], 'закупівля': д['закупівля'],
            'ррц_постачальника': д['ррц'], 'ставка_%': round(ставка, 1),
            'ставка_звідки': звідки,
            f'ціна_для_{int(a.маржа)}': round(потрібна, 2),
            'маржа_якщо_за_ррц': round(маржа_за_ррц, 2) if маржа_за_ррц is not None else '',
            'ррц_вистачає': 'так' if (маржа_за_ррц or 0) >= a.маржа else 'ні'})
    рядки.sort(key=lambda r: -(r['маржа_якщо_за_ррц'] or 0))
    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(рядки[0]))
        w.writeheader(); w.writerows(рядки)
    добрі = [r for r in рядки if r['ррц_вистачає'] == 'так']
    print(f'позицій прайсу, яких немає на Rozetka: {len(рядки)}')
    print(f'  де РРЦ постачальника дає маржу >= {a.маржа:.0f}: {len(добрі)} '
          f'({len(добрі)*100//max(len(рядки),1)}%)')
    print(f'  сумарна маржа по них: {sum(r["маржа_якщо_за_ррц"] for r in добрі):,.0f} грн'.replace(',', ' '))
    print(f'\n{"артикул":16} {"закуп":>7} {"ррц":>7} {"маржа@ррц":>10}  назва')
    for r in добрі[:10]:
        print(f"{r['артикул'][:16]:16} {r['закупівля']:7.0f} {r['ррц_постачальника']:7.0f} "
              f"{r['маржа_якщо_за_ррц']:10.2f}  {r['назва'][:36]}")
    print(f'\n→ {OUT}')


if __name__ == '__main__':
    main()
