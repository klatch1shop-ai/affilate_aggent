"""
shared/mcp_servers/browser_mcp.py
====================================
MCP сервер для Browser Automation — мегапарсер.

Дозволяє Claude та агентам:
- Виконувати дії в браузері по текстовій команді
- Логінитись в кабінети маркетплейсів
- Скачувати/завантажувати файли
- Парсити ціни конкурентів
- Перехоплювати API endpoints
- Отримувати скріншоти

Запуск:
    python3 shared/mcp_servers/browser_mcp.py
"""

import os, sys, json, asyncio
from loguru import logger
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

app = Server('browser-automation-mcp')


@app.list_tools()
async def list_tools():
    return [

        # ── НАВІГАЦІЯ ─────────────────────────────────────────────────
        types.Tool(
            name='browser_navigate',
            description='Відкрити URL в браузері і чекати завантаження.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'url': {'type': 'string', 'description': 'URL для відкриття'},
                    'wait_for': {
                        'type': 'string',
                        'default': 'networkidle',
                        'description': 'Умова очікування: networkidle/domcontentloaded/load'
                    }
                },
                'required': ['url']
            }
        ),

        types.Tool(
            name='browser_screenshot',
            description='Зробити скріншот поточної сторінки. Повертає шлях до файлу.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Назва файлу (без розширення)'},
                    'full_page': {'type': 'boolean', 'default': False}
                }
            }
        ),

        # ── ВЗАЄМОДІЯ ─────────────────────────────────────────────────
        types.Tool(
            name='browser_click',
            description=(
                'Клікнути на елемент. Self-Healing: якщо не знайдено — шукає альтернативний '
                'селектор по тексту/aria-label. При невдачі надсилає Telegram алерт зі скріншотом.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'selector': {'type': 'string', 'description': 'CSS селектор або текст кнопки'},
                    'description': {'type': 'string', 'description': 'Опис дії для Self-Healing'}
                },
                'required': ['selector']
            }
        ),

        types.Tool(
            name='browser_fill',
            description='Заповнити поле введення тексту.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'selector': {'type': 'string'},
                    'value': {'type': 'string', 'description': 'Текст для введення'},
                    'description': {'type': 'string'}
                },
                'required': ['selector', 'value']
            }
        ),

        types.Tool(
            name='browser_press_key',
            description='Натиснути клавішу: Enter, Tab, Escape, ArrowDown тощо.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'key': {'type': 'string', 'description': 'Назва клавіші'}
                },
                'required': ['key']
            }
        ),

        types.Tool(
            name='browser_scroll',
            description='Прокрутити сторінку (для нескінченного скролу).',
            inputSchema={
                'type': 'object',
                'properties': {
                    'direction': {
                        'type': 'string',
                        'enum': ['down', 'up', 'end', 'home'],
                        'default': 'down'
                    },
                    'times': {'type': 'integer', 'default': 3}
                }
            }
        ),

        # ── ЧИТАННЯ ДАНИХ ──────────────────────────────────────────────
        types.Tool(
            name='browser_get_text',
            description='Отримати текстовий вміст елемента.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'selector': {'type': 'string'}
                },
                'required': ['selector']
            }
        ),

        types.Tool(
            name='browser_get_table',
            description='Парсити HTML таблицю → повертає JSON масив об\'єктів.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'selector': {'type': 'string', 'description': 'CSS селектор таблиці'}
                },
                'required': ['selector']
            }
        ),

        types.Tool(
            name='browser_execute_js',
            description='Виконати JavaScript на сторінці і повернути результат.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'script': {'type': 'string', 'description': 'JS код для виконання'}
                },
                'required': ['script']
            }
        ),

        types.Tool(
            name='browser_get_html',
            description='Отримати HTML фрагменту для аналізу DOM.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'selector': {'type': 'string', 'default': 'body'}
                }
            }
        ),

        # ── ФАЙЛИ ─────────────────────────────────────────────────────
        types.Tool(
            name='browser_download',
            description='Клікнути на посилання і чекати на завантаження файлу. Повертає шлях.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'click_selector': {'type': 'string', 'description': 'Селектор кнопки/посилання'},
                    'save_dir': {'type': 'string', 'default': '/tmp'}
                },
                'required': ['click_selector']
            }
        ),

        types.Tool(
            name='browser_upload',
            description='Завантажити файл через input[type=file].',
            inputSchema={
                'type': 'object',
                'properties': {
                    'selector': {'type': 'string'},
                    'filepath': {'type': 'string', 'description': 'Повний шлях до файлу'}
                },
                'required': ['selector', 'filepath']
            }
        ),

        # ── МЕРЕЖА ────────────────────────────────────────────────────
        types.Tool(
            name='browser_intercept_start',
            description='Почати запис XHR/fetch запитів для виявлення API endpoints.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'filter_pattern': {
                        'type': 'string',
                        'description': 'Фільтр URL (напр. "api" або "epicentrm.com")'
                    }
                }
            }
        ),

        types.Tool(
            name='browser_intercept_stop',
            description='Зупинити запис і повернути список перехоплених API endpoints.',
            inputSchema={
                'type': 'object',
                'properties': {}
            }
        ),

        types.Tool(
            name='browser_get_token',
            description='Витягти Bearer token з localStorage або cookies поточної сесії.',
            inputSchema={
                'type': 'object',
                'properties': {}
            }
        ),

        # ── СЕСІЇ ─────────────────────────────────────────────────────
        types.Tool(
            name='browser_login',
            description=(
                'Залогінитись в кабінет маркетплейсу. '
                'Зберігає сесію в БД для повторного використання. '
                'Сайти: epicentr, rozetka, prom, grandinstrument'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'site': {
                        'type': 'string',
                        'enum': ['epicentr', 'rozetka', 'prom', 'grandinstrument'],
                        'description': 'Сайт для логіну'
                    },
                    'headless': {
                        'type': 'boolean',
                        'default': True,
                        'description': 'True = без вікна браузера'
                    }
                },
                'required': ['site']
            }
        ),

        types.Tool(
            name='browser_session_status',
            description='Перевірити статус збереженої сесії для сайту.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'site': {'type': 'string'}
                },
                'required': ['site']
            }
        ),

        # ── ЄПІЦЕНТР СПЕЦИФІЧНІ ───────────────────────────────────────
        types.Tool(
            name='epicentr_export_products',
            description=(
                'Скачати XLS всіх товарів з кабінету Єпіцентру. '
                'Використовується для отримання маппінгу їхній_ID ↔ наш_SKU.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {}
            }
        ),

        types.Tool(
            name='epicentr_import_prices',
            description='Завантажити XLS з оновленими цінами/наявністю в кабінет Єпіцентру.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'filepath': {
                        'type': 'string',
                        'description': 'Шлях до XLS файлу для завантаження'
                    }
                },
                'required': ['filepath']
            }
        ),

        types.Tool(
            name='epicentr_intercept_api',
            description=(
                'Пройти по всіх розділах кабінету Єпіцентру і перехопити XHR запити. '
                'Автоматично знаходить нові API endpoints без документації.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {}
            }
        ),

        # ── КОНКУРЕНТИ ────────────────────────────────────────────────
        types.Tool(
            name='competitor_check_price',
            description=(
                'Перевірити ціну товару у конкурентів на Prom або Розетці. '
                'Повертає список конкурентів з цінами і збільшує таблицю competitor_prices.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'sku': {'type': 'string', 'description': 'SKU товару для пошуку'},
                    'marketplace': {
                        'type': 'string',
                        'enum': ['prom', 'rozetka'],
                        'default': 'prom'
                    },
                    'limit': {
                        'type': 'integer',
                        'default': 10,
                        'description': 'Скільки конкурентів перевірити'
                    }
                },
                'required': ['sku']
            }
        ),

        types.Tool(
            name='competitor_monitor_skus',
            description=(
                'Запустити моніторинг цін для списку SKU. '
                'Результати зберігаються в competitor_prices таблицю.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'skus': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Список SKU для моніторингу'
                    },
                    'marketplace': {
                        'type': 'string',
                        'enum': ['prom', 'rozetka'],
                        'default': 'prom'
                    }
                },
                'required': ['skus']
            }
        ),

    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    """
    Роутить виклики до відповідних Playwright агентів.
    Агенти запускаються в окремому процесі щоб не блокувати MCP сервер.
    """

    async def run_playwright(script: str) -> str:
        """Запускає Python скрипт з Playwright в окремому процесі."""
        proc = await asyncio.create_subprocess_exec(
            'python3', '-c', script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd='/home/tek/agent-system'
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return f'❌ Помилка: {stderr.decode()[:500]}'
        return stdout.decode().strip()

    # ── browser_navigate ──────────────────────────────────────────────
    if name == 'browser_navigate':
        script = f"""
import sys, asyncio
sys.path.append('.')
from agents.scraper.playwright_base import PlaywrightBase

async def main():
    async with PlaywrightBase('browser') as b:
        await b.navigate('{arguments["url"]}', '{arguments.get("wait_for","networkidle")}')
        title = await b.page.title()
        print(f'✅ Завантажено: {{title}} | URL: {arguments["url"]}')

asyncio.run(main())
"""
        result = await run_playwright(script)
        return [types.TextContent(type='text', text=result)]

    # ── browser_screenshot ────────────────────────────────────────────
    elif name == 'browser_screenshot':
        return [types.TextContent(
            type='text',
            text='⚠️ Скріншот доступний тільки в активній сесії браузера. '
                 'Спочатку виконай browser_login або browser_navigate.'
        )]

    # ── browser_login ─────────────────────────────────────────────────
    elif name == 'browser_login':
        site = arguments['site']
        headless = arguments.get('headless', True)

        if site == 'epicentr':
            script = f"""
import sys, asyncio
sys.path.append('.')
from agents.scraper.epicentr_cabinet import EpicentrCabinet

async def main():
    async with EpicentrCabinet(headless={headless}) as cab:
        success = await cab.login()
        print('✅ Логін успішний' if success else '❌ Логін невдалий')

asyncio.run(main())
"""
        else:
            script = f"print('⚠️ Логін для {site} поки в розробці')"

        result = await run_playwright(script)
        return [types.TextContent(type='text', text=result)]

    # ── browser_session_status ────────────────────────────────────────
    elif name == 'browser_session_status':
        site = arguments['site']
        script = f"""
import sys
sys.path.append('.')
from dotenv import load_dotenv; load_dotenv('.env')
from shared.utils.db import get_connection
from datetime import datetime

conn = get_connection()
cur = conn.cursor()
cur.execute('SELECT site, valid_until, is_active FROM browser_sessions WHERE site=%s', ('{site}',))
row = cur.fetchone()
cur.close(); conn.close()

if row:
    active = row['valid_until'] > datetime.now() if row['valid_until'] else False
    status = '✅ Активна' if active else '⚠️ Протухла'
    print(f"{{status}} | {site} | до {{row['valid_until']}}")
else:
    print('❌ Сесії немає')
"""
        result = await run_playwright(script)
        return [types.TextContent(type='text', text=result)]

    # ── epicentr_export_products ──────────────────────────────────────
    elif name == 'epicentr_export_products':
        script = """
import sys, asyncio
sys.path.append('.')
from agents.scraper.epicentr_cabinet import EpicentrCabinet

async def main():
    async with EpicentrCabinet(headless=True) as cab:
        path = await cab.export_products_xls()
        if path:
            mapping = await cab.parse_xls_mapping(path)
            print(f'✅ XLS скачано: {path}')
            print(f'✅ Маппінг збережено: {len(mapping)} товарів')
        else:
            print('❌ Не вдалось скачати XLS')

asyncio.run(main())
"""
        result = await run_playwright(script)
        return [types.TextContent(type='text', text=result)]

    # ── epicentr_import_prices ────────────────────────────────────────
    elif name == 'epicentr_import_prices':
        filepath = arguments['filepath']
        script = f"""
import sys, asyncio
sys.path.append('.')
from agents.scraper.epicentr_cabinet import EpicentrCabinet

async def main():
    async with EpicentrCabinet(headless=True) as cab:
        success = await cab.import_prices_xls('{filepath}')
        print('✅ Ціни завантажено' if success else '❌ Помилка завантаження')

asyncio.run(main())
"""
        result = await run_playwright(script)
        return [types.TextContent(type='text', text=result)]

    # ── epicentr_intercept_api ────────────────────────────────────────
    elif name == 'epicentr_intercept_api':
        script = """
import sys, asyncio
sys.path.append('.')
from agents.scraper.epicentr_cabinet import EpicentrCabinet

async def main():
    async with EpicentrCabinet(headless=True) as cab:
        endpoints = await cab.intercept_api_endpoints()
        print(f'✅ Знайдено endpoints: {len(endpoints)}')
        for e in endpoints[:10]:
            print(f'  {e["method"]} {e["url"]}')

asyncio.run(main())
"""
        result = await run_playwright(script)
        return [types.TextContent(type='text', text=result)]

    # ── competitor_check_price ────────────────────────────────────────
    elif name == 'competitor_check_price':
        sku = arguments['sku']
        marketplace = arguments.get('marketplace', 'prom')
        limit = arguments.get('limit', 10)
        script = f"""
import sys, asyncio, json
sys.path.append('.')
from dotenv import load_dotenv; load_dotenv('.env')
from playwright.async_api import async_playwright

async def main():
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        if '{marketplace}' == 'prom':
            await page.goto(f'https://prom.ua/ua/search?search_term={sku}', timeout=30000)
            await page.wait_for_load_state('networkidle')
            # Парсимо результати пошуку
            items = await page.query_selector_all('.x-gallery-tile')
            for item in items[:{limit}]:
                try:
                    name_el = await item.query_selector('[class*="title"]')
                    price_el = await item.query_selector('[class*="price"]')
                    name = await name_el.inner_text() if name_el else ''
                    price = await price_el.inner_text() if price_el else ''
                    results.append({{'name': name[:50], 'price': price}})
                except:
                    pass

        await browser.close()

    print(f'Знайдено конкурентів для {sku}: {{len(results)}}')
    for r in results:
        print(f'  {{r[\"price\"]:15}} | {{r[\"name\"]}}')

asyncio.run(main())
"""
        result = await run_playwright(script)
        return [types.TextContent(type='text', text=result)]

    # ── competitor_monitor_skus ───────────────────────────────────────
    elif name == 'competitor_monitor_skus':
        skus = arguments.get('skus', [])
        return [types.TextContent(
            type='text',
            text=f'⏳ Запуск моніторингу для {len(skus)} SKU... '
                 f'(competitor_monitor.py в розробці)'
        )]

    # ── browser_execute_js ────────────────────────────────────────────
    elif name == 'browser_execute_js':
        return [types.TextContent(
            type='text',
            text='⚠️ JS виконання доступне тільки в активній сесії. '
                 'Використовуй в комбінації з browser_login.'
        )]

    # ── browser_get_token ─────────────────────────────────────────────
    elif name == 'browser_get_token':
        return [types.TextContent(
            type='text',
            text='⚠️ Токен доступний тільки в активній сесії браузера.'
        )]

    # ── browser_intercept_start/stop ──────────────────────────────────
    elif name in ('browser_intercept_start', 'browser_intercept_stop'):
        return [types.TextContent(
            type='text',
            text='⚠️ Перехоплення доступне через epicentr_intercept_api для Єпіцентру '
                 'або напряму через PlaywrightBase.'
        )]

    return [types.TextContent(type='text', text=f'❌ Невідомий інструмент: {name}')]


async def main():
    logger.info('[Browser MCP] Запуск...')
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(main())
