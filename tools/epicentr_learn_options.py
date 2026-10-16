#!/usr/bin/env python3
"""Довідник дозволених значень атрибутів — з наших ЖЕ опублікованих карток.

ЧОМУ ТАК. Значення select-атрибутів Єпіцентру це коди-хеші
(`2f28288483471e27d49a24d09dff8a38`), а не текст. Перелік допустимих кодів
віддає merchant-api, для якого потрібен окремий токен кабінету. Але кожна
опублікована картка несе у `attributeValues[].options[].translations`
українську назву свого значення — тобто довідник уже лежить у даних, які
нам доступні.

Беремо лише ОПУБЛІКОВАНІ картки: їхні значення Єпіцентр прийняв, отже вони
точно дозволені. Чернетки для цього не годяться.

    venv/bin/python tools/epicentr_learn_options.py --sets 7216,8960,6567 --на-набір 30
"""
import argparse
import collections
import json
import os
import re
import sys
import time

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
API = 'https://core-api.epicentrm.com.ua'
OUT = os.path.join(BASE, 'data', 'epicentr_option_dict.json')


def ua(o):
    for t in (o or {}).get('translations', []):
        if t.get('languageCode') in ('ua', 'uk'):
            return t.get('value') or t.get('title')
    for t in (o or {}).get('translations', []):
        return t.get('value') or t.get('title')
    return None


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def noire_skus():
    шлях = next((f for f in (
        os.path.expanduser('~/noire-feed/noire_epicentr_stock.xml'),
        os.path.join(BASE, 'data', 'noire_epicentr_stock.xml')) if os.path.exists(f)), None)
    if not шлях:
        sys.exit('немає фіду Єпіцентру — без нього NOIRE не відділити')
    return set(re.findall(r'<offer id="([^"]+)"', open(шлях, encoding='utf-8').read()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sets', help='коди наборів через кому; без цього — усі, де є enrich')
    ap.add_argument('--на-набір', type=int, default=30, dest='на_набір')
    a = ap.parse_args()

    items = json.load(open(os.path.join(BASE, 'data', 'epicentr_products.json'),
                           encoding='utf-8'))
    наші = noire_skus()
    if a.sets:
        треба = {s.strip() for s in a.sets.split(',')}
    else:
        треба = {str(i.get('attributeSetCode')) for i in items
                 if i.get('status') == 'enrich' and str(i.get('sku')) in наші}
    по_наборах = collections.defaultdict(list)
    for i in items:
        if (i.get('status') == 'published' and str(i.get('sku')) in наші
                and str(i.get('attributeSetCode')) in треба):
            по_наборах[str(i['attributeSetCode'])].append(i)

    s = requests.Session()
    s.headers.update({'Accept': 'application/json', 'Accept-Language': 'uk-UA'})
    login(s)

    довідник = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    for набір, картки in sorted(по_наборах.items(), key=lambda x: -len(x[1])):
        d = довідник.setdefault(набір, {})
        взято = 0
        for p in картки[:a.на_набір]:
            try:
                r = s.get(f"{API}/v2/pim/products/{p['id']}", timeout=45)
                if r.status_code == 401:
                    login(s)
                    r = s.get(f"{API}/v2/pim/products/{p['id']}", timeout=45)
                r.raise_for_status()
            except Exception as e:
                print(f"  {p['id']}: {e}", file=sys.stderr)
                continue
            for v in (r.json().get('attributeValues') or []):
                код = str(v.get('code'))
                поле = d.setdefault(код, {'id': v.get('id'), 'type': v.get('type'),
                                          'значення': {}})
                for o in (v.get('options') or []):
                    назва = ua(o)
                    if назва and not o.get('deleted'):
                        поле['значення'][o.get('code')] = назва
            взято += 1
            time.sleep(0.12)
        print(f'набір {набір}: з {взято} карток зібрано атрибутів {len(d)}, '
              f'значень {sum(len(v["значення"]) for v in d.values())}')
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(довідник, f, ensure_ascii=False, indent=1)
    print('→', OUT)


if __name__ == '__main__':
    main()
