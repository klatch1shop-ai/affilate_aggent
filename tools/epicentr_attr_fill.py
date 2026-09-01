#!/usr/bin/env python3
"""
tools/epicentr_attr_fill.py
============================
Заповнює одну обовʼязкову характеристику в картках Єпіцентру через API кабінету.

Механізм (SKILL-20 §3a):
    PUT /v4/pim/products/common/{id}
    {"attributeValues": [{"id": …, "code": …, "value": …}, …]}

Три речі, на яких легко втратити день:
  * кожне значення несе `id`, не лише code/value — без нього 403;
  * `id` НОВОЇ характеристики беремо з опису форми
    GET /v2/pim/products/forms/attribute-set/by-code/{cat}/attributes;
  * у тілі надсилаємо ВЕСЬ масив характеристик, а не тільки нову.

Статусів не міняє. Перехід на модерацію — окремо й з дозволу власника
(він односторонній: назад повертає лише модератор).

Запуск:
    python3 tools/epicentr_attr_fill.py --map /tmp/mast_vyd.json \
        --cat 9472 --attr 3106 --limit 1        # спершу одна картка
"""
import os, sys, json, time, argparse
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


def ua(o):
    for t in (o or {}).get('translations', []):
        if t.get('languageCode') == 'ua':
            return t.get('value') or t.get('title')
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--map', required=True, help='json: {sku: "назва значення"}')
    ap.add_argument('--cat', required=True)
    ap.add_argument('--attr', required=True)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    want = json.load(open(a.map, encoding='utf-8'))
    prods = {x['sku']: x for x in json.load(
        open(os.path.join(BASE, 'data', 'epicentr_products.json'), encoding='utf-8'))}

    s = requests.Session()
    s.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                      'Accept-Language': 'uk-UA'})
    login(s)

    form = s.get(f'{API}/v2/pim/products/forms/attribute-set/by-code/{a.cat}/attributes',
                 timeout=40).json()
    items = form.get('items', form if isinstance(form, list) else [])
    spec = next((x for x in items if str(x.get('code')) == a.attr), None)
    if not spec:
        sys.exit(f'атрибута {a.attr} немає у формі категорії {a.cat}')
    attr_id = spec['id']
    opts = {ua(o): o['code'] for o in (spec.get('options') or [])}
    if not opts:
        # Форма часто віддає options порожнім. Робочий шлях — merchant-api
        # за НАБОРОМ і КОДОМ атрибута (не за його id): перевірено на 9458/13948,
        # де форма дала 0 значень, а цей виклик — 33.
        MAPI = 'https://merchant-api.epicentrm.com.ua'
        # limit>100 дає 400 Invalid request parameters — читаємо сторінками
        h = {'Authorization': f"Bearer {os.getenv('EPICENTR_TOKEN')}",
             'Accept': 'application/json'}
        page = 1
        while True:
            r = requests.get(
                f'{MAPI}/v2/pim/attribute-sets/{a.cat}/attributes/{a.attr}/options',
                headers=h, params={'limit': 80, 'page': page}, timeout=40)
            if r.status_code != 200:
                print(f'  довідник значень: HTTP {r.status_code}', file=sys.stderr)
                break
            j = r.json()
            for o in j.get('items', []):
                opts[ua(o)] = o['code']
            if page >= (j.get('pages') or 1):
                break
            page += 1
    print(f'атрибут {a.attr} → id {attr_id} | дозволених значень: {len(opts)}')
    unknown = sorted(set(want.values()) - set(opts))
    if unknown:
        sys.exit(f'значення немає в довіднику: {unknown}')

    todo = [(sku, v) for sku, v in want.items() if sku in prods]
    if a.limit:
        todo = todo[:a.limit]
    print(f'карток до запису: {len(todo)}')

    ok = skip = fail = 0
    for sku, val in todo:
        pid = prods[sku]['id']
        for attempt in range(3):
            try:
                r = s.get(f'{API}/v2/pim/products/{pid}', timeout=45)
                if r.status_code == 401:
                    login(s); continue
                r.raise_for_status(); d = r.json(); break
            except Exception as e:
                if attempt == 2:
                    print(f'  {sku}: читання — {e}', file=sys.stderr); d = None; break
                time.sleep(2 * (attempt + 1))
        if not d:
            fail += 1; continue

        vals = [{'id': v['id'], 'code': v['code'], 'value': v['value']}
                for v in (d.get('attributeValues') or [])]
        if any(str(v['code']) == a.attr for v in vals):
            skip += 1; continue          # уже заповнено — не чіпаємо
        vals.append({'id': attr_id, 'code': a.attr, 'value': opts[val]})

        if a.dry:
            print(f'  [dry] {sku} ← {val}'); ok += 1; continue
        # Тіло має нести ТОЙ САМИЙ набір полів, що надсилає кабінет —
        # перехоплено з його власного збереження 24.08.2026. Якщо частину
        # опустити, API читає це як спробу їх очистити й відмовляє:
        # без translations → 400 validation.count.min,
        # лише translations+attributeValues → 403 permission.not_allowed.
        # Значення беремо з GET, тобто нічого, крім характеристики, не міняємо.
        body = {
            'attributeValues': vals,
            'categories': d.get('categories'),
            'isPrepayment': d.get('isPrepayment'),
            'media': d.get('media'),
            'productInPromotion': d.get('productInPromotion'),
            'attributeSetCode': d.get('attributeSetCode'),
            'companyId': d.get('companyId'),
            'sku': d.get('sku'),
            'translations': d.get('translations'),
        }
        r2 = s.put(f'{API}/v4/pim/products/common/{pid}', json=body, timeout=60)
        if r2.status_code in (200, 201, 204):
            ok += 1
        else:
            fail += 1
            print(f'  {sku}: {r2.status_code} {r2.text[:600]}', file=sys.stderr)
        if (ok + fail) % 50 == 0:
            print(f'  {ok + fail}/{len(todo)}', file=sys.stderr)
        time.sleep(0.2)

    print(f'\nзаписано: {ok} | уже було: {skip} | не вдалось: {fail}')


if __name__ == '__main__':
    main()
