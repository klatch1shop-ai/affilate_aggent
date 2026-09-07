#!/usr/bin/env python3
"""
tools/epicentr_moderate_ready.py
=================================
Знаходить УСІ картки в «Наповненні контентом», де заповнені всі обовʼязкові
характеристики, і переводить їх на модерацію.

Відрізняється від `epicentr_to_moderation.py` тим, що не потребує переліку
артикулів: сам обходить кабінет і перевіряє кожну картку.

ПЕРЕХІД ОДНОСТОРОННІЙ — назад повертає лише модератор. Тому:
  * перевіряється КОЖНА картка окремим запитом, а не за списком із файлу;
  * недозаповнені не рухаються взагалі;
  * дія під запобіжником consent.py (epicentr_moderate).

    python3 tools/epicentr_moderate_ready.py --plan
    python3 tools/epicentr_moderate_ready.py [--limit N]
"""
import os, sys, json, time, argparse, collections
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.consent import require as consent_require
API = 'https://core-api.epicentrm.com.ua'
CHUNK = 50


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--wave', default='2026-07')
    a = ap.parse_args()

    prods = [x for x in json.load(open(os.path.join(BASE, 'data', 'epicentr_products.json'),
                                       encoding='utf-8'))
             if (x.get('createdAt') or '')[:7] == a.wave and x['status'] == 'enrich']
    sets = json.load(open(os.path.join(BASE, 'data', 'epicentr_attribute_sets.json'),
                          encoding='utf-8'))
    print(f'карток у «Наповненні контентом»: {len(prods)}')

    s = requests.Session()
    s.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                      'Accept-Language': 'uk-UA'})
    login(s)

    ready, gaps = [], collections.Counter()
    for i, p in enumerate(prods, 1):
        try:
            d = s.get(f"{API}/v2/pim/products/{p['id']}", timeout=45)
            if d.status_code == 401:
                login(s); d = s.get(f"{API}/v2/pim/products/{p['id']}", timeout=45)
            d = d.json()
        except Exception:
            continue
        if d.get('status') != 'enrich':
            continue
        cat = str(d.get('attributeSetCode'))
        spec = sets.get(cat)
        if not spec:
            gaps['категорії немає в довіднику'] += 1; continue
        req = [str(x['code']) for x in spec.get('attributes', []) if x.get('isRequired')]
        have = {str(v['code']) for v in (d.get('attributeValues') or [])
                if v.get('value') not in (None, '', [])}
        miss = [c for c in req if c not in have]
        if miss:
            gaps[f'{p.get("attributeSetName")}'] += 1
        else:
            ready.append(p)
        if i % 300 == 0:
            print(f'  перевірено {i}/{len(prods)} — готових {len(ready)}', file=sys.stderr)
        time.sleep(0.05)

    print(f'\nготові до модерації: {len(ready)}')
    print('недозаповнені за категоріями:')
    for k, v in gaps.most_common(10):
        print(f'   {v:5}  {k}')
    if a.limit:
        ready = ready[:a.limit]
    if a.plan or not ready:
        print(f'\n[plan] перевів би {len(ready)}')
        return

    consent_require('epicentr_moderate', f'{len(ready)} карток → moderating')
    ok = fail = 0
    for i in range(0, len(ready), CHUNK):
        part = ready[i:i + CHUNK]
        coll = [{'productId': x['id'], 'statusCode': 'moderating'} for x in part]
        r = s.patch(f'{API}/v2/pim/products/common/status/batch',
                    json={'collection': coll}, timeout=90)
        if r.status_code in (200, 202, 204):
            ok += len(part)
        else:
            fail += len(part)
            print(f'  партія {i//CHUNK+1}: {r.status_code} {r.text[:160]}', file=sys.stderr)
        print(f'  {ok+fail}/{len(ready)}', file=sys.stderr)
        time.sleep(1)
    print(f'\nпереведено: {ok} | не вдалось: {fail}')


if __name__ == '__main__':
    main()
