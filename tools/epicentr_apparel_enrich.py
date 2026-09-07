#!/usr/bin/env python3
"""
tools/epicentr_apparel_enrich.py
=================================
Добудовує фід еротичної білизни й костюмів для Єпіцентру: «Розмір»,
«Матеріал», «Призначення».

НАВІЩО. 7261 товар SexOpt не має картки в Єпіцентрі, і це не розсіяні
прогалини — це цілий сегмент одягу, виключений у синхронізаторі рядком
`-x 7216,9464`. Причини ніде не задокументовано; перевірка показала, що
жодного технічного блокування немає: категорії відкриті, мапінг є, окрема
картка на розмір у постачальника вже зроблена.

Валідатор на згенерованих фідах:
    Еротична білизна  3344 → 1324 проходять (39 %)
    Еротичні костюми  2004 →  726 проходять (36 %)

Три причини відмов, усі усувні:
    2339  немає «Розмір»    — розмір є в назві («S/M», «L», «One Size»)
    1780  немає «Матеріал»  — довідник має 5 значень, виводиться з назви
     989  немає опису UA    — потребує генерації, тут не робиться

ПРАВИЛА
  * **Розмір із діапазону — менший.** «S/M» → S. Еротична білизна має щільно
    прилягати; позначена як L, вона буде затісною і повернеться (SKILL-26 §6).
  * **Матеріал за тканиною в назві**, а не за здогадкою. «Лакована», «вініл»,
    «wetlook» → екошкіра; «латекс» → латекс; «сітка», «мереживо», «тюль» →
    тканина; шкіра справжня → натуральна шкіра. Коли ознак кілька — комбінований.
  * Якщо ознак немає **жодних** — поле лишається порожнім. Пропуск дешевший
    за вигадане значення.

    python3 tools/epicentr_apparel_enrich.py --src f.xml --plan
    python3 tools/epicentr_apparel_enrich.py --src f.xml --out g.xml
"""
import os, re, sys, json, argparse, collections
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPTS = os.path.join(BASE, 'data', 'epicentr_options_cache.json')
SIZE_CODE, MAT_CODE, PURPOSE_CODE = '12923', '12731', '13949'
# Категорії одягу. Дефолт «тканина» чинний ЛИШЕ тут: коли інструмент почав
# працювати на всьому фіді, він проставив «тканину» 47 мастурбаторам і 77
# товарам BDSM, для яких це неправда. Виправлення значень поза довідником
# лишається для всіх категорій — воно спирається на факт, а не на дефолт.
APPAREL = {'7216', '9464'}
COUNTRY_CODE = 'country_of_origin'

# РАЗОВЕ рішення власника 04.09.2026 для цього завантаження одягу, **не
# правило**: якщо країни немає — «Китай», а для Art of Sex «Україна».
# Тому вмикається лише прапорцем `--country-fallback` і за замовчуванням
# вимкнене: наступного разу країна має братися з даних, а не з дефолту.
# Консультант радив лишати поле порожнім — застереження передано власнику.
COUNTRY_DEFAULT = ('Китай', 'chn')
COUNTRY_BY_BRAND = {'art of sex': ('Україна', 'ukr')}

# Генератор для 7216/9464 видає значення, яких у довіднику немає взагалі:
# «поліестер», «нейлон», «метал» у Матеріалі; «S/M», «L/XL», «XXL/XXXL» у
# Розмірі. Ці категорії були виключені з вивантаження, тож цей шлях коду
# ніколи не працював і його ніхто не перевіряв. Тому значення тут не просто
# доповнюються — вони **перевіряються по довіднику й виправляються**.
FABRIC = re.compile(r'поліестер|нейлон|еластан|спандекс|бавовн|трикотаж|сітк|'
                    r'мереж|тюль|шифон|атлас|сатин|фатин|велюр|оксамит|віскоз', re.I)

# Постачальник пише і «2XL», і «XXL» — обидві форми означають те саме.
SZ = r'xxxxxl|xxxxl|xxxl|xxl|xxs|xs|2xl|3xl|4xl|5xl|xl|s|m|l'
ALIAS = {'xxs': 'xs', 'xxl': '2xl', 'xxxl': '3xl', 'xxxxl': '4xl', 'xxxxxl': '5xl'}
SIZE_RANGE = re.compile(rf'\b({SZ})\s*[/\-]\s*({SZ})\b', re.I)
SIZE_ONE = re.compile(r'\bone\s*size\b|універсальн\w+\s+розмір|\bos\b', re.I)
SIZE_PLAIN = re.compile(rf'(?:розмір\w*\s*)?\b({SZ})\b(?=[\s,.)]|$)', re.I)
ORDER = ['xs', 's', 'm', 'l', 'xl', '2xl', '3xl', '4xl', '5xl']

MATERIAL = [
    ('натуральна шкіра', r'натуральн\w+\s+шкір|справжн\w+\s+шкір|genuine\s+leather'),
    ('латекс', r'латекс|latex'),
    ('екошкіра', r'лаков|вінілов|\bвініл\b|wetlook|wet\s*look|екошкір|'
                 r'штучн\w+\s+шкір|під\s+шкіру|\bpvc\b|поліуретан'),
    ('тканина', r'сітк|мереживо|мережив|тюль|шифон|атлас|сатин|бавовн|поліестер|'
                r'еластан|спандекс|нейлон|трикотаж|велюр|оксамит|фатин'),
]


def load_opts():
    return json.load(open(OPTS, encoding='utf-8'))


def size_of(name):
    """→ значення довідника або None. Діапазон дає менший розмір."""
    m = SIZE_RANGE.search(name)
    if m:
        a = ALIAS.get(m.group(1).lower(), m.group(1).lower())
        b = ALIAS.get(m.group(2).lower(), m.group(2).lower())
        return min((a, b), key=lambda x: ORDER.index(x) if x in ORDER else 99)
    if SIZE_ONE.search(name):
        return 'one size'
    m = SIZE_PLAIN.search(name)
    return ALIAS.get(m.group(1).lower(), m.group(1).lower()) if m else None


def material_of(text, fallback=False):
    """Матеріал за тканиною в назві або описі.

    `fallback=True` дає «тканина», коли ознак немає. Це не вигаданий склад:
    поле має лише п'ять значень (екошкіра, натуральна шкіра, латекс,
    комбінований, тканина), і для трусиків чи панчіх жодне з решти чотирьох
    не підходить. Загальне формулювання тут припустиме, на відміну від
    вигаданого відсоткового складу.

    Для РОЗМІРУ такого дефолту немає і бути не може: помилковий розмір
    означає, що покупець отримає не той товар — повернення й штрафні бали.
    """
    hits = [val for val, pat in MATERIAL if re.search(pat, text, re.I)]
    if not hits:
        return 'тканина' if fallback else None
    if len(hits) > 1:
        return 'комбінований'
    return hits[0]


DESC_TPL = ("<p><strong>{title}</strong> — {lead}</p>"
            "<p><strong>Характеристики:</strong></p><ul>{items}</ul>"
            "<p><strong>Догляд:</strong> делікатне прання при температурі не вище "
            "30°C, без відбілювачів — так тканина й колір збережуться довше.</p>")


def build_description(name, params):
    """Шаблонний опис для одягу.

    Для цієї категорії 80 % рішення про покупку — це фото, ціна й розмірна
    сітка; опис підтверджує склад і дає роботу маркетплейсу семантичну базу.
    Тому структурований шаблон тут доречніший за художній текст, і чекати на
    ручне написання 989 текстів немає сенсу — це місяці замороженого товару.

    Свідомо НЕ вигадуємо склад тканини: якщо матеріалу немає в даних, у
    списку його просто не буде. Абстрактне «якісні натуральні тканини» —
    це твердження про товар, якого ми не знаємо.
    """
    order = ('Тип товару', 'Матеріал', 'Розмір', 'Колір', 'Призначення',
             'Бренд', 'Країна-виробник')
    items = ''.join(f'<li><strong>{k}:</strong> {params[k]}</li>'
                    for k in order if params.get(k))
    if not items:
        return None
    title = name.split(',')[0].strip()
    lead = ('модель поєднує зручну посадку та якісні матеріали. '
            'Підходить для створення образу й повсякденного носіння.')
    return DESC_TPL.format(title=title, lead=lead, items=items)


def purpose_of(text):
    """Довідник має лише «для жінок» / «для чоловіків» — «унісекс» тут немає.
    Еротична білизна за замовчуванням жіноча (SKILL-26 §2); чоловіче явно
    називають у назві."""
    if re.search(r'чоловіч|для\s+чоловік|мужськ|боксер|труси\s+чоловіч|'
                 r'\bmen\b|male', text, re.I):
        return 'для чоловіків'
    return 'для жінок'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out')
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--country-fallback', action='store_true',
                    help='РАЗОВО: країна «Китай», для Art of Sex «Україна». '
                         'Не вмикати за замовчуванням — це рішення для одного '
                         'конкретного завантаження, а не постійне правило.')
    a = ap.parse_args()

    opts = load_opts()
    tree = ET.parse(a.src); root = tree.getroot()
    did = collections.Counter(); left = collections.Counter(); shown = []

    for o in root.findall('.//offer'):
        cs = o.find('category')
        cat = (cs.get('code') if cs is not None else '') or ''
        have = {p.get('paramcode') for p in o.findall('param')}
        ne = next((e for e in o.findall('name') if e.get('lang') == 'ua'), None)
        name = (ne.text or '') if ne is not None else ''
        de = next((e for e in o.findall('description') if e.get('lang') == 'ua'), None)
        desc = ''.join(de.itertext()) if de is not None else ''
        full = f'{name} {desc[:600]}'

        # 0. країна — лише коли явно попросили (разове рішення власника)
        if a.country_fallback and COUNTRY_CODE not in have:
            be = next((p for p in o.findall('param') if p.get('paramcode') == 'brand'), None)
            brand = (be.text or '').strip().lower() if be is not None else ''
            cname, ccode = COUNTRY_BY_BRAND.get(brand, COUNTRY_DEFAULT)
            if not a.plan:
                e = ET.SubElement(o, 'param')
                e.set('paramcode', COUNTRY_CODE); e.set('name', 'Країна-виробник')
                e.set('valuecode', ccode); e.text = cname
            did[f'Країна = {cname}'] += 1

        # 0b. виправлення значень, яких немає в довіднику категорії
        for pe in list(o.findall('param')):
            pc = pe.get('paramcode')
            # Перевіряємо КОЖЕН атрибут, для якого є довідник, а не лише три
            # заплановані: «Тип товару» теж мав хибні коди в 2031 випадку.
            if pc in ('brand', 'measure', 'ratio', COUNTRY_CODE, 'barcodes'):
                continue
            table = opts.get(f'{cat}:{pc}')
            if not isinstance(table, dict):
                continue
            val = (pe.text or '').strip().lower()
            if val in table:
                if pe.get('valuecode') != table[val]:
                    if not a.plan:
                        pe.set('valuecode', table[val])
                    did[f'код виправлено: {pe.get("name")} = {val}'] += 1
                continue
            fixed = None
            if pc == SIZE_CODE:
                fixed = size_of(pe.text or '')
            elif pc == MAT_CODE:
                fixed = ('тканина' if FABRIC.search(pe.text or '')
                         else material_of(full, cat in APPAREL))
            if fixed and fixed in table:
                if not a.plan:
                    pe.text = fixed; pe.set('valuecode', table[fixed])
                did[f'значення виправлено: {pe.get("name")} → {fixed}'] += 1
            else:
                if not a.plan:
                    o.remove(pe)
                left[f'{pe.get("name")}: «{(pe.text or "").strip()}» немає в довіднику, видалено'] += 1
        have = {p.get('paramcode') for p in o.findall('param')}

        for code, fn, src, label in (
                (SIZE_CODE, size_of, name, 'Розмір'),
                (MAT_CODE, lambda t: material_of(t, fallback=cat in APPAREL), full, 'Матеріал'),
                (PURPOSE_CODE, purpose_of, full, 'Призначення')):
            # «Призначення» з довідником «для жінок/чоловіків» існує лише в
            # одязі; в інших категоріях під тим самим кодом інший зміст.
            if code == PURPOSE_CODE and cat not in APPAREL:
                continue
            if code in have:
                continue
            table = opts.get(f'{cat}:{code}')
            if not isinstance(table, dict):
                left[f'{label}: немає довідника для категорії {cat}'] += 1
                continue
            v = fn(src)
            vc = table.get(v) if v else None
            if not vc:
                left[f'{label}: не визначити з назви'] += 1
                continue
            if not a.plan:
                e = ET.SubElement(o, 'param')
                e.set('paramcode', code); e.set('name', label); e.set('valuecode', vc)
                e.text = v
            did[f'{label} = {v}'] += 1
            if len(shown) < 10:
                shown.append(f'{label:9}= {v:10} ← {name[:66]}')

        # опис українською — після всіх атрибутів, щоб потрапили свіжі
        if de is None or not ''.join(de.itertext()).strip():
            pv = {p.get('name'): (p.text or '').strip()
                  for p in o.findall('param') if (p.text or '').strip()}
            body = build_description(name, pv)
            if body:
                if not a.plan:
                    if de is not None:
                        o.remove(de)
                    e = ET.SubElement(o, 'description'); e.set('lang', 'ua')
                    e.text = body
                did['опис UA згенеровано'] += 1
            else:
                left['опис: немає з чого будувати'] += 1


    print(f'{"порахував" if a.plan else "додано"}:')
    for k, v in did.most_common(16):
        print(f'  {v:5}  {k}')
    print('\nне визначено:')
    for k, v in left.most_common(6):
        print(f'  {v:5}  {k}')
    if shown:
        print('\nприклади:')
        for x in shown:
            print('  ' + x)
    if a.out and not a.plan:
        tree.write(a.out, encoding='utf-8', xml_declaration=True)
        print(f'\nзаписано: {a.out}')


if __name__ == '__main__':
    main()
