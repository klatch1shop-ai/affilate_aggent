#!/usr/bin/env python3
"""Гілка офіційного каталогу Rozetka: діти вузла, з відступами.

Пошук за словом (`rozetka_category_find.py`) відповідає на питання «чи є
категорія з таким словом». Але «слова немає» ще не означає «місця немає»:
«Нутроміри» в Rozetka немає, а розділ «Вимірювально-розмічувальний
інструмент» є, і перш ніж записати категорію в «немає відповідника», треба
подивитись перелік сусідів очима. Цей скрипт друкує саме його.

    python3 tools/rozetka_category_tree.py 4672164        # діти вузла
    python3 tools/rozetka_category_tree.py 4672164 -d 2   # два рівні
"""
import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(BASE_DIR, 'tools'))
from rozetka_category_find import load, path  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rz_id', type=int, nargs='+')
    ap.add_argument('-d', '--depth', type=int, default=1)
    a = ap.parse_args()

    rows, by_id, parents = load()
    kids = {}
    for r in rows:
        kids.setdefault(r['parent_id'], []).append(r)

    def walk(node: int, level: int):
        if level > a.depth:
            return
        for c in sorted(kids.get(node, []), key=lambda x: x['rz_name'] or ''):
            mark = '*' if c['rz_id'] in parents else ' '
            print('  ' * level + f"{mark}{c['rz_id']:>9}  {c['rz_name']}")
            walk(c['rz_id'], level + 1)

    for rid in a.rz_id:
        print(f'\n=== {rid}  {path(by_id, rid) or "НЕМАЄ ТАКОГО ID"} ===')
        walk(rid, 1)


if __name__ == '__main__':
    main()
