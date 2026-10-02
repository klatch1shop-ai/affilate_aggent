#!/usr/bin/env python3
"""Прогін photo_pick_main по всіх картках, які Єпіцентр відхилив (status=banned).

Навіщо: 96 % відмов — одне формулювання про головне фото. Якщо серед наявних
4-5 знімків постачальника є чистий кадр, картка лагодиться без фотостудії.

Чому без OCR: калібрування 02.10 показало, що відхилені фото відрізняються
КОЛАЖЕМ (4-10 ліній поділу проти 0 у прийнятих), а текст у трьох із чотирьох
нульовий. OCR додавав би хвилину на знімок — 19 годин на 1065 фото.

Поріг 3.9 — середина розриву між прийнятими (4.35-4.53) і відхиленими
(1.82-3.48) з того ж калібрування.

Ризику немає: ці 228 карток і так не продаються. Нічого не публікується —
на виході файл для рішення власника.

    venv/bin/python tools/epicentr_photo_pick_run.py --workers 6
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import psycopg2

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from tools.photo_pick_main import rate  # noqa: E402

DB = dict(host='192.168.3.28', dbname='agentdb', user='agentadmin', password='1')
OUT = os.path.join(BASE, 'exports', 'epicentr_photo_pick.json')


def load_cards():
    """SKU, які Єпіцентр відхилив, разом із фото постачальника."""
    products = json.load(open(os.path.join(BASE, 'data', 'epicentr_products.json'),
                              encoding='utf-8'))
    banned = {p['sku']: p for p in products if p['status'] == 'banned'}
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute('select sku, name, pictures from sexopt_products where sku = any(%s)',
                (list(banned),))
    cards = []
    for sku, name, pics in cur.fetchall():
        cards.append({'sku': sku, 'name': name, 'pictures': list(pics or [])})
    conn.close()
    missing = set(banned) - {c['sku'] for c in cards}
    if missing:
        print(f'[увага] немає в sexopt_products: {len(missing)} → {sorted(missing)[:5]}',
              flush=True)
    return cards


def run(min_score, workers):
    cards = load_cards()
    print(f'карток: {len(cards)} · фото: {sum(len(c["pictures"]) for c in cards)}',
          flush=True)

    def process(card):
        rated = []
        for url in card['pictures']:
            try:
                rated.append(rate(url, use_ocr=False, use_edge_text=True))
            except Exception as exc:
                rated.append({'url': url, 'error': type(exc).__name__})
        ok = [r for r in rated if 'error' not in r]
        best = max(ok, key=lambda r: r['score']) if ok else None
        card['rated'] = rated
        card['best'] = best
        # поточне головне = перше у списку постачальника
        card['current'] = rated[0] if rated else None
        card['passes'] = bool(best and best['score'] >= min_score)
        card['changes_photo'] = bool(best and rated and best['url'] != rated[0]['url'])
        return card

    done = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, card in enumerate(pool.map(process, cards), 1):
            done.append(card)
            if i % 20 == 0:
                print(f'  {i}/{len(cards)}', flush=True)

    fixable = [c for c in done if c['passes']]
    manual = [c for c in done if not c['passes']]
    already = [c for c in fixable if not c['changes_photo']]

    json.dump({'min_score': min_score,
               'fixable': fixable, 'manual': manual},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print(f'\nпоріг {min_score}')
    print(f'ЛАГОДИТЬСЯ заміною фото: {len(fixable) - len(already)}')
    print(f'найкраще фото вже перше (причина відмови інша): {len(already)}')
    print(f'РУЧНА ЧЕРГА (чистого кадру немає): {len(manual)}')
    print(f'  з них мають лише 1 фото: {sum(1 for c in manual if len(c["pictures"]) < 2)}')
    print('→', OUT)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-score', type=float, default=3.9)
    ap.add_argument('--workers', type=int, default=6)
    a = ap.parse_args()
    run(a.min_score, a.workers)
