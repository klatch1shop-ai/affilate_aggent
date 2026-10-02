#!/usr/bin/env python3
"""Звірка: що Prom РЕАЛЬНО має в картках проти того, що ми надіслали фідом.

Навіщо: перехресне обговорення 02.10 (Gemini + Codex) збіглось на тому, що
перед масовою правкою ключів треба довести доставку. Наші дані про картки
були від 12.09, фід від 07.09 — стан кабінету невідомий.

API віддає `keywords` одним полем (НЕ multilang, на відміну від
`name_multilang`), тож 9 слотів ключів спільні для обох мов.

    venv/bin/python tools/prom_live_audit.py --fetch    # вивантажити
    venv/bin/python tools/prom_live_audit.py --compare  # звірити з фідом
"""
import argparse
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
TOKEN = os.getenv('PROM_API_TOKEN')
API = 'https://my.prom.ua/api/v1/products/list'
LIVE = os.path.join(BASE, 'exports', 'prom_live_cards.json')
FEED = os.path.join(BASE, 'output', 'noire_prom.xml')


def fetch():
    out, last_id, page = [], None, 0
    while True:
        params = {'limit': 100}
        if last_id:
            params['last_id'] = last_id
        r = requests.get(API, headers={'Authorization': f'Bearer {TOKEN}'},
                         params=params, timeout=60)
        if r.status_code != 200:
            print(f'HTTP {r.status_code}: {r.text[:200]}', flush=True)
            break
        items = r.json().get('products', [])
        if not items:
            break
        page += 1
        for p in items:
            nm = p.get('name_multilang') or {}
            out.append({
                'external_id': p.get('external_id'), 'id': p.get('id'),
                'sku': p.get('sku'), 'status': p.get('status'),
                'presence': p.get('presence'),
                'name_ru': nm.get('ru'), 'name_uk': nm.get('uk'),
                'keywords': p.get('keywords') or '',
                'images': len(p.get('images') or []),
                'date_modified': p.get('date_modified'),
            })
        last_id = items[-1]['id']
        if page % 10 == 0:
            print(f'  сторінка {page}: {len(out)} товарів', flush=True)
        time.sleep(0.4)
    json.dump(out, open(LIVE, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'вивантажено {len(out)} карток → {LIVE}')


def compare():
    import xml.etree.ElementTree as ET
    live = {c['external_id']: c for c in json.load(open(LIVE, encoding='utf-8'))}
    feed = {}
    for o in ET.parse(FEED).getroot().findall('.//offer'):
        feed[o.get('id')] = {
            'name': (o.findtext('name') or '').strip(),
            'kw': [k.strip().lower() for k in (o.findtext('keywords') or '').split(',') if k.strip()],
        }
    print(f'у кабінеті {len(live)} · у фіді {len(feed)}')
    both = set(live) & set(feed)
    print(f'спільних: {len(both)} · лише в кабінеті: {len(set(live)-set(feed))} '
          f'· лише у фіді: {len(set(feed)-set(live))}')

    same_kw = diff_kw = empty_live = 0
    no_uk = 0
    for eid in both:
        lk = [k.strip().lower() for k in live[eid]['keywords'].split(',') if k.strip()]
        fk = feed[eid]['kw']
        if not lk:
            empty_live += 1
        elif set(lk) == set(fk):
            same_kw += 1
        else:
            diff_kw += 1
        if not (live[eid]['name_uk'] or '').strip():
            no_uk += 1
    print(f'\nКЛЮЧІ: збігаються з фідом {same_kw} · РОЗБІГАЮТЬСЯ {diff_kw} · '
          f'порожні в кабінеті {empty_live}')
    print(f'НАЗВИ: без української назви в кабінеті {no_uk} з {len(both)}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--fetch', action='store_true')
    ap.add_argument('--compare', action='store_true')
    a = ap.parse_args()
    if not TOKEN:
        sys.exit('немає PROM_API_TOKEN')
    if a.fetch:
        fetch()
    if a.compare:
        compare()
