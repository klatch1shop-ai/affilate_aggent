#!/usr/bin/env python3
"""Юг-Контракт → XML-фід для Rozetka, з відбором за маржею.

ЧОМУ ЦЕ ПРОСТІШЕ, НІЖ KATRAN. Постачальник сам віддає `rozetka_code` —
готову категорію Rozetka для кожного товару (перевірено: 4627031 це
«Тарілки та салатники»). Зіставляти категорії LLM, як для KATRAN, не
треба: 196 із 200 товарів у пробі мали код.

ЕКОНОМІКА. Беремо лише те, що приносить гроші:

    комісія = ціна × ставка/100 × 1.08
    маржа   = ціна − закупівля − комісія − 35 (доставка)

Коефіцієнт 1.08 — не здогад: офіційна довідка Rozetka каже, що ПДВ 20 %
нараховується на 40 % тарифу (1 + 0.2×0.4 = 1.08). Перевірено на 9564
наших товарах — збіг до копійки.

СТАВКА КОМІСІЇ. Джерела за спаданням надійності:
  1. наші ж товари в тій категорії (`/items-commissions/search`) — факт;
  2. таблиця `rozetka_cpa_rates` — офіційний тариф, але лише 19 рядків;
  3. якщо ставки немає — товар НЕ потрапляє у фід. Вгадувати комісію
     означає вгадувати, чи продаємо ми в збиток.

    venv/bin/python tools/yug_rozetka_generator.py --маржа 40 --вихід /tmp/yug_rozetka.xml
"""
import argparse
import collections
import html
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

КАТАЛОГ = os.path.join(BASE, 'data', 'yug_catalog.json')
КОМІСІЇ = os.path.join(BASE, 'data', 'rozetka_commissions.json')
# «Доставка в магазини ROZETKA» (35 грн з продавця) НЕ активована —
# доставку Новою Поштою платить покупець, нам вона не коштує нічого.
# Коли опцію ввімкнуть, поставити 35 і перерахувати.
ДОСТАВКА = 0.0
КОЕФ = 1.08


def ставки_з_наших_товарів():
    """{category_id: ставка} — лише там, де всі наші товари мають однакову."""
    якщо = collections.defaultdict(set)
    for x in json.load(open(КОМІСІЇ, encoding='utf-8')):
        if x.get('catalog_id') and x.get('commission') is not None:
            якщо[int(x['catalog_id'])].add(float(x['commission']))
    return {c: list(v)[0] for c, v in якщо.items() if len(v) == 1}


def ставки_з_тарифів():
    try:
        from shared.utils.db import get_connection
        cur = get_connection().cursor()
        cur.execute('select category_id, base_commission from rozetka_cpa_rates '
                    'where base_commission is not null')
        return {int(r['category_id']): float(r['base_commission'])
                for r in cur.fetchall()}
    except Exception as e:
        print(f'тарифи з бази недоступні: {e}', file=sys.stderr)
        return {}


def товари():
    d = json.load(open(КАТАЛОГ, encoding='utf-8'))
    out = []
    for cid, список in (d.get('товари') or {}).items():
        out += список
    return out


НАЗВИ = os.path.join(BASE, 'data', 'rozetka_category_names.json')


def назви_категорій(ids):
    """{id: назва} — з кешу, бракуючі добираємо з API Rozetka.

    Валідатор вимагає, щоб КОЖНА категорія, вжита в offer, була оголошена
    в блоці <categories>. Без цього фід не приймається — 5594 помилки на
    першому прогоні були саме про це.
    """
    кеш = json.load(open(НАЗВИ, encoding='utf-8')) if os.path.exists(НАЗВИ) else {}
    треба = [str(i) for i in ids if str(i) not in кеш]
    if треба:
        import requests
        sys.path.insert(0, BASE)
        from agents.orders import rozetka_order_agent as RZ
        h = {'Authorization': f'Bearer {RZ.get_token()}', 'Accept': 'application/json'}
        for cid in треба:
            try:
                r = requests.get('https://api-seller.rozetka.com.ua/market-categories/search',
                                 headers=h, params={'id': cid}, timeout=40)
                m = ((r.json().get('content') or {}).get('marketCategorys') or [{}])[0]
                кеш[cid] = m.get('name') or f'Категорія {cid}'
            except Exception:
                кеш[cid] = f'Категорія {cid}'
        with open(НАЗВИ, 'w', encoding='utf-8') as f:
            json.dump(кеш, f, ensure_ascii=False)
    return {str(i): кеш.get(str(i), f'Категорія {i}') for i in ids}


ХАРАКТЕРИСТИКИ = os.path.join(BASE, 'data', 'rozetka_category_options.json')


ФОТОАУДИТ = os.path.join(BASE, 'docs', 'yug_photo_audit.tsv')
СТОП = os.path.join(BASE, 'data', 'rozetka_stop_from_validator.json')


def стоп_переліки():
    """({категорії}, {бренди}) — з відповіді ОФІЦІЙНОГО валідатора Rozetka.

    Це найточніше джерело: не наш переказ таблиці стоп-брендів, а те, що
    Rozetka сказала про цей самий фід. 17.10 вона позначила 584 товари в
    27 стоп-категоріях і 314 товарів 8 стоп-брендів — наш фільтр цього не
    бачив, бо до фіду ЮК я його просто не підключив.

    Перелік поповнюється з кожного нового звіту валідатора.
    """
    if not os.path.exists(СТОП):
        return set(), set()
    d = json.load(open(СТОП, encoding='utf-8'))
    return ({к.strip().lower() for к in d.get('категорії', [])},
            {б.strip().upper() for б in d.get('бренди', [])})


def без_посилань(текст):
    """Опис без URL: Rozetka вважає посилання в описі ПОМИЛКОЮ.

    У звіті 17.10 це була єдина справжня помилка — 4 товари, де
    постачальник лишив адресу сайта в тексті.
    """
    t = re.sub(r'https?://\S+', '', текст or '')
    t = re.sub(r'\bwww\.\S+', '', t)
    t = re.sub(r'\S+\.(com|ua|net|org)(/\S*)?', '', t)
    return re.sub(r'\s{2,}', ' ', t).strip()


def фото_непридатні():
    """Артикули, де ГОЛОВНЕ фото не проходить вимоги Rozetka.

    Беремо з `rozetka_photo_audit.py`: 400×400 — мінімум, і 669 товарів
    постачальника його не мають. Подавати їх означає гарантовану відмову,
    а відмова після подачі не виправляється без повторної модерації
    (SKILL-36). Хибні спрацювання евристики «витягнуте фото» не
    відкидаємо: перевірив очима — там звичайні фото товарів.
    """
    if not os.path.exists(ФОТОАУДИТ):
        return set()
    погані = set()
    with open(ФОТОАУДИТ, encoding='utf-8') as f:
        next(f, None)
        for рядок in f:
            ч = рядок.rstrip('\n').split('\t')
            if len(ч) < 5:
                continue
            проблема = ч[4]
            if 'ГОЛОВНЕ' in проблема and ('менше' in проблема or 'не завантажується' in проблема):
                погані.add(ч[0])
    return погані


def довідник_характеристик():
    return (json.load(open(ХАРАКТЕРИСТИКИ, encoding='utf-8'))
            if os.path.exists(ХАРАКТЕРИСТИКИ) else {})


def факт_опис(t):
    """Опис із фактів, коли постачальник його не дав.

    Не вигадуємо властивостей товару: беремо лише те, що вже є в картці —
    назва, бренд, країна, гарантія, вага. Порожній опис це відмова
    модерації, а вигаданий — гірше за відмову.
    """
    ч = [t['назва']]
    if t.get('бренд'):
        ч.append(f"Бренд: {t['бренд']}.")
    if t.get('країна'):
        ч.append(f"Країна-виробник: {t['країна']}.")
    if t.get('гарантія') and str(t['гарантія']).strip() not in ('-', ''):
        ч.append(f"Гарантія: {t['гарантія']}.")
    if t.get('вага'):
        ч.append(f"Вага: {t['вага']} кг.")
    if t.get('штрихкод'):
        ч.append(f"Штрихкод: {t['штрихкод']}.")
    return ' '.join(str(x) for x in ч)


def характеристики(t, довідка):
    """[(назва, значення)] — лише ті, що є в довіднику ЦІЄЇ категорії.

    Валідатор хоче щонайменше три. Беремо виключно факти з даних
    постачальника й лише ті назви параметрів, які Rozetka справді
    очікує в цій категорії: чужа назва параметра однаково буде
    проігнорована, а вигадане значення — причина відмови.
    """
    якщо_є = {(v.get('назва') or '').strip().lower() for v in (довідка or {}).values()}
    пари = []
    # Назви беремо ТАКІ, ЯК У ДОВІДНИКУ Rozetka, а не як зручно нам:
    # «Країна-виробник товару», а не «Країна-виробник»; «EAN», а не
    # «Штрихкод»; «Код виробника», а не «Модель». Перший прогін дав 4104
    # попередження саме тому, що я вигадав назви з голови.
    кандидати = [('Гарантія', t.get('гарантія')),
                 ('EAN', t.get('штрихкод')),
                 ('Країна-виробник товару', t.get('країна')),
                 ('Країна реєстрації бренду', t.get('країна')),
                 ('Код виробника', t.get('артикул')),
                 ('Вага', f"{t.get('вага')} кг" if t.get('вага') else None),
                 ('Вага в упаковці', f"{t.get('вага')} кг" if t.get('вага') else None),
                 ('Бренд', t.get('бренд')),
                 ("Об'єм", t.get('обʼєм'))]
    бачили = set()
    for імʼя, знач in кандидати:
        if not знач or str(знач).strip() in ('-', '0', 'None'):
            continue
        if імʼя.lower() in бачили:
            continue
        if якщо_є and імʼя.lower() not in якщо_є:
            continue
        бачили.add(імʼя.lower())
        пари.append((імʼя, знач))
    return пари


def ціна_для(закуп, ставка, маржа):
    дільник = 1 - ставка * КОЕФ / 100
    return (закуп + ДОСТАВКА + маржа) / дільник if дільник > 0 else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--маржа', type=float, default=40.0)
    ap.add_argument('--усе', action='store_true', dest='усе',
                    help='повний фід постачальника: без відбору за маржею. '
                         'Маржа лишається в CSV як довідка, а рішення, що '
                         'продавати, ухвалює власник, а не генератор.')
    ap.add_argument('--вихід', default='/tmp/yug_rozetka.xml')
    ap.add_argument('--звіт', default=os.path.join(BASE, 'exports', 'yug_відбір.csv'))
    a = ap.parse_args()

    наші, тарифи = ставки_з_наших_товарів(), ставки_з_тарифів()
    назви_кеш = (json.load(open(НАЗВИ, encoding='utf-8'))
                 if os.path.exists(НАЗВИ) else {})
    from tools.rozetka_tariffs import зчитати, ставка as тариф_ставка, OUT as ТАРИФИ
    сітка = json.load(open(ТАРИФИ, encoding='utf-8')) if os.path.exists(ТАРИФИ) else {}
    print(f'ставок із наших товарів: {len(наші)} · тарифна сітка: {len(сітка)} категорій')

    узяті, причини = [], collections.Counter()
    вже_взяті = set()
    без_фото = фото_непридатні()
    стоп_кат, стоп_бренд = стоп_переліки()
    if стоп_кат or стоп_бренд:
        print(f'стоп-переліки валідатора: категорій {len(стоп_кат)}, '
              f'брендів {len(стоп_бренд)}')
    if без_фото:
        print(f'аудит фото: {len(без_фото)} артикулів із непридатним головним фото')
    for t in товари():
        rz = t.get('rozetka_code')
        закуп = t.get('price_uah') or 0
        ррц = t.get('price_rrc') or 0
        наявн = t.get('availability') or 0
        if not rz:
            причини['немає категорії Rozetka'] += 1; continue
        if not закуп or not ррц:
            причини['немає ціни'] += 1; continue
        if наявн <= 0:
            причини['немає в наявності'] += 1; continue
        rz = int(rz)
        # Стоп-переліки — з відповіді офіційного валідатора на цей самий
        # фід. 584 товари в стоп-категоріях і 314 стоп-брендів пройшли б
        # у подачу, бо фільтр до генератора ЮК просто не був підключений.
        назва_кат = (назви_кеш.get(str(rz)) or '').strip().lower()
        if назва_кат and назва_кат in стоп_кат:
            причини['стоп-категорія Rozetka'] += 1
            continue
        if (t.get('brand_name') or '').strip().upper() in стоп_бренд:
            причини['стоп-бренд Rozetka'] += 1
            continue
        # Порядок: офіційна сітка (вона знає бренд і ціновий діапазон),
        # далі наші ж продані товари, далі стара таблиця.
        ставка, _чому = тариф_ставка(сітка, rz, ррц, t.get('brand_name')) if сітка else (None, '')
        if ставка is None:
            ставка = наші.get(rz, тарифи.get(rz))
        if ставка is None:
            причини['невідома комісія — свідомо пропускаємо'] += 1; continue
        # Націнка понад 3× — ознака або помилки в даних, або ринку, якого
        # ми не розуміємо. У пробі такі позиції виявились запчастинами до
        # професійного обладнання: термістор Konica за 100 грн із РРЦ 4941.
        # Публікувати таке наосліп не можна, тому відкладаємо на перевірку.
        if not a.усе and ррц / закуп > 3:
            причини['націнка понад 3× — перевірити вручну'] += 1
            continue
        маржа_ррц = ррц - закуп - ррц * ставка * КОЕФ / 100 - ДОСТАВКА
        if not a.усе and маржа_ррц < a.маржа:
            причини[f'маржа за РРЦ менша за {a.маржа:.0f}'] += 1; continue
        # Порядок саме такий: `origin_img_url` це повнорозмірне фото
        # (перевірено: 577×507), `bigimg` — лише 200×200, `smallimg` —
        # 80×80. Rozetka вимагає від 400×400, тож перший прогін дав 4044
        # замалих головних фото з 4045 — тобто фід відхилили б цілком.
        фото = t.get('origin_img_url') or t.get('bigimg') or t.get('smallimg')
        if not фото:
            причини['немає фото — Rozetka вимагає хоча б одне'] += 1
            continue
        if str(t.get('artikul')) in без_фото:
            причини['головне фото менше 400 px або не вантажиться'] += 1
            continue
        # Той самий товар трапляється у кількох категоріях постачальника,
        # і в фіді це дає дублікати offer id — 469 помилок валідатора.
        ключ = str(t.get('product_id') or t.get('artikul'))
        if ключ in вже_взяті:
            причини['дублікат товару в кількох категоріях'] += 1
            continue
        вже_взяті.add(ключ)
        опис = (t.get('descr_typhoon') or '').strip()
        узяті.append({'id': t.get('product_id'), 'артикул': t.get('artikul'), 'назва': t.get('name_ukr') or t.get('name'),
                      'бренд': t.get('brand_name'), 'категорія_rz': rz,
                      'закупівля': закуп, 'ррц': ррц, 'ставка': ставка,
                      'маржа_за_ррц': round(маржа_ррц, 2),
                      'ціна_для_маржі': round(ціна_для(закуп, ставка, a.маржа), 2),
                      'наявність': наявн, 'штрихкод': t.get('barcode'),
                      'фото': фото,
                      'опис': опис, 'країна': t.get('country'),
                      'вага': t.get('weight'), 'гарантія': t.get('warranty'),
                      'обʼєм': t.get('volume'), 'модель': t.get('model'),
                      'фото_всі': [u for u in (t.get('origin_img_url'),) if u]})

    print(f'\nпідходить у фід: {len(узяті)}')
    for к, n in причини.most_common():
        print(f'  відсіяно — {к}: {n}')

    if узяті:
        import csv
        os.makedirs(os.path.dirname(a.звіт), exist_ok=True)
        with open(a.звіт, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(узяті[0])); w.writeheader(); w.writerows(узяті)
        назви = назви_категорій(sorted({t['категорія_rz'] for t in узяті}))
        import datetime
        with open(a.вихід, 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                    f'<yml_catalog date="{datetime.datetime.now():%Y-%m-%d %H:%M}">\n'
                    ' <shop>\n'
                    '  <name>klatch1 shop</name>\n'
                    '  <company>FOP Oliinyk Serhii</company>\n'
                    '  <url>https://rozetka.com.ua/</url>\n'
                    '  <currencies><currency id="UAH" rate="1"/></currencies>\n'
                    '  <categories>\n')
            for cid in назви:
                f.write(f'   <category id="{cid}">'
                        f'{html.escape(назви[cid], quote=True)}</category>\n')
            f.write('  </categories>\n  <offers>\n')
            довідник = довідник_характеристик()
            назви_зайняті = collections.Counter()
            for t in узяті:
                e = lambda s: html.escape(str(s or ''), quote=True)
                назва = t['назва']
                # Rozetka вимагає унікальну назву на кожен offer: 476
                # попереджень були про модифікації одного товару (ножі
                # різної довжини) з однаковою назвою. Різницю бере з
                # артикула — він у постачальника й відрізняє модифікації.
                назви_зайняті[назва] += 1
                if назви_зайняті[назва] > 1 and t['артикул']:
                    назва = f"{назва} ({t['артикул']})"
                опис = без_посилань(t['опис']) or факт_опис(t)
                парами = характеристики(t, довідник.get(str(t['категорія_rz'])))
                f.write(f'   <offer id="{e(t["id"] or t["артикул"])}" available="true">\n'
                        f'    <price>{t["ррц"]:.0f}</price>\n'
                        f'    <currencyId>UAH</currencyId>\n'
                        f'    <categoryId>{t["категорія_rz"]}</categoryId>\n')
                for u in t['фото_всі'][:5]:
                    f.write(f'    <picture>{e(u)}</picture>\n')
                f.write(f'    <vendor>{e(t["бренд"])}</vendor>\n'
                        f'    <article>{e(t["артикул"])}</article>\n'
                        f'    <barcode>{e(t["штрихкод"])}</barcode>\n'
                        f'    <stock_quantity>{t["наявність"]}</stock_quantity>\n'
                        f'    <name>{e(назва)}</name>\n'
                        f'    <name_ua>{e(назва)}</name_ua>\n'
                        f'    <description><![CDATA[{опис}]]></description>\n'
                        f'    <description_ua><![CDATA[{опис}]]></description_ua>\n')
                for імʼя, значення in парами:
                    f.write(f'    <param name="{e(імʼя)}">{e(значення)}</param>\n')
                f.write('   </offer>\n')
            f.write('  </offers>\n </shop>\n</yml_catalog>\n')
        print(f'\n→ {a.вихід}\n→ {a.звіт}')


if __name__ == '__main__':
    main()
