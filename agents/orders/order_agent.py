"""
Агент обробки замовлень — дропшипінг TOPTUL
============================================
Цикл:
1. Отримати нові замовлення з Prom API
2. Перевірити наявність у фіді TOPTUL (реальний час)
3. Підтвердити замовлення на Prom
4. Сформувати Excel бланк → відправити на opt@grandinstrument.ua
ТТН — постачальник сам надсилає, вручну вносимо в систему
"""
import os, sys, json, time, requests, smtplib
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
PROM_TOKEN = os.getenv('PROM_API_TOKEN')
PROM_HEADERS = {'Authorization': f'Bearer {PROM_TOKEN}'}
PROM_BASE = 'https://my.prom.ua/api/v1'

TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)

SUPPLIER_EMAIL = 'opt@grandinstrument.ua'
SUPPLIER_CODE = '000160594'

SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASS = os.getenv('SMTP_PASS')
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))

# === КЕШ ФІДУ ===
_feed_cache = {'data': {}, 'updated': 0}

# =============================================
# 1. ЗАВАНТАЖЕННЯ ФІДУ TOPTUL
# =============================================
def load_feed():
    """Завантажує фід TOPTUL і кешує на 1 годину"""
    if time.time() - _feed_cache['updated'] < 3600 and _feed_cache['data']:
        return _feed_cache['data']
    
    logger.info('Завантажуємо фід TOPTUL...')
    try:
        resp = requests.get(TOPTUL_FEED, timeout=120)
        root = ET.fromstring(resp.content)
        offers = root.find('shop').find('offers').findall('offer')
        
        cache = {}
        for offer in offers:
            # Шукаємо артикул
            sku = ''
            for p in offer.findall('param'):
                pname = (p.get('name') or '').lower()
                if 'артикул' in pname or 'article' in pname:
                    sku = (p.text or '').strip().upper()
                    break
            if not sku:
                sku = (offer.get('id') or '').upper()
            
            available = offer.get('available', 'true') == 'true'
            stock = getattr(offer.find('stock_quantity'), 'text', '*')
            price_el = offer.find('price')
            price = float(price_el.text) if price_el is not None else 0
            name_el = offer.find('name')
            name = name_el.text if name_el is not None else ''
            
            cache[sku] = {
                'available': available,
                'stock': stock,       # *, **, ***, ****
                'price': price,       # ціна фіду
                'zakupka': round(price * 0.88, 2),  # наша закупочна
                'name': name,
            }
        
        _feed_cache['data'] = cache
        _feed_cache['updated'] = time.time()
        logger.success(f'Фід завантажено: {len(cache)} товарів')
        return cache
    except Exception as e:
        logger.error(f'Помилка фіду: {e}')
        return {}

def check_availability(sku: str) -> dict | None:
    """Перевіряємо наявність конкретного SKU"""
    feed = load_feed()
    return feed.get(sku.upper())

# =============================================
# 2. PROM API — ЗАМОВЛЕННЯ
# =============================================
def get_new_orders() -> list:
    """Отримуємо нові замовлення зі статусом pending"""
    try:
        resp = requests.get(
            f'{PROM_BASE}/orders/list',
            headers=PROM_HEADERS,
            params={'status': 'pending', 'limit': 50},
            timeout=30
        )
        orders = resp.json().get('orders', [])
        logger.info(f'Нових замовлень з Prom: {len(orders)}')
        return orders
    except Exception as e:
        logger.error(f'Prom API помилка: {e}')
        return []

def confirm_order(order_id: int) -> bool:
    """Підтверджуємо замовлення на Prom"""
    try:
        resp = requests.post(
            f'{PROM_BASE}/orders/{order_id}/set_status',
            headers=PROM_HEADERS,
            json={'status': 'accepted'},
            timeout=30
        )
        ok = resp.status_code == 200
        if ok:
            logger.success(f'Замовлення #{order_id} підтверджено на Prom')
        else:
            logger.error(f'Помилка підтвердження #{order_id}: {resp.text}')
        return ok
    except Exception as e:
        logger.error(f'Помилка: {e}')
        return False

# =============================================
# 3. БАЗА ДАНИХ — ЗБЕРІГАЄМО ЗАМОВЛЕННЯ
# =============================================
def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        prom_order_id BIGINT UNIQUE NOT NULL,
        status VARCHAR(50) DEFAULT 'new',
        customer_name VARCHAR(200),
        customer_phone VARCHAR(50),
        delivery_city VARCHAR(100),
        delivery_warehouse TEXT,
        delivery_type VARCHAR(100),
        total_price NUMERIC(12,2),
        items JSONB,
        all_available BOOLEAN DEFAULT FALSE,
        supplier_email_sent BOOLEAN DEFAULT FALSE,
        ttn VARCHAR(50),
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )''')
    conn.commit()
    cur.close(); conn.close()

def save_order(order: dict, items_info: list, all_available: bool):
    conn = get_connection()
    cur = conn.cursor()
    
    # Delivery може бути рядком або словником
    delivery_raw = order.get('delivery_address', '') or ''
    if isinstance(delivery_raw, str):
        delivery_str = delivery_raw
    else:
        city_d = (delivery_raw.get('city') or {}).get('name', '')
        wh_d = (delivery_raw.get('warehouse') or {}).get('description', '')
        delivery_str = f'{city_d} {wh_d}'.strip()
    
    cur.execute('''
        INSERT INTO orders 
        (prom_order_id, status, customer_name, customer_phone,
         delivery_city, delivery_warehouse, delivery_type,
         total_price, items, all_available)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (prom_order_id) DO UPDATE SET
            status=EXCLUDED.status, updated_at=NOW()
        RETURNING id
    ''', (
        order['id'],
        'confirmed' if all_available else 'check_needed',
        f"{order.get('client_last_name','')} {order.get('client_first_name','')}".strip(),
        order.get('client_phone', ''),
        delivery_str,
        '',
        'Нова Пошта',
        float(order.get('price', 0)),
        json.dumps(items_info, ensure_ascii=False),
        all_available
    ))
    conn.commit()
    cur.close(); conn.close()

# =============================================
# 4. EXCEL БЛАНК ЗАМОВЛЕННЯ
# =============================================
def create_order_excel(order: dict, items_info: list) -> str:
    """Формат бланку Гранд Інструмент"""
    filename = f'/tmp/order_{order["id"]}_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    
    wb = xlsxwriter.Workbook(filename)
    ws = wb.add_worksheet('Замовлення')
    
    # Формати
    bold = wb.add_format({'bold': True, 'font_size': 11})
    header_fmt = wb.add_format({'bold': True, 'bg_color': '#1F4E79', 'font_color': 'white', 
                                 'border': 1, 'align': 'center'})
    cell_fmt = wb.add_format({'border': 1})
    sku_fmt = wb.add_format({'border': 1, 'bold': True})
    red_bold = wb.add_format({'bold': True, 'font_color': 'red'})
    wrap_fmt = wb.add_format({'text_wrap': True})
    
    # Ширина стовпців
    ws.set_column('A:A', 5)
    ws.set_column('B:B', 22)
    ws.set_column('C:C', 55)
    ws.set_column('D:D', 14)
    
    # Дані замовлення
    delivery_raw = order.get('delivery_address', '') or ''
    if isinstance(delivery_raw, str):
        delivery_str = delivery_raw
    else:
        city_d = (delivery_raw.get('city') or {}).get('name', '')
        wh_d = (delivery_raw.get('warehouse') or {}).get('description', '')
        delivery_str = f'{city_d} {wh_d}'.strip()
    customer = f"{order.get('client_last_name','')} {order.get('client_first_name','')}".strip()
    phone = order.get('client_phone', '')
    total = float(str(order.get('price', 0)).replace(' грн','').replace(',','.').split()[0])
    
    # Шапка
    ws.write('A1', 'Перевозчик', bold)
    ws.write('C1', 'Новая Почта')
    ws.write('A2', 'Оплата', bold)
    ws.write('C2', f'Наложенным платежом {total:.0f} грн')
    ws.write('A3', 'Коментарий', bold)
    ws.write('C3', f'{customer}  {phone}\n{delivery_str}', wrap_fmt)
    ws.set_row(2, 35)
    ws.write('A4', f'Замовлення Prom #{order["id"]}')
    ws.write('C4', f'Дата: {datetime.now().strftime("%d.%m.%Y %H:%M")}')
    ws.write('A5', f'Код клієнта: {SUPPLIER_CODE}', red_bold)
    
    # Заголовки таблиці
    row = 6
    for col, h in enumerate(['№', 'Артикул', 'Наименование', 'Количество']):
        ws.write(row, col, h, header_fmt)
    
    # Товари
    for i, item in enumerate(items_info):
        row += 1
        ws.write(row, 0, i+1, cell_fmt)
        ws.write(row, 1, item['sku'], sku_fmt)
        ws.write(row, 2, item['name'][:80], cell_fmt)
        ws.write(row, 3, item['quantity'], cell_fmt)
    
    wb.close()
    logger.success(f'Excel бланк: {filename}')
    return filename

# =============================================
# 5. ВІДПРАВКА EMAIL ПОСТАЧАЛЬНИКУ
# =============================================
def send_to_supplier(order: dict, excel_path: str, items_info: list):
    """Відправляємо замовлення на opt@grandinstrument.ua"""
    delivery_raw = order.get('delivery_address', '') or ''
    if isinstance(delivery_raw, str):
        delivery_str = delivery_raw
    else:
        city_d = (delivery_raw.get('city') or {}).get('name', '')
        wh_d = (delivery_raw.get('warehouse') or {}).get('description', '')
        delivery_str = f'{city_d} {wh_d}'.strip()
    customer = f"{order.get('client_last_name','')} {order.get('client_first_name','')}".strip()
    phone = order.get('client_phone', '')
    total = float(str(order.get('price', 0)).replace(' грн','').replace(',','.').split()[0])
    
    items_text = '\n'.join([
        f"{i+1}. {it['sku']} | {it['name'][:50]} | {it['quantity']} шт."
        for i, it in enumerate(items_info)
    ])
    
    body = f"""Добрый день!

Заказ #{order['id']}
Код клиента: {SUPPLIER_CODE}

Товары:
{items_text}

Получатель: {customer}
Телефон: {phone}
Город: {city}
Отделение НП: {warehouse}
Оплата: Наложенным платежом {total:.0f} грн

Детали в приложении (Excel).

С уважением,
klatch1.shop"""
    
    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = SUPPLIER_EMAIL
    msg['Subject'] = f'Заказ #{order["id"]} от {datetime.now().strftime("%d.%m.%Y")}'
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    
    with open(excel_path, 'rb') as f:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition',
            f'attachment; filename="{os.path.basename(excel_path)}"')
        msg.attach(part)
    
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    
    # Оновлюємо БД
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        'UPDATE orders SET supplier_email_sent=TRUE, updated_at=NOW() WHERE prom_order_id=%s',
        (order['id'],)
    )
    conn.commit()
    cur.close(); conn.close()
    logger.success(f'Email відправлено на {SUPPLIER_EMAIL}')

# =============================================
# 6. ГОЛОВНИЙ ЦИКЛ
# =============================================
def process_orders():
    init_db()
    logger.info('=== Обробка замовлень Prom ===')
    
    orders = get_new_orders()
    if not orders:
        logger.info('Нових замовлень немає')
        return
    
    for order in orders:
        oid = order['id']
        logger.info(f'--- Замовлення #{oid} ---')
        
        products = order.get('products', [])
        items_info = []
        all_available = True
        
        for product in products:
            sku = (product.get('sku') or '').strip()
            qty = product.get('quantity', 1)
            avail = check_availability(sku)
            
            info = {
                'sku': sku,
                'name': product.get('name', ''),
                'quantity': qty,
                'prom_price': float(product.get('price', 0)),
                'feed_available': avail['available'] if avail else False,
                'feed_stock': avail['stock'] if avail else '—',
                'zakupka': avail['zakupka'] if avail else 0,
            }
            items_info.append(info)
            
            if not avail or not avail['available']:
                all_available = False
                logger.warning(f'  ❌ {sku} — немає в наявності!')
            else:
                logger.info(f'  ✅ {sku} — є ({avail["stock"]})')
        
        # Тип оплати
        payment = order.get('payment_option') or {}
        payment_type = payment.get('name', 'Накладений платіж') if isinstance(payment, dict) else str(payment)
        
        # Зберігаємо в БД
        save_order(order, items_info, all_available)
        
        # Telegram сповіщення
        notify_new_order(order, items_info, payment_type)
        
        if all_available:
            # Підтверджуємо на Prom
            if confirm_order(oid):
                try:
                    excel = create_order_excel(order, items_info)
                    send_to_supplier(order, excel, items_info)
                    notify_order_sent(oid, excel)
                    logger.success(f'✅ Замовлення #{oid} — оброблено повністю')
                except Exception as e:
                    logger.error(f'Помилка відправки: {e}')
        else:
            missing = [i['sku'] for i in items_info if not i['feed_available']]
            notify_stock_problem(oid, missing)
            logger.warning(f'⚠️ Замовлення #{oid} — відсутні: {missing}')

if __name__ == '__main__':
    process_orders()

# =============================================
# TELEGRAM СПОВІЩЕННЯ
# =============================================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')

def tg(text: str, emoji: str = ''):
    """Відправляємо повідомлення в Telegram"""
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_ADMIN, 'text': f'{emoji} {text}'.strip(), 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.error(f'Telegram помилка: {e}')

def notify_new_order(order: dict, items_info: list, payment_type: str):
    """Сповіщення про нове замовлення"""
    items_text = '\n'.join([
        f"  • {i['sku']} x{i['quantity']} — {'✅ є' if i['feed_available'] else '❌ немає'}"
        for i in items_info
    ])
    
    is_prepaid = any(w in payment_type.lower() for w in ['пром-оплата', 'онлайн', 'картк', 'liqpay'])
    
    if is_prepaid:
        tg(f"""⚠️ <b>ПРОМ-ОПЛАТА!</b> Замовлення #{order['id']}
Покупець вже заплатив — потрібна передплата постачальнику!

👤 {order.get('client_last_name','')} {order.get('client_first_name','')}
💰 Сума: {order.get('price','')} грн
💳 Оплата: {payment_type}
📦 Товари:
{items_text}

🏦 Перекажи постачальнику перед відправкою!""")
    else:
        all_ok = all(i['feed_available'] for i in items_info)
        status = '✅ Всі в наявності' if all_ok else '⚠️ Є проблеми з наявністю'
        tg(f"""🛒 <b>Нове замовлення #{order['id']}</b>
👤 {order.get('client_last_name','')} {order.get('client_first_name','')}
💰 {order.get('price','')} грн | {payment_type}
📦 Товари:
{items_text}
{status}""")

def notify_stock_problem(order_id: int, missing_skus: list):
    """Сповіщення коли товар відсутній"""
    tg(f"""❌ <b>Замовлення #{order_id} — товар відсутній!</b>
Відсутні артикули:
{chr(10).join(f'  • {s}' for s in missing_skus)}

Перевір наявність вручну і прийми рішення.""")

def notify_order_sent(order_id: int, excel_file: str):
    """Сповіщення що замовлення відправлено постачальнику"""
    tg(f"""📧 <b>Замовлення #{order_id} відправлено постачальнику</b>
Email: {SUPPLIER_EMAIL}
Excel: {os.path.basename(excel_file)}
✅ Чекай підтвердження від Русанова""")
