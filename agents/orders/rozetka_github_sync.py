"""
rozetka_github_sync.py
======================
Оновлює ТІЛЬКИ ціни та наявність в data/carvol_rozetka.xml
Структура файлу (категорії, назви, фото, описи) — незмінна!

Що змінюється:
  <offer available="true/false">
    <price>НОВА_ЦІНА</price>
    <stock_quantity>КІЛЬКІСТЬ</stock_quantity>

Cron (раз на добу о 7:00):
0 7 * * * cd /home/tek/agent-system && source venv/bin/activate && python3 agents/orders/rozetka_github_sync.py
"""
import sys, os, requests, math, subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from loguru import logger
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')

CARVOL_FEED = (
    'https://carvol.prom.ua/rozetka_feed.xml'
    '?rozetka_hash_tag=2251d0779efad97117ac08d7efd82c2f'
    '&product_ids=&label_ids=28618299&languages=uk%2Cru&group_ids='
)
XML_PATH  = '/home/tek/agent-system/data/carvol_rozetka.xml'
REPO_PATH = '/home/tek/agent-system'
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID   = os.getenv('TG_CHAT_ID')

# Комісії Розетки по category_id (наші ID 1-16)
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


def tg(msg: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.warning(f'TG: {e}')


def calc_price(price: float, cat_id: str) -> float:
    """Ціна Carvol + комісія Розетки по тиру."""
    rules = CPA_RULES.get(str(cat_id), [(0, 9e9, 0.18)])
    for low, high, rate in rules:
        if low <= price <= high:
            return math.ceil(price * (1 + rate) / 10) * 10
    return math.ceil(price * 1.18 / 10) * 10


def fetch_carvol_live() -> dict:
    """Повертає {article: {price, qty, available}} з живого фіду."""
    logger.info('Завантажуємо Carvol фід...')
    r = requests.get(CARVOL_FEED, timeout=120)
    root = ET.fromstring(r.content)
    offers = root.find('shop').find('offers').findall('offer')
    data = {}
    for offer in offers:
        art_el = offer.find('article')
        if art_el is None:
            continue
        article  = (art_el.text or '').strip()
        price_el = offer.find('price')
        qty_el   = offer.find('stock_quantity')
        qty      = int(qty_el.text or 0) if qty_el is not None else 0
        price    = float(price_el.text or 0) if price_el is not None else 0
        available = offer.get('available','false').lower() == 'true' and qty > 0
        data[article] = {'price': price, 'qty': qty, 'available': available}
    logger.info(f'Carvol: {len(data)} SKU, в наявності: {sum(1 for v in data.values() if v["available"])}')
    return data


def update_prices_only(live: dict) -> dict:
    """
    Читає XML, оновлює ТІЛЬКИ:
    - offer[@available]
    - <price>
    - <stock_quantity>
    Все інше (структура, категорії, назви, фото) — незмінне!
    """
    # Читаємо як текст щоб зберегти форматування
    tree = ET.parse(XML_PATH)
    root = tree.getroot()

    # Оновлюємо дату генерації
    root.set('date', datetime.now().strftime('%Y-%m-%d %H:%M'))

    shop   = root.find('shop')
    offers = shop.find('offers').findall('offer')

    stats = {'updated': 0, 'not_found': 0, 'in_stock': 0,
             'out_stock': 0, 'price_changed': 0, 'examples': []}

    for offer in offers:
        art_el  = offer.find('article')
        cat_el  = offer.find('categoryId')
        article = (art_el.text or '').strip() if art_el is not None else ''
        cat_id  = (cat_el.text or '1').strip() if cat_el is not None else '1'

        live_item = live.get(article)

        if not live_item:
            # Товару немає в живому фіді — ставимо відсутній
            offer.set('available', 'false')
            qty_el = offer.find('stock_quantity')
            if qty_el is not None:
                qty_el.text = '0'
            stats['not_found'] += 1
            stats['out_stock'] += 1
            continue

        available    = live_item['available']
        price_carvol = live_item['price']
        qty          = live_item['qty']

        # 1. Оновлюємо available атрибут
        offer.set('available', 'true' if available else 'false')

        # 2. Оновлюємо ціну (тільки якщо є ціна від постачальника)
        if price_carvol > 0:
            rz_price = calc_price(price_carvol, cat_id)
            price_el = offer.find('price')
            if price_el is not None:
                old_price = price_el.text
                price_el.text = str(int(rz_price))
                if old_price != str(int(rz_price)):
                    stats['price_changed'] += 1

        # 3. Оновлюємо кількість
        qty_el = offer.find('stock_quantity')
        if qty_el is not None:
            qty_el.text = str(qty)

        stats['updated'] += 1
        if available:
            stats['in_stock'] += 1
        else:
            stats['out_stock'] += 1

        # Зберігаємо приклади для перевірки
        if len(stats['examples']) < 5 and price_carvol > 0:
            rz_price = calc_price(price_carvol, cat_id)
            rules = CPA_RULES.get(cat_id, [(0, 9e9, 0.18)])
            rate = next((r for lo, hi, r in rules if lo <= price_carvol <= hi), 0.18)
            stats['examples'].append({
                'article': article, 'cat': cat_id,
                'carvol': price_carvol, 'rz': rz_price,
                'rate': rate, 'qty': qty,
                'available': available,
            })

    # Записуємо XML зберігаючи структуру
    tree.write(XML_PATH, encoding='unicode', xml_declaration=False)
    # Додаємо UTF-8 declaration
    with open(XML_PATH, 'r+', encoding='utf-8') as f:
        content = f.read()
        f.seek(0)
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + content)

    return stats


def git_push() -> bool:
    """Пушить оновлений файл в GitHub."""
    msg = f'sync: prices+availability {datetime.now().strftime("%Y-%m-%d %H:%M")}'
    try:
        for cmd in [
            ['git', 'add', 'data/carvol_rozetka.xml'],
            ['git', 'commit', '-m', msg],
            ['git', 'pull', '--rebase'], ['git', 'push'],
        ]:
            r = subprocess.run(cmd, cwd=REPO_PATH, capture_output=True, text=True)
            if r.returncode != 0:
                if 'nothing to commit' in r.stdout + r.stderr:
                    logger.info('Git: немає змін')
                    return True
                logger.error(f'{cmd[1]}: {r.stderr[:200]}')
                return False
        logger.success('Git push OK')
        return True
    except Exception as e:
        logger.error(f'Git: {e}')
        return False


def main():
    logger.add('/tmp/rozetka_github_sync.log', rotation='10 MB', level='INFO')
    start = datetime.now()
    logger.info('=== Rozetka GitHub Sync ===')

    try:
        # 1. Живі дані Carvol
        live = fetch_carvol_live()

        # 2. Оновлюємо ТІЛЬКИ ціни та наявність
        stats = update_prices_only(live)

        # 3. Git push
        pushed = git_push()

        duration = (datetime.now() - start).seconds

        # Виводимо результат
        print('\n=== ПЕРЕВІРКА ЦІН (перші 5) ===')
        print(f'{"Article":20} | {"Cat":3} | {"Carvol":7} | {"Розетка":7} | {"Rate":5} | {"Qty":4} | {"Avail"}')
        print('-' * 70)
        for ex in stats['examples']:
            avail = '✅' if ex['available'] else '❌'
            print(f'{ex["article"][:20]:20} | {ex["cat"]:3} | {ex["carvol"]:7.0f} | {ex["rz"]:7.0f} | +{ex["rate"]*100:.0f}%  | {ex["qty"]:4} | {avail}')

        print(f'\n=== РЕЗУЛЬТАТ ===')
        print(f'Оновлено:         {stats["updated"]}')
        print(f'В наявності:      {stats["in_stock"]}')
        print(f'Відсутні:         {stats["out_stock"]}')
        print(f'Змінилось цін:    {stats["price_changed"]}')
        print(f'Нема у фіді:      {stats["not_found"]}')
        print(f'Git push:         {"✅ OK" if pushed else "❌ FAILED"}')
        print(f'Час:              {duration}с')
        print(f'URL: https://raw.githubusercontent.com/klatch1shop-ai/affilate_aggent/main/data/carvol_rozetka.xml')

        if not pushed:
            tg(f'❌ <b>Rozetka GitHub Sync</b>: git push FAILED')

    except Exception as e:
        logger.error(f'Помилка: {e}')
        tg(f'❌ <b>Rozetka GitHub Sync:</b> {e}')
        raise


if __name__ == '__main__':
    main()
