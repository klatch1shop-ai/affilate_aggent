#!/usr/bin/env python3
"""
tools/epicentr_classify_cosmetics.py
=====================================
Заповнює характеристики косметичних засобів (олії, свічки, засоби для
орального сексу) за назвою та складом.

Правила з товарознавчого визначення, отриманого власником 02.09.2026:

* **«Стать» — це навігаційна категорія, не біологічна.** Базове значення для
  90% олій — «унісекс». «Для жінок» ставлять за словами Woman/Lady/For Her
  або жіночими компонентами; «для чоловіків» — за Men/For Him, сандалом,
  кедром, мускусом, імбиром, чорним перцем.
* **«Основа засобу» визначається ПЕРШИМИ інгредієнтами INCI**, бо вони мають
  найбільшу частку: Aqua → водна; олії → масляна; -dimethicone/-siloxane →
  силіконова; Glycerin/Propylene Glycol → гліцеринова.
* **«Аромат»**: немає Parfum/Fragrance і ефірних олій → «без аромату».
  Інакше — з назви продукту або з екстракту у складі.
* **«Тип засобу»** — за формою випуску: олія, гель (Carbomer, Xanthan),
  крем/емульсія (емульгатори), спрей.

Загальне правило звідти ж: порожнє краще за «Інше», бо «Інше» шкодить
фільтрам і покупці його не обирають.

    python3 tools/epicentr_classify_cosmetics.py --plan
"""
import os, sys, re, json, time, argparse, collections
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.db import get_connection
API = 'https://core-api.epicentrm.com.ua'

MALE = re.compile(r'\bfor\s+him\b|\bmen\b|чоловіч|сандал|кедр|мускус|імбир|'
                  r'чорн\w+\s+перц|black\s+pepper|sandalwood', re.I)
FEMALE = re.compile(r'\bfor\s+her\b|\bwoman\b|\blady\b|жіноч|троянд|rose\b|'
                    r'примул|шавлі|clary\s+sage', re.I)
BASE_RULES = [
    (r'\baqua\b|\bwater\b|^вод', 'водна'),
    (r'dimethicone|siloxane|cyclopenta', 'силіконова'),
    (r'\boil\b|олі[яйї]|helianthus|prunus|simmondsia|paraffinum|cocos\s+nucifera', 'масляна'),
    (r'glycerin|propylene\s+glycol|гліцерин', 'гліцеринова'),
]
TYPE_RULES = [
    (r'свічк|candle', 'свічка'),
    (r'\bспрей\b|spray|розпилюв', 'спрей'),
    (r'\bгель\b|\bgel\b|carbomer|xanthan', 'гель'),
    (r'\bкрем\b|cream|емульс|lotion|cetearyl|glyceryl\s+stearate', 'крем'),
    (r'\bолі[яйї]\b|\boil\b|масл', 'олія'),
]
AROMA = [
    (r'ванільн|ваніл|vanilla', 'ваніль'), (r'полуни|strawberry', 'полуниця'),
    (r'шоколад|chocolate|какао|cocoa', 'шоколад'), (r'кокос|coconut', 'кокос'),
    (r'лаванд|lavender', 'лаванда'), (r'троянд|rose\b', 'троянда'),
    (r'м[ʼ\x27’]ят|mint|ментол|menthol', 'м’ята'), (r'вишн|cherry', 'вишня'),
    (r'кав[аи]|coffee', 'кава'), (r'цитрус|лимон|апельсин|citrus|orange', 'цитрус'),
]
NO_AROMA = re.compile(r'без\s+аромат|без\s+запах|нейтральн\w+\s+аромат|fragrance[-\s]?free', re.I)
HAS_PARFUM = re.compile(r'parfum|fragrance|ароматизатор|ефірн\w+\s+олі', re.I)


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def pick(rules, txt):
    for pat, val in rules:
        if re.search(pat, txt, re.I):
            return val
    return None


def decide(attr, name, desc, allowed):
    full = name + ' ' + desc
    if attr == 'Стать':
        if MALE.search(full) and not FEMALE.search(full):
            v = 'для чоловіків'
        elif FEMALE.search(full) and not MALE.search(full):
            v = 'для жінок'
        else:
            v = 'унісекс'                    # базове для 90% засобів
    elif attr == 'Основа засобу':
        v = pick(BASE_RULES, full)
    elif attr in ('Тип засобу', 'Тип'):
        v = pick(TYPE_RULES, full)
    elif attr == 'Аромат':
        if NO_AROMA.search(full):
            v = 'без аромату'
        else:
            v = pick(AROMA, full)
            if not v and not HAS_PARFUM.search(full):
                v = 'без аромату'
    else:
        return None
    if not v:
        return None
    for a in allowed:
        if a.lower() == v.lower():
            return a
    # синоніми довідника: «унісекс» ↔ «універсальний»
    if v == 'унісекс':
        for a in allowed:
            if 'універсал' in a.lower() or 'уніс' in a.lower():
                return a
    return None


# Значення multiselect-атрибута надсилається МАСИВОМ, скалярне дає
# 400 «attributeValues[<код>]: validation…». Помилка адресує атрибут за
# КОДОМ, а не за індексом у масиві: `attributeValues[78]` — це «Колір
# виробника» (код 78), єдиний multiselect у наборі 9526. Через це 112 із
# 130 записів аксесуарів упали 02.09.2026.
def _wrap(spec, value):
    """Приводить значення до форми, якої чекає атрибут даного типу."""
    return [value] if (spec or {}).get('type') == 'multiselect' else value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    gaps = json.load(open(os.path.join(BASE, 'docs', 'epicentr_enrich_gaps.json'),
                          encoding='utf-8'))
    prods = {x['id']: x for x in json.load(
        open(os.path.join(BASE, 'data', 'epicentr_products.json'), encoding='utf-8'))}
    opts = json.load(open(os.path.join(BASE, 'data', 'epicentr_options_cache.json'),
                          encoding='utf-8'))
    CATS = ('Засоби для еротичного масажу', 'Свічки для інтимного масажу',
            'Олія для еротичного масажу', 'Засоби для орального сексу',
            'Збуджуючі засоби', 'Еротичні масажні олії та косметика')
    sel = [g for g in gaps
           if (prods.get(g['id'], {}).get('attributeSetName') or '') in CATS
           and prods.get(g['id'], {}).get('status') == 'enrich']
    print(f'косметичних карток із прогалинами: {len(sel)}')

    conn = get_connection(); cur = conn.cursor()
    cur.execute("""select sku, name, coalesce(regexp_replace(description_html,'<[^>]+>',' ','g'),'') d
                   from sexopt_products where sku = any(%s)""", ([g['sku'] for g in sel],))
    txt = {r['sku']: ((r['name'] or ''), (r['d'] or '')) for r in cur.fetchall()}
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

    todo = sel[:a.limit] if a.limit else sel
    ok = fail = 0; picked = collections.Counter(); stat = collections.Counter()
    for i, g in enumerate(todo, 1):
        pair = txt.get(g['sku'])
        if not pair:
            stat['немає тексту'] += 1; continue
        name, desc = pair
        cat = str(g['category'])
        want = {}
        for m in g['missing']:
            allowed = opts.get(f"{cat}:{m['code']}")
            if not isinstance(allowed, dict):
                continue
            v = decide(m.get('name'), name, desc, list(allowed))
            if v:
                want[str(m['code'])] = (m['name'], v, allowed[v])
        if not want:
            stat['правило не спрацювало'] += 1; continue
        if a.plan:
            ok += 1
            for _, (nm, v, _c) in want.items():
                picked[f'{nm}={v}'] += 1
            continue
        try:
            d = s.get(f"{API}/v2/pim/products/{g['id']}", timeout=45)
            if d.status_code == 401:
                login(s); d = s.get(f"{API}/v2/pim/products/{g['id']}", timeout=45)
            d = d.json()
        except Exception:
            fail += 1; continue
        if d.get('status') != 'enrich':
            stat['уже не enrich'] += 1; continue
        cur_v = [{'id': v['id'], 'code': v['code'], 'value': v['value']}
                 for v in (d.get('attributeValues') or [])]
        have = {str(v['code']) for v in cur_v if v.get('value') not in (None, '', [])}
        fids = form_ids(cat)
        added = 0
        for code, (nm, v, vcode) in want.items():
            if code in have or code not in fids:
                continue
            cur_v.append({'id': fids[code]['id'], 'code': code,
                          'value': _wrap(fids[code], vcode)})
            picked[f'{nm}={v}'] += 1; added += 1
        if not added:
            stat['нічого додати'] += 1; continue
        body = {'attributeValues': cur_v, 'categories': d.get('categories'),
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
            print(f'  {g["sku"]}: {r2.status_code} {r2.text[:180]}', file=sys.stderr)
        time.sleep(0.15)

    print(f'\n{"порахував" if a.plan else "записано"} карток: {ok} | не вдалось: {fail}')
    for k, v in picked.most_common(14):
        print(f'   {v:5}  {k}')
    for k, v in stat.most_common(4):
        print(f'   [{v}]  {k}')


if __name__ == '__main__':
    main()
