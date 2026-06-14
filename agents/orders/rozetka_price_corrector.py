"""
agents/orders/rozetka_price_corrector.py
==========================================
Читає data/margin_analysis_6k.csv і оновлює ціни на Rozetka через API.

Використання:
  python3 agents/orders/rozetka_price_corrector.py --dry-run   # показати без змін
  python3 agents/orders/rozetka_price_corrector.py             # застосувати

API:
  GET  /items/search?article={article}          → owox_id
  PUT  /items/update-price-stock/{owox_id}      → оновити ціну
"""

import os, sys, csv, time, argparse
import requests
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / '.env')

API_BASE  = 'https://api-seller.rozetka.com.ua'
TOKEN     = os.getenv('ROZETKA_API_TOKEN', '')
CSV_PATH  = BASE_DIR / 'data' / 'margin_analysis_6k.csv'
XML_PATH  = BASE_DIR / 'data' / 'carvol_rozetka.xml'

HEADERS = {
    'Authorization': f'Bearer {TOKEN}',
    'Content-Type': 'application/json',
}


def api(method, path, **kwargs):
    url = API_BASE + path
    r = getattr(requests, method)(url, headers=HEADERS, verify=False, timeout=15, **kwargs)
    return r.status_code, r.json() if r.content else {}


def get_owox_id(article: str) -> str | None:
    """Знаходить owox_id товару за артикулом."""
    status, data = api('get', f'/items/search?article={requests.utils.quote(article)}')
    if status != 200:
        return None
    items = data.get('content', {}).get('items', [])
    if not items:
        return None
    return str(items[0].get('id') or items[0].get('owox_id') or '')


def update_price(owox_id: str, price: float) -> bool:
    """Оновлює ціну товару."""
    status, data = api('put', f'/items/update-price-stock/{owox_id}',
                       json={'price': price})
    return status == 200 and data.get('success', False)


def load_current_prices() -> dict:
    """Читає поточні ціни з Rozetka XML {article: price}."""
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(XML_PATH)
        root = tree.getroot()
        shop = root.find('shop')
        offers_el = (shop.find('offers') if shop is not None else None) or root.find('offers') or root
        prices = {}
        for offer in offers_el.findall('offer'):
            art = None
            for tag in ('vendorCode', 'article'):
                el = offer.find(tag)
                if el is not None and el.text:
                    art = el.text.strip(); break
            pe = offer.find('price')
            if art and pe is not None and pe.text:
                try: prices[art] = float(pe.text.strip())
                except: pass
        return prices
    except Exception as e:
        print(f'[warn] Не вдалось прочитати XML: {e}')
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Показати зміни без застосування')
    parser.add_argument('--limit', type=int, default=0, help='Ліміт оновлень (0=всі)')
    parser.add_argument('--min-diff', type=float, default=10, help='Мін. різниця цін для оновлення (грн)')
    args = parser.parse_args()

    if not TOKEN:
        sys.exit('ROZETKA_API_TOKEN не встановлено в .env')

    if not CSV_PATH.exists():
        sys.exit(f'Файл не знайдено: {CSV_PATH}')

    # Поточні ціни з XML (швидка перевірка без API)
    current_prices = load_current_prices()
    print(f'Поточні ціни з XML: {len(current_prices)} артикулів')

    # Читаємо CSV
    rows = []
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            rows.append(row)
    print(f'CSV: {len(rows)} рядків')

    # Знаходимо товари де ціна відрізняється
    to_update = []
    for row in rows:
        article = row['article']
        csv_price = float(row['sell_price'])
        xml_price = current_prices.get(article)
        if xml_price is None:
            continue
        if abs(csv_price - xml_price) > args.min_diff:
            to_update.append({
                'article': article,
                'csv_price': csv_price,
                'xml_price': xml_price,
                'diff': csv_price - xml_price,
                'margin': float(row['margin_uah']),
            })

    to_update.sort(key=lambda x: abs(x['diff']), reverse=True)
    if args.limit:
        to_update = to_update[:args.limit]

    print(f'\nПотребують оновлення: {len(to_update)} товарів')
    print(f'{"Артикул":<28} {"XML_ціна":>10} {"CSV_ціна":>10} {"Різниця":>10} {"Маржа":>10}')
    print('-' * 72)
    for item in to_update[:20]:
        print(f'{item["article"][:27]:<28} {item["xml_price"]:>10.0f} {item["csv_price"]:>10.0f} '
              f'{item["diff"]:>+10.0f} {item["margin"]:>+10.0f}')
    if len(to_update) > 20:
        print(f'  ... та ще {len(to_update) - 20}')

    if args.dry_run:
        print('\n[dry-run] Зміни не застосовано.')
        return

    if not to_update:
        print('\nНемає товарів для оновлення.')
        return

    print(f'\nОновлюємо {len(to_update)} цін через Rozetka API...')
    ok, fail, skip = 0, 0, 0

    for i, item in enumerate(to_update, 1):
        article = item['article']
        new_price = item['csv_price']

        owox_id = get_owox_id(article)
        if not owox_id:
            print(f'  [{i}/{len(to_update)}] {article}: owox_id не знайдено — пропуск')
            skip += 1
            time.sleep(0.3)
            continue

        success = update_price(owox_id, new_price)
        status = '✅' if success else '❌'
        print(f'  [{i}/{len(to_update)}] {article} owox={owox_id}: {item["xml_price"]:.0f}→{new_price:.0f} {status}')
        if success:
            ok += 1
        else:
            fail += 1
        time.sleep(0.5)  # rate limit

    print(f'\nРезультат: OK={ok} FAIL={fail} SKIP={skip}')


if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings()
    main()
