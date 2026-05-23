"""
agents/orders/epicentr_order_agent.py
========================================
Агент обробки замовлень Єпіцентру через Merchant API.

Алгоритм (кожні 5 хвилин):
1. GET /v3/oms/orders?filter[statusCode][]=new  — нові замовлення
2. Для кожного нового:
   a) GET /v5/oms/orders/{id} — деталі
   b) Перевірити наявність товарів у фіді TOPTUL
   c) Якщо є → POST change-status/to/confirmed_by_merchant (отримуємо контакти)
   d) Зберегти замовлення в БД
   e) Відправити Email постачальнику (Грандінструмент)
   f) Telegram сповіщення
3. Якщо товару немає → canceled_by_merchant + причина product_not_available

Запуск:
    python3 agents/orders/epicentr_order_agent.py

Як сервіс:
    systemctl start epicentr-order-agent
"""

import os, sys, time, json, requests
from datetime import datetime, timezone
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# =============================================
# КОНФІГУРАЦІЯ
# =============================================

EPICENTR_TOKEN   = os.getenv('EPICENTR_TOKEN', '')
EPICENTR_BASE    = os.getenv('EPICENTR_API_URL', 'https://merchant-api.epicentrm.com.ua').rstrip('/')
EPICENTR_HEADERS = {
    'Authorization': f'Bearer {EPICENTR_TOKEN}',
    'Content-Type':  'application/json',
    'Accept-Language': 'uk',
}

TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')
SUPPLIER_EMAIL = 'opt@grandinstrument.ua'
FROM_EMAIL     = os.getenv('SMTP_FROM', 'klatch1.shop@gmail.com')

POLL_INTERVAL = 300  # 5 хвилин
FEED_CACHE_TTL = 3600  # 1 година

# =============================================
# УТИЛІТИ
# =============================================

def api_get(path: str, params: dict = None) -> dict:
    try:
        r = requests.get(f'{EPICENTR_BASE}{path}',
                        headers=EPICENTR_HEADERS,
                        params=params or {},
                        timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f'[Єпіцентр API GET] {path}: {e}')
        return {}


def api_post(path: str, data: dict = None) -> tuple:
    """Returns (status_code, response_dict)"""
    try:
        r = requests.post(f'{EPICENTR_BASE}{path}',
                         headers=EPICENTR_HEADERS,
                         json=data or {},
                         timeout=30)
        return r.status_code, (r.json() if r.content else {})
    except Exception as e:
        logger.error(f'[Єпіцентр API POST] {path}: {e}')
        return 0, {}


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
# КЕШ ФІДУ TOPTUL
# =============================================

_feed_cache = {'data': {}, 'loaded_at': 0}


def get_feed() -> dict:
    """Завантажує фід TOPTUL з кешуванням на 1 годину."""
    now = time.time()
    if now - _feed_cache['loaded_at'] < FEED_CACHE_TTL and _feed_cache['data']:
        return _feed_cache['data']

    logger.info('[Єпіцентр] Завантажуємо фід TOPTUL...')
    try:
        import xml.etree.ElementTree as ET
        resp = requests.get(TOPTUL_FEED, timeout=120)
        root = ET.fromstring(resp.content)
        feed = {}
        for offer in root.find('shop').find('offers').findall('offer'):
            sku_el = offer.find('vendorCode')
            sku = (sku_el.text or '').strip().upper() if sku_el is not None else ''
            if not sku:
                continue
            price_el = offer.find('price')
            feed[sku] = {
                'price':     float(price_el.text) if price_el is not None else 0,
                'available': offer.get('available', 'true') == 'true',
                'stock':     getattr(offer.find('stock_quantity'), 'text', '*'),
            }
        _feed_cache['data'] = feed
        _feed_cache['loaded_at'] = now
        logger.success(f'[Єпіцентр] Фід завантажено: {len(feed)} товарів')
        return feed
    except Exception as e:
        logger.error(f'[Єпіцентр] Помилка фіду: {e}')
        return _feed_cache['data']


# =============================================
# БД: ЗАМОВЛЕННЯ
# =============================================

def is_order_processed(epicentr_order_id: str) -> bool:
    """Перевіряє чи замовлення вже оброблялось."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            'SELECT id FROM orders WHERE epicentr_order_id=%s',
            (epicentr_order_id,)
        )
        exists = cur.fetchone() is not None
        cur.close(); conn.close()
        return exists
    except Exception as e:
        logger.error(f'[БД] is_order_processed: {e}')
        return False


def save_order(order: dict, status: str, notes: str = ''):
    """Зберігає замовлення в БД."""
    try:
        addr = order.get('address', {})
        items = order.get('items', [])
        shipment = addr.get('shipment', {})

        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO orders (
                epicentr_order_id, prom_order_id, status,
                customer_name, customer_phone, customer_email,
                total_price, delivery_provider,
                products_json, notes, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (epicentr_order_id) DO UPDATE SET
                status=EXCLUDED.status,
                notes=EXCLUDED.notes,
                updated_at=NOW()
        ''', (
            order.get('id'),
            order.get('number'),
            status,
            f"{addr.get('firstName','')} {addr.get('lastName','')}".strip(),
            addr.get('phone', ''),
            addr.get('email', ''),
            float(order.get('subtotal', 0)),
            shipment.get('provider', ''),
            json.dumps(items, ensure_ascii=False),
            notes,
        ))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        logger.error(f'[БД] save_order: {e}')


# =============================================
# ПЕРЕВІРКА НАЯВНОСТІ ТОВАРІВ
# =============================================

def check_items_availability(items: list, feed: dict) -> tuple:
    """
    Перевіряє наявність товарів у фіді TOPTUL.

    NOTE: В Єпіцентрі SKU = їхній внутрішній ID (числовий).
    Нам потрібен маппінг epicentr_product_id → наш_sku.
    Якщо маппінгу немає — шукаємо по назві в my_products.

    Returns: (all_available: bool, unavailable_items: list)
    """
    unavailable = []

    try:
        conn = get_connection()
        cur = conn.cursor()

        for item in items:
            epicentr_sku = str(item.get('sku', ''))
            title = item.get('title', '')

            # Шукаємо наш SKU по маппінгу
            our_sku = None

            # Варіант 1: по epicentr_article або epicentr_product_id
            cur.execute('''
                SELECT our_sku FROM epicentr_sku_mapping
                WHERE epicentr_article = %s OR epicentr_product_id::text = %s
                LIMIT 1
            ''', (epicentr_sku, epicentr_sku))
            row = cur.fetchone()
            if row:
                our_sku = row['our_sku']

            # Варіант 2: пряме співпадання SKU
            if not our_sku:
                cur.execute(
                    'SELECT sku FROM my_products WHERE sku ILIKE %s LIMIT 1',
                    (epicentr_sku,)
                )
                row = cur.fetchone()
                if row:
                    our_sku = row['sku']

            # Варіант 3: пошук по назві
            if not our_sku and title:
                words = title.split()[:3]
                search = ' & '.join(words)
                cur.execute('''
                    SELECT sku FROM my_products
                    WHERE to_tsvector('simple', name_uk) @@ to_tsquery('simple', %s)
                    LIMIT 1
                ''', (search,))
                row = cur.fetchone()
                if row:
                    our_sku = row['sku']

            # Перевіряємо у фіді
            if our_sku:
                feed_info = feed.get(our_sku.upper())
                if not feed_info or not feed_info.get('available', False):
                    unavailable.append({
                        'epicentr_sku': epicentr_sku,
                        'our_sku': our_sku,
                        'title': title,
                        'reason': 'не в фіді' if not feed_info else 'недоступний'
                    })
            else:
                logger.warning(f'[Єпіцентр] Не знайдено маппінг для SKU: {epicentr_sku} ({title[:30]})')
                # Якщо немає маппінгу — вважаємо що є (не скасовуємо)

        cur.close(); conn.close()

    except Exception as e:
        logger.error(f'[Єпіцентр] check_items: {e}')

    return len(unavailable) == 0, unavailable


# =============================================
# ПІДТВЕРДЖЕННЯ ЗАМОВЛЕННЯ
# =============================================

async def confirm_order(order_id: str) -> bool:
    """Підтверджує замовлення (new → confirmed_by_merchant)."""
    status_code, resp = api_post(
        f'/v2/oms/orders/{order_id}/change-status/to/confirmed_by_merchant'
    )
    if status_code == 202:
        logger.success(f'[Єпіцентр] Замовлення {order_id} підтверджено')
        return True
    else:
        logger.error(f'[Єпіцентр] Помилка підтвердження {order_id}: {status_code} {resp}')
        return False


def cancel_order(order_id: str, reason: str = 'product_not_available',
                 comment: str = '') -> bool:
    """Скасовує замовлення продавцем."""
    status_code, resp = api_post(
        f'/v2/oms/orders/{order_id}/change-status/to/canceled_by_merchant',
        data={
            'reason_code': reason,
            'comment': comment or f'Товар відсутній у постачальника',
        }
    )
    if status_code == 202:
        logger.success(f'[Єпіцентр] Замовлення {order_id} скасовано: {reason}')
        return True
    else:
        logger.error(f'[Єпіцентр] Помилка скасування {order_id}: {status_code} {resp}')
        return False


# =============================================
# EMAIL ПОСТАЧАЛЬНИКУ
# =============================================

def send_supplier_email(order: dict, items: list):
    """Відправляє замовлення постачальнику Грандінструмент."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    addr = order.get('address', {})
    customer = f"{addr.get('firstName','')} {addr.get('lastName','')}".strip()
    phone = addr.get('phone', '')
    shipment = addr.get('shipment', {})
    delivery = shipment.get('provider', '')
    order_num = order.get('number', '')

    items_text = '\n'.join([
        f"  {i.get('sku','')} | {i.get('title','')[:50]} | {i.get('quantity',1)} шт | {i.get('price',0)} грн"
        for i in items
    ])

    body = f"""Нове замовлення з Єпіцентру #{order_num}

Замовник: {customer}
Телефон: {phone}
Доставка: {delivery}

Товари:
{items_text}

Сума: {order.get('subtotal', 0)} грн

Клієнт ID: {os.getenv('EPICENTR_CLIENT_CODE', '000160594')}

Будь ласка, відправте товар.
"""

    try:
        msg = MIMEMultipart()
        msg['From']    = FROM_EMAIL
        msg['To']      = SUPPLIER_EMAIL
        msg['Subject'] = f'Замовлення Єпіцентр #{order_num}'
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        smtp_user = os.getenv('SMTP_USER', FROM_EMAIL)
        smtp_pass = os.getenv('SMTP_PASSWORD', '')

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        logger.success(f'[Єпіцентр] Email відправлено постачальнику: замовлення #{order_num}')
        return True
    except Exception as e:
        logger.error(f'[Єпіцентр] Email помилка: {e}')
        return False


# =============================================
# ОБРОБКА ОДНОГО ЗАМОВЛЕННЯ
# =============================================

def process_order(order_summary: dict) -> str:
    """
    Обробляє одне замовлення.
    Returns: 'confirmed' | 'canceled' | 'skipped' | 'error'
    """
    order_id  = order_summary.get('id', '')
    order_num = order_summary.get('number', '')
    status    = order_summary.get('statusCode', '')

    if status != 'new':
        return 'skipped'

    if is_order_processed(order_id):
        logger.info(f'[Єпіцентр] #{order_num} вже оброблено')
        return 'skipped'

    # Отримуємо деталі V5
    order = api_get(f'/v5/oms/orders/{order_id}')
    if not order:
        logger.error(f'[Єпіцентр] Не вдалось отримати деталі #{order_num}')
        return 'error'

    items   = order.get('items', [])
    subtotal = float(order.get('subtotal', 0))
    addr    = order.get('address', {})
    skip    = order.get('skipCustomerContact', True)

    logger.info(f'[Єпіцентр] Обробляємо #{order_num}: {len(items)} товарів, {subtotal} грн')

    # Перевіряємо наявність у фіді
    feed = get_feed()
    all_available, unavailable = check_items_availability(items, feed)

    if not all_available:
        # Скасовуємо — товару немає
        names = ', '.join([i['title'][:30] for i in unavailable])
        logger.warning(f'[Єпіцентр] #{order_num} скасовуємо — немає: {names}')

        canceled = cancel_order(
            order_id,
            reason='product_not_available',
            comment=f'Товар відсутній: {names[:200]}'
        )
        save_order(order, 'canceled_no_stock',
                  f'Відсутні: {names}')

        tg(
            f'❌ <b>Єпіцентр #{order_num}</b>\n'
            f'Скасовано — немає в наявності:\n'
            f'{names}\n'
            f'Сума: {subtotal} грн'
        )
        return 'canceled'

    # Підтверджуємо замовлення
    status_code, _ = api_post(
        f'/v2/oms/orders/{order_id}/change-status/to/confirmed_by_merchant'
    )
    if status_code != 202:
        logger.error(f'[Єпіцентр] #{order_num} помилка підтвердження: {status_code}')
        return 'error'

    # Отримуємо оновлені деталі з контактами клієнта
    order_confirmed = api_get(f'/v5/oms/orders/{order_id}')
    if order_confirmed:
        order = order_confirmed

    addr  = order.get('address', {})
    phone = addr.get('phone', '')

    # Зберігаємо в БД
    save_order(order, 'confirmed', 'Підтверджено автоматично')

    # Email постачальнику
    send_supplier_email(order, items)

    # Telegram
    items_text = '\n'.join([
        f"  • {i.get('title','')[:40]} × {i.get('quantity',1)} = {i.get('price',0)*i.get('quantity',1):.0f} грн"
        for i in items
    ])
    shipment = addr.get('shipment', {})

    tg(
        f'✅ <b>Єпіцентр #{order_num}</b>\n'
        f'👤 {addr.get("firstName","")} {addr.get("lastName","")}\n'
        f'📞 {phone}\n'
        f'🚚 {shipment.get("provider","")}\n'
        f'💰 {subtotal} грн\n\n'
        f'{items_text}'
    )

    logger.success(f'[Єпіцентр] #{order_num} підтверджено і відправлено постачальнику')
    return 'confirmed'


# =============================================
# ГОЛОВНИЙ ЦИКЛ
# =============================================

def run_once():
    """Один цикл перевірки нових замовлень."""
    logger.info('[Єпіцентр] Перевіряємо нові замовлення...')

    data = api_get('/v3/oms/orders', {
        'filter[statusCode][]': 'new',
        'limit': 50,
    })

    orders = data.get('items', [])
    if not orders:
        logger.info('[Єпіцентр] Нових замовлень немає')
        return

    logger.info(f'[Єпіцентр] Знайдено нових замовлень: {len(orders)}')

    stats = {'confirmed': 0, 'canceled': 0, 'error': 0}
    for order in orders:
        result = process_order(order)
        if result in stats:
            stats[result] += 1
        time.sleep(1)  # пауза між замовленнями

    logger.info(f'[Єпіцентр] Цикл завершено: {stats}')


def main():
    logger.info('=== Epicentr Order Agent старт ===')
    tg('🟢 <b>Epicentr Order Agent</b> запущено')

    while True:
        try:
            run_once()
        except Exception as e:
            logger.error(f'[Єпіцентр] Критична помилка циклу: {e}')
            tg(f'🔴 <b>Epicentr Order Agent</b> помилка:\n{e}')

        logger.info(f'[Єпіцентр] Очікуємо {POLL_INTERVAL}с...')
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
