import os, sys, json, asyncio
import aiohttp
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
from shared.utils.db import get_connection

TOKEN = os.getenv("PROM_API_TOKEN")
API_URL = "https://my.prom.ua/api/v1/products/list"

def get_our_skus() -> set:
    """Отримуємо SKU які є в нашій БД"""
    from shared.utils.db import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT sku FROM my_products WHERE sku IS NOT NULL")
    skus = {r["sku"] for r in cur.fetchall()}
    cur.close(); conn.close()
    logger.info(f"[PROM] Our SKUs in DB: {len(skus)}")
    return skus

async def fetch_all_products() -> list:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    our_skus = get_our_skus()
    all_products = []
    page_from_id = None
    found = 0

    async with aiohttp.ClientSession() as session:
        while True:
            params = {"limit": 100}
            if page_from_id:
                params["page_from_id"] = page_from_id

            async with session.get(API_URL, headers=headers, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"[PROM] HTTP {resp.status}: {text[:200]}")
                    break
                data = await resp.json()

            page = data.get("products", [])
            if not page:
                break

            for p in page:
                sku = p.get("sku","").strip()
                if sku in our_skus:
                    all_products.append(p)
                    found += 1

            if found % 500 == 0 and found > 0:
                logger.info(f"[PROM] Found {found} matching products...")

            if len(page) < 100:
                break
            page_from_id = page[-1]["id"]

            # Якщо знайшли всі наші товари — зупиняємось
            if found >= len(our_skus):
                logger.info("[PROM] All our SKUs found, stopping")
                break

    logger.success(f"[PROM] Total found: {len(all_products)} matching products")
    return all_products

def import_to_db(products: list):
    conn = get_connection()
    cur = conn.cursor()

    # Додаємо колонки якщо нема
    cur.execute("""
        ALTER TABLE my_products
        ADD COLUMN IF NOT EXISTS price_supplier DECIMAL(12,2),
        ADD COLUMN IF NOT EXISTS pictures JSONB,
        ADD COLUMN IF NOT EXISTS params JSONB,
        ADD COLUMN IF NOT EXISTS vendor VARCHAR(100),
        ADD COLUMN IF NOT EXISTS prom_id BIGINT
    """)
    conn.commit()

    updated = 0
    inserted = 0

    for p in products:
        sku = p.get("sku", "").strip()
        if not sku:
            continue

        price = float(p.get("price") or 0)
        name_uk = p.get("name", "").strip()
        description = p.get("description", "") or ""
        presence = p.get("presence", "")
        prom_id = p.get("id")

        # Фото
        images = p.get("images", []) or []
        pictures = [img.get("url", "") for img in images if img.get("url")]

        # Параметри
        attrs = p.get("attributes", []) or []
        params = {}
        for attr in attrs:
            name = attr.get("name", "")
            val = attr.get("value", "")
            if name and val:
                params[name] = val

        # Категорія
        category = p.get("category", {}) or {}
        category_name = category.get("caption", "") or category.get("name", "")

        # stock_quantity
        stock = 10 if presence in ("available", "positive") else 0

        # Спробуємо оновити по SKU
        cur.execute("""
            UPDATE my_products SET
                price_supplier = %s,
                pictures = %s,
                params = %s,
                vendor = 'TOPTUL',
                prom_id = %s,
                name_uk = CASE WHEN name_uk IS NULL OR name_uk = '' THEN %s ELSE name_uk END,
                description_raw = CASE WHEN description_raw IS NULL OR description_raw = '' THEN %s ELSE description_raw END,
                category_epicentr = CASE WHEN category_epicentr IS NULL OR category_epicentr = '' THEN %s ELSE category_epicentr END,
                status = 'processed'
            WHERE sku = %s
        """, (price, json.dumps(pictures), json.dumps(params),
              prom_id, name_uk, description, category_name, sku))

        if cur.rowcount > 0:
            updated += 1
        else:
            # Вставляємо новий
            cur.execute("""
                INSERT INTO my_products (sku, name_uk, description_raw, category_epicentr,
                    price_supplier, pictures, params, vendor, prom_id, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'TOPTUL', %s, 'processed')
                ON CONFLICT (sku) DO NOTHING
            """, (sku, name_uk, description, category_name,
                  price, json.dumps(pictures), json.dumps(params), prom_id))
            inserted += 1

    conn.commit()
    cur.close()
    conn.close()
    logger.success(f"[PROM] DB: {updated} updated, {inserted} inserted")
    return updated, inserted

async def main():
    products = await fetch_all_products()
    updated, inserted = import_to_db(products)
    print(f"\n✅ Готово: {updated} оновлено, {inserted} додано")
    print(f"   Всього в Prom: {len(products)} товарів")

if __name__ == "__main__":
    asyncio.run(main())
