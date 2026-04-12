import os
import sys
import json
import time
import random
import asyncio
from loguru import logger
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from shared.utils.db import log_event, update_agent_status, get_connection
from shared.utils.redis_queue import pop_task, push_task

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

AGENT_NAME = "scraper"

# ── Fingerprint / anti-bot helpers ──────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]

async def human_delay(min_ms: int = 800, max_ms: int = 2800):
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))

async def human_scroll(page, steps: int = 4):
    for _ in range(steps):
        await page.mouse.wheel(0, random.randint(300, 700))
        await human_delay(300, 900)

async def build_stealth_context(playwright):
    ua = random.choice(USER_AGENTS)
    vp = random.choice(VIEWPORTS)
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-infobars",
        ]
    )
    context = await browser.new_context(
        user_agent=ua,
        viewport=vp,
        locale="uk-UA",
        timezone_id="Europe/Kiev",
        extra_http_headers={
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        }
    )
    # Маскуємо webdriver через JS
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        window.chrome = { runtime: {} };
    """)
    return browser, context

# ── Rozetka парсер ───────────────────────────────────────

async def parse_rozetka(category_url: str, max_items: int = 10) -> list:
    from playwright.async_api import async_playwright
    results = []
    logger.info(f"[SCRAPER] Rozetka: {category_url}")

    async with async_playwright() as p:
        browser, context = await build_stealth_context(p)
        page = await context.new_page()
        try:
            await page.goto(category_url, wait_until="domcontentloaded", timeout=30000)
            await human_delay(1500, 3000)
            await human_scroll(page, steps=3)
            await human_delay(800, 1500)

            items = await page.query_selector_all("li.catalog-grid__cell")
            logger.info(f"[SCRAPER] Found {len(items)} items on page")

            for item in items[:max_items]:
                try:
                    title_el = await item.query_selector("span.goods-tile__title")
                    price_el = await item.query_selector("span.goods-tile__price-value")
                    link_el  = await item.query_selector("a.goods-tile__heading")

                    title = await title_el.inner_text() if title_el else "N/A"
                    price_raw = await price_el.inner_text() if price_el else "0"
                    href  = await link_el.get_attribute("href") if link_el else ""

                    price = float(price_raw.replace("\u00a0", "").replace(",", ".").replace("грн", "").strip() or 0)

                    results.append({
                        "marketplace": "rozetka",
                        "title": title.strip(),
                        "price": price,
                        "url": href,
                    })
                except Exception as e:
                    logger.warning(f"Item parse error: {e}")
                    continue

        except Exception as e:
            logger.error(f"[SCRAPER] Page error: {e}")
        finally:
            await browser.close()

    return results

# ── Prom.ua парсер ───────────────────────────────────────

async def parse_prom(search_query: str, max_items: int = 10) -> list:
    from playwright.async_api import async_playwright
    url = f"https://prom.ua/search?search_term={search_query.replace(' ', '+')}"
    results = []
    logger.info(f"[SCRAPER] Prom: {url}")

    async with async_playwright() as p:
        browser, context = await build_stealth_context(p)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await human_delay(2000, 3500)
            await human_scroll(page, steps=3)

            items = await page.query_selector_all("div[data-qaid='product_gallery_item']")
            logger.info(f"[SCRAPER] Found {len(items)} items on page")

            for item in items[:max_items]:
                try:
                    title_el = await item.query_selector("span[data-qaid='product_name']")
                    price_el = await item.query_selector("span[data-qaid='product_price']")
                    link_el  = await item.query_selector("a[data-qaid='product_link']")

                    title = await title_el.inner_text() if title_el else "N/A"
                    price_raw = await price_el.inner_text() if price_el else "0"
                    href  = await link_el.get_attribute("href") if link_el else ""

                    price = float(price_raw.replace("\u00a0", "").replace(",", ".").replace("грн", "").strip() or 0)

                    results.append({
                        "marketplace": "prom",
                        "title": title.strip(),
                        "price": price,
                        "url": href,
                    })
                except Exception as e:
                    logger.warning(f"Item parse error: {e}")
                    continue

        except Exception as e:
            logger.error(f"[SCRAPER] Page error: {e}")
        finally:
            await browser.close()

    return results

# ── Prom.ua REST API ─────────────────────────────────────

async def prom_api_get_products(max_items: int = None) -> list:
    import aiohttp
    token = os.getenv("PROM_API_TOKEN")
    if not token:
        logger.error("[SCRAPER] PROM_API_TOKEN not set")
        return []

    api_url = "https://my.prom.ua/api/v1/products/list"
    headers = {"Authorization": f"Bearer {token}"}
    all_products = []
    page_from_id = None

    async with aiohttp.ClientSession() as session:
        while True:
            params = {"limit": 100}
            if page_from_id is not None:
                params["page_from_id"] = page_from_id

            async with session.get(api_url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"[SCRAPER] Prom API HTTP {resp.status}: {text[:200]}")
                    break
                data = await resp.json()

            page = data.get("products", [])
            if not page:
                break

            prev_count = len(all_products)
            for p in page:
                all_products.append({
                    "marketplace": "prom",
                    "title": p.get("name", "N/A"),
                    "price": float(p.get("price") or 0),
                    "url": p.get("url", ""),
                })

            new_count = len(all_products)
            if (new_count // 500) > (prev_count // 500):
                logger.info(f"[SCRAPER] Prom API: {new_count} products fetched so far...")

            if max_items and new_count >= max_items:
                all_products = all_products[:max_items]
                break

            if len(page) < 100:
                break

            page_from_id = page[-1]["id"]

    logger.info(f"[SCRAPER] Prom API: done, total {len(all_products)} products")
    return all_products

# ── Збереження в БД ──────────────────────────────────────

def save_products(products: list):
    if not products:
        return
    conn = get_connection()
    cur = conn.cursor()
    saved = 0
    for p in products:
        try:
            cur.execute("""
                INSERT INTO scraped_products (marketplace, title, price, url)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (p["marketplace"], p["title"], p["price"], p["url"]))
            saved += 1
        except Exception as e:
            logger.warning(f"Save error: {e}")
    conn.commit()
    cur.close()
    conn.close()
    logger.success(f"[SCRAPER] Saved {saved} products to DB")

# ── Головний обробник задач ──────────────────────────────

async def handle_task(task: dict):
    task_type = task.get("type", "")
    description = task.get("description", "")
    logger.info(f"[SCRAPER] Task: {task_type} — {description}")
    update_agent_status(AGENT_NAME, "busy")
    log_event(AGENT_NAME, "INFO", f"Started: {task_type}", task)

    products = []

    if "rozetka" in description.lower():
        url = "https://rozetka.com.ua/ua/notebooks/c80004/"
        if "електронік" in description.lower():
            url = "https://rozetka.com.ua/ua/electronics/c4627901/"
        products = await parse_rozetka(url, max_items=10)

    elif task_type == "prom_api":
        products = await prom_api_get_products()

    elif "prom" in description.lower():
        query = description.replace("prom", "").strip()
        products = await parse_prom(query, max_items=10)

    else:
        products = await parse_rozetka(
            "https://rozetka.com.ua/ua/electronics/c4627901/", max_items=10
        )

    save_products(products)
    log_event(AGENT_NAME, "INFO", f"Completed: {len(products)} products", {"count": len(products)})
    update_agent_status(AGENT_NAME, "idle")
    logger.success(f"[SCRAPER] Done: {len(products)} products")
    return products

def listen_loop():
    logger.info("[SCRAPER] Listening queue:scraper ...")
    update_agent_status(AGENT_NAME, "idle")
    while True:
        task = pop_task("queue:scraper", timeout=5)
        if task:
            asyncio.run(handle_task(task))

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Тест парсингу Rozetka")
    parser.add_argument("--listen", action="store_true", help="Слухати чергу")
    args = parser.parse_args()

    if args.test:
        products = asyncio.run(parse_rozetka(
            "https://rozetka.com.ua/ua/electronics/c4627901/", max_items=5
        ))
        print(json.dumps(products, ensure_ascii=False, indent=2))
    elif args.listen:
        listen_loop()
    else:
        parser.print_help()
