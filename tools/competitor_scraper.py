#!/usr/bin/env python3
"""
competitor_scraper.py — збирає товари продавця на Rozetka.

Використання:
    python3 tools/competitor_scraper.py
    python3 tools/competitor_scraper.py --seller ttul --pages 5
    python3 tools/competitor_scraper.py --no-save   # тільки вивід у консоль
"""

import asyncio
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import argparse
from loguru import logger
from dotenv import load_dotenv
from shared.utils.db import get_connection

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

# ── Константи ─────────────────────────────────────────────

DEFAULT_SELLER = "ttul"
SELLER_URL = "https://rozetka.com.ua/ua/seller/{seller}/goods/"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]

# ── Stealth-браузер ───────────────────────────────────────

async def build_stealth_context(playwright, headless: bool = True):
    from playwright_stealth import Stealth

    browser = await playwright.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-infobars",
        ],
    )
    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport=random.choice(VIEWPORTS),
        locale="uk-UA",
        timezone_id="Europe/Kiev",
        extra_http_headers={
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        },
    )
    # Зберігаємо stealth instance для застосування до кожної нової page
    context._stealth = Stealth()
    return browser, context


async def human_delay(min_ms: int = 700, max_ms: int = 2000):
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


async def human_scroll(page, steps: int = 4):
    for _ in range(steps):
        await page.mouse.wheel(0, random.randint(300, 700))
        await human_delay(250, 700)


# ── DDL ───────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS competitor_products (
    id              SERIAL PRIMARY KEY,
    seller          TEXT        NOT NULL,
    title           TEXT        NOT NULL,
    price           NUMERIC(12, 2),
    category        TEXT,
    url             TEXT        UNIQUE,
    reviews_count   INTEGER     DEFAULT 0,
    scraped_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_competitor_seller
    ON competitor_products (seller);
CREATE INDEX IF NOT EXISTS idx_competitor_scraped_at
    ON competitor_products (scraped_at);
"""

def ensure_table():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    cur.close()
    conn.close()
    logger.debug("Table competitor_products: OK")


# ── Парсинг однієї сторінки товарів ──────────────────────

async def parse_page(page, seller: str, debug_dump: bool = False) -> list[dict]:
    """Витягує всі товари з поточної сторінки пагінації."""
    products = []

    # Debug: зберігаємо HTML після завантаження
    if debug_dump:
        try:
            html = await page.content()
            Path("/tmp/rozetka_debug.html").write_text(html, encoding="utf-8")
            logger.debug("HTML збережено в /tmp/rozetka_debug.html")
        except Exception as e:
            logger.warning(f"Не вдалось зберегти debug HTML: {e}")

    # Чекаємо поки картки завантажаться (Angular-компонент rz-product-tile)
    try:
        await page.wait_for_selector("rz-product-tile", timeout=30000)
    except Exception:
        logger.warning("Картки товарів не знайдені на сторінці")
        return products

    await human_scroll(page, steps=5)
    await human_delay(500, 1000)

    items = await page.query_selector_all("rz-product-tile")
    logger.debug(f"  Карток на сторінці: {len(items)}")

    for item in items:
        try:
            # Назва + URL (один елемент a.tile-title)
            title_el = await item.query_selector("a.tile-title")
            title = (await title_el.inner_text()).strip() if title_el else None
            if not title:
                continue
            url = await title_el.get_attribute("href") if title_el else None

            # Ціна
            price_el = await item.query_selector("[class*='price']")
            price_raw = (await price_el.inner_text()).strip() if price_el else "0"
            price = float(
                price_raw
                .replace("\u00a0", "")
                .replace("\xa0", "")
                .replace(",", ".")
                .replace("грн", "")
                .replace("₴", "")
                .strip() or 0
            )

            # Категорія з URL: https://rozetka.com.ua/ua/<category>/<id>/p<id>/
            category = None
            if url:
                parts = [p for p in url.split("/") if p and p not in ("ua", "https:", "rozetka.com.ua")]
                if parts:
                    category = parts[0]

            # Кількість відгуків
            reviews_el = await item.query_selector(".rating-block-rating")
            reviews_count = 0
            if reviews_el:
                raw = (await reviews_el.inner_text()).strip()
                digits = "".join(filter(str.isdigit, raw))
                reviews_count = int(digits) if digits else 0

            products.append({
                "seller": seller,
                "title": title,
                "price": price,
                "category": category,
                "url": url,
                "reviews_count": reviews_count,
            })

        except Exception as e:
            logger.warning(f"  Помилка парсингу картки: {e}")
            continue

    return products


# ── Пагінація ─────────────────────────────────────────────

async def get_total_pages(page) -> int:
    """Визначає кількість сторінок пагінації (rz-paginator)."""
    try:
        # Збираємо всі a.page всередині rz-paginator і беремо останній href
        links = await page.query_selector_all("rz-paginator a.page")
        max_page = 1
        for link in links:
            href = await link.get_attribute("href") or ""
            if "page=" in href:
                num = int(href.split("page=")[-1].split("&")[0])
                if num > max_page:
                    max_page = num
        return max_page
    except Exception:
        return 1


# ── Головний скрапер ──────────────────────────────────────

async def scrape_seller(seller: str, max_pages: int | None = None, headless: bool = True) -> list[dict]:
    from playwright.async_api import async_playwright

    base_url = SELLER_URL.format(seller=seller)
    all_products: list[dict] = []

    # Seller ID потрібен для API запитів (отримаємо з першої сторінки)
    seller_api_id: str | None = None

    async with async_playwright() as p:
        browser, context = await build_stealth_context(p, headless=headless)
        page = await context.new_page()
        # Застосовуємо stealth до сторінки
        if hasattr(context, '_stealth'):
            await context._stealth.apply_stealth_async(page)

        # ── Перехоплення API відповідей catalog-api ──────
        api_data: dict[int, list[dict]] = {}

        async def on_response(resp):
            if 'catalog-api.rozetka' in resp.url and resp.status == 200:
                try:
                    body = await resp.body()
                    data = json.loads(body)
                    goods = (data.get('data') or {}).get('goods', [])
                    # Визначаємо номер сторінки з URL
                    pnum = 1
                    if 'page:' in resp.url:
                        pnum = int(resp.url.split('page:')[1].split('&')[0])
                    if goods:
                        api_data[pnum] = goods
                        logger.debug(f"  API page {pnum}: {len(goods)} товарів")
                except Exception as e:
                    logger.debug(f"  API parse error: {e}")

        page.on('response', on_response)

        try:
            # ── Перша сторінка (SSR — парсимо DOM) ──────
            logger.info(f"Відкриваю {base_url}")
            await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
            await human_delay(1500, 2500)

            total_pages = await get_total_pages(page)
            if max_pages:
                total_pages = min(total_pages, max_pages)
            logger.info(f"Сторінок для обходу: {total_pages}")

            # Парсимо page 1 з DOM (SSR вже рендерений)
            products = await parse_page(page, seller, debug_dump=True)
            all_products.extend(products)
            logger.info(f"Стор. 1/{total_pages}: {len(products)} товарів")

            # ── Решта сторінок через API перехоплення ────
            for page_num in range(2, total_pages + 1):
                logger.info(f"Стор. {page_num}/{total_pages}")
                try:
                    api_data.pop(page_num, None)  # скидаємо старі дані

                    # Клікаємо пагінатор щоб Angular зробив API запит
                    link = await page.query_selector(
                        f"rz-paginator a.page[href*='page={page_num}']"
                    )
                    if link:
                        await link.click()
                    else:
                        await page.evaluate("""
                            () => {
                                const btn = document.querySelector(
                                    "[data-testid='pagination_to_next_page']:not(.disabled)"
                                );
                                if (btn) btn.click();
                            }
                        """)

                    # Чекаємо поки API відповідь буде перехоплена
                    for _ in range(40):  # до 8 секунд
                        if page_num in api_data:
                            break
                        await asyncio.sleep(0.2)

                    if page_num in api_data:
                        # Конвертуємо API дані у наш формат
                        products = _parse_api_goods(api_data[page_num], seller)
                    else:
                        # Fallback: парсимо DOM (якщо API не відповів)
                        logger.debug(f"  API не відповів, fallback DOM парсинг")
                        await page.wait_for_selector("rz-product-tile", timeout=20000)
                        await human_delay(1500, 2500)
                        products = await parse_page(page, seller)

                    all_products.extend(products)
                    logger.info(f"  +{len(products)} товарів  (всього: {len(all_products)})")

                except Exception as e:
                    logger.error(f"  Помилка на сторінці {page_num}: {e}")
                    continue

        finally:
            await browser.close()

    return all_products


def _parse_api_goods(goods: list[dict], seller: str) -> list[dict]:
    """Конвертує сирі дані catalog API у наш формат."""
    products = []
    for g in goods:
        try:
            title = g.get('title') or g.get('name') or ''
            if not title:
                continue

            # Ціна
            price_raw = g.get('price') or g.get('sell_price') or 0
            try:
                price = float(str(price_raw).replace('\xa0', '').replace(' ', '').replace(',', '.') or 0)
            except Exception:
                price = 0.0

            # URL
            url = g.get('href') or g.get('url') or ''

            # Категорія з URL
            category = None
            if url:
                parts = [p for p in url.split('/') if p and p not in ('ua', 'https:', 'rozetka.com.ua')]
                if parts:
                    category = parts[0]

            # Відгуки
            reviews_count = 0
            comments = g.get('comments_amount') or g.get('reviews_count') or 0
            if comments:
                try:
                    reviews_count = int(comments)
                except Exception:
                    pass

            products.append({
                'seller': seller,
                'title': title,
                'price': price,
                'category': category,
                'url': url,
                'reviews_count': reviews_count,
            })
        except Exception as e:
            logger.debug(f"  _parse_api_goods error: {e}")
    return products


# ── Збереження ────────────────────────────────────────────

def save_products(products: list[dict]) -> tuple[int, int]:
    """Повертає (saved, skipped)."""
    if not products:
        return 0, 0

    conn = get_connection()
    cur = conn.cursor()
    saved = skipped = 0

    for p in products:
        try:
            cur.execute(
                """
                INSERT INTO competitor_products
                    (seller, title, price, category, url, reviews_count, scraped_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE SET
                    price        = EXCLUDED.price,
                    reviews_count = EXCLUDED.reviews_count,
                    scraped_at   = EXCLUDED.scraped_at
                """,
                (
                    p["seller"], p["title"], p["price"],
                    p["category"], p["url"], p["reviews_count"],
                    datetime.utcnow(),
                ),
            )
            saved += 1
        except Exception as e:
            logger.warning(f"Помилка збереження: {e} | {p.get('url')}")
            skipped += 1

    conn.commit()
    cur.close()
    conn.close()
    return saved, skipped


# ── CLI ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Парсинг товарів продавця на Rozetka"
    )
    parser.add_argument(
        "--seller", default=DEFAULT_SELLER,
        help=f"Slug продавця (за замовчуванням: {DEFAULT_SELLER})",
    )
    parser.add_argument(
        "--pages", type=int, default=None,
        help="Максимальна кількість сторінок (за замовчуванням: всі)",
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="Не зберігати в БД, тільки вивести в консоль",
    )
    parser.add_argument(
        "--headful", action="store_true",
        help="Запустити браузер у видимому режимі (для ручного проходження Cloudflare)",
    )
    args = parser.parse_args()

    logger.info(f"Старт: seller={args.seller}, max_pages={args.pages or 'всі'}, headless={not args.headful}")

    products = asyncio.run(scrape_seller(args.seller, max_pages=args.pages, headless=not args.headful))

    if not products:
        logger.warning("Товарів не знайдено — перевір selector або доступність сайту")
        sys.exit(1)

    if args.no_save:
        for p in products:
            print(f"{p['price']:>10.2f} грн | {p['reviews_count']:>4} відг. | {p['title'][:60]}")
    else:
        ensure_table()
        saved, skipped = save_products(products)
        logger.success(
            f"Готово: знайдено {len(products)}, збережено {saved}, пропущено {skipped}"
        )

    # ── Звіт ──────────────────────────────────────────────
    if products:
        prices = [p["price"] for p in products if p["price"]]
        categories = {}
        for p in products:
            categories[p["category"] or "unknown"] = categories.get(p["category"] or "unknown", 0) + 1

        print("\n" + "=" * 55)
        print(f"  Продавець       : {args.seller}")
        print(f"  Всього товарів  : {len(products)}")
        if prices:
            print(f"  Мін. ціна       : {min(prices):.2f} грн")
            print(f"  Макс. ціна      : {max(prices):.2f} грн")
            print(f"  Середня ціна    : {sum(prices)/len(prices):.2f} грн")
        print(f"  Категорії ({len(categories)}):")
        for cat, cnt in sorted(categories.items(), key=lambda x: -x[1])[:10]:
            print(f"    {cnt:>4}x  {cat}")
        print("=" * 55)


if __name__ == "__main__":
    main()
