#!/usr/bin/env python3
"""
tools/prom_content_fix.py
==========================
Кроки 3–4: назви, описи, пошукові ключі. Працює на копії фіду.

НАЗВА
  * тип товару виносимо на початок — він має бути раніше за бренд і модель;
  * ключову характеристику (діаметр, матеріал) вставляємо в перші 70 символів,
    але **лише якщо загальна довжина лишається ≤110**. Назва понад ліміт гірша
    за назву без характеристики.

ОПИС
  * кириличний бренд додаємо в перший абзац. Prom **не склеює** `rocks off` і
    `рокс оф` — це різні запити, а кирилицею шукають 30–40 % користувачів.
    Місце саме тут, а не в назві: перші 70 символів назви працюють на CTR, і
    транслітерація там зрізала б корисні слова;
  * блок <ul><li> з параметрами — Prom краще індексує структурований HTML;
  * **не ріжемо** довгі описи. Верхня межа 2000 у чек-лістах є застереженням
    проти SEO-спаму, а не проти змістовного тексту: жорсткий ліміт поля Prom
    50 000 символів, а текст на 2100–3400 цілком безпечний і підвищує конверсію.

    python3 tools/prom_content_fix.py --plan
    python3 tools/prom_content_fix.py --write output/noire_prom_step4.xml
"""
import os, re, sys, argparse, collections
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, 'tools'))
os.environ.setdefault('PROM_FEED', os.path.join(BASE, 'output', 'noire_prom_step2.xml'))
import prom_kw_matrix as M

SRC = os.environ.get('STEP_SRC') or os.path.join(BASE, 'output', 'noire_prom_step2.xml')
# Категорії, які проходять постобробку. Розширюється в міру того, як кожна
# наступна проходить аудит і перевірку очима: додавати всі одразу означало б
# застосувати неперевірені правила до всього каталогу.
CATEGORIES = [c.strip() for c in os.environ.get(
    'PROM_CATEGORIES', 'ALL').split(',') if c.strip()]

# Правки НАЗВ вмикаються окремо і лише для категорій, які вже переглянуті.
# Причина в ціні помилки: опис і ключі можна перегенерувати наступного разу,
# а назва — це те, що покупець бачить у видачі, і масова зміна 3000 назв
# одним рухом без перевірки кожної категорії надто ризикована.
NAME_CATEGORIES = [c.strip() for c in os.environ.get(
    'PROM_NAME_CATEGORIES', 'ALL').split(',') if c.strip()]
NAME_MAX, NAME_VISIBLE = 110, 70
UNIT_LABEL = {'мм': 'мм', 'г': 'г', 'мл': 'мл'}


def txt(o, tag):
    e = o.find(tag)
    return (e.text or '').strip() if e is not None else ''


def type_first(name, type_stem):
    """Тип товару має відкривати назву. «Силіконова анальна пробка Nexus» уже
    коректна; «Nexus ACE анальна пробка» — ні."""
    words = name.split()
    idx = next((i for i, w in enumerate(words) if type_stem in w.lower()), -1)
    if idx <= 0 or idx > 4:
        return name, False
    # тип уже в перших словах, але перед ним стоїть бренд/модель латиницею
    if not re.match(r'^[A-Za-z]', words[0]):
        return name, False
    head = words[idx - 1:] if idx and not re.match(r'^[A-Za-z]', words[idx - 1]) else words[idx:]
    tail = [w for w in words if w not in head]
    return ' '.join(head + tail), True


# Канонічний тип товару для кожної категорії — те слово, яке має стояти
# першим у назві. Виведено з назв категорій фіду, а не вигадано.
# Аксесуар до товару категорії — не той самий товар. «Кільце Bathmate
# комфорту» лежить у «Вакуумних помпах», але це деталь до помпи, і префікс
# «Вакуумна помпа кільце…» зробив би картку хибно релевантною.
ACCESSORY_HEAD = {
    'кільце', 'кільця', 'насадка', 'насадки', 'набір', 'чохол', 'чохли',
    'вставка', 'вставки', 'ремкомплект', 'аксесуар', 'аксесуари', 'змінна',
    'запасна', 'адаптер', 'перехідник', 'кріплення', 'подовжувач', 'помпа-',
    'гель', 'змазка', 'очищувач', 'сумка', 'кейс', 'батарейка', 'зарядка',
    'пробник', 'пробники', 'майданчик', 'подушка', 'вкладиш',
}
CANON_TYPE = {
    'Вібратори': 'Вібратор', 'Фалоімітатори': 'Фалоімітатор',
    'Мастурбатори': 'Мастурбатор', 'Анальні пробки': 'Анальна пробка',
    'Вакуумні стимулятори': 'Вакуумний стимулятор', 'Страпони': 'Страпон',
    'Вакуумні помпи': 'Вакуумна помпа', 'Масажери простати': 'Масажер простати',
    'Вагінальні кульки': 'Вагінальні кульки', 'Секс-машини': 'Секс-машина',
    'Презервативи': 'Презерватив', 'Лубриканти': 'Лубрикант',
    'Збуджуючі засоби': 'Збуджувальний засіб', 'Менструальні чаші': 'Менструальна чаша',
    'Тренажери кегеля': 'Тренажер Кегеля', 'Секс-ляльки': 'Секс-лялька',
}


def smart_prefix(name, canon):
    """Ставить канонічний тип першим словом, зберігаючи фірмову назву.

    Постачальник називає товар так, як його знають покупці: «Містер
    Fleshlight В'ялий Тілесний Large» — і слова «мастурбатор» там немає
    жодного разу. Для внутрішнього пошуку Prom тип у назві має найвищу вагу,
    тож без нього картка випадає з категорійних запитів. Але переписати
    назву на сухе «Мастурбатор Fleshlight Large» означає втратити впізнаване
    ім'я, за яким товар і шукають.

    Тому тип **додається префіксом**, а оригінальна назва лишається цілою.
    Якщо результат не влазить у 110 символів — не чіпаємо: обрізана назва
    гірша за назву без типу.
    """
    if not canon:
        return name, False
    low = name.lower()
    # Корінь у чотири літери, а не шість: «Віброкуля» вже містить «вібр», і
    # префікс дав би «Вібратор віброкуля» — надлишок, який не додає нічого
    # для пошуку, але псує назву. Дивимось перші пʼять слів, бо тип може
    # стояти після означення: «Силіконовий анальний плаг».
    words = low.split()
    if not words:
        return name, False
    first = words[0].strip('.,«»"')
    if first in ACCESSORY_HEAD:
        return name, False                    # це аксесуар, а не сам товар
    # Префікс приклеюється лише до іменника. «Пом'якшувальний майданчик» дав
    # би «Вакуумна помпа пом'якшувальний майданчик» — фраза, якої не існує.
    # Коли назва починається з означення, тип уже неможливо вставити
    # граматично коректно автоматично: лишаємо як є.
    if M._is_adj(first):
        return name, False
    # Постачальник пише і «віброяйце», і «виброяйце» — звіряємо нормалізовано.
    def _n(x):
        return x.replace('и', 'і').replace('ы', 'і').replace('е', 'е')
    # Звіряємо КОЖНЕ слово типу, не лише перше: «Вакуумна помпа» проти
    # «Гідропомпа» — збігається другим словом, і префікс дав би
    # «Вакуумна помпа гідропомпа».
    head_zone = _n(' '.join(words[:5]))
    if any(_n(w.lower())[:4] in head_zone
           for w in canon.split() if len(w) > 4):
        return name, False                    # тип (або його корінь) уже є
    new = f'{canon} {name[0].lower() + name[1:]}' if name else name
    if len(new) > NAME_MAX:
        return name, False
    return new, True


def pull_key_clause(name):
    """Переставляє клаузу з діаметром одразу після головної частини назви.

    Назви тут змістовні: за 70-м символом стоїть корисна деталь, а не
    маркетинг, тому різати їх не можна — обрізана назва втрачає інформацію,
    а хвіст усе одно індексується. Але покупець бачить лише перші 70
    символів, тож найважливіше — діаметр — має потрапити туди. Довжина при
    перестановці не змінюється.
    """
    # Кома в «діаметр 2,6 см» — десятковий роздільник, а не межа клаузи.
    # Наївний split(',') розривав саме ту клаузу, яку ми переставляємо.
    parts = [x.strip() for x in re.split(r',(?!\s*\d)', name)]
    if len(parts) < 3:
        return name, False
    idx = next((i for i, x in enumerate(parts)
                if i and re.search(r'діаметр', x, re.I)), -1)
    if idx <= 1:
        return name, False
    parts.insert(1, parts.pop(idx))
    out = ', '.join(parts)
    return (out, True) if out != name else (name, False)


def key_attr_phrase(prm):
    d = prm.get('Діаметр')
    if d and d.isdigit():
        v = int(d) / 10
        return f'діаметр {v:g} см'.replace('.', ',')  # укр. десятковий роздільник
    mat = (prm.get('Матеріал') or '').split('|')[0].strip().lower()
    return mat or ''


def add_cyr_brand(html, vendor, cyr):
    """Кирилицю ставимо поруч із першою згадкою бренду латиницею."""
    if not cyr or cyr.lower() in html.lower():
        return html, False
    mo = re.search(re.escape(vendor), html, re.I)
    if mo:
        return html[:mo.end()] + f' ({cyr})' + html[mo.end():], True
    return f'<p>Бренд {vendor} ({cyr}).</p>' + html, True


def add_list(html, prm):
    if '<li' in html or '<ul' in html:
        return html, False
    order = ['Тип товару', 'Форма', 'Матеріал', 'Діаметр', 'Довжина', 'Вага',
             'Колір', 'Водонепроникний', 'Країна-виробник']
    items = []
    for k in order:
        v = (prm.get(k) or '').strip()
        if not v:
            continue
        if k in ('Діаметр', 'Довжина') and v.isdigit():
            v = f'{int(v)/10:g} см'.replace('.', ',')
        elif k == 'Вага' and v.isdigit():
            v = f'{v} г'
        items.append(f'<li><b>{k}:</b> {v}</li>')
    # Менше трьох пунктів — списку не робимо: два рядки виглядають бідніше за
    # текст і створюють відчуття недописаної картки. Але й у суцільному абзаці
    # технічні деталі погано зчитуються і роботом, і оком. Тому для 1–2 фактів
    # використовуємо абзаци з жирним початком (inline-bolding).
    if not items:
        return html, False
    if len(items) < 3:
        plain = ''.join(f'<p>{re.sub(r"</?li>", "", it)}</p>' for it in items)
        return html + plain, True
    return html + '<ul>' + ''.join(items) + '</ul>', True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--write')
    a = ap.parse_args()

    tree = ET.parse(SRC); root = tree.getroot()
    cats = {c.get('id'): (c.text or '') for c in root.findall('.//category')}
    rows = [o for o in root.findall('.//offer')
            if 'ALL' in CATEGORIES
            or cats.get(txt(o, 'categoryId'), '').strip() in {c.strip() for c in CATEGORIES}]
    cw = re.findall(r'[а-яіїєґ]{4,}', ' '.join(CATEGORIES).lower())
    type_stem = cw[-1][:5] if cw else ''

    did = collections.Counter(); skip = collections.Counter(); shown = []
    # Дублікат назви Prom або зливає, або песимізує. Дописування характеристики
    # може випадково зробити дві назви однаковими — тримаємо зайняті назви й
    # відкочуємо правку, якщо вона створює збіг.
    taken = collections.Counter(txt(o, 'name_ua').strip().lower() for o in rows)
    for o in rows:
        name = txt(o, 'name_ua'); vendor = M.real_vendor(txt(o, 'vendor'))
        cat_now = cats.get(txt(o, 'categoryId'), '').strip()
        may_rename = ('ALL' in NAME_CATEGORIES
                      or cat_now in {c.strip() for c in NAME_CATEGORIES})
        cyr = M.brand_cyr(vendor, 'ua')
        prm = {p.get('name'): (p.text or '').strip() for p in o.findall('param')}
        before = name

        new, moved = (type_first(name, type_stem) if may_rename else (name, False))
        if moved:
            name = new; did['тип товару винесено на початок'] += 1
        if may_rename:
            new, pref = smart_prefix(name, CANON_TYPE.get(cat_now))
            if pref:
                name = new; did['канонічний тип додано префіксом'] += 1
            elif CANON_TYPE.get(cat_now) and len(name) > NAME_MAX - 12:
                skip['назва задовга для префікса типу'] += 1
        if may_rename and len(name) > NAME_VISIBLE:
            new, pulled = pull_key_clause(name)
            if pulled:
                name = new; did['діаметр переставлено в перші 70 символів'] += 1

        # Характеристику ДОПИСУЄМО В КІНЕЦЬ, а не вставляємо всередину: спроба
        # втиснути її в перші 70 символів рвала фрази — «з ерекційним,
        # діаметр 5,5 см кільцем». І перевіряємо всю назву, а не перші 70:
        # якщо діаметр уже є після 70-го символу, дописувати його вдруге
        # означає зіпсувати назву, а не покращити.
        ph = key_attr_phrase(prm) if may_rename else ''
        low = name.lower()
        has = bool(ph) and (ph.split()[0][:6] in low or ph.split()[-2:][0] in low)
        if ph and not has and len(name) + len(ph) + 2 <= NAME_MAX:
            name = f'{name}, {ph}'
            did['ключову характеристику дописано в назву'] += 1
        elif ph and not has:
            skip['назва вже задовга для характеристики'] += 1
        elif ph and ph.split()[0][:6] not in name[:NAME_VISIBLE].lower():
            skip['характеристика є, але після 70-го символу — треба скорочувати'] += 1

        if name != before:
            if taken.get(name.strip().lower()):
                skip['правка назви створила б дублікат — відкочено'] += 1
                name = before
            else:
                taken[name.strip().lower()] += 1
                taken[before.strip().lower()] -= 1
        if name != before:
            if a.write:
                o.find('name_ua').text = name
            if len(shown) < 6:
                shown.append(f'  БУЛО : {before[:96]}\n  СТАЛО: {name[:96]}')

        de = o.find('description_ua')
        if de is not None:
            html = de.text or ''
            plain = re.sub(r'<[^>]+>', ' ', html)
            if vendor and vendor.lower() not in plain[:300].lower():
                # бренд стоїть десь глибоко в тексті — виносимо на початок
                html = (f'<p><b>{name.split(",")[0]}</b> від бренду {vendor}'
                        + (f' ({cyr})' if cyr else '') + '.</p>' + html)
                did['бренд винесено в перший абзац опису'] += 1
            html, c1 = add_cyr_brand(html, vendor, cyr)
            if c1:
                did['кириличний бренд додано в опис'] += 1
            html, c2 = add_list(html, prm)
            if c2:
                did['список <ul><li> додано'] += 1
            if a.write and (c1 or c2):
                de.text = html

        kw = M.build(name, txt(o, 'vendor'), cats.get(txt(o, 'categoryId'), ''), prm,
                     re.sub(r'<[^>]+>', ' ', txt(o, 'description_ua')))
        did[f'ключів: {len(kw)}'] += 0
        if len(kw) < 6:
            skip[f'ключів усе ще мало ({len(kw)})'] += 1
        if a.write:
            ke = o.find('keywords_ua')
            if ke is None:
                ke = ET.SubElement(o, 'keywords_ua')
            ke.text = ', '.join(kw)

    print(f'категорії {CATEGORIES}: {len(rows)} товарів\n')
    for k, v in did.most_common():
        if v:
            print(f'  {v:5}  {k}')
    if skip:
        print('\nне вдалось:')
        for k, v in skip.most_common(6):
            print(f'  {v:5}  {k}')
    if shown:
        print('\nПРИКЛАДИ НАЗВ:')
        for x in shown:
            print(x)
    if a.write:
        tree.write(a.write, encoding='utf-8', xml_declaration=True)
        print(f'\nкопію збережено: {a.write}')


if __name__ == '__main__':
    main()
