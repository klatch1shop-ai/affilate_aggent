#!/usr/bin/env python3
"""
NOIRE / SexOpt → XML прайс-лист для Prom.ua
============================================
Формат YML за офіційним описом support.prom.ua/hc/uk/articles/360004963538.

Чим відрізняється від Єпіцентру та Rozetka — і чому саме так:

  • Категорія береться через ДВА шари: sexopt → epicentr (готовий, двічі
    аудитований мапінг) → prom. Це 33 відповідності замість 170+.
  • Без type="vendor.model". У фіді Віктора цей атрибут стоїть без
    <typePrefix>, і Prom ігнорує готову назву, склеюючи власну з vendor+model:
    «Шланг системи охолодження Polestar 2 2023» перетворюється на
    «Polestar 32257944». Пишемо <name> напряму.
  • selling_type — АТРИБУТ офера зі значенням r/w/u/s, а не дочірній тег.
    У Віктора він дочірній зі значенням "retail", тобто мовчки ігнорується.
  • Ціна — gross-up ÷(1−комісія), а не mark-up ×(1+комісія) як у Toptul-коді.
    Різниця на 18.88% — 3.7% недобору з кожного продажу.
  • Розміри білизни та інших виробів обʼєднуються в різновиди через group_id:
    три розміри одного товару — одна позиція, а не три.
  • Фото максимум 10 (у Rozetka 15), опис обовʼязковий і лише в CDATA.
  • name_ua і description_ua заповнюються ЗАВЖДИ парою: без опису українською
    українська назва не застосується, і навпаки.

Запуск:
    python3 tools/noire_prom_generator.py -o output/noire_prom.xml
    python3 tools/noire_prom_generator.py --limit 50
"""
import argparse
import collections
import hashlib
import html
import math
import os
import re
import sys
from datetime import datetime

import psycopg2
import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

OUT = os.path.join(BASE_DIR, 'output', 'noire_prom.xml')

SHOP_NAME = 'klatch1 shop'
SHOP_COMPANY = '3721108'
SHOP_URL = 'https://cs4053918.prom.ua/'

MARKUP = float(os.getenv('NOIRE_MARKUP_PROM', '1.10'))
DEFAULT_COMMISSION = float(os.getenv('NOIRE_PROM_COMMISSION', '18.88'))

MAX_PICTURES = 10        # офіційний ліміт Prom (у Rozetka 15)
MAX_NAME = 110           # правила оформлення карток
MAX_PARAMS = 100
MAX_ARTICLE = 25
MIN_PARAMS = 2           # Prom радить «мінімум 2-3 основні характеристики»

# Порогів «відкритого словника», як у Rozetka, тут немає: найбільший список
# Prom — 33 значення (Тип інтимної іграшки), тобто всі вони закриті переліки.
# Значення поза списком у фільтри не потрапить, тому звіряємо суворо.


def esc(t) -> str:
    return html.escape(str(t) if t is not None else '', quote=True)


def cdata(t: str) -> str:
    """Опис може містити HTML — тоді він обовʼязково в CDATA (вимога Prom)."""
    return '<![CDATA[' + (t or '').replace(']]>', ']]&gt;') + ']]>'


def calc_price(retail: float, commission: float) -> int:
    """Ціна продажу з gross-up на комісію.

    Свідомо НЕ повторюємо формулу Toptul-коду ×(1+cpa): при 18.88% вона
    лишає на руки 96.4% закупівлі замість 100%. Тут ділимо на (1−cpa),
    щоб після утримання комісії лишалась рівно роздрібна ціна SexOpt,
    помножена на нашу націнку.
    """
    price = math.ceil(retail * MARKUP / (1 - commission / 100))
    return max(price, math.ceil(retail * MARKUP))


# ── Наші назви характеристик → назви з довідника Prom ───────────────────────
# Збігаються лише «Матеріал», «Колір», «Розмір», «Призначення». Решту треба
# перекладати, інакше характеристика не потрапить у фільтри каталогу.
PARAM_ALIAS = {
    'Тип товару': ('Тип вібратора', 'Тип інтимної іграшки', 'Вид'),
    'Вид': ('Тип вібратора', 'Тип інтимної іграшки', 'Вид'),
    'Тип приладу': ('Тип вібратора', 'Тип інтимної іграшки'),
    'Тип живлення': ('Живлення',),
    'Живлення': ('Живлення',),
    'Для кого': ('Для кого', 'Стать'),
    'Стать': ('Стать', 'Для кого'),
    'Кількість режимів': ('Кількість режимів вібрації',),
    'Кількість режимів вібрації': ('Кількість режимів вібрації',),
    'Форма': ('Форма',),
    'Конструкція': ('Форма', 'Особливості'),
    'Основа засобу': ('Основа',),
    'Аромат': ('Аромат',),
    'Обʼєм': ("Об'єм",),
    "Об'єм": ("Об'єм",),
}

# Булеві характеристики → значення multiselect «Особливості»
FEATURE_MAP = {
    'Водонепроникний': 'Водонепроникні',
    'Підігрів': 'З підігрівом',
    'На присосці': 'На присосках',
    'Безшумний': 'Безшумні',
}

# Наші значення → значення довідника Prom (коли формулювання різне)
VALUE_ALIAS = {
    'силікон': 'Силікон', 'медичний силікон': 'Медичний силікон',
    'латекс': 'Латекс', 'метал': 'Метал', 'скло': 'Скло', 'гума': 'Гума',
    'пвх': 'ПВХ', 'пластик': 'Пластик', 'абс-пластик': 'ABS-пластик',
    'тпе': 'ТПЕ (термопластичний еластомер)',
    'кібершкіра': 'Кібершкіра', 'нержавіюча сталь': 'Нержавіюча сталь',
    'акумулятор': 'Акумулятор', 'батарейки': 'Батарейки', 'мережа': 'Мережа',
    'унісекс': 'Унісекс', 'для жінок': 'Для жінок',
    'для чоловіків': 'Для чоловіків', 'для пар': 'Для пар',
}

# Розмірні позначки, за якими товар визнається різновидом того самого виробу
SIZE_TOKEN = re.compile(
    r'\b(?:XS|S|M|L|XL|XXL|2XL|3XL|XXXL)\s*/\s*(?:S|M|L|XL|XXL|2XL|3XL|XXXL)\b'
    r'|\b(?:XS|S|M|L|XL|XXL|2XL|3XL|XXXL)\b|\bone\s?size\b|\bT[1-4]\b'
    r'|\b[1-4]/[2-4]\b', re.I)


def variant_key(vendor: str, name: str) -> str:
    """Ключ різновиду: назва без розмірної позначки."""
    return re.sub(r'\s+', ' ', SIZE_TOKEN.sub(' ', name or '')).strip(' ,.-').lower()


# Кольори, якими розрізняються різновиди, коли розміру в назві немає
COLOR_TOKEN = [
    (r'\bчорн\w*|\bblack\b', 'Чорний'), (r'\bбіл\w*|\bwhite\b', 'Білий'),
    (r'\bчервон\w*|\bred\b', 'Червоний'), (r'\bрожев\w*|\bpink\b', 'Рожевий'),
    (r'\bсин\w*|\bblue\b', 'Синій'), (r'\bзелен\w*|\bgreen\b', 'Зелений'),
    (r'\bфіолетов\w*|\bpurple\b|\bviolet\b', 'Фіолетовий'),
    (r'\bзолот\w*|\bgold\b', 'Золотистий'), (r'\bсрібн\w*|\bsilver\b', 'Сріблястий'),
    (r'\bбежев\w*|\bbeige\b', 'Бежевий'), (r'\bпрозор\w*|\btransparent\b', 'Прозорий'),
]


def variant_mark(name: str) -> tuple:
    """Чим саме цей різновид відрізняється від інших у групі.

    Prom відхиляє різновид, у якого немає жодного значення, відмінного від
    решти групи: «Різновид не буде імпортований». Артикул не рахується.
    А в наших даних відмінність — розмір або колір — живе ЛИШЕ в назві:
    у 134 зі 135 груп набори характеристик виявились ідентичними.
    Тому витягуємо ознаку з назви й віддаємо окремим <param>.

    «Розміру» немає в довідниках цих категорій, тож він стане
    користувацькою характеристикою: у фільтри каталогу не піде, зате
    зробить різновид валідним, а покупцеві буде видно на картці.
    """
    m = SIZE_TOKEN.search(name or '')
    if m:
        return 'Розмір', re.sub(r'\s*/\s*', '/', m.group(0)).upper()
    for rx, val in COLOR_TOKEN:
        if re.search(rx, name or '', re.I):
            return 'Колір', val
    return None, None


def stable_group_id(key) -> int:
    """Незмінний номер групи різновидів у діапазоні Prom (1..999999999)."""
    digest = hashlib.sha1(repr(key).encode('utf-8')).hexdigest()
    return int(digest[:12], 16) % 999_999_000 + 1


def load_mapping(cur) -> dict:
    """epicentr_code → [(prom_id, name_rule, excluded)], правила спершу."""
    cur.execute("""SELECT epicentr_code, prom_category_id, name_rule, excluded
                   FROM prom_category_mapping WHERE source='noire'
                   ORDER BY (name_rule IS NULL), id""")
    out = collections.defaultdict(list)
    for r in cur.fetchall():
        out[r['epicentr_code']].append(
            (r['prom_category_id'], r['name_rule'], r['excluded']))
    return out


def resolve_category(mapping: dict, ec: str, name: str):
    """Категорія Prom за кодом Єпіцентру, з урахуванням правил по назві."""
    for pid, rule, excluded in mapping.get(ec, []):
        if rule and not re.search(rule, name, re.I):
            continue
        return pid, excluded
    return None, False


def load_rates(cur) -> dict:
    cur.execute("""SELECT category_id, cpa_rate FROM prom_cpa_rates
                   WHERE source='noire'""")
    return {r['category_id']: float(r['cpa_rate']) for r in cur.fetchall()}


def load_attributes(cur) -> dict:
    """prom_id → {назва: (тип, одиниця, {значення_lower: значення})}"""
    cur.execute("""SELECT prom_category_id, attr_name, attr_type,
                          measure_unit, allowed_values
                   FROM prom_category_attributes""")
    out = collections.defaultdict(dict)
    for r in cur.fetchall():
        vals = {str(v).strip().lower(): str(v).strip()
                for v in (r['allowed_values'] or [])}
        out[r['prom_category_id']][r['attr_name']] = (
            r['attr_type'], r['measure_unit'], vals)
    return out


def load_categories(cur) -> dict:
    cur.execute('SELECT category_id, name FROM prom_categories')
    return {str(r['category_id']): r['name'] for r in cur.fetchall()}


def _number(value: str):
    m = re.search(r'(\d+(?:[.,]\d+)?)', str(value))
    return float(m.group(1).replace(',', '.')) if m else None


def fit_params(raw: dict, pid: str, attrs: dict) -> dict:
    """Наші характеристики → характеристики довідника Prom.

    Все, чого немає в довіднику категорії, відкидаємо: такі значення
    показуються лише на картці й не працюють у фільтрах каталогу, а
    фільтри — головна причина, чому характеристики взагалі заповнюють.
    """
    spec = attrs.get(pid, {})
    if not spec:
        return {}
    out, features = {}, []

    for name, value in raw.items():
        v = str(value).strip()
        if not v:
            continue

        if name in FEATURE_MAP and v.lower() in ('так', 'yes', 'true'):
            features.append(FEATURE_MAP[name])
            continue

        targets = PARAM_ALIAS.get(name, (name,))
        hit = next((t for t in targets if t in spec), None)
        if not hit:
            continue
        atype, unit, allowed = spec[hit]

        if atype in ('real', 'int'):
            num = _number(v)
            if num is None:
                continue
            # У довіднику одиниця своя: наша «Довжина (мм)» у категорії
            # вібраторів має бути в см, у БДСМ — у мм.
            if unit == 'см' and 'мм' in name:
                num /= 10
            elif unit == 'мм' and 'см' in name:
                num *= 10
            out[hit] = f'{num:g}'
        elif allowed:
            key = VALUE_ALIAS.get(v.lower(), v).lower()
            if key in allowed:
                out[hit] = allowed[key]
        else:
            out[hit] = v[:500]

    if features and 'Особливості' in spec:
        _, _, allowed = spec['Особливості']
        ok = [f for f in features if f.lower() in allowed]
        if ok:
            out['Особливості'] = ' | '.join(sorted(set(ok)))
    return out


def load_products(cur):
    cur.execute("""
        SELECT p.sku, p.name, p.description_html, p.price_retail, p.vendor,
               p.pictures, p.country, p.quantity, p.available,
               m.epicentr_category_code AS ec
        FROM sexopt_products p
        JOIN epicentr_category_mapping m
          ON m.sexopt_category_id = p.category_id
         AND COALESCE(m.confidence, 1) > 0
        WHERE p.available IS TRUE AND p.quantity > 1
          AND NOT p.damaged_stock AND p.price_retail > 0
        ORDER BY p.sku
    """)
    return cur.fetchall()


def load_params(cur) -> dict:
    """rozetka_boost сюди не пускаємо — ті значення робились під вільні пари."""
    cur.execute("""SELECT sku, param_name, param_value
                   FROM sexopt_extracted_params
                   WHERE source <> 'rozetka_boost'
                     AND param_value IS NOT NULL AND TRIM(param_value) <> ''""")
    out = collections.defaultdict(dict)
    for r in cur.fetchall():
        out[r['sku']][r['param_name']] = r['param_value']
    return out


def load_unknown_vendors(cur) -> set:
    """Бренди, яких немає в базі виробників Prom.

    Prom імпортує виробника лише якщо він є в базі маркетплейсу, інакше
    у звіті зʼявляється «Невідомий виробник». Перевірити це програмно
    неможливо — публічної вигрузки бази виробників немає, а API-токен
    акаунта віддає 401. Тому список наповнюється зі звіту про імпорт:
    tools/prom_unknown_vendors_load.py --from-report.

    Поки таблиця порожня, підміни не відбувається: це не блокує імпорт,
    бо невідомий виробник — попередження, а не помилка.
    """
    try:
        cur.execute('SELECT vendor FROM prom_unknown_vendors')
        return {(r['vendor'] or '').strip().lower() for r in cur.fetchall()}
    except psycopg2.Error:
        cur.connection.rollback()
        return set()


def load_overrides(cur) -> dict:
    try:
        cur.execute("""SELECT sku, price_manual FROM sexopt_price_override
                       WHERE until IS NULL OR until >= CURRENT_DATE""")
        return {r['sku']: int(r['price_manual']) for r in cur.fetchall()}
    except psycopg2.Error:
        cur.connection.rollback()
        return {}


def generate(out_file=OUT, limit=None):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    mapping = load_mapping(cur)
    rates = load_rates(cur)
    attrs = load_attributes(cur)
    cat_names = load_categories(cur)
    products = load_products(cur)
    params = load_params(cur)
    overrides = load_overrides(cur)
    unknown_vendors = load_unknown_vendors(cur)
    conn.close()
    logger.info(f'Товарів у вибірці: {len(products)}')

    # ── різновиди: групуємо за брендом і назвою без розміру ─────────────────
    groups = collections.defaultdict(list)
    for p in products:
        groups[(p['vendor'], variant_key(p['vendor'], p['name']))].append(p)
    logger.info(f'Груп після обʼєднання розмірів: {len(groups)}')

    st = collections.Counter()
    used_cats, offers = {}, []

    for key, items in groups.items():
        head = items[0]
        pid, excluded = resolve_category(mapping, head['ec'], head['name'] or '')
        if not pid:
            st['без мапінгу'] += len(items)
            continue
        if excluded:
            st['виключено (Фаза 2)'] += len(items)
            continue
        # ворота якості: опис і фото — вимоги Prom, не наші побажання
        if not any((x['description_html'] or '').strip() for x in items):
            st['без опису'] += len(items)
            continue
        if not any(len(x['pictures'] or []) >= 2 for x in items):
            st['менше 2 фото'] += len(items)
            continue

        # Групуємо лише тоді, коли різновиди справді різні. Ознака береться
        # з назви (розмір або колір); якщо в двох позицій вона однакова —
        # це не різновиди, а дублі товару під різними артикулами. Вигадувати
        # їм відмінність не можна, тому такі йдуть окремими позиціями.
        marks = [variant_mark(x['name'] or '')[1] for x in items]
        distinct = len(items) > 1 and all(marks) and len(set(marks)) == len(marks)
        # Prom відхиляє різновид, у якого є характеристика, відсутня в
        # основного товару: «знайдені характеристики, яких немає в основного
        # товару». Тому в межах групи лишаємо лише СПІЛЬНІ ключі — перетин,
        # а не обʼєднання. Відмітна ознака додається всім, тож набір ключів
        # виходить однаковий, а значення різні.
        common_keys = None
        if distinct:
            for x in items:
                r = dict(params.get(x['sku'], {}))
                if x['country']:
                    r.setdefault('Країна-виробник',
                                 x['country'].split('(')[0].strip())
                keys = set(fit_params(r, pid, attrs))
                common_keys = keys if common_keys is None else (common_keys & keys)
        # group_id рахуємо ДЕТЕРМІНОВАНО з ключа групи, а не наскрізним
        # лічильником: зникнення одного товару зсувало нумерацію всім групам
        # після нього (147 з 359 офферів змінили group_id між двома збірками),
        # і Prom щоразу перебудовував би звʼязки різновидів заново.
        group_id = stable_group_id(key) if distinct else None
        if group_id:
            st['груп із різновидами'] += 1
        elif len(items) > 1:
            st['дублі — розгруповано'] += len(items)
        used_cats[pid] = cat_names.get(pid, pid)
        rate = rates.get(pid, DEFAULT_COMMISSION)

        for p in items:
            sku = p['sku']
            name = (p['name'] or '').strip()
            if len(name) > MAX_NAME:
                name = name[:MAX_NAME].rsplit(' ', 1)[0].rstrip(' ,.-')
                st['назву вкорочено'] += 1
            pics = [u for u in (p['pictures'] or []) if u]
            if len(pics) > MAX_PICTURES:
                st['фото обрізано'] += 1
            pics = pics[:MAX_PICTURES]
            if not pics:
                st['без фото'] += 1
                continue

            desc = (p['description_html'] or '').strip()
            if not desc:
                # У межах групи опис може бути лише в одного розміру —
                # беремо його, інакше українська назва не застосується.
                desc = next(((x['description_html'] or '').strip()
                             for x in items
                             if (x['description_html'] or '').strip()), '')
                st['опис узято з різновиду'] += 1

            raw = dict(params.get(sku, {}))
            if p['country']:
                raw.setdefault('Країна-виробник',
                               p['country'].split('(')[0].strip())
            prm = fit_params(raw, pid, attrs)
            if group_id:
                dropped = len(prm)
                prm = {k: v for k, v in prm.items() if k in (common_keys or set())}
                if dropped != len(prm):
                    st['характеристик прибрано з різновидів'] += dropped - len(prm)
                # Різновид без жодного відмінного значення Prom не імпортує
                mk, mv = variant_mark(p['name'] or '')
                prm[mk] = mv
                st['ознаку різновиду додано'] += 1
            st[f'характеристик {min(len(prm), 5)}'] += 1
            if len(prm) < MIN_PARAMS:
                st['менше 2 характеристик'] += 1

            price = overrides.get(sku) or calc_price(
                float(p['price_retail']), rate)
            attr = (f'      <offer id="{esc(sku)}" available="true" '
                    f'selling_type="r"'
                    + (f' group_id="{group_id}"' if group_id else '') + '>')
            o = [attr,
                 f'        <name>{esc(name)}</name>',
                 f'        <name_ua>{esc(name)}</name_ua>']
            o += [f'        <picture>{esc(u)}</picture>' for u in pics]
            o += [f'        <price>{price}</price>',
                  '        <currencyId>UAH</currencyId>',
                  f'        <categoryId>{esc(pid)}</categoryId>',
                  f'        <portal_category_id>{esc(pid)}</portal_category_id>']
            vendor = re.sub(r'\s*\(.*?\)', '', p['vendor'] or '').strip()
            if vendor.lower() in unknown_vendors:
                vendor = 'Без бренда'
                st['бренд замінено на «Без бренда»'] += 1
            if vendor:
                o.append(f'        <vendor>{esc(vendor)}</vendor>')
            o.append(f'        <vendorCode>{esc(sku[:MAX_ARTICLE])}</vendorCode>')
            o.append(f'        <quantity_in_stock>{int(p["quantity"] or 0)}'
                     f'</quantity_in_stock>')
            # description і description_ua ЗАВЖДИ разом: без пари Prom не
            # застосує ані український опис, ані українську назву.
            o.append(f'        <description>{cdata(desc)}</description>')
            o.append(f'        <description_ua>{cdata(desc)}</description_ua>')
            for k, v in list(prm.items())[:MAX_PARAMS]:
                o.append(f'        <param name="{esc(k)}">{esc(v)}</param>')
            o.append('      </offer>')
            offers.append('\n'.join(o))
            st['офферів'] += 1

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<yml_catalog date="{datetime.now():%Y-%m-%d %H:%M}">',
             '  <shop>',
             f'    <name>{esc(SHOP_NAME)}</name>',
             f'    <company>{esc(SHOP_COMPANY)}</company>',
             f'    <url>{esc(SHOP_URL)}</url>',
             '    <currencies><currency id="UAH" rate="1" /></currencies>',
             '    <categories>']
    for pid, nm in sorted(used_cats.items(), key=lambda x: x[1]):
        lines.append(f'      <category id="{esc(pid)}" portal_id="{esc(pid)}">'
                     f'{esc(nm)}</category>')
    lines += ['    </categories>', '    <offers>']
    lines += offers[:limit] if limit else offers
    lines += ['    </offers>', '  </shop>', '</yml_catalog>', '']

    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    logger.success(f"Згенеровано офферів: {st['офферів']} → {out_file}")
    logger.info(f"  категорій             : {len(used_cats)}")
    logger.info(f"  груп із різновидами   : {st['груп із різновидами']}")
    for k in ('виключено (Фаза 2)', 'без опису', 'менше 2 фото', 'без мапінгу',
              'фото обрізано', 'назву вкорочено', 'менше 2 характеристик',
              'опис узято з різновиду', 'ознаку різновиду додано',
              'дублі — розгруповано', 'бренд замінено на «Без бренда»',
              'характеристик прибрано з різновидів'):
        if st[k]:
            logger.info(f'  {k:22}: {st[k]}')
    return st['офферів']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--output', default=OUT)
    ap.add_argument('--limit', type=int)
    a = ap.parse_args()
    sys.exit(0 if generate(a.output, a.limit) else 1)


if __name__ == '__main__':
    main()
