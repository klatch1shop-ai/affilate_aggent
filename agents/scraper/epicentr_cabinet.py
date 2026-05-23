"""
agents/scraper/epicentr_cabinet.py
=====================================
Автоматизація кабінету Єпіцентру через Playwright.

Функції:
- Логін і збереження сесії
- Скачування XLS всіх товарів → маппінг артикулів
- Завантаження XLS з оновленими цінами/наявністю
- Перехоплення API endpoints
- Підтвердження замовлень

Запуск:
    python3 agents/scraper/epicentr_cabinet.py --action export_products
    python3 agents/scraper/epicentr_cabinet.py --action import_prices --file /tmp/prices.xlsx
    python3 agents/scraper/epicentr_cabinet.py --action intercept_api
    python3 agents/scraper/epicentr_cabinet.py --action map_skus
"""

import os, sys, json, asyncio, argparse
import pandas as pd
from datetime import datetime
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection
from agents.scraper.playwright_base import PlaywrightBase

# =============================================
# КОНСТАНТИ
# =============================================

EPICENTR_LOGIN_URL  = 'https://admin.epicentrm.com.ua/login'
EPICENTR_CABINET    = 'https://admin.epicentrm.com.ua'
EPICENTR_PRODUCTS   = 'https://admin.epicentrm.com.ua/products'
EPICENTR_IMPORT     = 'https://admin.epicentrm.com.ua/import'
EPICENTR_ORDERS     = 'https://admin.epicentrm.com.ua/orders'

EPICENTR_EMAIL    = os.getenv('EPICENTR_EMAIL', '')
EPICENTR_PASSWORD = os.getenv('EPICENTR_PASSWORD', '')

DOWNLOAD_DIR = '/tmp/epicentr_downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# =============================================
# ОСНОВНИЙ КЛАС
# =============================================

class EpicentrCabinet(PlaywrightBase):

    def __init__(self, headless: bool = True):
        super().__init__(site='epicentr', headless=headless)

    # =============================================
    # АВТОРИЗАЦІЯ
    # =============================================

    async def login(self) -> bool:
        """
        Логін в кабінет Єпіцентру.
        Зберігає сесію після успішного логіну.
        """
        logger.info('[Єпіцентр] Логін...')
        start = datetime.now()

        await self.navigate(EPICENTR_LOGIN_URL, wait_for='domcontentloaded')
        await self.random_delay(1000, 2000)

        # Заповнюємо email
        email_filled = await self.resilient_fill(
            'input[type="email"], input[name="email"], #email',
            EPICENTR_EMAIL,
            'поле email'
        )
        if not email_filled:
            return False

        await self.random_delay(300, 700)

        # Заповнюємо пароль
        pass_filled = await self.resilient_fill(
            'input[type="password"], input[name="password"], #password',
            EPICENTR_PASSWORD,
            'поле пароль'
        )
        if not pass_filled:
            return False

        await self.random_delay(500, 1000)

        # Натискаємо Увійти
        clicked = await self.resilient_click(
            'button[type="submit"], .login-button, button:has-text("Увійти"), button:has-text("Войти")',
            'кнопка Увійти'
        )
        if not clicked:
            return False

        # Чекаємо на перехід до кабінету
        try:
            await self.page.wait_for_url('**/admin.epicentrm.com.ua/**', timeout=15000)
            if 'login' not in self.page.url:
                await self.save_session()
                duration = (datetime.now() - start).seconds
                await self._log_action('login', 'success', duration_ms=duration*1000)
                logger.success('[Єпіцентр] Логін успішний')
                return True
        except:
            pass

        # Перевіряємо помилку
        error_text = await self.get_text('.error, .alert-danger, [class*="error"]')
        if error_text:
            logger.error(f'[Єпіцентр] Помилка логіну: {error_text}')

        screenshot = await self.screenshot('login_failed')
        await self._telegram_alert('❌ [Єпіцентр] Не вдалось залогінитись', screenshot)
        await self._log_action('login', 'error', {'error': error_text})
        return False

    async def ensure_logged_in(self) -> bool:
        """Перевіряє авторизацію і логінить якщо треба."""
        # Перевіряємо поточну сторінку
        try:
            await self.navigate(EPICENTR_CABINET, wait_for='domcontentloaded')
            if 'login' not in self.page.url:
                logger.info('[Єпіцентр] Вже залогінений')
                return True
        except:
            pass
        return await self.login()

    # =============================================
    # СКАЧУВАННЯ XLS ТОВАРІВ
    # =============================================

    async def export_products_xls(self) -> str | None:
        """
        Скачує XLS всіх товарів з кабінету Єпіцентру.
        Повертає шлях до збереженого файлу.
        """
        logger.info('[Єпіцентр] Скачування XLS товарів...')

        if not await self.ensure_logged_in():
            return None

        await self.navigate(EPICENTR_PRODUCTS, wait_for='networkidle')
        await self.random_delay(1000, 2000)

        # Шукаємо кнопку Export/Вивантажити
        export_selectors = [
            'button:has-text("Вивантажити")',
            'button:has-text("Export")',
            'a:has-text("Вивантажити")',
            'a:has-text("Скачати")',
            '[data-action="export"]',
            '.export-button',
        ]

        file_path = None
        for selector in export_selectors:
            try:
                count = await self.page.locator(selector).count()
                if count > 0:
                    file_path = await self.download_file(selector, DOWNLOAD_DIR)
                    if file_path:
                        break
            except:
                continue

        if not file_path:
            # Спробуємо через меню
            screenshot = await self.screenshot('export_products')
            logger.warning('[Єпіцентр] Кнопка export не знайдена — аналіз сторінки...')

            # Self-Healing: аналізуємо DOM
            html = await self.page.inner_html('body')
            logger.info(f'[Єпіцентр] DOM розмір: {len(html)} символів')

            await self._telegram_alert(
                '⚠️ [Єпіцентр] Не знайдено кнопку Export товарів. '
                'Перевірте скріншот.',
                screenshot
            )
            return None

        logger.success(f'[Єпіцентр] XLS скачано: {file_path}')
        await self._log_action('export_products', 'success', {'file': file_path})
        return file_path

    # =============================================
    # МАППІНГ АРТИКУЛІВ
    # =============================================

    async def parse_xls_mapping(self, xls_path: str) -> dict:
        """
        Парсить XLS і витягує маппінг: наш_SKU ↔ артикул_Єпіцентру.
        Зберігає в таблицю epicentr_sku_mapping.
        """
        logger.info(f'[Єпіцентр] Парсинг XLS маппінгу: {xls_path}')

        try:
            df = pd.read_excel(xls_path)
            logger.info(f'Колонки XLS: {list(df.columns)}')
            logger.info(f'Рядків: {len(df)}')
        except Exception as e:
            logger.error(f'Помилка читання XLS: {e}')
            return {}

        # Визначаємо колонки (назви можуть відрізнятись)
        sku_col = None
        article_col = None
        id_col = None

        for col in df.columns:
            col_lower = str(col).lower()
            if any(k in col_lower for k in ['артикул', 'sku', 'код', 'article']):
                if sku_col is None:
                    sku_col = col
                else:
                    article_col = col
            if any(k in col_lower for k in ['id', 'ідентифікатор', 'номер']):
                id_col = col

        logger.info(f'SKU колонка: {sku_col}, Артикул: {article_col}, ID: {id_col}')

        mapping = {}
        saved = 0

        conn = get_connection()
        cur = conn.cursor()

        for _, row in df.iterrows():
            our_sku = str(row.get(sku_col, '')).strip() if sku_col else ''
            epicentr_article = str(row.get(article_col, '')).strip() if article_col else ''
            epicentr_id = row.get(id_col) if id_col else None

            if not our_sku or our_sku == 'nan':
                continue

            mapping[our_sku] = {
                'article': epicentr_article,
                'id': epicentr_id,
            }

            # Зберігаємо в БД
            try:
                cur.execute('''
                    INSERT INTO epicentr_sku_mapping (our_sku, epicentr_article, epicentr_product_id, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (our_sku) DO UPDATE SET
                        epicentr_article=EXCLUDED.epicentr_article,
                        epicentr_product_id=EXCLUDED.epicentr_product_id,
                        updated_at=NOW()
                ''', (our_sku, epicentr_article or None, int(epicentr_id) if epicentr_id else None))
                saved += 1
            except Exception as e:
                logger.error(f'Помилка збереження маппінгу {our_sku}: {e}')

        conn.commit(); cur.close(); conn.close()
        logger.success(f'[Єпіцентр] Маппінг збережено: {saved} товарів')
        return mapping

    # =============================================
    # ЗАВАНТАЖЕННЯ XLS З ЦІНАМИ
    # =============================================

    async def import_prices_xls(self, xls_path: str) -> bool:
        """
        Завантажує XLS з оновленими цінами/наявністю в Єпіцентр.
        """
        logger.info(f'[Єпіцентр] Завантаження цін: {xls_path}')

        if not await self.ensure_logged_in():
            return False

        await self.navigate(EPICENTR_IMPORT, wait_for='networkidle')
        await self.random_delay(1000, 2000)

        # Завантажуємо файл
        uploaded = await self.upload_file(
            'input[type="file"]',
            xls_path
        )
        if not uploaded:
            screenshot = await self.screenshot('import_upload_failed')
            await self._telegram_alert('❌ [Єпіцентр] Не вдалось завантажити XLS', screenshot)
            return False

        await self.random_delay(500, 1000)

        # Натискаємо кнопку Завантажити/Import
        clicked = await self.resilient_click(
            'button[type="submit"], button:has-text("Завантажити"), button:has-text("Імпорт"), button:has-text("Import")',
            'кнопка завантаження'
        )
        if not clicked:
            return False

        # Чекаємо на результат
        await self.random_delay(3000, 5000)
        try:
            await self.wait_for('.success, .alert-success, [class*="success"]', timeout=30000)
            result_text = await self.get_text('.success, .alert-success')
            logger.success(f'[Єпіцентр] Завантаження успішне: {result_text}')
            screenshot = await self.screenshot('import_success')
            await self._telegram_alert(
                f'✅ [Єпіцентр] XLS завантажено\n{result_text}',
                screenshot
            )
            await self._log_action('import_prices', 'success', {'file': xls_path})
            return True
        except:
            screenshot = await self.screenshot('import_result')
            result_text = await self.get_text('body')
            logger.info(f'[Єпіцентр] Результат завантаження: {result_text[:200]}')
            await self._telegram_alert(
                f'[Єпіцентр] Результат завантаження XLS — перевір скріншот',
                screenshot
            )
            return False

    # =============================================
    # ПЕРЕХОПЛЕННЯ API ENDPOINTS
    # =============================================

    async def intercept_api_endpoints(self) -> list:
        """
        Проходить по всіх розділах кабінету і перехоплює XHR запити.
        Повертає список унікальних API endpoints.
        """
        logger.info('[Єпіцентр] Перехоплення API endpoints...')

        if not await self.ensure_logged_in():
            return []

        await self.intercept_start('epicentrm.com.ua')

        # Переходимо по всіх ключових розділах
        sections = [
            (EPICENTR_PRODUCTS, 'products'),
            (EPICENTR_ORDERS, 'orders'),
            (EPICENTR_IMPORT, 'import'),
            (f'{EPICENTR_CABINET}/prices', 'prices'),
            (f'{EPICENTR_CABINET}/categories', 'categories'),
        ]

        for url, section in sections:
            try:
                logger.info(f'[Єпіцентр] Сканую: {section}')
                await self.navigate(url, wait_for='networkidle')
                await self.random_delay(2000, 3000)
                await self.scroll_down(2)
            except Exception as e:
                logger.warning(f'[Єпіцентр] Помилка {section}: {e}')

        requests = self.intercept_stop()

        # Аналізуємо унікальні endpoints
        endpoints = {}
        for r in requests:
            url = r['url']
            method = r['method']
            key = f'{method} {url.split("?")[0]}'
            if key not in endpoints:
                endpoints[key] = {
                    'method': method,
                    'url': url.split('?')[0],
                    'example_response': r.get('body', {}),
                    'count': 0
                }
            endpoints[key]['count'] += 1

        result = sorted(endpoints.values(), key=lambda x: -x['count'])

        # Зберігаємо в файл
        output_path = '/home/tek/agent-system/shared/skills/scraper/epicentr_api_discovered.json'
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)

        logger.success(f'[Єпіцентр] Знайдено {len(result)} унікальних endpoints → {output_path}')

        # Telegram звіт
        top_endpoints = '\n'.join([f'{e["method"]} {e["url"]}' for e in result[:10]])
        await self._telegram_alert(
            f'🔍 [Єпіцентр] Знайдено API endpoints: {len(result)}\n\nТоп-10:\n{top_endpoints}'
        )

        return result

    # =============================================
    # ГЕНЕРАЦІЯ XLS ДЛЯ ІМПОРТУ
    # =============================================

    async def generate_prices_xls(self, output_path: str = None) -> str:
        """
        Генерує XLS файл з поточними цінами і наявністю з БД.
        Формат відповідає вимогам Єпіцентру.
        """
        output_path = output_path or f'/tmp/epicentr_prices_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'

        # Отримуємо дані з БД
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT
                m.our_sku,
                m.epicentr_article,
                m.epicentr_product_id,
                p.price_our,
                p.available,
                p.stock
            FROM epicentr_sku_mapping m
            JOIN my_products p ON m.our_sku = p.sku
            WHERE p.price_our > 0
            ORDER BY m.our_sku
        ''')
        rows = cur.fetchall()
        cur.close(); conn.close()

        if not rows:
            logger.error('Немає даних для генерації XLS — спочатку запусти map_skus')
            return None

        # Формуємо DataFrame
        data = []
        for r in rows:
            data.append({
                'Артикул': r['epicentr_article'] or r['our_sku'],
                'Ціна': float(r['price_our']),
                'Наявність': 'В наявності' if r['available'] else 'Немає в наявності',
                'Залишок': r['stock'] or '',
            })

        df = pd.DataFrame(data)
        df.to_excel(output_path, index=False)
        logger.success(f'XLS згенеровано: {output_path} ({len(data)} товарів)')
        return output_path


# =============================================
# CLI ЗАПУСК
# =============================================

async def main():
    parser = argparse.ArgumentParser(description='Єпіцентр Cabinet Automation')
    parser.add_argument('--action', required=True,
        choices=['login', 'export_products', 'import_prices', 'intercept_api',
                 'map_skus', 'generate_prices'],
        help='Дія для виконання')
    parser.add_argument('--file', type=str, help='Шлях до файлу (для import_prices)')
    parser.add_argument('--visible', action='store_true', help='Запустити з відкритим браузером')
    args = parser.parse_args()

    async with EpicentrCabinet(headless=not args.visible) as cabinet:

        if args.action == 'login':
            success = await cabinet.login()
            print('✅ Логін успішний' if success else '❌ Логін невдалий')

        elif args.action == 'export_products':
            path = await cabinet.export_products_xls()
            if path:
                print(f'✅ XLS збережено: {path}')
            else:
                print('❌ Не вдалось скачати XLS')

        elif args.action == 'import_prices':
            if not args.file:
                print('❌ Вкажи --file шлях_до_файлу.xlsx')
                return
            success = await cabinet.import_prices_xls(args.file)
            print('✅ Завантажено' if success else '❌ Помилка завантаження')

        elif args.action == 'intercept_api':
            endpoints = await cabinet.intercept_api_endpoints()
            print(f'✅ Знайдено endpoints: {len(endpoints)}')

        elif args.action == 'map_skus':
            # Спочатку скачуємо XLS, потім парсимо маппінг
            xls_path = await cabinet.export_products_xls()
            if xls_path:
                mapping = await cabinet.parse_xls_mapping(xls_path)
                print(f'✅ Маппінг збережено: {len(mapping)} товарів')
            else:
                print('❌ Не вдалось отримати XLS')

        elif args.action == 'generate_prices':
            path = await cabinet.generate_prices_xls()
            if path:
                print(f'✅ XLS цін згенеровано: {path}')
            else:
                print('❌ Помилка генерації — спочатку запусти map_skus')


if __name__ == '__main__':
    asyncio.run(main())
