#!/usr/bin/env python3
"""
tools/epicentr_classify_rules.py
=================================
Заповнює найбільші прогалини NOIRE за товарознавчими правилами, отриманими
власником 02.09.2026. Кожне правило закриває сотні карток.

ПРАВИЛА Й ЇХНЯ ПІДСТАВА

* **Водонепроникний → «ні», якщо немає маркування.** Галузева норма: без
  прямої вказівки IPX або «waterproof» товар НЕ можна позначати
  водонепроникним. Акумулятор і USB-зарядка герметичності не гарантують.
  Обирають «ні», щоб уникнути повернень через залиту плату.

* **Кількість → 1 для одиничного товару.** Поле відповідає на питання
  «скільки фізичних одиниць отримає покупець», а не про обʼєм.

* **Стать — за анатомією, НЕ «унісекс» за замовчуванням** (на відміну від
  косметики): вібратори й фалоімітатори — для жінок; мастурбатори,
  ерекційні кільця, масажери простати — для чоловіків; анальні іграшки —
  унісекс, бо анус мають усі.

* **Матеріал — за категорією та доглядом.** «Тільки водна основа» в описі
  означає силікон/TPE/кібершкіру; «будь-які лубриканти» — ABS, метал, скло.
  Типові матеріали: пробки — метал/скло/силікон; вібратори — силікон;
  мастурбатори й насадки — TPE/кібершкіра.

* **«Колір виробника» дублює базовий колір українською.** Це усталене
  рішення e-commerce, яке закриває обовʼязковість поля. Плюс розшифровка
  суфікса артикула: -BLK, -RED, -PNK, -PUR, -NU.

    python3 tools/epicentr_classify_rules.py --plan
"""
import os, sys, re, json, time, argparse, collections
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.db import get_connection
API = 'https://core-api.epicentrm.com.ua'

WATERPROOF = re.compile(r'\bipx?\s*[4-8]\b|waterproof|водонепроникн|повне\s+занурення|'
                        r'можна\s+занурюв|100%\s*водо', re.I)
NOT_WATER = re.compile(r'не\s+(?:є\s+)?водонепроникн|не\s+занурюв|не\s+допускати\s+потрапляння|'
                       r'уникати\s+контакту\s+з\s+водою', re.I)
# набір проти поштучного товару — довідник «Кількість» має лише ці два значення
KIT = re.compile(r'набір|набор|комплект|\bсет\b|\bset\b|\bkit\b|(?<!\d[.,])\b([2-9]|\d\d)\s*шт', re.I)
PROSTATE = re.compile(r'простат|prostate', re.I)
ANY_LUBE = re.compile(r'будь-як\w+\s+лубрикант|з\s+усіма\s+лубрикант', re.I)

# Реальні назви категорій кабінету. Стать визначається анатомією використання,
# а не за замовчуванням «унісекс» (це правило чинне лише для косметики).
SEX_BY_CAT = {
    'Вібратори': 'для жінок', 'Фалоімітатори': 'для жінок', 'Страпони': 'для жінок',
    'Вагінальні кульки та тренажери': 'для жінок', 'Менструальні чаші': 'для жінок',
    'Еротична білизна': 'для жінок', 'Еротичні костюми': 'для жінок',
    'Мастурбатори': 'для чоловіків', 'Аксесуари для мастурбаторів': 'для чоловіків',
    'Ерекційні кільця': 'для чоловіків', 'Масажери простати': 'для чоловіків',
    'Насадки на член': 'для чоловіків', 'Екстендери та помпи': 'для чоловіків',
    'Анальні пробки': 'унісекс', 'Анальні кульки та намисто': 'унісекс',
    'Анальні розширювачі': 'унісекс', 'Анальний душ': 'унісекс',
    # косметика та засоби — тут «унісекс» справді базове значення
    'Засоби для еротичного масажу': 'унісекс', 'Засоби для орального сексу': 'унісекс',
    'Свічки для інтимного масажу': 'унісекс', 'Косметичні олії': 'унісекс',
    'Гель для душу': 'унісекс', 'Крем для тіла': 'унісекс', 'Піна для ванни': 'унісекс',
    'Сіль для ванни': 'унісекс', 'Засоби після гоління': 'унісекс',
    'Аксесуари до інтимних іграшок': 'унісекс', 'Презервативи': 'унісекс',
}
# Типовий матеріал за категорією: мастурбатори й насадки — мʼякий TPE/кібершкіра,
# вібратори й пробки — силікон, білизна — тканина.
MAT_BY_CAT = {
    'Мастурбатори': 'tpe', 'Аксесуари для мастурбаторів': 'tpe',
    'Насадки на член': 'tpe', 'Секс-ляльки': 'tpe',
    'Вібратори': 'силікон', 'Фалоімітатори': 'силікон', 'Анальні пробки': 'силікон',
    'Анальні кульки та намисто': 'силікон', 'Анальні розширювачі': 'силікон',
    'Ерекційні кільця': 'силікон', 'Страпони': 'силікон', 'Аксесуари для страпонів': 'силікон',
    'Вагінальні кульки та тренажери': 'силікон', 'Масажери простати': 'силікон',
    'Менструальні чаші': 'силікон',
    'Еротична білизна': 'тканина', 'Еротичні костюми': 'тканина',
}
MAT_TEXT = [
    (r'нержавіюч\w+\s+стал', 'нержавіюча сталь'),
    (r'алюміні', 'алюміній'),
    (r'з\s+металу|металев|\bметал\b', 'метал'),
    (r'боросилікатн', 'боросилікатне скло'),
    (r'з\s+(?:мед\w*\s+)?скл|склян', 'скло'),
    (r'кібершкір|cyberskin|realskin|cyberflesh', 'кібершкіра'),
    (r'медичн\w+\s+силікон', 'медичний силікон'),
    (r'силікон', 'силікон'),
    (r'\btpr\b', 'tpr'), (r'\btpu\b', 'tpu'),
    (r'\btpe\b|термопласт', 'tpe'),
    (r'полікарбонат', 'полікарбонат'),
    (r'нейлон', 'нейлон'), (r'поліестер', 'поліестер'), (r'поліпропілен', 'поліпропілен'),
    (r'\bpvc\b|полівінілхлорид', 'pvc'),
    (r'abs[-\s]?пластик|\babs\b|абс[-\s]?пластик', 'абс-пластик'),
    (r'екошкір|штучн\w+\s+шкір', 'екошкіра'),
    (r'натуральн\w+\s+шкір|справжн\w+\s+шкір', 'натуральна шкіра'),
    (r'латекс', 'латекс'), (r'\bвіск\b|восков', 'віск'),
    (r'текстиль', 'текстиль'), (r'тканин', 'тканина'),
    (r'пластик', 'пластик'),
]
COLORS = [
    (r'чорн|black|[-_]blk?\b', 'чорний'), (r'біл(?:ий|а|е)|white|[-_]wht?\b', 'білий'),
    (r'червон|\bred\b|[-_]rd\b', 'червоний'), (r'рожев|pink|[-_]pnk?\b', 'рожевий'),
    (r'фіолетов|бузков|purple|[-_]pur?\b', 'фіолетовий'), (r'син[ій]|\bblue\b', 'синій'),
    (r'блакитн|бірюзов', 'блакитний'), (r'зелен|green', 'зелений'),
    (r'сір(?:ий|а)|gray|grey', 'сірий'), (r'тілесн|nude|[-_]nu\b|бежев|beige', 'бежевий'),
    (r'золот|gold', 'золотий'), (r'срібл|silver|хром', 'сріблястий'),
    (r'прозор|clear|transparent', 'прозорий'), (r'коричнев|brown', 'коричневий'),
    (r'бордов|wine', 'бордовий'), (r'помаранч|orange', 'помаранчевий'),
    (r'фуксі|fuchsia', 'рожевий'), (r'жовт|yellow', 'жовтий'),
]

def norm(x):
    """Кирилична «абс» і латинська «abs» — той самий матеріал; довідники пишуть
    по-різному в різних категоріях, тому звіряємо нормалізовані рядки."""
    x = (x or '').lower().replace('абс', 'abs')
    return re.sub(r'[^a-zа-яіїєґ0-9]+', '', x)


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def _wrap(spec, value):
    return [value] if (spec or {}).get('type') == 'multiselect' else value


def match(allowed, want):
    w = norm(want)
    if not w:
        return None
    for a in allowed:
        if norm(a) == w:
            return a
    for a in allowed:
        na = norm(a)
        if w and (w in na or na in w):
            return a
    return None


def decide(attr, name, desc, sku, catname, allowed):
    full = name + ' ' + desc
    a = (attr or '').lower()

    if a == 'водонепроникний':
        if NOT_WATER.search(full):
            return match(allowed, 'ні')
        # без прямої вказівки IPX/waterproof маркувати «так» не можна
        return match(allowed, 'так' if WATERPROOF.search(full) else 'ні')

    if a == 'підігрів':
        return match(allowed, 'так' if re.search(r'підігрів|нагрів|heating|warm', full, re.I)
                     else 'ні')

    if a.startswith('кількість'):
        # довідник має лише «поштучно» / «набір» — це не число одиниць
        return match(allowed, 'набір' if KIT.search(full) else 'поштучно')

    if a == 'стать':
        if PROSTATE.search(full):
            return match(allowed, 'для чоловіків')
        v = SEX_BY_CAT.get(catname)
        return match(allowed, v) if v else None

    if a in ('матеріал', 'основний матеріал'):
        for pat, val in MAT_TEXT:
            if re.search(pat, full, re.I):
                m = match(allowed, val)
                if m:
                    return m
        if ANY_LUBE.search(full):
            return match(allowed, 'абс-пластик')
        v = MAT_BY_CAT.get(catname)
        return match(allowed, v) if v else None

    if a in ('колір', 'колір виробника', 'базовий колір'):
        src = name + ' ' + sku + ' ' + desc[:400]
        for pat, val in COLORS:
            if re.search(pat, src, re.I):
                m = match(allowed, val)
                if m:
                    return m
        return None
    return None


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
            v = decide(m.get('name'), name, desc, g['sku'], catname, list(allowed))
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
    for k, v in picked.most_common(16):
        print(f'   {v:5}  {k}')
    for k, v in stat.most_common(4):
        print(f'   [{v}]  {k}')


if __name__ == '__main__':
    main()
