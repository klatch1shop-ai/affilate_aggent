#!/usr/bin/env python3
"""Нормалізує вигрузку SMTM-косметики у список товарів для фіду EVA.

Вхід: exports/eva_categories_20260925.json (стоп-бренди EVA) і сирий прайс
SMTM `/tmp/smtm_cosmetic.xls` (`https://smtm.com.ua/_prices/import-retail-cosmetic.xls`,
завантажується окремо, не лежить у git). Виключає позиції без залишку та
зі стоп-брендом EVA.

Пастка, на якій уже спіймався 25.09: колонка «Фото» розділяє кілька URL
через `;\n`, НЕ через кому — з комою половина фото зливається в один тег
<picture>, і EVA отримала б биту адресу замість кількох окремих.

    python3 tools/eva_build_items.py --profile cosmetics   # лише підтверджені категорії
    python3 tools/eva_build_items.py --profile full        # увесь асортимент

Категорія більше НЕ береться з фолбеку `100212`: її дає
`content/eva_category_rules.resolve()` за розділом постачальника й назвою
товару, а коди звірені з живим довідником `exports/eva_categories_live.json`.

Профіль `cosmetics` лишає тільки косметику, `full` — увесь асортимент разом
із тримерами (це техніка, не косметика).
"""
import argparse
import json
import os
import re
import sys

import xlrd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from content.eva_category_rules import resolve          # noqa: E402

XLS = '/tmp/smtm_cosmetic.xls'
OUT_SKIPPED = os.path.join(BASE, 'exports', 'eva_feed_skipped_stopbrand.json')

# не косметика — потрапляє лише в повний фід: тримери (техніка), вінілові
# простирадла, текстильна маска, масажний килимок
NON_COSMETIC_SECTIONS = {'Регулярний догляд за тілом/Тример і засоби проти волосся'}
NON_COSMETIC_CATEGORIES = {'15535', '13677', '15025', '12852-12876'}


def load_ru(skus):
    """Російські назви й описи з `sexopt_products_ru` (13 222 рядки).

    EVA вимагає `name` російською і `name_ua` українською одночасно. Прайс
    SMTM дає лише українську — російська версія лежить окремо в базі.
    """
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, '.env'))
    conn = psycopg2.connect(host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT'),
                            dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
                            password=os.getenv('DB_PASSWORD'), connect_timeout=10)
    cur = conn.cursor()
    cur.execute('select sku, name_ru, description_ru from sexopt_products_ru '
                'where sku = any(%s)', (list(skus),))
    out = {sku: (nm, ds) for sku, nm, ds in cur.fetchall()}
    conn.close()
    return out


def clean_name(name):
    """Прибирає подвійні пробіли, які приходять із CMS постачальника."""
    return re.sub(r'\s{2,}', ' ', (name or '').strip())


def clean_description(html):
    """Чистить сміття CMS постачальника в описі.

    `<meta charset>` усередині <p>, атрибут lang="ru-RU" на українському
    тексті (менеджер EVA на ручній валідації це помітить) і порожні абзаци
    `<p>&nbsp;</p>`.
    """
    if not html:
        return ''
    html = re.sub(r'<meta[^>]*>', '', html, flags=re.I)
    html = re.sub(r'\s+lang="[^"]*"', '', html, flags=re.I)
    html = re.sub(r'<p[^>]*>(?:\s|&nbsp;)*</p>', '', html, flags=re.I)
    return html.strip()


def https(url):
    """Фото постачальника віддаються і по http, і по https з того самого хоста.

    http відповідає 301 на https, але EVA тягне фото окремим ботом — на
    редирект покладатись не варто, тому нормалізуємо самі.
    """
    return re.sub(r'^http://', 'https://', url)


VOLUME_RE = re.compile(r'\((?:(\d+)\s*[xх×]\s*)?(\d+(?:[.,]\d+)?)\s*(мл|г|гр)\)', re.I)


def volume_from_name(name):
    """Обʼєм із назви виду «(100 мл)» або «(3х30 мл)» — для 153 товарів,
    де колонка обʼєму в прайсі порожня, хоча в назві він є."""
    m = VOLUME_RE.search(name or '')
    if not m:
        return None
    mult = int(m.group(1)) if m.group(1) else 1
    val = float(m.group(2).replace(',', '.')) * mult
    unit = 'мл' if m.group(3).lower() == 'мл' else 'г'
    return f'{val:g} {unit}'


def main(profile='cosmetics'):
    cats = json.load(open(os.path.join(BASE, 'exports', 'eva_categories_20260925.json'),
                          encoding='utf-8'))
    stop_brands = set()
    for lst in cats['stop_brands'].values():
        stop_brands.update(b.strip().lower() for b in lst)

    wb = xlrd.open_workbook(XLS)
    ws = wb.sheet_by_index(0)
    headers = ws.row_values(0)
    idx = {h: i for i, h in enumerate(headers)}
    vol_col = idx["Об'єм (мл)"]
    sec_col = idx['Розділ']

    items, skipped, no_category = [], [], []
    for i in range(1, ws.nrows):
        r = ws.row_values(i)
        sku = r[0]
        brand = re.sub(r'\s*\([^)]*\)\s*$', '', r[9] or '').strip()
        qty = r[2] or 0
        if not qty or float(qty) <= 0:
            continue
        if brand.lower() in stop_brands:
            skipped.append((sku, brand))
            continue
        photos = [https(p.strip()) for p in (r[6] or '').replace('\n', '').split(';') if p.strip()]
        name = clean_name(r[1])
        desc = clean_description(r[5])
        params = {}
        if r[idx['Косметика: вид']]:
            params['Косметика: вид'] = r[idx['Косметика: вид']]
        if r[idx['Косметика: дія']]:
            params['Косметика: дія'] = r[idx['Косметика: дія']]
        if r[vol_col]:
            params['Обʼєм'] = f'{r[vol_col]:g} мл'
        else:
            vol = volume_from_name(name)        # у прайсі порожньо, але в назві обʼєм є
            if vol:
                params['Обʼєм'] = vol
        if r[idx['Країна надходження']]:
            params['Країна'] = r[idx['Країна надходження']]
        section = (r[sec_col] or '').strip()
        cid, slug, rule = resolve(section, name)
        if cid is None:
            no_category.append((sku, section))
            continue
        if profile == 'cosmetics' and (section in NON_COSMETIC_SECTIONS
                                       or cid in NON_COSMETIC_CATEGORIES):
            continue

        items.append({'sku': sku, 'name_ru': name, 'name_ua': name, 'price': float(r[3]),
                      'qty': float(qty), 'vendor': brand or 'NOIRE',
                      'category_id': cid, 'category_slug': slug, 'category_rule': rule,
                      'section': section, 'pictures': photos,
                      'description_ru': desc, 'description_ua': desc, 'params': params})

    # друга хвиля: російські назви й описи з бази, українські лишаються з прайсу
    ru = load_ru({i['sku'] for i in items})
    no_ru_name, no_ru_desc = [], []
    for it in items:
        nm, ds = ru.get(it['sku'], (None, None))
        if nm:
            it['name_ru'] = clean_name(nm)
        else:
            no_ru_name.append(it['sku'])
        if ds:
            it['description_ru'] = clean_description(ds)
        else:
            no_ru_desc.append(it['sku'])

    out_items = os.path.join(BASE, 'exports', f'eva_feed_items_{profile}.json')
    print(f'профіль: {profile}')
    print(f'без російської назви: {len(no_ru_name)} · без російського опису: {len(no_ru_desc)}')
    print(f'придатних позицій: {len(items)} · виключено (стоп-бренд): {len(skipped)}')
    print(f'не зіставлено з категорією EVA: {len(no_category)}')
    print(f'без опису: {sum(1 for x in items if not x["description_ru"])} · '
          f'без параметрів: {sum(1 for x in items if not x["params"])}')
    json.dump(items, open(out_items, 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(skipped, open(OUT_SKIPPED, 'w', encoding='utf-8'), ensure_ascii=False)
    print('записано:', out_items)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile', choices=['cosmetics', 'full'], default='cosmetics')
    main(ap.parse_args().profile)
