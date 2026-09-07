#!/usr/bin/env python3
"""
tools/epicentr_classify_accessories.py
=======================================
Заповнює характеристики аксесуарів: тип аксесуара, матеріал, колір.

Перевірка 02.09.2026 на двох живих картках (ME012 «еластичний бинт»,
BM-VP «набір для ремонту клапана») показала, що категорія 9526 підібрана
ПРАВИЛЬНО: обовʼязкових полів усього 8, бракує 4, і всі вони про сам
аксесуар — «Тип аксесуара», «Основний матеріал», «Колір виробника», «Колір».
Жодного «Типу живлення» чи «Вібрації», як я припускав із загальної
статистики.

Урок, вартий правила: **перш ніж робити висновок про категорію, подивитись
на конкретну картку.** Загальна статистика змішує категорії й створює
хибну картину.

Значення беруться з назви й опису; довідник — `epicentr_options_cache.json`.
Колір у назвах трапляється рідко (5%), тому здебільшого лишається порожнім.

    python3 tools/epicentr_classify_accessories.py --plan
"""
import os, sys, re, json, time, argparse, collections
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.db import get_connection
API = 'https://core-api.epicentrm.com.ua'

# тип аксесуара — за провідним словом назви
TYPE_RULES = [
    (r'адаптер|перехідник|connect', 'адаптер'),
    (r'набір\s+для\s+ремонт|ремкомплект|^набір|комплект', 'набір'),
    (r'кріпленн|mount|присоск.*кріп|тримач\s+для\s+душ', 'кріплення'),
    (r'тримач|holder', 'тримач'),
    (r'чохол|кейс|футляр|сумк|case', 'чохол для зберігання'),
    (r'підставк|ложе|майданчик|stand', 'підставка'),
    (r'нагрівач|підігрівач|warmer', 'нагрівач'),
    (r'сушарк|dryer', 'сушарка'),
    (r'зарядн\w*\s+кабел|usb[-\s]?кабел', 'зарядний кабель'),
    (r'зарядн\w*\s+пристр|зарядк', 'зарядний пристрій'),
    (r'док[-\s]?станц', 'док-станція'),
    (r'пульт', 'пульт керування'),
    (r'фіксатор|бинт|стрічк', 'фіксатор'),
    (r'насадк|рукав|sleeve', 'насадка'),
    (r'кільц\w*\s*o-?ring|o-?ring', 'кільце o-ring'),
    (r'трусик|harness.*трус', 'трусики'),
    (r'ремінь|ремен|strap', 'ремінь'),
    (r'аплікатор', 'аплікатор для введення лубриканту'),
    (r'магнітн\w+\s+замок', 'магнітний замок для вібратора'),
]
MAT_RULES = [
    (r'нержавіюч\w+\s+стал', 'нержавіюча сталь'),
    (r'медичн\w+\s+силікон', 'медичний силікон'),
    (r'силікон', 'силікон'),
    (r'боросилікатн', 'боросилікатне скло'),
    (r'\bскл[оя]\b|glass', 'скло'),
    (r'алюміні', 'алюміній'),
    (r'\bметал', 'метал'),
    (r'натуральн\w+\s+шкір', 'натуральна шкіра'),
    (r'екошкір|шкірозамін', 'екошкіра'),
    (r'латекс', 'латекс'),
    (r'\bгум[аи]\b|каучук', 'гума'),
    (r'нейлон', 'нейлон'),
    (r'поліестер', 'поліестер'),
    (r'поліпропілен', 'поліпропілен'),
    (r'полікарбонат', 'полікарбонат'),
    (r'\btpe\b', 'tpe'),
    (r'\btpu\b', 'tpu'),
    (r'\bpvc\b|пвх', 'pvc'),
    (r'abs[-\s]?пластик|\babs\b', 'abs пластик'),
    (r'бинт|тканин|текстил|нейлонов', 'текстиль'),
    (r'пластик', 'пластик (abs)'),
]
COLOR_RULES = [
    (r'чорн|black', 'чорний'), (r'біл(?:ий|а|е)|white', 'білий'),
    (r'червон|red\b', 'червоний'), (r'рожев|pink', 'рожевий'),
    (r'фіолетов|purple|violet', 'фіолетовий'), (r'син[ій]|blue', 'синій'),
    (r'блакитн', 'блакитний'), (r'зелен|green', 'зелений'),
    (r'сір(?:ий|а)|gray|grey', 'сірий'), (r'бежев|beige', 'бежевий'),
    (r'золот|gold', 'золото'), (r'коричнев|brown', 'коричневий'),
    (r'помаранч|orange', 'помаранчевий'), (r'різнокольор|multi', 'різнокольоровий'),
]
BY_ATTR = {'тип аксесуара': TYPE_RULES, 'тип аксесуару': TYPE_RULES,
           'основний матеріал': MAT_RULES, 'матеріал': MAT_RULES,
           'колір': COLOR_RULES, 'колір виробника': COLOR_RULES}


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def decide(attr, name, desc, allowed):
    rules = BY_ATTR.get((attr or '').lower())
    if not rules:
        return None
    # тип шукаємо у назві (провідне слово), матеріал і колір — усюди
    scope = name if 'тип' in (attr or '').lower() else name + ' ' + desc
    for pat, val in rules:
        if re.search(pat, scope, re.I):
            for a in allowed:
                if a.lower() == val:
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
    sel = [g for g in gaps
           if 'Аксесуари' in (prods.get(g['id'], {}).get('attributeSetName') or '')
           and prods.get(g['id'], {}).get('status') == 'enrich']
    print(f'аксесуарів із прогалинами: {len(sel)}')

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
    for g in todo:
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
            print(f'  {g["sku"]}: {r2.status_code} {r2.text[:400]}', file=sys.stderr)
        time.sleep(0.15)

    print(f'\n{"порахував" if a.plan else "записано"} карток: {ok} | не вдалось: {fail}')
    for k, v in picked.most_common(14):
        print(f'   {v:5}  {k}')
    for k, v in stat.most_common(4):
        print(f'   [{v}]  {k}')


if __name__ == '__main__':
    main()
