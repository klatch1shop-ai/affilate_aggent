import os, sys, json, re
from xml.etree import ElementTree as ET
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from dotenv import load_dotenv
load_dotenv('/home/tekken/agent-system/.env')
from shared.utils.db import get_connection

FEED_FILE = "/home/tekken/agent-system/data/prom_feed.xml"

def parse_and_import():
    logger.info(f"[IMPORT] Parsing {FEED_FILE}...")
    tree = ET.parse(FEED_FILE)
    root = tree.getroot()
    shop = root.find('shop')
    offers = shop.find('offers').findall('offer')
    logger.info(f"[IMPORT] Found {len(offers)} offers")

    conn = get_connection()
    cur = conn.cursor()

    # Додаємо колонки якщо нема
    cur.execute("""
        ALTER TABLE my_products
        ADD COLUMN IF NOT EXISTS price_supplier DECIMAL(12,2),
        ADD COLUMN IF NOT EXISTS pictures JSONB,
        ADD COLUMN IF NOT EXISTS params JSONB,
        ADD COLUMN IF NOT EXISTS vendor VARCHAR(100),
        ADD COLUMN IF NOT EXISTS prom_id BIGINT,
        ADD COLUMN IF NOT EXISTS availability VARCHAR(20)
    """)
    conn.commit()

    updated = 0
    inserted = 0
    skipped = 0

    for offer in offers:
        prom_id = offer.get('id')
        available = offer.get('available', 'true')

        # SKU/артикул
        # SKU в vendorCode або article
        sku = None
        for tag in ['vendorCode', 'article']:
            el = offer.find(tag)
            if el is not None and el.text and el.text.strip():
                sku = el.text.strip()
                break
        if not sku:
            skipped += 1
            continue

        # Ціна
        price_el = offer.find('price')
        price = float(price_el.text) if price_el is not None and price_el.text else 0

        # Назва українська
        name_ua = None
        for tag in ['name_ua', 'model_ua', 'name', 'model']:
            el = offer.find(tag)
            if el is not None and el.text and el.text.strip():
                name_ua = el.text.strip()
                break

        # Опис
        desc_ua = None
        for tag in ['description_ua', 'description']:
            el = offer.find(tag)
            if el is not None and el.text and el.text.strip():
                desc_ua = el.text.strip()[:5000]
                break

        # Фото
        pictures = []
        for pic in offer.findall('picture'):
            if pic.text and pic.text.strip():
                url = pic.text.strip()
                if url.startswith('http'):
                    pictures.append(url)

        # Параметри
        params = {}
        param_list = []
        for param in offer.findall('param'):
            name = param.get('name', '')
            val = param.text or ''
            if name and val.strip():
                params[name] = val.strip()
            elif val.strip():
                param_list.append(val.strip())
        if param_list:
            params['_values'] = param_list

        # Vendor
        vendor_el = offer.find('vendor')
        vendor = vendor_el.text.strip() if vendor_el is not None and vendor_el.text else 'TOPTUL'

        # Stock
        stock_el = offer.find('stock_quantity')
        if stock_el is None:
            stock_el = offer.find('quantity_in_stock')
        stock = int(stock_el.text) if stock_el is not None and stock_el.text else (10 if available == 'true' else 0)

        # Категорія з прому
        cat_id = offer.find('categoryId')

        # Оновлюємо існуючий запис
        cur.execute("""
            UPDATE my_products SET
                price_supplier = %s,
                pictures = %s,
                params = %s,
                vendor = %s,
                prom_id = %s,
                availability = %s,
                name_uk = CASE WHEN name_uk IS NULL OR name_uk = '' THEN %s ELSE name_uk END,
                description_raw = CASE WHEN description_raw IS NULL OR description_raw = '' THEN %s ELSE description_raw END,
                status = 'processed'
            WHERE sku = %s
        """, (
            price, json.dumps(pictures), json.dumps(params),
            vendor, prom_id, available,
            name_ua, desc_ua, sku
        ))

        if cur.rowcount > 0:
            updated += 1
        else:
            # Вставляємо новий
            cur.execute("""
                INSERT INTO my_products
                    (sku, name_uk, description_raw, price_supplier, pictures, params, vendor, prom_id, availability, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'processed')
                ON CONFLICT (sku) DO UPDATE SET
                    price_supplier = EXCLUDED.price_supplier,
                    pictures = EXCLUDED.pictures,
                    params = EXCLUDED.params,
                    vendor = EXCLUDED.vendor,
                    prom_id = EXCLUDED.prom_id,
                    availability = EXCLUDED.availability,
                    status = 'processed'
            """, (sku, name_ua, desc_ua, price, json.dumps(pictures),
                  json.dumps(params), vendor, prom_id, available))
            inserted += 1

        if (updated + inserted) % 500 == 0:
            conn.commit()
            logger.info(f"[IMPORT] Progress: {updated} updated, {inserted} inserted, {skipped} skipped")

    conn.commit()
    cur.close()
    conn.close()

    logger.success(f"[IMPORT] Done: {updated} updated, {inserted} inserted, {skipped} skipped")
    return updated, inserted

if __name__ == "__main__":
    updated, inserted = parse_and_import()
    print(f"\n✅ Імпорт завершено: {updated} оновлено, {inserted} додано")
