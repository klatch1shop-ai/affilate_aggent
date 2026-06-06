import os, sys, json, re, time
from loguru import logger
from playwright.sync_api import sync_playwright

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

def get_competitor_prices(sku: str, min_price: float = 0) -> dict:
    """Отримує ціни конкурентів з Prom для артикулу"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(f'https://prom.ua/ua/search?search_term={sku}',
                      wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(2000)

            prices = []
            # Шукаємо ціни в елементах
            items = page.query_selector_all('[data-qaid="product_price"]')
            for item in items:
                text = item.inner_text().strip()
                nums = re.findall(r'\d[\d\s]*', text)
                for n in nums:
                    n = int(n.replace(' ', ''))
                    # Фільтруємо: ціна має бути більше закупки і менше 500000
                    if min_price * 0.8 < n < 500000:
                        prices.append(n)

            # Якщо не знайшло через data-qaid — шукаємо через JS
            if not prices:
                data = page.evaluate('''() => {
                    const items = document.querySelectorAll(".x-gallery-tile");
                    return Array.from(items).map(el => {
                        const price = el.querySelector("[class*=price]");
                        return price ? price.innerText : null;
                    }).filter(Boolean);
                }''')
                for text in data:
                    nums = re.findall(r'\d[\d\s]*', text)
                    for n in nums:
                        n = int(n.replace(' ', ''))
                        if min_price * 0.8 < n < 500000:
                            prices.append(n)

        except Exception as e:
            logger.error(f"[MARKET] Error for {sku}: {e}")
            prices = []
        finally:
            browser.close()

    if not prices:
        return {'sku': sku, 'error': 'no prices', 'count': 0}

    # Фільтруємо викиди тільки якщо є достатньо цін
    if len(prices) > 3:
        avg = sum(prices) / len(prices)
        std = (sum((p-avg)**2 for p in prices) / len(prices)) ** 0.5
        filtered = [p for p in prices if abs(p - avg) < 2 * std]
        if filtered:  # Якщо після фільтрації є ціни
            prices = filtered

    return {
        'sku': sku,
        'min': min(prices),
        'max': max(prices),
        'avg': round(sum(prices) / len(prices)),
        'median': sorted(prices)[len(prices)//2],
        'count': len(prices),
        'prices': sorted(prices),
    }

def get_cpa_rate(category_name: str = None) -> float:
    """Повертає CPA ставку для категорії з БД"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        if category_name:
            cur.execute("""SELECT cpa_rate FROM prom_cpa_rates 
                WHERE category_name ILIKE %s LIMIT 1""", (f"%{category_name}%",))
            row = cur.fetchone()
            if row:
                cur.close(); conn.close()
                return float(row["cpa_rate"]) / 100
        # Дефолт для інструментів
        cur.close(); conn.close()
    except:
        pass
    return 0.15  # 15% дефолт для інструментів TOPTUL

def calculate_our_price(zakupka: float, avg_market: float, cpa_rate: float = 0.15) -> float:
    """Розраховує нашу ціну з урахуванням реального CPA"""
    delivery = 20  # середня вартість доставки
    margin = 0.20  # бажана маржа 20%
    
    # Мінімальна ціна = (закупка + доставка) / (1 - CPA) * (1 + маржа)
    min_price = (zakupka + delivery) / (1 - cpa_rate) * (1 + margin)
    
    # Цільова = середня ринкова * 0.95 (на 5% нижче)
    target = avg_market * 0.95
    
    # Беремо більше з двох
    price = max(target, min_price)
    
    # Округлення до 10 грн
    return round(price / 10) * 10

def analyze_and_update(limit: int = 10):
    """Аналізує ціни і оновлює БД"""
    conn = get_connection()
    cur = conn.cursor()

    # Таблиця для зберігання ринкових цін
    cur.execute('''
        CREATE TABLE IF NOT EXISTS market_prices (
            sku VARCHAR(100) PRIMARY KEY,
            min_price DECIMAL(12,2),
            max_price DECIMAL(12,2),
            avg_price DECIMAL(12,2),
            median_price DECIMAL(12,2),
            sellers_count INTEGER,
            our_price DECIMAL(12,2),
            analyzed_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    conn.commit()

    # Беремо товари для аналізу
    cur.execute('''
        SELECT sku, price_supplier 
        FROM my_products 
        WHERE price_supplier > 0
        AND sku NOT IN (SELECT sku FROM market_prices)
        ORDER BY price_supplier DESC
        LIMIT %s
    ''', (limit,))
    products = cur.fetchall()
    logger.info(f"[MARKET] Analyzing {len(products)} products")

    for p in products:
        sku = p['sku']
        zakupka = float(p['price_supplier']) * 0.88

        logger.info(f"[MARKET] Searching: {sku}")
        result = get_competitor_prices(sku, min_price=zakupka)

        if result.get('count', 0) > 0:
            our_price = calculate_our_price(zakupka, result['avg'])
            cur.execute('''
                INSERT INTO market_prices 
                (sku, min_price, max_price, avg_price, median_price, sellers_count, our_price)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (sku) DO UPDATE SET
                    min_price=EXCLUDED.min_price,
                    avg_price=EXCLUDED.avg_price,
                    our_price=EXCLUDED.our_price,
                    analyzed_at=NOW()
            ''', (sku, result['min'], result['max'], result['avg'],
                  result['median'], result['count'], our_price))

            # Оновлюємо ціну в my_products
            cur.execute('UPDATE my_products SET price_our=%s WHERE sku=%s',
                       (our_price, sku))
            conn.commit()

            logger.success(f"[MARKET] {sku}: avg={result['avg']} → our={our_price} грн")
        else:
            logger.warning(f"[MARKET] {sku}: no competitors found")

        time.sleep(2)  # Пауза між запитами

    cur.close(); conn.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--sku", type=str, default=None)
    args = parser.parse_args()

    if args.sku:
        # Тест одного артикулу
        from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT price_supplier FROM my_products WHERE sku=%s", (args.sku,))
        row = cur.fetchone()
        zakupka = float(row['price_supplier']) * 0.88 if row else 100
        cur.close(); conn.close()

        result = get_competitor_prices(args.sku, zakupka)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get('count', 0) > 0:
            our = calculate_our_price(zakupka, result['avg'])
            print(f"Закупка: {zakupka:.0f} грн")
            print(f"Наша ціна: {our:.0f} грн")
    else:
        analyze_and_update(args.limit)
