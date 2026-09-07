#!/usr/bin/env python3
"""
tools/epicentr_classify_specs.py
=================================
Третій блок правил (консультація 02.09.2026, блок 3): обʼєм, білизна, форма
пробки, розмір чаш, живлення, режими, BDSM, колір.

ОКРЕМО ПРО ОБʼЄМ. Довідник Епіцентру для «Обʼєму» має лише три значення —
30/100/120 мл, тоді як у каталозі є 3, 15, 50, 75, 200 і 250 мл. Це технічна
прогалина конфігурації категорії на боці маркетплейсу, а не наша.

Оперативне рішення — округлення до найближчого доступного, і воно допустиме
**лише тому**, що точний обʼєм лишається в назві товару («…Hot Vanilla 50мл»).
Покупець бачить справжнє число там, де воно юридично значуще. Це тимчасовий
костур; системне рішення — тикет у підтримку на розширення довідника.

    python3 tools/epicentr_classify_specs.py --plan
"""
import os, sys, re, json, time, argparse, collections
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.db import get_connection
API = 'https://core-api.epicentrm.com.ua'

VOL = re.compile(r'(\d+[.,]?\d*)\s*(?:мл|ml|г\b|гр\b)', re.I)

# --- Еротична білизна: межі за конструкцією ------------------------------
LINGERIE = [
    # 3+ предмети або рольовий костюм
    ('еротичний набір', r'костюм\s+(?:медсестр|покоївк|поліцейськ|школярк)|'
                        r'набір\s+з\s+[3-9]|\+\s*(?:маск|наручник|чокер|гартер|пояс)'),
    ('стікіні', r'стікіні|stickini|наклейк\w*\s+на\s+соск|пестіс|pasties|nipple\s*cover'),
    ('бодістокінг', r'бодістокінг|bodystocking|комбінезон-сітк|суцільн\w+\s+сітк'),
    ('комбідрес', r'комбідрес|combidress|боді[-\s]?шортик|з\s+панталончик'),
    ('комбінезон', r'комбінезон|catsuit|jumpsuit|з\s+штанинам'),
    ('боді', r'\bбоді\b|\bbody\b'),
    ('корсет', r'корсет|corset|бюстьє'),
    ('пеньюар', r'пеньюар|негліже|peignoir'),
    ('халатик', r'халат'),
    ('сукня', r'сукн|плать|\bdress\b'),
    ('панчохи', r'панчох|stockings'),
    ('колготки та легінси', r'колготк|легінс|leggings'),
    ('пояси для панчох', r'пояс\w*\s+для\s+панчох|garter\s*belt'),
    ('гартери', r'гартер|підв\W?язк\w*\s+на\s+ног'),
    ('підв\'язка', r'підв\W?язк'),
    ('накладні груди', r'накладн\w+\s+груд'),
    ('рукавички', r'рукавичк|мітенк'),
    ('шортики', r'шортик'),
    ('футболка', r'футболк|\bтоп\b'),
    ('комплект білизни', r'комплект|\bсет\b|бюстгальтер\s*(?:\+|та|і)\s*трусик'),
    ('бюстгальтер та топи', r'бюстгальтер|ліф\b|\bбра\b'),
    ('трусики', r'трусик|стрінг|танга|бразиліан'),
]
# --- Форма анальної пробки: лише три значення ----------------------------
PLUG_SHAPE = [
    ('фалос', r'анатомічн\w+\s+форм|з\s+голівк|з\s+венам|у\s+формі\s+член|реалістичн'),
    ('фігурна', r'кристал|страз|хвостик|з\s+хвостом|сердечк|квітк|спіральн|'
                r'у\s+формі\s+(?:зірк|метелик|тварин)|дизайнерськ|пухнаст'),
]
# --- Живлення ------------------------------------------------------------
ACCU = re.compile(r'акумулятор|li-?ion|li-?pol|\busb\b|зарядк|заряджаєтьс|'
                  r'магнітн\w+\s+заряд|rechargeable|перезаряджув', re.I)
BATT = re.compile(r'\b\d?\s?[xх]?\s?(?:aaa|aa|lr44|cr2032|cr2016|ag13)\b|батарейк|батарейок', re.I)
MAINS = re.compile(r'220\s?v|від\s+мережі|мережев\w+\s+шнур|у\s+розетк', re.I)
MOTOR = re.compile(r'вібр|мотор|стимулятор|пульсац|обертан|двигун', re.I)
# --- Режими --------------------------------------------------------------
MODES = re.compile(r'(\d+)\s*(?:режим\w*|швидкост\w*|програм\w*|паттерн\w*|modes|speeds)', re.I)
# --- BDSM ----------------------------------------------------------------
BDSM = [
    ('кляп', r'кляп|\bgag\b'), ('наручники', r'наручник|кайдан|поножи|\bcuffs?\b'),
    ('батіг/флогер', r'батіг|флогер|\bwhip\b|flogger'), ('стек', r'\bстек\b|crop'),
    ('пов\'язка на очі', r'пов\W?язк\w*\s+на\s+оч|blindfold|маска\s+на\s+оч'),
    ('маска для обличчя', r'маска\s+(?:для\s+)?облич|\bmask\b'),
    ('нашийник', r'нашийник|\bcollar'), ('чокер', r'чокер|choker'),
    ('повідець', r'повідец|повідк|\bleash\b'),
    ('затискач для сосків та клітора', r'затискач\w*\s+(?:на|для)\s+(?:соск|клітор)|nipple\s*clamp'),
    ('затискачі на яєчка', r'затискач\w*\s+(?:на|для)\s+яєч'),
    ('затискач для вагіни', r'затискач\w*\s+для\s+вагін'),
    ('портупея/збруя', r'портупе|збру|harness'),
    ('пояс вірності', r'пояс\w*\s+вірност|chastity'),
    ('мотузка бандажна', r'мотузк|bondage\s*rope|шибарі'),
    ('бандаж/фіксатор', r'бандаж|фіксатор|\bcuff\s*set'),
    ('розпірка', r'розпірк|spreader'),
    ('колесо вартенберга', r'вартенберг|wartenberg|колесо'),
    ('лоскоталка', r'лоскот|махалк|перо\b|tickler'),
    ('ляпалка/тоуза', r'ляпалк|тоуза|шльопалк|\bpaddle\b'),
    ('свічки низькотемпературні', r'низькотемператур|свічк'),
    ('уретральні вставки', r'уретральн|\bsound\b|діласт'),
    ('насадка на палець для стимуляції', r'на\s+палець|напальчник'),
    ('набір речей', r'набір|комплект'),
]
COLORS = [
    (r'чорн|black|[-_]blk?\b', 'чорний'), (r'біл(?:ий|а|е|о)|white|[-_]wht?\b', 'білий'),
    (r'червон|\bred\b|[-_]rd\b', 'червоний'), (r'рожев|pink|фуксі|fuchsia|корал|[-_]pnk?\b', 'рожевий'),
    (r'фіолетов|бузков|лілов|purple|violet|lavender|[-_]pur?\b', 'фіолетовий'),
    (r'син[ій]|\bblue\b|navy|індиго', 'синій'), (r'блакитн|бірюзов|cyan|teal|aqua|мятн', 'блакитний'),
    (r'зелен|green|олив', 'зелений'), (r'сір(?:ий|а)|gray|grey|графіт', 'сірий'),
    (r'тілесн|nude|[-_]nu\b|бежев|beige|\bflesh\b', 'бежевий'),
    (r'золот|gold', 'золотий'), (r'срібл|silver|хром|сталев|chrome', 'сріблястий'),
    (r'прозор|clear|transparent', 'прозорий'), (r'коричнев|brown|шоколад', 'коричневий'),
    (r'бордов|wine|марсал|бургунд', 'бордовий'), (r'помаранч|orange|персик', 'помаранчевий'),
    (r'жовт|yellow|лимон', 'жовтий'), (r'\bчорно-червон', 'чорно-червоний'),
]
KIT = re.compile(r'набір|комплект|\bkit\b|\bset\b', re.I)


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


def volumes(text):
    out = []
    for mo in VOL.finditer(text):
        try:
            out.append(float(mo.group(1).replace(',', '.')))
        except ValueError:
            pass
    return out


def decide(attr, name, desc, catname, allowed):
    full = name + ' ' + desc
    a = (attr or '').lower()
    cl = (catname or '').lower()

    if a in ('об’єм', "об'єм", 'обʼєм'):
        v = volumes(name) or volumes(desc[:600])
        if not v:
            return None
        val = max(v) if KIT.search(name) else v[0]
        if 'чаш' in cl:                       # чаші мають власний числовий атрибут
            return None
        for exact in ('30 мл', '100 мл', '120 мл'):
            if abs(val - float(exact.split()[0])) < 0.01:
                return match(allowed, exact)
        # округлення до найближчого доступного; точне число лишається в назві
        if val <= 15:
            return match(allowed, '30 мл')
        if val <= 110:
            return match(allowed, '100 мл')
        return match(allowed, '120 мл')

    if a == 'розмір' and 'чаш' in cl:
        v = volumes(full)
        if not v:
            return None
        val = min(v)                          # у наборі беруть менший розмір
        if val <= 14:
            return match(allowed, 'xs')
        if val <= 20:
            return match(allowed, 's')
        if val <= 25:
            return match(allowed, 'm')
        if val <= 30:
            return match(allowed, 'l')
        return match(allowed, 'xl')

    if a == 'розмір' and ('білизн' in cl or 'костюм' in cl):
        m = re.search(r'\b(one\s*size|універсальн)', full, re.I)
        if m:
            return match(allowed, 'one size')
        m = re.search(r'\b(xs|s|m|l|xl|2xl|3xl|4xl|5xl)\s*[/\-]\s*(xs|s|m|l|xl|2xl)\b', full, re.I)
        if m:
            return match(allowed, m.group(1).lower())   # з діапазону беруть менший
        m = re.search(r'розмір\w*[:\s]+(xs|s|m|l|xl|2xl|3xl|4xl|5xl)\b', full, re.I)
        if m:
            return match(allowed, m.group(1).lower())
        return match(allowed, 'one size')     # еластична білизна за замовчуванням

    if a == 'тип товару':
        if 'білизн' in cl or 'костюм' in cl:
            return first(LINGERIE, full, allowed)
        if 'фетиш' in cl or 'bdsm' in cl:
            return first(BDSM, name, allowed) or first(BDSM, full, allowed)
        return None

    if a == 'форма' and 'пробк' in cl:
        return first(PLUG_SHAPE, full, allowed) or match(allowed, 'класична конусна')

    if a == 'тип живлення':
        # акумулятор перевіряємо першим: пульт на CR2032 не робить девайс батарейковим
        if ACCU.search(full):
            return match(allowed, 'акумулятор')
        if MAINS.search(full):
            return match(allowed, 'від мережі')
        if BATT.search(full):
            return match(allowed, 'одноразові батарейки')
        if not MOTOR.search(full):
            return match(allowed, 'без живлення')
        return None

    if a.startswith('кількість режимів'):
        vals = [int(x) for x in MODES.findall(full)]
        if not vals:
            if not MOTOR.search(full):
                return match(allowed, '1')
            return None
        n = sum(vals) if len(vals) > 1 else vals[0]
        return match(allowed, str(n)) or match(allowed, str(max(vals)))

    if a in ('колір', 'колір виробника', 'базовий колір'):
        src = name + ' ' + desc[:400]
        for pat, val in COLORS:
            if re.search(pat, src, re.I):
                m = match(allowed, val)
                if m:
                    return m
        return None
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
            r = s.get(f'{API}/v2/pim/products/forms/attribute-set/by-code/{cat}/attributes', timeout=40)
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
            print(f'  {g["sku"]}: {r2.status_code} {r2.text[:300]}', file=sys.stderr)
        time.sleep(0.15)
        if i % 200 == 0:
            print(f'  {i}/{len(todo)} — карток {ok}', file=sys.stderr)

    print(f'\n{"порахував" if a.plan else "записано"} карток: {ok} | не вдалось: {fail}')
    for k, v in picked.most_common(28):
        print(f'   {v:5}  {k}')
    for k, v in stat.most_common(4):
        print(f'   [{v}]  {k}')


if __name__ == '__main__':
    main()
