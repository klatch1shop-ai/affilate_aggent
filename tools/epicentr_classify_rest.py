#!/usr/bin/env python3
"""
tools/epicentr_classify_rest.py
================================
Закриває решту прогалин NOIRE в «Наповненні контентом».

ЧОМУ САМЕ ЦІ ПОЛЯ. З 569 карток **327 мають рівно одну прогалину**. Тому мета
не «довести картку до досконалості», а закрити останнє поле: кожна закрита
прогалина одразу дає картку, готову до модерації.

Кольори тут НЕ чіпаються — вони потребують читання головного фото, і це окреме
рішення власника.

    python3 tools/epicentr_classify_rest.py --plan
"""
import os, sys, re, json, html, time, argparse, collections
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.db import get_connection
API = 'https://core-api.epicentrm.com.ua'

SMART = re.compile(r'застосун|додаток\s+для\s+смартфон|\bapp\b|bluetooth|блютуз|'
                   r'смарт-|smart\s|connect|magic\s*motion|feelconnect|wi-?fi|'
                   r'керуванн\w+\s+через\s+інтернет|дистанційн\w+\s+через\s+телефон', re.I)
MODES = re.compile(r'(\d+)\s*(?:режим\w*|швидкост\w*|програм\w*|паттерн\w*|modes|speeds)', re.I)
KIT = re.compile(r'набір|комплект|\bсет\b|\bset\b|\bkit\b', re.I)
VOL = re.compile(r'(\d+[.,]?\d*)\s*(?:мл|ml|г\b|гр\b)', re.I)
MOTOR = re.compile(r'вібр|мотор|стимулятор|пульсац|обертан', re.I)
REALISTIC = re.compile(r'реалістичн|realistic|з\s+венам|імітує\s+шкір|анатомічн\w+\s+форм', re.I)
# Клас косметики за ціною: іншого об'єктивного джерела в даних немає, тому
# межі задані явно і їх видно в коді, а не сховані в евристиці.
PRICE_TIER = ((350, 'мас-маркет'), (900, 'мідл-маркет'), (10 ** 9, 'елітна'))


def norm(x):
    x = html.unescape(x or '').lower().replace('ʼ', "'").replace('’', "'")
    return re.sub(r'[^a-zа-яіїєґ0-9]+', '', x)


def match(allowed, want):
    w = norm(want)
    if not w:
        return None
    for a in allowed:
        if norm(a) == w:
            return a
    for a in allowed:
        na = norm(a)
        if w in na or na in w:
            return a
    return None


STOP_TOKENS = {'для', 'без', 'при', 'над', 'під', 'засіб', 'засоби', 'та', 'із',
               'зі', 'що', 'the', 'and'}


def by_dictionary(allowed, text, skip=()):
    """Значення довідника, згадане в тексті.

    Ключове — **за яким словом шукати**. Перша версія брала перше слово
    значення, і «для лікування подразнень…» шукалось за коренем «для», який
    збігається майже з будь-яким описом. Так само «солодкий ром» ловився на
    кожному «солодкому смаку». Тому шукаємо за **найдовшим змістовним словом**
    значення, а службові слова відкидаємо. І вимагаємо збігу ВСІХ змістовних
    слів, якщо їх у значенні кілька: «шоколад-мʼята» не має спрацьовувати на
    самому шоколаді.
    """
    best = None
    for a in sorted(allowed, key=lambda x: -len(x)):
        clean = html.unescape(a).lower().replace('&#039;', "'")
        if clean in skip:
            continue
        core = re.sub(r'\s*\(.*?\)', '', clean).strip()
        # Поріг 3, а не 4: коротке слово «ром» у «солодкий ром» відсіювалось,
        # і значення спрацьовувало на самому «солодкому» — «солодким мінетом»,
        # «солодкуватий смак полуниці». Хибних значень було 18.
        words = [w for w in re.split(r'[\s\-/,]+', core)
                 if len(w) >= 3 and w not in STOP_TOKENS]
        if not words:
            continue
        stems = [w[:6] for w in words]
        if all(re.search(r'\b' + re.escape(st), text, re.I) for st in stems):
            best = best or a
    return best


def decide(attr, name, desc, catname, allowed, price):
    full = name + ' ' + desc
    a = html.unescape(attr or '').lower()

    if 'застосунок' in a or a.startswith('керування через'):
        return match(allowed, 'так' if SMART.search(full) else 'ні')

    if a.startswith('кількість режимів'):
        v = [int(x) for x in MODES.findall(full)]
        if not v:
            return match(allowed, '1') if not MOTOR.search(full) else None
        n = sum(v) if len(v) > 1 else v[0]
        return match(allowed, str(n)) or match(allowed, str(max(v)))

    if a.startswith('кількість в упаковці') or a == 'кількість в упаковці':
        return None if KIT.search(full) else '1'

    if a in ("об'єм", 'об’єм', 'обʼєм') :
        m = VOL.search(name) or VOL.search(desc[:600])
        return m.group(1).replace(',', '.') if m else None

    if a == 'аромат':
        v = by_dictionary(allowed, full, skip=('без аромату',))
        # відсутність згадки — законна підстава для «без аромату»
        return v or match(allowed, 'без аромату')

    if a == 'смак':
        v = by_dictionary(allowed, full, skip=('без смаку',))
        return v or match(allowed, 'без смаку')

    if a == 'вид':
        if match(allowed, 'реалістичні') and match(allowed, 'нереалістичні'):
            return match(allowed, 'реалістичні' if REALISTIC.search(full) else 'нереалістичні')
        return by_dictionary(allowed, name) or by_dictionary(allowed, full)

    if a == 'клас косметики':
        if price:
            for lim, tier in PRICE_TIER:
                if price <= lim:
                    return match(allowed, tier)
        return None

    if a == 'призначення':
        return by_dictionary(allowed, full) or match(allowed, 'для тіла')
    return None


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def _wrap(spec, value):
    return [value] if (spec or {}).get('type') == 'multiselect' else value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    gaps = json.load(open(os.path.join(BASE, 'docs', 'epicentr_enrich_gaps.json'), encoding='utf-8'))
    prods = {x['id']: x for x in json.load(
        open(os.path.join(BASE, 'data', 'epicentr_products.json'), encoding='utf-8'))}
    opts = json.load(open(os.path.join(BASE, 'data', 'epicentr_options_cache.json'), encoding='utf-8'))
    sel = [g for g in gaps
           if (prods.get(g['id'], {}).get('createdAt') or '')[:7] == '2026-07' and g['missing']]
    print(f'карток NOIRE із прогалинами: {len(sel)}')

    conn = get_connection(); cur = conn.cursor()
    cur.execute("""select sku, name, coalesce(regexp_replace(description_html,'<[^>]+>',' ','g'),'') d,
                          price_retail as price from sexopt_products where sku = any(%s)""", ([g['sku'] for g in sel],))
    txt = {r['sku']: ((r['name'] or ''), (r['d'] or ''), float(r['price'] or 0)) for r in cur.fetchall()}
    cur.close(); conn.close()

    s = requests.Session()
    s.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                      'Accept-Language': 'uk-UA'})
    login(s)
    form_cache = {}

    def form_ids(cat):
        if cat not in form_cache:
            r = s.get(f'{API}/v2/pim/products/forms/attribute-set/by-code/{cat}/attributes', timeout=40)
            items = r.json().get('items', []) if r.status_code == 200 else []
            form_cache[cat] = {str(x['code']): x for x in items}
        return form_cache[cat]

    todo = sel[:a.limit] if a.limit else sel
    ok = fail = 0; picked = collections.Counter(); stat = collections.Counter()
    for i, g in enumerate(todo, 1):
        rec = txt.get(g['sku'])
        if not rec:
            stat['немає тексту'] += 1; continue
        name, desc, price = rec
        catname = prods[g['id']].get('attributeSetName') or ''
        cat = str(g['category'])
        want = {}
        for m in g['missing']:
            allowed = opts.get(f"{cat}:{m['code']}")
            free = m.get('type') in ('float', 'int', 'number', 'text')
            v = decide(m.get('name'), name, desc, catname,
                       list(allowed) if isinstance(allowed, dict) else [], price)
            if not v:
                continue
            code_val = v if free else (allowed or {}).get(v)
            if code_val is None:
                continue
            want[str(m['code'])] = (m['name'], v, code_val)
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
            cur_v.append({'id': fids[code]['id'], 'code': code, 'value': _wrap(fids[code], vcode)})
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
            print(f'  {g["sku"]}: {r2.status_code} {r2.text[:250]}', file=sys.stderr)
        time.sleep(0.15)
        if i % 150 == 0:
            print(f'  {i}/{len(todo)} — карток {ok}', file=sys.stderr)

    print(f'\n{"порахував" if a.plan else "записано"} карток: {ok} | не вдалось: {fail}')
    for k, v in picked.most_common(22):
        print(f'   {v:5}  {k}')
    for k, v in stat.most_common(4):
        print(f'   [{v}]  {k}')


if __name__ == '__main__':
    main()
