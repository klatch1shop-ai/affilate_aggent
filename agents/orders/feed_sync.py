"""
feed_sync.py — Синхронізація цін і наявності для Єпіцентру
===========================================================
Що робить:
1. Скачує фід TOPTUL
2. Порівнює наявність з БД
3. Оновлює epicentr_price при зміні цін
4. Генерує XML для автооновлення Єпіцентру
5. Зберігає в shared/feeds/epicentr_update.xml

Запуск:
    python3 agents/orders/feed_sync.py

Cron (кожні 4 год):
    0 */4 * * * cd /home/tek/agent-system && venv/bin/python3 agents/orders/feed_sync.py
"""
import sys, os, requests, json, math
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from loguru import logger
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)
OUTPUT_PATH  = '/home/tek/agent-system/shared/feeds/epicentr_update.xml'
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID   = os.getenv('TG_CHAT_ID')


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


def epicentr_price(price_our: float, category_name: str) -> float:
    """Розраховує ціну для Єпіцентру = наша ціна + CPA."""
    cpa = 1.10 if any(x in (category_name or '').lower()
                      for x in ['компресор', 'верстак', 'станок']) else 1.15
    return math.ceil(price_our * cpa / 10) * 10


def fetch_feed() -> dict:
    """Скачує фід і повертає {sku: {available, price, name}}."""
    logger.info('Завантажуємо фід TOPTUL...')
    r = requests.get(TOPTUL_FEED, timeout=120)
    root = ET.fromstring(r.content)
    offers = root.find('shop').find('offers').findall('offer')
    data = {}
    for offer in offers:
        sku_el = offer.find('vendorCode')
        if sku_el is None:
            continue
        sku = (sku_el.text or '').strip().upper()
        price_el   = offer.find('price')
        name_ua_el = offer.find('name_ua') or offer.find('name')
        data[sku] = {
            'available': offer.get('available', 'false').lower() == 'true',
            'price':     float(price_el.text or 0) if price_el is not None else 0,
            'name':      (name_ua_el.text or '') if name_ua_el is not None else '',
        }
    logger.info(f'Фід: {len(data)} SKU')
    return data


def sync_with_db(feed: dict) -> dict:
    """
    Синхронізує фід з БД:
    - Оновлює price_supplier і epicentr_price при зміні ціни
    - Повертає статистику змін
    """
    conn = get_connection()
    cur  = conn.cursor()

    # Отримуємо всі товари з маппінгом
    cur.execute('''
        SELECT p.sku, p.price_supplier, p.price_our, p.epicentr_price,
               p.epicentr_category_name, m.epicentr_article
        FROM my_products p
        JOIN epicentr_sku_mapping m ON m.our_sku = p.sku
        WHERE p.epicentr_category_id IS NOT NULL AND p.price_our > 0
    ''')
    db_products = cur.fetchall()

    price_changed   = 0
    avail_changed   = 0
    price_updated   = []

    for p in db_products:
        sku       = p['sku'].upper()
        feed_item = feed.get(sku)
        if not feed_item:
            continue

        feed_price = feed_item['price']
        old_price  = float(p['price_supplier'] or 0)

        # Якщо ціна постачальника змінилась — оновлюємо
        if abs(feed_price - old_price) > 0.01 and feed_price > 0:
            new_price_our  = feed_price  # ціна постачальника = наша ціна (маржа від постачальника)
            new_epi_price  = epicentr_price(new_price_our, p['epicentr_category_name'])
            cur.execute('''
                UPDATE my_products
                SET price_supplier = %s,
                    price_our = %s,
                    epicentr_price = %s
                WHERE sku = %s
            ''', (feed_price, new_price_our, new_epi_price, p['sku']))
            price_changed += 1
            price_updated.append({
                'sku':       sku,
                'article':   p['epicentr_article'],
                'old_price': old_price,
                'new_price': new_price_our,
                'epi_price': new_epi_price,
            })

    conn.commit()
    cur.close(); conn.close()

    logger.info(f'Оновлено цін: {price_changed}')
    return {
        'price_changed': price_changed,
        'price_updated': price_updated[:5],  # перші 5 для логу
    }


def generate_update_xml(feed: dict) -> tuple:
    """
    Генерує XML для автооновлення Єпіцентру.
    Формат: тільки offer id + price + availability (мінімальний)
    """
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute('''
        SELECT m.epicentr_article, p.epicentr_price, p.sku,
               p.epicentr_category_name
        FROM epicentr_sku_mapping m
        JOIN my_products p ON p.sku = m.our_sku
        WHERE p.epicentr_category_id IS NOT NULL AND p.epicentr_price > 0
    ''')
    rows = cur.fetchall()
    cur.close(); conn.close()

    root   = ET.Element('yml_catalog')
    root.set('date', datetime.now().strftime('%Y-%m-%d %H:%M'))
    offers = ET.SubElement(root, 'offers')

    in_stock = 0
    out_of_stock = 0

    for r in rows:
        sku       = r['sku'].upper()
        feed_item = feed.get(sku, {})
        available = feed_item.get('available', False)

        o = ET.SubElement(offers, 'offer')
        o.set('id', r['epicentr_article'])
        o.set('available', 'true' if available else 'false')
        ET.SubElement(o, 'price').text = str(r['epicentr_price'])
        ET.SubElement(o, 'availability').text = 'in_stock' if available else 'out_of_stock'

        if available:
            in_stock += 1
        else:
            out_of_stock += 1

    xml_bytes = minidom.parseString(
        ET.tostring(root, encoding='unicode')
    ).toprettyxml(indent='  ', encoding='UTF-8')

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'wb') as f:
        f.write(xml_bytes)

    size_kb = os.path.getsize(OUTPUT_PATH) // 1024
    logger.info(f'XML: {OUTPUT_PATH} ({size_kb} KB), в наявності: {in_stock}, відсутні: {out_of_stock}')
    return in_stock, out_of_stock



def git_push() -> bool:
    import subprocess
    cwd = '/home/tek/agent-system'
    try:
        subprocess.run(['git', 'add', 'shared/feeds/epicentr_update.xml'], check=True, capture_output=True, cwd=cwd)
        result = subprocess.run(['git', 'diff', '--cached', '--quiet'], capture_output=True, cwd=cwd)
        if result.returncode == 0:
            logger.info('Git: файл не змінився')
            return True
        subprocess.run(['git', 'commit', '-m', 'sync: epicentr availability auto'], check=True, capture_output=True, cwd=cwd)
        subprocess.run(['git', 'push', '--force-with-lease'], check=True, capture_output=True, cwd=cwd)
        logger.success('Git push: OK')
        return True
    except Exception as e:
        logger.error(f'Git push: FAILED {e}')
        return False

def main():
    logger.add('/tmp/feed_sync.log', rotation='10 MB', level='INFO')
    start = datetime.now()
    logger.info('=== Feed Sync запущено ===')

    try:
        # 1. Скачуємо фід
        feed = fetch_feed()

        # 2. Синхронізуємо ціни в БД
        changes = sync_with_db(feed)

        # 3. Генеруємо XML для автооновлення
        in_stock, out_stock = generate_update_xml(feed)
        git_ok = git_push()

        duration = (datetime.now() - start).seconds
        msg = (
            f'🔄 <b>Feed Sync завершено</b> ({duration}с)\n'
            f'В наявності: {in_stock}\n'
            f'Відсутні: {out_stock}\n'
            f'Змінилось цін: {changes["price_changed"]}'
        )
        if changes['price_updated']:
            msg += '\n\nЗміни цін:'
            for p in changes['price_updated']:
                msg += f'\n  {p["sku"]}: {p["old_price"]:.0f}→{p["new_price"]:.0f} грн (Єп: {p["epi_price"]:.0f})'

        logger.success(f'Завершено за {duration}с')
        git_status = "✅ OK" if git_ok else "❌ FAILED"
        print(f"OK: in_stock={in_stock}, out_of_stock={out_stock}, price_changes={changes["price_changed"]}, git={git_status}")

    except Exception as e:
        logger.error(f'Feed Sync помилка: {e}')
        tg(f'❌ <b>Feed Sync помилка:</b> {e}')
        raise


if __name__ == '__main__':
    main()
