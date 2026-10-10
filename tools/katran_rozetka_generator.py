#!/usr/bin/env python3
"""Фід KATRAN → Rozetka. Заміна `agents/orders/katran_xml_generator.py`.

ЧОМУ ЗАНОВО. Старий генератор виміряно 06.10.2026 на справжніх даних:
  * 3886 з 6427 товарів (60,5 %) падали в ЗАПАСНУ категорію «Ручний
    інструмент» — ноутбук серед ручного інструменту;
  * 80 товарів мали ціну, нижчу за нашу ж закупівлю; найгірший — ноутбук,
    закупівля 51 744 ₴, наша ціна 48 490 ₴, збиток 3254 ₴ на штуці;
  * фільтра стоп-брендів не було ВЗАГАЛІ: 116 товарів заборонених на
    Rozetka брендів (Tefal, Rowenta, Xiaomi, Moulinex) пішли б у фід;
  * `is_in_stock` приймав будь-яке слово на «е»/«є», тож майбутнє значення
    на кшталт «ожидается» зарахувалось би як наявність.

ПРАВИЛА ЦЬОГО ГЕНЕРАТОРА:
  1. ЛИШЕ СКЛАД. `stock` має дорівнювати «есть» ТОЧНО. Значення «на витрине»
     (131 товар, у всіх stock_quantity=0) — це вітринні зразки, не склад.
     Будь-яке невідоме значення вважається НЕ наявністю, а не навпаки.
  2. БЕЗ ЗАПАСНОЇ КАТЕГОРІЇ. Немає підтвердженого rz_id — товар не йде у
     фід. Покласти не туди гірше, ніж не покласти.
  3. СТОП-БРЕНДИ за брендом І категорією (`tools/rozetka_stop_brands.py`),
     з офіційної таблиці Rozetka, а не з переказу.
  4. ЦІНА НІКОЛИ НЕ НИЖЧА ЗА ЗАКУПІВЛЮ. Беремо більше з двох: РРЦ плюс
     комісія категорії, або закупівля з ПДВ плюс та сама комісія плюс
     мінімальна маржа. Інакше продаж коштує нам грошей.
  5. Формат — як у фідів, що вже пройшли валідацію (dropoffice, toptul):
     локальний id категорії плюс атрибут `rz_id`.

Довідка: shared/knowledge_base/rozetka/ (xml_requirements, stop_brands_full).
"""
import argparse
import collections
import io
import json
import math
import os
import re
import sys
import zipfile
from datetime import datetime
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'tools'))
from dotenv import load_dotenv                                     # noqa: E402
load_dotenv(os.path.join(BASE, '.env'), override=True)
from rozetka_stop_brands import banned, load as load_stop          # noqa: E402

SHOP_NAME = 'klatch1 shop'
SHOP_COMPANY = 'FOP Oliinyk Serhii'
SHOP_URL = 'https://cs4053918.prom.ua/'
OUT = os.path.join(BASE, 'data', 'katran_rozetka.xml')
DROPS = os.path.join(BASE, 'data', 'katran_rozetka_drops.tsv')
MIN_MARGIN = 1.05          # щонайменше 5 % над закупівлею з ПДВ
MAX_PICTURES = 10
TITLE_MAX = 200


def fetch(url=None):
    url = url or os.getenv('KATRAN_FEED_URL_STOCK')
    if not url:
        raise SystemExit('KATRAN_FEED_URL_STOCK не заданий у .env')
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = [n for n in z.namelist() if n.lower().endswith('.xml')]
        if not names:
            raise SystemExit('у архіві немає XML')
        return ET.parse(z.open(names[0])).getroot()


def categories():
    """{katran_id: (rz_id, назва, комісія)} — з БД і з LLM-зіставлення."""
    from shared.utils.db import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, rozetka_category, rozetka_rz_id, commission_pct, '
                'name, parent_id FROM katran_categories')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    tree = {str(r['id']): dict(r) for r in rows}
    out, comm_by_rz = {}, {}
    for r in rows:
        if r['rozetka_rz_id']:
            rz = str(r['rozetka_rz_id'])
            out[str(r['id'])] = (rz, r['rozetka_category'],
                                 float(r['commission_pct'] or 0))
            comm_by_rz[rz] = float(r['commission_pct'] or 0)

    names = {}
    pj = os.path.join(BASE, 'docs', 'rozetka_categories_all.json')
    if os.path.exists(pj):
        names = {str(x['rz_id']): x['rz_name']
                 for x in json.load(open(pj, encoding='utf-8'))}
    # Канонічні назви категорій — з офіційного каталогу Rozetka. Інакше
    # назву в фіді задає перший товар, що туди потрапив: 06.10 категорія
    # rz 80137 підписалась як «Варильні поверхні», хоча насправді це
    # «Варильні поверхні та плити», і виглядало, ніби 39 плит лежать не там.
    # Rozetka читає rz_id, тож це був лише показ, але плутало перевірку.
    # Доповнення з LLM-зіставлення: лише ті, у кого є rz_id і яких ще немає.
    extra = os.path.join(BASE, 'data', 'katran_cat_map_llm.json')
    if names:
        out = {k: (rz, names.get(rz, nm), c) for k, (rz, nm, c) in out.items()}
    if os.path.exists(extra):
        for cid, v in json.load(open(extra, encoding='utf-8')).items():
            if v.get('rz_id') and cid not in out:
                rz = str(v['rz_id'])
                out[cid] = (rz, names.get(rz, tree.get(cid, {}).get('name') or ''),
                            comm_by_rz.get(rz, 19.44))   # невідома комісія — найбільша
    return out, tree


def top_section(cid, tree):
    x, seen, last = cid, set(), None
    while x and x in tree and x not in seen:
        seen.add(x)
        last = tree[x].get('name')
        x = tree[x].get('parent_id')
    return last


def num(t):
    try:
        return float((t or '0').replace(',', '.').strip())
    except (ValueError, AttributeError):
        return 0.0


def clean_name(s):
    s = re.sub(r'\s+', ' ', (s or '').strip())
    # Службові позначки постачальника на початку: «!Папір», «!Уцінка».
    return s.lstrip('!').strip()


def title(name, article):
    """Назва за формулою Rozetka: Тип Бренд Модель Колір Характеристики (Артикул).

    Джерело дає характеристики через «/»: «Блендер Amica BTM3011, 700Вт/
    Механічне керування/2 швидкості». Довідка Rozetka (title.txt) вимагає
    читабельний перелік, тому слеші стають комами. 28 % назв мали два і
    більше слешів — на це вказав і рецензент.

    Артикул у дужках наприкінці — теж вимога формули; він ще й рятує від
    однакових назв у різних модифікацій.
    """
    t = clean_name(name)
    # СЛЕШІ НЕ ЧІПАЄМО. 06.10 я замінював їх комами «для читабельності» —
    # і зламав коди моделей: «UFO ECO-EC/18» ставало «UFO ECO-EC, 18».
    # Слеш у джерелі буває і роздільником характеристик, і частиною
    # моделі, а відрізнити їх надійно не вийшло. Псувати модель гірше,
    # ніж лишити кому не там, тому лишаємо як є.
    t = re.sub(r'\s+', ' ', t).strip(' ,')
    if article and article.lower() not in t.lower():
        t = f'{t} ({article})'
    return t[:TITLE_MAX]


# Плита — не варильна поверхня. 06.10 у фіді було 39 окремостоячих плит,
# покладених у «Варильні поверхні»; на це вказав рецензент, і перевірка
# підтвердила. Правильна категорія існує — «Варильні поверхні та плити».
# 80137 офіційно зветься «Вбудовані варильні поверхні» — окремостояча
# плита туди не належить. У нашій БД ця категорія підписана «Варильні
# поверхні та плити», через що помилка й жила непоміченою. Правильна
# категорія для окремостоячих — 80122 «Кухонні плити».
STOVE_RZ = '80122'
STOVE_NAME = 'Кухонні плити'
STOVE_RE = re.compile(r'\b(плита|плити)\b', re.I)


def price_for(rrc, pdv, commission):
    """Ціна продажу. Ніколи не нижча за закупівлю — правило власника."""
    by_rrc = rrc * (1 + commission / 100) if rrc > 0 else 0
    floor = pdv * (1 + commission / 100) * MIN_MARGIN if pdv > 0 else 0
    best = max(by_rrc, floor)
    return int(math.ceil(best / 10) * 10) if best > 0 else 0


def build(section=None, out_file=OUT, limit=None):
    root = fetch()
    cats, tree = categories()
    stop = load_stop()
    items = list(root.find('products'))
    stats = collections.Counter()
    drops = []
    offers, used = [], {}
    seen = set()

    for p in items:
        def g(t):
            return (p.findtext(t) or '').strip()

        stats['усього в джерелі'] += 1
        art = g('artikul') or g('code')
        name = clean_name(g('name'))
        cid = g('categoryId')

        # 1. ЛИШЕ СКЛАД — точна рівність, не «починається з е»
        if g('stock') != 'есть':
            stats['не склад'] += 1
            drops.append((art, f"не склад: {g('stock')}", name))
            continue
        if section and top_section(cid, tree) != section:
            stats['інший розділ'] += 1
            continue
        if not name or len(name) < 3:
            stats['без назви'] += 1
            drops.append((art, 'без назви', name))
            continue
        if art in seen:
            stats['дублікат артикула'] += 1
            drops.append((art, 'дублікат', name))
            continue

        # 2. КАТЕГОРІЯ — без запасної
        if cid not in cats:
            stats['немає категорії Rozetka'] += 1
            drops.append((art, 'немає категорії Rozetka', name))
            continue
        rz, rz_name, commission = cats[cid]
        # Окремостояча плита у «Варильних поверхнях» — помилка довідника.
        if (STOVE_RE.search(name) and 'варильн' in (rz_name or '').lower()):
            rz, rz_name = STOVE_RZ, STOVE_NAME
            stats['плиту перенесено з варильних поверхонь'] += 1

        # 3. СТОП-БРЕНДИ
        vendor = g('vendor') or 'Без бренду'
        if vendor.lower() in ('no name', 'noname', 'no-name', 'unknown'):
            vendor = 'Без бренду'
        bad, why = banned(vendor, rz_name, stop)
        if bad:
            stats['стоп-бренд'] += 1
            drops.append((art, why, name))
            continue

        # 4. ЦІНА
        rrc, pdv = num(g('price_rrc')), num(g('price_pdv'))
        price = price_for(rrc, pdv, commission)
        if price <= 0:
            stats['без ціни'] += 1
            drops.append((art, 'без ціни', name))
            continue
        if pdv > 0 and price <= pdv:
            # Запобіжник: сюди не має потрапити жоден товар, але якщо
            # потрапить — краще втратити позицію, ніж гроші.
            stats['ціна нижча за закупівлю'] += 1
            drops.append((art, f'ціна {price} ≤ закупівля {pdv:.0f}', name))
            continue

        qty = int(num(g('stock_quantity')))
        if qty <= 0:
            stats['нуль на складі'] += 1
            drops.append((art, 'stock_quantity=0', name))
            continue

        pics = []
        el = p.find('images')
        if el is not None:
            for img in el.findall('image'):
                u = (img.text or img.get('url') or '').strip()
                if u.startswith('http') and len(u) < 500 and u not in pics:
                    pics.append(u)
        if not pics:
            stats['без фото'] += 1
            drops.append((art, 'без фото', name))
            continue

        seen.add(art)
        if rz not in used:
            used[rz] = (len(used) + 1, rz_name)
        desc = clean_name(g('description'))
        offers.append({'art': art, 'name': title(name, art), 'desc': desc, 'rz': rz,
                       'vendor': vendor, 'qty': qty, 'price': price,
                       'pics': pics[:MAX_PICTURES],
                       'warranty': g('warranty')})
        stats['у фіді'] += 1
        if limit and len(offers) >= limit:
            break

    head = ['<?xml version="1.0" encoding="UTF-8"?>',
            f'<yml_catalog date="{datetime.now():%Y-%m-%d %H:%M}">',
            '  <shop>',
            f'    <name>{xml_escape(SHOP_NAME)}</name>',
            f'    <company>{xml_escape(SHOP_COMPANY)}</company>',
            f'    <url>{xml_escape(SHOP_URL)}</url>',
            '    <currencies><currency id="UAH" rate="1"/></currencies>',
            '    <categories>']
    head += [f'      <category id="{i}" rz_id="{rz}">{xml_escape(nm or "")}</category>'
             for rz, (i, nm) in used.items()]
    head += ['    </categories>', '    <offers>']

    body = []
    for o in offers:
        body.append(f'      <offer id="{xml_escape(o["art"])}" available="true">')
        body.append(f'        <price>{o["price"]}</price>')
        body.append('        <currencyId>UAH</currencyId>')
        body.append(f'        <categoryId>{used[o["rz"]][0]}</categoryId>')
        body += [f'        <picture>{xml_escape(u)}</picture>' for u in o['pics']]
        body.append(f'        <vendor>{xml_escape(o["vendor"])}</vendor>')
        body.append(f'        <article>{xml_escape(o["art"])}</article>')
        body.append(f'        <stock_quantity>{o["qty"]}</stock_quantity>')
        body.append(f'        <name>{xml_escape(o["name"])}</name>')
        body.append(f'        <name_ua>{xml_escape(o["name"])}</name_ua>')
        d = o['desc'] or o['name']
        body.append(f'        <description><![CDATA[<p>{d}</p>]]></description>')
        body.append(f'        <description_ua><![CDATA[<p>{d}</p>]]></description_ua>')
        if o['warranty'] and o['warranty'] not in ('0', ''):
            body.append(f'        <param name="Гарантія">{xml_escape(o["warranty"])} міс</param>')
        body.append('      </offer>')

    tail = ['    </offers>', '  </shop>', '</yml_catalog>', '']
    tmp = out_file + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('\n'.join(head + body + tail))
    ET.parse(tmp)              # невалідний XML не має замінити робочий файл
    os.replace(tmp, out_file)

    with open(DROPS, 'w', encoding='utf-8') as f:
        f.write('article\treason\tname\n')
        for a, r, nm in sorted(drops, key=lambda x: (x[1], x[0])):
            f.write(f'{a}\t{r}\t{nm}\n')

    print(f'→ {out_file}')
    for k, v in stats.most_common():
        print(f'  {k:<28}{v:>6}')
    print(f'  категорій у фіді            {len(used):>6}')
    return stats, offers


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--section', help='лише один верхній розділ KATRAN')
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--limit', type=int)
    a = ap.parse_args()
    build(a.section, a.out, a.limit)
