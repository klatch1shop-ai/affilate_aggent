"""
rozetka_feed_sync_v2.py
=======================
Генерує XML для Розетки:
1. Структура і категорії — з /data/carvol_rozetka.xml (пройшов перевірку Розетки)
2. Ціни і наявність — з Carvol Prom фіду (реальний час)
3. Комісія Розетки — по категоріях з БД
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
TEMPLATE_PATH = '/home/tek/agent-system/data/carvol_rozetka.xml'
OUTPUT_PATH   = '/home/tek/agent-system/shared/feeds/rozetka_feed.xml'
TG_BOT_TOKEN  = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID    = os.getenv('TG_CHAT_ID')

# Комісії Розетки по нашим category_id (з тарифу)
# Автоелектроніка: 18% базова, знижується з ціною
# Автосвітло/запчастини: 13% базова
CPA_RULES = {
    '1':  [( 0,   5999, 0.18), (6000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Камери
    '2':  [( 0,   5999, 0.18), (6000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Штатні пристрої
    '3':  [( 0,   5999, 0.18), (6000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Кабелі
    '4':  [( 0,   5999, 0.18), (6000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Перехідні рамки
    '5':  [( 0,   5999, 0.18), (6000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Антени
    '6':  [( 0,   5999, 0.18), (6000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Реєстратори
    '7':  [( 0,   2999, 0.18), (3000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Кронштейни
    '8':  [( 0,   2999, 0.13), (3000, 9999, 0.07), (10000, 19999, 0.05), (20000, 9e9, 0.03)],  # Оптика
    '9':  [( 0,   2999, 0.18), (3000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Проводка
    '10': [( 0,   2999, 0.13), (3000, 9999, 0.07), (10000, 19999, 0.05), (20000, 9e9, 0.03)],  # LED лампи
    '12': [( 0,   2999, 0.13), (3000, 9999, 0.07), (10000, 19999, 0.05), (20000, 9e9, 0.03)],  # Фари
    '14': [( 0,   2999, 0.18), (3000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Запобіжники
    '15': [( 0,   2999, 0.18), (3000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Дефлектори
    '16': [( 0,   2999, 0.18), (3000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Мото
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
    """Розраховує ціну для Розетки з урахуванням CPA тиру."""
    rules = CPA_RULES.get(str(cat_id), [(0, 9e9, 0.18)])
    for low, high, rate in rules:
        if low <= price <= high:
            return math.ceil(price * (1 + rate) / 10) * 10
    return math.ceil(price * 1.18 / 10) * 10


def fetch_carvol_live() -> dict:
    """
    Завантажує живий фід Carvol і повертає:
    {article: {price, qty, available}}
    """
    logger.info('Завантажуємо живий фід Carvol...')
    r = requests.get(CARVOL_FEED, timeout=120)
    root = ET.fromstring(r.content)
    offers = root.find('shop').find('offers').findall('offer')

    data = {}
    for offer in offers:
        art_el = offer.find('article')
        if art_el is None:
            continue
        article = (art_el.text or '').strip()
        price_el = offer.find('price')
        qty_el   = offer.find('stock_quantity')
        qty      = int(qty_el.text or 0) if qty_el is not None else 0
        price    = float(price_el.text or 0) if price_el is not None else 0
        available = offer.get('available', 'false').lower() == 'true' and qty > 0

        data[article] = {
            'price':     price,
            'qty':       qty,
            'available': available,
        }

    logger.info(f'Живий фід: {len(data)} SKU, в наявності: {sum(1 for v in data.values() if v["available"])}')
    return data


def generate_feed(live_data: dict) -> tuple:
    """
    Генерує XML на основі шаблону carvol_rozetka.xml
    але з живими цінами і наявністю з Carvol фіду.
    """
    # Читаємо шаблон (структура що пройшла перевірку Розетки)
    template = ET.parse(TEMPLATE_PATH)
    tmpl_root = template.getroot()
    tmpl_shop = tmpl_root.find('shop')

    # Будуємо новий XML
    root = ET.Element('yml_catalog')
    root.set('date', datetime.now().strftime('%Y-%m-%d %H:%M'))
    shop = ET.SubElement(root, 'shop')

    # Копіюємо метадані
    for tag in ['name', 'company', 'url']:
        el = tmpl_shop.find(tag)
        if el is not None:
            new_el = ET.SubElement(shop, tag)
            new_el.text = el.text

    # Копіюємо валюти
    currencies = tmpl_shop.find('currencies')
    if currencies is not None:
        shop.append(currencies)

    # Копіюємо категорії (з rz_id — вже правильні!)
    categories = tmpl_shop.find('categories')
    if categories is not None:
        shop.append(categories)

    # Оновлюємо товари з живими цінами
    offers_el = ET.SubElement(shop, 'offers')

    stats = {'total': 0, 'in_stock': 0, 'out_stock': 0,
             'not_in_live': 0, 'price_examples': []}

    tmpl_offers = tmpl_shop.find('offers').findall('offer')

    for tmpl_offer in tmpl_offers:
        art_el = tmpl_offer.find('article')
        article = (art_el.text or '').strip() if art_el is not None else ''
        cat_el  = tmpl_offer.find('categoryId')
        cat_id  = (cat_el.text or '').strip() if cat_el is not None else '1'

        # Беремо живі дані
        live = live_data.get(article)
        if not live:
            stats['not_in_live'] += 1
            available = False
            price_carvol = 0.0
            qty = 0
        else:
            available    = live['available']
            price_carvol = live['price']
            qty          = live['qty']

        # Розраховуємо ціну з комісією
        rz_price = calc_price(price_carvol, cat_id) if price_carvol > 0 else 0

        # Будуємо offer
        o = ET.SubElement(offers_el, 'offer')
        o.set('id', tmpl_offer.get('id', ''))
        o.set('available', 'true' if available else 'false')

        ET.SubElement(o, 'price').text = str(rz_price) if rz_price > 0 else str(price_carvol)
        ET.SubElement(o, 'currencyId').text = 'UAH'

        # Категорія
        if cat_el is not None:
            new_cat = ET.SubElement(o, 'categoryId')
            new_cat.text = cat_id

        # Фото (з шаблону)
        for pic in tmpl_offer.findall('picture'):
            p = ET.SubElement(o, 'picture')
            p.text = (pic.text or '').strip()

        # Vendor
        vendor_el = tmpl_offer.find('vendor')
        if vendor_el is not None:
            ET.SubElement(o, 'vendor').text = vendor_el.text or ''

        # Article
        if art_el is not None:
            ET.SubElement(o, 'article').text = article

        # Кількість
        ET.SubElement(o, 'stock_quantity').text = str(qty)

        # Назви
        for tag in ['name_ua', 'name']:
            el = tmpl_offer.find(tag)
            if el is not None:
                new_el = ET.SubElement(o, tag)
                new_el.text = el.text or ''

        # Опис
        desc_el = tmpl_offer.find('description_ua')
        if desc_el is not None and desc_el.text:
            d = ET.SubElement(o, 'description_ua')
            d.text = desc_el.text

        # Params
        for param in tmpl_offer.findall('param'):
            p = ET.SubElement(o, 'param')
            p.set('name', param.get('name', ''))
            p.text = param.text or ''

        stats['total'] += 1
        if available:
            stats['in_stock'] += 1
        else:
            stats['out_stock'] += 1

        # Приклади для перевірки
        if len(stats['price_examples']) < 5 and price_carvol > 0:
            rules = CPA_RULES.get(str(cat_id), [(0, 9e9, 0.18)])
            rate = next((r for lo, hi, r in rules if lo <= price_carvol <= hi), 0.18)
            stats['price_examples'].append({
                'article':  article,
                'cat_id':   cat_id,
                'carvol':   price_carvol,
                'rz_price': rz_price,
                'rate':     rate,
                'qty':      qty,
            })

    return root, stats


def main():
    logger.add('/tmp/rozetka_feed_sync.log', rotation='10 MB', level='INFO')
    start = datetime.now()
    logger.info('=== Rozetka Feed Sync v2 ===')

    try:
        # 1. Живі дані з Carvol
        live = fetch_carvol_live()

        # 2. Генеруємо XML
        root, stats = generate_feed(live)

        # 3. Зберігаємо
        xml_bytes = minidom.parseString(
            ET.tostring(root, encoding='unicode')
        ).toprettyxml(indent='  ', encoding='UTF-8')

        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, 'wb') as f:
            f.write(xml_bytes)

        size_kb = os.path.getsize(OUTPUT_PATH) // 1024
        duration = (datetime.now() - start).seconds

        # Виводимо приклади цін
        print('\n=== ПЕРЕВІРКА ЦІН ===')
        print(f'{"Article":20} | {"Cat":4} | {"Carvol":8} | {"Розетка":8} | {"Комісія":8} | {"Qty":5}')
        print('-'*70)
        for ex in stats['price_examples']:
            print(
                f'{ex["article"][:20]:20} | '
                f'{ex["cat_id"]:4} | '
                f'{ex["carvol"]:8.0f} | '
                f'{ex["rz_price"]:8.0f} | '
                f'+{ex["rate"]*100:.0f}%      | '
                f'{ex["qty"]:5}'
            )

        print(f'\n=== РЕЗУЛЬТАТ ===')
        print(f'Всього товарів:     {stats["total"]}')
        print(f'В наявності:        {stats["in_stock"]}')
        print(f'Відсутні:           {stats["out_stock"]}')
        print(f'Немає в живому фіді:{stats["not_in_live"]}')
        print(f'Файл: {OUTPUT_PATH} ({size_kb} KB)')
        print(f'Час: {duration}с')

        msg = (
            f'🔄 <b>Rozetka Feed Sync v2</b> ({duration}с)\n'
            f'Всього: {stats["total"]} | В наявності: {stats["in_stock"]}\n'
            f'Файл: {size_kb} KB\n'
            f'URL: https://usa1.tail3a617f.ts.net/rozetka_feed.xml'
        )
        tg(msg)

    except Exception as e:
        logger.error(f'Помилка: {e}')
        tg(f'❌ <b>Rozetka Feed Sync помилка:</b> {e}')
        raise


if __name__ == '__main__':
    main()
