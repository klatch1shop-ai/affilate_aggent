"""
agents/orders/price_updater.py
================================
Щоденне оновлення цін на Prom.ua

Алгоритм:
1. Завантажує XML фід TOPTUL
2. Порівнює ціни фіду з БД
3. Для кожного зміненого товару — бере реальну CPA з prom_cpa_rates
   (через prom_category_name або prom_group_name → fuzzy match)
4. Розраховує нову ціну: РРЦ / (1 - CPA)
5. Оновлює змінені ціни на Prom через API батчами по 100
6. Telegram звіт

Запуск:
    python3 agents/orders/price_updater.py              # стандартний
    python3 agents/orders/price_updater.py --force      # переоцінити всі товари
    python3 agents/orders/price_updater.py --dry-run    # без запису змін
    python3 agents/orders/price_updater.py --limit 100  # тільки N товарів

Cron: 0 8 * * * (щодня о 8:00)
"""
import os, sys, requests, json, time, argparse
import xml.etree.ElementTree as ET
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection
from shared.utils.pricing import calc_price, get_prom_cpa, DEFAULT_PROM_CPA

PROM_TOKEN = os.getenv('PROM_API_TOKEN')
PROM_HEADERS = {'Authorization': f'Bearer {PROM_TOKEN}'}
PROM_BASE = 'https://my.prom.ua/api/v1'

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')

TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)

MIN_PRICE = 40.0
ROUND_TO = 10


def tg(text: str):
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_ADMIN, 'text': text, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.error(f'Telegram: {e}')


# =============================================
# 1. ФІД TOPTUL
# =============================================

def load_feed() -> dict:
    """Завантажує XML фід TOPTUL. SKU береться з <vendorCode>."""
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
# 2. PROM API — ЗАВАНТАЖЕННЯ ТОВАРІВ
# =============================================

def load_prom_map() -> dict:
    """
    Завантажує всі товари з Prom API.
    Повертає dict: SKU → {id, price}
    """
    logger.info('Завантажуємо товари з Prom API...')
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
            logger.error(f'Prom API помилка: {e}')
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

    logger.success(f'Prom API: {len(prom_map)} товарів з SKU')
    return prom_map


# =============================================
# 3. БД — ЗАВАНТАЖЕННЯ ТОВАРІВ
# =============================================

def load_db_products(limit: int = None, force: bool = False) -> list:
    """
    Завантажує товари з БД.

    Args:
        limit: обмеження кількості (None = всі)
        force: True = всі товари, False = тільки ті де ціна фіду змінилась

    Returns:
        list of dicts: id, sku, price_supplier, price_our,
                       prom_category_name, prom_group_name, prom_id
    """
    conn = get_connection()
    cur = conn.cursor()

    # Перевіряємо чи є колонки категорій (можуть бути відсутні до fetch_prom_categories)
    cur.execute('''
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'my_products'
        AND column_name IN ('prom_category_name', 'prom_group_name', 'prom_id')
    ''')
    existing_cols = {r['column_name'] for r in cur.fetchall()}

    select_extra = ''
    if 'prom_category_name' in existing_cols:
        select_extra += ', prom_category_name'
    if 'prom_group_name' in existing_cols:
        select_extra += ', prom_group_name'
    if 'prom_id' in existing_cols:
        select_extra += ', prom_id'

    query = f'''
        SELECT id, sku, price_supplier, price_our{select_extra}
        FROM my_products
        WHERE price_supplier IS NOT NULL AND price_supplier > 0
    '''

    if limit:
        query += f' LIMIT {int(limit)}'

    cur.execute(query)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    logger.info(f'БД: завантажено {len(rows)} товарів')
    return [dict(r) for r in rows]


# =============================================
# 4. ГОЛОВНА ЛОГІКА ОНОВЛЕННЯ ЦІН
# =============================================

def run(force: bool = False, dry_run: bool = False, limit: int = None):
    logger.info('=== Price Updater старт ===')
    if force:
        logger.info('Режим --force: переоцінюємо всі товари')
    if dry_run:
        logger.info('Режим --dry-run: без запису змін')

    # Завантажуємо дані
    feed = load_feed()
    if not feed:
        tg('⚠️ <b>Price Updater</b>: не вдалось завантажити фід TOPTUL')
        return

    prom_map = load_prom_map()
    db_products = load_db_products(limit=limit)

    conn = get_connection()
    cur = conn.cursor()

    changed = []        # список змін для звіту
    price_updates = []  # список для Prom API батч-оновлення
    cpa_used = {}       # статистика яких CPA використано

    for product in db_products:
        sku = (product.get('sku') or '').strip().upper()
        if not sku:
            continue

        feed_info = feed.get(sku)
        if not feed_info:
            continue  # товар є в БД але не в фіді — пропускаємо

        new_feed_price = feed_info['price']
        old_feed_price = float(product.get('price_supplier') or 0)
        old_our_price = float(product.get('price_our') or 0)

        # Перевіряємо чи змінилась ціна фіду (або force режим)
        price_changed = abs(new_feed_price - old_feed_price) >= 0.5
        if not force and not price_changed:
            continue

        # Визначаємо CPA для цього товару
        # Пріоритет: prom_category_name → prom_group_name → DEFAULT
        prom_category = (product.get('prom_category_name') or '').strip()
        prom_group = (product.get('prom_group_name') or '').strip()

        cpa_source = 'default'
        if prom_category:
            cpa = get_prom_cpa(prom_category)
            if cpa != DEFAULT_PROM_CPA:
                cpa_source = f'category:{prom_category}'
            elif prom_group:
                cpa = get_prom_cpa(prom_group)
                if cpa != DEFAULT_PROM_CPA:
                    cpa_source = f'group:{prom_group}'
        elif prom_group:
            cpa = get_prom_cpa(prom_group)
            if cpa != DEFAULT_PROM_CPA:
                cpa_source = f'group:{prom_group}'
        else:
            cpa = DEFAULT_PROM_CPA

        # Рахуємо нову ціну
        new_our_price = calc_price(new_feed_price, cpa)

        # Перевіряємо чи змінилась наша ціна
        if not force and abs(new_our_price - old_our_price) < 1.0:
            continue

        diff_pct = ((new_feed_price - old_feed_price) / old_feed_price * 100) if old_feed_price > 0 else 0

        change = {
            'sku': sku,
            'old_feed': old_feed_price,
            'new_feed': new_feed_price,
            'old_our': old_our_price,
            'new_our': new_our_price,
            'diff_pct': diff_pct,
            'cpa': cpa,
            'cpa_source': cpa_source,
        }
        changed.append(change)

        # Статистика CPA
        cpa_key = f'{cpa*100:.2f}%'
        cpa_used[cpa_key] = cpa_used.get(cpa_key, 0) + 1

        if not dry_run:
            # Оновлюємо БД
            cur.execute(
                'UPDATE my_products SET price_supplier=%s, price_our=%s WHERE sku=%s',
                (new_feed_price, new_our_price, product['sku'])
            )

            # Готуємо для Prom API
            prom_info = prom_map.get(sku)
            if prom_info and abs(prom_info['price'] - new_our_price) >= 1.0:
                price_updates.append({'id': prom_info['id'], 'price': new_our_price})

    if not dry_run:
        conn.commit()

    cur.close()
    conn.close()

    logger.info(f'Змін цін: {len(changed)}')
    logger.info(f'CPA розподіл: {cpa_used}')

    if not changed:
        logger.success('Ціни актуальні — змін немає')
        tg('📊 <b>Price Updater</b>: ціни актуальні, змін немає')
        return

    # Оновлюємо ціни на Prom батчами
    updated_prom = 0
    if not dry_run and price_updates:
        logger.info(f'Оновлюємо {len(price_updates)} цін на Prom...')
        for i in range(0, len(price_updates), 100):
            batch = price_updates[i:i+100]
            try:
                resp = requests.post(
                    f'{PROM_BASE}/products/edit',
                    headers=PROM_HEADERS,
                    json=batch,
                    timeout=30
                )
                if resp.status_code == 200:
                    processed = resp.json().get('processed_ids', [])
                    updated_prom += len(processed)
                    logger.success(f'Prom батч {i//100+1}: оновлено {len(processed)}')
                else:
                    logger.error(f'Prom API помилка: {resp.status_code} {resp.text[:200]}')
            except Exception as e:
                logger.error(f'Prom API батч помилка: {e}')
            time.sleep(0.5)

    # Звіт
    up = [c for c in changed if c['diff_pct'] > 0]
    down = [c for c in changed if c['diff_pct'] < 0]
    forced = [c for c in changed if c['diff_pct'] == 0]

    cpa_stat_str = ', '.join([f'{k}:{v}шт' for k, v in sorted(cpa_used.items())])

    msg = f'''📊 <b>Price Updater — звіт</b>

Всього змін: {len(changed)}
📈 Подорожчало: {len(up)}
📉 Подешевшало: {len(down)}
🔄 Переоцінено: {len(forced)}
✅ Оновлено на Prom: {updated_prom}

📌 CPA: {cpa_stat_str}'''

    if dry_run:
        msg += '\n\n⚠️ DRY RUN — зміни не застосовані'

    # Топ змін
    if up:
        top_up = sorted(up, key=lambda x: -abs(x['diff_pct']))[:3]
        msg += '\n\n📈 Подорожчало (топ 3):'
        for c in top_up:
            msg += f'\n  {c["sku"]}: {c["old_our"]:.0f}→{c["new_our"]:.0f} грн ({c["diff_pct"]:+.1f}%) CPA={c["cpa"]*100:.1f}%'

    if down:
        top_down = sorted(down, key=lambda x: abs(x['diff_pct']))[:3]
        msg += '\n\n📉 Подешевшало (топ 3):'
        for c in top_down:
            msg += f'\n  {c["sku"]}: {c["old_our"]:.0f}→{c["new_our"]:.0f} грн ({c["diff_pct"]:+.1f}%) CPA={c["cpa"]*100:.1f}%'

    logger.success(msg.replace('<b>', '').replace('</b>', ''))
    tg(msg)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Price Updater — оновлення цін на Prom')
    parser.add_argument('--force', action='store_true',
                        help='Переоцінити всі товари (навіть якщо ціна не змінилась)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Показати зміни без запису')
    parser.add_argument('--limit', type=int, default=None,
                        help='Обмеження кількості товарів (для тесту)')
    args = parser.parse_args()

    run(force=args.force, dry_run=args.dry_run, limit=args.limit)
