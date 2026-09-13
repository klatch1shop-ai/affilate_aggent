#!/usr/bin/env python3
"""
tools/epicentr_valuecode_audit.py
==================================
Звіряє valuecode кожного параметра фіду з живим довідником Єпіцентру.

ЧОМУ ЦЕ ПОТРІБНО ОКРЕМИМ ІНСТРУМЕНТОМ. Імпорт 04.09.2026 відхилив 53 картки
з 1530. Причина в усіх однакова: у `valuecode` стоїть значення, якого в
довіднику цієї категорії немає. Два різні дефекти під одним симптомом:

  * `valuecode="3369"` — у поле значення записаний **код самої
    характеристики** («3369» це код поля «Призначення»);
  * `valuecode="8c64e0f6…"` — хеш існує, але належить довіднику **іншої**
    категорії. Коди значень у Єпіцентрі per-category, і той самий «силікон»
    у страпонах і вібраторах має різні коди.

Попередня перевірка ловила лише те, для чого був локальний кеш опцій. Там,
де кешу не було, параметр проходив без перевірки — саме ці 53 і пройшли.
Тому довідник тягнемо з API для **кожної категорії, що є у фіді**, а не з
того, що випадково лежить у кеші.

Невалідний параметр **видаляється**, а не виправляється: підставити «схоже»
значення означало б написати про товар те, чого ми не знаємо. Відсутній
атрибут максимум завадить фільтру, хибний — бреше покупцеві.

    python3 tools/epicentr_valuecode_audit.py --src f.xml --plan
    python3 tools/epicentr_valuecode_audit.py --src f.xml --out g.xml
"""
import os, re, sys, json, argparse, collections
import xml.etree.ElementTree as ET
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
API = 'https://core-api.epicentrm.com.ua'
CACHE = os.path.join(BASE, 'data', 'epicentr_valuecodes.json')
# Системні поля мають власні коди-рядки («chn», «measure_pcs»), не хеші.
SYSTEM = {'measure', 'ratio', 'brand', 'country_of_origin', 'barcodes',
          'width', 'height', 'length', 'weight'}


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def load_dicts(_cats, refresh=False):
    """{cat: {paramcode: [valuecode, …]}} з локального кешу опцій.

    Форма атрибутів (`/forms/attribute-set/.../attributes`) повертає
    `options: null` — самі значення там не приходять, лише `totalOptions`.
    Довідник збирається окремим ендпоінтом merchant-api, і він вимагає
    **іншого токена** (`EPICENTR_TOKEN`, не JWT сесії) та пагінації через
    `page`. Переклад значення лежить у полі `value`, а не `title` — на цьому
    я спершу отримав 239 порожніх довідників поспіль і хибний висновок
    «жодне значення не валідне».
    """
    raw = json.load(open(os.path.join(BASE, 'data', 'epicentr_options_cache.json'),
                         encoding='utf-8'))
    out = collections.defaultdict(dict)
    for key, vals in raw.items():
        if ':' not in key or not isinstance(vals, dict):
            continue
        cat, pc = key.split(':', 1)
        out[cat][pc] = set(vals.values())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out')
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--refresh', action='store_true')
    a = ap.parse_args()

    tree = ET.parse(a.src); root = tree.getroot()
    offers = root.findall('.//offer')
    cats = sorted({(o.find('category').get('code') or '')
                   for o in offers if o.find('category') is not None})
    print(f'офферів: {len(offers)} | категорій: {len(cats)}')
    dicts = load_dicts([c for c in cats if c], a.refresh)

    bad = collections.Counter(); hit = collections.Counter(); touched = set()
    for o in offers:
        cs = o.find('category')
        cat = cs.get('code') if cs is not None else ''
        table = dicts.get(cat) or {}
        for p in list(o.findall('param')):
            pc = p.get('paramcode') or ''
            vc = p.get('valuecode')
            if pc in SYSTEM or not vc:
                continue
            allowed = table.get(pc)
            if allowed is None:            # атрибута немає в наборі категорії
                bad[f'{p.get("name")}: атрибута немає в наборі категорії {cat}'] += 1
            elif vc not in allowed:
                why = ('код характеристики замість значення'
                       if re.fullmatch(r'\d{2,6}', vc) else 'значення з чужої категорії')
                bad[f'{p.get("name")}: {why}'] += 1
            else:
                hit[pc] += 1
                continue
            touched.add(o.get('id'))
            if not a.plan:
                o.remove(p)

    print(f'\nкоректних значень: {sum(hit.values())}')
    print(f'ХИБНИХ: {sum(bad.values())} у {len(touched)} картках')
    for k, v in bad.most_common(14):
        print(f'  {v:5}  {k}')
    if a.out and not a.plan:
        tree.write(a.out, encoding='utf-8', xml_declaration=True)
        print(f'\nзаписано: {a.out}')


if __name__ == '__main__':
    main()
