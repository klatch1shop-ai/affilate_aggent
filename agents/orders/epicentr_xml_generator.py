"""
agents/orders/epicentr_xml_generator.py
==========================================
Генератор XML для імпорту товарів в Єпіцентр.

Формат: yml_catalog (власний формат Єпіцентру, НЕ Prom/Rozetka)
Документація: template (5).xml від Євгенія Тамбовського

Структура XML:
  <offer id="SKU" available="true">
    <price>ціна</price>
    <category code="ID">Назва</category>
    <attribute_set code="ID">Назва</attribute_set>
    <name lang="ua">Назва УА</name>
    <name lang="ru">Назва РУ</name>
    <picture>URL</picture>
    <description lang="ua">Опис</description>
    <vendor code="hash">TOPTUL</vendor>
    <country_of_origin code="twn">Тайвань</country_of_origin>
    <param paramcode="measure" valuecode="measure_pcs">шт.</param>
    <param paramcode="ratio">1</param>
    <param paramcode="brand">TOPTUL</param>
    <width>0</width>
    <height>0</height>
  </offer>

Запуск:
    # Всі товари (один XML файл)
    python3 epicentr_xml_generator.py --output /tmp/epicentr_import.xml

    # По категоріях (окремий файл на кожну)
    python3 epicentr_xml_generator.py --by-category --output-dir /tmp/epicentr_xml/

    # Тільки топ категорії
    python3 epicentr_xml_generator.py --limit 100 --output /tmp/epicentr_test.xml
"""

import os, sys, xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# =============================================
# КОНСТАНТИ
# =============================================

# Фіксовані значення для всіх TOPTUL товарів
VENDOR_NAME = 'TOPTUL'
VENDOR_CODE = 'bj0nbzkpfibrajom'
COUNTRY_NAME_UA = 'Тайвань'
COUNTRY_NAME_RU = 'Тайвань'
COUNTRY_CODE = 'twn'

# Обов'язкові param для всіх категорій інструментів
COMMON_PARAMS = [
    # paramcode, valuecode, name_ua, value_ua, is_cdata
    ('measure', 'measure_pcs', 'Міра виміру та кількість', 'шт.', False),
    ('ratio',   None,          'Мінімальна кратність товару', '1', True),
    ('brand',   'bj0nbzkpfibrajom', 'Бренд', 'TOPTUL', False),
    ('country_of_origin', 'twn', 'Країна-виробник', 'Тайвань', False),
]

# Базові розміри якщо немає в БД
DEFAULT_WIDTH  = 0
DEFAULT_HEIGHT = 0
DEFAULT_WEIGHT = 0


# =============================================
# ЗАВАНТАЖЕННЯ ФІДУ TOPTUL (для фото і опису)
# =============================================

_feed_cache = {}

def load_feed_data() -> dict:
    """Завантажує фід TOPTUL для отримання фото і описів."""
    global _feed_cache
    if _feed_cache:
        return _feed_cache

    import requests, xml.etree.ElementTree as ET
    TOPTUL_FEED = (
        'https://toptul.online/products_feed.xml?'
        'hash_tag=442309995a1416e3104d287504a1846f'
        '&label_ids=3882792&html_description=1&languages=uk,ru'
    )
    try:
        logger.info('Завантажуємо фід TOPTUL для фото і описів...')
        resp = requests.get(TOPTUL_FEED, timeout=120)
        root = ET.fromstring(resp.content)
        for offer in root.find('shop').find('offers').findall('offer'):
            sku_el = offer.find('vendorCode')
            sku = (sku_el.text or '').strip().upper() if sku_el is not None else ''
            if not sku:
                continue

            # Фото
            pictures = [p.text for p in offer.findall('picture') if p.text]

            # Описи
            desc_ua = desc_ru = ''
            for desc in offer.findall('description'):
                lang = desc.get('lang', '')
                if lang == 'uk' or lang == 'ua':
                    desc_ua = (desc.text or '').strip()
                elif lang == 'ru':
                    desc_ru = (desc.text or '').strip()

            # Назви
            name_ua = name_ru = ''
            for name in offer.findall('name'):
                lang = name.get('lang', '')
                if lang == 'uk' or lang == 'ua':
                    name_ua = (name.text or '').strip()
                elif lang == 'ru':
                    name_ru = (name.text or '').strip()

            _feed_cache[sku] = {
                'pictures': pictures,
                'desc_ua': desc_ua,
                'desc_ru': desc_ru,
                'name_ua': name_ua,
                'name_ru': name_ru,
            }

        logger.success(f'Фід завантажено: {len(_feed_cache)} товарів')
    except Exception as e:
        logger.error(f'Помилка завантаження фіду: {e}')

    return _feed_cache


# =============================================
# ГЕНЕРАТОР XML
# =============================================

def generate_xml(
    output_path: str,
    category_filter: str = None,
    limit: int = None,
    confidence_filter: list = None
) -> int:
    """
    Генерує XML файл для імпорту в Єпіцентр.

    Args:
        output_path: шлях для збереження XML
        category_filter: фільтр по назві категорії
        limit: максимальна кількість товарів
        confidence_filter: список рівнів впевненості ['high','medium','low']

    Returns:
        Кількість товарів в XML
    """
    if confidence_filter is None:
        confidence_filter = ['high', 'medium', 'low']

    # Завантажуємо дані фіду
    feed = load_feed_data()

    # Отримуємо товари з БД
    conn = get_connection()
    cur  = conn.cursor()

    conditions = [
        'epicentr_category_id IS NOT NULL',
        'price_our > 0',
        f"epicentr_confidence IN ({','.join(['%s']*len(confidence_filter))})"
    ]
    params = list(confidence_filter)

    if category_filter:
        conditions.append('epicentr_category_name ILIKE %s')
        params.append(f'%{category_filter}%')

    sql = f'''
        SELECT
            mp.sku,
            mp.name_uk,
                mp.price_our,
            mp.price_supplier,
            mp.epicentr_category_id,
            mp.epicentr_category_name,
            mp.epicentr_confidence
        FROM my_products mp
        WHERE {' AND '.join(conditions)}
        ORDER BY mp.epicentr_category_name, mp.sku
    '''
    if limit:
        sql += f' LIMIT {limit}'

    cur.execute(sql, params)
    products = cur.fetchall()
    cur.close(); conn.close()

    logger.info(f'Генеруємо XML для {len(products)} товарів → {output_path}')

    # Будуємо XML
    root = ET.Element('yml_catalog')
    root.set('date', datetime.now().strftime('%Y-%m-%d %H:%M'))
    offers_el = ET.SubElement(root, 'offers')

    count = 0
    for p in products:
        sku      = p['sku']
        name_uk  = p['name_uk'] or sku
        name_ru  = name_uk  # немає окремої RU назви в БД
        price    = float(p['price_our'])
        cat_id   = str(p['epicentr_category_id'])
        cat_name = p['epicentr_category_name'] or ''

        # Дані з фіду
        feed_data = feed.get(sku.upper(), {})
        pictures  = feed_data.get('pictures', [])
        desc_ua   = feed_data.get('desc_ua', '')
        desc_ru   = feed_data.get('desc_ru', '')
        # Якщо є фідові назви — вони кращі
        if feed_data.get('name_ua'):
            name_uk = feed_data['name_ua']
        name_ru = feed_data.get('name_ru') or name_uk

        # offer елемент
        offer = ET.SubElement(offers_el, 'offer')
        offer.set('id', sku)
        offer.set('available', 'true')

        # Ціна
        price_el = ET.SubElement(offer, 'price')
        price_el.text = str(price)

        # Наявність (availability має пріоритет над available)
        avail_el = ET.SubElement(offer, 'availability')
        avail_el.text = 'in_stock'

        # Стара ціна (ціна фіду якщо більша)
        if p['price_supplier'] and float(p['price_supplier']) > price:
            old_el = ET.SubElement(offer, 'price_old')
            old_el.text = str(float(p['price_supplier']))

        # Категорія
        cat_el = ET.SubElement(offer, 'category')
        cat_el.set('code', cat_id)
        cat_el.text = cat_name

        # Набір атрибутів (той самий код що і категорія)
        attr_el = ET.SubElement(offer, 'attribute_set')
        attr_el.set('code', cat_id)
        attr_el.text = cat_name

        # Назви
        name_ua_el = ET.SubElement(offer, 'name')
        name_ua_el.set('lang', 'ua')
        name_ua_el.text = name_uk

        name_ru_el = ET.SubElement(offer, 'name')
        name_ru_el.set('lang', 'ru')
        name_ru_el.text = name_ru

        # Фото (max 10)
        for pic_url in pictures[:10]:
            if pic_url:
                pic_el = ET.SubElement(offer, 'picture')
                pic_el.text = pic_url

        # Описи
        if desc_ua:
            desc_ua_el = ET.SubElement(offer, 'description')
            desc_ua_el.set('lang', 'ua')
            desc_ua_el.text = desc_ua[:3000]  # обмеження

        if desc_ru:
            desc_ru_el = ET.SubElement(offer, 'description')
            desc_ru_el.set('lang', 'ru')
            desc_ru_el.text = desc_ru[:3000]

        # Виробник
        vendor_el = ET.SubElement(offer, 'vendor')
        vendor_el.set('code', VENDOR_CODE)
        vendor_el.text = VENDOR_NAME

        # Країна
        country_el = ET.SubElement(offer, 'country_of_origin')
        country_el.set('code', COUNTRY_CODE)
        country_el.text = COUNTRY_NAME_UA

        # Обов'язкові параметри
        for paramcode, valuecode, name, value, is_cdata in COMMON_PARAMS:
            param_el = ET.SubElement(offer, 'param')
            param_el.set('name', name)
            param_el.set('paramcode', paramcode)
            if valuecode:
                param_el.set('valuecode', valuecode)
            if is_cdata:
                param_el.text = value  # minidom загорне в CDATA якщо треба
            else:
                param_el.text = value

        # Габарити вже додані через COMMON_PARAMS як param

        count += 1

    # Форматуємо і зберігаємо
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    xml_str = ET.tostring(root, encoding='unicode', xml_declaration=False)
    # Красиве форматування
    pretty = minidom.parseString(
        '<?xml version="1.0" encoding="UTF-8"?>' + xml_str
    ).toprettyxml(indent='  ', encoding='UTF-8')

    with open(output_path, 'wb') as f:
        f.write(pretty)

    size_kb = os.path.getsize(output_path) // 1024
    logger.success(f'XML збережено: {output_path} ({count} товарів, {size_kb} KB)')
    return count


def generate_by_category(output_dir: str, confidence_filter: list = None) -> dict:
    """
    Генерує окремий XML файл для кожної категорії.
    Зручно для покрокового завантаження в кабінет.
    """
    os.makedirs(output_dir, exist_ok=True)

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute('''
        SELECT epicentr_category_name, COUNT(*) as cnt
        FROM my_products
        WHERE epicentr_category_id IS NOT NULL
          AND price_our > 0
          AND epicentr_confidence IN ('high','medium','low')
        GROUP BY epicentr_category_name
        ORDER BY cnt DESC
    ''')
    categories = cur.fetchall()
    cur.close(); conn.close()

    results = {}
    for cat in categories:
        cat_name = cat['epicentr_category_name']
        safe_name = cat_name.replace('/', '_').replace(' ', '_')[:50]
        output_path = os.path.join(output_dir, f'{safe_name}.xml')

        count = generate_xml(
            output_path=output_path,
            category_filter=cat_name,
            confidence_filter=confidence_filter
        )
        results[cat_name] = {'count': count, 'file': output_path}

    logger.success(f'Згенеровано {len(results)} XML файлів → {output_dir}')
    return results


# =============================================
# CLI
# =============================================

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Генератор XML для Єпіцентру')
    parser.add_argument('--output', type=str, default='/tmp/epicentr_import.xml',
                       help='Шлях для збереження XML')
    parser.add_argument('--output-dir', type=str,
                       help='Папка для XML файлів по категоріях')
    parser.add_argument('--by-category', action='store_true',
                       help='Генерувати окремий файл на кожну категорію')
    parser.add_argument('--category', type=str,
                       help='Фільтр по назві категорії')
    parser.add_argument('--limit', type=int,
                       help='Максимальна кількість товарів')
    parser.add_argument('--confidence', type=str, default='high,medium,low',
                       help='Рівні впевненості (high,medium,low)')
    args = parser.parse_args()

    confidence = [c.strip() for c in args.confidence.split(',')]

    if args.by_category:
        output_dir = args.output_dir or '/tmp/epicentr_xml'
        results = generate_by_category(output_dir, confidence)
        print(f'\nЗгенеровано категорій: {len(results)}')
        for cat, info in list(results.items())[:10]:
            print(f'  {info["count"]:4} товарів | {cat}')
    else:
        count = generate_xml(
            output_path=args.output,
            category_filter=args.category,
            limit=args.limit,
            confidence_filter=confidence
        )
        print(f'\n✅ XML готовий: {args.output} ({count} товарів)')
        print(f'Завантаж в Єпіцентр: Імпорт → Завантажити файл → вибрати XML')
