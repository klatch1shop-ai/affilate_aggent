"""
tools/epicentr_categories_fetch.py
===================================
Викачує дерево категорій Єпіцентру в data/epicentr_categories_live.json.

Джерело: GET /v2/pim/categories (merchant-api) — віддає code, parentCode,
hasChild, attributeSets, переклади. Це єдиний авторитетний перелік:
локальна таблиця epicentr_intimate_categories й CSV від 05.2026 застаріли.
"""
import os, sys, json, time
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
HOST  = 'https://merchant-api.epicentrm.com.ua'
TOKEN = os.getenv('EPICENTR_TOKEN')
OUT   = os.path.join(BASE, 'data', 'epicentr_categories_live.json')


def main():
    s = requests.Session()
    s.headers.update({'Authorization': f'Bearer {TOKEN}', 'Accept': 'application/json'})
    cats, page = {}, 1
    while True:
        for attempt in range(4):
            try:
                r = s.get(f'{HOST}/v2/pim/categories',
                          params={'page': page, 'limit': 100}, timeout=60)
                r.raise_for_status(); d = r.json(); break
            except Exception as e:
                if attempt == 3:
                    print(f'сторінка {page}: {e}', file=sys.stderr); d = None; break
                time.sleep(2 * (attempt + 1))
        if not d:
            break
        for it in d.get('items', []):
            cats[str(it['code'])] = it
        total = d.get('pages', 1)
        if page % 20 == 0 or page >= total:
            print(f'  {page}/{total} — категорій {len(cats)}', file=sys.stderr)
        if page >= total:
            break
        page += 1
    json.dump(cats, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'збережено категорій: {len(cats)} → {OUT}')


if __name__ == '__main__':
    main()
