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
import re as _re
from playwright.sync_api import sync_playwright


def ціни_з_назвами(артикул, timeout=45000):
    """Ціни лише з карток, у назві яких є артикул.

    Готовий `market_price_analyzer` бере ціни з УСІХ плиток сторінки
    пошуку, а Prom показує там і сусідні товари. Через це медіана
    виходила вища за РРЦ на 40 %: у вибірку потрапляли чужі товари, до
    74 тис. грн при РРЦ 21 тис. Тому звіряємо назву картки з артикулом.
    """
    ключ = _re.sub(r'[^0-9a-zа-яіїєґ]+', '', артикул.lower())
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page()
        try:
            page.goto(f'https://prom.ua/ua/search?search_term={артикул}',
                      wait_until='domcontentloaded', timeout=timeout)
            page.wait_for_timeout(3000)
            дані = page.evaluate('''() => {
                const out = [];
                document.querySelectorAll('[data-qaid="product_block"], .x-gallery-tile').forEach(el => {
                    const t = el.querySelector('[data-qaid="product_name"], [class*=name]');
                    const p = el.querySelector('[data-qaid="product_price"], [class*=price]');
                    if (t && p) out.push([t.innerText, p.innerText]);
                });
                return out;
            }''')
        finally:
            b.close()
    свої = []
    for назва, ціна in дані:
        n = _re.sub(r'[^0-9a-zа-яіїєґ]+', '', назва.lower())
        if ключ and ключ in n:
            м = _re.findall(r'\d[\d\s]*', ціна.replace('\u00a0', ' '))
            if м:
                свої.append(int(м[0].replace(' ', '')))
    return sorted(свої)

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
            ціни = ціни_з_назвами(арт)
        except Exception as e:
            print(f'{i}/{len(черга)} {арт}: збій — {e}')
            continue
        наша = фід[арт]['наша']
        if not ціни:
            d[арт] = {'наша': наша, 'назва': фід[арт]['назва'],
                      'категорія': фід[арт]['категорія'], 'конкуренти': [],
                      'мін_конкурент': None, 'різниця_%': None,
                      'не_знайдено': 'на Промі немає карток із цим артикулом',
                      'висновок': '', 'коли': time.strftime('%Y-%m-%d')}
            print(f'{i}/{len(черга)} {арт}: цін немає')
        else:
            мін = min(ціни)
            import statistics
            медіана = int(statistics.median(ціни))
            d[арт] = {
                'наша': наша, 'назва': фід[арт]['назва'],
                'категорія': фід[арт]['категорія'],
                'конкуренти': [{'ціна': c, 'джерело': 'prom-пошук'}
                               for c in ціни],
                'мін_конкурент': мін,
                'різниця_%': round((наша - мін) / мін * 100, 1),
                'медіана_конкурентів': медіана,
                'скільки_пропозицій': len(ціни),
                'висновок': (f"закупівля з ПДВ {закуп:.0f}; "
                             f"медіана ринку {медіана}; "
                             f"лише картки з артикулом у назві"),
                'коли': time.strftime('%Y-%m-%d')}
            print(f"{i}/{len(черга)} {арт}: наша {наша:.0f} · мін {мін} · "
                  f"медіана {медіана} · карток {len(ціни)}")
        tmp = СХОВИЩЕ + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, СХОВИЩЕ)
        time.sleep(a.пауза)


if __name__ == '__main__':
    main()
