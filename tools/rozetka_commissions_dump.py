#!/usr/bin/env python3
"""Комісії Rozetka по кожному товару → data/rozetka_commissions.json.

ЩО ВАЖЛИВО. Метод `/items-commissions/search` віддає і ставку
(`commission`), і ФАКТИЧНУ суму (`commission_sum`). Вони не збігаються:
на всіх перевірених позиціях сума рівно на 8 % більша за ставку × ціну.
Тобто оголошені 15 % коштують 16,2 %, а 19,4 % — 20,95 %. Рахувати треба
за сумою, а не за ставкою.

Тільки читання.

    venv/bin/python tools/rozetka_commissions_dump.py
"""
import json
import os
import sys
import time

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from agents.orders import rozetka_order_agent as RZ   # noqa: E402

API = 'https://api-seller.rozetka.com.ua'
OUT = os.path.join(BASE, 'data', 'rozetka_commissions.json')


def main():
    h = {'Authorization': f'Bearer {RZ.get_token()}', 'Accept': 'application/json'}
    out, page = [], 1
    while True:
        for спроба in range(3):
            try:
                r = requests.get(f'{API}/items-commissions/search', headers=h,
                                 params={'page': page, 'pageSize': 100}, timeout=90)
                if r.status_code == 401:
                    h['Authorization'] = f'Bearer {RZ.get_token()}'
                    continue
                r.raise_for_status()
                break
            except Exception as e:
                if спроба == 2:
                    print(f'сторінка {page}: {e}', file=sys.stderr)
                    r = None
                time.sleep(2 * (спроба + 1))
        if r is None:
            break
        d = (r.json().get('content') or {})
        порція = d.get('commissions') or []
        out.extend(порція)
        мета = d.get('_meta') or {}
        if page == 1:
            print(f"усього товарів: {мета.get('totalCount')}, сторінок: {мета.get('pageCount')}")
        if page >= (мета.get('pageCount') or 1) or not порція:
            break
        page += 1
        if page % 20 == 0:
            print(f'  {len(out)} …', file=sys.stderr)
        time.sleep(0.2)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print(f'збережено: {len(out)} → {OUT}')


if __name__ == '__main__':
    main()
