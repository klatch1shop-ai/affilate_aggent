#!/usr/bin/env python3
"""
tools/epicentr_classify_devices.py
===================================
Заповнює «Тип приладу», «Призначення», «Конструкція», «Тип товару» та «Вид»
за конструктивними ознаками. Правила з консультації з товарознавства 02.09.2026.

ГОЛОВНЕ, ЩО ТРЕБА РОЗУМІТИ ПРО ЦЕЙ ДОВІДНИК

«Тип приладу» змішує чотири різні принципи поділу, тому порядок перевірок
критичний і не є довільним:

  * формотворення — кролик, мікрофон, віброчлен;
  * технологія    — вакуумний, звуковий, пульсатор;
  * зона впливу   — для сосків, на палець, трусики;
  * комплектація  — набір приладів, насадки.

Спершу перевіряємо найвужчі ознаки (комплектація і зона), потім технологію,
потім форму, і лише наприкінці — «класичний вібратор» як залишкове значення.
Якщо переставити місцями, «набір вакуумних стимуляторів» стане просто
вакуумним стимулятором, а вібротрусики — міні-вібратором.

ЗАГЛУШКИ. Обовʼязкове поле не можна лишати порожнім: при імпорті це validation
error і картка не потрапляє на сайт. Коли властивість до товару не застосовується
(конструкція віброяйця), беруть значення за спаданням:
«не застосовується» → «монолітна» → «одинарна»/«одностороння» → «інше».
У довідниках Епіцентру нейтральних значень немає, тому фактично працює третій
рівень — «односторонні» / «одинарні».

    python3 tools/epicentr_classify_devices.py --plan
"""
import os, sys, re, json, time, argparse, collections
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.db import get_connection
API = 'https://core-api.epicentrm.com.ua'

# --- Тип приладу: від найвужчої ознаки до найширшої ------------------------
DEVICE = [
    # комплектація
    ('набір приладів', r'набір\s+(?:з\s+)?\d|набір\s+приладів|набір\s+віброр?|'
                       r'\d\s+девайс|два\s+прилад'),
    ('насадки до вібратора', r'насадк\w*\s+(?:на|до|для)\s+вібратор|змінн\w+\s+насадк|'
                             r'чохол\s+на\s+вібратор'),
    # зона впливу
    ('вібратор для сосків', r'для\s+соск|на\s+соск|nipple|затискач\w*\s+для\s+груд|присоск\w*\s+для\s+груд'),
    ('вібратор-насадка на палець', r'на\s+палець|на\s+пальц|finger\s*vib|напальчник'),
    ('вібротрусики', r'вібротрусик|трусик\w*\s+з\s+вібр|panty\s*vib|у\s+білизн'),
    # технологія
    ('ороімітатор', r'ороімітатор|язичк|імітаці\w+\s+орал|орал\w+\s+сексу|лижуч|'
                    r'пелюстк\w*,?\s*що\s+оберт'),
    ('звуковий стимулятор', r'\bsonic\b|звуков\w+\s+хвил|акустичн\w+\s+імпульс|ультразвук'),
    ('вакуумний стимулятор', r'вакуум|air[-\s]?pulse|безконтактн|хвильов\w+\s+пульсац|'
                             r'розтруб|повітрян\w+\s+стимул'),
    ('вібратор-пульсатор', r'пульсатор|фрикці|поступальн\w+\s+рух|thrusting|штовхач|'
                           r'рух\w*\s+вгору-вниз'),
    # формотворення
    ('вібратор-мікрофон', r'мікрофон|\bwand\b|мікрофонн'),
    ('вібратор-кролик', r'кролик|rabbit|вушк'),
    ('вібратор для пар', r'для\s+пар\b|u-подібн|подібн\w+\s+літер\w+\s+u|couples'),
    ('віброяйця', r'віброяйц|яйц\w*\s+з\s+вібр|\begg\b|яйцеподібн'),
    ('віброкулі', r'віброкул|\bкул[яі]\b|bullet'),
    ('віброчлен', r'віброчлен|реалістичн\w+\s+вібратор|з\s+венам|з\s+мошонк'),
    ('міні-вібратор', r'\bміні\b|\bmini\b|компактн\w+\s+вібратор'),
    ('нестандартний вібратор', r'у\s+формі\s+(?:помад|розчіск|морозив|качк)|замаскован|'
                               r'трансформер|згинаєтьс\w+\s+під\s+будь-як'),
]
# --- Призначення вібратора -------------------------------------------------
BEND = re.compile(r'вигин|загнут|зігнут|точк\w*\s+g|g-spot|g-точк|у\s+формі\s+гачк', re.I)
CLIT_ARM = re.compile(r'відросток|вушк|кролик|rabbit|додатков\w+\s+стимул\w*\s+клітор|'
                      r'подвійн\w+\s+стимуляц', re.I)
NO_PENETRATION = re.compile(r'вакуум|безконтактн|мікрофон|\bwand\b|кліторальн|'
                            r'зовнішн\w+\s+стимул|пласк', re.I)
ANAL = re.compile(r'анальн|для\s+ануса|простат', re.I)
THREE = re.compile(r'3\s*в\s*1|три\s+зон|потрійн\w+\s+стимул', re.I)

# --- Тип товару: анальні пробки -------------------------------------------
PLUG = [
    ('набір', r'набір|комплект\w*\s+з\s+\d|\bkit\b'),
    ('анальний душ', r'анальн\w+\s+душ|спринцівк|клізм|douche'),
    ('іграшки для фістингу', r'фіст[иі]нг|fisting'),
    ('анальний тунель', r'тунель|наскрізн\w+\s+отвір|порожнист|hollow|втулка\s+з\s+отвор'),
    ('анальна пробка-ялинка', r'ялинк|ярус|ступінчаст|сегмент\w+\s+рельєф|christmas\s*tree|'
                              r'з\s+кількох\s+конус'),
    ('анальна смарт-пробка', r'застосун|додаток\s+для\s+смартфон|\bapp\b|bluetooth|смарт-|'
                             r'magic\s*motion|feelconnect|satisfyer\s*connect'),
    ('анальний розширювач', r'розширювач|дилатор|спекулум'),
]
DIAM = re.compile(r'діаметр\w*[^.\d]{0,25}(\d+[.,]?\d*)\s*см', re.I)
SPECULUM = re.compile(r'спекулум|гвинтов\w+\s+розшир|розсувн\w+\s+механізм', re.I)
KIT = re.compile(r'набір|комплект|\bkit\b', re.I)
REALISTIC = re.compile(r'реалістичн|realistic|з\s+венам|імітує\s+шкір|анатомічн\w+\s+форм', re.I)


def norm(x):
    x = (x or '').lower().replace('абс', 'abs')
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


def first(rules, text, allowed):
    for val, pat in rules:
        if re.search(pat, text, re.I):
            m = match(allowed, val)
            if m:
                return m
    return None


# Технологічні значення — це прикметники («вакуумний», «звуковий»), а решта —
# іменники, що називають сам предмет. В українській назві прикметник стоїть
# перед іменником, тому «найлівіше слово» саме по собі хибне: у «Вакуумному
# ороімітаторі» воно дало б технологію замість форми. Тому спершу шукаємо
# предметні значення, і лише за їх відсутності — технологічні.
TECH = {'вакуумний стимулятор', 'звуковий стимулятор', 'вібратор-пульсатор',
        'міні-вібратор', 'класичний вібратор'}


def by_head_noun(rules, name, allowed):
    """Постачальник сам класифікує товар назвою. Серед предметних значень
    виграє те, що стоїть найлівіше («Пульсатор із вакуумною стимуляцією» —
    пульсатор). Технологічні значення беруться, лише коли предметних немає."""
    for tier in (0, 1):
        best = None
        for val, pat in rules:
            if (val in TECH) != bool(tier):
                continue
            mo = re.search(pat, name, re.I)
            if mo:
                m = match(allowed, val)
                if m and (best is None or mo.start() < best[0]):
                    best = (mo.start(), m)
        if best:
            return best[1]
    return None


def decide(attr, name, desc, catname, allowed):
    full = name + ' ' + desc
    a = (attr or '').lower()

    if a == 'тип приладу':
        v = by_head_noun(DEVICE, name, allowed) or first(DEVICE, full, allowed)
        # «класичний вібратор» — залишкове значення, а не ознака
        return v or match(allowed, 'класичний вібратор')

    if a == 'тип товару' and 'пробк' in (catname or '').lower():
        v = by_head_noun(PLUG, name, allowed) or first(PLUG, full, allowed)
        return v or match(allowed, 'класична анальна пробка')

    if a == 'вид':
        # довідник має лише реалістичні / нереалістичні
        return match(allowed, 'реалістичні' if REALISTIC.search(full) else 'нереалістичні')

    if a == 'призначення':
        cl = (catname or '').lower()
        if 'розширювач' in cl:
            # шкала за діаметром; набір завжди «тренувальний»
            if SPECULUM.search(full):
                return match(allowed, 'професійний')
            if KIT.search(full):
                return match(allowed, 'тренувальний')
            d = DIAM.search(full)
            if not d:
                return None
            v = float(d.group(1).replace(',', '.'))
            if v <= 3.0:
                return match(allowed, 'для початківців')
            if v <= 3.8:
                return match(allowed, 'тренувальний')
            if v <= 4.5:
                return match(allowed, 'для досвідчених')
            return match(allowed, 'професійний')
        if 'кільц' in cl:
            # базове призначення кільця — те, заради чого воно існує
            if re.search(r'стимул\w*\s+клітор|вібро\w*\s+елемент|для\s+партнерк|'
                         r'з\s+вібрацією\s+для\s+клітор', full, re.I):
                return match(allowed, 'стимуляція партнера')
            if re.search(r'продовж\w+\s+(?:статев|акт)|затрим\w+\s+еякуляц|'
                         r'довш\w+\s+акт', full, re.I):
                return match(allowed, 'продовження статевого акту')
            if re.search(r'посил\w+\s+відчутт|інтенсивніш\w+\s+відчутт', full, re.I):
                return match(allowed, 'посилення відчуттів')
            return match(allowed, 'підтримка ерекції')
        if 'вібратор' in cl or 'фалоімітатор' in cl:
            if THREE.search(full):
                return match(allowed, 'cтимуляція 3 в 1')
            if ANAL.search(full) and not CLIT_ARM.search(full):
                return match(allowed, 'анальні')
            if CLIT_ARM.search(full):
                return match(allowed, 'вагінально-кліторні')
            if NO_PENETRATION.search(full):
                return match(allowed, 'кліторні')
            if BEND.search(full):
                return match(allowed, 'для точки g')
            return match(allowed, 'вагінальні')   # базове значення
        return None

    if a == 'конструкція':
        cl = (catname or '').lower()
        if 'кільц' in cl:
            if re.search(r'з\s+анальн\w+\s+пробк|з\s+пробк', full, re.I):
                return match(allowed, 'з анальною пробкою')
            if re.search(r'подвійн\w+\s+проникнен|з\s+відростк\w*\s+для\s+анал', full, re.I):
                return match(allowed, 'для подвійного проникнення')
            if re.search(r'потрійн|три\s+кільц|три\s+петл', full, re.I):
                return match(allowed, 'потрійні')
            if re.search(r'подвійн|дв[іа]\s+петл|за\s+мошонк|з\s+фіксацією\s+яєч', full, re.I):
                return match(allowed, 'подвійні')
            return match(allowed, 'одинарні')     # заглушка 3-го рівня
        # вібратори: дві робочі кінцівки на протилежних боках — «двосторонні»
        if re.search(r'двосторонн|з\s+двох\s+боків|обидв\w+\s+кінц|double[-\s]?ended|'
                     r'два\s+робоч\w+\s+кінц', full, re.I):
            return match(allowed, 'двосторонні')
        if CLIT_ARM.search(full) or THREE.search(full) or \
           re.search(r'u-подібн|для\s+пар\b', full, re.I):
            return match(allowed, 'подвійні')
        return match(allowed, 'односторонні')     # заглушка 3-го рівня
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

    gaps = json.load(open(os.path.join(BASE, 'docs', 'epicentr_enrich_gaps.json'),
                          encoding='utf-8'))
    prods = {x['id']: x for x in json.load(
        open(os.path.join(BASE, 'data', 'epicentr_products.json'), encoding='utf-8'))}
    opts = json.load(open(os.path.join(BASE, 'data', 'epicentr_options_cache.json'),
                          encoding='utf-8'))
    sel = [g for g in gaps
           if (prods.get(g['id'], {}).get('createdAt') or '')[:7] == '2026-07'
           and prods.get(g['id'], {}).get('status') == 'enrich']
    print(f'карток NOIRE із прогалинами: {len(sel)}')

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
        catname = prods[g['id']].get('attributeSetName') or ''
        cat = str(g['category'])
        want = {}
        for m in g['missing']:
            allowed = opts.get(f"{cat}:{m['code']}")
            if not isinstance(allowed, dict):
                continue
            v = decide(m.get('name'), name, desc, catname, list(allowed))
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
            print(f'  {g["sku"]}: {r2.status_code} {r2.text[:300]}', file=sys.stderr)
        time.sleep(0.15)
        if i % 200 == 0:
            print(f'  {i}/{len(todo)} — карток {ok}', file=sys.stderr)

    print(f'\n{"порахував" if a.plan else "записано"} карток: {ok} | не вдалось: {fail}')
    for k, v in picked.most_common(24):
        print(f'   {v:5}  {k}')
    for k, v in stat.most_common(4):
        print(f'   [{v}]  {k}')


if __name__ == '__main__':
    main()
