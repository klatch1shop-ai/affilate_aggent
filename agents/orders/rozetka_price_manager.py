"""
agents/orders/rozetka_price_manager.py
=======================================
Управління цінами Розетки через XML + CSV.

РЕЖИМ 1: python3 agents/orders/rozetka_price_manager.py --generate
  - Питає корекцію % від РРЦ
  - Читає живий фід Carvol (або data/carvol_feed.xml якщо є)
  - Зберігає data/rozetka_prices.csv

РЕЖИМ 2: python3 agents/orders/rozetka_price_manager.py --apply
  - Читає data/rozetka_prices.csv (може бути відредагований вручну)
  - Оновлює data/carvol_rozetka.xml (тег <price> по <article>)
  - Git commit + push
"""

import os, sys, csv, math, argparse, subprocess
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / '.env')

CARVOL_FEED = (
    'https://carvol.prom.ua/rozetka_feed.xml'
    '?rozetka_hash_tag=2251d0779efad97117ac08d7efd82c2f'
    '&product_ids=&label_ids=28618299&languages=uk%2Cru&group_ids='
)
XML_PATH   = BASE_DIR / 'data' / 'carvol_rozetka.xml'
CSV_PATH   = BASE_DIR / 'data' / 'rozetka_prices.csv'
FEED_CACHE = BASE_DIR / 'data' / 'carvol_feed.xml'
REPO_PATH  = str(BASE_DIR)

# Комісії Розетки по categoryId (ступінчасті: sell_price тир → rate)
CPA_RULES = {
    '1':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '2':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '3':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '4':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '5':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '6':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '7':  [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '8':  [(0,2999,0.13),(3000,9999,0.07),(10000,19999,0.05),(20000,9e9,0.03)],
    '9':  [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '10': [(0,2999,0.13),(3000,9999,0.07),(10000,19999,0.05),(20000,9e9,0.03)],
    '12': [(0,2999,0.13),(3000,9999,0.07),(10000,19999,0.05),(20000,9e9,0.03)],
    '14': [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '15': [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '16': [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
}


def calc_sell_price(rrc: float, cat_id: str) -> tuple:
    """
    Gross-up: sell = ceil(rrc / (1 - rate) / 10) * 10.
    Tier-crossing: якщо breakeven виходить за межі тира — переходимо до наступного.
    Повертає (sell_price, commission_rate).
    """
    rules = sorted(CPA_RULES.get(str(cat_id), [(0, 9e9, 0.18)]), key=lambda x: x[0])
    for low, high, rate in rules:
        breakeven = math.ceil(rrc / (1 - rate) / 10) * 10
        if breakeven <= high:
            sell = max(breakeven, math.ceil(low / 10) * 10)
            return sell, rate
    _, _, rate = rules[-1]
    return math.ceil(rrc / (1 - rate) / 10) * 10, rate


def load_xml_cat_map() -> dict:
    """Повертає {article: cat_id} з carvol_rozetka.xml."""
    if not XML_PATH.exists():
        print(f'[warn] {XML_PATH} не знайдено — категорії за замовчуванням 1')
        return {}
    tree = ET.parse(XML_PATH)
    root = tree.getroot()
    shop = root.find('shop')
    if shop is None:
        shop = root
    offers_el = shop.find('offers')
    if offers_el is None:
        offers_el = root
    result = {}
    for offer in offers_el.findall('offer'):
        art_el = offer.find('article')
        cat_el = offer.find('categoryId')
        if art_el is not None and art_el.text:
            art = art_el.text.strip()
            cat = (cat_el.text or '1').strip() if cat_el is not None else '1'
            result[art] = cat
    print(f'XML cat_map: {len(result)} артикулів')
    return result


def fetch_feed() -> dict:
    """Повертає {article: rrc} з фіду (кеш або живий)."""
    if FEED_CACHE.exists():
        print(f'Читаємо кешований фід: {FEED_CACHE}')
        content = FEED_CACHE.read_bytes()
    else:
        print('Завантажуємо живий фід Carvol...')
        r = requests.get(CARVOL_FEED, timeout=120)
        content = r.content

    root = ET.fromstring(content)
    shop = root.find('shop')
    if shop is None:
        shop = root
    offers_el = shop.find('offers')
    if offers_el is None:
        offers_el = root

    feed = {}
    for offer in offers_el.findall('offer'):
        art_el   = offer.find('article')
        price_el = offer.find('price')
        if art_el is None or not art_el.text:
            continue
        art   = art_el.text.strip()
        price = float(price_el.text or 0) if price_el is not None else 0.0
        if art and price > 0:
            feed[art] = price

    print(f'Фід: {len(feed)} товарів з ціною')
    return feed


def cmd_generate():
    raw = input('РРЦ корекція % (+ або -, Enter = 0): ').strip()
    try:
        pct = float(raw) if raw else 0.0
    except ValueError:
        print(f'Некоректне значення "{raw}" → використовую 0%')
        pct = 0.0

    print(f'Корекція: {pct:+.1f}%\n')

    feed    = fetch_feed()
    cat_map = load_xml_cat_map()

    rows = []
    for article, rrc in feed.items():
        cat_id       = cat_map.get(article, '1')
        rrc_adjusted = rrc * (1 + pct / 100)
        sell_price, rate = calc_sell_price(rrc_adjusted, cat_id)
        commission   = round(sell_price * rate, 2)
        margin       = round(sell_price - commission - rrc, 2)
        rows.append({
            'article':         article,
            'rrc':             rrc,
            'rrc_adjusted':    round(rrc_adjusted, 2),
            'sell_price':      int(sell_price),
            'commission_rate': rate,
            'commission':      commission,
            'margin_vs_rrc':   margin,
        })

    rows.sort(key=lambda x: x['sell_price'], reverse=True)

    fields = ['article', 'rrc', 'rrc_adjusted', 'sell_price',
              'commission_rate', 'commission', 'margin_vs_rrc']
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f'\nЗбережено: {CSV_PATH}  ({len(rows)} рядків)')
    print(f'\n{"Артикул":<30} {"РРЦ":>8} {"Корр":>8} {"Продаж":>8} {"Ставка":>7} {"Комісія":>9} {"Маржа":>9}')
    print('─' * 86)
    for r in rows[:10]:
        sign = '+' if r['margin_vs_rrc'] >= 0 else ''
        print(f'{r["article"][:29]:<30} {r["rrc"]:>8.0f} {r["rrc_adjusted"]:>8.0f} '
              f'{r["sell_price"]:>8d} {r["commission_rate"]*100:>6.0f}%  '
              f'{r["commission"]:>9.0f} {sign}{r["margin_vs_rrc"]:>8.0f}')
    if len(rows) > 10:
        print(f'  … ще {len(rows) - 10} рядків')

    neg   = sum(1 for r in rows if r['margin_vs_rrc'] < 0)
    avg_m = sum(r['margin_vs_rrc'] for r in rows) / len(rows) if rows else 0
    print(f'\nСтатистика: всього {len(rows)}, нижче РРЦ: {neg}, середня маржа: {avg_m:+.0f} грн')
    print(f'\nВідредагуй sell_price у CSV і запусти --apply щоб оновити XML.')


def cmd_apply():
    if not CSV_PATH.exists():
        sys.exit(f'Файл не знайдено: {CSV_PATH}')
    if not XML_PATH.exists():
        sys.exit(f'XML не знайдено: {XML_PATH}')

    prices: dict[str, int] = {}
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                prices[row['article']] = int(float(row['sell_price']))
            except (KeyError, ValueError):
                pass
    print(f'CSV: {len(prices)} цін')

    tree = ET.parse(XML_PATH)
    root = tree.getroot()
    root.set('date', datetime.now().strftime('%Y-%m-%d %H:%M'))
    shop = root.find('shop')
    if shop is None:
        shop = root
    offers_el = shop.find('offers')
    if offers_el is None:
        offers_el = root

    updated, not_found, changed, examples = 0, 0, 0, []

    for offer in offers_el.findall('offer'):
        art_el = offer.find('article')
        if art_el is None or not art_el.text:
            continue
        article   = art_el.text.strip()
        new_price = prices.get(article)

        if new_price is None:
            not_found += 1
            continue

        price_el = offer.find('price')
        if price_el is None:
            continue

        old_price_str = price_el.text or '0'
        try:
            old_price = int(float(old_price_str))
        except ValueError:
            old_price = 0

        price_el.text = str(new_price)
        updated += 1
        if old_price != new_price:
            changed += 1
            if len(examples) < 12:
                examples.append((article, old_price, new_price))

    tree.write(str(XML_PATH), encoding='unicode', xml_declaration=False)
    with open(XML_PATH, 'r+', encoding='utf-8') as f:
        content = f.read()
        f.seek(0)
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + content)

    print(f'\nОновлено: {updated}, змінилось цін: {changed}, не знайдено: {not_found}')

    if examples:
        print(f'\n{"Артикул":<30} {"Стара":>8} {"Нова":>8} {"Різниця":>9}')
        print('─' * 60)
        for art, old, new in examples:
            diff = new - old
            sign = '+' if diff >= 0 else ''
            print(f'{art[:29]:<30} {old:>8d} {new:>8d} {sign}{diff:>8d}')

    # git commit + push
    ts  = datetime.now().strftime('%Y-%m-%d %H:%M')
    msg = f'prices: rozetka apply {ts}'
    print(f'\nGit: {msg}')
    for cmd in [
        ['git', 'add', 'data/carvol_rozetka.xml', 'data/rozetka_prices.csv'],
        ['git', 'commit', '-m', msg],
        ['git', 'pull', '--rebase'],
        ['git', 'push'],
    ]:
        r = subprocess.run(cmd, cwd=REPO_PATH, capture_output=True, text=True)
        if r.returncode != 0:
            if 'nothing to commit' in r.stdout + r.stderr:
                print('Git: немає змін')
                return
            print(f'Git {cmd[1]} error: {r.stderr[:200]}')
            return
    print('Git push ✅')


def main():
    parser = argparse.ArgumentParser(description='Rozetka Price Manager')
    parser.add_argument('--generate', action='store_true',
                        help='Генерувати data/rozetka_prices.csv з живого фіду')
    parser.add_argument('--apply', action='store_true',
                        help='Застосувати ціни з CSV → оновити XML + git push')
    args = parser.parse_args()

    if args.generate:
        cmd_generate()
    elif args.apply:
        cmd_apply()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
