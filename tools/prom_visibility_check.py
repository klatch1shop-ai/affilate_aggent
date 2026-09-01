#!/usr/bin/env python3
"""Перевірка реальної видимості наших карток у пошуку Prom.

Навіщо окремий інструмент, коли є prom_serp_baseline.py: той ходить усіма
запитами в ОДНОМУ браузері й одній сесії. Саме цей шаблон щойно дав
мовний баг у зборі тегів — Prom записав мову в сесію, і всі наступні
запити віддавались не тією мовою, а помилка мовчки потрапила у фід.
Доки не доведено протилежне, висновок «0 з 8 у видачі» треба вважати
таким, що міг постраждати від того самого класу проблеми.

Тому тут: окремий екземпляр браузера на КОЖЕН запит (свій профіль, свої
кукі, своя мова), запити по одному, з паузою. Дорожче в рази, але
перехресне забруднення виключене за конструкцією.

Порядок перевірки має значення:
  1) пошук за ВЛАСНИМ артикулом — якщо картки нема навіть за унікальним
     рядком, який більше ніде не зустрічається, це проблема видимості;
  2) пошук за точною назвою — відсіює випадок «артикул не індексується»;
  3) пошук за широкою фразою — тут відсутність нормальна, це конкуренція
     за релевантність, а не блокування.

Запуск:
    python3 tools/prom_visibility_check.py --n 8
    python3 tools/prom_visibility_check.py --sku SO2795,EGG-001L
"""
import argparse
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import psycopg2.extras
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

FEED = os.path.join(BASE_DIR, 'output', 'noire_prom.xml')
# Як нас видно покупцеві. У фіді <name>klatch1 shop</name>; у видачі Prom
# показує назву компанії, тож тримаємо кілька варіантів написання.
OURS = ('klatch', 'noire', 'клатч', 'нуар')
PAUSE = 6


def ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS prom_visibility (
        sku TEXT, mode TEXT, query TEXT, results INTEGER,
        found BOOLEAN, seller TEXT, checked_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (sku, mode, checked_at))""")


def sample(n, skus):
    """Беремо картки з фіду: артикул, назва, широка фраза з keywords."""
    root = ET.parse(FEED).getroot()
    out = []
    for o in root.findall('.//offer'):
        sku = o.findtext('vendorCode') or o.get('id')
        if skus and sku not in skus:
            continue
        kw = [x.strip() for x in (o.findtext('keywords_ua') or '').split(',')
              if x.strip()]
        # широка фраза — найкоротша, вона ж найзагальніша
        broad = min(kw, key=len) if kw else ''
        out.append({'sku': sku, 'name': o.findtext('name_ua') or '',
                    'broad': broad})
        if not skus and len(out) >= n:
            break
    if skus:
        return out
    # рівномірна вибірка по всьому фіду, а не перші n підряд
    allo = root.findall('.//offer')
    step = max(len(allo) // n, 1)
    out = []
    for o in allo[::step][:n]:
        sku = o.findtext('vendorCode') or o.get('id')
        kw = [x.strip() for x in (o.findtext('keywords_ua') or '').split(',')
              if x.strip()]
        out.append({'sku': sku, 'name': o.findtext('name_ua') or '',
                    'broad': min(kw, key=len) if kw else ''})
    return out


PAGES = 5          # 10 карток на сторінку — переглядаємо перші 50 позицій


def one_query(query: str, pages: int = PAGES) -> tuple:
    """Свіжий браузер на запит; повертає (переглянуто карток, позиція, стор.).

    Читаємо ім'я продавця з DOM (`data-qaid="company_name"`), а не з сирого
    HTML: у сирому його немає взагалі, і перша версія цієї перевірки через
    те відповідала «нас немає» на будь-який запит.

    Дивимось не лише першу сторінку: «немає в топ-10» і «немає в індексі» —
    різні діагнози, і саме їх треба розрізнити.
    """
    from camoufox.sync_api import Camoufox
    seen = 0
    with Camoufox(headless=True, humanize=True, geoip=True,
                  locale='uk-UA') as br:
        page = br.new_page()
        page.set_default_timeout(60000)
        for pg in range(1, pages + 1):
            url = ('https://prom.ua/ua/search?search_term='
                   + query.replace(' ', '%20')
                   + (f'&page={pg}' if pg > 1 else ''))
            page.goto(url, wait_until='domcontentloaded')
            page.wait_for_timeout(4500)
            page.mouse.wheel(0, 8000)
            page.wait_for_timeout(2000)
            blocks = page.locator('[data-qaid="product_block"]')
            n = blocks.count()
            if not n:
                break
            for i in range(n):
                b = blocks.nth(i)
                try:
                    loc = b.locator('[data-qaid="company_name"]')
                    comp = (loc.first.inner_text() or '').strip().lower() \
                        if loc.count() else ''
                except Exception:
                    comp = ''
                seen += 1
                if any(o in comp for o in OURS):
                    return seen, seen, pg
            if n < 10:
                break
    return seen, 0, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=8)
    ap.add_argument('--sku')
    ap.add_argument('--modes', default='article,name,broad')
    a = ap.parse_args()

    skus = set(a.sku.split(',')) if a.sku else None
    items = sample(a.n, skus)
    modes = a.modes.split(',')

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()

    print(f'перевіряємо {len(items)} SKU × {len(modes)} режимів, '
          f'свіжий браузер на кожен запит\n')
    tally = {m: [0, 0] for m in modes}
    for it in items:
        print(f"── {it['sku']}  {it['name'][:60]}")
        for mode in modes:
            q = {'article': it['sku'], 'name': it['name'][:70],
                 'broad': it['broad']}[mode]
            if not q:
                continue
            try:
                cards, pos, pg = one_query(q)
            except Exception as e:
                print(f'   {mode:8} ПОМИЛКА {type(e).__name__}')
                continue
            tally[mode][1] += 1
            tally[mode][0] += bool(pos)
            mark = (f'МИ НА {pos}-й позиції (стор. {pg})' if pos
                    else f'нас немає серед {cards}')
            print(f'   {mode:8} «{q[:40]}» → переглянуто {cards:3}, {mark}')
            cur.execute("""INSERT INTO prom_visibility
                (sku, mode, query, results, found, seller)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                        (it['sku'], mode, q, cards, bool(pos),
                         f'позиція {pos}' if pos else ''))
            conn.commit()
            time.sleep(PAUSE)

    print('\n── підсумок ──')
    for m in modes:
        ok, tot = tally[m]
        if tot:
            print(f'   {m:8} знайдено {ok}/{tot}')
    print('\nЧитати так: відсутність за АРТИКУЛОМ — реальна проблема '
          'видимості. Відсутність лише за широкою фразою — конкуренція '
          'за релевантність, це нормально.')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
