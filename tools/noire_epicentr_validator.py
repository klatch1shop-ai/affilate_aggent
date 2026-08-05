#!/usr/bin/env python3
"""
tools/noire_epicentr_validator.py
Per-offer validation for NOIRE → Epicentr XML.

Перевіряє:
  1. Базові обов'язкові поля (id, available, price, name, pictures, vendor,
     country_of_origin, weight/width/height/length, description)
  2. Категорійні обов'язкові характеристики (<param paramcode=...>) з
     epicentr_required_attrs_sexopt (populated by fetch_sexopt_attr_sets.py),
     fallback → scan /v2/pim/attribute-sets API

Запуск:
    cd /home/tekken/agent-system && source venv/bin/activate
    python3 tools/noire_epicentr_validator.py /tmp/noire_test_batch.xml
    python3 tools/noire_epicentr_validator.py exports/noire_epicentr.xml --brief
"""

import argparse, json, os, re, sys, time
from collections import defaultdict
from typing import NamedTuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, '.env'))

try:
    from lxml import etree as ET
    LXML = True
except ImportError:
    import xml.etree.ElementTree as ET
    LXML = False

import requests
from shared.utils.db import get_connection

# ── Ліміти полів ─────────────────────────────────────────────────────────────

LIMIT_ID          = 64
LIMIT_NAME        = 150
LIMIT_DESC        = 12160
MIN_PICS_WARN     = 2      # попередження якщо <2 фото

# Логістичні атрибути — вже перевіряються як XML-теги, не як <param>
# Пропускаємо їх при перевірці category params щоб не дублювати
LOGISTICS_NAMES_KW = (
    'вага', 'ширина', 'висота', 'довжина', 'глибина',
    'розмір упак', 'габарит', 'weight', 'width', 'height', 'length', 'depth',
)

# Базові params що генератор вже додає — вони ОК навіть без явного PIM-requirement
ALWAYS_PRESENT_PARAMCODES = {'measure', 'ratio', 'brand'}

# ── Типи ─────────────────────────────────────────────────────────────────────

CRIT = 'CRIT'
WARN = 'WARN'

class Issue(NamedTuple):
    severity: str
    field:    str
    message:  str


# ── Довідники з БД ────────────────────────────────────────────────────────────

def load_valid_cats(cur) -> set[str]:
    cur.execute("SELECT code FROM epicentr_intimate_categories")
    return {r['code'] for r in cur.fetchall()}


def load_required_attrs_from_db(cur, attr_set_codes: set[str]) -> dict[str, list[dict]]:
    """Повертає {code: [{attribute_code, attribute_name}, ...]} з is_required=true."""
    if not attr_set_codes:
        return {}
    cur.execute("""
        SELECT attribute_set_code, attribute_code, attribute_name
        FROM   epicentr_required_attrs_sexopt
        WHERE  attribute_set_code = ANY(%s)
          AND  is_required = TRUE
        ORDER BY attribute_set_code, attribute_code
    """, (list(attr_set_codes),))
    result: dict[str, list[dict]] = defaultdict(list)
    for r in cur.fetchall():
        result[r['attribute_set_code']].append({
            'code': r['attribute_code'],
            'name': r['attribute_name'],
        })
    return dict(result)


def fetch_required_attrs_api(attr_set_codes: set[str]) -> dict[str, list[dict]]:
    """
    Сканує /v2/pim/attribute-sets (всі сторінки — filter[ids][] не фільтрує),
    повертає required attrs для запрошених кодів.
    """
    import os
    TOKEN = os.getenv('EPICENTR_TOKEN')
    if not TOKEN:
        print("  WARN: EPICENTR_TOKEN не задано — пропускаємо API-перевірку params", file=sys.stderr)
        return {}

    BASE  = 'https://merchant-api.epicentrm.com.ua'
    H     = {'Authorization': f'Bearer {TOKEN}'}

    def get_name_ua(translations):
        for t in translations:
            if t.get('languageCode') == 'ua':
                return t.get('title', '')
        return ''

    found: dict[str, list[dict]] = {}
    remaining = set(attr_set_codes)
    print(f"  Сканування PIM API для {len(remaining)} кодів...", flush=True)

    for pg in range(1, 60):
        r = requests.get(f'{BASE}/v2/pim/attribute-sets', headers=H,
                         params={'limit': 100, 'page': pg}, timeout=30)
        if not r.ok:
            break
        for item in r.json().get('items', []):
            code = str(item['code'])
            if code in remaining:
                attrs = [
                    {'code': str(a.get('code', '')), 'name': get_name_ua(a.get('translations', []))}
                    for a in item.get('attributes', [])
                    if a.get('isRequired')
                ]
                found[code] = attrs
                remaining.discard(code)
        if not remaining:
            break
        time.sleep(0.1)

    return found


def load_required_attrs(cur, attr_set_codes: set[str]) -> dict[str, list[dict]]:
    """DB-first, API-fallback."""
    result = load_required_attrs_from_db(cur, attr_set_codes)
    missing = attr_set_codes - set(result.keys())
    if missing:
        print(f"  {len(missing)} кодів відсутні в DB → API fallback: {sorted(missing)}", flush=True)
        api_result = fetch_required_attrs_api(missing)
        result.update(api_result)
    return result


# ── Перевірка одного offer ────────────────────────────────────────────────────

def check_offer(
    offer,
    valid_cats: set[str],
    required_attrs: dict[str, list[dict]],
    use_lxml: bool = False,
) -> tuple[str, str, str, list[Issue]]:
    """
    Повертає (sku, cat_code, name_short, issues).
    """
    issues: list[Issue] = []

    def crit(field, msg): issues.append(Issue(CRIT, field, msg))
    def warn(field, msg): issues.append(Issue(WARN, field, msg))

    get   = offer.get if use_lxml else offer.get
    find  = offer.find
    findall = offer.findall

    # ── 1. id ─────────────────────────────────────────────────────────────────
    sku = (get('id') or '').strip()
    if not sku:
        crit('id', 'відсутній або порожній')
    elif len(sku) > LIMIT_ID:
        crit('id', f'перевищує {LIMIT_ID} символів ({len(sku)})')

    # ── 2. available ──────────────────────────────────────────────────────────
    avail = (get('available') or '').lower()
    if avail not in ('true', 'false'):
        crit('available', f'невалідне значення: {avail!r}')

    # ── 3. price ──────────────────────────────────────────────────────────────
    price_el = find('price')
    price_val = 0.0
    if price_el is None or not (price_el.text or '').strip():
        crit('price', 'відсутня або порожня')
    else:
        try:
            price_val = float(price_el.text.strip())
            if price_val <= 0:
                crit('price', f'значення ≤ 0: {price_el.text.strip()}')
        except ValueError:
            crit('price', f'не є числом: {price_el.text.strip()!r}')

    # ── 4. category code ──────────────────────────────────────────────────────
    cat_el   = find('category')
    cat_code = ''
    if cat_el is None:
        crit('category', 'тег <category> відсутній')
    else:
        cat_code = (cat_el.get('code') or '').strip()
        if not cat_code:
            crit('category', 'атрибут code порожній')
        elif cat_code not in valid_cats:
            crit('category', f'code={cat_code!r} відсутній у epicentr_intimate_categories')

    # ── 5. attribute_set code ─────────────────────────────────────────────────
    as_el = find('attribute_set')
    as_code = ''
    if as_el is None:
        crit('attribute_set', 'тег <attribute_set> відсутній')
    else:
        as_code = (as_el.get('code') or '').strip()
        if not as_code:
            crit('attribute_set', 'атрибут code порожній')

    # ── 6. name lang="ua" ─────────────────────────────────────────────────────
    name_text = ''
    ua_names = [n for n in findall('name') if n.get('lang') == 'ua']
    if not ua_names:
        crit('name', 'відсутній <name lang="ua">')
    else:
        name_text = (ua_names[0].text or '').strip()
        if not name_text:
            crit('name', '<name lang="ua"> порожній')
        elif len(name_text) > LIMIT_NAME:
            crit('name', f'{len(name_text)} символів > ліміт {LIMIT_NAME}')

    # ── 7. vendor ─────────────────────────────────────────────────────────────
    vendor_el = find('vendor')
    if vendor_el is None:
        crit('vendor', 'тег <vendor> відсутній')
    elif not (vendor_el.text or '').strip():
        crit('vendor', '<vendor> порожній')

    # ── 8. pictures ───────────────────────────────────────────────────────────
    pics = findall('picture')
    valid_pics = [p for p in pics if (p.text or '').strip().startswith('http')]
    if not valid_pics:
        crit('picture', 'жодного фото')
    elif len(valid_pics) < MIN_PICS_WARN:
        warn('picture', f'лише {len(valid_pics)} фото (рекомендовано ≥{MIN_PICS_WARN})')

    # ── 9. description lang="ua" ──────────────────────────────────────────────
    ua_descs = [d for d in findall('description') if d.get('lang') == 'ua']
    if not ua_descs:
        crit('description', 'відсутній <description lang="ua">')
    else:
        desc_text = (ua_descs[0].text or '').strip()
        if not desc_text:
            crit('description', '<description lang="ua"> порожній')
        elif len(desc_text) > LIMIT_DESC:
            crit('description', f'{len(desc_text)} символів > ліміт {LIMIT_DESC}')

    # ── 10. country_of_origin ─────────────────────────────────────────────────
    co_el = find('country_of_origin')
    if co_el is None:
        crit('country_of_origin', 'тег <country_of_origin> відсутній')
    else:
        co_code = (co_el.get('code') or '').strip()
        if not co_code:
            crit('country_of_origin', 'атрибут code порожній')

    # ── 11. weight / width / height / length ──────────────────────────────────
    for dim in ('weight', 'width', 'height', 'length'):
        dim_el = find(dim)
        if dim_el is None:
            crit(dim, f'тег <{dim}> відсутній')
        else:
            try:
                v = float(dim_el.text or '0')
                if v <= 0:
                    crit(dim, f'значення ≤ 0: {dim_el.text!r}')
                elif int(v) != v:
                    warn(dim, f'рекомендується ціле число: {dim_el.text!r}')
            except (ValueError, TypeError):
                crit(dim, f'не є числом: {dim_el.text!r}')

    # ── 12. Категорійні required params ──────────────────────────────────────
    # Використовуємо attribute_set_code для пошуку required attrs
    req_code = as_code or cat_code
    if req_code and req_code in required_attrs:
        present_codes = {(p.get('paramcode') or '').strip()
                         for p in findall('param')
                         if (p.get('paramcode') or '').strip()}

        for attr in required_attrs[req_code]:
            acode = attr['code']
            aname = attr['name'] or acode

            # Пропускаємо логістичні (вага/габарити) — вже перевірені в п.11
            if any(kw in aname.lower() for kw in LOGISTICS_NAMES_KW):
                continue
            # Пропускаємо те, що генератор завжди додає
            if acode in ALWAYS_PRESENT_PARAMCODES:
                continue

            if acode not in present_codes:
                crit('param', f'відсутній обов\'язковий атрибут: {aname} (paramcode={acode!r})')

    name_short = name_text[:55] + '…' if len(name_text) > 55 else name_text
    return sku, cat_code, name_short, issues


# ── Головна функція ───────────────────────────────────────────────────────────

def validate(filepath: str, brief: bool = False) -> dict:
    if not os.path.exists(filepath):
        print(f'❌ Файл не знайдено: {filepath}')
        sys.exit(1)

    # ── Парсинг XML ─────────────────────────────────────────────────────────
    print(f'Парсинг {filepath}...', flush=True)
    try:
        if LXML:
            tree = ET.parse(filepath)
            root = tree.getroot()
        else:
            tree = ET.parse(filepath)
            root = tree.getroot()
    except Exception as exc:
        print(f'❌ XML parse error: {exc}')
        sys.exit(1)

    offers_el = root.find('offers')
    if offers_el is None:
        print('❌ Тег <offers> відсутній')
        sys.exit(1)

    offers = list(offers_el.findall('offer'))
    print(f'Офферів: {len(offers)}')

    # ── Довідники ───────────────────────────────────────────────────────────
    conn = get_connection()
    cur  = conn.cursor()

    valid_cats = load_valid_cats(cur)
    print(f'Валідних категорій у DB: {len(valid_cats)}')

    # Унікальні attribute_set_code з XML
    attr_set_codes = set()
    for off in offers:
        as_el = off.find('attribute_set')
        if as_el is not None:
            c = (as_el.get('code') or '').strip()
            if c:
                attr_set_codes.add(c)
    print(f'Унікальних attribute_set кодів: {attr_set_codes}')

    required_attrs = load_required_attrs(cur, attr_set_codes)
    conn.close()

    # Показуємо зведення required attrs по категоріях
    print()
    for code in sorted(attr_set_codes):
        attrs = required_attrs.get(code, [])
        req_non_logistics = [
            a for a in attrs
            if not any(kw in (a['name'] or '').lower() for kw in LOGISTICS_NAMES_KW)
            and a['code'] not in ALWAYS_PRESENT_PARAMCODES
        ]
        print(f'  {code}: {len(attrs)} required attrs, {len(req_non_logistics)} category-specific')
    print()

    # ── Перевірка офферів ───────────────────────────────────────────────────
    results   = []
    cnt_pass  = 0
    cnt_warn  = 0
    cnt_fail  = 0
    cat_names = {}  # code → name (from XML itself)

    for off in offers:
        cat_el = off.find('category')
        if cat_el is not None:
            c = (cat_el.get('code') or '').strip()
            t = (cat_el.text or '').strip()
            if c and t:
                cat_names[c] = t

    for idx, off in enumerate(offers, 1):
        sku, cat_code, name_short, issues = check_offer(
            off, valid_cats, required_attrs, use_lxml=LXML
        )
        crits = [i for i in issues if i.severity == CRIT]
        warns = [i for i in issues if i.severity == WARN]

        if crits:
            status   = '❌ FAIL'
            cnt_fail += 1
        elif warns:
            status   = '⚠️  WARN'
            cnt_warn += 1
        else:
            status   = '✅ PASS'
            cnt_pass += 1

        cat_label = cat_names.get(cat_code, cat_code)
        results.append((idx, sku, cat_label, name_short, status, crits, warns))

    # ── Вивід ───────────────────────────────────────────────────────────────
    print('═' * 110)
    print(f'  NOIRE EPICENTR VALIDATOR  |  {filepath}  |  {len(offers)} офферів')
    print('═' * 110)

    for idx, sku, cat_label, name_short, status, crits, warns in results:
        print(f'[{idx:02d}] {sku:<12}  {cat_label:<32}  {status}')
        if not brief or (crits or warns):
            for i in crits:
                print(f'       ❌ [{i.field}] {i.message}')
            for i in warns:
                print(f'       ⚠️  [{i.field}] {i.message}')

    # ── Підсумок ─────────────────────────────────────────────────────────────
    print()
    print('═' * 110)
    total = cnt_pass + cnt_warn + cnt_fail
    print(f'  ПІДСУМОК: {total} офферів')
    print(f'  ✅ PASS  (без проблем)         : {cnt_pass:>3}  ({100*cnt_pass//total if total else 0}%)')
    print(f'  ⚠️  WARN  (лише попередження)  : {cnt_warn:>3}  ({100*cnt_warn//total if total else 0}%)')
    print(f'  ❌ FAIL  (критичні — блокують) : {cnt_fail:>3}  ({100*cnt_fail//total if total else 0}%)')

    # Топ відсутніх полів по всім офферам
    from collections import Counter
    field_crit_cnt: Counter = Counter()
    for _, _, _, _, _, crits, _ in results:
        for i in crits:
            field_crit_cnt[f'{i.field}: {i.message[:60]}'] += 1

    if field_crit_cnt:
        print()
        print('  ТОП КРИТИЧНИХ ПРОБЛЕМ:')
        for msg, cnt in field_crit_cnt.most_common(15):
            print(f'    {cnt:>3}×  {msg}')

    print('═' * 110)
    return {'pass': cnt_pass, 'warn': cnt_warn, 'fail': cnt_fail, 'total': total}


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='NOIRE Epicentr XML validator')
    parser.add_argument('file', help='Шлях до XML-файлу')
    parser.add_argument('--brief', action='store_true',
                        help='Показувати деталі лише для FAIL/WARN офферів')
    args = parser.parse_args()

    result = validate(args.file, brief=args.brief)
    sys.exit(0 if result['fail'] == 0 else 1)


if __name__ == '__main__':
    main()
