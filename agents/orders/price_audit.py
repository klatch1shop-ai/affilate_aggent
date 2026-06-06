"""
agents/orders/price_audit.py
=============================
Аудит цін: порівнює поточні ціни в БД з новими розрахованими.

Алгоритм:
1. Завантажує XML фід TOPTUL (актуальні ціни постачальника)
2. Для кожного товару розраховує нову ціну: ціна_постачальника * (1 + CPA)
3. Порівнює з поточною ціною в БД
4. Записує повний лог змін у CSV файл
5. Окремий файл алертів для товарів зі зміною > ALERT_THRESHOLD%
6. Telegram звіт зі статистикою + файл алертів як вкладення

Запуск:
    python3 agents/orders/price_audit.py                    # стандартний
    python3 agents/orders/price_audit.py --threshold 10     # алерт при зміні >10%
    python3 agents/orders/price_audit.py --no-telegram      # без Telegram

Файли результатів:
    logs/price_audit_YYYYMMDD_HHMMSS.csv   — повний лог всіх товарів
    logs/price_alerts_YYYYMMDD_HHMMSS.csv  — тільки алерти (різкі зміни)
"""

import os, sys, requests, time, csv, json, argparse
import xml.etree.ElementTree as ET
from datetime import datetime
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection
from shared.utils.pricing import calc_price, get_prom_cpa, DEFAULT_PROM_CPA

# =============================================
# КОНСТАНТИ
# =============================================

ALERT_THRESHOLD_DEFAULT = 20.0  # % зміни ціни для алерту

TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)

LOGS_DIR = '/home/tek/agent-system/logs'

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')


# =============================================
# TELEGRAM
# =============================================

def tg_message(text: str):
    """Відправляє текстове повідомлення в Telegram."""
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={
                'chat_id': TELEGRAM_ADMIN,
                'text': text,
                'parse_mode': 'HTML'
            },
            timeout=15
        )
    except Exception as e:
        logger.error(f'Telegram message помилка: {e}')


def tg_file(file_path: str, caption: str = ''):
    """Відправляє файл в Telegram."""
    try:
        with open(file_path, 'rb') as f:
            requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument',
                data={
                    'chat_id': TELEGRAM_ADMIN,
                    'caption': caption,
                    'parse_mode': 'HTML'
                },
                files={'document': f},
                timeout=60
            )
        logger.success(f'Файл відправлено в Telegram: {os.path.basename(file_path)}')
    except Exception as e:
        logger.error(f'Telegram file помилка: {e}')


# =============================================
# 1. ФІД TOPTUL
# =============================================

def load_feed() -> dict:
    """
    Завантажує XML фід TOPTUL.
    Повертає dict: SKU → {price, available, stock}
    """
    logger.info('Завантажуємо фід TOPTUL...')
    try:
        resp = requests.get(TOPTUL_FEED, timeout=120)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        offers = root.find('shop').find('offers').findall('offer')

        feed = {}
        for offer in offers:
            sku_el = offer.find('vendorCode')
            sku = (sku_el.text or '').strip() if sku_el is not None else ''
            if not sku:
                sku = (offer.get('id') or '').upper()
            if not sku:
                continue

            price_el = offer.find('price')
            price = float(price_el.text) if price_el is not None else 0.0
            available = offer.get('available', 'true') == 'true'
            stock_el = offer.find('stock_quantity')
            stock = stock_el.text if stock_el is not None else '*'

            feed[sku.upper()] = {
                'price': price,
                'available': available,
                'stock': stock,
            }

        logger.success(f'Фід завантажено: {len(feed)} товарів')
        return feed

    except Exception as e:
        logger.error(f'Помилка завантаження фіду: {e}')
        return {}


# =============================================
# 2. БД — ЗАВАНТАЖЕННЯ ТОВАРІВ
# =============================================

def load_db_products() -> list:
    """
    Завантажує всі товари з my_products.
    Повертає list of dicts.
    """
    conn = get_connection()
    cur = conn.cursor()

    # Перевіряємо наявність колонок категорій
    cur.execute('''
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'my_products'
        AND column_name IN ('prom_category_name', 'prom_group_name')
    ''')
    existing = {r['column_name'] for r in cur.fetchall()}

    extra = ''
    if 'prom_category_name' in existing:
        extra += ', prom_category_name'
    if 'prom_group_name' in existing:
        extra += ', prom_group_name'

    cur.execute(f'''
        SELECT id, sku, name_uk, price_supplier, price_our{extra}
        FROM my_products
        WHERE price_supplier IS NOT NULL AND price_supplier > 0
        ORDER BY sku
    ''')
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    logger.info(f'БД: завантажено {len(rows)} товарів')
    return rows


# =============================================
# 3. АУДИТ ЦІН
# =============================================

def audit_prices(
    feed: dict,
    db_products: list,
    alert_threshold: float
) -> tuple:
    """
    Порівнює поточні ціни з новими розрахованими.

    Returns:
        tuple: (all_results, alerts)
            all_results — список всіх товарів з порівнянням
            alerts — список товарів зі зміною > alert_threshold%
    """
    all_results = []
    alerts = []

    total = len(db_products)
    logger.info(f'Аудит {total} товарів...')

    for i, product in enumerate(db_products):
        sku = (product.get('sku') or '').strip().upper()
        if not sku:
            continue

        name = (product.get('name_uk') or sku)[:60]
        old_supplier_price = float(product.get('price_supplier') or 0)
        old_our_price = float(product.get('price_our') or 0)

        # Беремо ціну з фіду
        feed_info = feed.get(sku)
        if not feed_info:
            # Товар не знайдено у фіді
            result = {
                'sku': sku,
                'name': name,
                'status': 'not_in_feed',
                'old_supplier': old_supplier_price,
                'new_supplier': 0,
                'old_our': old_our_price,
                'new_our': 0,
                'supplier_diff_pct': 0,
                'our_diff_pct': 0,
                'cpa': 0,
                'cpa_source': '',
                'available': False,
                'stock': '—',
                'is_alert': False,
                'alert_reason': '',
            }
            all_results.append(result)
            continue

        new_supplier_price = feed_info['price']
        available = feed_info['available']
        stock = feed_info['stock']

        # Визначаємо CPA
        prom_category = (product.get('prom_category_name') or '').strip()
        prom_group = (product.get('prom_group_name') or '').strip()

        cpa_source = 'default'
        if prom_category:
            cpa = get_prom_cpa(prom_category)
            if cpa != DEFAULT_PROM_CPA:
                cpa_source = prom_category
            elif prom_group:
                cpa = get_prom_cpa(prom_group)
                if cpa != DEFAULT_PROM_CPA:
                    cpa_source = prom_group
                else:
                    cpa_source = 'default'
        elif prom_group:
            cpa = get_prom_cpa(prom_group)
            if cpa != DEFAULT_PROM_CPA:
                cpa_source = prom_group
            else:
                cpa_source = 'default'
        else:
            cpa = DEFAULT_PROM_CPA
            cpa_source = 'default'

        # Розраховуємо нову ціну
        new_our_price = calc_price(new_supplier_price, cpa)

        # Відсоток зміни ціни постачальника
        if old_supplier_price > 0:
            supplier_diff_pct = (new_supplier_price - old_supplier_price) / old_supplier_price * 100
        else:
            supplier_diff_pct = 0

        # Відсоток зміни нашої ціни
        if old_our_price > 0:
            our_diff_pct = (new_our_price - old_our_price) / old_our_price * 100
        else:
            our_diff_pct = 0

        # Визначаємо чи є алерт
        is_alert = False
        alert_reason = ''

        if abs(our_diff_pct) >= alert_threshold:
            is_alert = True
            direction = 'подорожчало' if our_diff_pct > 0 else 'подешевшало'
            alert_reason = f'{direction} на {abs(our_diff_pct):.1f}%'

        if not available and old_our_price > 0:
            is_alert = True
            alert_reason = ('відсутній у фіді + ' + alert_reason).strip(' + ')

        result = {
            'sku': sku,
            'name': name,
            'status': 'ok',
            'old_supplier': old_supplier_price,
            'new_supplier': new_supplier_price,
            'old_our': old_our_price,
            'new_our': new_our_price,
            'supplier_diff_pct': round(supplier_diff_pct, 2),
            'our_diff_pct': round(our_diff_pct, 2),
            'cpa': round(cpa * 100, 2),
            'cpa_source': cpa_source,
            'available': available,
            'stock': stock,
            'is_alert': is_alert,
            'alert_reason': alert_reason,
        }
        all_results.append(result)

        if is_alert:
            alerts.append(result)

        if (i + 1) % 500 == 0:
            logger.info(f'Оброблено {i+1}/{total}...')

    logger.success(f'Аудит завершено: {len(all_results)} товарів, {len(alerts)} алертів')
    return all_results, alerts


# =============================================
# 4. ЗАПИС CSV ФАЙЛІВ
# =============================================

CSV_HEADERS = [
    'SKU', 'Назва', 'Статус',
    'Ціна постач. стара', 'Ціна постач. нова', 'Зміна постач. %',
    'Наша ціна стара', 'Наша ціна нова', 'Зміна нашої %',
    'CPA %', 'Джерело CPA',
    'Наявність', 'Залишок',
    'Алерт', 'Причина алерту',
]


def write_csv(results: list, file_path: str):
    """Записує результати у CSV файл."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(CSV_HEADERS)

        for r in results:
            writer.writerow([
                r['sku'],
                r['name'],
                r['status'],
                f"{r['old_supplier']:.2f}",
                f"{r['new_supplier']:.2f}",
                f"{r['supplier_diff_pct']:+.2f}%",
                f"{r['old_our']:.2f}",
                f"{r['new_our']:.2f}",
                f"{r['our_diff_pct']:+.2f}%",
                f"{r['cpa']:.2f}%",
                r['cpa_source'],
                'Так' if r['available'] else 'Ні',
                r['stock'],
                'Так' if r['is_alert'] else 'Ні',
                r['alert_reason'],
            ])

    logger.success(f'CSV записано: {file_path} ({len(results)} рядків)')


# =============================================
# 5. ГОЛОВНИЙ ЗАПУСК
# =============================================

def run(alert_threshold: float = ALERT_THRESHOLD_DEFAULT, send_telegram: bool = True):
    logger.info('=== Price Audit старт ===')
    logger.info(f'Поріг алерту: >{alert_threshold:.0f}%')

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    audit_file = f'{LOGS_DIR}/price_audit_{timestamp}.csv'
    alerts_file = f'{LOGS_DIR}/price_alerts_{timestamp}.csv'

    # Завантажуємо дані
    feed = load_feed()
    if not feed:
        tg_message('⚠️ <b>Price Audit</b>: не вдалось завантажити фід TOPTUL')
        return

    db_products = load_db_products()
    if not db_products:
        logger.error('Немає товарів в БД')
        return

    # Аудит
    all_results, alerts = audit_prices(feed, db_products, alert_threshold)

    # Статистика
    in_feed = [r for r in all_results if r['status'] == 'ok']
    not_in_feed = [r for r in all_results if r['status'] == 'not_in_feed']
    price_up = [r for r in in_feed if r['our_diff_pct'] > 1]
    price_down = [r for r in in_feed if r['our_diff_pct'] < -1]
    no_change = [r for r in in_feed if abs(r['our_diff_pct']) <= 1]
    unavailable = [r for r in in_feed if not r['available']]
    default_cpa = [r for r in in_feed if r['cpa_source'] == 'default']

    # Записуємо CSV файли
    write_csv(all_results, audit_file)
    if alerts:
        write_csv(alerts, alerts_file)
        logger.info(f'Алертів: {len(alerts)}')
    else:
        logger.info('Алертів немає')

    # Топ найбільших змін
    top_up = sorted(price_up, key=lambda x: -x['our_diff_pct'])[:5]
    top_down = sorted(price_down, key=lambda x: x['our_diff_pct'])[:5]

    # Формуємо Telegram повідомлення
    msg = f'''📊 <b>Price Audit — {datetime.now().strftime("%d.%m.%Y %H:%M")}</b>

📦 Всього товарів: {len(all_results)}
✅ Знайдено у фіді: {len(in_feed)}
❓ Відсутні у фіді: {len(not_in_feed)}
🚫 Недоступні: {len(unavailable)}

💰 Зміни цін:
📈 Подорожчало: {len(price_up)}
📉 Подешевшало: {len(price_down)}
➡️ Без змін: {len(no_change)}

⚠️ Алертів (>{alert_threshold:.0f}%): {len(alerts)}
🔄 Fallback CPA 15%: {len(default_cpa)} товарів'''

    if top_up:
        msg += '\n\n📈 <b>Найбільше подорожчало:</b>'
        for r in top_up:
            msg += f'\n  {r["sku"]}: {r["old_our"]:.0f}→{r["new_our"]:.0f} грн ({r["our_diff_pct"]:+.1f}%)'

    if top_down:
        msg += '\n\n📉 <b>Найбільше подешевшало:</b>'
        for r in top_down:
            msg += f'\n  {r["sku"]}: {r["old_our"]:.0f}→{r["new_our"]:.0f} грн ({r["our_diff_pct"]:+.1f}%)'

    if alerts:
        msg += f'\n\n📎 Файл алертів: {os.path.basename(alerts_file)}'

    logger.success(msg.replace('<b>', '').replace('</b>', ''))

    if send_telegram:
        tg_message(msg)
        if alerts:
            tg_file(
                alerts_file,
                caption=f'⚠️ Алерти цін {datetime.now().strftime("%d.%m.%Y")} — {len(alerts)} товарів зі зміною >{alert_threshold:.0f}%'
            )
        # Повний звіт також відправляємо
        tg_file(
            audit_file,
            caption=f'📊 Повний аудит цін {datetime.now().strftime("%d.%m.%Y")} — {len(all_results)} товарів'
        )

    logger.success(f'Аудит завершено. Файли:')
    logger.success(f'  Повний: {audit_file}')
    if alerts:
        logger.success(f'  Алерти: {alerts_file}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Price Audit — аудит цін з алертами')
    parser.add_argument('--threshold', type=float, default=ALERT_THRESHOLD_DEFAULT,
                        help=f'Поріг алерту у %% (default: {ALERT_THRESHOLD_DEFAULT})')
    parser.add_argument('--no-telegram', action='store_true',
                        help='Не відправляти в Telegram')
    args = parser.parse_args()

    run(
        alert_threshold=args.threshold,
        send_telegram=not args.no_telegram
    )
