"""
agents/scraper/playwright_base.py
===================================
Базовий клас для всіх Playwright агентів.

Можливості:
- Self-Healing: автоматичний пошук нових селекторів при помилці
- Retry logic: повтор дій з exponential backoff
- Screenshot on error: скріншот при кожній помилці
- Session management: збереження/відновлення сесій
- Telegram alerts: сповіщення при критичних помилках
- Random delays: анти-бот поведінка
- Proxy support: ротація проксі
"""

import os, sys, json, asyncio, time, random
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Error as PlaywrightError

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# =============================================
# КОНСТАНТИ
# =============================================

SCREENSHOTS_DIR = '/home/tek/agent-system/logs/screenshots'
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')

# User Agents — реалістичні браузери
USER_AGENTS = [
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
]


# =============================================
# БАЗОВИЙ КЛАС
# =============================================

class PlaywrightBase:
    """
    Базовий клас для Playwright агентів.
    Успадковуй його в epicentr_cabinet.py, competitor_monitor.py і т.д.
    """

    def __init__(self, site: str, headless: bool = True, proxy: str = None):
        self.site = site
        self.headless = headless
        self.proxy = proxy
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None
        self.session_data = {}
        self._intercepted_requests = []

        # Фіксований UA для цієї сесії
        self.user_agent = self._get_or_create_ua()

        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    def _get_or_create_ua(self) -> str:
        """Отримує збережений UA або створює новий."""
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute('SELECT user_agent FROM browser_sessions WHERE site=%s', (self.site,))
            row = cur.fetchone()
            cur.close(); conn.close()
            if row and row['user_agent']:
                return row['user_agent']
        except:
            pass
        return random.choice(USER_AGENTS)

    # =============================================
    # ЗАПУСК І ЗУПИНКА
    # =============================================

    async def start(self):
        """Запускає браузер і відновлює сесію якщо є."""
        self.playwright = await async_playwright().start()

        launch_args = {
            'headless': self.headless,
            'args': [
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
            ]
        }

        if self.proxy:
            launch_args['proxy'] = {'server': self.proxy}

        self.browser = await self.playwright.chromium.launch(**launch_args)

        context_args = {
            'user_agent': self.user_agent,
            'viewport': {'width': 1280, 'height': 800},
            'locale': 'uk-UA',
            'timezone_id': 'Europe/Kyiv',
            'extra_http_headers': {
                'Accept-Language': 'uk-UA,uk;q=0.9,en;q=0.8',
            }
        }

        self.context = await self.browser.new_context(**context_args)

        # Приховуємо ознаки automation
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
        """)

        self.page = await self.context.new_page()

        # Відновлюємо сесію якщо є
        await self._load_session()

        logger.info(f'[{self.site}] Браузер запущено')
        return self

    async def stop(self):
        """Зупиняє браузер."""
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info(f'[{self.site}] Браузер зупинено')
        except Exception as e:
            logger.error(f'[{self.site}] Помилка зупинки: {e}')

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()

    # =============================================
    # СЕСІЇ
    # =============================================

    async def _load_session(self):
        """Відновлює cookies і localStorage з БД."""
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                'SELECT cookies, local_storage, valid_until FROM browser_sessions WHERE site=%s AND is_active=TRUE',
                (self.site,)
            )
            row = cur.fetchone()
            cur.close(); conn.close()

            if row and row['valid_until'] and row['valid_until'] > datetime.now():
                if row['cookies']:
                    await self.context.add_cookies(row['cookies'])
                if row['local_storage']:
                    self.session_data['local_storage'] = row['local_storage']
                logger.success(f'[{self.site}] Сесія відновлена (дійсна до {row["valid_until"].strftime("%d.%m %H:%M")})')
                return True
        except Exception as e:
            logger.warning(f'[{self.site}] Не вдалось відновити сесію: {e}')
        return False

    async def save_session(self, valid_hours: int = 23):
        """Зберігає поточну сесію в БД."""
        try:
            cookies = await self.context.cookies()
            valid_until = datetime.now() + timedelta(hours=valid_hours)

            conn = get_connection()
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO browser_sessions (site, cookies, user_agent, valid_until, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (site) DO UPDATE SET
                    cookies=EXCLUDED.cookies,
                    user_agent=EXCLUDED.user_agent,
                    valid_until=EXCLUDED.valid_until,
                    updated_at=NOW()
            ''', (self.site, json.dumps(cookies), self.user_agent, valid_until))
            conn.commit(); cur.close(); conn.close()
            logger.success(f'[{self.site}] Сесія збережена до {valid_until.strftime("%d.%m %H:%M")}')
        except Exception as e:
            logger.error(f'[{self.site}] Помилка збереження сесії: {e}')

    async def check_session(self) -> bool:
        """Перевіряє чи сесія активна в БД."""
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                'SELECT valid_until FROM browser_sessions WHERE site=%s AND is_active=TRUE',
                (self.site,)
            )
            row = cur.fetchone()
            cur.close(); conn.close()
            return bool(row and row['valid_until'] and row['valid_until'] > datetime.now())
        except:
            return False

    # =============================================
    # SELF-HEALING ACTIONS
    # =============================================

    async def resilient_click(self, selector: str, description: str = '', timeout: int = 10000) -> bool:
        """
        Клік з Self-Healing: якщо елемент не знайдено — шукаємо альтернативний селектор.
        """
        # Спроба 1: прямий клік
        try:
            await self.page.click(selector, timeout=timeout)
            logger.debug(f'[{self.site}] Click OK: {description or selector}')
            return True
        except PlaywrightError:
            pass

        # Спроба 2: пошук по тексту якщо selector виглядає як текст
        if not selector.startswith(('.', '#', '[', '*', 'button', 'a', 'div', 'span')):
            try:
                await self.page.get_by_text(selector, exact=False).first.click(timeout=5000)
                logger.info(f'[{self.site}] Click by text OK: {selector}')
                return True
            except PlaywrightError:
                pass

        # Спроба 3: Self-Healing через аналіз DOM
        logger.warning(f'[{self.site}] Element not found: {description or selector} — Self-Healing...')
        screenshot = await self.screenshot(f'error_click_{description or "unknown"}')

        new_selector = await self._find_selector_by_description(description or selector)
        if new_selector:
            try:
                await self.page.click(new_selector, timeout=5000)
                logger.success(f'[{self.site}] Self-Healing click OK: {new_selector}')
                await self._log_action('self_healing_click', 'success',
                    {'original': selector, 'healed': new_selector})
                return True
            except PlaywrightError:
                pass

        # Фінал: Telegram повідомлення
        await self._telegram_alert(
            f'⚠️ [{self.site}] Не можу клікнути: {description or selector}',
            screenshot
        )
        return False

    async def resilient_fill(self, selector: str, value: str, description: str = '') -> bool:
        """
        Заповнення поля з Self-Healing.
        """
        try:
            await self.page.fill(selector, value, timeout=10000)
            return True
        except PlaywrightError:
            logger.warning(f'[{self.site}] Fill failed: {description or selector} — Self-Healing...')
            screenshot = await self.screenshot(f'error_fill_{description or "unknown"}')

            new_selector = await self._find_selector_by_description(description or selector)
            if new_selector:
                try:
                    await self.page.fill(new_selector, value, timeout=5000)
                    return True
                except PlaywrightError:
                    pass

            await self._telegram_alert(
                f'⚠️ [{self.site}] Не можу заповнити поле: {description or selector}',
                screenshot
            )
            return False

    async def _find_selector_by_description(self, description: str) -> str | None:
        """
        Аналізує DOM і намагається знайти новий селектор.
        Шукає по тексту, placeholder, aria-label.
        """
        try:
            # Пробуємо різні варіанти пошуку
            variants = [
                f'[aria-label*="{description}"]',
                f'[placeholder*="{description}"]',
                f'[title*="{description}"]',
                f'button:has-text("{description}")',
                f'a:has-text("{description}")',
                f'[data-testid*="{description.lower().replace(" ", "-")}"]',
            ]
            for v in variants:
                try:
                    count = await self.page.locator(v).count()
                    if count > 0:
                        logger.info(f'Self-Healing знайшов: {v}')
                        return v
                except:
                    continue
        except:
            pass
        return None

    # =============================================
    # БАЗОВІ ДІЇ
    # =============================================

    async def navigate(self, url: str, wait_for: str = 'networkidle'):
        """Перехід на URL з очікуванням завантаження."""
        await self.page.goto(url, wait_until=wait_for, timeout=30000)
        await self.random_delay(500, 1500)

    async def wait_for(self, selector: str, timeout: int = 30000):
        """Чекає появи елемента."""
        await self.page.wait_for_selector(selector, timeout=timeout)

    async def get_text(self, selector: str) -> str:
        """Повертає текст елемента."""
        try:
            return await self.page.inner_text(selector)
        except:
            return ''

    async def get_table(self, selector: str) -> list:
        """Парсить HTML таблицю в список dict."""
        try:
            return await self.page.evaluate(f'''() => {{
                const table = document.querySelector('{selector}');
                if (!table) return [];
                const headers = [...table.querySelectorAll('th')].map(h => h.innerText.trim());
                return [...table.querySelectorAll('tbody tr')].map(row => {{
                    const cells = [...row.querySelectorAll('td')].map(c => c.innerText.trim());
                    return headers.reduce((obj, h, i) => {{ obj[h] = cells[i] || ''; return obj; }}, {{}});
                }});
            }}''')
        except:
            return []

    async def execute_js(self, script: str):
        """Виконує JS на сторінці."""
        return await self.page.evaluate(script)

    async def random_delay(self, min_ms: int = 300, max_ms: int = 1200):
        """Випадкова затримка для анти-бот поведінки."""
        delay = random.randint(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)

    async def scroll_down(self, times: int = 3):
        """Скрол вниз для нескінченного скролу."""
        for _ in range(times):
            await self.page.keyboard.press('End')
            await self.random_delay(800, 2000)

    # =============================================
    # СКРІНШОТИ
    # =============================================

    async def screenshot(self, name: str = 'screenshot') -> str:
        """Робить скріншот і зберігає в logs/screenshots/."""
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{SCREENSHOTS_DIR}/{self.site}_{name}_{ts}.png'
        await self.page.screenshot(path=filename, full_page=False)
        logger.debug(f'Screenshot: {filename}')
        return filename

    # =============================================
    # ПЕРЕХОПЛЕННЯ МЕРЕЖІ
    # =============================================

    async def intercept_start(self, filter_pattern: str = ''):
        """Починає запис XHR/fetch запитів."""
        self._intercepted_requests = []
        self._intercept_pattern = filter_pattern

        async def handle_response(response):
            url = response.url
            if filter_pattern and filter_pattern not in url:
                return
            if any(ext in url for ext in ['.css', '.js', '.png', '.jpg', '.woff', '.ico']):
                return
            try:
                body = await response.json()
                self._intercepted_requests.append({
                    'url': url,
                    'method': response.request.method,
                    'status': response.status,
                    'body': body,
                })
            except:
                pass

        self.page.on('response', handle_response)
        logger.info(f'[{self.site}] Intercept started (filter: {filter_pattern or "all"})')

    def intercept_stop(self) -> list:
        """Зупиняє запис і повертає всі перехоплені запити."""
        self.page.remove_listener('response', lambda *a: None)
        logger.info(f'[{self.site}] Intercepted {len(self._intercepted_requests)} requests')
        return self._intercepted_requests

    async def get_bearer_token(self) -> str:
        """Витягує Bearer token з localStorage або cookies."""
        try:
            # Перевіряємо localStorage
            token = await self.page.evaluate('''() => {
                const keys = ['token', 'access_token', 'auth_token', 'bearer', 'jwt'];
                for (const k of keys) {
                    const v = localStorage.getItem(k);
                    if (v) return v;
                }
                // Шукаємо в всіх ключах
                for (let i = 0; i < localStorage.length; i++) {
                    const k = localStorage.key(i);
                    const v = localStorage.getItem(k);
                    if (v && v.length > 20 && (v.startsWith('ey') || k.includes('token'))) {
                        return v;
                    }
                }
                return null;
            }''')
            if token:
                return token

            # Перевіряємо cookies
            cookies = await self.context.cookies()
            for c in cookies:
                if 'token' in c['name'].lower() or 'auth' in c['name'].lower():
                    return c['value']
        except:
            pass
        return ''

    # =============================================
    # ЗАВАНТАЖЕННЯ ФАЙЛІВ
    # =============================================

    async def download_file(self, click_selector: str, save_dir: str = '/tmp') -> str | None:
        """Клікає на посилання і чекає на завантаження файлу."""
        try:
            async with self.page.expect_download(timeout=60000) as download_info:
                await self.page.click(click_selector)
            download = await download_info.value
            filename = download.suggested_filename or f'download_{int(time.time())}'
            save_path = f'{save_dir}/{filename}'
            await download.save_as(save_path)
            logger.success(f'[{self.site}] Файл завантажено: {save_path}')
            return save_path
        except Exception as e:
            logger.error(f'[{self.site}] Download error: {e}')
            await self.screenshot('download_error')
            return None

    async def upload_file(self, selector: str, filepath: str) -> bool:
        """Завантажує файл через input[type=file]."""
        try:
            await self.page.set_input_files(selector, filepath)
            logger.success(f'[{self.site}] Файл завантажено: {filepath}')
            return True
        except Exception as e:
            logger.error(f'[{self.site}] Upload error: {e}')
            return False

    # =============================================
    # TELEGRAM СПОВІЩЕННЯ
    # =============================================

    async def _telegram_alert(self, message: str, screenshot_path: str = None):
        """Відправляє Telegram повідомлення і файл скріншоту."""
        import requests as req
        try:
            req.post(
                f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
                json={'chat_id': TELEGRAM_ADMIN, 'text': message, 'parse_mode': 'HTML'},
                timeout=10
            )
            if screenshot_path and os.path.exists(screenshot_path):
                with open(screenshot_path, 'rb') as f:
                    req.post(
                        f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto',
                        data={'chat_id': TELEGRAM_ADMIN},
                        files={'photo': f},
                        timeout=30
                    )
        except Exception as e:
            logger.error(f'Telegram alert error: {e}')

    # =============================================
    # ЛОГУВАННЯ В БД
    # =============================================

    async def _log_action(self, action: str, status: str, details: dict = None,
                          screenshot: str = None, duration_ms: int = None):
        """Записує дію в browser_action_log."""
        try:
            import json as _json
            conn = get_connection()
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO browser_action_log (site, action, status, details, screenshot, duration_ms)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (self.site, action, status,
                  _json.dumps(details or {}, ensure_ascii=False),
                  screenshot, duration_ms))
            conn.commit(); cur.close(); conn.close()
        except:
            pass
