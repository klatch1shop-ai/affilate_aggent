"""
rozetka_order_agent.py v4
=========================
v4:
- set_ttn: POST /orders/add-ttn (primary) з fallback на PATCH /orders/{id}
- process_order: confirm(2) → Excel Carvol → save 'accepted'; TTN окремо через бот
- save_to_db: зберігає phone/recipient/city для match_order_by_ttn_data
- get_orders_by_status: новий хелпер для пошуку за статусом
- set_ttn_and_ship: видалено; set_ttn тепер standalone (тільки TTN, без status)

Послідовність статусів:
  new (4) → підтверджено (2) → TTN додано (61) → передано в доставку (3)
"""
import os, sys, json, time, requests, smtplib, shutil
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
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
CARVOL_EMAIL      = os.getenv('CARVOL_SUPPLIER_EMAIL', 'carvolua@gmail.com')
CARVOL_TG_CHAT_ID = os.getenv('CARVOL_TG_CHAT_ID', '')
SUPPLIER_CODE     = os.getenv('CARVOL_SUPPLIER_CODE', '')
SMTP_USER         = os.getenv('SMTP_USER')
SMTP_PASS         = os.getenv('SMTP_PASS')
SMTP_HOST         = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT         = int(os.getenv('SMTP_PORT', '587'))
TG_BOT_TOKEN      = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID        = os.getenv('TG_CHAT_ID')
CABINET_BASE    = 'https://cabinet-seller.rozetka.com.ua'
POLL_INTERVAL     = 300
MARKETPLACE       = 'Розетка'
FORBIDDEN_STATUSES = {40, 49, 6}  # 40=клієнт передумав, 49=небезпечний, 6=скасування

ORDERS_DIR = '/home/tek/agent-system/shared/feeds/orders'


# === TELEGRAM (адмін) ===
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


# === ТОКЕН ===
def get_token() -> str:
    if not ROZETKA_API_TOKEN:
        raise Exception('ROZETKA_API_TOKEN не задано в .env!')
    return ROZETKA_API_TOKEN


def rz_headers() -> dict:
    return {
        'Authorization':    f'Bearer {get_token()}',
        'Content-Type':     'application/json',
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
    try:
        r = requests.get(CARVOL_FEED, timeout=120)
        root = ET.fromstring(r.content)
        offers = root.find('shop').find('offers').findall('offer')

        data = {}
        for offer in offers:
            article_el = offer.find('article')
            if article_el is None:
                continue
            article  = (article_el.text or '').strip()
            price_el = offer.find('price')
            qty_el   = offer.find('stock_quantity')
            qty      = int(qty_el.text or 0) if qty_el is not None else 0
            data[article] = {
                'available': offer.get('available', 'false').lower() == 'true' and qty > 0,
                'price':     float(price_el.text or 0) if price_el is not None else 0,
                'qty':       qty,
            }

        _carvol_cache['data']    = data
        _carvol_cache['updated'] = now
        logger.info(f'Carvol фід: {len(data)} SKU')
        return data
    except Exception as e:
        logger.error(f'Carvol фід недоступний: {e}')
        if _carvol_cache['data']:
            logger.warning(f'Використовую кеш ({len(_carvol_cache["data"])} SKU)')
            return _carvol_cache['data']
        logger.warning('Кеш порожній — продовжуємо без фіду')
        return {}


# === РОЗЕТКА API ===

def get_new_orders() -> list:
    """Отримати нові замовлення: types=4 + status=1 + status=26 + status=55 + status=61, без дублів."""
    params_base = {
        'expand': 'purchases,delivery,status_available,payment_type',
        'sort':   '-id',
        'page':   1,
    }
    results = {}

    for extra_key, extra_val in [('types', 4), ('status', 1), ('status', 2), ('status', 26), ('status', 55), ('status', 61)]:
        try:
            r = requests.get(
                f'{ROZETKA_BASE}/orders/search',
                headers=rz_headers(),
                verify=False,
                params={**params_base, extra_key: extra_val},
                timeout=30
            )
            if r.status_code == 200 and r.json().get('success'):
                for o in r.json()['content'].get('orders', []):
                    results[o['id']] = o
            else:
                logger.error(f'get_new_orders {extra_key}={extra_val}: {r.text[:200]}')
        except Exception as e:
            logger.error(f'get_new_orders {extra_key}={extra_val}: {e}')

    return list(results.values())


def get_orders_by_status(status: int) -> list:
    """Пошук замовлень за статусом через GET /orders/search?status={status}."""
    try:
        r = requests.get(
            f'{ROZETKA_BASE}/orders/search',
            headers=rz_headers(),
            verify=False,
            params={
                'status': status,
                'expand': 'purchases,delivery,payment_type',
                'sort':   '-id',
                'page':   1,
            },
            timeout=30
        )
        if r.status_code == 200 and r.json().get('success'):
            return r.json()['content'].get('orders', [])
        logger.error(f'get_orders_by_status({status}): {r.text[:200]}')
        return []
    except Exception as e:
        logger.error(f'get_orders_by_status: {e}')
        return []


def get_order_details(order_id: int) -> dict:
    """Отримати повні деталі замовлення."""
    try:
        r = requests.get(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(),
            verify=False,
            params={'expand': 'purchases,delivery,status_available,payment_type'},
            timeout=30
        )
        return r.json().get('content', {}) if r.status_code == 200 else {}
    except Exception as e:
        logger.error(f'get_order_details: {e}')
        return {}


def change_status(order_id: int, status: int) -> bool:
    """Змінити статус замовлення через PATCH /orders/{id}."""
    try:
        r = requests.patch(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(),
            verify=False,
            json={'status': status},
            timeout=15
        )
        data = r.json()
        if data.get('success'):
            logger.success(f'Статус #{order_id} → {status}')
            return True
        logger.warning(f'change_status failed: {data}')
        return False
    except Exception as e:
        logger.error(f'change_status: {e}')
        return False


def set_ttn(order_id: int, ttn: str) -> bool:
    """
    Встановити ТТН для замовлення.
    Після успіху статус автоматично стає 61 (TTN додано).
    Потім викликати change_status(3) для передачі в доставку.

    Пробує:
      1. POST /orders/add-ttn  {"order_id", "ttn", "delivery_service_id": 1}
      2. Fallback: PATCH /orders/{id} {"ttn": ttn}
    """
    # Спроба 1: POST /orders/add-ttn
    try:
        r = requests.post(
            f'{ROZETKA_BASE}/orders/add-ttn',
            headers=rz_headers(),
            verify=False,
            json={'order_id': order_id, 'ttn': ttn, 'delivery_service_id': 1},
            timeout=15
        )
        data = r.json()
        if data.get('success'):
            logger.success(f'ТТН {ttn} додано до #{order_id} (POST add-ttn → статус 61)')
            return True
        logger.warning(f'set_ttn POST add-ttn failed ({data}), trying PATCH fallback...')
    except Exception as e:
        logger.warning(f'set_ttn POST add-ttn exception ({e}), trying PATCH fallback...')

    # Fallback: PATCH /orders/{id}
    try:
        r = requests.patch(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(),
            verify=False,
            json={'ttn': ttn},
            timeout=15
        )
        data = r.json()
        if data.get('success'):
            logger.success(f'ТТН {ttn} додано до #{order_id} (PATCH fallback)')
            return True
        logger.warning(f'set_ttn PATCH fallback failed: {data}')
        return False
    except Exception as e:
        logger.error(f'set_ttn PATCH fallback: {e}')
        return False


def confirm_order(order_id: int) -> bool:
    """Підтвердити замовлення (status=2) — перевіряє доступні переходи."""
    def _safe_patch(target_status: int, label: str) -> bool:
        if target_status in FORBIDDEN_STATUSES:
            logger.error(
                f'confirm_order #{order_id}: відхилено PATCH на {target_status} '
                f'— статус у FORBIDDEN_STATUSES {FORBIDDEN_STATUSES}'
            )
            return False
        rp   = requests.patch(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(), verify=False,
            json={'status': target_status, 'comment': 'Підтверджено'}, timeout=15
        )
        data = rp.json()
        if data.get('success'):
            logger.success(f'Статус #{order_id} → {target_status} ({label})')
            return True
        logger.warning(f'confirm_order PATCH {target_status} failed: {data}')
        return False

    try:
        r = requests.get(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(),
            verify=False,
            params={'expand': 'status_available'},
            timeout=30
        )
        if r.status_code != 200 or not r.json().get('success'):
            logger.error(f'confirm_order GET #{order_id}: {r.text[:200]}')
            return False
        order_data     = r.json().get('content', {})
        current_status = order_data.get('status')
        available_raw  = [s.get('child_id') for s in (order_data.get('status_available') or []) if s.get('child_id')]
        # Ніколи не використовувати заборонені статуси
        available      = [s for s in available_raw if s not in FORBIDDEN_STATUSES]
        if available_raw != available:
            blocked = [s for s in available_raw if s in FORBIDDEN_STATUSES]
            logger.warning(f'confirm_order #{order_id}: заблоковано небезпечні статуси {blocked}')
        logger.info(f'confirm_order #{order_id}: current={current_status}, available={available}')

        if current_status in (2, 55, 61):
            logger.info(f'#{order_id} вже підтверджено (status={current_status})')
            return True

        # Зі статусу 1 дозволено лише переходи на 2 або 55
        allowed_targets = {2, 55} - FORBIDDEN_STATUSES

        if 2 in available and 2 in allowed_targets:
            return _safe_patch(2, 'підтверджено')

        if 55 in available and 55 in allowed_targets:
            if not _safe_patch(55, 'проміжний 55'):
                return False
            logger.info(f'Статус #{order_id} → 55, тепер → 2')
            return _safe_patch(2, 'підтверджено після 55')

        logger.warning(
            f'confirm_order #{order_id}: перехід на 2 недоступний. '
            f'current={current_status}, available={available}'
        )
        if current_status == 1:
            # Спробуємо cabinet-seller PUT як fallback для статусу 1
            logger.info(f'confirm_order #{order_id}: пробуємо cabinet-seller PUT...')
            try:
                rc = requests.put(
                    f"{CABINET_BASE}/orders/{order_id}",
                    headers=rz_headers(),
                    verify=False,
                    json={"status": 55, "ttn": "", "id": order_id},
                    timeout=15
                )
                if rc.json().get("success"):
                    logger.success(f'confirm_order #{order_id}: cabinet-seller 55 OK')
                    return True
            except Exception as ce:
                logger.warning(f'confirm_order cabinet fallback: {ce}')
            return None  # sentinel: потрібне ручне підтвердження
        return False
    except Exception as e:
        logger.error(f'confirm_order: {e}')
        return False


def cancel_order(order_id: int, comment: str = 'Товар відсутній у постачальника') -> bool:
    """Скасувати замовлення (status=6)."""
    try:
        r = requests.patch(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(),
            verify=False,
            json={'status': 6, 'comment': comment},
            timeout=15
        )
        data = r.json()
        if data.get('success'):
            logger.success(f'Замовлення #{order_id} скасовано')
            return True
        logger.warning(f'cancel_order failed: {data}')
        return False
    except Exception as e:
        logger.error(f'cancel_order: {e}')
        return False


# === БД ===

def is_already_processed(order_id: int) -> bool:
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS rozetka_processed_orders (
                order_id     BIGINT PRIMARY KEY,
                status       VARCHAR(50),
                total_price  NUMERIC(12,2),
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


def get_db_status(order_id: int):
    """Повертає статус замовлення з БД або None якщо не знайдено."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute(
            'CREATE TABLE IF NOT EXISTS rozetka_processed_orders '
            '(order_id BIGINT PRIMARY KEY, status VARCHAR(50), '
            'total_price NUMERIC(12,2), processed_at TIMESTAMP DEFAULT NOW())'
        )
        cur.execute('SELECT status FROM rozetka_processed_orders WHERE order_id = %s', (order_id,))
        row = cur.fetchone()
        cur.close(); conn.close()
        return row["status"] if row else None
    except:
        return None


def delete_from_db(order_id: int):
    """Видаляє замовлення з БД для повторної обробки."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('DELETE FROM rozetka_processed_orders WHERE order_id = %s', (order_id,))
        conn.commit()
        cur.close(); conn.close()
        logger.info(f'#{order_id} видалено з БД для повторної обробки')
    except Exception as e:
        logger.error(f'delete_from_db: {e}')


def _get_db_processed_at(order_id: int):
    """Повертає processed_at для замовлення або None."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('SELECT processed_at FROM rozetka_processed_orders WHERE order_id = %s', (order_id,))
        row = cur.fetchone()
        cur.close(); conn.close()
        return row['processed_at'] if row else None
    except:
        return None


def _update_db_status(order_id: int, status: str):
    """Оновлює тільки статус в БД без зміни processed_at."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('UPDATE rozetka_processed_orders SET status=%s WHERE order_id=%s', (status, order_id))
        conn.commit()
        cur.close(); conn.close()
        logger.debug(f'#{order_id} статус БД → {status}')
    except Exception as e:
        logger.error(f'_update_db_status: {e}')


def save_to_db(order: dict, status: str):
    """Зберігає замовлення в БД включно з phone/recipient/city для TTN-матчингу."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        total = float(order.get('amount_with_discount') or order.get('amount') or 0)

        ri = _order_recipient_info(order) if order.get('id') else {}
        phone     = ri.get('phone', '') or ''
        recipient = ri.get('customer', '') or ''
        city      = ri.get('city', '') or ''

        cur.execute('''
            INSERT INTO rozetka_processed_orders
                (order_id, status, total_price, phone, recipient, city)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (order_id) DO UPDATE
            SET status=EXCLUDED.status,
                total_price=EXCLUDED.total_price,
                phone=COALESCE(EXCLUDED.phone, rozetka_processed_orders.phone),
                recipient=COALESCE(EXCLUDED.recipient, rozetka_processed_orders.recipient),
                city=COALESCE(EXCLUDED.city, rozetka_processed_orders.city),
                processed_at=NOW()
        ''', (order['id'], status, total, phone or None, recipient or None, city or None))
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        logger.error(f'save_to_db: {e}')


# === HELPЕР: дані отримувача ===

def _order_recipient_info(order: dict) -> dict:
    """Повертає {customer, phone, city, warehouse, total, payment_str}."""
    delivery  = order.get('delivery') or {}
    rec_title = delivery.get('recipient_title') or order.get('recipient_title') or order.get('user_title') or {}
    if isinstance(rec_title, dict):
        customer = (
            rec_title.get('full_name', '')
            or f"{rec_title.get('first_name','')} {rec_title.get('last_name','')}".strip()
        )
    else:
        customer = str(rec_title)
    phone     = delivery.get('recipient_phone') or order.get('recipient_phone') or order.get('user_phone', '')
    city_obj  = delivery.get('city') or {}
    city_name = city_obj.get('name_ua') or city_obj.get('name', '')
    warehouse = (
        delivery.get('warehouse_description', '')
        or delivery.get('place_name', '')
        or (f"{delivery.get('place_street','')} {delivery.get('place_number','')}".strip()
            if delivery.get('place_street') else '')
    )
    total        = float(order.get('amount_with_discount') or order.get('amount') or 0)
    payment_type = order.get('payment_type', 'cash')
    payment_str  = 'Накладений платіж' if payment_type in ('cash', 'cod') else f'Передоплата ({payment_type})'
    return dict(customer=customer, phone=phone, city=city_name,
                warehouse=warehouse, total=total, payment_str=payment_str)


# === EXCEL БЛАНК ===

def create_order_excel(order: dict, items_info: list) -> str:
    order_id = order.get('id', 'unknown')
    os.makedirs(ORDERS_DIR, exist_ok=True)
    filename = f'{ORDERS_DIR}/rozetka_order_{order_id}_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'

    wb         = xlsxwriter.Workbook(filename)
    ws         = wb.add_worksheet('Замовлення')
    bold_fmt   = wb.add_format({'bold': True, 'font_size': 11})
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

    ri = _order_recipient_info(order)

    ws.write('A1', 'Перевозчик', bold_fmt);  ws.write('C1', 'Нова Пошта')
    ws.write('A2', 'Оплата', bold_fmt);      ws.write('C2', f'{ri["payment_str"]} {ri["total"]:.0f} грн')
    ws.write('A3', 'Коментар', bold_fmt)
    ws.write('C3', f'{ri["customer"]}  {ri["phone"]}\n{ri["city"]} {ri["warehouse"]}'.strip(), wrap_fmt)
    ws.set_row(2, 35)
    ws.write('A4', f'Замовлення {MARKETPLACE} #{order_id}')
    ws.write('C4', f'Дата: {datetime.now().strftime("%d.%m.%Y %H:%M")}')
    if SUPPLIER_CODE:
        ws.write('A5', f'Код клієнта: {SUPPLIER_CODE}', red_bold)

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


# === ВІДПРАВКА ПОСТАЧАЛЬНИКУ ===

def send_excel_to_carvol_telegram(excel_path: str, order_id: int,
                                   items_info: list, order: dict) -> bool:
    """Надсилає Excel файл у Telegram чат Carvol."""
    if not CARVOL_TG_CHAT_ID:
        logger.warning('CARVOL_TG_CHAT_ID не задано — Telegram не відправлено')
        return False
    if not TG_BOT_TOKEN:
        logger.warning('TG_BOT_TOKEN не задано — Telegram не відправлено')
        return False

    ri            = _order_recipient_info(order)
    delivery_line = f'{ri["city"]} {ri["warehouse"]}'.strip() or 'Нова Пошта'
    items_text    = '\n'.join(
        f"{i}. {item.get('sku','')} × {item.get('quantity',1)}"
        for i, item in enumerate(items_info, 1)
    )
    caption = (
        f'📦 Замовлення {MARKETPLACE} #{order_id}\n'
        f'👤 {ri["customer"]}  {ri["phone"]}\n'
        f'🏙 {delivery_line}\n'
        f'💳 {ri["payment_str"]}\n'
        f'💰 {ri["total"]:.0f} грн\n'
        f'🔧 {items_text}'
    )

    try:
        with open(excel_path, 'rb') as f:
            r = requests.post(
                f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendDocument',
                data={'chat_id': CARVOL_TG_CHAT_ID, 'caption': caption},
                files={'document': (os.path.basename(excel_path), f,
                                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
                timeout=30,
            )
        resp = r.json()
        if resp.get('ok'):
            logger.success(f'Excel #{order_id} відправлено Carvol (chat {CARVOL_TG_CHAT_ID})')
            return True
        logger.warning(f'Telegram Carvol: {resp}')
        return False
    except Exception as e:
        logger.error(f'send_excel_to_carvol_telegram: {e}')
        return False


def send_to_supplier(order: dict, excel_path: str, items_info: list) -> bool:
    """Fallback: відправка Excel поштою на CARVOL_EMAIL."""
    order_id      = order['id']
    ri            = _order_recipient_info(order)
    delivery_str  = f'{ri["city"]} {ri["warehouse"]}'.strip() or 'Нова Пошта'
    items_text    = '\n'.join(
        f"{i}. {item.get('sku','')} | {item.get('name','')[:50]} | {item.get('quantity',1)} шт."
        for i, item in enumerate(items_info, 1)
    )
    excel_filename = os.path.basename(excel_path)
    excel_url      = f'https://usa1.tail3a617f.ts.net/orders/{excel_filename}'

    body = (
        f"Доброго дня!\n\n"
        f"Замовлення #{order_id} від {datetime.now().strftime('%d.%m.%Y')}\n"
        f"{f'Код клієнта: {SUPPLIER_CODE}' if SUPPLIER_CODE else ''}\n\n"
        f"Товари:\n{items_text}\n\n"
        f"Отримувач: {ri['customer']}\n"
        f"Телефон: {ri['phone']}\n"
        f"Доставка: {delivery_str}\n"
        f"Оплата: {ri['payment_str']} {ri['total']:.0f} грн\n\n"
        f"Excel бланк: {excel_url}\n\n"
        f"З повагою,\nklatch1.shop ({MARKETPLACE})\n"
    )
    if not SMTP_USER or not SMTP_PASS:
        logger.warning('SMTP не налаштовано — email не відправлено')
        return False

    msg = MIMEMultipart()
    msg['From']    = SMTP_USER
    msg['To']      = CARVOL_EMAIL
    msg['Subject'] = f'Замовлення #{order_id} від {datetime.now().strftime("%d.%m.%Y")} ({MARKETPLACE})'
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    with open(excel_path, 'rb') as f:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{excel_filename}"')
        msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.success(f'Email відправлено #{order_id} → {CARVOL_EMAIL}')
        return True
    except Exception as e:
        logger.error(f'Email: {e}')
        return False


# === ОБРОБКА ЗАМОВЛЕННЯ ===

def process_order(order: dict, feed: dict):
    """
    Послідовність:
      new(4) → confirm(2) → Excel до Carvol → save 'accepted'
      TTN приходить окремо через Telegram-бот:
        set_ttn() → статус 61 (автоматично) → change_status(3)
    """
    order_id = order.get('id')
    if not order_id:
        return

    db_status          = get_db_status(order_id)
    skip_payment_check = False   # True коли оплата підтверджена, щоб не повторити waiting_payment
    if db_status == 'pending_manual':
        current = get_order_details(order_id)
        rz_status = current.get('status')
        if rz_status == 1:
            logger.debug(f'#{order_id} pending_manual — статус Розетки ще 1, пропускаємо')
            return
        logger.info(f'#{order_id} pending_manual — статус Розетки змінився на {rz_status}, обробляємо знову')
        delete_from_db(order_id)
    elif db_status in ('waiting_payment', 'waiting_payment_alerted'):
        current = get_order_details(order_id)
        rz_status = current.get('status')
        if rz_status == 26:
            # Замовлення ще не оплачене
            if db_status == 'waiting_payment':
                saved_at = _get_db_processed_at(order_id)
                if saved_at:
                    age_hours = (datetime.now() - saved_at).total_seconds() / 3600
                    if age_hours >= 24:
                        ri = _order_recipient_info(current if current else order)
                        tg(f'⏳⚠️ <b>{MARKETPLACE} #{order_id} — очікує оплату вже {int(age_hours)} год!</b>\n'
                           f'Клієнт: {ri["customer"]} {ri["phone"]}\n'
                           f'💰 {ri["total"]:.0f} грн\nПеревірте статус оплати в кабінеті.')
                        _update_db_status(order_id, 'waiting_payment_alerted')
            logger.debug(f'#{order_id} waiting_payment — статус Розетки ще 26, пропускаємо')
            return
        logger.info(f'#{order_id} waiting_payment — статус змінився на {rz_status}, обробляємо знову')
        delete_from_db(order_id)
        skip_payment_check = True  # payment_type не змінюється, але оплата вже підтверджена статусом
    elif db_status is not None:
        return

    logger.info(f'Обробляємо {MARKETPLACE} #{order_id}')

    details   = get_order_details(order_id) or order
    purchases = details.get('purchases') or order.get('purchases') or []

    if not purchases:
        logger.warning(f'#{order_id} — purchases порожній')
        save_to_db({'id': order_id, 'amount': 0}, 'no_purchases')
        return

    payment_type  = details.get('payment_type', 'cash')
    is_prepaid    = payment_type not in ('cash', 'cod')
    items_info    = []
    all_available = True

    for purchase in purchases:
        offer_id  = (purchase.get('item') or {}).get('article') or purchase.get('article', '')
        sku       = str(offer_id).strip()
        feed_item = feed.get(sku, {})
        available = feed_item.get('available', False)
        qty       = feed_item.get('qty', 0)
        if not available:
            all_available = False
            logger.warning(f'  {sku} — немає в Carvol (qty={qty})')
        items_info.append({
            'sku':       sku,
            'name':      purchase.get('item_name') or purchase.get('name', ''),
            'quantity':  purchase.get('quantity', 1),
            'price':     purchase.get('price', 0),
            'available': available,
            'feed_qty':  qty,
        })

    ri = _order_recipient_info(details)

    # Товар відсутній → скасування
    if not all_available:
        unavailable = [i['sku'] for i in items_info if not i['available']]
        cancel_order(order_id, 'Товар відсутній у постачальника')
        save_to_db(details, 'cancelled_no_stock')
        tg(f'❌ <b>{MARKETPLACE} #{order_id} — товар відсутній!</b>\n'
           f'Клієнт: {ri["customer"]} {ri["phone"]}\n'
           f'Відсутні SKU: {", ".join(unavailable)}\nСкасовано.')
        return

    # Передоплата → чекаємо підтвердження оплати (пропускаємо якщо оплата вже підтверджена)
    if is_prepaid and not skip_payment_check:
        save_to_db(details, 'waiting_payment')
        tg(f'⏳ <b>{MARKETPLACE} #{order_id} — очікує оплату</b>\n'
           f'Клієнт: {ri["customer"]} {ri["phone"]}\n'
           f'Тип: {payment_type} | 💰 {ri["total"]:.0f} грн')
        return

    # Статус 61 — ТТН вже встановлено (раніше оброблено або через бот);
    # якщо є в БД як accepted — пропускаємо; якщо немає — відправляємо Excel і зберігаємо
    if details.get('status') == 61:
        if get_db_status(order_id) == 'accepted':
            logger.debug(f'#{order_id} статус 61, вже в БД як accepted — пропускаємо')
            return
        excel   = create_order_excel(details, items_info)
        tg_sent = send_excel_to_carvol_telegram(excel, order_id, items_info, details)
        save_to_db(details, 'accepted')
        sent_icon = '📲 Telegram' if tg_sent else '❌ не відправлено'
        tg(f'📦 <b>{MARKETPLACE} #{order_id} статус 61 — збережено!</b>\n'
           f'Клієнт: {ri["customer"]}\nТелефон: {ri["phone"]}\n'
           f'💰 {ri["total"]:.0f} грн | Carvol: {sent_icon}')
        logger.info(f'#{order_id} статус 61 — Excel відправлено, збережено як accepted')
        return

    # Підтверджуємо (status=2)
    confirm_result = confirm_order(order_id)
    if confirm_result is None:
        save_to_db(details, 'pending_manual')
        tg(
            f'⚠️ Замовлення <b>#{order_id}</b> потребує ручного підтвердження '
            f'в кабінеті Розетки.\n'
            f'Клієнт: {ri["customer"]} {ri["phone"]} {ri["total"]:.0f} грн\n'
            f'Після підтвердження агент обробить автоматично.'
        )
        return
    if not confirm_result:
        logger.error(f'Не вдалось підтвердити #{order_id}')
        return

    # Відправляємо Excel Carvol (Telegram → fallback email)
    excel      = create_order_excel(details, items_info)
    tg_sent    = send_excel_to_carvol_telegram(excel, order_id, items_info, details)
    email_sent = send_to_supplier(details, excel, items_info) if not tg_sent else False

    # Зберігаємо з phone/recipient/city для подальшого TTN-матчингу
    save_to_db(details, 'accepted')

    sent_icon = '📲 Telegram' if tg_sent else ('📧 Email' if email_sent else '❌')
    tg(f'📦 <b>{MARKETPLACE} #{order_id} прийнято!</b>\n'
       f'Клієнт: {ri["customer"]}\nТелефон: {ri["phone"]}\n'
       f'Товарів: {len(items_info)} | 💰 {ri["total"]:.0f} грн\n'
       f'Carvol: {sent_icon}\n'
       f'⏳ Чекаємо PDF з ТТН від Carvol')


# === ГОЛОВНИЙ ЦИКЛ ===

def main():
    logger.add('/tmp/rozetka_order_agent.log', rotation='10 MB', level='INFO')
    logger.info(f'=== {MARKETPLACE} Order Agent v4 запущено ===')
    os.makedirs(ORDERS_DIR, exist_ok=True)

    if not ROZETKA_API_TOKEN:
        logger.error('ROZETKA_API_TOKEN не задано в .env!')
        tg(f'❌ {MARKETPLACE} Order Agent: немає API токену')
        return

    tg(f'🚀 <b>{MARKETPLACE} Order Agent v4 запущено</b>')

    while True:
        feed = get_carvol_feed()
        try:
            orders = get_new_orders()
            if orders:
                logger.info(f'Знайдено {len(orders)} нових замовлень')
                for order in orders:
                    process_order(order, feed)
            else:
                logger.debug('Нових замовлень немає')
        except Exception as e:
            logger.error(f'Помилка циклу: {e}')
            tg(f'⚠️ <b>{MARKETPLACE} Order Agent помилка:</b> {e}')

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
