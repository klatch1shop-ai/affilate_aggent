#!/usr/bin/env python3
"""
tools/prom_units_normalize.py
==============================
Зведення числових характеристик фіду Prom до еталонного формату:

    <param name="Довжина" unit="мм">102</param>
    <param name="Діаметр" unit="мм">38</param>
    <param name="Вага"    unit="г">36</param>
    <param name="Обʼєм"   unit="мл">100</param>

ЩО САМЕ ЗЛАМАНО. У фіді той самий розмір лежить у двох одиницях під двома
іменами полів: «Довжина» з медіаною 18 (сантиметри) і «Довжина (мм)» з
медіаною 100. Атрибута unit немає ніде. Для повзунка-фільтра Prom це один
стовпець, тож 18 і 100 стоять поруч як різні розміри, хоч означають те саме.
Гірше: 280 значень суперечать навіть власному імені поля — менструальна чаша
«діаметр 3,8 см» має <param name="Діаметр">38</param>.

ЧОМУ ЧИСТА ЕВРИСТИКА «>15 БЕЗ КРАПКИ = МІЛІМЕТРИ» НЕ ПІДХОДИТЬ. У полі
«Довжина» медіана 18 — це вібратори завдовжки 18 **сантиметрів**, записані
цілим числом. Евристика перетворила б їх на 18 мм, тобто зіпсувала б 600+
карток, які зараз коректні. Тому порядок джерел такий:

  1. **назва товару** — якщо вона каже «діаметр 3,5 см», це доказ, а не здогад;
  2. **суфікс у назві поля** — «Довжина (мм)» означає міліметри;
  3. **фізична правдоподібність** — з двох прочитань беремо те, що потрапляє
     в реальний діапазон для цього типу товару;
  4. якщо однозначно не виходить — **не чіпаємо** і виводимо в список на
     ручний розгляд. Мовчазна здогадка тут гірша за пропуск.

    python3 tools/prom_units_normalize.py --sample 25
    python3 tools/prom_units_normalize.py --write output/noire_prom_units.xml
"""
import os, re, sys, argparse, collections
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.environ.get('STEP_SRC') or os.path.join(BASE, 'output', 'noire_prom.xml')

# Поля, що описують одну величину під різними іменами → канонічне ім'я й одиниця
CANON = {
    'довжина': ('Довжина', 'мм'), 'діаметр': ('Діаметр', 'мм'),
    'ширина': ('Ширина', 'мм'), 'висота': ('Висота', 'мм'),
    'глибина': ('Глибина', 'мм'), 'вага': ('Вага', 'г'),
    'обєм': ('Обʼєм', 'мл'), 'об’єм': ('Обʼєм', 'мл'), "об'єм": ('Обʼєм', 'мл'),
    'об`єм': ('Обʼєм', 'мл'),
}
# Правдоподібні межі в МІЛІМЕТРАХ (для ваги — грами, для обʼєму — мілілітри)
PLAUSIBLE = {
    # Нижні межі підняті свідомо: товару завдовжки 2 см або діаметром 5 мм у
    # цьому каталозі не буває, а широкий діапазон робив половину значень
    # «однаково правдоподібними» і в міліметрах, і в сантиметрах.
    'Довжина': (30, 2500), 'Діаметр': (8, 200), 'Ширина': (10, 600),
    'Висота': (10, 600), 'Глибина': (10, 600), 'Вага': (1, 20000),
    'Обʼєм': (1, 5000),
}
NUM = re.compile(r'^\s*([0-9]+(?:[.,][0-9]+)?)\s*(мм|см|м|г|кг|мл|л)?\.?\s*$', re.I)
TO_MM = {'мм': 1, 'см': 10, 'м': 1000}
TO_G = {'г': 1, 'кг': 1000}
TO_ML = {'мл': 1, 'л': 1000}


def canon(field):
    key = re.sub(r'[\s(,].*$', '', field.strip().lower())
    key = re.sub(r'[^а-яіїєґ\'`’]', '', key)
    return CANON.get(key)


def unit_in_field(field):
    mo = re.search(r'[(,]\s*(мм|см|м|г|кг|мл|л)\)?\s*$', field.strip(), re.I)
    return mo.group(1).lower() if mo else None


def from_name(name, canon_name):
    """Доказ із назви товару: «діаметр 3,5 см» → 35 мм."""
    word = {'Довжина': r'довжин\w*', 'Діаметр': r'діаметр\w*',
            'Вага': r'(?:вага|маса)', 'Обʼєм': r'об.?єм'}.get(canon_name)
    if not word:
        return None
    mo = re.search(word + r'\s*[-–:]?\s*(\d+(?:[.,]\d+)?)\s*(мм|см|м|г|кг|мл|л)\b',
                   name, re.I)
    if not mo and canon_name == 'Обʼєм':
        # у назві косметики обʼєм пишуть без слова: «(4 мл)», «100мл»
        mo = re.search(r'(\d+(?:[.,]\d+)?)\s*(мл|л)\b', name, re.I)
    if not mo:
        return None
    v = float(mo.group(1).replace(',', '.')); u = mo.group(2).lower()
    if canon_name == 'Вага':
        return v * TO_G.get(u, 0) or None
    if canon_name == 'Обʼєм':
        return v * TO_ML.get(u, 0) or None
    return v * TO_MM.get(u, 0) or None


def convert(field, raw, name, unit_attr=None):
    """→ (значення в канонічній одиниці, чим доведено) або (None, причина).

    ІДЕМПОТЕНТНІСТЬ. Якщо параметр уже має атрибут `unit` із канонічною
    одиницею, значення вже зведене — чіпати його не можна. Без цієї перевірки
    повторний прогін по вже обробленому фіду множив довжину ще раз: медіана
    165 мм ставала 1320. У бойовому конвеєрі це не спрацьовувало, бо генератор
    щоразу збирає фід із джерела, — але будь-який повторний запуск по готовому
    файлу тихо псував дані.
    """
    c = canon(field)
    if not c:
        return None, 'не числове поле'
    cname, cunit = c
    if unit_attr and unit_attr.strip().lower() == cunit:
        return None, 'уже зведено (unit=)'
    mo = NUM.match(raw or '')
    if not mo:
        return None, f'значення не число: «{raw}»'
    val = float(mo.group(1).replace(',', '.'))
    inline = (mo.group(2) or '').lower()
    lo, hi = PLAUSIBLE[cname]
    table = TO_G if cunit == 'г' else TO_ML if cunit == 'мл' else TO_MM

    # Десяткова частина сама по собі є доказом: «20.1» — це сантиметри, бо
    # міліметри з десятими ніхто не пише. Це знімає більшість неоднозначностей.
    has_frac = ',' in mo.group(1) or '.' in mo.group(1)

    ev = from_name(name, cname)                       # 1. назва товару
    if ev is not None and lo <= ev <= hi:
        return round(ev), 'назва товару'
    u = inline or unit_in_field(field)                # 2. одиниця в значенні/полі
    if u and u in table:
        v = val * table[u]
        if lo <= v <= hi:
            return round(v), f'одиниця «{u}»'
    if has_frac and cunit == 'мм' and lo <= val * 10 <= hi:
        return round(val * 10), 'десяткова частина = см'
    if cunit in ('г', 'мл') and lo <= val <= hi:
        # Косметика фасується в мілілітрах, а не літрах; вага — у грамах.
        # «4» у полі обʼєму означає 4 мл, а не 4 літри.
        return round(val), f'за замовчуванням у {cunit}'
    cand = [(val * k, un) for un, k in table.items() if lo <= val * k <= hi]
    if len(cand) == 1:                                # 3. правдоподібність
        return round(cand[0][0]), f'правдоподібність ({cand[0][1]})'
    if len(cand) > 1:
        # Дефолт не з голови: у полях без суфікса медіана «Довжини» 18, а
        # «Діаметра» 3.7 — це сантиметри. Тож коли обидва прочитання формально
        # можливі, сантиметри є значно ймовірнішими. Виводимо окремим рядком,
        # щоб було видно, скільки значень трималось саме на цьому припущенні.
        if cunit == 'мм' and lo <= val * 10 <= hi:
            return round(val * 10), 'дефолт: поле без суфікса = см'
        return None, 'неоднозначно: ' + '/'.join(f'{un}' for _, un in cand)
    return None, f'поза межами правдоподібності ({val})'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', type=int, default=0)
    ap.add_argument('--write')
    a = ap.parse_args()

    tree = ET.parse(FEED); root = tree.getroot()
    how = collections.Counter(); shown = 0; unresolved = []
    for o in root.findall('.//offer'):
        ne = o.find('name_ua') if o.find('name_ua') is not None else o.find('name')
        name = (ne.text or '') if ne is not None else ''
        lines = []
        for p in o.findall('param'):
            f = p.get('name') or ''
            if not canon(f):
                continue
            before = f'{f}="{(p.text or "").strip()}"'
            val, why = convert(f, (p.text or '').strip(), name, p.get('unit'))
            if val is None:
                how[f'НЕ ЗМІНЕНО — {why.split("(")[0].split(":")[0].strip()}'] += 1
                unresolved.append((name, before, why))
                continue
            cname, cunit = canon(f)
            how[f'зведено — {why.split("(")[0].strip()}'] += 1
            lines.append((before, f'{cname} unit="{cunit}">{val}'))
            if a.write:
                p.set('name', cname); p.set('unit', cunit); p.text = str(val)
        if a.sample and lines and shown < a.sample:
            print(f'  {name[:78]}')
            for b, af in lines:
                print(f'      {b:34} → {af}')
            shown += 1

    print('\nПІДСУМОК:')
    for k, v in how.most_common():
        print(f'  {v:6}  {k}')
    if unresolved:
        print(f'\nНЕ ЗМІНЕНО, потребує розгляду — {len(unresolved)}; приклади:')
        for nm, b, why in unresolved[:10]:
            print(f'   {b:30} {why:34} ← {nm[:46]}')
    if a.write:
        tree.write(a.write, encoding='utf-8', xml_declaration=True)
        print(f'\nкопію збережено: {a.write}')


if __name__ == '__main__':
    main()
