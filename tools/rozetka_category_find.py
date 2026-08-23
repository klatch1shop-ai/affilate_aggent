#!/usr/bin/env python3
"""Пошук категорії в офіційному каталозі Rozetka за словом чи основою.

Потрібен для добору відповідників тим категоріям TOPTUL, яких немає в
`docs/rozetka_seller_categories.json` — там лише 289 категорій, узятих із
каталогу конкурента. Офіційний перелік (`rozetka_categories_fetch.py`) має
4762 категорії, тож «відповідника немає» треба перевіряти саме по ньому.

Друкує повний шлях від кореня: без нього «Насоси» з розділу «Дача, сад,
город» не відрізнити від «Насоси» з «Авто і мото товари», а це різні
категорії з різною комісією.

    python3 tools/rozetka_category_find.py свердл пінцет
    python3 tools/rozetka_category_find.py --leaf насос
"""
import argparse
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALL = os.path.join(BASE_DIR, 'docs', 'rozetka_categories_all.json')


def load():
    with open(ALL, encoding='utf-8') as f:
        rows = json.load(f)
    by_id = {r['rz_id']: r for r in rows}
    parents = {r['parent_id'] for r in rows if r['parent_id']}
    return rows, by_id, parents


def path(by_id: dict, rz_id: int) -> str:
    """Шлях від кореня. Захист від циклу: батько, який уже трапився."""
    out, seen = [], set()
    cur = rz_id
    while cur in by_id and cur not in seen:
        seen.add(cur)
        out.append(by_id[cur]['rz_name'])
        cur = by_id[cur]['parent_id']
    return ' › '.join(reversed(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('query', nargs='+')
    ap.add_argument('--leaf', action='store_true', help='лише листкові категорії')
    ap.add_argument('--limit', type=int, default=12)
    a = ap.parse_args()

    rows, by_id, parents = load()
    for q in a.query:
        rx = re.compile(re.escape(q), re.I)
        hits = [r for r in rows if rx.search(r['rz_name'] or '')]
        if a.leaf:
            hits = [r for r in hits if r['rz_id'] not in parents]
        print(f'\n=== {q} ({len(hits)}) ===')
        for r in hits[:a.limit]:
            leaf = ' ' if r['rz_id'] not in parents else '*'
            print(f"{leaf}{r['rz_id']:>9}  {path(by_id, r['rz_id'])}")


if __name__ == '__main__':
    main()
