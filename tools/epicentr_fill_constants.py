"""Заповнює характеристики, сталі для набору, значеннями з ОПУБЛІКОВАНИХ карток.

Знайдено 27.09.2026 (метод `finding-solutions`): опубліковані картки вже
пройшли модерацію, тож їхні значення гарантовано дійсні — на відміну від
будь-чого, що вигадає модель. У наборі 7216 такими виявились «Одиниця виміру
та кількість» (measure_pcs, 100%) і «Мінімальна кратність товару» (1, 100%) —
поля, яких ми не заповнювали взагалі, бо виводили характеристики з фото.

Записує ЛИШЕ те, що в зразках трапляється з часткою ≥ порога, і ЛИШЕ в
порожні поля: наявне значення не чіпається.

    venv/bin/python tools/epicentr_fill_constants.py --templates exports/epicentr_templates.json \
        --skus exports/noire_left.json --set 7216
    ... --apply
"""
import argparse
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

API = 'https://core-api.epicentrm.com.ua'
PRODUCTS = os.path.join(BASE, 'data', 'epicentr_products.json')


def login(session):
    r = session.post(f'{API}/v2/users/login',
                     json={'login': os.getenv('EPICENTR_EMAIL'),
                           'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    session.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def form_ids(session, set_code):
    """{код атрибута: id у формі} — без id PUT відхиляє значення."""
    r = session.get(f'{API}/v2/pim/products/forms/attribute-set/by-code/{set_code}/attributes',
                    timeout=40)
    r.raise_for_status()
    data = r.json()
    items = data.get('items', data if isinstance(data, list) else [])
    return {str(x['code']): x.get('id') for x in items}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--templates', required=True)
    ap.add_argument('--skus', required=True, help='{sku: ...} — які картки чіпати')
    ap.add_argument('--set', required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--min-share', type=float, default=0.95)
    a = ap.parse_args()

    templates = json.load(open(a.templates, encoding='utf-8'))
    tpl = templates.get(a.set)
    if not tpl:
        sys.exit(f'немає зразка для набору {a.set}')
    const = {code: info for code, info in tpl['сталі'].items()
             if info['частка'] >= a.min_share}
    if not const:
        sys.exit('немає достатньо сталих значень')
    print(f'набір {a.set}, сталих до запису: {len(const)}')
    for code, info in const.items():
        print(f"  {info['назва']} = {str(info['значення'])[:40]} ({int(info['частка']*100)}%)")

    wanted = set(json.load(open(a.skus, encoding='utf-8')))
    products = [x for x in json.load(open(PRODUCTS, encoding='utf-8'))
                if x['sku'] in wanted and str(x.get('attributeSetCode')) == a.set]
    if a.limit:
        products = products[:a.limit]
    print(f'карток: {len(products)}')
    if not a.apply:
        print('\nце ПОКАЗ. Щоб записати — додайте --apply')
        return

    session = requests.Session()
    session.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                            'Accept-Language': 'uk-UA'})
    login(session)
    ids = form_ids(session, a.set)

    ok = fail = skipped = 0
    for i, product in enumerate(products, 1):
        pid = product['id']
        try:
            r = session.get(f'{API}/v2/pim/products/{pid}', timeout=45)
            if r.status_code == 401:
                login(session)
                r = session.get(f'{API}/v2/pim/products/{pid}', timeout=45)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            fail += 1
            print(f"  {product['sku']}: читання — {e}", file=sys.stderr)
            continue

        current = [{'id': v['id'], 'code': v['code'], 'value': v['value']}
                   for v in (data.get('attributeValues') or [])]
        have = {str(v['code']) for v in current}
        added = 0
        for code, info in const.items():
            if code in have or not ids.get(code):
                continue                      # наявне не чіпаємо
            # code — РЯДОК: int дає 400 validation.type
            current.append({'id': ids[code], 'code': code, 'value': info['значення']})
            added += 1
        if not added:
            skipped += 1
            continue

        body = {'attributeValues': current, 'categories': data.get('categories'),
                'isPrepayment': data.get('isPrepayment'), 'media': data.get('media'),
                'productInPromotion': data.get('productInPromotion'),
                'attributeSetCode': data.get('attributeSetCode'),
                'companyId': data.get('companyId'), 'sku': data.get('sku'),
                'translations': data.get('translations')}
        r2 = session.put(f'{API}/v4/pim/products/common/{pid}', json=body, timeout=60)
        tries = 0
        while r2.status_code == 400 and tries < 2:
            import re
            bad = set(re.findall(r'attributeValues\[(\d+)\]', r2.text))
            if not bad:
                break
            body['attributeValues'] = [v for v in body['attributeValues']
                                       if str(v['code']) not in bad]
            tries += 1
            r2 = session.put(f'{API}/v4/pim/products/common/{pid}', json=body, timeout=60)
        if r2.status_code in (200, 201, 204):
            ok += 1
        else:
            fail += 1
            print(f"  {product['sku']}: {r2.status_code} {r2.text[:150]}", file=sys.stderr)
        if i % 100 == 0:
            print(f'  {i}/{len(products)}', file=sys.stderr, flush=True)
        time.sleep(0.15)

    print(f'\nзаписано: {ok} | пропущено (вже було): {skipped} | не вдалось: {fail}')


if __name__ == '__main__':
    main()
