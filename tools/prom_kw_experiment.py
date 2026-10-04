#!/usr/bin/env python3
"""Знімок і порівняння груп досліду з ключовими словами.

Навіщо: без знімка ДО змін завтра не буде точки відліку. Саме через це
03.10 довелось переробляти аналіз — міряли по фіду, а не по тому, що
насправді в кабінеті.

Три групи:
  косметика — 482 картки, ключі від Gemini (внесено 03.10)
  бдсм      — 968 карток, ключі від Codex
  контроль  — решта каталогу, не чіпали

Міряємо те саме для всіх трьох, інакше різниця буде різницею вибірок.
Дані беремо з КАБІНЕТУ через API, а не з фіду: 02.10 виявилось, що 4619 з
5383 карток мають у кабінеті не ті ключі, що у фіді.

    venv/bin/python3 tools/prom_kw_experiment.py --snapshot
    venv/bin/python3 tools/prom_kw_experiment.py --compare
"""
import argparse
import collections
import datetime
import json
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
SNAP_DIR = os.path.join(BASE, 'data', 'prom', 'snapshots')


def groups():
    """→ {назва групи: {external_id}}. Контроль — усе інше."""
    out = {}
    p = os.path.join(BASE, 'data', 'prom', 'kw_expert_pilot.json')
    out['косметика'] = set(json.load(open(p, encoding='utf-8'))['група']) \
        if os.path.exists(p) else set()
    q = os.path.join(BASE, 'data', 'kw_queue', 'БДСМ-игрушки.json')
    out['бдсм'] = set(json.load(open(q, encoding='utf-8'))['cards']) \
        if os.path.exists(q) else set()
    return out


def fetch_live():
    """Ключі з КАБІНЕТУ. API віддає лише keywords (рос.), keywords_ua — ні."""
    import requests
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, '.env'))
    H = {'Authorization': f'Bearer {os.environ["PROM_API_TOKEN"]}'}
    out, last = [], None
    while True:
        prm = {'limit': 100}
        if last:
            prm['last_id'] = last
        r = requests.get('https://my.prom.ua/api/v1/products/list',
                         headers=H, params=prm, timeout=60)
        items = r.json().get('products', [])
        if not items:
            break
        out += items
        last = items[-1]['id']
    return {x['external_id']: x for x in out}


def measure(cards, ids, freq):
    sel = [cards[i] for i in ids if i in cards]
    if not sel:
        return None
    def kw(x):
        return [k.strip().lower() for k in (x.get('keywords') or '').split(',') if k.strip()]
    n = [len(kw(x)) for x in sel]
    uniq = [sum(1 for k in kw(x) if freq[k] == 1) for x in sel]
    return {'карток': len(sel),
            'медіана_ключів': statistics.median(n),
            'порожніх_слотів': len(sel) * 9 - sum(n),
            'без_унікального_%': round(sum(1 for u in uniq if u == 0) / len(sel) * 100, 1),
            'медіана_унікальних': statistics.median(uniq)}


def snapshot(label):
    cards = fetch_live()
    freq = collections.Counter(
        k.strip().lower() for x in cards.values()
        for k in (x.get('keywords') or '').split(',') if k.strip())
    g = groups()
    g['контроль'] = set(cards) - g['косметика'] - g['бдсм']
    snap = {'дата': datetime.datetime.now().isoformat(timespec='minutes'),
            'мітка': label, 'групи': {}}
    for name, ids in g.items():
        m = measure(cards, ids, freq)
        if m:
            snap['групи'][name] = m
    os.makedirs(SNAP_DIR, exist_ok=True)
    path = os.path.join(SNAP_DIR, f'{label}.json')
    json.dump(snap, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    show(snap)
    print('→', path)


def show(snap):
    print(f"\nЗНІМОК «{snap['мітка']}» · {snap['дата']}")
    print(f'{"група":<12}{"карток":>8}{"ключів":>9}{"порожніх":>10}'
          f'{"без унік.":>11}{"унік.медіана":>14}')
    for name, m in snap['групи'].items():
        print(f'{name:<12}{m["карток"]:>8}{m["медіана_ключів"]:>9.0f}'
              f'{m["порожніх_слотів"]:>10}{m["без_унікального_%"]:>10.1f}%'
              f'{m["медіана_унікальних"]:>14.0f}')


def compare():
    snaps = sorted(os.listdir(SNAP_DIR)) if os.path.isdir(SNAP_DIR) else []
    if len(snaps) < 2:
        print(f'знімків: {len(snaps)} — для порівняння потрібні два')
        for s in snaps:
            show(json.load(open(os.path.join(SNAP_DIR, s), encoding='utf-8')))
        return
    a = json.load(open(os.path.join(SNAP_DIR, snaps[0]), encoding='utf-8'))
    b = json.load(open(os.path.join(SNAP_DIR, snaps[-1]), encoding='utf-8'))
    print(f"ПОРІВНЯННЯ: «{a['мітка']}» → «{b['мітка']}»")
    print(f'{"група":<12}{"без унік. було":>16}{"стало":>10}{"зміна":>9}')
    for name in b['групи']:
        if name not in a['групи']:
            continue
        x, y = a['групи'][name]['без_унікального_%'], b['групи'][name]['без_унікального_%']
        print(f'{name:<12}{x:>15.1f}%{y:>9.1f}%{y-x:>+8.1f}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--snapshot', metavar='МІТКА')
    ap.add_argument('--compare', action='store_true')
    a = ap.parse_args()
    if a.snapshot:
        snapshot(a.snapshot)
    elif a.compare:
        compare()
    else:
        ap.print_help()
