#!/usr/bin/env python3
"""
tools/noire_epicentr_stock_feed.py
===================================
Фід Єпіцентру ТІЛЬКИ з ціною й наявністю — для автооновлення за посиланням.

НАВІЩО ОКРЕМИЙ ФАЙЛ. Повний фід не можна ставити в автооновлення: повторний
імпорт **стирає категорії й характеристики карток у статусі «Наповнення
контентом»**. Тобто щоденне автооновлення повним файлом знищувало б рівно ту
роботу, яку ми тижнями робимо — дозаповнення атрибутів.

Саме тому опублікований `noire_epicentr.xml` датований 05.08: його бояться
оновлювати, і ціни з наявністю в кабінеті місяць не рухались.

Цей файл містить лише те, що дозволено оновлювати щодня, за шаблоном довідки
«Як оновити ціну та наявність товару за допомогою імпорту (XML-файл)»:

    <offer id="артикул" available="true">
      <price>163</price>
      <availability>in_stock</availability>
    </offer>

Жодних характеристик, категорій, назв і описів — тому перезаписати ними
нічого не можна за побудовою, а не за уважністю.

    python3 tools/noire_epicentr_stock_feed.py -o output/noire_epicentr_stock.xml
"""
import os, sys, argparse, datetime
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.db import get_connection

# Дозволені значення наявності — з довідки Єпіцентру
IN, OUT = 'in_stock', 'out_of_stock'


def esc(x):
    return (str(x).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--out', required=True)
    # За замовчуванням беремо ВСІ артикули, а не лише наявні в кабінеті.
    # Єпіцентр просто ігнорує id, якого в нього немає, зате після кожного
    # нового завантаження асортименту файл не треба перегенеровувати з новим
    # фільтром — наявність одразу працює для всіх, включно з новими картками.
    ap.add_argument('--only-existing', metavar='JSON',
                    help='звузити до артикулів, які вже є в кабінеті '
                         '(зазвичай не потрібно)')
    a = ap.parse_args()

    conn = get_connection(); cur = conn.cursor()
    cur.execute("""select sku, price_retail, available, quantity
                   from sexopt_products where price_retail is not null""")
    rows = cur.fetchall()
    conn.close()

    keep = None
    if a.only_existing:
        import json
        keep = {(x.get('sku') or '').strip()
                for x in json.load(open(a.only_existing, encoding='utf-8'))}

    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<yml_catalog date="{now}">', '  <offers>']
    n = skipped = 0
    for r in rows:
        sku = (r['sku'] or '').strip()
        if not sku or (keep is not None and sku not in keep):
            skipped += 1
            continue
        avail = bool(r['available'])
        parts.append(f'    <offer id="{esc(sku)}" available="{str(avail).lower()}">')
        parts.append(f'      <price>{float(r["price_retail"]):.2f}</price>')
        parts.append(f'      <availability>{IN if avail else OUT}</availability>')
        parts.append('    </offer>')
        n += 1
    parts += ['  </offers>', '</yml_catalog>', '']
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))
    size = os.path.getsize(a.out) / 1024 / 1024
    print(f'офферів: {n} | пропущено (немає в кабінеті): {skipped}')
    print(f'файл: {a.out}  ({size:.1f} МБ)')
    print('\nЦе файл ТІЛЬКИ для «Імпорт → Автооновлення».')
    print('Повний фід у автооновлення ставити НЕ можна: він стирає')
    print('характеристики карток у статусі «Наповнення контентом».')


if __name__ == '__main__':
    main()
