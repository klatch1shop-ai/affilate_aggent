import asyncio

async def find():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # відкриє вікно браузера
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            locale="uk-UA"
        )
        page = await context.new_page()
        await page.goto("https://rozetka.com.ua/ua/", wait_until="networkidle", timeout=40000)
        print("Відкрий категорію 'Електроніка' вручну в браузері")
        print("Потім подивись URL і натисни Enter тут...")
        input()
        url = page.url
        print(f"Поточний URL: {url}")
        
        # Зберегти HTML
        html = await page.content()
        with open("/tmp/rozetka_real.html", "w") as f:
            f.write(html)
        print(f"HTML збережено: {len(html)} bytes")
        
        # Знайти картки товарів
        selectors_to_try = [
            "li.catalog-grid__cell",
            "li[class*='catalog']",
            "div[class*='catalog']",
            "app-goods-tile-default",
            "rz-catalog-tile",
            "[class*='goods-tile']",
            "[class*='product-tile']",
        ]
        for sel in selectors_to_try:
            items = await page.query_selector_all(sel)
            if items:
                print(f"✓ Знайдено {len(items)} елементів з селектором: {sel}")
        
        await browser.close()

asyncio.run(find())
