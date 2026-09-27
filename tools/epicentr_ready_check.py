"""Які картки справді готові йти на модерацію — за ЖИВИМИ даними кабінету.

Навіщо окремо. 21.09.2026 на модерацію пішли 59 карток лише тому, що в них не
лишилось порожніх обовʼязкових полів, — і жодна не пройшла. Урок: «немає
порожніх» і «готова» це різні твердження, а перехід у `moderating`
**односторонній** (SKILL-20 §3b): назад картку повертає тільки модератор.

Тому тут нічого не відправляється. Лише читання: беремо картку з кабінету,
звіряємо з переліком обовʼязкових атрибутів її набору й кажемо, чого бракує.

    venv/bin/python tools/epicentr_ready_check.py --skus-from exports/epicentr_sets_norm
    venv/bin/python tools/epicentr_ready_check.py --skus-from ... --out exports/epicentr_ready_to_send.json
"""
import argparse
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
MOVABLE = ('enrich', 'draft', 'new')


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


def required_codes(sets, set_code):
    """{код: назва} обовʼязкових атрибутів набору."""
    spec = sets.get(str(set_code)) or {}
    return {str(a['code']): ua(a) for a in spec.get('attributes', []) if a.get('isRequired')}


def check(session, product, sets):
    """Чого бракує картці. Повертає (готова, [назви порожніх], статус)."""
    r = session.get(f"{API}/v2/pim/products/{product['id']}", timeout=45)
    if r.status_code == 401:
        login(session)
        r = session.get(f"{API}/v2/pim/products/{product['id']}", timeout=45)
    r.raise_for_status()
    data = r.json()
    filled = {str(v['code']) for v in (data.get('attributeValues') or [])
              if str(v.get('value') or '').strip()}
    need = required_codes(sets, data.get('attributeSetCode') or product.get('attributeSetCode'))
    missing = [name for code, name in need.items() if code not in filled]
    return (not missing), missing, data.get('status') or product.get('status')


def load_skus(path):
    if os.path.isdir(path):
        skus = set()
        for fn in os.listdir(path):
            if fn.endswith('.json'):
                with open(os.path.join(path, fn), encoding='utf-8') as f:
                    skus |= set(json.load(f))
        return sorted(skus)
    with open(path, encoding='utf-8') as f:
        return sorted(json.load(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skus-from', required=True, help='файл або тека з мапами {sku: {...}}')
    ap.add_argument('--out', help='куди скласти готові {sku: productId}')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    products = {x['sku']: x for x in json.load(open(PRODUCTS, encoding='utf-8'))}
    sets = json.load(open(SETS, encoding='utf-8'))
    skus = [s for s in load_skus(a.skus_from) if s in products]
    if a.limit:
        skus = skus[:a.limit]

    session = requests.Session()
    session.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                            'Accept-Language': 'uk-UA'})
    login(session)

    ready, not_ready, by_missing, by_status = {}, 0, {}, {}
    for i, sku in enumerate(skus, 1):
        try:
            ok, missing, status = check(session, products[sku], sets)
        except Exception as e:
            not_ready += 1
            by_missing[f'помилка читання: {type(e).__name__}'] = \
                by_missing.get(f'помилка читання: {type(e).__name__}', 0) + 1
            continue
        by_status[status] = by_status.get(status, 0) + 1
        # Рухати можна те, що ще редагується. «Чернетка» сюди теж належить:
        # 27.09 після імпорту 653 наші картки опинились саме в ній, і
        # жорсткий фільтр на `enrich` мовчки давав нуль готових.
        if ok and status in MOVABLE:
            ready[sku] = products[sku]['id']
        else:
            not_ready += 1
            for name in (missing or [f'(статус {status})'])[:1]:
                by_missing[name] = by_missing.get(name, 0) + 1
        if i % 100 == 0:
            print(f'  {i}/{len(skus)}', file=sys.stderr, flush=True)

    print(f'\nперевірено: {len(skus)}')
    print(f'ГОТОВІ до модерації: {len(ready)}')
    print(f'не готові: {not_ready}')
    print('статуси:', by_status)
    print('чого бракує найчастіше:')
    for name, n in sorted(by_missing.items(), key=lambda kv: -kv[1])[:12]:
        print(f'  {n:>5}  {name}')
    if a.out and ready:
        with open(a.out, 'w', encoding='utf-8') as f:
            json.dump(ready, f, ensure_ascii=False, indent=1)
        print(f'→ {a.out}')


if __name__ == '__main__':
    main()
