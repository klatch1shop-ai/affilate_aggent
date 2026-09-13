#!/usr/bin/env python3
"""
tools/epicentr_fill_from_prom.py
=================================
Переносить характеристики з нашого ж фіду Prom у картки Єпіцентру.

Ідея власника 01.09.2026: ті самі товари вже мають заповнені характеристики
у фіді Prom — «Вид», «Конструкція», «Призначення», «Тип приладу». Значення
там ЗБІГАЮТЬСЯ з довідником Єпіцентру дослівно, бо обидва фіди збирає наш
генератор із тих самих даних. Тобто інформація в нас була, просто не
доїжджала до кабінету.

Що робить:
  1. читає `output/noire_prom.xml` → {sku: {назва: значення}}
  2. для кожної картки в статусі enrich бере ЇЇ категорію з кабінету
  3. з довідника наборів бере обовʼязкові атрибути цієї категорії
  4. заповнює лише ті, яких у картці НЕМАЄ і для яких Prom дає значення,
     що є в довіднику дозволених

Нічого не вигадує: значення або є в Prom і дозволене, або поле лишається
порожнім. Статусів не міняє.

    python3 tools/epicentr_fill_from_prom.py --plan     # порахувати, не писати
    python3 tools/epicentr_fill_from_prom.py --limit 5  # спершу кілька
"""
import os, sys, re, json, time, argparse, collections
import xml.etree.ElementTree as ET
import requests
from dotenv import load_dotenv

# Апостроф у тих самих словах пишеться по-різному: Єпіцентр віддає атрибут
# «Об’єм» (U+2019), Prom — «Об`єм» (U+0060) і «Об'єм» (U+0027). Зіставлення
# назв «як є» мовчки не знаходило поле й лишало його порожнім (02.09: 79
# прогалин «Об’єм», з них 21 із дозволеним значенням).
APOS = {ord(c): "'" for c in '`´ʹʼ‘’'}


def key(s):
    return re.sub(r'\s+', ' ', (s or '')).strip().lower().translate(APOS)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
API  = 'https://core-api.epicentrm.com.ua'
MAPI = 'https://merchant-api.epicentrm.com.ua'


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def ua(o):
    for t in (o or {}).get('translations', []):
        if t.get('languageCode') == 'ua':
            return t.get('value') or t.get('title')
    return None


_opts_cache = {}
def options(cat, code):
    ck = (cat, code)          # не `key`: так зветься функція нормалізації назв
    if ck in _opts_cache:
        return _opts_cache[ck]
    h = {'Authorization': f"Bearer {os.getenv('EPICENTR_TOKEN')}", 'Accept': 'application/json'}
    out, page = {}, 1
    while True:
        r = requests.get(f'{MAPI}/v2/pim/attribute-sets/{cat}/attributes/{code}/options',
                         headers=h, params={'limit': 80, 'page': page}, timeout=40)
        if r.status_code != 200:
            break
        j = r.json()
        for o in j.get('items', []):
            out[key(ua(o))] = o['code']
        if page >= (j.get('pages') or 1):
            break
        page += 1
    _opts_cache[ck] = out
    return out


_form_cache = {}
def form_ids(s, cat):
    if cat in _form_cache:
        return _form_cache[cat]
    r = s.get(f'{API}/v2/pim/products/forms/attribute-set/by-code/{cat}/attributes', timeout=40)
    items = r.json().get('items', []) if r.status_code == 200 else []
    _form_cache[cat] = {str(x['code']): x['id'] for x in items}
    return _form_cache[cat]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--only', default='', help='список SKU через кому')
    ap.add_argument('--dump-fails', default='', help='файл JSONL: тіло запиту + повна відповідь')
    ap.add_argument('--prom', default=os.path.join(BASE, 'output', 'noire_prom.xml'),
                    help='фід Prom; на сервері він свіжіший за локальний')
    ap.add_argument('--params', default='', help='TSV sku/назва/значення/джерело з '
                    'sexopt_extracted_params — джерело, з якого фід Prom і '
                    'збирається. Фід не несе карток поза продажем і значень, що '
                    'не лягли в закриті переліки Prom, тому з нього видно менше')
    a = ap.parse_args()

    prom = {}
    root = ET.parse(a.prom).getroot()
    for o in root.findall('.//offer'):
        sku = (o.findtext('vendorCode') or o.get('id') or '').strip()
        if sku:
            prom[sku] = {key(p.get('name')): (p.text or '').strip()
                         for p in o.findall('param') if (p.text or '').strip()}
    print(f'товарів у фіді Prom: {len(prom)}')
    if a.params:
        add = 0
        for line in open(a.params, encoding='utf-8'):
            f = line.rstrip('\n').split('\t')
            if len(f) >= 3 and f[2].strip():
                # фід має перевагу: він уже пройшов наші ж перевірки значень
                d = prom.setdefault(f[0], {})
                if key(f[1]) not in d:
                    d[key(f[1])] = f[2].strip()
                    add += 1
        print(f'додано з {os.path.basename(a.params)}: {add} значень, '
              f'товарів разом: {len(prom)}')

    prods = [x for x in json.load(open(os.path.join(BASE, 'data', 'epicentr_products.json'),
                                       encoding='utf-8'))
             if (x.get('createdAt') or '')[:7] == '2026-07' and x['status'] == 'enrich']
    sets = json.load(open(os.path.join(BASE, 'data', 'epicentr_attribute_sets.json'),
                          encoding='utf-8'))
    print(f'карток у «Наповненні контентом»: {len(prods)}')

    s = requests.Session()
    s.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                      'Accept-Language': 'uk-UA'})
    login(s)

    todo = [p for p in prods if (p.get('sku') or '').strip() in prom]
    if a.only:
        want = {x.strip() for x in a.only.split(',') if x.strip()}
        todo = [p for p in todo if (p.get('sku') or '').strip() in want]
        missing = want - {(p.get('sku') or '').strip() for p in todo}
        if missing:
            print(f'НЕ знайдено серед enrich+Prom: {sorted(missing)}', file=sys.stderr)
    if a.limit:
        todo = todo[:a.limit]
    print(f'з них є у фіді Prom: {len(todo)}\n')

    stat = collections.Counter(); filled_names = collections.Counter()
    ok = fail = 0
    for i, p in enumerate(todo, 1):
        sku = (p.get('sku') or '').strip()
        cat = str(p.get('attributeSetCode'))
        spec = sets.get(cat)
        if not spec:
            stat['категорії немає в довіднику'] += 1; continue
        req = [x for x in spec.get('attributes', []) if x.get('isRequired')]
        try:
            d = s.get(f"{API}/v2/pim/products/{p['id']}", timeout=45).json()
        except Exception:
            fail += 1; continue
        cur = [{'id': v['id'], 'code': v['code'], 'value': v['value']}
               for v in (d.get('attributeValues') or [])]
        have = {str(v['code']) for v in cur
                if v.get('value') not in (None, '', [])}
        fids = form_ids(s, cat)
        added = 0
        for at in req:
            code = str(at['code'])
            if code in have:
                continue
            name = (ua(at) or '').strip()
            val = prom[sku].get(key(name))
            if not val:
                stat[f'немає в Prom: {name}'] += 1; continue
            opts = options(cat, code)
            # `key`, а не `.lower()`: апостроф різний і в ЗНАЧЕННЯХ, не лише в
            # назвах полів — «м'ятний» (U+0027) проти «мʼятний» (U+02BC) у
            # довіднику. 5 карток «Аромат» стояли порожні саме через це.
            vc = opts.get(key(val))
            if not vc:
                stat[f'значення поза довідником: {name}={val[:24]}'] += 1; continue
            fid = fids.get(code)
            if not fid:
                stat[f'немає id у формі: {name}'] += 1; continue
            # multiselect приймає ТІЛЬКИ список кодів. Рядок дає 400
            # `attributeValues[<code>]: validation.attribute.invalid` — саме це
            # 01.09 поклало всі 49 карток категорії 9476 («Тип помпи», 5249).
            cur.append({'id': fid, 'code': code,
                        'value': [vc] if at.get('type') == 'multiselect' else vc})
            filled_names[name] += 1; added += 1
        if not added:
            stat['нічого додати'] += 1; continue
        if a.plan:
            ok += 1; stat['заповнили б'] += 1
        else:
            body = {'attributeValues': cur, 'categories': d.get('categories'),
                    'isPrepayment': d.get('isPrepayment'), 'media': d.get('media'),
                    'productInPromotion': d.get('productInPromotion'),
                    'attributeSetCode': d.get('attributeSetCode'),
                    'companyId': d.get('companyId'), 'sku': d.get('sku'),
                    'translations': d.get('translations')}
            r2 = s.put(f'{API}/v4/pim/products/common/{p["id"]}', json=body, timeout=60)
            if r2.status_code in (200, 201, 204):
                ok += 1
            else:
                fail += 1
                # Повний текст, без обрізання: 01.09 обрізання на 140 символах
                # ховало саме поле `errors`, де названо проблемний атрибут.
                print(f'  {sku}: {r2.status_code} {r2.text}', file=sys.stderr)
                if a.dump_fails:
                    with open(a.dump_fails, 'a', encoding='utf-8') as fh:
                        json.dump({'sku': sku, 'id': p['id'], 'cat': cat,
                                   'status': r2.status_code, 'resp': r2.text,
                                   'body': body}, fh, ensure_ascii=False)
                        fh.write('\n')
            time.sleep(0.15)
        if i % 200 == 0:
            print(f'  {i}/{len(todo)} — заповнено {ok}', file=sys.stderr)

    print(f'\n{"порахував" if a.plan else "записано"}: {ok} | не вдалось: {fail}')
    print(f'\nяких полів додано: {sum(filled_names.values())} у '
          f'{len(filled_names)} різних полях')
    # без обрізання: 02.09 сума по 12 показаних рядках (912) не сходилась із
    # незалежним заміром (1037), і розбіжність була в невидимому хвості
    for k, v in filled_names.most_common():
        print(f'   {v:5}  {k}')
    print('\nчому пропущено:')
    for k, v in stat.most_common(10):
        print(f'   {v:5}  {k}')


if __name__ == '__main__':
    main()
