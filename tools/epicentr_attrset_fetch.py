"""
tools/epicentr_attrset_fetch.py
================================
Викачує довідник наборів атрибутів Єпіцентру в data/epicentr_attribute_sets.json.

Робочий маршрут — саме GET /v2/pim/attribute-sets (список), він віддає для
кожного набору повний масив attributes з isRequired/type/code.
Маршрут /v2/pim/attribute-sets/{code}/attributes НЕ існує ("No route
configured") — не витрачати на нього час (перевірено 21.08.2026).
"""
import os, sys, json, time
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))

HOST  = 'https://merchant-api.epicentrm.com.ua'
TOKEN = os.getenv('EPICENTR_TOKEN')
OUT   = os.path.join(BASE, 'data', 'epicentr_attribute_sets.json')
LIMIT = 100


def main():
    s = requests.Session()
    s.headers.update({'Authorization': f'Bearer {TOKEN}', 'Accept': 'application/json'})
    sets, page = {}, 1
    while True:
        for attempt in range(4):
            try:
                r = s.get(f'{HOST}/v2/pim/attribute-sets',
                          params={'page': page, 'limit': LIMIT}, timeout=60)
                r.raise_for_status()
                data = r.json()
                break
            except Exception as e:
                if attempt == 3:
                    print(f'сторінка {page}: {e}', file=sys.stderr)
                    data = None
                    break
                time.sleep(2 * (attempt + 1))
        if not data:
            break
        for it in data.get('items', []):
            sets[str(it['code'])] = it
        total = data.get('pages', 1)
        if page % 10 == 0 or page >= total:
            print(f'  сторінка {page}/{total} — наборів {len(sets)}', file=sys.stderr)
        if page >= total:
            break
        page += 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(sets, f, ensure_ascii=False)
    print(f'збережено наборів: {len(sets)} → {OUT}')


if __name__ == '__main__':
    main()
