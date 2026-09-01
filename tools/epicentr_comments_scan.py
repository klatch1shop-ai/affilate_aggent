#!/usr/bin/env python3
"""
tools/epicentr_comments_scan.py
================================
Збирає коментарі модераторів Єпіцентру по картках компанії.

    GET /v2/pim/products/{id}/comments  →  {"total": N, "items": [...]}

Навіщо: коментар — єдине місце, де модератор пояснює, ЩО саме не так. У
переліку товарів його видно лише іконкою; текст є тільки тут.

Урок, який коштував двох хибних висновків: нуль коментарів на одній картці
(і навіть на сорока випадкових) — це факт ПРО ВИБІРКУ, а не про систему.
Коментарі мають картки, ПОВЕРНУТІ з модерації, а таких серед випадкових
майже немає. Сканувати треба адресно — ті, що відправляли.

    python3 tools/epicentr_comments_scan.py [--status enrich] [--limit N]
"""
import os, sys, json, time, argparse, collections
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
API = 'https://core-api.epicentrm.com.ua'


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--status', default='', help='фільтр за статусом картки')
    ap.add_argument('--wave', default='2026-07', help='місяць створення (постачальник)')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--ids', default='', help='json-перелік id карток: сканувати '
                                             'саме їх, ігноруючи --wave/--status')
    ap.add_argument('--out', default='', help='куди писати (типово '
                                             'docs/epicentr_moderator_comments.json)')
    a = ap.parse_args()

    prods = json.load(open(os.path.join(BASE, 'data', 'epicentr_products.json'),
                           encoding='utf-8'))
    if a.ids:
        # адресний прохід: перелік складається зовні (наприклад, картки, які
        # повернулись із модерації). Саме про це попередження в шапці — по
        # випадковій вибірці коментарів майже немає, і нуль нічого не означає.
        want = set(json.load(open(a.ids, encoding='utf-8')))
        sel = [x for x in prods if x['id'] in want]
        missing = want - {x['id'] for x in sel}
        if missing:
            print(f'УВАГА: {len(missing)} id немає у вивантаженні карток',
                  file=sys.stderr)
    else:
        sel = [x for x in prods if (x.get('createdAt') or '')[:7] == a.wave]
        if a.status:
            sel = [x for x in sel if x['status'] == a.status]
    if a.limit:
        sel = sel[:a.limit]
    print(f'карток до перевірки: {len(sel)}')

    s = requests.Session()
    s.headers.update({'Accept': 'application/json', 'Accept-Language': 'uk-UA'})
    login(s)

    found, out = 0, []
    for i, p in enumerate(sel, 1):
        for attempt in range(3):
            try:
                r = s.get(f"{API}/v2/pim/products/{p['id']}/comments", timeout=30)
                if r.status_code == 401:
                    login(s); continue
                if r.status_code != 200:
                    j = None; break
                j = r.json(); break
            except Exception:
                if attempt == 2:
                    j = None; break
                time.sleep(2 * (attempt + 1))
        if not j or not j.get('total'):
            continue
        found += 1
        for it in j.get('items', []):
            au = it.get('author') or {}
            out.append({'sku': p['sku'], 'id': p['id'], 'status': p['status'],
                        'category': p.get('attributeSetName'),
                        'text': (it.get('content') or '').strip(),
                        'author': f"{au.get('firstName','')} {au.get('lastName','')}".strip(),
                        'createdAt': it.get('createdAt')})
        if i % 300 == 0:
            print(f'  {i}/{len(sel)} — з коментарями {found}', file=sys.stderr)
        time.sleep(0.08)

    dst = os.path.join(BASE, 'docs', 'epicentr_moderator_comments.json')
    json.dump(out, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\nкарток із коментарями: {found} | коментарів усього: {len(out)}')
    if out:
        txt = collections.Counter(o['text'][:90] for o in out)
        print('\nнайчастіші зауваження:')
        for k, v in txt.most_common(12):
            print(f'   {v:5}  {k}')
        cat = collections.Counter(o['category'] for o in out)
        print('\nза категоріями:')
        for k, v in cat.most_common(8):
            print(f'   {v:5}  {k}')
    print(f'\n→ {dst}')


if __name__ == '__main__':
    main()
