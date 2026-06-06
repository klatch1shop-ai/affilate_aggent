"""
agents/orders/fetch_prom_categories.py
=======================================
Одноразовий скрипт (і щотижнева підтримка):
- Проходить всі товари через Prom API /products/list
- Зберігає group.name і category.caption в my_products
- Додає колонку prom_category_name якщо не існує
- Показує маппінг на prom_cpa_rates

Запуск:
    python3 agents/orders/fetch_prom_categories.py
    python3 agents/orders/fetch_prom_categories.py --dry-run   # без запису в БД
    python3 agents/orders/fetch_prom_categories.py --stats     # тільки статистика

Час: ~5-10 хвилин для 5908 товарів (rate limit Prom: ~3 req/sec)
"""
import os, sys, time, requests, json, argparse
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

PROM_TOKEN = os.getenv('PROM_API_TOKEN')
PROM_HEADERS = {'Authorization': f'Bearer {PROM_TOKEN}'}
PROM_BASE = 'https://my.prom.ua/api/v1'

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')


def tg(text: str):
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_ADMIN, 'text': text, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.error(f'Telegram: {e}')


def ensure_columns():
    """Додає колонки prom_category_name і prom_group_id якщо не існують"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        ALTER TABLE my_products
        ADD COLUMN IF NOT EXISTS prom_category_name VARCHAR(255),
        ADD COLUMN IF NOT EXISTS prom_group_name VARCHAR(255),
        ADD COLUMN IF NOT EXISTS prom_group_id BIGINT
    ''')
    conn.commit()
    cur.close()
    conn.close()
    logger.info('Колонки prom_category_name, prom_group_name, prom_group_id — готові')


def fetch_all_prom_products() -> list:
    """
    Завантажує всі товари з Prom API з пагінацією.
    Повертає список з полями: id, sku, group, category
    """
    all_products = []
    last_id = None
    page = 0

    logger.info('Завантажуємо товари з Prom API...')

    while True:
        page += 1
        params = {'limit': 100}
        if last_id:
            params['last_id'] = last_id

        try:
            resp = requests.get(
                f'{PROM_BASE}/products/list',
                headers=PROM_HEADERS,
                params=params,
                timeout=30
            )
            resp.raise_for_status()
            products = resp.json().get('products', [])
        except Exception as e:
            logger.error(f'Prom API помилка (сторінка {page}): {e}')
            time.sleep(5)
            continue

        if not products:
            break

        for p in products:
            group = p.get('group') or {}
            category = p.get('category') or {}
            all_products.append({
                'prom_id': p.get('id'),
                'sku': p.get('sku', '').strip(),
                'prom_group_id': group.get('id'),
                'prom_group_name': group.get('name_multilang', {}).get('uk') or group.get('name', ''),
                'prom_category_name': category.get('caption', ''),
            })

        last_id = products[-1]['id']
        logger.info(f'Сторінка {page}: {len(all_products)} товарів завантажено')

        if len(products) < 100:
            break

        time.sleep(0.4)  # rate limit: ~2.5 req/sec

    logger.success(f'Всього з Prom API: {len(all_products)} товарів')
    return all_products


def save_to_db(products: list, dry_run: bool = False) -> dict:
    """
    Зберігає group і category в my_products.
    Оновлює тільки товари де є SKU.

    Returns:
        dict: статистика {'updated': N, 'skipped': N, 'no_sku': N}
    """
    stats = {'updated': 0, 'skipped': 0, 'no_sku': 0, 'no_match': 0}

    if dry_run:
        logger.info('[DRY RUN] Тільки перегляд — без запису в БД')

    conn = get_connection()
    cur = conn.cursor()

    for p in products:
        sku = p.get('sku', '').strip()
        if not sku:
            stats['no_sku'] += 1
            continue

        group_name = p.get('prom_group_name', '') or ''
        category_name = p.get('prom_category_name', '') or ''
        group_id = p.get('prom_group_id')

        if not dry_run:
            cur.execute('''
                UPDATE my_products
                SET
                    prom_group_name = %s,
                    prom_group_id = %s,
                    prom_category_name = %s
                WHERE sku = %s
            ''', (group_name, group_id, category_name, sku))

            if cur.rowcount > 0:
                stats['updated'] += 1
            else:
                stats['no_match'] += 1
        else:
            logger.debug(f'  {sku}: group="{group_name}" | category="{category_name}"')
            stats['updated'] += 1

    if not dry_run:
        conn.commit()

    cur.close()
    conn.close()
    return stats


def show_cpa_mapping_stats():
    """
    Показує скільки товарів матчиться з prom_cpa_rates через group_name.
    Допомагає зрозуміти якість маппінгу.
    """
    conn = get_connection()
    cur = conn.cursor()

    # Розподіл по group_name
    cur.execute('''
        SELECT prom_group_name, COUNT(*) as cnt
        FROM my_products
        WHERE prom_group_name IS NOT NULL AND prom_group_name != ''
        GROUP BY prom_group_name
        ORDER BY cnt DESC
        LIMIT 30
    ''')
    rows = cur.fetchall()
    logger.info('\n=== Топ-30 груп товарів Prom ===')
    for r in rows:
        logger.info(f'  {r["cnt"]:4d} × {r["prom_group_name"]}')

    # Перевіряємо маппінг на prom_cpa_rates
    cur.execute('''
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN prom_category_name IS NOT NULL THEN 1 END) as with_category,
            COUNT(CASE WHEN prom_group_name IS NOT NULL THEN 1 END) as with_group
        FROM my_products
        WHERE price_our > 0
    ''')
    row = cur.fetchone()
    logger.info(f'\n=== Покриття категорій ===')
    logger.info(f'  Всього товарів з ціною: {row["total"]}')
    logger.info(f'  З prom_category_name:   {row["with_category"]}')
    logger.info(f'  З prom_group_name:      {row["with_group"]}')

    # Топ категорій Prom
    cur.execute('''
        SELECT prom_category_name, COUNT(*) as cnt
        FROM my_products
        WHERE prom_category_name IS NOT NULL AND prom_category_name != ''
        GROUP BY prom_category_name
        ORDER BY cnt DESC
        LIMIT 20
    ''')
    rows = cur.fetchall()
    if rows:
        logger.info('\n=== Топ-20 категорій Prom ===')
        for r in rows:
            logger.info(f'  {r["cnt"]:4d} × {r["prom_category_name"]}')

    cur.close()
    conn.close()


def run(dry_run: bool = False, stats_only: bool = False):
    logger.info('=== Fetch Prom Categories — старт ===')

    if stats_only:
        show_cpa_mapping_stats()
        return

    # Крок 1: додаємо колонки
    ensure_columns()

    # Крок 2: завантажуємо з Prom API
    products = fetch_all_prom_products()

    if not products:
        logger.error('Не отримано жодного товару з Prom API')
        return

    # Крок 3: зберігаємо в БД
    stats = save_to_db(products, dry_run=dry_run)

    # Крок 4: статистика маппінгу
    if not dry_run:
        show_cpa_mapping_stats()

    msg = f'''✅ <b>Prom Categories оновлено</b>
Оброблено: {len(products)}
Оновлено: {stats["updated"]}
Без SKU: {stats["no_sku"]}
Не знайдено в БД: {stats["no_match"]}'''

    logger.success(msg.replace('<b>', '').replace('</b>', ''))
    if not dry_run:
        tg(msg)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fetch Prom product categories')
    parser.add_argument('--dry-run', action='store_true', help='Тільки перегляд без запису')
    parser.add_argument('--stats', action='store_true', help='Тільки статистика маппінгу')
    args = parser.parse_args()

    run(dry_run=args.dry_run, stats_only=args.stats)
