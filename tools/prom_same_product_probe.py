#!/usr/bin/env python3
"""Гіпотеза «Prom склеює однаковий товар різних продавців»: що стоїть на місці нашої картки.

Замір 12.09.2026 (`prom_search.py`, 150 карток): 16 знайдено — УСІ на першій
сторінці; 134 не знайдено взагалі, навіть на 2–3 сторінках. Проміжного стану
немає, тож справа не в конкуренції за позицію, а в тому, чи картка в
індексі. Текстові ознаки знайдених і незнайдених майже однакові.

Перевірка: за точною назвою незнайденої картки — чи є у видачі ТОЙ САМИЙ
товар від інших продавців. Той самий = у назві результату є ядро моделі
(латиниця й цифри з нашої назви, ≥2 токени, усі). Якщо у незнайдених
видача зайнята тим самим товаром чужих продавців, а в знайдених — ні або
значно рідше, гіпотеза склеювання жива. Якщо однаково — ні.

    python3 tools/prom_same_product_probe.py --from docs/prom_visibility_20260912.tsv --n-missing 40
"""
import argparse
import collections
import csv
import os
import re
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from prom_search import search, OUR_COMPANY, PAUSE  # noqa: E402

TOK = re.compile(r"[A-Za-z][A-Za-z0-9\-']+|\d+[A-Za-z]*")


def core_tokens(name: str) -> list:
    toks = [t.lower() for t in TOK.findall(name.split(',')[0])]
    return [t for t in toks if len(t) >= 2][:4]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='src', required=True)
    ap.add_argument('--n-missing', type=int, default=40)
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.src, encoding='utf-8'), delimiter='\t'))
    found = [r for r in rows if r['found_pos'] not in ('0', '')]
    missing = [r for r in rows if r['found_pos'] in ('0', '')][:a.n_missing]

    out = collections.defaultdict(list)
    for group, items in (('знайдені', found), ('незнайдені', missing)):
        for r in items:
            ct = core_tokens(r['name'])
            if len(ct) < 2:
                out[group].append(None)
                continue
            res = search(r['name'], pages=1)
            same = [x for x in res if all(t in x['name'].lower() for t in ct)
                    and x['company_id'] != OUR_COMPANY]
            out[group].append(len(same))
            print(f"{group[:4]} {r['sku']:8} ядро={' '.join(ct):28} той самий товар в інших: {len(same)} "
                  f"з {len(res)}", flush=True)
            time.sleep(PAUSE)
    print('\nпідсумок (картки з ядром ≥2 токени):')
    for g, v in out.items():
        v = [x for x in v if x is not None]
        if v:
            print(f'  {g:10} карток {len(v):3} · є той самий товар в інших продавців у '
                  f'{sum(x > 0 for x in v)} ({sum(x > 0 for x in v) / len(v):.0%}) · '
                  f'середньо таких результатів {sum(v) / len(v):.1f}')


if __name__ == '__main__':
    main()
