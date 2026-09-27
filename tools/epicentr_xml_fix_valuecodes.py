"""Виправляє `valuecode` у згенерованому XML за опублікованими картками.

Привід (27.09.2026, реальний імпорт): із 578 товарів створено 275, а 303 впали
з помилкою «Значення "13949" по характеристиці "Стать" відсутнє в довіднику».
13949 — це код САМОЇ характеристики, а не її значення: генератор писав
`valuecode="{paramcode}"` для 495 параметрів. Ще частина несла довгі хеші з
`/options`, які майданчик теж не приймає.

Джерело правильних кодів — **опубліковані картки того самого набору**: там
значення вже пройшли модерацію, а в тілі відповіді API кожне несе і свій код,
і український переклад. Це те саме відкриття, що дозволило закрити 1492 картки.

Параметр, для якого коду не знайшлось, **вилучається** з offer: краще картка
без необовʼязкової характеристики, ніж 303 відмови.

    venv/bin/python tools/epicentr_xml_fix_valuecodes.py \
        --xml exports/epicentr_new_cards_ready.xml \
        --out exports/epicentr_new_cards_fixed.xml
"""
import argparse
import collections
import concurrent.futures as cf
import json
import os
import re
import sys

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

API = 'https://core-api.epicentrm.com.ua'
PRODUCTS = os.path.join(BASE, 'data', 'epicentr_products.json')
# Числові й текстові характеристики: у них немає довідника, значення йде як є.
PLAIN = {'measure', 'ratio', 'brand', 'country_of_origin', 'weight', 'width',
         'height', 'length', 'description'}
# Зі звіту реального імпорту 27.09: саме ці значення майданчик не прийняв.
BROKEN_ATTRS = {'Матеріал'}
BAD_CODES = {'de9da78728b8771e050b3332f862fc94', '8c64e0f6c6e6e47cddf4249588d6e260',
             '35d73f60d46d4a4871e86947088e318c', '063a479f96ed369ac655b2d6e90f216b'}


def login(session):
    r = session.post(f'{API}/v2/users/login',
                     json={'login': os.getenv('EPICENTR_EMAIL'),
                           'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    session.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def ua(obj):
    for t in (obj or {}).get('translations', []):
        if t.get('languageCode') == 'ua':
            return t.get('value') or t.get('title')
    return None


def learn(session, products, set_code, sample):
    """{код атрибута: {українська назва значення: код значення}} з опублікованих."""
    pool = [p for p in products if p.get('status') == 'published'
            and str(p.get('attributeSetCode')) == str(set_code)][:sample]
    table = collections.defaultdict(dict)

    def fetch(p):
        try:
            return session.get(f"{API}/v2/pim/products/{p['id']}", timeout=45).json()
        except Exception:
            return None

    with cf.ThreadPoolExecutor(max_workers=6) as pool_ex:
        for data in pool_ex.map(fetch, pool):
            for v in ((data or {}).get('attributeValues') or []):
                for option in (v.get('options') or []):
                    name = ua(option)
                    if name:
                        table[str(v['code'])][name.strip().casefold()] = option['code']
    return table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--xml', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--sample', type=int, default=80)
    ap.add_argument('--report', default=os.path.join(BASE, 'exports', 'valuecode_fix.csv'))
    a = ap.parse_args()

    text = open(a.xml, encoding='utf-8').read()
    products = json.load(open(PRODUCTS, encoding='utf-8'))
    sets = sorted({m for m in re.findall(r'<attribute_set code="(\d+)"', text)})

    session = requests.Session()
    session.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                            'Accept-Language': 'uk-UA'})
    login(session)

    tables = {}
    for set_code in sets:
        tables[set_code] = learn(session, products, set_code, a.sample)
        print(f'  набір {set_code}: довідників {len(tables[set_code])}', flush=True)

    stats = collections.Counter()
    unresolved = collections.Counter()

    def fix_offer(match):
        offer = match.group(0)
        set_code = re.search(r'<attribute_set code="(\d+)"', offer)
        table = tables.get(set_code.group(1) if set_code else '', {})

        def fix_param(pm):
            whole = pm.group(0)
            name, code, current, value = pm.group(1), pm.group(2), pm.group(3), pm.group(4)
            if code in PLAIN:
                stats['без довідника — лишаємо'] += 1
                return whole
            # Точкове втручання. 275 карток імпортувались успішно САМЕ з цими
            # кодами, тож переписувати все підряд означало б зламати те, що
            # працює. Чіпаємо лише те, що звіт імпорту назвав помилковим:
            # valuecode, рівний коду характеристики, і перелічені матеріали.
            broken = (current == code) or (name in BROKEN_ATTRS and current in BAD_CODES)
            if not broken:
                stats['не чіпаємо (працює)'] += 1
                return whole
            options = table.get(code)
            correct = options.get((value or '').strip().casefold()) if options else None
            if correct:
                stats['виправлено'] += 1
                return (f'<param name="{name}" paramcode="{code}" '
                        f'valuecode="{correct}">{value}</param>')
            # Коду немає серед того, що пройшло модерацію — прибираємо параметр.
            stats['прибрано (немає в довіднику)'] += 1
            unresolved[f'{name} = {value}'] += 1
            return ''

        fixed = re.sub(r'<param name="([^"]+)" paramcode="([^"]+)"'
                       r'(?: valuecode="([^"]*)")?>([^<]*)</param>', fix_param, offer)
        return re.sub(r'\n\s*\n', '\n', fixed)

    out = re.sub(r'  <offer .*?  </offer>', fix_offer, text, flags=re.DOTALL)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(out)

    for key, n in stats.most_common():
        print(f'  {n:>6}  {key}')
    print('\nнайчастіше не знайшлось:')
    for key, n in unresolved.most_common(12):
        print(f'  {n:>5}  {key}')
    with open(a.report, 'w', encoding='utf-8') as f:
        f.write('значення,кількість\n')
        for key, n in unresolved.most_common():
            f.write(f'"{key}",{n}\n')
    print(f'\n→ {a.out}\n→ {a.report}')


if __name__ == '__main__':
    main()
