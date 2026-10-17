#!/usr/bin/env python3
"""TOPTUL: чи можна продавати хоч щось — з урахуванням цінових порогів комісії.

ЩО НОВОГО ПРОТИ `toptul_margin.py`. Там комісія бралась як один відсоток
на товар. Насправді в категорії «Інструменти й обладнання» ставка падає
сходинками: 18 % базово, 10 % від 5000 грн, 7 % від 10000, 5 % від 20000.
Тобто підняття ціни може не лише додати виручки, а й зменшити комісію —
лінійна формула цього не бачить і завищує потрібну ціну.

    закупівля Z = РРЦ × 0.88        (знижка TOPTUL 12 %, з накладних)
    комісія  C(P) = P × ставка(P)/100 × 1.08
    маржа    M(P) = P − Z − C(P) − 35

Шукаємо найменшу ціну, за якої маржа ≥ порогу, перебираючи сходинки.

    venv/bin/python tools/toptul_margin_bands.py --маржа 40
"""
import argparse
import csv
import glob
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from tools.rozetka_tariffs import ставка as тариф_ставка, OUT as ТАРИФИ  # noqa
from tools.toptul_margin import прайс, ЗНИЖКА                            # noqa

КОМ = os.path.join(BASE, 'data', 'rozetka_commissions.json')
OUT = os.path.join(BASE, 'exports', 'toptul_маржа_пороги.csv')
ДОСТАВКА, КОЕФ = 35.0, 1.08


def число(x):
    """'2 418.07' → 2418.07. Rozetka розділяє тисячі нерозривним пробілом,
    і прямий float() на таких сумах падає."""
    return float(str(x).replace('\xa0', '').replace(' ', '').replace(',', '.') or 0)


def мінімальна_ціна(сітка, cid, z, бренд, поріг):
    """Найменша ціна з маржею ≥ поріг. Перебираємо сходинки, бо ставка
    залежить від самої ціни — пряма формула дає відповідь лише в межах
    однієї сходинки."""
    межі = [0]
    зап = сітка.get(str(cid)) or {}
    for p in зап.get('правила', []):
        m = re.match(r'\s*(\d+)\s*-', p['діапазон'] or '')
        if m:
            межі.append(float(m.group(1)))
    межі = sorted(set(межі))
    найкраща = None
    for i, низ in enumerate(межі):
        верх = межі[i + 1] - 0.01 if i + 1 < len(межі) else 10 ** 9
        проба = max(низ, 1)
        с, _ = тариф_ставка(сітка, cid, проба, бренд)
        if с is None:
            continue
        дільник = 1 - с * КОЕФ / 100
        if дільник <= 0:
            continue
        p = (z + ДОСТАВКА + поріг) / дільник
        if низ <= p <= верх and (найкраща is None or p < найкраща[0]):
            найкраща = (p, с)
    return найкраща


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--маржа', type=float, default=40.0)
    a = ap.parse_args()
    сітка = json.load(open(ТАРИФИ, encoding='utf-8'))
    п = прайс()
    ком = json.load(open(КОМ, encoding='utf-8'))
    рядки = []
    for it in ком:
        арт = (it.get('item_article') or '').strip()
        дані = п.get(арт)
        if not дані:
            continue
        бренд, ррц = дані
        if бренд not in ЗНИЖКА or not ррц:
            continue
        z = ррц * (1 - ЗНИЖКА[бренд])
        cid = it.get('catalog_id')
        ціна_зараз = число(it['item_price'])
        сума_зараз = число(it['commission_sum'])
        маржа_зараз = ціна_зараз - z - сума_зараз - ДОСТАВКА
        рез = мінімальна_ціна(сітка, cid, z, бренд, a.маржа)
        рядки.append({
            'артикул': арт, 'назва': (it.get('item_name') or '')[:60],
            'категорія': it.get('catalog_name'), 'закупівля': round(z, 2),
            'ррц_постачальника': ррц, 'ціна_зараз': ціна_зараз,
            'ставка_зараз_%': it.get('commission'),
            'маржа_зараз': round(маржа_зараз, 2),
            'мін_ціна_для_маржі': round(рез[0], 2) if рез else '',
            'ставка_на_тій_ціні_%': рез[1] if рез else '',
            'підняти_%': round((рез[0] / ціна_зараз - 1) * 100, 1) if рез and ціна_зараз else ''})
    рядки.sort(key=lambda r: -(r['маржа_зараз']))
    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(рядки[0])); w.writeheader(); w.writerows(рядки)
    добрі = [r for r in рядки if r['маржа_зараз'] >= a.маржа]
    можливі = [r for r in рядки if r['мін_ціна_для_маржі'] != '']
    до_ррц = [r for r in можливі if r['мін_ціна_для_маржі'] <= r['ррц_постачальника']]
    print(f'позицій TOPTUL: {len(рядки)}')
    print(f'  прибуткові вже зараз (маржа >= {a.маржа:.0f}): {len(добрі)}')
    print(f'  мають досяжну ціну для маржі: {len(можливі)}')
    print(f'  де потрібна ціна НЕ ВИЩА за РРЦ постачальника: {len(до_ррц)}')
    print(f'\n{"артикул":12} {"зараз":>8} {"закуп":>8} {"маржа":>8} {"треба":>9} {"ставка":>7}')
    for r in добрі[:6] + [x for x in можливі if x not in добрі][:6]:
        print(f"{r['артикул'][:12]:12} {r['ціна_зараз']:8.0f} {r['закупівля']:8.0f} "
              f"{r['маржа_зараз']:8.0f} {str(r['мін_ціна_для_маржі']):>9} "
              f"{str(r['ставка_на_тій_ціні_%']):>7}")
    print(f'\n→ {OUT}')


if __name__ == '__main__':
    main()
