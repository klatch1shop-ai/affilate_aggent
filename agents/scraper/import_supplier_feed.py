import os, sys, json, re, requests
from loguru import logger
from xml.etree import ElementTree as ET

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
from shared.utils.db import get_connection

FEED_URL = "https://toptul.online/products_feed.xml?hash_tag=442309995a1416e3104d287504a1846f&sales_notes=&product_ids=&label_ids=3882792&exclude_fields=&html_description=1&yandex_cpa=&process_presence_sure=&languages=uk%2Cru&group_ids="

def download_feed(url: str) -> bytes:
    logger.info(f"[IMPORT] Downloading feed...")
    resp = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    logger.success(f"[IMPORT] Downloaded {len(resp.content)//1024}KB")
    return resp.content

def parse_and_import(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    shop = root.find("shop")
    offers = shop.find("offers")

    conn = get_connection()
    cur = conn.cursor()

    # Додаємо нові колонки якщо нема
    cur.execute("""
        ALTER TABLE my_products
        ADD COLUMN IF NOT EXISTS price_supplier DECIMAL(12,2),
        ADD COLUMN IF NOT EXISTS pictures JSONB,
        ADD COLUMN IF NOT EXISTS params JSONB,
        ADD COLUMN IF NOT EXISTS vendor VARCHAR(100)
    """)
    conn.commit()

    updated = 0
    skipped = 0

    for offer in offers.findall("offer"):
        sku = offer.get("id", "").strip()
        if not sku:
            continue

        # Ціна
        price_el = offer.find("price")
        price = float(price_el.text) if price_el is not None and price_el.text else 0

        # Фото
        pictures = [p.text for p in offer.findall("picture") if p.text]

        # Назва українська
        name_ua = None
        for tag in ["name_ua", "model_ua", "name", "model"]:
            el = offer.find(tag)
            if el is not None and el.text:
                name_ua = el.text.strip()
                break

        # Опис
        desc_ua = None
        for tag in ["description_ua", "description"]:
            el = offer.find(tag)
            if el is not None and el.text:
                desc_ua = el.text.strip()
                break

        # Параметри
        params = {}
        for param in offer.findall("param"):
            name = param.get("name", "")
            val = param.text or ""
            if name and val.strip():
                params[name] = val.strip()

        # Vendor
        vendor_el = offer.find("vendor")
        vendor = vendor_el.text.strip() if vendor_el is not None else "TOPTUL"

        # Оновлюємо існуючий запис або пропускаємо
        cur.execute("""
            UPDATE my_products SET
                price_supplier = %s,
                pictures = %s,
                params = %s,
                vendor = %s,
                description_raw = COALESCE(NULLIF(description_raw,''), %s),
                name_uk = COALESCE(NULLIF(name_uk,''), %s)
            WHERE sku = %s
        """, (
            price,
            json.dumps(pictures),
            json.dumps(params),
            vendor,
            desc_ua,
            name_ua,
            sku
        ))

        if cur.rowcount > 0:
            updated += 1
        else:
            skipped += 1

    conn.commit()
    cur.close()
    conn.close()

    logger.success(f"[IMPORT] Done: {updated} updated, {skipped} not found in DB")
    return updated

if __name__ == "__main__":
    xml_bytes = download_feed(FEED_URL)
    count = parse_and_import(xml_bytes)
    print(f"✅ Імпортовано: {count} товарів")
