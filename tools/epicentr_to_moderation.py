#!/usr/bin/env python3
"""
tools/epicentr_to_moderation.py
================================
Переводить картки Єпіцентру з «Наповнення контентом» на модерацію.

    PATCH /v2/pim/products/common/status/batch
    {"collection": [{"productId": …, "statusCode": "moderating"}]}

ПЕРЕХІД ОДНОСТОРОННІЙ: одразу після нього availabilityTransitions стає
порожнім — назад картку повертає лише модератор. Тому дія під запобіжником
shared/utils/consent.py (epicentr_moderate) і вимагає дозволу власника.

Перед переведенням перевіряє КОЖНУ картку: усі обовʼязкові характеристики
заповнені. Недозаповнена картка на модерації — це гарантоване повернення
й зіпсована статистика магазину.

Запуск:
    python3 tools/epicentr_to_moderation.py --map /tmp/mast_vyd.json --cat 9472 [--limit 10]
"""
import os, sys, json, time, argparse
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
    ap.add_argument('--map', required=True)
    ap.add_argument('--cat', required=True)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    skus = list(json.load(open(a.map, encoding='utf-8')))
    prods = {x['sku']: x for x in json.load(
        open(os.path.join(BASE, 'data', 'epicentr_products.json'), encoding='utf-8'))}
    sets = json.load(open(os.path.join(BASE, 'data', 'epicentr_attribute_sets.json'),
                          encoding='utf-8'))
    req = [str(x['code']) for x in sets[a.cat]['attributes'] if x.get('isRequired')]

    s = requests.Session()
    s.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                      'Accept-Language': 'uk-UA'})
    login(s)

    ready, notready, wrongstate = [], [], []
    for sku in skus:
        p = prods.get(sku)
        if not p:
            continue
        d = s.get(f"{API}/v2/pim/products/{p['id']}", timeout=45).json()
        if d.get('status') != 'enrich':
            wrongstate.append((sku, d.get('status'))); continue
        codes = {str(v['code']) for v in (d.get('attributeValues') or [])
                 if v.get('value') not in (None, '', [])}
        miss = [c for c in req if c not in codes]
        (ready if not miss else notready).append(sku if not miss else (sku, miss))
    print(f'готові до модерації : {len(ready)}')
    print(f'недозаповнені       : {len(notready)}')
    print(f'уже не в enrich     : {len(wrongstate)}')
    if a.limit:
        ready = ready[:a.limit]
    if not ready:
        return
    if a.dry:
        print(f'[dry] перевів би {len(ready)}'); return

    consent_require('epicentr_moderate', f'{len(ready)} карток → moderating')
    ok = fail = 0
    for i in range(0, len(ready), CHUNK):
        part = ready[i:i + CHUNK]
        coll = [{'productId': prods[x]['id'], 'statusCode': 'moderating'} for x in part]
        r = s.patch(f'{API}/v2/pim/products/common/status/batch',
                    json={'collection': coll}, timeout=90)
        if r.status_code in (200, 202, 204):
            ok += len(part)
        else:
            fail += len(part)
            print(f'  партія {i//CHUNK+1}: {r.status_code} {r.text[:200]}', file=sys.stderr)
        print(f'  {ok+fail}/{len(ready)}', file=sys.stderr)
        time.sleep(1)
    print(f'\nпереведено: {ok} | не вдалось: {fail}')


if __name__ == '__main__':
    main()
