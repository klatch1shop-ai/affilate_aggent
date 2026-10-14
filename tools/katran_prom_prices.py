#!/usr/bin/env python3
"""Ціни конкурентів для кандидатів KATRAN через пошук Prom.

Пошуком у вебі ціни вбудованої техніки не знаходяться — приблизно
половина моделей не має сторінок у видачі. Але в системі вже є
`agents/scraper/market_price_analyzer.py`, який читає пошук Prom
браузером, і для тих самих моделей він ціни дає.

    venv/bin/python tools/katran_prom_prices.py --скільки 20

Пише в те саме сховище, що й `katran_competitors.py`, тому звіт і черга
бачать результати одразу. Джерело позначається `prom-пошук`, щоб було
видно, звідки число.
"""
import argparse
import csv
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from agents.scraper.market_price_analyzer import get_competitor_prices  # noqa

СХОВИЩЕ = os.path.join(BASE, 'data', 'katran_competitors.json')
КАНДИДАТИ = os.path.join(BASE, 'exports', 'katran_кандидати_старт.csv')
ФІД = next((p for p in (
    os.path.expanduser('~/noire-feed/katran_rozetka_pobutova.xml'),
    os.path.join(BASE, 'data', 'katran', 'katran_rozetka_pobutova.xml'),
) if os.path.exists(p)), '')


def товари():
    with open(ФІД, encoding='utf-8') as f:
        t = f.read()
    cats = dict(re.findall(r'<category id="(\d+)"[^>]*>([^<]+)</category>', t))
    out = {}
    for b in re.findall(r'<offer .*?</offer>', t, re.S):
        g = lambda k: (re.search(rf'<{k}>([^<]*)</{k}>', b) or [None, None])[1]
        a = (re.search(r'<offer id="([^"]+)"', b) or [None, None])[1]
        if a:
            out[a] = {'наша': float(g('price') or 0),
                      'назва': g('name_ua') or g('name'),
                      'категорія': cats.get(g('categoryId'), '')}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--скільки', type=int, default=20)
    ap.add_argument('--пауза', type=float, default=3.0)
    a = ap.parse_args()

    фід = товари()
    with open(КАНДИДАТИ, encoding='utf-8') as f:
        канд = {r['артикул']: r for r in csv.DictReader(f)}
    d = (json.load(open(СХОВИЩЕ, encoding='utf-8'))
         if os.path.exists(СХОВИЩЕ) else {})

    черга = [k for k in канд if k in фід
             and not d.get(k, {}).get('конкуренти')]
    черга.sort(key=lambda k: -float(канд[k]['маржа']))
    черга = черга[:a.скільки]
    print(f'у черзі {len(черга)} кандидатів')

    for i, арт in enumerate(черга, 1):
        закуп = float(канд[арт]['закуп_пдв'])
        try:
            r = get_competitor_prices(арт, закуп)
        except Exception as e:
            print(f'{i}/{len(черга)} {арт}: збій — {e}')
            continue
        ціни = r.get('prices') or []
        наша = фід[арт]['наша']
        if not ціни:
            d[арт] = {'наша': наша, 'назва': фід[арт]['назва'],
                      'категорія': фід[арт]['категорія'], 'конкуренти': [],
                      'мін_конкурент': None, 'різниця_%': None,
                      'не_знайдено': 'пошук Prom не дав цін',
                      'висновок': '', 'коли': time.strftime('%Y-%m-%d')}
            print(f'{i}/{len(черга)} {арт}: цін немає')
        else:
            мін = min(ціни)
            d[арт] = {
                'наша': наша, 'назва': фід[арт]['назва'],
                'категорія': фід[арт]['категорія'],
                'конкуренти': [{'ціна': c, 'джерело': 'prom-пошук'}
                               for c in ціни],
                'мін_конкурент': мін,
                'різниця_%': round((наша - мін) / мін * 100, 1),
                'медіана_конкурентів': r.get('median'),
                'скільки_пропозицій': r.get('count'),
                'висновок': (f"закупівля з ПДВ {закуп:.0f}; "
                             f"медіана ринку {r.get('median')}"),
                'коли': time.strftime('%Y-%m-%d')}
            print(f"{i}/{len(черга)} {арт}: наша {наша:.0f} · мін {мін} · "
                  f"медіана {r.get('median')} · пропозицій {r.get('count')}")
        tmp = СХОВИЩЕ + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, СХОВИЩЕ)
        time.sleep(a.пауза)


if __name__ == '__main__':
    main()
