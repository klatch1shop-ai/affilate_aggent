"""
Price Updater — щоденне оновлення цін на Prom
=============================================
Алгоритм:
1. Завантажує фід TOPTUL (vendorCode = SKU)
2. Порівнює з цінами в БД
3. Перераховує our_price якщо змінилась ціна фіду
4. Оновлює змінені ціни на Prom через API
5. Telegram сповіщення про зміни
"""
import os, sys, requests, json, time
import xml.etree.ElementTree as ET
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

PROM_TOKEN = os.getenv('PROM_API_TOKEN')
PROM_HEADERS = {'Authorization': f'Bearer {PROM_TOKEN}'}
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')

TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)

CPA_RATE = 0.15
DELIVERY = 20
MARGIN = 0.20
DISCOUNT = 0.88
MIN_PRICE = 40

def tg(text: str):
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_ADMIN, 'text': text, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.error(f'Telegram: {e}')

def calc_price(feed_price: float) -> float:
    """Розраховує нашу ціну з урахуванням CPA і маржі"""
    zakupka = feed_price * DISCOUNT
    min_price = (zakupka + DELIVERY) / (1 - CPA_RATE) * (1 + MARGIN)
    price = round(min_price / 10) * 10
    return max(price, MIN_PRICE)

def load_feed() -> dict:
    """Завантажує фід TOPTUL"""
    logger.info('Завантажуємо фід TOPTUL...')
    resp = requests.get(TOPTUL_FEED, timeout=120)
    root = ET.fromstring(resp.content)
    offers = root.find('shop').find('offers').findall('offer')
    
    feed = {}
    for offer in offers:
        sku_el = offer.find('vendorCode')
        sku = (sku_el.text or '').strip() if sku_el is not None else ''
        if not sku:
            continue
        price_el = offer.find('price')
        price = float(price_el.text) if price_el is not None else 0
        available = offer.get('available', 'true') == 'true'
        stock_el = offer.find('stock_quantity')
        stock = stock_el.text if stock_el is not None else '*'
        feed[sku] = {'price': price, 'available': available, 'stock': stock}
    
    logger.success(f'Фід: {len(feed)} товарів')
    return feed

def load_prom_map() -> dict:
    """Завантажує всі товари з Prom API"""
    logger.info('Завантажуємо товари з Prom...')
    prom_map = {}
    last_id = None
    
    while True:
        params = {'limit': 100}
        if last_id:
            params['last_id'] = last_id
        resp = requests.get('https://my.prom.ua/api/v1/products/list',
            headers=PROM_HEADERS, params=params, timeout=30)
        products = resp.json().get('products', [])
        if not products:
            break
        for p in products:
            if p.get('sku'):
                prom_map[p['sku']] = {'id': p['id'], 'price': float(p.get('price') or 0)}
        last_id = products[-1]['id']
        if len(products) < 100:
            break
        time.sleep(0.3)
    
    logger.success(f'Prom: {len(prom_map)} товарів')
    return prom_map

def run():
    logger.info('=== Price Updater старт ===')
    
    feed = load_feed()
    prom_map = load_prom_map()
    
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT sku, price_supplier, price_our FROM my_products WHERE price_our IS NOT NULL")
    db_rows = cur.fetchall()
    
    changed = []
    price_updates = []
    
    for r in db_rows:
        sku = r['sku']
        old_feed_price = float(r['price_supplier'])
        old_our_price = float(r['price_our'])
        
        feed_info = feed.get(sku)
        if not feed_info:
            continue
        
        new_feed_price = feed_info['price']
        
        # Ціна фіду змінилась?
        if abs(new_feed_price - old_feed_price) < 0.5:
            continue
        
        # Перераховуємо нашу ціну
        new_our_price = calc_price(new_feed_price)
        diff_pct = (new_feed_price - old_feed_price) / old_feed_price * 100
        
        changed.append({
            'sku': sku,
            'old_feed': old_feed_price,
            'new_feed': new_feed_price,
            'old_our': old_our_price,
            'new_our': new_our_price,
            'diff_pct': diff_pct,
        })
        
        # Оновлюємо БД
        cur.execute(
            'UPDATE my_products SET price_supplier=%s, price_our=%s WHERE sku=%s',
            (new_feed_price, new_our_price, sku)
        )
        
        # Готуємо для Prom
        prom_info = prom_map.get(sku)
        if prom_info and abs(prom_info['price'] - new_our_price) > 1:
            price_updates.append({'id': prom_info['id'], 'price': new_our_price})
    
    conn.commit()
    cur.close(); conn.close()
    
    logger.info(f'Змінено цін: {len(changed)}')
    
    if not changed:
        logger.success('Ціни актуальні — змін немає')
        return
    
    # Оновлюємо на Prom батчами
    updated_prom = 0
    for i in range(0, len(price_updates), 100):
        batch = price_updates[i:i+100]
        resp = requests.post('https://my.prom.ua/api/v1/products/edit',
            headers=PROM_HEADERS, json=batch, timeout=30)
        if resp.status_code == 200:
            updated_prom += len(resp.json().get('processed_ids', []))
        time.sleep(0.5)
    
    logger.success(f'Оновлено на Prom: {updated_prom}')
    
    # Telegram звіт
    up = [c for c in changed if c['diff_pct'] > 0]
    down = [c for c in changed if c['diff_pct'] < 0]
    
    msg = f"""📊 <b>Price Updater — звіт</b>
    
Змінено цін: {len(changed)}
📈 Подорожчало: {len(up)}
📉 Подешевшало: {len(down)}
✅ Оновлено на Prom: {updated_prom}"""
    
    if up[:3]:
        msg += '\n\nПодорожчало (топ 3):'
        for c in sorted(up, key=lambda x: -abs(x['diff_pct']))[:3]:
            msg += f'\n  {c["sku"]}: {c["old_our"]:.0f}→{c["new_our"]:.0f} грн ({c["diff_pct"]:+.1f}%)'
    
    if down[:3]:
        msg += '\n\nПодешевшало (топ 3):'
        for c in sorted(down, key=lambda x: abs(x['diff_pct']))[:3]:
            msg += f'\n  {c["sku"]}: {c["old_our"]:.0f}→{c["new_our"]:.0f} грн ({c["diff_pct"]:+.1f}%)'
    
    tg(msg)

if __name__ == '__main__':
    run()
