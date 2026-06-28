#!/usr/bin/env python3
"""
epicentr_competitor_scraper.py — HTTP-парсер карток конкурентів на epicentrk.ua.

Базовий клас BaseHttpScraper реюзабельний для будь-якого SSR-сайту без Cloudflare.
EpicentrPublicScraper реалізує конкретні селектори для epicentrk.ua.
Для Rozetka/Prom (Cloudflare-захист) використовуй playwright_base.py.

Результати зберігаються в таблицю competitor_prices (розширюється міграцією при запуску).

Використання:
    python3 tools/epicentr_competitor_scraper.py --query "Teyes CC3 2DIN"
    python3 tools/epicentr_competitor_scraper.py --query "Автомагнітола" --limit 5 --parse-cards
    python3 tools/epicentr_competitor_scraper.py --url "https://epicentrk.ua/ua/shop/mplc-*.html"
    python3 tools/epicentr_competitor_scraper.py --query "Carav рамка" --no-save --verbose
"""

import argparse
import json
import os
import re
import sys
import time
import random
from datetime import datetime
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

try:
    from shared.utils.db import get_connection
    HAS_DB = True
except ImportError:
    HAS_DB = False

BASE_URL = "https://epicentrk.ua"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

# ── Міграція схеми ────────────────────────────────────────────────────────────

MIGRATION_SQL = """
ALTER TABLE competitor_prices
    ALTER COLUMN sku DROP NOT NULL;

ALTER TABLE competitor_prices
    ADD COLUMN IF NOT EXISTS title        TEXT,
    ADD COLUMN IF NOT EXISTS vendor       VARCHAR(200),
    ADD COLUMN IF NOT EXISTS specs_json   TEXT,
    ADD COLUMN IF NOT EXISTS photos_json  TEXT,
    ADD COLUMN IF NOT EXISTS search_query VARCHAR(300),
    ADD COLUMN IF NOT EXISTS category_id  INTEGER,
    ADD COLUMN IF NOT EXISTS category_name VARCHAR(200),
    ADD COLUMN IF NOT EXISTS external_id  VARCHAR(100);
"""

def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(MIGRATION_SQL)
    conn.commit()


# ── Базовий HTTP-скрейпер ─────────────────────────────────────────────────────

class BaseHttpScraper:
    """
    Базовий HTTP-скрейпер для SSR-сайтів без Cloudflare.
    Для адаптації під новий маркетплейс — успадкуй і перевизнач
    search() та parse_card() з власними селекторами.

    Призначений для:
    - epicentrk.ua (підклас EpicentrPublicScraper нижче)
    - Будь-який інший SSR-сайт без захисту від ботів

    Для Rozetka / Prom / Khoroshop (Cloudflare) — використовуй playwright_base.py.
    """

    MARKETPLACE = "generic"

    def __init__(self, delay_range=(1.0, 2.5), max_retries=3):
        self.delay_range = delay_range
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
        })

    def _get(self, url: str, params: dict = None) -> BeautifulSoup | None:
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=15)
                resp.raise_for_status()
                time.sleep(random.uniform(*self.delay_range))
                return BeautifulSoup(resp.text, "html.parser")
            except requests.RequestException as e:
                logger.warning(f"Attempt {attempt+1}/{self.max_retries} failed for {url}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
        return None

    def search(self, query: str, max_results: int = 20) -> list[dict]:
        raise NotImplementedError

    def parse_card(self, url: str) -> dict | None:
        raise NotImplementedError

    def find_competitors(
        self,
        query: str,
        max_results: int = 10,
        parse_cards: bool = False,
    ) -> list[dict]:
        """
        Шукає товари за запитом і повертає список карток.
        parse_cards=True — додатково завантажує кожну картку (повільніше, але більше даних).
        """
        results = self.search(query, max_results=max_results)
        if not parse_cards:
            return results

        enriched = []
        for item in results:
            card = self.parse_card(item["url"])
            if card:
                card["search_query"] = query
                enriched.append(card)
            else:
                item["search_query"] = query
                enriched.append(item)
        return enriched


# ── Epicentr-специфічна реалізація ───────────────────────────────────────────

class EpicentrPublicScraper(BaseHttpScraper):
    """
    Парсер публічних сторінок epicentrk.ua.

    Сайт: Nuxt.js SSR, без Cloudflare з нашого серверного IP.
    Тестовано: 2026-06-28 — HTTP 200 без блокування.

    Структура пошуку:  button[data-product-card-action="favorite"] → aria-label (назва)
                       a[data-product-picture] → href (URL картки)
                       img[src*="cdn.27.ua"] → фото в результатах

    Структура картки:  window.dataLayer.push({...}) → price, vendor, categoryId
                       dl > div > dt + dd → характеристики (19+ полів)
                       img[src*="cdn.27.ua"] → всі фото (14+)
                       h1 → повна назва
    """

    MARKETPLACE = "epicentr"
    SEARCH_URL = "https://epicentrk.ua/ua/search/"

    def search(self, query: str, max_results: int = 20) -> list[dict]:
        """
        Шукає товари на epicentrk.ua і повертає список з назвою, URL, фото.
        Ціна в пошуку відсутня — потрібен parse_card() для її отримання.
        """
        encoded_query = quote_plus(query)
        url = f"{self.SEARCH_URL}?q={encoded_query}"
        logger.info(f"Searching: {url}")
        soup = self._get(url)
        if not soup:
            return []

        results = []
        buttons = soup.find_all(attrs={"data-product-card-action": "favorite"})
        logger.info(f"Found {len(buttons)} product cards on search page")

        for btn in buttons[:max_results]:
            title = btn.get("aria-label", "").replace("Додати в обране товар: ", "").strip()
            card_div = btn.parent.parent.parent

            link_el = card_div.find("a", attrs={"data-product-picture": True})
            if not link_el:
                link_el = card_div.find("a", href=lambda h: h and "/ua/shop/mplc-" in h)
            product_url = urljoin(BASE_URL, link_el["href"]) if link_el else None

            img = card_div.find("img", src=lambda s: s and "cdn.27.ua" in s)
            photo = img["src"] if img else None

            results.append({
                "title": title,
                "url": product_url,
                "photo_preview": photo,
                "marketplace": self.MARKETPLACE,
                "search_query": query,
            })

        return results

    def parse_card(self, url: str) -> dict | None:
        """
        Парсить повну картку товару на epicentrk.ua.
        Повертає: title, price, vendor, category_id, category_name, specs (dict),
                  photos (list), in_stock, external_id, url.
        """
        if not url:
            return None
        logger.info(f"Parsing card: {url}")
        soup = self._get(url)
        if not soup:
            return None

        result = {"url": url, "marketplace": self.MARKETPLACE}

        # Назва
        h1 = soup.find("h1")
        result["title"] = h1.get_text(strip=True) if h1 else ""

        # Ціна, бренд, категорія, доступність — з dataLayer (найнадійніше)
        datalayer_match = re.search(
            r'window\.dataLayer\.push\((\{[^)]+\})\)',
            soup.decode() if hasattr(soup, 'decode') else str(soup)
        )
        if datalayer_match:
            try:
                dl = json.loads(datalayer_match.group(1))
                result["price"] = float(dl.get("productPrice") or 0) or None
                result["vendor"] = dl.get("vendorName")
                result["category_id"] = dl.get("categoryId")
                result["category_name"] = dl.get("categoryName")
                result["in_stock"] = bool(dl.get("productAvailable", True))
                result["external_id"] = dl.get("productId")
                if not result["title"] and dl.get("productName"):
                    result["title"] = dl["productName"]
            except (json.JSONDecodeError, ValueError):
                pass

        # Характеристики з dl > div > dt + dd
        specs = {}
        for dl_tag in soup.find_all("dl"):
            for div in dl_tag.find_all("div"):
                dt = div.find("dt")
                dd = div.find("dd")
                if dt and dd:
                    key = dt.get_text(strip=True).rstrip(":")
                    val = dd.get_text(separator=" ", strip=True)
                    if key and val:
                        specs[key] = val
        result["specs"] = specs

        # Бренд з specs якщо не знайшли в dataLayer
        if not result.get("vendor") and "Бренд" in specs:
            result["vendor"] = specs["Бренд"]

        # Фото з cdn.27.ua (без дублів)
        photos = list(dict.fromkeys(
            img["src"] for img in soup.find_all("img", src=True)
            if "cdn.27.ua" in img["src"]
        ))
        result["photos"] = photos

        return result


# ── Збереження в БД ──────────────────────────────────────────────────────────

def save_products(conn, products: list[dict], search_query: str = None):
    """Зберігає список продуктів у competitor_prices."""
    saved = 0
    with conn.cursor() as cur:
        for p in products:
            specs_json = json.dumps(p.get("specs") or {}, ensure_ascii=False)
            photos_json = json.dumps(p.get("photos") or ([p["photo_preview"]] if p.get("photo_preview") else []), ensure_ascii=False)
            cur.execute("""
                INSERT INTO competitor_prices
                    (sku, marketplace, competitor_name, competitor_url, price,
                     in_stock, title, vendor, specs_json, photos_json,
                     search_query, category_id, category_name, external_id, checked_at)
                VALUES
                    (%(sku)s, %(marketplace)s, %(competitor_name)s, %(url)s, %(price)s,
                     %(in_stock)s, %(title)s, %(vendor)s, %(specs_json)s, %(photos_json)s,
                     %(search_query)s, %(category_id)s, %(category_name)s, %(external_id)s, NOW())
                ON CONFLICT DO NOTHING
            """, {
                "sku": None,
                "marketplace": p.get("marketplace", "epicentr"),
                "competitor_name": p.get("vendor") or "Unknown",
                "url": p.get("url"),
                "price": p.get("price"),
                "in_stock": p.get("in_stock", True),
                "title": p.get("title"),
                "vendor": p.get("vendor"),
                "specs_json": specs_json,
                "photos_json": photos_json,
                "search_query": search_query or p.get("search_query"),
                "category_id": p.get("category_id"),
                "category_name": p.get("category_name"),
                "external_id": p.get("external_id"),
            })
            saved += 1
    conn.commit()
    return saved


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Epicentr competitor card scraper")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query", "-q", help="Пошуковий запит (латиниця або транслітерація)")
    group.add_argument("--url", "-u", help="Пряме посилання на картку товару")
    parser.add_argument("--limit", "-l", type=int, default=10, help="Макс. результатів пошуку (default 10)")
    parser.add_argument("--parse-cards", action="store_true", help="Завантажити кожну картку окремо (ціна, specs)")
    parser.add_argument("--no-save", action="store_true", help="Не зберігати в БД")
    parser.add_argument("--verbose", "-v", action="store_true", help="Детальний вивід")
    args = parser.parse_args()

    if not args.verbose:
        logger.remove()
        logger.add(sys.stderr, level="INFO")

    scraper = EpicentrPublicScraper(delay_range=(1.0, 2.0))

    if args.url:
        products = [scraper.parse_card(args.url)]
        products = [p for p in products if p]
    elif args.query:
        if args.parse_cards:
            products = scraper.find_competitors(args.query, max_results=args.limit, parse_cards=True)
        else:
            products = scraper.search(args.query, max_results=args.limit)

    print(f"\n=== Знайдено: {len(products)} товарів ===\n")
    for i, p in enumerate(products, 1):
        print(f"[{i}] {p.get('title', 'N/A')[:80]}")
        print(f"     Ціна: {p.get('price', '—')} грн | Бренд: {p.get('vendor', '—')}")
        print(f"     Кат.: {p.get('category_name', '—')} ({p.get('category_id', '—')})")
        print(f"     URL: {p.get('url', '—')}")
        if p.get("specs"):
            print(f"     Характеристики ({len(p['specs'])}):")
            for k, v in list(p["specs"].items())[:5]:
                print(f"       {k}: {v}")
        if p.get("photos"):
            print(f"     Фото: {len(p['photos'])} шт. | Перше: {p['photos'][0]}")
        elif p.get("photo_preview"):
            print(f"     Фото: {p['photo_preview']}")
        print()

    if not args.no_save and HAS_DB and products:
        try:
            conn = get_connection()
            ensure_schema(conn)
            saved = save_products(conn, products, search_query=args.query)
            conn.close()
            print(f"Збережено в БД: {saved} записів → таблиця competitor_prices")
        except Exception as e:
            logger.error(f"DB save failed: {e}")
    elif args.no_save:
        print("(--no-save: не зберігаємо в БД)")


if __name__ == "__main__":
    main()
