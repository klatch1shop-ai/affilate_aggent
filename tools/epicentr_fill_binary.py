#!/usr/bin/env python3
"""
tools/epicentr_fill_binary.py
==============================
Заповнює обовʼязкові булеві характеристики («Так/Ні») значенням «Ні» там,
де в тексті картки немає жодної згадки про цю властивість.

Підстава — рішення власника 02.09.2026: «за відсутність згадки — Ні».
Це найбільший клас прогалин: 2290 полів у картках NOIRE.

ЧОМУ ЛИШЕ ВІДСУТНІСТЬ ЗГАДКИ, А НЕ ВСІ ПІДРЯД:
якщо властивість у тексті ЗГАДАНА, «Ні» ставити не можна — треба читати
контекст. Ми вже маємо на цьому опік: `has_heating` вважав підігрів
наявним у фразі «можна нагріти у воді», і 286 карток отримали хибне «так».
Тому картки зі згадкою пропускаємо й виносимо окремим переліком.

Булевим вважається поле, у довіднику якого РІВНО два значення — «так» і
«ні». Перелік беремо з `data/epicentr_options_cache.json`, а не на око.

    python3 tools/epicentr_fill_binary.py --plan
    python3 tools/epicentr_fill_binary.py [--limit N]
"""
import os, sys, json, time, re, argparse, collections
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
API = 'https://core-api.epicentrm.com.ua'

# Слова, за якими шукаємо згадку властивості в тексті картки.
# Ключ — початок назви характеристики в нижньому регістрі.
HINTS = {
    'підігрів':        r'підігрів|нагрів|тепл',
    'вібрація':        r'вібр',
    'водонепроник':    r'водонепроник|вологозахищ|у\s+воді|під\s+душем|ip[x]?\d',
    'керування через': r'застосун|додаток|\bapp\b|smart|bluetooth|блютуз',
    'пульт':           r'пульт|дистанц|\bдк\b',
    'акумулятор':      r'акумулятор|usb|заряд',
    'нагрів':          r'нагрів|підігрів|тепл',
    'присоск':         r'присоск',
    'телескопіч':      r'телескоп|поступальн|фрикц',
    'ремені':          r'рем[іе]н|фіксац',
    'без фталат':      r'фталат',
    'їстів':           r'їстів|орально|смак',
    'гіпоалерген':     r'гіпоалерген|алерг',
}


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def hint_for(name):
    low = (name or '').lower()
    for k, pat in HINTS.items():
        if low.startswith(k):
            return pat
    # загальний випадок: шукаємо корінь самої назви (перші 6 літер)
    root = re.sub(r'[^а-яіїєґa-z]', '', low)[:6]
    return root if len(root) >= 4 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    opts = json.load(open(os.path.join(BASE, 'data', 'epicentr_options_cache.json'),
                          encoding='utf-8'))
    # булеві: рівно два значення, і це «так»/«ні»
    binary = {k: v for k, v in opts.items()
              if isinstance(v, dict) and len(v) == 2
              and set(x.strip().lower() for x in v) == {'так', 'ні'}}
    print(f'булевих полів у довіднику: {len(binary)}')

    gaps = json.load(open(os.path.join(BASE, 'docs', 'epicentr_remaining_gaps.json'),
                          encoding='utf-8'))
    prods = {x['id']: x for x in json.load(
        open(os.path.join(BASE, 'data', 'epicentr_products.json'), encoding='utf-8'))}

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
            form_cache[cat] = {str(x['code']): x['id'] for x in items}
        return form_cache[cat]

    todo = gaps[:a.limit] if a.limit else gaps
    ok = fail = 0
    stat = collections.Counter(); mentioned = []
    for i, g in enumerate(todo, 1):
        cat = str(g['category'])
        cand = [m for m in g['missing'] if f"{cat}:{m['code']}" in binary]
        if not cand:
            stat['булевих прогалин немає'] += 1; continue
        try:
            d = s.get(f"{API}/v2/pim/products/{g['id']}", timeout=45)
            if d.status_code == 401:
                login(s); d = s.get(f"{API}/v2/pim/products/{g['id']}", timeout=45)
            d = d.json()
        except Exception:
            fail += 1; continue
        if d.get('status') != 'enrich':
            stat['уже не enrich'] += 1; continue
        # текст картки: назва + опис
        txt = ' '.join(
            (t.get('title') or '') + ' ' + (t.get('value') or '')
            for t in (d.get('translations') or []))
        for v in (d.get('attributeValues') or []):
            if str(v.get('code')) == 'description':
                txt += ' ' + str(v.get('value') or '')
        low = txt.lower()

        cur = [{'id': v['id'], 'code': v['code'], 'value': v['value']}
               for v in (d.get('attributeValues') or [])]
        have = {str(v['code']) for v in cur if v.get('value') not in (None, '', [])}
        fids = form_ids(cat)
        added = 0
        for m in cand:
            code = str(m['code'])
            if code in have:
                continue
            pat = hint_for(m.get('name'))
            if pat and re.search(pat, low):
                stat['згадано в тексті — пропускаю'] += 1
                mentioned.append({'sku': g['sku'], 'attr': m.get('name')})
                continue
            no = binary[f'{cat}:{code}'].get('ні') or binary[f'{cat}:{code}'].get('Ні')
            fid = fids.get(code)
            if not no or not fid:
                stat['немає значення «ні» або id'] += 1; continue
            cur.append({'id': fid, 'code': code, 'value': no})
            added += 1
        if not added:
            stat['нічого додати'] += 1; continue
        stat['полів «Ні»'] += added
        if a.plan:
            ok += 1; continue
        body = {'attributeValues': cur, 'categories': d.get('categories'),
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
        if i % 200 == 0:
            print(f'  {i}/{len(todo)} — карток {ok}', file=sys.stderr)

    json.dump(mentioned, open(os.path.join(BASE, 'docs', 'epicentr_binary_mentioned.json'),
                              'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n{"порахував" if a.plan else "записано"} карток: {ok} | не вдалось: {fail}')
    for k, v in stat.most_common(8):
        print(f'   {v:5}  {k}')
    print(f'\nзгадані в тексті (окремий розбір) → docs/epicentr_binary_mentioned.json')


if __name__ == '__main__':
    main()
