#!/usr/bin/env python3
"""Тарифна сітка Rozetka з кабінету → довідник комісій.

Файл качається в кабінеті: «Мій баланс» → «Історія тарифів». Колонки:
    ID категорії · Категорія · Бренд · Діапазон цін · Відсоток комісії

Три тонкощі, через які не можна брати просто «відсоток по категорії»:

1. БРЕНД. Для частини категорій є окрема ставка на бренд («Oculus 10 %»
   проти 22 % загальних). Шукаємо спершу точний бренд, потім «-».
2. ЦІНОВИЙ ДІАПАЗОН. У більшості категорій ставка залежить від ціни
   товару («3000-9999 → 20 %»). Діапазон застосовується до ціни ОДНОГО
   товару, не до суми замовлення.
3. УСПАДКУВАННЯ. Якщо для кінцевої категорії ставки немає, діє ставка
   батьківської — так каже довідка Rozetka. Батьків беремо з API
   `/market-categories/search`.

До суми комісії застосовується множник 1.08: ПДВ 20 % нараховується на
40 % тарифу (офіційна довідка; збіг із фактом на 9564 товарах).

    venv/bin/python tools/rozetka_tariffs.py --файл ~/Завантажене/tarif/...xlsx
    venv/bin/python tools/rozetka_tariffs.py --ставка 4626670 --ціна 500
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'data', 'rozetka_tariffs.json')
КОЕФ = 1.08


def зчитати(шлях):
    import openpyxl
    wb = openpyxl.load_workbook(шлях, read_only=True, data_only=True)
    ws = wb['Тариф']
    сітка, cid, назва = {}, None, None
    for row in ws.iter_rows(min_row=2, values_only=True):
        c, к, бренд, діап, відс = (list(row) + [None] * 5)[:5]
        if c:
            cid, назва = str(c).strip(), str(к or '').strip()
        if not cid or відс in (None, ''):
            continue
        зап = сітка.setdefault(cid, {'назва': назва, 'правила': []})
        зап['правила'].append({'бренд': (str(бренд).strip() if бренд else '-'),
                               'діапазон': (str(діап).strip() if діап else '-'),
                               'відсоток': float(str(відс).replace(',', '.'))})
    return сітка


def у_діапазоні(діап, ціна):
    if діап in ('-', '', None):
        return True
    m = re.match(r'\s*(\d+)\s*-\s*(\d+)', діап)
    if m:
        return float(m.group(1)) <= ціна <= float(m.group(2))
    m = re.match(r'\s*(?:від|from)?\s*(\d+)\s*\+?\s*$', діап)
    return float(m.group(1)) <= ціна if m else True


БАТЬКИ = os.path.join(BASE, 'data', 'rozetka_category_parents.json')


def батько(cid, кеш=None):
    """parent_id категорії з API Rozetka, з файловим кешем."""
    кеш = кеш if кеш is not None else _кеш_батьків()
    if str(cid) in кеш:
        return кеш[str(cid)]
    import requests
    sys.path.insert(0, BASE)
    from agents.orders import rozetka_order_agent as RZ
    r = requests.get('https://api-seller.rozetka.com.ua/market-categories/search',
                     headers={'Authorization': f'Bearer {RZ.get_token()}',
                              'Accept': 'application/json'},
                     params={'id': cid}, timeout=40)
    m = ((r.json().get('content') or {}).get('marketCategorys') or [{}])[0]
    кеш[str(cid)] = m.get('parent_id')
    with open(БАТЬКИ, 'w', encoding='utf-8') as f:
        json.dump(кеш, f, ensure_ascii=False)
    return кеш[str(cid)]


def _кеш_батьків():
    return json.load(open(БАТЬКИ, encoding='utf-8')) if os.path.exists(БАТЬКИ) else {}


def ставка(сітка, cid, ціна, бренд=None, вгору=True):
    """→ (відсоток, пояснення) або (None, причина).

    Якщо для кінцевої категорії правила немає — піднімаємось до
    батьківської. Так каже довідка Rozetka, і без цього більшість
    категорій лишається без ставки: у сітці 335 категорій, а в каталозі
    їх тисячі.
    """
    кеш = _кеш_батьків()
    поточна, шлях = str(cid), []
    for _ in range(8):
        відс, чому = _ставка_в_категорії(сітка, поточна, ціна, бренд)
        if відс is not None:
            хвіст = (' ← ' + ' ← '.join(шлях)) if шлях else ''
            return відс, чому + хвіст
        if not вгору:
            break
        шлях.append(поточна)
        p = батько(поточна, кеш)
        if not p:
            break
        поточна = str(p)
    return None, 'ставки немає ні в категорії, ні в батьківських'


def _ставка_в_категорії(сітка, cid, ціна, бренд=None):
    зап = сітка.get(str(cid))
    if not зап:
        return None, 'категорії немає в тарифній сітці'
    for шукаємо in ([бренд] if бренд else []) + ['-']:
        правила = [p for p in зап['правила']
                   if p['бренд'].lower() == str(шукаємо).lower()]
        точні = [p for p in правила if p['діапазон'] not in ('-', '')
                 and у_діапазоні(p['діапазон'], ціна)]
        if точні:
            p = точні[0]
            return p['відсоток'], f"{зап['назва']} · бренд {p['бренд']} · {p['діапазон']}"
        загальні = [p for p in правила if p['діапазон'] in ('-', '')]
        if загальні:
            p = загальні[0]
            return p['відсоток'], f"{зап['назва']} · бренд {p['бренд']} · без діапазону"
    return None, 'у категорії немає придатного правила'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--файл')
    ap.add_argument('--ставка', dest='ставка_для')
    ap.add_argument('--ціна', type=float, default=0)
    ap.add_argument('--бренд')
    a = ap.parse_args()
    if a.файл:
        сітка = зчитати(os.path.expanduser(a.файл))
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(сітка, f, ensure_ascii=False)
        правил = sum(len(v['правила']) for v in сітка.values())
        print(f'категорій у сітці: {len(сітка)} · правил: {правил} → {OUT}')
        з_діапазонами = sum(1 for v in сітka.values()
                            for p in v['правила'] if p['діапазон'] not in ('-', '')) \
            if False else sum(1 for v in сітка.values()
                              for p in v['правила'] if p['діапазон'] not in ('-', ''))
        з_брендом = sum(1 for v in сітка.values()
                        for p in v['правила'] if p['бренд'] != '-')
        print(f'  правил із ціновим діапазоном: {з_діапазонами}')
        print(f'  правил із окремим брендом: {з_брендом}')
        return
    if a.ставка_для:
        сітка = json.load(open(OUT, encoding='utf-8'))
        с, чому = ставка(сітка, a.ставка_для, a.ціна, a.бренд)
        print(f'ставка: {с}% · {чому}')
        if с:
            print(f'комісія з ціни {a.ціна:.0f}: {a.ціна * с / 100 * КОЕФ:.2f} грн '
                  f'(з коефіцієнтом 1.08)')


if __name__ == '__main__':
    main()
