#!/usr/bin/env python3
"""
tools/prom_card_audit.py
=========================
Перевірка карток Prom за машинним чек-лістом (консультація 02.09.2026).

ПОРЯДОК ПЕРЕВІРКИ НЕ ДОВІЛЬНИЙ:

    категорія → характеристики → назва й опис → пошукові ключі

Категорія задає набір доступних атрибутів; характеристики дають фактаж, з
якого будується назва; ключі закривають те, що **не влізло** в назву. Якщо
почати з назви, після дозаповнення характеристик її доведеться переписувати.
Це стосується і «чистих» карток, які просто доводять до ідеалу, — не лише
тих, де знайдено помилку.

Суб'єктивні пункти («емоційність опису») сюди не входять: скрипт їх не
оцінить. Лишились тільки машинозчитувані.

    python3 tools/prom_card_audit.py --category "Анальні пробки"
    python3 tools/prom_card_audit.py --category "Анальні пробки" --list 20
"""
import os, re, sys, argparse, collections
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'tools'))
import prom_kw_matrix as M

FEED = os.environ.get('PROM_FEED') or os.path.join(BASE, 'output', 'noire_prom.xml')
NAME_MIN, NAME_VISIBLE, NAME_MAX = 30, 70, 110
DESC_MIN, DESC_MAX = 300, 4000   # верхня межа — застереження проти SEO-спаму,
                                 # а не проти змістовного тексту: Prom індексує
                                 # перші 1000-1500 символів, жорсткий ліміт поля 50000
KW_MIN, KW_MAX, KW_FIELD_MAX = 6, 9, 1024
STOP = ('купити', 'ціна', 'оптом', 'київ', 'доставка', 'акція', 'безкоштовно',
        'знижка', 'дешево', 'замовити')
# Значення, які формально заповнені, а фактично порожні
JUNK_VALUES = {'0', '-', '—', 'null', 'undefined', 'н/а', 'n/a', 'немає', 'нет', ''}
BAD_CHARS = re.compile(r'[#@*<>\\|]|\s{2,}|!{2,}')


def txt(o, tag):
    e = o.find(tag)
    return (e.text or '').strip() if e is not None else ''


def check_name(name, vendor, names_seen, key_attrs, type_stem='', extra_types=()):
    bad = []
    n = len(name)
    if n < NAME_MIN:
        bad.append(f'назва коротка ({n})')
    if n > NAME_MAX:
        bad.append(f'назва довша за {NAME_MAX} ({n})')
    low = name.lower()
    for w in STOP:
        if w in low:
            bad.append(f'стоп-слово «{w}»')
    if BAD_CHARS.search(name):
        bad.append('спецсимволи або подвійні пробіли')
    if names_seen[low] > 1:
        bad.append('назва не унікальна у фіді')
    head = name[:NAME_VISIBLE].lower()
    if vendor and vendor.lower().split()[0] not in head:
        bad.append('бренду немає в перших 70 символах')
    # Виняток для довгих брендових позицій: якщо «Тип + Бренд + Модель» самі
    # займають понад 55 символів, вимагати ще й характеристику в перших 70 —
    # означає жертвувати назвою моделі або ключовим словом типу. Обидва
    # важливіші: модель дає точний клік, тип має найвищу вагу в пошуку.
    # Робот Prom однаково читає всі 110 символів, тож характеристика в хвості
    # індексується; 70 — це межа лише візуального зрізання в інтерфейсі.
    head_part = name.split(',')[0]
    if key_attrs and not any(a in head for a in key_attrs) and len(head_part) <= 55:
        bad.append('ключової характеристики немає в перших 70 символах')
    # Вимога «перше слово — іменник» хибна для складених типів: «Анальна
    # пробка» починається з прикметника, який є частиною самого типу. Тому
    # перевіряємо не частину мови, а те, що тип товару стоїть НА ПОЧАТКУ —
    # у межах перших трьох слів, до бренда й моделі.
    # Категорія зветься «Анальні пробки», але в ній законно є вібратори,
    # ланцюжки й стимулятори. Вимагати слово «пробка» в кожній назві —
    # помилка перевірки, а не даних. Тому приймаємо і корінь категорії, і
    # значення «Тип товару» самої картки.
    first3 = ' '.join(name.split()[:3]).lower()
    stems = [t for t in ([type_stem] + list(extra_types or [])) if t]
    if stems and not any(t in first3 for t in stems):
        bad.append(f'тип товару «{stems[0]}» не стоїть на початку назви')
    w0 = re.sub(r'[^\w\-]', '', name.split()[0]).lower() if name.split() else ''
    if w0 in M.FLUFF:
        bad.append(f'назва починається з епітета «{w0}»')
    return bad


NUMERIC = re.compile(r'довжин|діаметр|вага|об.?єм|ширин|висот|глибин', re.I)
UNIT_IN_NAME = re.compile(r'[(,]\s*(мм|см|м|г|кг|мл|л)\)?\s*$')
PURE_NUM = re.compile(r'^[0-9]+([.,][0-9]+)?$')
# Очікувані межі, щоб зловити значення, подане не в тій одиниці, яку заявляє
# поле. Доказ беремо з самої назви товару: «діаметр 3,8 см» при значенні 38
# означає, що в поле сантиметрів записали міліметри.
# Межі правдоподібності В КАНОНІЧНІЙ ОДИНИЦІ (мм, г, мл). До нормалізації
# тут стояли межі в сантиметрах — після кроку 1 вони давали 430 хибних
# зауважень на цілком коректні значення. Перевірка мусить іти за атрибутом
# unit=, а не за здогадкою про масштаб поля.
SCALE = {'Довжина': (20, 3000), 'Діаметр': (5, 250), 'Ширина': (5, 700),
         'Висота': (5, 700), 'Вага': (1, 20000), 'Обʼєм': (1, 5000)}
CANON_UNIT = {'Довжина': 'мм', 'Діаметр': 'мм', 'Ширина': 'мм',
              'Висота': 'мм', 'Вага': 'г', 'Обʼєм': 'мл'}


def check_units(prm, elems):
    """Числове значення має бути чистим числом, а одиниця — в атрибуті unit=
    або в назві поля. Літери всередині значення роблять поле текстовим, і
    товар випадає з фільтра-повзунка (напр. «довжина від 50 до 150 мм»)."""
    bad = []
    for k, v in prm.items():
        if not NUMERIC.search(k):
            continue
        v = (v or '').strip()
        if v and not PURE_NUM.match(v):
            bad.append(f'одиниця всередині значення «{k}={v}»')
        if not UNIT_IN_NAME.search(k) and not elems.get(k):
            bad.append(f'одиниці виміру немає ні в назві поля, ні в unit= «{k}»')
        want = CANON_UNIT.get(k)
        if want and elems.get(k) and elems[k] != want:
            bad.append(f'«{k}» має одиницю «{elems[k]}», очікується «{want}»')
        lo, hi = SCALE.get(k, (None, None))
        if lo is not None and PURE_NUM.match(v or ''):
            f = float(v.replace(',', '.'))
            if not (lo <= f <= hi):
                bad.append(f'«{k}={v}» поза правдоподібним діапазоном')
    return bad


def check_params(prm, name, common):
    bad = []
    missing = [k for k in common if k not in prm]
    if missing:
        bad.append('немає характеристик: ' + ', '.join(missing[:4]))
    for k, v in prm.items():
        if (v or '').strip().lower() in JUNK_VALUES:
            bad.append(f'порожнє значення «{k}»')
    mat = (prm.get('Матеріал') or '').lower()
    low = name.lower()
    for m1, m2 in (('метал', 'силікон'), ('силікон', 'метал'), ('скло', 'силікон')):
        if m1 in low and m2 in mat and m1 not in mat:
            bad.append(f'назва каже «{m1}», характеристика — «{m2}»')
            break
    return bad


def check_desc(desc_html, name, vendor, cyr):
    bad = []
    plain = re.sub(r'<[^>]+>', ' ', desc_html)
    plain = re.sub(r'\s+', ' ', plain).strip()
    n = len(plain)
    if n < DESC_MIN:
        bad.append(f'опис короткий ({n})')
    elif n > DESC_MAX:
        bad.append(f'опис довгий ({n})')
    if '<li' not in desc_html and '<ul' not in desc_html:
        bad.append('немає маркованого списку')
    head = plain[:300].lower()
    if vendor and vendor.lower().split()[0] not in head:
        bad.append('бренду немає в перших 300 символах опису')
    if cyr and cyr.lower() not in plain.lower():
        bad.append(f'немає кириличного бренду «{cyr}»')
    return bad


def check_kw(phrases):
    bad = []
    if len(phrases) < KW_MIN:
        bad.append(f'ключів мало ({len(phrases)})')
    if len(phrases) > KW_MAX:
        bad.append(f'ключів забагато ({len(phrases)})')
    if len(', '.join(phrases)) > KW_FIELD_MAX:
        bad.append('поле ключів перевищує ліміт')
    for p in phrases:
        w = len(p.split())
        if not (2 <= w <= 4) and phrases.index(p) > 1:
            bad.append(f'фраза «{p}» має {w} слів')
    stems = [M.stem_set(p) for p in phrases]
    for i, a in enumerate(stems):
        for b in stems[i + 1:]:
            if a == b:
                bad.append('є фрази-клони')
                break
        else:
            continue
        break
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--category', required=True)
    ap.add_argument('--list', type=int, default=0)
    a = ap.parse_args()

    root = ET.parse(FEED).getroot()
    cats = {c.get('id'): (c.text or '') for c in root.findall('.//category')}
    offers = root.findall('.//offer')
    names_seen = collections.Counter(txt(o, 'name_ua').lower() for o in offers)

    rows = [o for o in offers if cats.get(txt(o, 'categoryId'), '').strip() == a.category.strip()]
    if not rows:
        print(f'категорії «{a.category}» у фіді немає'); return
    # «обов'язкові» атрибути виводимо емпірично: ті, що є у 80 % карток категорії
    freq = collections.Counter()
    for o in rows:
        for p in o.findall('param'):
            freq[p.get('name')] += 1
    common = [k for k, v in freq.items() if v >= 0.8 * len(rows)]
    # «ключова характеристика в назві» означає її ЗНАЧЕННЯ («силікон», «чорна»,
    # «5 см»), а не заголовок поля. Перша версія шукала слово «матеріал» — і
    # закономірно не знаходила його в жодній назві.

    # головне слово категорії — корінь, який має бути на початку назви
    cw = [w for w in re.findall(r'[а-яіїєґ]{4,}', a.category.lower())]
    type_stem = cw[-1][:5] if cw else ''
    print(f'категорія: {a.category} — {len(rows)} товарів')
    print(f'обовʼязкові за фактом (≥80 %): {", ".join(common)}\n')

    tally = collections.Counter()
    perfect = 0
    problems = []
    for o in rows:
        name = txt(o, 'name_ua'); vendor = M.real_vendor(txt(o, 'vendor'))
        cyr = M.brand_cyr(vendor, 'ua')
        prm = {p.get('name'): (p.text or '') for p in o.findall('param')}
        desc_html = txt(o, 'description_ua')
        kw = M.build(name, txt(o, 'vendor'), a.category, prm,
                     re.sub(r'<[^>]+>', ' ', desc_html))
        vals = [v.split('|')[0].strip().lower()[:6]
                for k, v in prm.items()
                if k in ('Матеріал', 'Колір', 'Форма', 'Тип товару') and v.strip()]
        # Після нормалізації параметр у міліметрах (44), а назва пише
        # сантиметри («діаметр 4,4 см»). Порівнювати треба обидві форми,
        # інакше перевірка звинувачує в браку того, що насправді є.
        for k in ('Діаметр', 'Довжина'):
            raw = (prm.get(k) or '').replace(',', '.')
            if not raw.replace('.', '').isdigit():
                continue
            mm = int(float(raw))
            vals.append(str(mm))
            cm = f'{mm / 10:g}'
            vals += [cm, cm.replace('.', ',')]
        issues = ([f'НАЗВА: {x}' for x in check_name(
                      name, vendor, names_seen, vals, type_stem,
                      [w[:5] for w in re.findall(r'[а-яіїєґ]{4,}', ' '.join(
                          # Поле з типом зветься по-різному: у БДСМ це «Тип
                          # інтимної іграшки», у вібраторах «Тип приладу»,
                          # деінде «Тип товару». Перевірка лише по одному
                          # імені дала 726 хибних зауважень у БДСМ.
                          (prm.get(k) or '') for k in
                          ('Тип товару', 'Тип інтимної іграшки',
                           'Тип приладу', 'Вид', 'Тип')).lower())])]
                  + [f'ХАРАКТ: {x}' for x in check_params(prm, name, common)]
                  + [f'ОДИНИЦІ: {x}' for x in check_units(
                      prm, {p.get('name'): p.get('unit') for p in o.findall('param')})]
                  + [f'ОПИС: {x}' for x in check_desc(desc_html, name, vendor, cyr)]
                  + [f'КЛЮЧІ: {x}' for x in check_kw(kw)])
        for i in issues:
            tally[i.split(':')[0] + ': ' + re.sub(r'\s*\(\d+\)|«[^»]*»', '…', i.split(': ', 1)[1])] += 1
        if not issues:
            perfect += 1
        else:
            problems.append((len(issues), name, issues))

    print(f'без жодного зауваження: {perfect} із {len(rows)}\n')
    print('НАЙЧАСТІШІ ЗАУВАЖЕННЯ:')
    for k, v in tally.most_common(20):
        print(f'  {v:5}  {k}')
    if a.list:
        print(f'\nНАЙПРОБЛЕМНІШІ {a.list} КАРТОК:')
        for cnt, name, issues in sorted(problems, reverse=True)[:a.list]:
            print(f'\n  [{cnt}] {name[:80]}')
            for i in issues:
                print(f'      · {i}')


if __name__ == '__main__':
    main()
