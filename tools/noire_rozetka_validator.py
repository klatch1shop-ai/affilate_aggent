#!/usr/bin/env python3
"""
Валідатор XML прайс-листа Rozetka для NOIRE.

Пороги взято з довідки продавця Rozetka (shared/knowledge_base/rozetka):
  • мінімум 3 характеристики на товар (p210)
  • від 1 до 15 фото, посилання без кирилиці (p216)
  • ціна без копійок, у гривнях (p214)
  • назва, бренд, артикул — обовʼязкові (p211, p213, p217)

Окремо перевіряється правило Rozetka про різку зміну ціни: позиції, де ціна
зросла втричі або впала вдвічі проти попереднього фіду, маркетплейс робить
неактивними до ручного підтвердження. Тому потрібен попередній файл.

Запуск:
    python3 tools/noire_rozetka_validator.py output/noire_rozetka.xml
    python3 tools/noire_rozetka_validator.py new.xml --prev old.xml
"""
import argparse
import collections
import re
import sys
import xml.etree.ElementTree as ET

MIN_PARAMS = 3
MIN_PIC, MAX_PIC = 1, 15
MAX_NAME = 255
PRICE_JUMP_UP = 3.0      # ціна зросла втричі
PRICE_JUMP_DOWN = 0.5    # ціна впала вдвічі


def load_prices(path):
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return {}
    out = {}
    for o in root.findall('.//offer'):
        p = o.findtext('price')
        if p:
            try:
                out[o.get('id', '')] = float(p)
            except ValueError:
                pass
    return out


def validate(path, prev_path=None):
    root = ET.parse(path).getroot()
    cats = {c.get('id'): (c.get('rz_id'), (c.text or '').strip())
            for c in root.findall('.//category')}
    offers = root.findall('.//offer')
    prev = load_prices(prev_path) if prev_path else {}

    no_rz = [cid for cid, (rz, _) in cats.items() if not rz]
    fails = collections.defaultdict(list)
    warns = collections.defaultdict(list)
    seen = set()
    avail = collections.Counter()

    for o in offers:
        sku = o.get('id', '')
        if sku in seen:
            fails['дублікат offer id'].append(sku)
        seen.add(sku)
        avail[o.get('available', '?')] += 1

        # ціна
        price_t = o.findtext('price')
        try:
            price = float(price_t)
            if price <= 0:
                fails['ціна <= 0'].append(sku)
            elif price != int(price):
                fails['ціна з копійками'].append(sku)
        except (TypeError, ValueError):
            fails['ціна відсутня або не число'].append(sku)
            price = None

        # категорія
        cid = o.findtext('categoryId')
        if cid not in cats:
            fails['categoryId немає в <categories>'].append(sku)
        elif not cats[cid][0]:
            warns['категорія без rz_id'].append(sku)

        # фото
        pics = [p.text for p in o.findall('picture') if p.text]
        if len(pics) < MIN_PIC:
            fails['немає фото'].append(sku)
        elif len(pics) > MAX_PIC:
            fails[f'фото більше {MAX_PIC}'].append(sku)
        for u in pics:
            if re.search(r'[А-Яа-яЇїІіЄєҐґ]', u):
                fails['кирилиця в URL фото'].append(sku)
                break
            if not u.lower().startswith(('http://', 'https://')):
                fails['фото не http(s)'].append(sku)
                break

        # назва, артикул, бренд
        name = o.findtext('name_ua') or o.findtext('name') or ''
        if not name.strip():
            fails['порожня назва'].append(sku)
        elif len(name) > MAX_NAME:
            warns[f'назва довша за {MAX_NAME}'].append(sku)
        if not (o.findtext('article') or '').strip():
            fails['немає article'].append(sku)
        if not (o.findtext('vendor') or '').strip():
            warns['немає vendor (бренд)'].append(sku)

        # характеристики
        params = o.findall('param')
        if len(params) < MIN_PARAMS:
            fails[f'характеристик менше {MIN_PARAMS}'].append(sku)
        for p in params:
            if not (p.get('name') or '').strip() or not (p.text or '').strip():
                fails['порожня характеристика'].append(sku)
                break
            if len(p.text or '') > 500:
                fails['характеристика довша за 500 символів'].append(sku)
                break

        # опис
        if not (o.findtext('description_ua') or o.findtext('description') or '').strip():
            warns['немає опису'].append(sku)

        # різка зміна ціни
        if price and sku in prev and prev[sku] > 0:
            ratio = price / prev[sku]
            if ratio >= PRICE_JUMP_UP:
                fails[f'стрибок ціни вгору у {ratio:.1f}× (Rozetka заблокує)'].append(sku)
            elif ratio <= PRICE_JUMP_DOWN:
                fails[f'падіння ціни у {1/ratio:.1f}× (Rozetka заблокує)'].append(sku)

    bad = {s for lst in fails.values() for s in lst}
    ok = len(seen) - len(bad)

    print('=' * 78)
    print(f'ФАЙЛ: {path}')
    print(f'Категорій: {len(cats)}' + (f'  (без rz_id: {len(no_rz)})' if no_rz else ''))
    print(f'Офферів: {len(offers)}  |  available: '
          + ', '.join(f'{k}={v}' for k, v in avail.items()))
    if prev:
        print(f'Порівняння цін з: {prev_path} ({len(prev)} позицій)')
    print('=' * 78)
    print(f'  ПРОЙШЛИ  : {ok}')
    print(f'  ПОМИЛКИ  : {len(bad)}')
    if fails:
        print('\nКРИТИЧНЕ (товар не буде опубліковано):')
        for k, v in sorted(fails.items(), key=lambda x: -len(x[1])):
            print(f'  {len(v):>5}×  {k}')
            print(f'         {", ".join(v[:6])}{" …" if len(v) > 6 else ""}')
    if warns:
        print('\nПОПЕРЕДЖЕННЯ (публікації не блокують):')
        for k, v in sorted(warns.items(), key=lambda x: -len(x[1])):
            print(f'  {len(v):>5}×  {k}')
    print('=' * 78)
    return len(bad)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('--prev', help='попередній фід для перевірки стрибків ціни')
    a = ap.parse_args()
    sys.exit(1 if validate(a.file, a.prev) else 0)


if __name__ == '__main__':
    main()
