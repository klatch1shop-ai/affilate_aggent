#!/usr/bin/env python3
"""Закупівельні ціни, мінімальна роздрібна й габарити з кабінету SexOpt.

Навіщо. У жодному з 13 вивантажень постачальника закупівельної ціни немає —
`price-retail.csv` містить ту саму роздрібну, що вже лежить у нас. Наша
маржа видима **лише в кабінеті після входу**, і досі всі розмови про
«позиції з доброю маржею» були здогадками.

Приклад різниці: SO1657 Tenga Egg Lotion — 429 грн у нашій базі (роздріб)
і 221.54 грн у кабінеті (наша ціна). Маржа 48%, і ми її не бачили.

Що дає сторінка товару, окрім ціни:
  • «Мин. розница (грн)» — нижня межа, під яку не можна ставити ціну;
  • габарити упаковки (довжина/ширина/висота) і тип пакування — те, чого
    нам бракувало для розрахунку доставки й що ми досі підставляли
    категорійними дефолтами;
  • наявність і країна походження.

Ключове спрощення: **адреса товару = артикул**. `sexopt.com.ua/so7321/`
відкриває картку SO7321 напряму, шукати не треба.

Запуск:
    python3 tools/sexopt_prices.py --limit 5      # проба
    python3 tools/sexopt_prices.py --all          # повний прогін
    python3 tools/sexopt_prices.py --report
"""
import argparse
import html
import os
import re
import sys
import time

import psycopg2.extras

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
from shared.utils.db import get_connection  # noqa: E402
from sexopt_portal import open_browser, do_login, URL  # noqa: E402

# Ціна лежить у мікророзмітці schema.org — надійніше за пошук «грн» у тексті:
# на сторінці кілька цін (гривні, долари, мін. роздріб), і текстовий regex
# у першій версії витягав «65 грн» із середини числа.
_PRICE = re.compile(r'itemprop="price"[^>]*>(?:<meta[^>]*>)?\s*([\d\s.,]+)<')
_ROW = re.compile(r'<th class="product-features-cell __h">([^<]+)</th>\s*'
                  r'<td class="product-features-cell">([^<]*)</td>')
_AVAIL = re.compile(r'productCard-availability[^>]*>([^<]{3,40})<')


def ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS sexopt_dropship_price (
        sku          TEXT PRIMARY KEY,
        our_price    NUMERIC,
        min_retail   NUMERIC,
        availability TEXT,
        pack_length  NUMERIC,
        pack_width   NUMERIC,
        pack_height  NUMERIC,
        pack_weight  NUMERIC,
        pack_type    TEXT,
        country      TEXT,
        features     JSONB,
        checked_at   TIMESTAMPTZ DEFAULT NOW())""")


def num(s):
    s = re.sub(r'[^\d.,]', '', s or '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None


def parse(page_html: str) -> dict:
    out = {'features': {}}
    m = _PRICE.search(page_html)
    if m:
        out['our_price'] = num(m.group(1))
    a = _AVAIL.search(page_html)
    if a:
        out['availability'] = html.unescape(a.group(1)).strip()
    for k, v in _ROW.findall(page_html):
        key = html.unescape(k).strip()
        val = html.unescape(v).strip()
        out['features'][key] = val
        low = key.lower()
        if 'розница' in low or 'розниця' in low:
            out['min_retail'] = num(val)
        elif low.startswith('упаковка'):
            # ТІЛЬКИ ключі, що починаються з «Упаковка:». Без цієї умови
            # «Общая длина (мм): 102» потрапляла в довжину упаковки й
            # робила мінівібратор метровим.
            if 'длина' in low or 'довжина' in low:
                out['pack_length'] = num(val)
            elif 'ширина' in low:
                out['pack_width'] = num(val)
            elif 'высота' in low or 'висота' in low:
                out['pack_height'] = num(val)
            elif 'масса' in low or 'маса' in low:
                out['pack_weight'] = num(val)
        elif 'тип упаковки' in low or 'тип пакування' in low:
            out['pack_type'] = val
        elif 'происхождения' in low or 'походження' in low:
            out['country'] = val
    return out


def targets(cur, limit, only_new):
    cur.execute("""SELECT p.sku FROM sexopt_products p
                   LEFT JOIN sexopt_dropship_price d ON d.sku = p.sku
                   WHERE p.available IS TRUE
                     AND (%s IS FALSE OR d.sku IS NULL)
                   ORDER BY p.sku""" + (f' LIMIT {int(limit)}' if limit else ''),
                (only_new,))
    return [r['sku'] for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--refresh', action='store_true',
                    help='перечитати вже зібрані, а не лише нові')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()

    if a.report:
        cur.execute("""SELECT count(*) n, count(min_retail) m,
                              round(avg(min_retail - our_price)) marg,
                              round(avg((min_retail - our_price) /
                                        NULLIF(min_retail, 0) * 100)) pct
                       FROM sexopt_dropship_price WHERE our_price > 0""")
        r = cur.fetchone()
        print(f"зібрано: {r['n']} | з мін. роздрібом: {r['m']} | "
              f"середня маржа: {r['marg']} грн ({r['pct']}%)")
        cur.execute("""SELECT sku, our_price, min_retail,
                              round((min_retail - our_price) /
                                    NULLIF(min_retail, 0) * 100) pct
                       FROM sexopt_dropship_price
                       WHERE min_retail > 0 AND our_price > 0
                       ORDER BY pct DESC NULLS LAST LIMIT 12""")
        print('\nнайбільша маржа:')
        for r in cur.fetchall():
            print(f"   {r['sku']:10} наша {r['our_price']:>9} → "
                  f"мін.роздріб {r['min_retail']:>9}  {r['pct']}%")
        return

    skus = targets(cur, a.limit or (None if a.all else 5), not a.refresh)
    print(f'до збору: {len(skus)}')
    done = fail = 0
    with open_browser() as br:
        page = br.new_page()
        page.set_default_timeout(45000)
        if not do_login(page):
            sys.exit('не вдалося увійти в кабінет постачальника')
        for i, sku in enumerate(skus, 1):
            try:
                page.goto(f'{URL}/{sku.lower()}/', wait_until='domcontentloaded')
                page.wait_for_timeout(1200)
                d = parse(page.content())
            except Exception as e:
                print(f'   {sku}: {type(e).__name__}')
                fail += 1
                continue
            if not d.get('our_price'):
                fail += 1
                continue
            cur.execute("""INSERT INTO sexopt_dropship_price
                (sku, our_price, min_retail, availability, pack_length,
                 pack_width, pack_height, pack_weight, pack_type, country,
                 features)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (sku) DO UPDATE SET our_price=EXCLUDED.our_price,
                  min_retail=EXCLUDED.min_retail,
                  availability=EXCLUDED.availability,
                  pack_length=EXCLUDED.pack_length, pack_width=EXCLUDED.pack_width,
                  pack_height=EXCLUDED.pack_height,
                  pack_weight=EXCLUDED.pack_weight, pack_type=EXCLUDED.pack_type,
                  country=EXCLUDED.country, features=EXCLUDED.features,
                  checked_at=NOW()""",
                        (sku, d.get('our_price'), d.get('min_retail'),
                         d.get('availability'), d.get('pack_length'),
                         d.get('pack_width'), d.get('pack_height'),
                         d.get('pack_weight'), d.get('pack_type'),
                         d.get('country'),
                         psycopg2.extras.Json(d['features'])))
            conn.commit()
            done += 1
            if i % 50 == 0:
                print(f'   {i}/{len(skus)}  зібрано {done}, невдач {fail}',
                      flush=True)
            time.sleep(0.4)
    print(f'\nзібрано: {done}, невдач: {fail}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
