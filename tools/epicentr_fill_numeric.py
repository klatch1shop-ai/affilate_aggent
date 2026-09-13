#!/usr/bin/env python3
"""
tools/epicentr_fill_numeric.py
===============================
Заповнює числові обовʼязкові характеристики Єпіцентру з тексту самого товару.

Підстава — дослід 02.09.2026 (ідея власника): на картці SX0811 з 21 прогалиною
пошук у конкурента дав лише 4 поля, і два з них («чорний», «силіконовий»)
стояли просто в НАЗВІ нашого ж товару. Реальний виграш зовнішнього пошуку —
два числа: довжина й діаметр.

Замір по всіх 1760 картках із прогалинами: **470 (27%) мають числовий
показник у власному тексті** — діаметр 303, довжина 261, вага 69.
Тобто дешеве джерело було під рукою.

Одиниці зводимо до тих, що очікує довідник Єпіцентру (мм для довжин, г для
ваги, мл для обʼєму) — інакше значення приймається, але означає інше.

    python3 tools/epicentr_fill_numeric.py --plan
    python3 tools/epicentr_fill_numeric.py [--limit N]
"""
import os, sys, re, json, time, argparse, collections
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.db import get_connection
API = 'https://core-api.epicentrm.com.ua'

# назва характеристики Єпіцентру → (регулярка, одиниця довідника)
RULES = [
    ('робоча довжина',      r'робоч\w*\s+довжин\w*[\s:–-]*([\d]+[.,]?\d*)\s*(см|мм)', 'мм'),
    ('загальна довжина',    r'(?:загальн\w*\s+)?довжин\w*[\s:–-]*([\d]+[.,]?\d*)\s*(см|мм)', 'мм'),
    ('довжина',             r'довжин\w*[\s:–-]*([\d]+[.,]?\d*)\s*(см|мм)', 'мм'),
    ('максимальний діаметр', r'(?:макс\w*\.?\s+)?діаметр[\s:–-]*([\d]+[.,]?\d*)\s*(см|мм)', 'мм'),
    ('мінімальний діаметр', r'мін\w*\.?\s+діаметр[\s:–-]*([\d]+[.,]?\d*)\s*(см|мм)', 'мм'),
    ('діаметр',             r'діаметр[\s:–-]*([\d]+[.,]?\d*)\s*(см|мм)', 'мм'),
    ('вага',                r'вага[\s:–-]*([\d]+[.,]?\d*)\s*(г|кг)', 'г'),
    ('обʼєм',               r'об[\x27’ʼ]?[єе]м[\s:–-]*([\d]+[.,]?\d*)\s*(мл|л)', 'мл'),
    ("об'єм",               r'об[\x27’ʼ]?[єе]м[\s:–-]*([\d]+[.,]?\d*)\s*(мл|л)', 'мл'),
]
FACTOR = {('см', 'мм'): 10, ('мм', 'мм'): 1, ('кг', 'г'): 1000, ('г', 'г'): 1,
          ('л', 'мл'): 1000, ('мл', 'мл'): 1}


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def extract(name, text):
    """Значення для характеристики `name` з тексту, зведене до одиниці довідника."""
    low = (name or '').lower().strip()
    for key, pat, unit in RULES:
        if low != key:
            continue
        m = re.search(pat, text, re.I)
        if not m:
            return None
        try:
            val = float(m.group(1).replace(',', '.'))
        except ValueError:
            return None
        k = FACTOR.get((m.group(2).lower(), unit))
        if not k:
            return None
        v = val * k
        return int(v) if abs(v - int(v)) < 1e-6 else round(v, 2)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    gaps = json.load(open(os.path.join(BASE, 'docs', 'epicentr_remaining_gaps.json'),
                          encoding='utf-8'))
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""select sku, name, coalesce(regexp_replace(description_html,'<[^>]+>',' ','g'),'') d
                   from sexopt_products where sku = any(%s)""", ([g['sku'] for g in gaps],))
    txt = {r['sku']: ((r['name'] or '') + ' ' + (r['d'] or '')) for r in cur.fetchall()}
    cur.close(); conn.close()

    s = requests.Session()
    s.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                      'Accept-Language': 'uk-UA'})
    login(s)
    form_cache = {}

    def form_ids(cat):
        if cat not in form_cache:
            r = s.get(f'{API}/v2/pim/products/forms/attribute-set/by-code/{cat}/attributes',
                      timeout=40)
            items = r.json().get('items', []) if r.status_code == 200 else []
            form_cache[cat] = {str(x['code']): x for x in items}
        return form_cache[cat]

    todo = gaps[:a.limit] if a.limit else gaps
    ok = fail = 0
    stat = collections.Counter(); names = collections.Counter()
    for i, g in enumerate(todo, 1):
        t = txt.get(g['sku'])
        if not t:
            stat['немає тексту'] += 1; continue
        want = {}
        for m in g['missing']:
            v = extract(m.get('name'), t)
            if v is not None:
                want[str(m['code'])] = (m.get('name'), v)
        if not want:
            stat['числових даних у тексті немає'] += 1; continue
        try:
            d = s.get(f"{API}/v2/pim/products/{g['id']}", timeout=45)
            if d.status_code == 401:
                login(s); d = s.get(f"{API}/v2/pim/products/{g['id']}", timeout=45)
            d = d.json()
        except Exception:
            fail += 1; continue
        if d.get('status') != 'enrich':
            stat['уже не enrich'] += 1; continue
        cur_vals = [{'id': v['id'], 'code': v['code'], 'value': v['value']}
                    for v in (d.get('attributeValues') or [])]
        have = {str(v['code']) for v in cur_vals if v.get('value') not in (None, '', [])}
        fids = form_ids(str(d.get('attributeSetCode')))
        added = 0
        for code, (nm, val) in want.items():
            if code in have:
                continue
            spec = fids.get(code)
            if not spec:
                stat['немає у формі'] += 1; continue
            if spec.get('type') not in ('float', 'int', 'number', 'decimal'):
                stat[f"поле не числове: {nm}"] += 1; continue
            cur_vals.append({'id': spec['id'], 'code': code, 'value': val})
            names[nm] += 1; added += 1
        if not added:
            stat['нічого додати'] += 1; continue
        if a.plan:
            ok += 1; continue
        body = {'attributeValues': cur_vals, 'categories': d.get('categories'),
                'isPrepayment': d.get('isPrepayment'), 'media': d.get('media'),
                'productInPromotion': d.get('productInPromotion'),
                'attributeSetCode': d.get('attributeSetCode'),
                'companyId': d.get('companyId'), 'sku': d.get('sku'),
                'translations': d.get('translations')}
        r2 = s.put(f'{API}/v4/pim/products/common/{g["id"]}', json=body, timeout=60)
        if r2.status_code in (200, 201, 204):
            ok += 1
        else:
            fail += 1
            print(f'  {g["sku"]}: {r2.status_code} {r2.text[:220]}', file=sys.stderr)
        time.sleep(0.15)
        if i % 200 == 0:
            print(f'  {i}/{len(todo)} — карток {ok}', file=sys.stderr)

    print(f'\n{"порахував" if a.plan else "записано"} карток: {ok} | не вдалось: {fail}')
    print('яких полів:')
    for k, v in names.most_common(10):
        print(f'   {v:5}  {k}')
    print('чому пропущено:')
    for k, v in stat.most_common(6):
        print(f'   {v:5}  {k}')


if __name__ == '__main__':
    main()
