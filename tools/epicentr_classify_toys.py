#!/usr/bin/env python3
"""
tools/epicentr_classify_toys.py
================================
Виводить «Вид», «Конструкція», «Призначення» з назви й опису товару.

Правила взяті з товарознавчого визначення, отриманого власником 02.09.2026.
Головне в ньому — три речі, які знімають неоднозначність:

1. «ВИД — ЦЕ ФОРМА, А НЕ ВІДЧУТТЯ.» Реалістичний = імітує анатомію (голівка,
   вени, складки, кібершкіра). Нереалістичний = абстрактний силует без
   біологічних атрибутів. Тому «реалістичні відчуття» в описі — НЕ ознака:
   саме на цьому ми вже помилялись 96 разів (SKILL-21).

2. **Базове значення «Конструкція» — односторонні.** Віброкулі та віброяйця
   належать саме сюди: одна робоча зона, немає ні розгалужень, ні двох
   протилежних кінців. Це не здогад, а правило «від протилежного».

3. **Анальне впізнається за ОБМЕЖУВАЧЕМ.** Анальні іграшки без широкої
   основи не виготовляються — це питання безпеки. Тому «широка основа»,
   «стопор», «обмежувач» — надійніша ознака, ніж слово «анальний» у тексті.

Загальне правило для незастосовних полів (звідти ж): якщо поле обовʼязкове —
ставити базове значення, а не «інше»; «інше» шкодить фільтрам і покупці його
не обирають.

    python3 tools/epicentr_classify_toys.py --plan
    python3 tools/epicentr_classify_toys.py [--limit N]
"""
import os, sys, re, json, time, argparse, collections
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.db import get_connection
API = 'https://core-api.epicentrm.com.ua'

# ── ВИД: анатомічна деталізація, не відчуття ───────────────────────────────
REAL = re.compile(
    r'реалістичн\w*\s+(?:фалоімітатор|вібратор|форм|дизайн|копі)|'
    r'з\s+венами|вен(?:ами|ки)\b|голівк|зліпк|кібершкір|cyberskin|'
    r'ultraskyn|realistic|анатоміч|імітує\s+(?:справжн|чолові)|'
    r'схож\w+\s+на\s+справжн|тілесн\w+\s+кол', re.I)
# «реалістичні відчуття/ефект» — про стимуляцію, а не про форму
REAL_FALSE = re.compile(r'реалістичн\w*\s+(?:відчут|ефект|емоц|стимул|насолод|враж)', re.I)

# ── КОНСТРУКЦІЯ ────────────────────────────────────────────────────────────
DOUBLE = re.compile(r'кролик|rabbit|з\s+відростк|вушк[аи]|додатков\w+\s+відросток|'
                    r'клітор\w*\s+відросток|одночасн\w+\s+стимуляц\w+\s+двох', re.I)
TWOSIDE = re.compile(r'двосторонн|з\s+двох\s+бок|обидва\s+кінц|два\s+робоч\w+\s+кінц', re.I)
SCROTUM = re.compile(r'з\s+мошонк|з\s+яєчк', re.I)

# ── ПРИЗНАЧЕННЯ ────────────────────────────────────────────────────────────
PURPOSE = [
    (r'3\s*в\s*1|три\s+в\s+одн', 'cтимуляція 3 в 1'),
    (r'вагінально[-\s]?анальн', 'вагінально-анальні'),
    (r'вагінально[-\s]?клітор|кролик|rabbit|відросток\w*\s+для\s+клітор', 'вагінально-кліторні'),
    (r'точк\w*\s*g\b|точки\s+g|g[-\s]?spot|для\s+точки', 'для точки G'),
    # анальне — за обмежувачем, це ознака безпеки й тому надійна
    (r'широк\w+\s+основ|обмежувач|стопор|анальн', 'анальні'),
    (r'клітор|вакуумн\w+\s+стимул|безконтактн|на\s+палець|трояндочк', 'кліторні'),
    (r'вагінальн|піхв|проникненн|введенн', 'вагінальні'),
]


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def decide(name, text, attr, allowed):
    """Значення для характеристики або None. `allowed` — довідник у нижньому регістрі."""
    head = name[:90]
    full = name + ' ' + text
    if attr == 'Вид':
        if REAL.search(full) and not REAL_FALSE.search(full):
            v = 'реалістичні'
        else:
            v = 'нереалістичні'          # базове: немає анатомії — не реалістичний
        return v if v in allowed else None
    if attr == 'Конструкція':
        if SCROTUM.search(full) and 'з мошонкою' in allowed:
            return 'з мошонкою'
        if TWOSIDE.search(full) and 'двосторонні' in allowed:
            return 'двосторонні'
        if DOUBLE.search(full) and 'подвійні' in allowed:
            return 'подвійні'
        return 'односторонні' if 'односторонні' in allowed else None
    if attr == 'Призначення':
        for pat, val in PURPOSE:
            if re.search(pat, head, re.I) or re.search(pat, full, re.I):
                if val.lower() in allowed:
                    return val.lower()
        return None
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

    gaps = json.load(open(os.path.join(BASE, 'docs', 'epicentr_remaining_gaps.json'),
                          encoding='utf-8'))
    opts = json.load(open(os.path.join(BASE, 'data', 'epicentr_options_cache.json'),
                          encoding='utf-8'))
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""select sku, name, coalesce(regexp_replace(description_html,'<[^>]+>',' ','g'),'') d
                   from sexopt_products where sku = any(%s)""", ([g['sku'] for g in gaps],))
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

    TARGET = ('Вид', 'Конструкція', 'Призначення')
    todo = gaps[:a.limit] if a.limit else gaps
    ok = fail = 0
    picked = collections.Counter(); stat = collections.Counter()
    for i, g in enumerate(todo, 1):
        pair = txt.get(g['sku'])
        if not pair:
            stat['немає тексту'] += 1; continue
        name, desc = pair
        cand = [m for m in g['missing'] if m.get('name') in TARGET]
        if not cand:
            stat['цих полів не бракує'] += 1; continue
        cat = str(g['category'])
        want = {}
        for m in cand:
            allowed = opts.get(f"{cat}:{m['code']}")
            if not isinstance(allowed, dict):
                stat['немає довідника значень'] += 1; continue
            v = decide(name, desc, m['name'], set(allowed))
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
            print(f'  {g["sku"]}: {r2.status_code} {r2.text[:200]}', file=sys.stderr)
        time.sleep(0.15)
        if i % 200 == 0:
            print(f'  {i}/{len(todo)} — карток {ok}', file=sys.stderr)

    print(f'\n{"порахував" if a.plan else "записано"} карток: {ok} | не вдалось: {fail}')
    print('що проставлено:')
    for k, v in picked.most_common(14):
        print(f'   {v:5}  {k}')
    print('чому пропущено:')
    for k, v in stat.most_common(6):
        print(f'   {v:5}  {k}')


if __name__ == '__main__':
    main()
