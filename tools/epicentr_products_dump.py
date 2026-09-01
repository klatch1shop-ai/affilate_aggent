"""
tools/epicentr_products_dump.py
================================
Вивантажує всі товари компанії з кабінету Єпіцентру через core-api
у data/epicentr_products.json.

Це ЄДИНЕ джерело правди про наші картки на Єпіцентрі: статус і категорію
призначає їхній категорійний менеджер, і наш фід про це не знає.

Тільки читання. Нічого не змінює. Деталі API — SKILL-20.
"""
import os, sys, json, time, base64
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
API = 'https://core-api.epicentrm.com.ua'
OUT = os.path.join(BASE, 'data', 'epicentr_products.json')
LIMIT = 100


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    tok = r.json()['token']['auth']
    pl = json.loads(base64.urlsafe_b64decode(tok.split('.')[1] + '=='))
    s.headers.update({'Authorization': f'Bearer {tok}',
                      'Accept': 'application/json', 'Accept-Language': 'uk-UA'})
    return pl


def title(obj, lang='ua'):
    for t in (obj or {}).get('translations', []):
        if t.get('languageCode') == lang:
            return t.get('title') or t.get('name')
    return None


def main():
    s = requests.Session()
    pl = login(s)
    print(f"компанія {pl.get('companyId')} | токен до "
          f"{time.strftime('%H:%M', time.localtime(pl.get('exp', 0)))}")
    total = s.get(f'{API}/v2/pim/products/total', timeout=30).json().get('total')
    print(f'усього товарів: {total}')

    items, cursor, seen = [], None, set()
    while True:
        for attempt in range(4):
            try:
                params = {'limit': LIMIT, 'sort[]': 'id'}
                if cursor:
                    params['cursor'] = cursor      # курсорна пагінація, НЕ page
                r = s.get(f'{API}/v2/pim/products', params=params, timeout=60)
                if r.status_code == 401:            # токен протух — перелогін
                    login(s)
                    continue
                r.raise_for_status()
                d = r.json()
                break
            except Exception as e:
                if attempt == 3:
                    print(f'сторінка {page}: {e}', file=sys.stderr)
                    d = None
                    break
                time.sleep(3 * (attempt + 1))
        if not d:
            break
        batch = d.get('items', [])
        if not batch:
            break
        for it in batch:
            aset = it.get('attributeSet') or {}
            items.append({
                'id': it.get('id'),
                'sku': it.get('sku'),
                'status': it.get('status'),
                'name': title(it),
                'attributeSetCode': it.get('attributeSetCode'),
                'attributeSetName': title(aset),
                'brand': (it.get('brand') or {}).get('title')
                         or title(it.get('brand') or {}),
                'completeness': it.get('completeness'),
                'availability': it.get('availability'),
                'price': it.get('price'),
                'createdAt': it.get('createdAt'),
                'updatedAt': it.get('updatedAt'),
                'publishedAt': it.get('publishedAt'),
            })
        if len(items) % 2000 < LIMIT:
            print(f'  {len(items)}/{total}', file=sys.stderr)
        cursor = d.get('next')
        if not cursor or cursor in seen:
            break
        seen.add(cursor)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False)
    print(f'збережено: {len(items)} → {OUT}')


if __name__ == '__main__':
    main()
