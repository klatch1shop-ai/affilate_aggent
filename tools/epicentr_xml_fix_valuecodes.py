"""Виправляє `valuecode` у згенерованому XML за опублікованими картками.

Привід (27.09.2026, реальний імпорт): із 578 товарів створено 275, а 303 впали
з помилкою «Значення "13949" по характеристиці "Стать" відсутнє в довіднику».
13949 — це код САМОЇ характеристики, а не її значення: генератор писав
`valuecode="{paramcode}"` для 495 параметрів. Ще частина несла довгі хеші з
`/options`, які майданчик теж не приймає.

Джерело правильних кодів — **опубліковані картки того самого набору**: там
значення вже пройшли модерацію, а в тілі відповіді API кожне несе і свій код,
і український переклад. Це те саме відкриття, що дозволило закрити 1492 картки.

Параметр, для якого коду не знайшлось, **вилучається** з offer: краще картка
без необовʼязкової характеристики, ніж 303 відмови.

    venv/bin/python tools/epicentr_xml_fix_valuecodes.py \
        --xml exports/epicentr_new_cards_ready.xml \
        --out exports/epicentr_new_cards_fixed.xml
"""
import argparse
import collections
import concurrent.futures as cf
import json
import os
import re
import sys

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

API = 'https://core-api.epicentrm.com.ua'
PRODUCTS = os.path.join(BASE, 'data', 'epicentr_products.json')
# Числові й текстові характеристики: у них немає довідника, значення йде як є.
PLAIN = {'measure', 'ratio', 'brand', 'country_of_origin', 'weight', 'width',
         'height', 'length', 'description'}
# Атрибути, чиїм кодам у файлі не можна вірити взагалі — їх ЗАВЖДИ переписуємо
# з опублікованих карток. «Матеріал» потрапив сюди після двох імпортів поспіль:
# перелічувати конкретні хеші марно, їх щоразу виявлялись нові
# (de9da787…, 063a479f…, df250c82…, 8b5e660f…, 7f2e25e7…).
ALWAYS_REMAP = {'Матеріал'}

# Генератор кладе СИРИЙ матеріал постачальника («нейлон», «поліестер»,
# «80% поліамід, 20% еластан»), а довідник Єпіцентру знає лише узагальнені
# категорії. Без цього зведення 189 карток лишались без обовʼязкового поля.
MATERIAL_TO_DICT = {
    'нейлон': 'тканина', 'поліестер': 'тканина', 'поліамід': 'тканина',
    'еластан': 'тканина', 'спандекс': 'тканина', 'бавовн': 'тканина',
    'віскоз': 'тканина', 'мереж': 'тканина', 'сітк': 'тканина',
    'мікрофібр': 'тканина', 'атлас': 'тканина', 'сатин': 'тканина',
    'синтетичне волокно': 'тканина', 'текстиль': 'тканина', 'шифон': 'тканина',
    'пліс': 'тканина', 'велюр': 'тканина', 'шовк': 'тканина', 'льон': 'тканина',
    'pvc': 'АБС-пластик', 'полівінілхлорид': 'АБС-пластик',
    'пластик': 'АБС-пластик', 'абс': 'АБС-пластик', 'акрил': 'АБС-пластик',
    'tpe': 'TPE (термопластичний еластомер)', 'термопластич': 'TPE (термопластичний еластомер)',
    'tpr': 'TPE (термопластичний еластомер)', 'еластомер': 'TPE (термопластичний еластомер)',
    'латекс': 'латекс', 'гума': 'латекс',
    # Для білизни «силікон», «метал», «АБС-пластик» із довідника ВИДАЛЕНІ.
    # Виріб із такими вставками — комбінований, це найближче чесне значення.
    'силікон': 'комбінований', 'сталь': 'комбінований', 'метал': 'комбінований',
    'алюміні': 'комбінований', 'цинк': 'комбінований', 'стразі': 'комбінований',
    'шкіра натуральна': 'натуральна шкіра', 'натуральна шкіра': 'натуральна шкіра',
    'екошкір': 'екошкіра', 'штучна шкіра': 'екошкіра', 'шкірзам': 'екошкіра',
    'картон': 'картон', 'папер': 'картон',
}


def to_dictionary_value(raw, options):
    """Сире значення постачальника → назва з довідника, або None."""
    lowered = (raw or '').casefold()
    hits = sorted((lowered.find(word), target)
                  for word, target in MATERIAL_TO_DICT.items()
                  if lowered.find(word) >= 0 and target.casefold() in options)
    return hits[0][1] if hits else None


def login(session):
    r = session.post(f'{API}/v2/users/login',
                     json={'login': os.getenv('EPICENTR_EMAIL'),
                           'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    session.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def ua(obj):
    for t in (obj or {}).get('translations', []):
        if t.get('languageCode') == 'ua':
            return t.get('value') or t.get('title')
    return None


def learn(session, products, set_code, sample):
    """{код атрибута: {українська назва значення: код значення}} з опублікованих."""
    pool = [p for p in products if p.get('status') == 'published'
            and str(p.get('attributeSetCode')) == str(set_code)][:sample]
    table = collections.defaultdict(dict)

    def fetch(p):
        try:
            return session.get(f"{API}/v2/pim/products/{p['id']}", timeout=45).json()
        except Exception:
            return None

    with cf.ThreadPoolExecutor(max_workers=6) as pool_ex:
        for data in pool_ex.map(fetch, pool):
            for v in ((data or {}).get('attributeValues') or []):
                for option in (v.get('options') or []):
                    # ГОЛОВНЕ (27.09): опубліковані картки зберігають ВИДАЛЕНІ
                    # значення за інерцією — `deleted: true` / `outOfMapping:
                    # true`. Для нового імпорту майданчик їх уже не приймає,
                    # і саме на них я вчився два імпорти поспіль.
                    if option.get('deleted') or option.get('outOfMapping'):
                        continue
                    name = ua(option)
                    if name:
                        table[str(v['code'])][name.strip().casefold()] = option['code']
    return table


def live_options(set_code, attr_code, _cache={}):
    """Чинний довідник майданчика — запасне джерело, коли серед опублікованих
    карток лишились самі видалені значення."""
    key = (set_code, attr_code)
    if key not in _cache:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'afm', os.path.join(BASE, 'tools', 'epicentr_attr_fill_multi.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            _cache[key] = {k.strip().casefold(): v
                           for k, v in module.options(set_code, attr_code).items() if k}
        except Exception:
            _cache[key] = {}
    return _cache[key]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--xml', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--sample', type=int, default=80)
    ap.add_argument('--report', default=os.path.join(BASE, 'exports', 'valuecode_fix.csv'))
    a = ap.parse_args()

    text = open(a.xml, encoding='utf-8').read()
    products = json.load(open(PRODUCTS, encoding='utf-8'))
    sets = sorted({m for m in re.findall(r'<attribute_set code="(\d+)"', text)})

    session = requests.Session()
    session.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                            'Accept-Language': 'uk-UA'})
    login(session)

    tables = {}
    for set_code in sets:
        tables[set_code] = learn(session, products, set_code, a.sample)
        print(f'  набір {set_code}: довідників {len(tables[set_code])}', flush=True)

    stats = collections.Counter()
    unresolved = collections.Counter()

    def fix_offer(match):
        offer = match.group(0)
        set_code = re.search(r'<attribute_set code="(\d+)"', offer)
        table = tables.get(set_code.group(1) if set_code else '', {})

        def fix_param(pm):
            whole = pm.group(0)
            name, code, current, value = pm.group(1), pm.group(2), pm.group(3), pm.group(4)
            if code in PLAIN:
                stats['без довідника — лишаємо'] += 1
                return whole
            # Точкове втручання. 275 карток імпортувались успішно САМЕ з цими
            # кодами, тож переписувати все підряд означало б зламати те, що
            # працює. Чіпаємо лише те, що звіт імпорту назвав помилковим:
            # valuecode, рівний коду характеристики, і перелічені матеріали.
            broken = (current == code) or (name in ALWAYS_REMAP)
            if not broken:
                stats['не чіпаємо (працює)'] += 1
                return whole
            # Для ALWAYS_REMAP джерело істини — ЧИННИЙ довідник майданчика.
            # 27.09: у «Матеріалі» наборів 7216/9464 лишилось 5 значень, а
            # «силікон», «метал», «АБС-пластик» видалено. Опубліковані картки
            # їх досі показують, і навчання на них давало відхилені коди.
            if name in ALWAYS_REMAP:
                options = live_options(set_code.group(1) if set_code else '', code)
                stats['довідник із /options'] += 1
            else:
                options = table.get(code) or {}
                if not options:
                    options = live_options(set_code.group(1) if set_code else '', code)
            correct = options.get((value or '').strip().casefold()) if options else None
            if not correct and options and name in ALWAYS_REMAP:
                mapped = to_dictionary_value(value, options)
                if mapped:
                    correct = options.get(mapped.casefold())
                    if correct:
                        stats['зведено до довідника'] += 1
                        return (f'<param name="{name}" paramcode="{code}" '
                                f'valuecode="{correct}">{mapped}</param>')
            if correct:
                stats['виправлено'] += 1
                return (f'<param name="{name}" paramcode="{code}" '
                        f'valuecode="{correct}">{value}</param>')
            # Коду немає серед того, що пройшло модерацію — прибираємо параметр.
            stats['прибрано (немає в довіднику)'] += 1
            unresolved[f'{name} = {value}'] += 1
            return ''

        fixed = re.sub(r'<param name="([^"]+)" paramcode="([^"]+)"'
                       r'(?: valuecode="([^"]*)")?>([^<]*)</param>', fix_param, offer)
        return re.sub(r'\n\s*\n', '\n', fixed)

    out = re.sub(r'  <offer .*?  </offer>', fix_offer, text, flags=re.DOTALL)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(out)

    for key, n in stats.most_common():
        print(f'  {n:>6}  {key}')
    print('\nнайчастіше не знайшлось:')
    for key, n in unresolved.most_common(12):
        print(f'  {n:>5}  {key}')
    with open(a.report, 'w', encoding='utf-8') as f:
        f.write('значення,кількість\n')
        for key, n in unresolved.most_common():
            f.write(f'"{key}",{n}\n')
    print(f'\n→ {a.out}\n→ {a.report}')


if __name__ == '__main__':
    main()
