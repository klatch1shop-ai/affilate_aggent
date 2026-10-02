#!/usr/bin/env python3
"""Чи існують наші опубліковані картки на вітрині epicentrk.ua.

Привід: картка GR001 має в кабінеті статус `published`, «В наявності» і ціну
3469 ₴, але сторінка за її власним slug віддає 404. Якщо так із усіма —
продажів не буде за визначенням, скільки б ми не покращували картки.

Формат адреси підтверджено з офіційного sitemap маркетплейсу
(`products_mp/products_merchant_ua.xml`): `epicentrk.ua/ua/shop/<slug>.html`.
Контроль на завідомо живих адресах звідти дає 200, тож інструмент справний і
404 у наших карток — справжній, а не наслідок способу запиту.

    python3 tools/epicentr_site_check.py --limit 100
"""
import argparse
import collections
import json
import os
import random
import sys
import time

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
API = 'https://core-api.epicentrm.com.ua'
SITE = 'https://epicentrk.ua/ua/shop/{}.html'
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/140.0 Safari/537.36')


def login():
    s = requests.Session()
    s.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                      'Accept-Language': 'uk-UA'})
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=100)
    ap.add_argument('--pause', type=float, default=1.2)
    ap.add_argument('--out', default=os.path.join(BASE, 'exports', 'epicentr_site_check.json'))
    a = ap.parse_args()

    prods = json.load(open(os.path.join(BASE, 'data', 'epicentr_products.json'),
                           encoding='utf-8'))
    live = [x for x in prods
            if x.get('status') == 'published' and str(x.get('availability')) == '100']
    print(f'живих карток у знімку: {len(live)}', flush=True)
    random.seed(20260929)                    # відтворювана вибірка
    sample = random.sample(live, min(a.limit, len(live)))

    api = login()
    web = requests.Session()
    web.headers.update({'User-Agent': UA, 'Accept-Language': 'uk-UA,uk;q=0.9'})

    codes = collections.Counter()
    rows = []
    for n, x in enumerate(sample, 1):
        try:
            d = api.get(f"{API}/v2/pim/products/{x['id']}", timeout=45).json()
        except Exception as exc:
            print(f'[{n}] {x["sku"]} API збій: {exc}', flush=True)
            continue
        slug = d.get('slug')
        if not slug:
            codes['без slug'] += 1
            continue
        url = SITE.format(slug)
        try:
            code = web.get(url, timeout=30, allow_redirects=True).status_code
        except Exception as exc:
            code = f'збій {type(exc).__name__}'
        codes[code] += 1
        rows.append({'sku': x['sku'], 'name': x.get('name'), 'url': url, 'http': code})
        if n % 10 == 0:
            print(f'  перевірено {n}: {dict(codes)}', flush=True)
        time.sleep(a.pause)

    print(f'\nПІДСУМОК по {len(rows)} картках:')
    for k, v in codes.most_common():
        print(f'   {v:>5}  HTTP {k}')
    json.dump(rows, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('записано:', a.out)


if __name__ == '__main__':
    main()
