#!/usr/bin/env python3
"""Характеристики (фільтри) заданих категорій Rozetka → окремий кеш.

Для нових постачальників: `rozetka_category_options.py` бере категорії з
готового фіду, а фіду ще немає — спершу треба знати, які характеристики
категорія взагалі приймає. Кеш ОКРЕМИЙ від TOPTUL-ового
(`data/rozetka_category_options.json`), бо той читає генератор TOPTUL, а
його фід зараз на перевірці в Rozetka й не має змінюватись навіть побічно.

Лише читання API. Токен ROZETKA_API_TOKEN є тільки на сервері.

    python3 tools/rozetka_options_fetch.py -o data/dropoffice_category_options.json 4629548 4648788
"""
import argparse
import json
import os
import sys
import time

import requests
import urllib3
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'tools'))
load_dotenv(os.path.join(BASE, '.env'))
from rozetka_category_options import fetch  # noqa: E402

urllib3.disable_warnings()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('ids', nargs='+', type=int)
    a = ap.parse_args()
    out = os.path.abspath(os.path.join(BASE, a.out) if not os.path.isabs(a.out) else a.out)
    if os.path.basename(out) == 'rozetka_category_options.json':
        sys.exit('ВІДМОВА: це кеш TOPTUL, писати в нього звідси не можна')
    tok = os.getenv('ROZETKA_API_TOKEN')
    if not tok:
        sys.exit('ROZETKA_API_TOKEN відсутній — запускати на сервері')
    s = requests.Session()
    s.headers.update({'Authorization': f'Bearer {tok}', 'Content-Language': 'uk'})
    s.verify = False
    cache = {}
    if os.path.exists(out):
        with open(out, encoding='utf-8') as f:
            cache = json.load(f)
    miss = []
    for cid in a.ids:
        opts = fetch(s, cid)
        if opts is None:
            miss.append(cid)
            continue
        cache[str(cid)] = opts
        names = {o.get('name') for o in opts}
        print(f'{cid}: {len(opts)} значень, {len(names)} характеристик')
        time.sleep(0.5)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f'записано {len(cache)} категорій у {out}; не отримано: {miss or "—"}')


if __name__ == '__main__':
    main()
