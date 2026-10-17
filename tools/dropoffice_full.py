#!/usr/bin/env python3
"""dropoffice: повний розбір прайсу — що прибуткове, що ні, і за якою ціною.

УМОВИ, станом на 17.10.2026:
  * доставка нам НЕ коштує: «Доставка в магазини ROZETKA» (35 грн з
    продавця) НЕ активована, Новою Поштою платить покупець;
  * комісія = ціна × ставка/100 × 1.08 (ПДВ 20 % на 40 % тарифу).

ЗВІДКИ СТАВКА, за спаданням надійності:
  1. товар уже продається — беремо ФАКТИЧНУ суму комісії з
     `/items-commissions/search`;
  2. товар ще не заведено — ставка з офіційної тарифної сітки за
     категорією Rozetka, яку ми знаємо для СУСІДІВ цього товару по
     категорії постачальника (більшість у групі);
  3. якщо сусідів немає — позиція лишається без оцінки, а не з вигаданою.

    venv/bin/python tools/dropoffice_full.py --прайс ~/Завантажене/price.xlsx --маржа 40
"""
import argparse
import collections
import csv
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from tools.dropoffice_margin import прайс, число          # noqa: E402
from tools.rozetka_tariffs import ставка as тариф_ставка, OUT as ТАРИФИ  # noqa

КОМ = os.path.join(BASE, 'data', 'rozetka_commissions.json')
OUT = os.path.join(BASE, 'exports', 'dropoffice_повний.csv')
КОЕФ = 1.08
ДОСТАВКА = 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--прайс', required=True)
    ap.add_argument('--маржа', type=float, default=40.0)
    a = ap.parse_args()
    п = прайс(os.path.expanduser(a.прайс))
    ком = {(x.get('item_article') or '').strip(): x
           for x in json.load(open(КОМ, encoding='utf-8'))}
    сітка = json.load(open(ТАРИФИ, encoding='utf-8')) if os.path.exists(ТАРИФИ) else {}

    # категорія постачальника → найчастіша категорія Rozetka серед заведених
    по_групі = collections.defaultdict(collections.Counter)
    for арт, д in п.items():
        it = ком.get(арт)
        if it and it.get('catalog_id'):
            по_групі[д['категорія']][int(it['catalog_id'])] += 1
    здогад = {г: c.most_common(1)[0][0] for г, c in по_групі.items() if c}

    рядки, без_оцінки = [], 0
    for арт, д in п.items():
        if not д['закупівля']:
            continue
        it = ком.get(арт)
        якщо_заведено = bool(it)
        if якщо_заведено:
            ціна = число(it['item_price'])
            сума = число(it['commission_sum'])
            ставка = число(it['commission'])
            джерело = 'факт: товар продається'
            cid = it.get('catalog_id')
        else:
            ціна = д['ррц'] or 0
            cid = здогад.get(д['категорія'])
            if not (ціна and cid and сітка):
                без_оцінки += 1
                continue
            ставка, _ = тариф_ставка(сітка, cid, ціна)
            if ставка is None:
                без_оцінки += 1
                continue
            сума = ціна * ставка / 100 * КОЕФ
            джерело = f'тариф за категорією {cid} (сусіди в групі)'
        маржа = ціна - д['закупівля'] - сума - ДОСТАВКА
        дільник = 1 - ставка * КОЕФ / 100
        потрібна = ((д['закупівля'] + ДОСТАВКА + a.маржа) / дільник) if дільник > 0 else 0
        рядки.append({
            'артикул': арт, 'назва': д['назва'], 'група_постачальника': д['категорія'],
            'заведено_на_rozetka': 'так' if якщо_заведено else 'ні',
            'закупівля': д['закупівля'], 'ррц_постачальника': д['ррц'],
            'ціна': round(ціна, 2), 'ставка_%': ставка, 'комісія': round(сума, 2),
            'маржа': round(маржа, 2),
            f'ціна_для_{int(a.маржа)}': round(потрібна, 2),
            'ррц_вистачає': 'так' if потрібна <= (д['ррц'] or 0) else 'ні',
            'наявність': д['наявність'], 'звідки_ставка': джерело})
    рядки.sort(key=lambda r: -r['маржа'])
    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(рядки[0])); w.writeheader(); w.writerows(рядки)

    добрі = [r for r in рядки if r['маржа'] >= a.маржа]
    збиток = [r for r in рядки if r['маржа'] < 0]
    лік = [r for r in збиток if r['ррц_вистачає'] == 'так']
    заведені = [r for r in рядки if r['заведено_на_rozetka'] == 'так']
    нові = [r for r in рядки if r['заведено_на_rozetka'] == 'ні']
    print(f'позицій у прайсі: {len(п)} · оцінено: {len(рядки)} · без оцінки: {без_оцінки}')
    print(f'  уже на Rozetka: {len(заведені)} · ще не заведені: {len(нові)}')
    print(f'\nмаржа >= {a.маржа:.0f} грн: {len(добрі)} ({len(добрі)*100//len(рядки)}%)')
    print(f'  з них уже продаються: {sum(1 for r in добрі if r["заведено_на_rozetka"] == "так")}')
    print(f'  з них ще не заведені: {sum(1 for r in добрі if r["заведено_на_rozetka"] == "ні")}')
    print(f'у збиток: {len(збиток)} · з них лікуються ціною в межах РРЦ: {len(лік)}')
    print(f'сумарна маржа по прибуткових: {sum(r["маржа"] for r in добрі):,.0f} грн'.replace(',', ' '))
    print(f'\n{"артикул":16} {"ціна":>7} {"закуп":>7} {"ком%":>5} {"маржа":>8}  назва')
    for r in добрі[:10]:
        print(f"{r['артикул'][:16]:16} {r['ціна']:7.0f} {r['закупівля']:7.0f} "
              f"{r['ставка_%']:5.0f} {r['маржа']:8.0f}  {r['назва'][:36]}")
    print(f'\n→ {OUT}')


if __name__ == '__main__':
    main()
