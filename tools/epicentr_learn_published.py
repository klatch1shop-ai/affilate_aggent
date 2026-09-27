"""Вчиться в уже опублікованих карток: що заповнювати і якими значеннями.

Знайдено 27.09.2026 методом `finding-solutions`: ми заповнювали не ті
характеристики. У наборі 7216 обовʼязкових виявилось 13, а не 4, і сім із
них — практично константи («Одиниця виміру» одне значення на 120 карток,
«Мінімальна кратність» одне). Тобто половина роботи робиться копіюванням,
без жодної моделі.

Опубліковані картки вже пройшли модерацію, тож їхні значення гарантовано
дійсні для довідника — на відміну від будь-чого, що вигадає модель.

Нічого не пише. Складає зразок: для кожного набору — обовʼязкові атрибути,
які значення в них трапляються і наскільки вони сталі.

    venv/bin/python tools/epicentr_learn_published.py --sets 7216,8743 --sample 120
    venv/bin/python tools/epicentr_learn_published.py --all --out exports/epicentr_templates.json
"""
import argparse
import collections
import concurrent.futures as cf
import json
import os
import sys

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

API = 'https://core-api.epicentrm.com.ua'
PRODUCTS = os.path.join(BASE, 'data', 'epicentr_products.json')
SETS = os.path.join(BASE, 'data', 'epicentr_attribute_sets.json')
# Частка, з якої значення вважається сталим для набору. 0.9 обрано свідомо
# високою: підставити «майже завжди таке» значення в чужу картку — це рівно
# той різновид здогаду, через який 21.09 на модерацію пішло 59 непридатних.
CONSTANT_SHARE = 0.9


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


def flat(value):
    """Значення бувають списками (багатозначні атрибути) і словниками."""
    items = value if isinstance(value, list) else [value]
    out = []
    for it in items:
        if isinstance(it, (dict, list)):
            it = json.dumps(it, ensure_ascii=False)
        if str(it or '').strip():
            out.append(str(it))
    return out


def learn(session, products, set_code, sample):
    """Що трапляється в опублікованих картках набору."""
    pool = [p for p in products if p.get('status') == 'published'
            and str(p.get('attributeSetCode')) == str(set_code)][:sample]
    if not pool:
        return None

    def fetch(p):
        try:
            return session.get(f"{API}/v2/pim/products/{p['id']}", timeout=45).json()
        except Exception:
            return None

    used = collections.defaultdict(collections.Counter)
    seen = 0
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for data in ex.map(fetch, pool):
            if not data:
                continue
            seen += 1
            for v in (data.get('attributeValues') or []):
                for item in flat(v.get('value')):
                    used[str(v['code'])][item] += 1
    return used, seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sets', help='коди через кому')
    ap.add_argument('--all', action='store_true', help='усі набори, де є картки в enrich')
    ap.add_argument('--sample', type=int, default=120, help='скільки опублікованих вивчати')
    ap.add_argument('--min-samples', type=int, default=10)
    ap.add_argument('--out', help='куди скласти зразки')
    a = ap.parse_args()

    products = json.load(open(PRODUCTS, encoding='utf-8'))
    sets = json.load(open(SETS, encoding='utf-8'))
    enrich = collections.Counter(str(p.get('attributeSetCode')) for p in products
                                 if p.get('status') == 'enrich')
    if a.sets:
        codes = [c.strip() for c in a.sets.split(',') if c.strip()]
    elif a.all:
        codes = [c for c, _ in enrich.most_common()]
    else:
        sys.exit('потрібен --sets або --all')

    session = requests.Session()
    session.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                            'Accept-Language': 'uk-UA'})
    login(session)

    templates, total_const = {}, 0
    for code in codes:
        spec = sets.get(code)
        if not spec:
            continue
        got = learn(session, products, code, a.sample)
        if not got:
            continue
        used, seen = got
        if seen < a.min_samples:
            print(f'  набір {code}: лише {seen} зразків — пропускаю', flush=True)
            continue
        names = {str(at['code']): ua(at) for at in spec['attributes']}
        required = {str(at['code']) for at in spec['attributes'] if at.get('isRequired')}
        const, variable = {}, {}
        for attr_code in required:
            counter = used.get(attr_code)
            if not counter:
                continue
            value, n = counter.most_common(1)[0]
            if n / seen >= CONSTANT_SHARE:
                const[attr_code] = {'назва': names.get(attr_code), 'значення': value,
                                    'частка': round(n / seen, 3)}
            else:
                variable[attr_code] = {'назва': names.get(attr_code),
                                       'варіанти': counter.most_common(25)}
        templates[code] = {'вивчено': seen, 'у_наповненні': enrich.get(code, 0),
                           'сталі': const, 'змінні': variable}
        total_const += len(const) * enrich.get(code, 0)
        print(f'  набір {code}: зразків {seen}, у наповненні {enrich.get(code, 0)}, '
              f'сталих {len(const)}, змінних {len(variable)}', flush=True)

    print(f'\nнаборів вивчено: {len(templates)}')
    print(f'значень, які можна заповнити копіюванням: ~{total_const}')
    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, 'w', encoding='utf-8') as f:
            json.dump(templates, f, ensure_ascii=False, indent=1)
        print(f'→ {a.out}')


if __name__ == '__main__':
    main()
