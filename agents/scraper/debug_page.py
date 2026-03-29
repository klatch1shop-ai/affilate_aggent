import asyncio
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

async def save_html():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            locale="uk-UA"
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        page = await context.new_page()
        await page.goto("https://rozetka.com.ua/ua/electronics/c4627901/", wait_until="networkidle", timeout=40000)
        await asyncio.sleep(4)
        html = await page.content()
        with open("/tmp/rozetka.html", "w") as f:
            f.write(html)
        print(f"Saved {len(html)} bytes")
        # Знайти всі li, div з класами що схожі на картку товару
        items_li = await page.query_selector_all("li")
        items_div = await page.query_selector_all("div[class*='product'], div[class*='goods'], div[class*='item']")
        print(f"li elements: {len(items_li)}")
        print(f"product divs: {len(items_div)}")
        # Перші класи li
        for el in items_li[:5]:
            cls = await el.get_attribute("class")
            if cls:
                print(f"  li class: {cls}")
        await browser.close()

asyncio.run(save_html())
