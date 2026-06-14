"""
agents/orders/carvol_epicentr_sync.py
======================================
Оновлює ТІЛЬКИ ціни та наявність в exports/carvol_epicentr.xml
з живого фіду https://carvol.prom.ua/rozetka_feed.xml

Що змінюється:
  <offer available="true/false">
    <price>НОВА_ЦІНА</price>

Формула: math.ceil(carvol_price / (1 - 0.15) / 10) * 10

Cron (раз на добу о 7:00):
0 7 * * * cd /home/tek/agent-system && venv/bin/python3 agents/orders/carvol_epicentr_sync.py
"""
import sys, os, math, requests, subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
from dotenv import load_dotenv; load_dotenv(os.path.join(BASE_DIR, '.env'))

CARVOL_FEED = (
    'https://carvol.prom.ua/rozetka_feed.xml'
    '?rozetka_hash_tag=2251d0779efad97117ac08d7efd82c2f'
    '&product_ids=&label_ids=&languages=uk%2Cru&group_ids='
)
XML_PATH    = os.path.join(BASE_DIR, 'exports', 'carvol_epicentr.xml')
REPO_PATH   = BASE_DIR
COMMISSION  = 0.15

TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID   = os.getenv('TG_CHAT_ID')


def tg(msg: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f'TG: {e}')


def calc_price(carvol_price: float) -> float:
    """Gross-up ціни Carvol на комісію Єпіцентру 15%, округлення вгору до 10."""
    return math.ceil(carvol_price / (1 - COMMISSION) / 10) * 10


def fetch_carvol_live() -> dict:
    """Повертає {article: {price, available}} з живого фіду Carvol."""
    logger.info('Завантажуємо Carvol фід...')
    r = requests.get(CARVOL_FEED, timeout=120)
    root = ET.fromstring(r.content)
    shop = root.find('shop')
    if shop is None:
        shop = root
    offers_el = shop.find('offers')
    if offers_el is None:
        offers_el = root
    offers = offers_el.findall('offer')

    data = {}
    for offer in offers:
        art_el = offer.find('article')
        if art_el is None:
            art_el = offer.find('vendorCode')
        if art_el is None:
            continue
        article = (art_el.text or '').strip()
        if not article:
            continue

        price_el = offer.find('price')
        qty_el   = offer.find('stock_quantity')
        price    = float(price_el.text or 0) if price_el is not None else 0.0
        qty      = int(qty_el.text or 0)     if qty_el   is not None else 0
        avail    = offer.get('available', 'false').lower() == 'true'
        data[article] = {'price': price, 'available': avail and qty > 0}

    in_stock = sum(1 for v in data.values() if v['available'])
    logger.info(f'Carvol: {len(data)} SKU, в наявності: {in_stock}')
    return data


def update_xml(live: dict) -> dict:
    """
    Читає exports/carvol_epicentr.xml, оновлює ТІЛЬКИ:
    - offer[@available]
    - <price>
    Все інше (структура, категорії, назви, фото, описи) — незмінне!
    """
    tree = ET.parse(XML_PATH)
    root = tree.getroot()
    root.set('date', datetime.now().strftime('%Y-%m-%d %H:%M'))

    offers = root.find('offers').findall('offer')

    stats = {
        'updated': 0, 'not_found': 0,
        'in_stock': 0, 'out_stock': 0,
        'price_changed': 0, 'examples': [],
    }

    for offer in offers:
        article = offer.get('id', '').strip()
        if not article:
            continue

        live_item = live.get(article)

        if not live_item:
            offer.set('available', 'false')
            stats['not_found'] += 1
            stats['out_stock'] += 1
            continue

        available    = live_item['available']
        price_carvol = live_item['price']

        offer.set('available', 'true' if available else 'false')

        if price_carvol > 0:
            ep_price  = calc_price(price_carvol)
            price_el  = offer.find('price')
            if price_el is not None:
                old_price = price_el.text
                new_price = f'{ep_price:.2f}'
                price_el.text = new_price
                if old_price != new_price:
                    stats['price_changed'] += 1

            if len(stats['examples']) < 5 and available:
                stats['examples'].append({
                    'article':  article,
                    'carvol':   price_carvol,
                    'epicentr': calc_price(price_carvol),
                    'available': available,
                })

        stats['updated'] += 1
        if available:
            stats['in_stock'] += 1
        else:
            stats['out_stock'] += 1

    tree.write(XML_PATH, encoding='unicode', xml_declaration=False)
    with open(XML_PATH, 'r+', encoding='utf-8') as f:
        content = f.read()
        f.seek(0)
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + content)

    return stats


def git_reset_to_origin() -> bool:
    """Скидає локальний репо до стану origin/main перед оновленням XML."""
    try:
        for cmd in [
            ['git', 'fetch', 'origin'],
            ['git', 'reset', '--hard', 'origin/main'],
        ]:
            r = subprocess.run(cmd, cwd=REPO_PATH, capture_output=True, text=True)
            if r.returncode != 0:
                logger.error(f'{" ".join(cmd)}: {r.stderr[:200]}')
                return False
        logger.info('Git: reset to origin/main OK')
        return True
    except Exception as e:
        logger.error(f'Git reset: {e}')
        return False


def git_push() -> bool:
    """Пушить оновлений XML в GitHub (без rebase — завжди поверх origin/main)."""
    msg = f'sync: epicentr prices+availability {datetime.now().strftime("%Y-%m-%d %H:%M")}'
    try:
        for cmd in [
            ['git', 'add', 'exports/carvol_epicentr.xml'],
            ['git', 'commit', '-m', msg],
            ['git', 'push'],
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
    logger.add('/tmp/carvol_epicentr_sync.log', rotation='10 MB', level='INFO')
    start = datetime.now()
    logger.info('=== Carvol → Єпіцентр Sync ===')

    try:
        # Спочатку синхронізуємось з origin щоб уникнути конфліктів
        git_reset_to_origin()

        live   = fetch_carvol_live()
        stats  = update_xml(live)
        pushed = git_push()

        duration = (datetime.now() - start).seconds

        print('\n=== ПЕРЕВІРКА ЦІН (перші 5 в наявності) ===')
        print(f'{"Артикул":25} | {"Carvol":9} | {"Єпіцентр":10}')
        print('-' * 55)
        for ex in stats['examples']:
            print(f'{ex["article"][:25]:25} | {ex["carvol"]:9.2f} | {ex["epicentr"]:10.2f}')

        print(f'\n=== РЕЗУЛЬТАТ ===')
        print(f'Оновлено:         {stats["updated"]}')
        print(f'В наявності:      {stats["in_stock"]}')
        print(f'Відсутні:         {stats["out_stock"]}')
        print(f'Змінилось цін:    {stats["price_changed"]}')
        print(f'Нема у фіді:      {stats["not_found"]}')
        print(f'Git push:         {"✅ OK" if pushed else "❌ FAILED"}')
        print(f'Час:              {duration}с')

        if not pushed:
            tg('❌ <b>Carvol→Єпіцентр Sync</b>: git push FAILED')

    except Exception as e:
        logger.error(f'Помилка: {e}')
        tg(f'❌ <b>Carvol→Єпіцентр Sync:</b> {e}')
        raise


if __name__ == '__main__':
    main()
