#!/usr/bin/env python3
"""Незалежна перевірка готового фіду KATRAN → Rozetka.

Читає ГОТОВИЙ файл і звіряє його з джерелом та з правилами Rozetka. Нічого
не знає про генератор: власник 06.10 сказав, що генератору довіри немає,
тож підсумковий рядок генератора доказом не є.

Перевіряє:
  структура — обовʼязкові теги, валідний XML, унікальність id
  гроші     — жодна ціна не нижча за закупівлю з ПДВ (звіряється з джерелом)
  бренди    — жодного стоп-бренда для його категорії
  категорії — кожен rz_id існує в офіційному каталозі Rozetka
  склад     — кожен товар є в джерелі зі `stock` = «есть»
  зміст     — фото, довжина назви, порожні описи
"""
import collections
import io
import os
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'tools'))
from dotenv import load_dotenv                                     # noqa: E402
load_dotenv(os.path.join(BASE, '.env'), override=True)
from rozetka_stop_brands import banned, load as load_stop          # noqa: E402

REQUIRED = ('price', 'currencyId', 'categoryId', 'vendor', 'article',
            'stock_quantity', 'name', 'name_ua')
TITLE_MAX = 200


def source_index():
    r = requests.get(os.environ['KATRAN_FEED_URL_STOCK'], timeout=180)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        n = [x for x in z.namelist() if x.lower().endswith('.xml')][0]
        root = ET.parse(z.open(n)).getroot()
    out = {}
    for p in root.find('products'):
        def g(t):
            return (p.findtext(t) or '').strip()
        key = g('artikul') or g('code')
        out[key] = {'stock': g('stock'),
                    'pdv': float((g('price_pdv') or '0').replace(',', '.') or 0),
                    'rrc': float((g('price_rrc') or '0').replace(',', '.') or 0),
                    'vendor': g('vendor')}
    return out


def check(path):
    import json
    root = ET.parse(path).getroot()
    shop = root.find('shop')
    cats = {c.get('id'): (c.get('rz_id'), (c.text or '').strip())
            for c in shop.find('categories')}
    offers = list(shop.find('offers'))
    src = source_index()
    official = {str(x['rz_id']) for x in
                json.load(open(os.path.join(BASE, 'docs',
                                            'rozetka_categories_all.json'),
                               encoding='utf-8'))}
    stop = load_stop()
    bad = collections.Counter()
    examples = collections.defaultdict(list)

    def flag(key, text):
        bad[key] += 1
        if len(examples[key]) < 3:
            examples[key].append(text)

    ids = collections.Counter()
    for o in offers:
        oid = o.get('id')
        ids[oid] += 1
        get = lambda t: (o.findtext(t) or '').strip()          # noqa: E731
        for t in REQUIRED:
            if not get(t):
                flag(f'немає тега <{t}>', oid)
        if not o.findall('picture'):
            flag('без фото', oid)
        name = get('name')
        if len(name) > TITLE_MAX:
            flag(f'назва довша за {TITLE_MAX}', f'{oid}: {len(name)}')
        if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ET.tostring(o, 'unicode')):
            flag('недруковані символи', oid)

        cid = get('categoryId')
        rz = cats.get(cid, (None, None))[0]
        if rz is None:
            flag('categoryId не оголошений', oid)
        elif rz not in official:
            flag('rz_id немає в каталозі Rozetka', f'{oid}: {rz}')

        s = src.get(oid)
        if s is None:
            flag('товару немає в джерелі', oid)
            continue
        if s['stock'] != 'есть':
            flag('у джерелі НЕ на складі', f'{oid}: {s["stock"]}')
        price = float(get('price') or 0)
        if s['pdv'] > 0 and price <= s['pdv']:
            flag('ЦІНА НИЖЧА ЗА ЗАКУПІВЛЮ',
                 f'{oid}: ціна {price:.0f} ≤ закупівля {s["pdv"]:.0f}')
        b, why = banned(get('vendor'), cats.get(cid, (None, ''))[1], stop)
        if b:
            flag('СТОП-БРЕНД', f'{oid}: {why}')

    for oid, n in ids.items():
        if n > 1:
            flag('дублікат id', oid)

    print(f'фід: {path}')
    print(f'  офферів: {len(offers)} | категорій: {len(cats)}')
    def body(o):
        # strip() з набором символів з'їдає літери з країв, а не обгортку:
        # 06.10 через це показувалось 0 % замість справжніх 5 %.
        t = (o.findtext('description') or '').strip()
        return re.sub(r'^<p>|</p>$', '', t).strip()
    desc_eq = sum(1 for o in offers if body(o) == (o.findtext('name') or '').strip())
    print(f'  опис дорівнює назві: {desc_eq} ({desc_eq/max(len(offers),1)*100:.0f}%)')
    if not bad:
        print('\n✅ помилок не знайдено')
        return 0
    print('\n❌ ЗНАЙДЕНО:')
    for k, n in bad.most_common():
        print(f'  {k:<34}{n:>5}')
        for e in examples[k]:
            print(f'       {e}')
    return 1


if __name__ == '__main__':
    sys.exit(check(sys.argv[1] if len(sys.argv) > 1
                   else os.path.join(BASE, 'data', 'katran_rozetka.xml')))
