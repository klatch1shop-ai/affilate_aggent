#!/usr/bin/env python3
"""
tools/epicentr_attr_fill_multi.py
==================================
Заповнює КІЛЬКА обовʼязкових характеристик у картках Єпіцентру за один прохід.

Вхід: json {sku: {"Назва характеристики": "значення", ...}}
Коди й id атрибутів визначаються з довідника набору автоматично за назвою.

Механізм і пастки — SKILL-20 §3a:
  * тіло PUT несе девʼять полів, узятих із GET; опустити щось = 403;
  * кожне значення має власний `id`;
  * id НОВОЇ характеристики беремо з опису форми, а перелік дозволених
    значень — з merchant-api за набором і кодом (limit ≤ 80, сторінками).

Статусів не міняє.

    python3 tools/epicentr_attr_fill_multi.py --map /tmp/fal_final.json --cat 9480 [--limit 3]
"""
import os, sys, json, time, argparse
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
API = 'https://core-api.epicentrm.com.ua'
MAPI = 'https://merchant-api.epicentrm.com.ua'


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def ua(o):
    for t in (o or {}).get('translations', []):
        if t.get('languageCode') == 'ua':
            return t.get('value') or t.get('title')
    return None


def options(cat, code):
    h = {'Authorization': f"Bearer {os.getenv('EPICENTR_TOKEN')}", 'Accept': 'application/json'}
    out, page = {}, 1
    while True:
        r = requests.get(f'{MAPI}/v2/pim/attribute-sets/{cat}/attributes/{code}/options',
                         headers=h, params={'limit': 80, 'page': page}, timeout=40)
        if r.status_code != 200:
            break
        j = r.json()
        for o in j.get('items', []):
            out[ua(o)] = o['code']
        if page >= (j.get('pages') or 1):
            break
        page += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--map', required=True)
    ap.add_argument('--cat', required=True)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    want = json.load(open(a.map, encoding='utf-8'))
    prods = {x['sku']: x for x in json.load(
        open(os.path.join(BASE, 'data', 'epicentr_products.json'), encoding='utf-8'))}
    sets = json.load(open(os.path.join(BASE, 'data', 'epicentr_attribute_sets.json'),
                          encoding='utf-8'))

    s = requests.Session()
    s.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                      'Accept-Language': 'uk-UA'})
    login(s)
    form = s.get(f'{API}/v2/pim/products/forms/attribute-set/by-code/{a.cat}/attributes',
                 timeout=40).json()
    fitems = form.get('items', form if isinstance(form, list) else [])
    by_code = {str(x['code']): x for x in fitems}

    # назва характеристики → (code, id, {значення: valuecode})
    names = set()
    for v in want.values():
        names |= set(v)
    spec = {}
    for at in sets[a.cat]['attributes']:
        nm = ua(at)
        if nm in names:
            code = str(at['code'])
            fid = (by_code.get(code) or {}).get('id')
            spec[nm] = (code, fid, options(a.cat, code))
    for nm in names:
        if nm not in spec or not spec[nm][1] or not spec[nm][2]:
            sys.exit(f'не вдалося визначити «{nm}»: {spec.get(nm)}')
        print(f'  {nm:14} код {spec[nm][0]:6} id {spec[nm][1]:6} значень {len(spec[nm][2])}')

    todo = [(k, v) for k, v in want.items() if k in prods]
    if a.limit:
        todo = todo[:a.limit]
    print(f'карток до запису: {len(todo)}')

    ok = fail = 0
    for sku, vals in todo:
        pid = prods[sku]['id']
        try:
            r = s.get(f'{API}/v2/pim/products/{pid}', timeout=45)
            if r.status_code == 401:
                login(s); r = s.get(f'{API}/v2/pim/products/{pid}', timeout=45)
            r.raise_for_status(); d = r.json()
        except Exception as e:
            fail += 1; print(f'  {sku}: читання — {e}', file=sys.stderr); continue

        cur = [{'id': v['id'], 'code': v['code'], 'value': v['value']}
               for v in (d.get('attributeValues') or [])]
        have = {str(v['code']) for v in cur}
        added = 0
        for nm, val in vals.items():
            code, fid, opts = spec[nm]
            if code in have or val not in opts:
                continue
            cur.append({'id': fid, 'code': code, 'value': opts[val]}); added += 1
        if not added:
            continue
        body = {'attributeValues': cur, 'categories': d.get('categories'),
                'isPrepayment': d.get('isPrepayment'), 'media': d.get('media'),
                'productInPromotion': d.get('productInPromotion'),
                'attributeSetCode': d.get('attributeSetCode'),
                'companyId': d.get('companyId'), 'sku': d.get('sku'),
                'translations': d.get('translations')}
        r2 = s.put(f'{API}/v4/pim/products/common/{pid}', json=body, timeout=60)
        if r2.status_code in (200, 201, 204):
            ok += 1
        else:
            fail += 1
            print(f'  {sku}: {r2.status_code} {r2.text[:200]}', file=sys.stderr)
        if (ok + fail) % 100 == 0:
            print(f'  {ok+fail}/{len(todo)}', file=sys.stderr)
        time.sleep(0.2)
    print(f'\nзаписано: {ok} | не вдалось: {fail}')


if __name__ == '__main__':
    main()
