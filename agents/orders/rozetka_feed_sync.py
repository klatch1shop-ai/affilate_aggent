"""
rozetka_feed_sync.py — Генерація XML фіду для Розетки з Carvol
==============================================================
Що робить:
1. Скачує фід Carvol (Prom)
2. Розраховує ціну з CPA комісією Розетки (залежить від ціни)
3. Генерує XML в форматі carvol_rozetka.xml (вже пройшов перевірку!)
4. Зберігає в shared/feeds/rozetka_feed.xml

Запуск:
    python3 agents/orders/rozetka_feed_sync.py

Cron (кожні 4 год):
    0 */4 * * * cd /home/tek/agent-system && venv/bin/python3 agents/orders/rozetka_feed_sync.py
"""
import sys, os, requests, math
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from loguru import logger
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

CARVOL_FEED = (
    'https://carvol.prom.ua/rozetka_feed.xml'
    '?rozetka_hash_tag=2251d0779efad97117ac08d7efd82c2f'
    '&product_ids=&label_ids=28618299&languages=uk%2Cru&group_ids='
)
OUTPUT_PATH = '/home/tek/agent-system/shared/feeds/rozetka_feed.xml'
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID   = os.getenv('TG_CHAT_ID')

# Комісії Розетки для авто-товарів (з тарифного плану)
# Формат: (ціна_від, ціна_до, ставка)
ROZETKA_CPA_TIERS = {
    # Автоелектроніка (камери, реєстратори, антени, штатні пристрої)
    'electronics': [
        (0,      5999,  0.18),
        (6000,   9999,  0.12),
        (10000,  19999, 0.07),
        (20000,  float('inf'), 0.05),
    ],
    # Автозапчастини, автосвітло (LED, фари)
    'parts': [
        (0,      2999,  0.13),
        (3000,   9999,  0.07),
        (10000,  19999, 0.05),
        (20000,  float('inf'), 0.03),
    ],
    # Загальна авто категорія
    'auto': [
        (0,      2999,  0.18),
        (3000,   9999,  0.12),
        (10000,  19999, 0.07),
        (20000,  99999, 0.05),
        (100000, float('inf'), 0.03),
    ],
}

# Маппінг категорій Carvol → тип комісії
CATEGORY_CPA_TYPE = {
    '1':  'electronics',  # Камери заднього огляду
    '2':  'electronics',  # Штатні головні пристрої
    '3':  'electronics',  # Кабелі та перехідники
    '4':  'electronics',  # Перехідні рамки
    '5':  'electronics',  # Автомобільні антени
    '6':  'electronics',  # Відеореєстратори
    '7':  'auto',         # Кронштейни та тримачі
    '8':  'parts',        # Альтернативна оптика
    '9':  'auto',         # Автомобільна проводка
    '10': 'parts',        # LED лампи автомобільні
    '12': 'parts',        # Автомобільні фари
    '14': 'auto',         # Запобіжники та перемикачі
    '15': 'auto',         # Автомобільні дефлектори
    '16': 'auto',         # Аксесуари для мототехніки
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


def calc_rozetka_price(price: float, category_id: str) -> float:
    """Розраховує ціну для Розетки = ціна постачальника + CPA комісія."""
    cpa_type = CATEGORY_CPA_TYPE.get(str(category_id), 'auto')
    tiers = ROZETKA_CPA_TIERS[cpa_type]
    for low, high, rate in tiers:
        if low <= price <= high:
            return math.ceil(price * (1 + rate) / 10) * 10
    # Fallback: 18%
    return math.ceil(price * 1.18 / 10) * 10


def get_rz_category_mapping() -> dict:
    """Завантажує маппінг категорій з БД."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('SELECT carvol_category_id, rozetka_category_id, category_name FROM rozetka_category_mapping')
        mapping = {r['carvol_category_id']: {
            'rz_id': r['rozetka_category_id'],
            'name':  r['category_name']
        } for r in cur.fetchall()}
        cur.close(); conn.close()
        return mapping
    except Exception as e:
        logger.error(f'DB mapping error: {e}')
        return {}


def fetch_carvol_feed() -> ET.Element:
    """Завантажує фід Carvol."""
    logger.info('Завантажуємо Carvol фід...')
    r = requests.get(CARVOL_FEED, timeout=120)
    root = ET.fromstring(r.content)
    offers = root.find('shop').find('offers').findall('offer')
    logger.info(f'Carvol фід: {len(offers)} товарів')
    return root


def generate_rozetka_xml(feed_root: ET.Element, cat_mapping: dict) -> tuple:
    """
    Генерує XML для Розетки в тому ж форматі що carvol_rozetka.xml
    (пройшов перевірку Розетки).
    """
    shop = feed_root.find('shop')
    offers_el = shop.find('offers').findall('offer')

    # Новий XML
    root = ET.Element('yml_catalog')
    root.set('date', datetime.now().strftime('%Y-%m-%d %H:%M'))
    new_shop = ET.SubElement(root, 'shop')
    ET.SubElement(new_shop, 'name').text = 'klatch1 shop'
    ET.SubElement(new_shop, 'company').text = '3721108'
    ET.SubElement(new_shop, 'url').text = 'https://cs4053918.prom.ua/'

    currencies = ET.SubElement(new_shop, 'currencies')
    cur_el = ET.SubElement(currencies, 'currency')
    cur_el.set('id', 'UAH'); cur_el.set('rate', '1')

    # Категорії з rz_id
    categories_el = ET.SubElement(new_shop, 'categories')
    for cat_id, info in cat_mapping.items():
        cat = ET.SubElement(categories_el, 'category')
        cat.set('id', cat_id)
        cat.set('rz_id', info['rz_id'])
        cat.text = info['name']

    # Товари
    new_offers = ET.SubElement(new_shop, 'offers')

    total = 0
    in_stock = 0
    out_stock = 0
    price_changes = 0

    for offer in offers_el:
        offer_id  = offer.get('id', '')
        available = offer.get('available', 'false').lower() == 'true'
        cat_id    = (offer.find('categoryId').text or '').strip()

        price_el = offer.find('price')
        price    = float(price_el.text or 0) if price_el is not None else 0

        # Розраховуємо ціну для Розетки
        rz_price = calc_rozetka_price(price, cat_id) if price > 0 else 0

        # Кількість
        qty_el = offer.find('stock_quantity')
        qty    = int(qty_el.text or 0) if qty_el is not None else 0

        # Якщо кількість 0 — out of stock
        if qty == 0:
            available = False

        o = ET.SubElement(new_offers, 'offer')
        o.set('id', offer_id)
        o.set('available', 'true' if available else 'false')

        ET.SubElement(o, 'price').text = str(rz_price)
        ET.SubElement(o, 'currencyId').text = 'UAH'

        cat_id_el = ET.SubElement(o, 'categoryId')
        cat_id_el.text = cat_id

        # Фото (всі)
        for pic in offer.findall('picture'):
            pic_el = ET.SubElement(o, 'picture')
            pic_el.text = (pic.text or '').strip()

        # Vendor
        vendor_el = offer.find('vendor')
        if vendor_el is not None:
            ET.SubElement(o, 'vendor').text = vendor_el.text or ''

        # Article (SKU)
        article_el = offer.find('article')
        if article_el is not None:
            ET.SubElement(o, 'article').text = article_el.text or ''

        # Кількість
        ET.SubElement(o, 'stock_quantity').text = str(qty)

        # Назва UA і RU
        name_ua_el = offer.find('name_ua')
        name_el    = offer.find('name')
        if name_ua_el is not None:
            name_ua = ET.SubElement(o, 'name_ua')
            name_ua.text = name_ua_el.text or ''
        if name_el is not None:
            name = ET.SubElement(o, 'name')
            name.text = name_el.text or ''

        # Опис UA
        desc_ua_el = offer.find('description_ua')
        if desc_ua_el is not None and desc_ua_el.text:
            desc = ET.SubElement(o, 'description_ua')
            desc.text = desc_ua_el.text

        # Params
        for param in offer.findall('param'):
            p = ET.SubElement(o, 'param')
            p.set('name', param.get('name', ''))
            p.text = param.text or ''

        total += 1
        if available:
            in_stock += 1
        else:
            out_stock += 1

    return root, total, in_stock, out_stock


def main():
    logger.add('/tmp/rozetka_feed_sync.log', rotation='10 MB', level='INFO')
    start = datetime.now()
    logger.info('=== Rozetka Feed Sync запущено ===')

    try:
        # 1. Завантажуємо маппінг категорій
        cat_mapping = get_rz_category_mapping()
        logger.info(f'Категорій в маппінгу: {len(cat_mapping)}')

        # 2. Завантажуємо Carvol фід
        feed_root = fetch_carvol_feed()

        # 3. Генеруємо XML для Розетки
        new_root, total, in_stock, out_stock = generate_rozetka_xml(feed_root, cat_mapping)

        # 4. Зберігаємо
        xml_bytes = minidom.parseString(
            ET.tostring(new_root, encoding='unicode')
        ).toprettyxml(indent='  ', encoding='UTF-8')

        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, 'wb') as f:
            f.write(xml_bytes)

        size_kb = os.path.getsize(OUTPUT_PATH) // 1024
        duration = (datetime.now() - start).seconds

        msg = (
            f'🔄 <b>Rozetka Feed Sync завершено</b> ({duration}с)\n'
            f'Всього товарів: {total}\n'
            f'В наявності: {in_stock}\n'
            f'Відсутні: {out_stock}\n'
            f'Файл: {size_kb} KB\n'
            f'URL: https://usa1.tail3a617f.ts.net/rozetka_feed.xml'
        )
        tg(msg)
        logger.success(f'Завершено за {duration}с: {total} товарів, {in_stock} в наявності')
        print(f'OK: total={total}, in_stock={in_stock}, out_stock={out_stock}, size={size_kb}KB')

    except Exception as e:
        logger.error(f'Rozetka Feed Sync помилка: {e}')
        tg(f'❌ <b>Rozetka Feed Sync помилка:</b> {e}')
        raise


if __name__ == '__main__':
    main()
