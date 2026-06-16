#!/usr/bin/env python3
"""
tools/epicentr_xml_checker.py
Повна перевірка XML-файлу Єпіцентру перед імпортом.

Запуск:
    python3 tools/epicentr_xml_checker.py ~/Downloads/carvol_epicentr.xml
"""

import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

# ── Константи ────────────────────────────────────────────────────────────────

VALID_CATS = {'2821', '2848', '2866', '2874', '3729', '4907', '8743'}
WARN_CATS  = {'2883'}   # 2883 замінена на 2848 в Єпіцентрі

REQUIRED_PARAMS: dict[str, list[str]] = {
    '2821': ['10986', '11971', '4857', '5290', '5291', '78', '826', 'measure', 'ratio', 'brand'],
    '2848': ['measure', 'ratio', 'brand'],
    '2866': ['11263', '1548', '4866', '6534', '6546', '6547', 'measure', 'ratio', 'brand'],
    '3729': ['11926', '1514', '4866', '6510', '6513', '6564', 'measure', 'ratio', 'brand'],
    '4907': ['103', '1382', '1384', '1386', '5093', '6187', '78', 'measure', 'ratio', 'brand'],
    '8743': ['12097', '4866', '51', '52', '5575', 'measure', 'ratio', 'brand'],
}

W = 48   # inner width of report box (between ║ and ║)


# ── Хелпери ──────────────────────────────────────────────────────────────────

def _emoji_width(s: str) -> int:
    """Повертає приблизну display-ширину рядка (emoji = 2 cols)."""
    # emoji: ✅ ❌ ⚠️ — кожен займає 2 позиції в терміналі
    extra = sum(1 for ch in s if ch in '✅❌⚠️')
    return len(s) + extra


def _row(text: str) -> str:
    dw = _emoji_width(text)
    inner = f' {text} '
    inner_dw = dw + 2
    if inner_dw < W:
        inner = inner + ' ' * (W - inner_dw)
    elif inner_dw > W:
        # обрізаємо по символах (не по display width)
        inner = inner[:W - 1] + '…'
    return f'║{inner}║'


def _sep() -> str:
    return '╠' + '═' * W + '╣'


def _top() -> str:
    return '╔' + '═' * W + '╗'


def _bot() -> str:
    return '╚' + '═' * W + '╝'


def is_valid_pic_url(url: str) -> bool:
    if not url or not url.startswith('https://'):
        return False
    if len(url) <= 30:
        return False
    if not re.search(r'\d{7,}', url):
        return False
    return True


# ── Основна перевірка ────────────────────────────────────────────────────────

def check_xml(filepath: str) -> dict:
    r: dict = {
        'filepath': filepath,
        'parse_ok': False,
        'parse_error': '',
        'total_offers': 0,
        # дублікати
        'dup_ids': [],
        # назви
        'missing_name_ua': 0,
        'missing_name_ru': 0,
        'long_names': [],       # [(article, length), ...]
        # фото
        'no_pic': [],           # article ids без <picture>
        'bad_pic_count': 0,     # кількість окремих битих URL
        'bad_pic_articles': [], # article ids з хоча б одним битим URL
        # ціна
        'no_price': 0,
        'zero_price': 0,
        # категорії
        'invalid_cats': Counter(),
        'warn_cats': Counter(),
        'cat_stats': Counter(),
        # обов'язкові поля
        'no_vendor_code': 0,
        'no_country': 0,
        'bad_dims': 0,
        # обов'язкові params
        # cat_code → {'ok': n, 'bad': n, 'missing': Counter()}
        'params_by_cat': {c: {'ok': 0, 'bad': 0, 'missing': Counter()}
                          for c in REQUIRED_PARAMS},
    }

    # 1. Парсинг
    try:
        tree = ET.parse(filepath)
    except ET.ParseError as exc:
        r['parse_error'] = str(exc)
        return r

    root = tree.getroot()
    r['parse_ok'] = True

    if root.tag != 'yml_catalog':
        r['parse_error'] = f'корінь: {root.tag!r} (очікується yml_catalog)'

    offers_el = root.find('offers')
    if offers_el is None:
        r['parse_error'] += ' | тег <offers> відсутній'
        return r

    offers = offers_el.findall('offer')
    r['total_offers'] = len(offers)

    seen_ids: set[str] = set()

    for offer in offers:
        article = (offer.get('id') or '').strip()

        # 2. Дублікати
        if article in seen_ids:
            r['dup_ids'].append(article)
        else:
            seen_ids.add(article)

        # 3. Назви
        ua_names = [n for n in offer.findall('name') if n.get('lang') == 'ua']
        ru_names = [n for n in offer.findall('name') if n.get('lang') == 'ru']
        if not ua_names or not (ua_names[0].text or '').strip():
            r['missing_name_ua'] += 1
        else:
            ua_text = ua_names[0].text.strip()
            if len(ua_text) > 150:
                r['long_names'].append((article, len(ua_text)))
        if not ru_names or not (ru_names[0].text or '').strip():
            r['missing_name_ru'] += 1

        # 4. Фото
        pics = offer.findall('picture')
        if not pics:
            r['no_pic'].append(article)
        else:
            bad_in_offer = False
            for p in pics:
                url = (p.text or '').strip()
                if not is_valid_pic_url(url):
                    r['bad_pic_count'] += 1
                    bad_in_offer = True
            if bad_in_offer:
                r['bad_pic_articles'].append(article)

        # 5. Ціна
        price_el = offer.find('price')
        if price_el is None or not (price_el.text or '').strip():
            r['no_price'] += 1
        else:
            try:
                if float(price_el.text.strip()) <= 0:
                    r['zero_price'] += 1
            except ValueError:
                r['zero_price'] += 1

        # 6. Категорія
        cat_el = offer.find('category')
        cat_code = ((cat_el.get('code') or '') if cat_el is not None else '').strip()
        if cat_code:
            if cat_code not in VALID_CATS:
                r['invalid_cats'][cat_code] += 1
            if cat_code in WARN_CATS:
                r['warn_cats'][cat_code] += 1
            r['cat_stats'][cat_code] += 1

        # 7. Обов'язкові поля
        vendor_el = offer.find('vendor')
        if vendor_el is None or not (vendor_el.get('code') or '').strip():
            r['no_vendor_code'] += 1

        if offer.find('country_of_origin') is None:
            r['no_country'] += 1

        bad_dim = False
        for tag in ('weight', 'width', 'height', 'length'):
            el = offer.find(tag)
            if el is None:
                bad_dim = True
                break
            try:
                if float(el.text or '0') <= 0:
                    bad_dim = True
                    break
            except (ValueError, TypeError):
                bad_dim = True
                break
        if bad_dim:
            r['bad_dims'] += 1

        # 8. Обов'язкові params
        if cat_code in REQUIRED_PARAMS:
            present = {(p.get('paramcode') or '').strip()
                       for p in offer.findall('param')}
            missing = set(REQUIRED_PARAMS[cat_code]) - present
            c = r['params_by_cat'][cat_code]
            if missing:
                c['bad'] += 1
                for m in missing:
                    c['missing'][m] += 1
            else:
                c['ok'] += 1

    return r


# ── Друк звіту ───────────────────────────────────────────────────────────────

def print_report(r: dict) -> bool:
    """Друкує звіт і повертає True якщо файл готовий до імпорту."""

    errors:   list[str] = []
    warnings: list[str] = []
    check_lines: list[str] = []

    def add(msg: str):
        check_lines.append(msg)
        if msg.startswith('❌'):
            errors.append(msg)
        elif msg.startswith('⚠'):
            warnings.append(msg)

    # 1. Структура XML
    if not r['parse_ok']:
        add(f'❌ Структура XML: {r["parse_error"]}')
    elif r['parse_error']:
        add(f'⚠️  Структура XML: {r["parse_error"]}')
    else:
        add('✅ Структура XML: OK')

    # 2. Дублікати
    dup_cnt = len(r['dup_ids'])
    if dup_cnt:
        add(f'❌ Дублікати: {dup_cnt} offer id')
    else:
        add('✅ Дублікати: 0')

    # 3. Назви
    miss_ua = r['missing_name_ua']
    miss_ru = r['missing_name_ru']
    long_n  = len(r['long_names'])
    if miss_ua or miss_ru or long_n:
        parts = []
        if miss_ua: parts.append(f'{miss_ua} без ua')
        if miss_ru: parts.append(f'{miss_ru} без ru')
        if long_n:  parts.append(f'{long_n} довших 150')
        add('❌ Назви: ' + ', '.join(parts))
    else:
        add('✅ Назви: всі ≤ 150 символів')

    # 4. Фото
    no_pic_cnt  = len(r['no_pic'])
    bad_pic_cnt = r['bad_pic_count']
    if no_pic_cnt or bad_pic_cnt:
        parts = []
        if no_pic_cnt:  parts.append(f'{no_pic_cnt} без фото')
        if bad_pic_cnt: parts.append(f'{bad_pic_cnt} битих URL')
        if no_pic_cnt:
            add('❌ Фото: ' + ', '.join(parts))
        else:
            add('⚠️  Фото: ' + ', '.join(parts))
    else:
        add('✅ Фото: всі валідні')

    # 5. Ціна
    price_bad = r['no_price'] + r['zero_price']
    if price_bad:
        add(f'❌ Ціна: {price_bad} офферів ≤ 0 або відсутня')
    else:
        add('✅ Ціна: всі > 0')

    # 6. Категорії
    invalid_cnt = sum(r['invalid_cats'].values())
    warn_cnt    = sum(r['warn_cats'].values())
    if invalid_cnt:
        add(f'❌ Категорії: {invalid_cnt} офферів з невалідним кодом')
    elif warn_cnt:
        add(f'⚠️  Категорії: {warn_cnt} офферів у 2883 (→ замінити на 2848)')
    else:
        add('✅ Категорії: всі валідні')

    # 7. Обов'язкові поля
    nvc = r['no_vendor_code']
    nc  = r['no_country']
    bd  = r['bad_dims']
    if nvc or nc or bd:
        parts = []
        if nvc: parts.append(f'{nvc} без vendor.code')
        if nc:  parts.append(f'{nc} без country')
        if bd:  parts.append(f'{bd} без dims')
        add('❌ Поля: ' + ', '.join(parts))
    else:
        add('✅ Поля (vendor/country/dims): OK')

    # 8. Обов'язкові params
    for cat_code in sorted(REQUIRED_PARAMS.keys()):
        c = r['params_by_cat'].get(cat_code, {})
        ok_n  = c.get('ok', 0)
        bad_n = c.get('bad', 0)
        total_cat = ok_n + bad_n
        if total_cat == 0:
            continue
        if bad_n:
            pct = int(bad_n / total_cat * 100)
            add(f'❌ Params {cat_code}: {bad_n}/{total_cat} без attrs ({pct}%)')
        else:
            add(f'✅ Params {cat_code}: {ok_n}/{ok_n} OK')

    # ── Друк рамки ──────────────────────────────────────────────────────────
    filepath = r['filepath']
    total    = r['total_offers']

    lines = [
        _top(),
        _row('    EPICENTR XML CHECKER REPORT    '),
        _sep(),
        _row(f'Файл: {os.path.abspath(filepath)}'),
        _row(f'Офферів: {total}'),
        _sep(),
    ]
    for cl in check_lines:
        lines.append(_row(cl))
    lines.append(_sep())

    ready = len(errors) == 0
    if ready:
        lines.append(_row('ГОТОВИЙ ДО ІМПОРТУ: ТАК ✅'))
    else:
        lines.append(_row('ГОТОВИЙ ДО ІМПОРТУ: НІ ❌'))
    lines.append(_bot())

    print('\n'.join(lines))

    # ── Детальна статистика ──────────────────────────────────────────────────
    if r['cat_stats']:
        print('\nСтатистика по категоріях:')
        for cat, cnt in sorted(r['cat_stats'].items(), key=lambda x: -x[1]):
            print(f'  {cat:>6}  {cnt:5}')

    if r['dup_ids']:
        print(f'\nПерші дублікати: {r["dup_ids"][:10]}')

    if r['long_names']:
        print('\nНадто довгі назви (топ-5):')
        for art, ln in r['long_names'][:5]:
            print(f'  {art}: {ln} символів')

    if r['no_pic']:
        print(f'\nАртикули без фото (топ-10): {r["no_pic"][:10]}')

    if r['bad_pic_articles']:
        print(f'\nАртикули з битими фото (топ-10): {r["bad_pic_articles"][:10]}')

    for cat_code in sorted(REQUIRED_PARAMS.keys()):
        c = r['params_by_cat'].get(cat_code, {})
        missing_c: Counter = c.get('missing', Counter())
        if not missing_c:
            continue
        print(f'\nВідсутні params у кат. {cat_code} (топ-5):')
        for param, cnt in missing_c.most_common(5):
            print(f'  paramcode={param!r:<12}  у {cnt} офферів')

    return ready


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(f'Використання: python3 {sys.argv[0]} <path/to/carvol_epicentr.xml>')
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f'Файл не знайдено: {filepath}')
        sys.exit(1)

    size_mb = os.path.getsize(filepath) / 1024 / 1024
    print(f'Перевірка: {filepath} ({size_mb:.1f} MB) ...\n')

    results = check_xml(filepath)
    ready   = print_report(results)
    sys.exit(0 if ready else 1)


if __name__ == '__main__':
    main()
