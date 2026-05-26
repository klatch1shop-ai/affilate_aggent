"""
rozetka_order_agent.py — Агент обробки замовлень Розетки
=========================================================
Цикл:
1. Авторизація (токен 24 год, авто-рефреш)
2. Отримати нові замовлення (status=1)
3. Перевірити наявність у фіді Carvol (stock_quantity > 0)
4. Підтвердити замовлення (status=2)
5. Excel бланк → email постачальнику Carvol
6. Telegram сповіщення
"""
import os, sys, json, time, requests, smtplib, base64
import xml.etree.ElementTree as ET
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from loguru import logger
import xlsxwriter
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# === КОНСТАНТИ ===
ROZETKA_API_TOKEN = os.getenv('ROZETKA_API_TOKEN')
ROZETKA_BASE      = 'https://api-seller.rozetka.com.ua'

CARVOL_FEED = (
    'https://carvol.prom.ua/rozetka_feed.xml'
    '?rozetka_hash_tag=2251d0779efad97117ac08d7efd82c2f'
    '&product_ids=&label_ids=28618299&languages=uk%2Cru&group_ids='
)
CARVOL_EMAIL   = os.getenv('CARVOL_SUPPLIER_EMAIL', 'info@carvol.com.ua')
SUPPLIER_CODE  = os.getenv('CARVOL_SUPPLIER_CODE', '')
SMTP_USER      = os.getenv('SMTP_USER')
SMTP_PASS      = os.getenv('SMTP_PASS')
SMTP_HOST      = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT      = int(os.getenv('SMTP_PORT', '587'))
TG_BOT_TOKEN   = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID     = os.getenv('TG_CHAT_ID')
POLL_INTERVAL  = 300  # 5 хвилин
MARKETPLACE    = 'Розетка'

# === ТОКЕН (авто-рефреш кожні 23 год) ===


def tg(msg: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.warning(f'TG: {e}')


def get_token() -> str:
    """Повертає постійний API токен з кабінету Розетки."""
    if not ROZETKA_API_TOKEN:
        raise Exception('ROZETKA_API_TOKEN не задано в .env!')
    return ROZETKA_API_TOKEN


def rz_headers() -> dict:
    return {
        'Authorization': f'Bearer {get_token()}',
        'Content-Type':  'application/json',
        'Content-Language': 'uk',
    }


# === ФІД CARVOL ===
_carvol_cache = {'data': {}, 'updated': None}


def get_carvol_feed(force=False) -> dict:
    """Повертає {article: {available, price, qty}} з Carvol фіду."""
    now = datetime.now()
    if (not force and _carvol_cache['updated'] and
            (now - _carvol_cache['updated']).seconds < 3600):
        return _carvol_cache['data']

    logger.info('Завантажуємо Carvol фід...')
    r = requests.get(CARVOL_FEED, timeout=120)
    root = ET.fromstring(r.content)
    offers = root.find('shop').find('offers').findall('offer')

    data = {}
    for offer in offers:
        article_el = offer.find('article')
        if article_el is None:
            continue
        article = (article_el.text or '').strip()
        price_el = offer.find('price')
        qty_el   = offer.find('stock_quantity')
        qty      = int(qty_el.text or 0) if qty_el is not None else 0
        data[article] = {
            'available': offer.get('available','false').lower() == 'true' and qty > 0,
            'price':     float(price_el.text or 0) if price_el is not None else 0,
            'qty':       qty,
        }

    _carvol_cache['data']    = data
    _carvol_cache['updated'] = now
    logger.info(f'Carvol фід: {len(data)} SKU')
    return data


# === РОЗЕТКА API ===

def get_new_orders() -> list:
    """Отримати нові замовлення (status=1)."""
    try:
        r = requests.get(
            f'{ROZETKA_BASE}/orders/search',
            headers=rz_headers(),
            params={
                'types': 4,           # нові
                'expand': 'purchases,delivery,status_available',
                'sort': '-id',
                'page': 1,
            },
            timeout=30
        )
        if r.status_code == 200 and r.json().get('success'):
            return r.json()['content'].get('orders', [])
        logger.error(f'Помилка отримання замовлень: {r.text[:200]}')
        return []
    except Exception as e:
        logger.error(f'get_new_orders: {e}')
        return []


def get_order_details(order_id: int) -> dict:
    """Отримати повні деталі замовлення."""
    try:
        r = requests.get(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(),
            params={'expand': 'purchases,delivery,status_available'},
            timeout=30
        )
        return r.json().get('content', {}) if r.status_code == 200 else {}
    except Exception as e:
        logger.error(f'get_order_details: {e}')
        return {}


def confirm_order(order_id: int) -> bool:
    """Підтвердити замовлення (status=2)."""
    try:
        r = requests.post(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(),
            json={'status': 2},
            timeout=15
        )
        return r.status_code == 200 and r.json().get('success', False)
    except Exception as e:
        logger.error(f'confirm_order: {e}')
        return False


def cancel_order(order_id: int, comment: str = 'Товар відсутній у постачальника') -> bool:
    """Скасувати замовлення (status=6)."""
    try:
        r = requests.post(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(),
            json={'status': 6, 'comment': comment},
            timeout=15
        )
        return r.status_code == 200 and r.json().get('success', False)
    except Exception as e:
        logger.error(f'cancel_order: {e}')
        return False


def is_already_processed(order_id: int) -> bool:
    """Перевірити чи замовлення вже оброблялось."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS rozetka_processed_orders (
                order_id    BIGINT PRIMARY KEY,
                status      VARCHAR(50),
                total_price NUMERIC(12,2),
                processed_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        conn.commit()
        cur.execute('SELECT 1 FROM rozetka_processed_orders WHERE order_id = %s', (order_id,))
        exists = cur.fetchone() is not None
        cur.close(); conn.close()
        return exists
    except:
        return False


def save_to_db(order: dict, status: str):
    """Зберегти замовлення в БД."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        total = float(order.get('amount_with_discount') or order.get('amount') or 0)
        cur.execute('''
            INSERT INTO rozetka_processed_orders (order_id, status, total_price)
            VALUES (%s, %s, %s)
            ON CONFLICT (order_id) DO UPDATE
            SET status=EXCLUDED.status, processed_at=NOW()
        ''', (order['id'], status, total))
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        logger.error(f'save_to_db: {e}')


# === EXCEL БЛАНК ===

def create_order_excel(order: dict, items_info: list) -> str:
    """Формат бланку для постачальника Carvol."""
    order_id = order.get('id', 'unknown')
    filename = f'/tmp/rozetka_order_{order_id}_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'

    wb = xlsxwriter.Workbook(filename)
    ws = wb.add_worksheet('Замовлення')

    bold       = wb.add_format({'bold': True, 'font_size': 11})
    header_fmt = wb.add_format({'bold': True, 'bg_color': '#1F4E79',
                                'font_color': 'white', 'border': 1, 'align': 'center'})
    cell_fmt   = wb.add_format({'border': 1})
    sku_fmt    = wb.add_format({'border': 1, 'bold': True})
    red_bold   = wb.add_format({'bold': True, 'font_color': 'red'})
    wrap_fmt   = wb.add_format({'text_wrap': True})

    ws.set_column('A:A', 5)
    ws.set_column('B:B', 22)
    ws.set_column('C:C', 55)
    ws.set_column('D:D', 14)

    # Дані доставки
    delivery   = order.get('delivery') or {}
    recipient  = delivery.get('recipient_title') or order.get('recipient_title') or {}
    customer   = recipient.get('full_name', '') or f"{recipient.get('first_name','')} {recipient.get('last_name','')}".strip()
    phone      = delivery.get('recipient_phone') or order.get('recipient_phone') or order.get('user_phone', '')
    city_name  = (delivery.get('city') or {}).get('name', '')
    warehouse  = delivery.get('warehouse_description', '') or delivery.get('place_name', '')
    delivery_str = f'{city_name} {warehouse}'.strip() or 'Нова Пошта'

    total = float(order.get('amount_with_discount') or order.get('amount') or 0)

    # Шапка
    ws.write('A1', 'Перевозчик', bold)
    ws.write('C1', 'Нова Пошта')
    ws.write('A2', 'Оплата', bold)
    ws.write('C2', f'Накладений платіж {total:.0f} грн')
    ws.write('A3', 'Коментар', bold)
    ws.write('C3', f'{customer}  {phone}\n{delivery_str}', wrap_fmt)
    ws.set_row(2, 35)
    ws.write('A4', f'Замовлення {MARKETPLACE} #{order_id}')
    ws.write('C4', f'Дата: {datetime.now().strftime("%d.%m.%Y %H:%M")}')
    if SUPPLIER_CODE:
        ws.write('A5', f'Код клієнта: {SUPPLIER_CODE}', red_bold)

    # Заголовки
    row = 6
    for col, h in enumerate(['№', 'Артикул', 'Найменування', 'Кількість']):
        ws.write(row, col, h, header_fmt)
    row += 1

    for idx, item in enumerate(items_info, 1):
        ws.write(row, 0, idx, cell_fmt)
        ws.write(row, 1, item.get('sku', ''), sku_fmt)
        ws.write(row, 2, item.get('name', '')[:80], cell_fmt)
        ws.write(row, 3, item.get('quantity', 1), cell_fmt)
        row += 1

    wb.close()
    return filename


def send_to_supplier(order: dict, excel_path: str, items_info: list):
    """Відправити бланк на email постачальника Carvol."""
    order_id   = order['id']
    delivery   = order.get('delivery') or {}
    recipient  = delivery.get('recipient_title') or order.get('recipient_title') or {}
    customer   = recipient.get('full_name', '') or f"{recipient.get('first_name','')} {recipient.get('last_name','')}".strip()
    phone      = delivery.get('recipient_phone') or order.get('user_phone', '')
    city_name  = (delivery.get('city') or {}).get('name', '')
    warehouse  = delivery.get('warehouse_description', '') or ''
    delivery_str = f'{city_name} {warehouse}'.strip() or 'Нова Пошта'
    total      = float(order.get('amount_with_discount') or order.get('amount') or 0)

    items_text = '\n'.join(
        f"{i}. {item.get('sku','')} | {item.get('name','')[:50]} | {item.get('quantity',1)} шт."
        for i, item in enumerate(items_info, 1)
    )

    body = f"""Доброго дня!

Замовлення #{order_id} від {datetime.now().strftime('%d.%m.%Y')}
{f'Код клієнта: {SUPPLIER_CODE}' if SUPPLIER_CODE else ''}

Товари:
{items_text}

Отримувач: {customer}
Телефон: {phone}
Доставка: {delivery_str}
Оплата: Накладений платіж {total:.0f} грн

Деталі в додатку (Excel).

З повагою,
klatch1.shop ({MARKETPLACE})
"""
    msg = MIMEMultipart()
    msg['From']    = SMTP_USER
    msg['To']      = CARVOL_EMAIL
    msg['Subject'] = f'Замовлення #{order_id} від {datetime.now().strftime("%d.%m.%Y")} ({MARKETPLACE})'
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    with open(excel_path, 'rb') as f:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition',
                        f'attachment; filename="{os.path.basename(excel_path)}"')
        msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.success(f'Email відправлено для замовлення {order_id}')
        return True
    except Exception as e:
        logger.error(f'Email помилка: {e}')
        return False


# === ОБРОБКА ЗАМОВЛЕННЯ ===

def process_order(order: dict, feed: dict):
    """Обробити одне замовлення."""
    order_id = order.get('id')
    if not order_id or is_already_processed(order_id):
        return

    logger.info(f'Обробляємо {MARKETPLACE} замовлення #{order_id}')

    # Деталі замовлення
    details = get_order_details(order_id)
    if not details:
        details = order  # fallback до даних зі списку

    purchases = details.get('purchases') or order.get('purchases') or []
    if not purchases:
        logger.warning(f'Замовлення #{order_id} — немає товарів')
        return

    # Перевіряємо наявність кожного товару у фіді Carvol
    items_info    = []
    all_available = True

    for purchase in purchases:
        offer_id = purchase.get('offer_id') or purchase.get('article', '')
        sku      = str(offer_id).strip()
        feed_item = feed.get(sku, {})
        available = feed_item.get('available', False)
        qty       = feed_item.get('qty', 0)

        if not available:
            all_available = False
            logger.warning(f'  {sku} — відсутній або qty=0 у Carvol')

        items_info.append({
            'sku':       sku,
            'name':      purchase.get('name', ''),
            'quantity':  purchase.get('quantity', 1),
            'price':     purchase.get('price', 0),
            'available': available,
            'feed_qty':  qty,
        })

    delivery   = details.get('delivery') or {}
    recipient  = delivery.get('recipient_title') or details.get('recipient_title') or {}
    customer   = recipient.get('full_name', '') or f"{recipient.get('first_name','')} {recipient.get('last_name','')}".strip()
    phone      = delivery.get('recipient_phone') or details.get('user_phone', '')
    total      = float(details.get('amount_with_discount') or details.get('amount') or 0)

    if not all_available:
        unavailable = [i['sku'] for i in items_info if not i['available']]
        cancel_order(order_id, 'Товар відсутній у постачальника')
        save_to_db(details, 'cancelled_no_stock')
        tg(f"""❌ <b>{MARKETPLACE} #{order_id} — товар відсутній!</b>
Клієнт: {customer} {phone}
Відсутні SKU: {', '.join(unavailable)}
Замовлення скасовано.""")
        return

    # Підтверджуємо
    if confirm_order(order_id):
        logger.success(f'Замовлення #{order_id} підтверджено')
    else:
        logger.error(f'Не вдалось підтвердити #{order_id}')
        return

    # Excel + email
    excel      = create_order_excel(details, items_info)
    email_sent = send_to_supplier(details, excel, items_info)
    save_to_db(details, 'accepted')

    tg(f"""📧 <b>{MARKETPLACE} #{order_id} відправлено постачальнику</b>
Клієнт: {customer} {phone}
Товарів: {len(items_info)}
💰 Сума: {total:.0f} грн
📧 Email: {'✅' if email_sent else '❌'}""")


# === ГОЛОВНИЙ ЦИКЛ ===

def main():
    logger.add('/tmp/rozetka_order_agent.log', rotation='10 MB', level='INFO')
    logger.info(f'{MARKETPLACE} Order Agent запущено')

    if not ROZETKA_API_TOKEN:
        logger.error('ROZETKA_API_TOKEN не задано в .env!')
        tg(f'❌ {MARKETPLACE} Order Agent: не задано API токен у .env')
        return

    tg(f'🚀 <b>{MARKETPLACE} Order Agent запущено</b>')

    while True:
        try:
            feed   = get_carvol_feed()
            orders = get_new_orders()

            if orders:
                logger.info(f'Знайдено {len(orders)} замовлень')
                for order in orders:
                    if order.get('status') == 1:  # тільки нові
                        process_order(order, feed)
            else:
                logger.debug('Нових замовлень немає')

        except Exception as e:
            logger.error(f'Помилка циклу: {e}')
            tg(f'⚠️ <b>{MARKETPLACE} Order Agent помилка:</b> {e}')

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
