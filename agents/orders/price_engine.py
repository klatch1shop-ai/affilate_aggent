"""
agents/orders/price_engine.py
==============================
Головний двигун ціноутворення.

Алгоритм:
1. Завантажує XML фід TOPTUL (актуальні РРЦ)
2. Для кожного товару:
   - Бере попередню ціну з price_history
   - Розраховує нову: feed_price * (1 + CPA)
   - Визначає чи є зміна
   - Записує в price_history (тільки зміни після першого запуску)
3. Оновлює my_products.price_our
4. Оновлює ціни на Prom через API (батчами)
5. Telegram звіт + CSV файл алертів

Режими запуску:
    python3 price_engine.py                  # щоденний (тільки зміни)
    python3 price_engine.py --full           # повний знімок всіх товарів
    python3 price_engine.py --dry-run        # без запису змін
    python3 price_engine.py --no-prom        # без оновлення Prom API
    python3 price_engine.py --limit 100      # тест на N товарах
    python3 price_engine.py --report-only    # тільки звіт без оновлення
"""

import os, sys, requests, time, csv, json, argparse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection
from shared.utils.pricing import calc_price, get_prom_cpa, DEFAULT_PROM_CPA

# =============================================
# КОНСТАНТИ
# =============================================

TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)

PROM_TOKEN = os.getenv('PROM_API_TOKEN')
PROM_HEADERS = {'Authorization': f'Bearer {PROM_TOKEN}'}
PROM_BASE = 'https://my.prom.ua/api/v1'

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')

LOGS_DIR = '/home/tek/agent-system/logs'

# Значення за замовчуванням (перезаписуються з БД)
DEFAULT_CONFIG = {
    'alert_threshold_pct':  20.0,
    'alert_threshold_high': 15.0,
    'high_price_threshold': 1000.0,
    'min_price':            40.0,
    'round_to':             10,
    'history_days_keep':    365,
    'stock_premium_pct':    0.0,
}


# =============================================
# TELEGRAM
# =============================================

def tg(text: str):
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_ADMIN, 'text': text, 'parse_mode': 'HTML'},
            timeout=15
        )
    except Exception as e:
        logger.error(f'Telegram: {e}')


def tg_file(path: str, caption: str = ''):
    try:
        with open(path, 'rb') as f:
            requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument',
                data={'chat_id': TELEGRAM_ADMIN, 'caption': caption, 'parse_mode': 'HTML'},
                files={'document': f},
                timeout=60
            )
    except Exception as e:
        logger.error(f'Telegram file: {e}')


# =============================================
# 1. КОНФІГУРАЦІЯ З БД
# =============================================

def load_config() -> dict:
    """Завантажує налаштування з price_engine_config."""
    config = DEFAULT_CONFIG.copy()
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('SELECT key, value FROM price_engine_config')
        for row in cur.fetchall():
            key = row['key']
            if key in config:
                try:
                    config[key] = type(DEFAULT_CONFIG[key])(row['value'])
                except (ValueError, TypeError):
                    pass
        cur.close(); conn.close()
    except Exception as e:
        logger.warning(f'Не вдалось завантажити config: {e} → використовуємо defaults')
    return config


def update_config(key: str, value: str):
    """Оновлює значення в price_engine_config."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO price_engine_config (key, value, updated_at) VALUES (%s, %s, NOW()) '
            'ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()',
            (key, str(value))
        )
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        logger.error(f'update_config: {e}')


# =============================================
# 2. ФІД TOPTUL
# =============================================

def load_feed() -> dict:
    """
    Завантажує XML фід TOPTUL.
    Returns: dict SKU → {price, available, stock}
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
            sku = (sku_el.text or '').strip().upper() if sku_el is not None else ''
            if not sku:
                sku = (offer.get('id') or '').upper()
            if not sku:
                continue

            price_el = offer.find('price')
            price = float(price_el.text) if price_el is not None else 0.0
            available = offer.get('available', 'true') == 'true'
            stock_el = offer.find('stock_quantity')
            stock = stock_el.text if stock_el is not None else '*'

            feed[sku] = {
                'price': price,
                'available': available,
                'stock': stock or '*',
            }

        logger.success(f'Фід: {len(feed)} товарів')
        return feed

    except Exception as e:
        logger.error(f'Помилка фіду: {e}')
        return {}


# =============================================
# 3. ПОПЕРЕДНІ ЦІНИ З HISTORY
# =============================================

def load_previous_prices() -> dict:
    """
    Завантажує останні ціни з price_history для кожного SKU.
    Returns: dict SKU → {feed_price, our_price, date}
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT DISTINCT ON (sku)
                sku, feed_price, our_price, date
            FROM price_history
            ORDER BY sku, date DESC
        ''')
        result = {
            r['sku'].upper(): {
                'feed_price': float(r['feed_price']),
                'our_price': float(r['our_price']),
                'date': r['date'],
            }
            for r in cur.fetchall()
        }
        cur.close(); conn.close()
        logger.info(f'History: {len(result)} записів')
        return result
    except Exception as e:
        logger.error(f'load_previous_prices: {e}')
        return {}


# =============================================
# 4. ТОВАРИ З БД
# =============================================

def load_db_products(limit: int = None) -> list:
    """Завантажує товари з my_products."""
    conn = get_connection()
    cur = conn.cursor()

    # Перевіряємо наявність колонок категорій
    cur.execute('''
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'my_products'
        AND column_name IN ('prom_category_name', 'prom_group_name', 'prom_id')
    ''')
    existing = {r['column_name'] for r in cur.fetchall()}

    extra = ', '.join(c for c in ['prom_category_name', 'prom_group_name', 'prom_id'] if c in existing)
    if extra:
        extra = ', ' + extra

    query = f'''
        SELECT id, sku, name_uk, price_supplier, price_our{extra}
        FROM my_products
        WHERE price_supplier IS NOT NULL AND price_supplier > 0
        ORDER BY sku
    '''
    if limit:
        query += f' LIMIT {int(limit)}'

    cur.execute(query)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    logger.info(f'БД: {len(rows)} товарів')
    return rows


# =============================================
# 5. PROM API — ЗАВАНТАЖЕННЯ ТОВАРІВ
# =============================================

def load_prom_map() -> dict:
    """Завантажує SKU→prom_id з Prom API."""
    logger.info('Завантажуємо Prom API...')
    prom_map = {}
    last_id = None

    while True:
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
            logger.error(f'Prom API: {e}')
            break

        if not products:
            break

        for p in products:
            sku = (p.get('sku') or '').strip().upper()
            if sku:
                prom_map[sku] = {
                    'id': p.get('id'),
                    'price': float(p.get('price') or 0),
                }

        last_id = products[-1]['id']
        if len(products) < 100:
            break
        time.sleep(0.35)

    logger.success(f'Prom: {len(prom_map)} товарів')
    return prom_map


# =============================================
# 6. ГОЛОВНА ЛОГІКА РОЗРАХУНКУ
# =============================================

def process_products(
    feed: dict,
    db_products: list,
    prev_prices: dict,
    config: dict,
    full_mode: bool = False,
) -> tuple:
    """
    Обробляє кожен товар: розраховує нову ціну, визначає зміни та алерти.

    Returns:
        tuple: (records_to_save, price_updates_for_prom, stats)
    """
    alert_threshold = config['alert_threshold_pct']
    alert_threshold_high = config['alert_threshold_high']
    high_price = config['high_price_threshold']
    min_price = config['min_price']
    round_to = int(config['round_to'])

    records = []        # записи для price_history
    prom_updates = []   # оновлення для Prom API
    stats = {
        'total': 0, 'in_feed': 0, 'not_in_feed': 0,
        'changed': 0, 'unchanged': 0,
        'price_up': 0, 'price_down': 0,
        'alerts': 0, 'unavailable': 0,
        'fallback_cpa': 0,
    }

    today = date.today()

    for product in db_products:
        sku = (product.get('sku') or '').strip().upper()
        if not sku:
            continue

        stats['total'] += 1
        feed_info = feed.get(sku)

        if not feed_info:
            stats['not_in_feed'] += 1
            # Якщо немає у фіді — пишемо запис про недоступність (тільки якщо змінилось)
            prev = prev_prices.get(sku)
            if prev and prev.get('available', True):
                # Був доступний, тепер немає — це зміна
                record = {
                    'sku': sku,
                    'date': today,
                    'feed_price': prev['feed_price'],
                    'our_price': prev['our_price'],
                    'prev_feed_price': prev['feed_price'],
                    'prev_our_price': prev['our_price'],
                    'feed_diff_pct': 0,
                    'our_diff_pct': 0,
                    'cpa_rate': 0,
                    'cpa_source': 'unavailable',
                    'available': False,
                    'stock': '-',
                    'is_change': True,
                    'is_alert': True,
                    'alert_reason': 'зник з фіду',
                    'prom_updated': False,
                }
                records.append(record)
                stats['alerts'] += 1
            continue

        stats['in_feed'] += 1
        new_feed_price = feed_info['price']
        available = feed_info['available']
        stock = feed_info['stock']

        if not available:
            stats['unavailable'] += 1

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
                cpa_source = prom_group if cpa != DEFAULT_PROM_CPA else 'default'
        elif prom_group:
            cpa = get_prom_cpa(prom_group)
            cpa_source = prom_group if cpa != DEFAULT_PROM_CPA else 'default'
        else:
            cpa = DEFAULT_PROM_CPA

        if cpa_source == 'default':
            stats['fallback_cpa'] += 1

        # Розраховуємо нову ціну
        new_our_price = calc_price(new_feed_price, cpa, min_price, round_to)

        # Беремо попередні ціни
        prev = prev_prices.get(sku)
        prev_feed = prev['feed_price'] if prev else float(product.get('price_supplier') or 0)
        prev_our = prev['our_price'] if prev else float(product.get('price_our') or 0)

        # Розраховуємо зміни
        feed_diff_pct = ((new_feed_price - prev_feed) / prev_feed * 100) if prev_feed > 0 else 0
        our_diff_pct = ((new_our_price - prev_our) / prev_our * 100) if prev_our > 0 else 0

        # Визначаємо чи є зміна
        price_changed = abs(new_our_price - prev_our) >= 1.0 or abs(new_feed_price - prev_feed) >= 0.5
        availability_changed = prev and (prev.get('available', True) != available)
        is_change = price_changed or availability_changed or full_mode

        if not is_change:
            stats['unchanged'] += 1
            continue

        stats['changed'] += 1
        if our_diff_pct > 0:
            stats['price_up'] += 1
        elif our_diff_pct < 0:
            stats['price_down'] += 1

        # Визначаємо алерт
        threshold = alert_threshold_high if new_feed_price >= high_price else alert_threshold
        is_alert = abs(our_diff_pct) >= threshold or not available
        alert_reason = ''

        if not available:
            alert_reason = 'недоступний у фіді'
        if abs(our_diff_pct) >= threshold:
            direction = 'подорожчало' if our_diff_pct > 0 else 'подешевшало'
            alert_reason = (alert_reason + f' | {direction} на {abs(our_diff_pct):.1f}%').strip(' | ')

        if is_alert:
            stats['alerts'] += 1

        record = {
            'sku': sku,
            'date': today,
            'feed_price': new_feed_price,
            'our_price': new_our_price,
            'prev_feed_price': prev_feed,
            'prev_our_price': prev_our,
            'feed_diff_pct': round(feed_diff_pct, 2),
            'our_diff_pct': round(our_diff_pct, 2),
            'cpa_rate': round(cpa * 100, 2),
            'cpa_source': cpa_source,
            'available': available,
            'stock': stock,
            'is_change': is_change,
            'is_alert': is_alert,
            'alert_reason': alert_reason,
            'prom_updated': False,
        }
        records.append(record)

        # Готуємо для Prom API (тільки якщо ціна змінилась)
        if abs(new_our_price - prev_our) >= 1.0:
            prom_id = product.get('prom_id')
            if prom_id:
                prom_updates.append({'id': prom_id, 'price': new_our_price, 'sku': sku})

    return records, prom_updates, stats


# =============================================
# 7. ЗАПИС В БД
# =============================================

def save_history(records: list, dry_run: bool = False) -> int:
    """Зберігає записи в price_history і оновлює my_products."""
    if dry_run or not records:
        return 0

    conn = get_connection()
    cur = conn.cursor()
    saved = 0

    for r in records:
        try:
            cur.execute('''
                INSERT INTO price_history (
                    sku, date, feed_price, our_price,
                    prev_feed_price, prev_our_price,
                    feed_diff_pct, our_diff_pct,
                    cpa_rate, cpa_source,
                    available, stock,
                    is_change, is_alert, alert_reason,
                    prom_updated
                ) VALUES (
                    %(sku)s, %(date)s, %(feed_price)s, %(our_price)s,
                    %(prev_feed_price)s, %(prev_our_price)s,
                    %(feed_diff_pct)s, %(our_diff_pct)s,
                    %(cpa_rate)s, %(cpa_source)s,
                    %(available)s, %(stock)s,
                    %(is_change)s, %(is_alert)s, %(alert_reason)s,
                    %(prom_updated)s
                )
                ON CONFLICT (sku, date) DO UPDATE SET
                    feed_price      = EXCLUDED.feed_price,
                    our_price       = EXCLUDED.our_price,
                    prev_feed_price = EXCLUDED.prev_feed_price,
                    prev_our_price  = EXCLUDED.prev_our_price,
                    feed_diff_pct   = EXCLUDED.feed_diff_pct,
                    our_diff_pct    = EXCLUDED.our_diff_pct,
                    cpa_rate        = EXCLUDED.cpa_rate,
                    cpa_source      = EXCLUDED.cpa_source,
                    available       = EXCLUDED.available,
                    stock           = EXCLUDED.stock,
                    is_change       = EXCLUDED.is_change,
                    is_alert        = EXCLUDED.is_alert,
                    alert_reason    = EXCLUDED.alert_reason
            ''', r)

            # Оновлюємо my_products
            cur.execute(
                'UPDATE my_products SET price_supplier=%s, price_our=%s WHERE sku=%s',
                (r['feed_price'], r['our_price'], r['sku'])
            )
            saved += 1

        except Exception as e:
            logger.error(f'save_history {r["sku"]}: {e}')

    conn.commit()
    cur.close(); conn.close()
    logger.success(f'Збережено в history: {saved}')
    return saved


# =============================================
# 8. ОНОВЛЕННЯ PROM API
# =============================================

def update_prom_prices(
    prom_updates: list,
    prom_map: dict,
    records: list,
    dry_run: bool = False
) -> int:
    """Оновлює ціни на Prom батчами по 100."""
    if dry_run or not prom_updates:
        return 0

    # Збагачуємо prom_id з prom_map якщо не було в БД
    batch_data = []
    for upd in prom_updates:
        prom_id = upd.get('id')
        if not prom_id:
            prom_info = prom_map.get(upd['sku'].upper())
            prom_id = prom_info['id'] if prom_info else None
        if prom_id:
            batch_data.append({'id': prom_id, 'price': upd['price']})

    if not batch_data:
        return 0

    updated = 0
    updated_ids = set()

    for i in range(0, len(batch_data), 100):
        batch = batch_data[i:i+100]
        try:
            resp = requests.post(
                f'{PROM_BASE}/products/edit',
                headers=PROM_HEADERS,
                json=batch,
                timeout=30
            )
            if resp.status_code == 200:
                processed = resp.json().get('processed_ids', [])
                updated += len(processed)
                updated_ids.update(str(p) for p in processed)
                logger.success(f'Prom батч {i//100+1}: {len(processed)} оновлено')
            else:
                logger.error(f'Prom помилка {resp.status_code}: {resp.text[:200]}')
        except Exception as e:
            logger.error(f'Prom батч помилка: {e}')
        time.sleep(0.5)

    # Позначаємо prom_updated в history
    if updated_ids and records:
        conn = get_connection()
        cur = conn.cursor()
        today = date.today()
        for r in records:
            prom_info = prom_map.get(r['sku'].upper())
            if prom_info and str(prom_info['id']) in updated_ids:
                cur.execute(
                    'UPDATE price_history SET prom_updated=TRUE WHERE sku=%s AND date=%s',
                    (r['sku'], today)
                )
        conn.commit(); cur.close(); conn.close()

    return updated


# =============================================
# 9. ЗВІТ CSV
# =============================================

def write_alerts_csv(records: list, filepath: str):
    """Записує алерти в CSV."""
    alerts = [r for r in records if r['is_alert']]
    if not alerts:
        return None

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([
            'SKU', 'Ціна фіду стара', 'Ціна фіду нова', 'Зміна фіду %',
            'Наша ціна стара', 'Наша ціна нова', 'Зміна нашої %',
            'CPA %', 'Доступний', 'Залишок', 'Причина алерту'
        ])
        for r in sorted(alerts, key=lambda x: -abs(x['our_diff_pct'])):
            writer.writerow([
                r['sku'],
                f"{r['prev_feed_price']:.2f}",
                f"{r['feed_price']:.2f}",
                f"{r['feed_diff_pct']:+.2f}%",
                f"{r['prev_our_price']:.2f}",
                f"{r['our_price']:.2f}",
                f"{r['our_diff_pct']:+.2f}%",
                f"{r['cpa_rate']:.2f}%",
                'Так' if r['available'] else 'Ні',
                r['stock'],
                r['alert_reason'],
            ])

    logger.success(f'Алерти CSV: {filepath} ({len(alerts)} рядків)')
    return filepath


# =============================================
# 10. ОЧИЩЕННЯ СТАРИХ ЗАПИСІВ
# =============================================

def cleanup_old_history(days_keep: int):
    """Видаляє записи старші за days_keep днів."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cutoff = date.today() - timedelta(days=int(days_keep))
        cur.execute('DELETE FROM price_history WHERE date < %s', (cutoff,))
        deleted = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        if deleted > 0:
            logger.info(f'Очищено старих записів: {deleted} (старіше {cutoff})')
    except Exception as e:
        logger.error(f'cleanup: {e}')


# =============================================
# 11. ГОЛОВНИЙ ЗАПУСК
# =============================================

def run(
    full_mode: bool = False,
    dry_run: bool = False,
    no_prom: bool = False,
    limit: int = None,
    report_only: bool = False,
):
    start_time = datetime.now()
    mode_label = 'ПОВНИЙ' if full_mode else 'ЩОДЕННИЙ'
    logger.info(f'=== Price Engine {mode_label} старт ===')

    config = load_config()
    today_str = date.today().strftime('%Y%m%d_%H%M%S')
    alerts_file = f'{LOGS_DIR}/price_alerts_{today_str}.csv'

    # Завантажуємо дані
    feed = load_feed()
    if not feed:
        tg('⚠️ <b>Price Engine</b>: не вдалось завантажити фід TOPTUL')
        return

    db_products = load_db_products(limit=limit)
    prev_prices = load_previous_prices()

    is_first_run = len(prev_prices) == 0
    if is_first_run:
        logger.info('Перший запуск — збережемо повний знімок всіх товарів')
        full_mode = True

    # Завантажуємо Prom тільки якщо потрібно
    prom_map = {}
    if not no_prom and not dry_run and not report_only:
        prom_map = load_prom_map()

    # Обробляємо товари
    records, prom_updates, stats = process_products(
        feed, db_products, prev_prices, config, full_mode
    )

    elapsed_process = (datetime.now() - start_time).seconds

    # Зберігаємо в БД
    saved = 0
    if not report_only:
        saved = save_history(records, dry_run=dry_run)

    # Оновлюємо Prom
    prom_updated = 0
    if not no_prom and not dry_run and not report_only and prom_updates:
        prom_updated = update_prom_prices(prom_updates, prom_map, records)

    # Записуємо алерти в CSV
    alerts_path = None
    if records:
        alerts_path = write_alerts_csv(records, alerts_file)

    # Оновлюємо last_full_sync
    if full_mode and not dry_run:
        update_config('last_full_sync', date.today().isoformat())

    # Очищення старих записів
    if not dry_run and not report_only:
        cleanup_old_history(config['history_days_keep'])

    elapsed_total = (datetime.now() - start_time).seconds

    # Статистика
    alerts = [r for r in records if r['is_alert']]
    top_up = sorted([r for r in records if r['our_diff_pct'] > 0], key=lambda x: -x['our_diff_pct'])[:5]
    top_down = sorted([r for r in records if r['our_diff_pct'] < 0], key=lambda x: x['our_diff_pct'])[:5]

    mode_emoji = '🔄' if full_mode else '📅'
    msg = f'''{mode_emoji} <b>Price Engine — {mode_label}</b>
{date.today().strftime("%d.%m.%Y %H:%M")}

📦 Перевірено: {stats["total"]}
✅ У фіді: {stats["in_feed"]}
❓ Відсутні у фіді: {stats["not_in_feed"]}
🚫 Недоступні: {stats["unavailable"]}

💾 Збережено в history: {saved}
📈 Подорожчало: {stats["price_up"]}
📉 Подешевшало: {stats["price_down"]}
➡️ Без змін: {stats["unchanged"]}

⚠️ Алертів: {stats["alerts"]}
✅ Оновлено на Prom: {prom_updated}
🔄 Fallback CPA: {stats["fallback_cpa"]}
⏱ Час: {elapsed_total}с'''

    if top_up:
        msg += '\n\n📈 <b>Найбільше подорожчало:</b>'
        for r in top_up:
            msg += f'\n  {r["sku"]}: {r["prev_our_price"]:.0f}→{r["our_price"]:.0f} ({r["our_diff_pct"]:+.1f}%)'

    if top_down:
        msg += '\n\n📉 <b>Найбільше подешевшало:</b>'
        for r in top_down:
            msg += f'\n  {r["sku"]}: {r["prev_our_price"]:.0f}→{r["our_price"]:.0f} ({r["our_diff_pct"]:+.1f}%)'

    if dry_run:
        msg += '\n\n⚠️ <b>DRY RUN — зміни не збережено</b>'

    logger.success(msg.replace('<b>', '').replace('</b>', ''))

    if not dry_run:
        tg(msg)
        if alerts_path and alerts:
            tg_file(
                alerts_path,
                f'⚠️ Алерти цін {date.today().strftime("%d.%m.%Y")} — {len(alerts)} товарів'
            )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Price Engine — щоденне оновлення цін')
    parser.add_argument('--full', action='store_true',
                        help='Повний знімок всіх товарів (ігнорує unchanged)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Без запису в БД і Prom API')
    parser.add_argument('--no-prom', action='store_true',
                        help='Без оновлення Prom API')
    parser.add_argument('--limit', type=int, default=None,
                        help='Обмеження кількості товарів (для тесту)')
    parser.add_argument('--report-only', action='store_true',
                        help='Тільки аналіз без запису')
    args = parser.parse_args()

    run(
        full_mode=args.full,
        dry_run=args.dry_run,
        no_prom=args.no_prom,
        limit=args.limit,
        report_only=args.report_only,
    )
