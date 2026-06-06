import os, sys, json, re
from xml.etree import ElementTree as ET
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

FEED_FILE = "/home/tek/agent-system/data/carvol_feed.xml"

def fix_pic_url(url: str) -> str:
    """Виправляє URL фото з Prom CDN на прямий"""
    if not url:
        return ""
    # Prom CDN трансформації — беремо оригінальний ID
    # https://images.prom.ua/WkSMubxVO=/6304575772_k → потрібне пряме посилання
    # Спробуємо витягнути ID файлу
    match = re.search(r'/(\d+)_', url)
    if match:
        file_id = match.group(1)
        return f"https://images.prom.ua/{file_id}_b.jpg"
    return url

def check_name_unique(names: set, name: str, sku: str) -> str:
    """Робить назву унікальною якщо є дублі"""
    if name in names:
        # Додаємо артикул якщо не унікальна
        new_name = f"{name} ({sku})"
        if new_name in names:
            new_name = f"{name} {sku}"
        name = new_name
    names.add(name)
    return name

def parse_and_import():
    logger.info(f"[CARVOL] Parsing {FEED_FILE}...")
    tree = ET.parse(FEED_FILE)
    root = tree.getroot()
    shop = root.find('shop')
    offers = shop.find('offers').findall('offer')
    logger.info(f"[CARVOL] Found {len(offers)} offers")

    conn = get_connection()
    cur = conn.cursor()

    inserted = 0
    updated = 0
    skipped = 0
    names_seen = set()

    for offer in offers:
        try:
            external_id = offer.get('id', '').strip()
            available = offer.get('available', 'true') == 'true'

            article_el = offer.find('article')
            article = article_el.text.strip() if article_el is not None and article_el.text else external_id

            price_el = offer.find('price')
            price = float(price_el.text.replace(',','.')) if price_el is not None and price_el.text else 0

            name_ua_el = offer.find('name_ua')
            name_ua = name_ua_el.text.strip() if name_ua_el is not None and name_ua_el.text else ""

            # Унікальність назви
            name_ua = check_name_unique(names_seen, name_ua, article)

            desc_ua_el = offer.find('description_ua')
            desc_ua = desc_ua_el.text.strip() if desc_ua_el is not None and desc_ua_el.text else ""
            # Очищаємо від HTML
            desc_ua = re.sub(r'<[^>]+>', ' ', desc_ua)
            desc_ua = re.sub(r'\s+', ' ', desc_ua).strip()[:5000]

            vendor_el = offer.find('vendor')
            vendor = vendor_el.text.strip() if vendor_el is not None and vendor_el.text else ""

            category_el = offer.find('categoryId')
            category_id = category_el.text.strip() if category_el is not None and category_el.text else ""

            stock_el = offer.find('stock_quantity')
            stock = int(stock_el.text) if stock_el is not None and stock_el.text else 0

            # Фото — виправляємо URL
            pictures = []
            for pic in offer.findall('picture'):
                if pic.text and pic.text.strip():
                    fixed_url = fix_pic_url(pic.text.strip())
                    if fixed_url:
                        pictures.append(fixed_url)

            # Параметри
            params = {}
            for param in offer.findall('param'):
                name = param.get('name', '').strip()
                val = param.text.strip() if param.text else ''
                if name and val:
                    params[name] = val

            has_params = len(params) >= 3

            cur.execute("""
                INSERT INTO carvol_products
                    (external_id, article, name_ua, description_ua, vendor,
                     price, category_id, pictures, params, stock_quantity,
                     available, has_params, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'new')
                ON CONFLICT (external_id) DO UPDATE SET
                    price = EXCLUDED.price,
                    stock_quantity = EXCLUDED.stock_quantity,
                    available = EXCLUDED.available,
                    params = EXCLUDED.params,
                    status = 'updated'
            """, (
                external_id, article, name_ua, desc_ua, vendor,
                price, category_id, json.dumps(pictures),
                json.dumps(params), stock, available, has_params
            ))

            if cur.rowcount == 1:
                inserted += 1
            else:
                updated += 1

            if (inserted + updated) % 500 == 0:
                conn.commit()
                logger.info(f"[CARVOL] Progress: {inserted} inserted, {updated} updated")

        except Exception as e:
            logger.error(f"[CARVOL] Error {external_id}: {e}")
            skipped += 1

    conn.commit()
    cur.close()
    conn.close()

    logger.success(f"[CARVOL] Done: {inserted} inserted, {updated} updated, {skipped} skipped")
    return inserted, updated

if __name__ == "__main__":
    inserted, updated = parse_and_import()
    print(f"\n✅ Імпорт: {inserted} нових, {updated} оновлених")

    # Статистика
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT has_params, COUNT(*) FROM carvol_products GROUP BY has_params")
    for r in cur.fetchall():
        print(f"  has_params={r['has_params']}: {r['count']} товарів")
    cur.execute("SELECT vendor, COUNT(*) as cnt FROM carvol_products GROUP BY vendor ORDER BY cnt DESC LIMIT 5")
    print("\nТоп бренди:")
    for r in cur.fetchall():
        print(f"  {r['vendor']}: {r['cnt']}")
    cur.close()
    conn.close()
