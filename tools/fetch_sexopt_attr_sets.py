#!/usr/bin/env python3
"""
Сканує Epicentr PIM API, знаходить 32 attribute-sets для SexOpt-категорій,
зберігає всі атрибути (з is_required) в epicentr_required_attrs_sexopt,
виводить підсумок з оцінкою покриття з sexopt_products.
"""
import os, sys, time, re
import requests
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, '/home/tekken/agent-system')
from shared.utils.db import get_connection

BASE  = 'https://merchant-api.epicentrm.com.ua'
TOKEN = os.getenv('EPICENTR_TOKEN')
H     = {'Authorization': f'Bearer {TOKEN}'}

TARGET_CODES = {
    '7216','9448','9450','9452','9454','9456','9458','9460','9464','9466',
    '9468','9470','9472','9474','9476','9478','9480','9482','9484','9486',
    '9488','9526','9548','9550','9578','9616','9620','9624','9628','9630','9632','9636'
}

# Ключові слова, які можна покрити з sexopt_products
# sexopt має: name, description_html, vendor, country (+ price, sku, pictures)
SEXOPT_FIELDS = {
    'vendor':    ['бренд', 'brand', 'виробник', 'manufacturer', 'торгова марка'],
    'country':   ['країна', 'country', 'країна-виробник', 'країна виробника'],
    'name':      ['назва', 'модель', 'name', 'title', 'найменування'],
    'desc_html': ['опис', 'description', 'комплект', 'склад', 'матеріал', 'колір',
                  'розмір', 'довжина', 'діаметр', 'вага', 'обєм',
                  'потужність', 'живлення', 'батарея', 'waterproof', 'водонепрон',
                  'тип', 'форма', 'стиль', 'особливост'],
}

def can_cover(attr_name: str) -> str:
    """Повертає джерело даних у sexopt_products або '—'."""
    low = attr_name.lower()
    for field, keywords in SEXOPT_FIELDS.items():
        if any(kw in low for kw in keywords):
            return field
    return '—'

def get_name_ua(translations: list) -> str:
    for t in translations:
        if t.get('languageCode') == 'ua':
            return t.get('title', '')
    return ''

def main():
    conn = get_connection()
    cur  = conn.cursor()

    # ── Таблиця ──────────────────────────────────────────────────────────────
    cur.execute('''
        CREATE TABLE IF NOT EXISTS epicentr_required_attrs_sexopt (
            attribute_set_code VARCHAR(50),
            attribute_code     VARCHAR(50),
            attribute_name     TEXT,
            is_required        BOOLEAN,
            attribute_type     VARCHAR(30),
            created_at         TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (attribute_set_code, attribute_code)
        )
    ''')
    cur.execute('TRUNCATE epicentr_required_attrs_sexopt')
    conn.commit()

    # ── Підтягуємо маппінг кодів → назви категорій ───────────────────────────
    cur.execute('''
        SELECT DISTINCT m.attribute_set_code, e.name_ua
        FROM epicentr_category_mapping m
        JOIN epicentr_intimate_categories e ON e.code = m.epicentr_category_code
    ''')
    cat_names = {r['attribute_set_code']: r['name_ua'] for r in cur.fetchall()}

    # ── Сканування API ────────────────────────────────────────────────────────
    found = {}  # code -> {name_ua, attrs:[]}
    print(f'Скануємо /v2/pim/attribute-sets (55 стор.)...')

    for pg in range(1, 56):
        r = requests.get(f'{BASE}/v2/pim/attribute-sets', headers=H,
                         params={'limit': 100, 'page': pg}, timeout=30)
        r.raise_for_status()
        for item in r.json()['items']:
            code = str(item['code'])
            if code in TARGET_CODES:
                found[code] = {
                    'api_name_ua': get_name_ua(item.get('translations', [])),
                    'attrs': item.get('attributes', [])
                }
        if pg % 10 == 0:
            print(f'  page {pg}/55 — знайдено {len(found)}/{len(TARGET_CODES)}')
        if len(found) == len(TARGET_CODES):
            print(f'  Всі {len(TARGET_CODES)} знайдено на сторінці {pg}.')
            break
        time.sleep(0.12)

    missing = TARGET_CODES - set(found.keys())
    if missing:
        print(f'  ⚠️ Не знайдено в API: {sorted(missing)}')

    # ── Запис у БД ────────────────────────────────────────────────────────────
    total_saved = 0
    for code, info in found.items():
        for attr in info['attrs']:
            attr_code = str(attr.get('code', ''))
            attr_type = attr.get('type', '')
            is_req    = bool(attr.get('isRequired', False))
            name_ua   = get_name_ua(attr.get('translations', [])) or attr_code
            cur.execute('''
                INSERT INTO epicentr_required_attrs_sexopt
                    (attribute_set_code, attribute_code, attribute_name, is_required, attribute_type)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (attribute_set_code, attribute_code) DO UPDATE
                    SET attribute_name=EXCLUDED.attribute_name,
                        is_required=EXCLUDED.is_required,
                        attribute_type=EXCLUDED.attribute_type
            ''', (code, attr_code, name_ua, is_req, attr_type))
            total_saved += 1
    conn.commit()
    print(f'Збережено {total_saved} рядків у epicentr_required_attrs_sexopt\n')

    # ── Звіт ──────────────────────────────────────────────────────────────────
    print(f"{'№':>2}  {'code':>6}  {'Категорія Epicentr':<38}  {'Обов':>4}  {'Всього':>6}  {'Обов. атрибути та покриття'}")
    print('─' * 130)

    order = sorted(found.keys(), key=lambda x: int(x))
    for i, code in enumerate(order, 1):
        cat_name    = cat_names.get(code, found[code]['api_name_ua'])
        all_attrs   = found[code]['attrs']
        req_attrs   = [a for a in all_attrs if a.get('isRequired')]
        total_count = len(all_attrs)
        req_count   = len(req_attrs)

        req_details = []
        for a in req_attrs:
            name = get_name_ua(a.get('translations', [])) or str(a.get('code'))
            atype = a.get('type', '?')
            src = can_cover(name)
            req_details.append(f'{name}({atype})[→{src}]')

        details_str = ', '.join(req_details) if req_details else '—'
        print(f"{i:>2}  {code:>6}  {cat_name:<38}  {req_count:>4}  {total_count:>6}  {details_str}")

    print('─' * 130)

    # ── Аналіз покриття ───────────────────────────────────────────────────────
    all_req = []
    for code, info in found.items():
        for a in info['attrs']:
            if a.get('isRequired'):
                name = get_name_ua(a.get('translations', [])) or str(a.get('code'))
                src  = can_cover(name)
                all_req.append({'code': code, 'attr': name, 'type': a.get('type'), 'src': src})

    from collections import Counter
    src_counts = Counter(r['src'] for r in all_req)
    print(f'\nПОКРИТТЯ обов\'язкових атрибутів з sexopt_products:')
    for src, cnt in sorted(src_counts.items(), key=lambda x: -x[1]):
        pct = 100 * cnt / len(all_req) if all_req else 0
        label = {'vendor':'vendor (бренд)','country':'country (країна)',
                 'name':'name (назва)','desc_html':'description_html (текстовий опис)','—':'❌ немає джерела'}.get(src, src)
        print(f'  {label:<40} {cnt:>3} атр. ({pct:.0f}%)')

    print(f'\n  Всього обов. атрибутів: {len(all_req)}')
    no_src = [r for r in all_req if r['src'] == '—']
    if no_src:
        unique_no = sorted(set(r['attr'] for r in no_src))
        print(f'  Без джерела ({len(unique_no)} унікальних): {unique_no}')

    conn.close()

if __name__ == '__main__':
    main()
