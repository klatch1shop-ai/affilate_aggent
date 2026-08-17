"""
Агент обробки замовлень Єпіцентру — дропшипінг TOPTUL
======================================================
Цикл:
1. Отримати нові замовлення з Єпіцентр OMS API
2. Перевірити наявність у фіді TOPTUL (реальний час)
3. Підтвердити замовлення на Єпіцентрі
4. Сформувати Excel бланк → відправити на opt@grandinstrument.ua
5. Сповістити в Telegram
"""
import os, sys, json, time, requests, smtplib, asyncio
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
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
EPICENTR_TOKEN  = os.getenv('EPICENTR_TOKEN')
EPICENTR_BASE   = 'https://merchant-api.epicentrm.com.ua'
EPICENTR_HEADERS = {
    'Authorization': f'Bearer {EPICENTR_TOKEN}',
    'Content-Type':  'application/json',
}
TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)
SUPPLIER_EMAIL = 'opt@grandinstrument.ua'
SUPPLIER_CODE  = '000160594'
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASS = os.getenv('SMTP_PASS')
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID   = os.getenv('TG_CHAT_ID')
POLL_INTERVAL = 300  # 5 хвилин
MARKETPLACE   = 'Єпіцентр'

# === УТИЛІТИ ===

def tg(msg: str):
    """Відправити повідомлення в Telegram."""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.warning(f'TG помилка: {e}')


def parse_price(val) -> float:
    """Парсить ціну з будь-якого формату."""
    if val is None:
        return 0.0
    import re
    s = str(val).replace(' грн', '').replace('грн', '')
    s = s.replace('\xa0', '').replace('\u00a0', '')
    s = re.sub(r'(\d)\s+(\d)', r'\1\2', s)
    s = s.replace(',', '.').strip()
    match = re.search(r'[\d]+(?:\.[\d]+)?', s)
    return float(match.group()) if match else 0.0


# === ФІД TOPTUL ===

_feed_cache = {'data': {}, 'updated': None}

def get_feed_data(force=False) -> dict:
    """Повертає словник {sku: {available, price, name}} з фіду TOPTUL."""
    now = datetime.now()
    if (not force and _feed_cache['updated'] and
            (now - _feed_cache['updated']).seconds < 3600):
        return _feed_cache['data']
    try:
        r = requests.get(TOPTUL_FEED, timeout=120)
        root = ET.fromstring(r.content)
        offers = root.find('shop').find('offers').findall('offer')
        data = {}
        for offer in offers:
            sku_el = offer.find('vendorCode')
            if sku_el is None:
                continue
            sku = (sku_el.text or '').strip().upper()
            price_el = offer.find('price')
            name_el  = offer.find('name_ua') or offer.find('name')
            data[sku] = {
                'available': offer.get('available','false').lower() == 'true',
                'price':     float(price_el.text or 0) if price_el is not None else 0,
                'name':      (name_el.text or '') if name_el is not None else '',
            }
        _feed_cache['data']    = data
        _feed_cache['updated'] = now
        logger.info(f'Фід TOPTUL: {len(data)} SKU')
        return data
    except Exception as e:
        logger.error(f'Помилка фіду: {e}')
        return _feed_cache['data']


# === ЄПІЦЕНТР OMS API ===

def get_new_orders() -> list:
    """Отримати нові замовлення (статус new)."""
    try:
        r = requests.get(
            f'{EPICENTR_BASE}/v3/oms/orders',
            headers=EPICENTR_HEADERS,
            params={'statusCode': 'new', 'limit': 50},
            timeout=30
        )
        if r.status_code != 200:
            logger.error(f'OMS помилка {r.status_code}: {r.text[:200]}')
            return []
        items = r.json().get('items', [])
        # Фільтр statusCode=new у запиті Єпіцентр не застосовує: 17.08.2026
        # він повернув чотири замовлення зі статусом "canceled", створені ще
        # у квітні. Тому статус перевіряємо самі, а не віримо параметру.
        fresh = [o for o in items if (o.get('statusCode') or '').lower() == 'new']
        if len(fresh) != len(items):
            logger.warning(f'OMS віддав {len(items)} замовлень, з них справді '
                           f'нових {len(fresh)} — решту відкинуто за статусом')
        return fresh
    except Exception as e:
        logger.error(f'get_new_orders: {e}')
        return []


def get_order_details(order_id: str) -> dict:
    """Отримати повні деталі замовлення."""
    try:
        r = requests.get(
            f'{EPICENTR_BASE}/v5/oms/orders/{order_id}',
            headers=EPICENTR_HEADERS,
            timeout=30
        )
        return r.json() if r.status_code == 200 else {}
    except Exception as e:
        logger.error(f'get_order_details: {e}')
        return {}


def accept_order(order_id: str) -> bool:
    """Підтвердити замовлення (new → confirmed_by_merchant)."""
    try:
        # 1. Перевіряємо дозволені статуси
        r = requests.get(
            f'{EPICENTR_BASE}/v2/oms/orders/{order_id}/allowed-statuses',
            headers=EPICENTR_HEADERS, timeout=15
        )
        if r.status_code == 200:
            allowed = [s.get('code') for s in r.json().get('items', [])]
            if 'confirmed_by_merchant' not in allowed:
                logger.warning(f'Статус confirmed_by_merchant недоступний для {order_id}')
                return False
        # 2. Змінюємо статус
        r2 = requests.post(
            f'{EPICENTR_BASE}/v2/oms/orders/{order_id}/change-status/to/confirmed_by_merchant',
            headers=EPICENTR_HEADERS,
            json={'comment': 'Прийнято автоматично'},
            timeout=15
        )
        return r2.status_code in (200, 202, 204)
    except Exception as e:
        logger.error(f'accept_order: {e}')
        return False


def cancel_order(order_id: str, reason: str = 'customer_not_timely_confirmation_of_the_availability_of_goods') -> bool:
    """Скасувати замовлення (товар відсутній)."""
    try:
        r = requests.post(
            f'{EPICENTR_BASE}/v2/oms/orders/{order_id}/change-status/to/canceled_by_merchant',
            headers=EPICENTR_HEADERS,
            json={'reason_code': reason, 'comment': 'Товар відсутній у постачальника'},
            timeout=15
        )
        return r.status_code in (200, 202, 204)
    except Exception as e:
        logger.error(f'cancel_order: {e}')
        return False


def save_to_db(order: dict, status: str):
    """Зберегти замовлення в БД."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS epicentr_processed_orders (
                order_id    VARCHAR(100) PRIMARY KEY,
                ext_id      VARCHAR(100),
                status      VARCHAR(50),
                total_price NUMERIC(12,2),
                items       JSONB,
                processed_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        items = json.dumps(order.get('items', []), ensure_ascii=False)
        total = sum(i.get('subtotal', 0) for i in order.get('items', []))
        cur.execute('''
            INSERT INTO epicentr_processed_orders
                (order_id, ext_id, status, total_price, items)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (order_id) DO UPDATE
            SET status=EXCLUDED.status, processed_at=NOW()
        ''', (order.get('id'), order.get('externalId'), status, total, items))
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        logger.error(f'save_to_db: {e}')


def is_already_processed(order_id: str):
    """True — оброблялось, False — ні, None — перевірити не вдалось.

    Раніше при недоступній базі поверталось False, тобто «не оброблялось».
    17.08.2026 після перезавантаження PostgreSQL ще піднімався — агент
    втратив памʼять і взяв у роботу чотири замовлення, скасовані ще в квітні
    й липні, розіславши тривоги про них заново.
    """
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('''
            SELECT 1 FROM epicentr_processed_orders
            WHERE order_id = %s
        ''', (order_id,))
        exists = cur.fetchone() is not None
        cur.close(); conn.close()
        return exists
    except Exception as e:
        logger.error(f'is_already_processed({order_id}): {e}')
        return None


# === EXCEL БЛАНК ===

def create_order_excel(order: dict, items_info: list) -> str:
    """Формат бланку Гранд Інструмент (аналог Prom)."""
    order_id = order.get('id', 'unknown')[:8]
    filename = f'/tmp/epicentr_order_{order_id}_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'

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

    # Дані замовлення
    addr    = order.get('address') or {}
    ship    = addr.get('shipment') or {}
    customer = f"{addr.get('lastName','')} {addr.get('firstName','')}".strip()
    phone    = addr.get('phone', '')
    city_id  = ship.get('settlementId', '')
    office_n = ship.get('number', '')
    delivery_str = f'Нова Пошта {office_n}'.strip() if office_n else 'Нова Пошта'

    total = sum(i.get('subtotal', 0) for i in order.get('items', []))

    # Шапка
    ws.write('A1', 'Перевозчик', bold)
    ws.write('C1', 'Новая Почта')
    ws.write('A2', 'Оплата', bold)
    ws.write('C2', f'Наложенным платежом {total:.0f} грн')
    ws.write('A3', 'Комментарий', bold)
    ws.write('C3', f'{customer}  {phone}\n{delivery_str}', wrap_fmt)
    ws.set_row(2, 35)
    ws.write('A4', f'Замовлення {MARKETPLACE} #{order.get("externalId") or order_id}')
    ws.write('C4', f'Дата: {datetime.now().strftime("%d.%m.%Y %H:%M")}')
    ws.write('A5', f'Код клієнта: {SUPPLIER_CODE}', red_bold)

    # Заголовки
    row = 6
    for col, h in enumerate(['№', 'Артикул', 'Наименование', 'Количество']):
        ws.write(row, col, h, header_fmt)
    row += 1

    # Товари
    for idx, item in enumerate(items_info, 1):
        ws.write(row, 0, idx, cell_fmt)
        ws.write(row, 1, item.get('sku', ''), sku_fmt)
        ws.write(row, 2, item.get('title', '')[:80], cell_fmt)
        ws.write(row, 3, item.get('quantity', 1), cell_fmt)
        row += 1

    wb.close()
    logger.info(f'Excel: {filename}')
    return filename


def send_to_supplier(order: dict, excel_path: str, items_info: list):
    """Відправити бланк замовлення на пошту постачальника."""
    addr     = order.get('address') or {}
    customer = f"{addr.get('lastName','')} {addr.get('firstName','')}".strip()
    phone    = addr.get('phone', '')
    ship     = addr.get('shipment') or {}
    office_n = ship.get('number', '')
    delivery_str = f'Нова Пошта відд.{office_n}' if office_n else 'Нова Пошта'
    total    = sum(i.get('subtotal', 0) for i in order.get('items', []))
    order_id = order.get('externalId') or order.get('id', '')[:8]

    items_text = '\n'.join(
        f"{i}. {item.get('sku','')} | {item.get('title','')[:50]} | {item.get('quantity',1)} шт."
        for i, item in enumerate(items_info, 1)
    )

    body = f"""Добрый день!

Заказ #{order_id} от {datetime.now().strftime('%d.%m.%Y')}
Код клиента: {SUPPLIER_CODE}

Товары:
{items_text}

Получатель: {customer}
Телефон: {phone}
Доставка: {delivery_str}
Оплата: Наложенным платежом {total:.0f} грн

Детали в приложении (Excel).

С уважением,
klatch1.shop
"""
    msg = MIMEMultipart()
    msg['From']    = SMTP_USER
    msg['To']      = SUPPLIER_EMAIL
    msg['Subject'] = f'Заказ #{order_id} от {datetime.now().strftime("%d.%m.%Y")} ({MARKETPLACE})'
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
        logger.success(f'Email відправлено: {order_id}')
        return True
    except Exception as e:
        logger.error(f'Email помилка: {e}')
        return False


# === ОБРОБКА ЗАМОВЛЕННЯ ===

def process_order(order: dict, feed: dict):
    """Обробити одне замовлення."""
    order_id  = order.get('id', '')
    ext_id    = order.get('externalId') or order_id[:8]

    processed = is_already_processed(order_id)
    if processed is None:
        logger.warning(f'#{ext_id} — стан у базі невідомий, пропускаємо цикл')
        return
    if processed:
        return

    logger.info(f'Обробляємо {MARKETPLACE} замовлення #{ext_id}')

    # Деталі замовлення
    details = get_order_details(order_id)
    if not details:
        logger.error(f'Не вдалось отримати деталі {order_id}')
        return

    items = details.get('items', [])
    if not items:
        logger.warning(f'Замовлення {ext_id} — немає товарів')
        return

    # Перевіряємо наявність кожного товару
    items_info   = []
    all_available = True

    # Три стани замість двох: є доказ наявності, є доказ відсутності, і
    # «перевірити не вдалось». Останній доти зливався з відсутністю.
    # 17.08.2026 о 18:25 це коштувало замовлення #0307dcfb: після
    # перезавантаження PostgreSQL ще піднімався, маппінг не прочитався,
    # артикул 2934020997 не знайшовся у фіді під сирим номером — і товар,
    # який був у наявності, скасувався автоматично.
    unknown = []
    out_of_stock = []

    for item in items:
        # SKU береться з productExternalId або з маппінгу
        product_ext_id = item.get('productExternalId') or item.get('sku', '')
        sku = product_ext_id.upper()

        # Шукаємо наш SKU через epicentr_sku_mapping
        our_sku = sku
        mapping_ok = False
        try:
            conn = get_connection()
            cur  = conn.cursor()
            cur.execute(
                'SELECT our_sku FROM epicentr_sku_mapping WHERE epicentr_article = %s',
                (product_ext_id,)
            )
            row = cur.fetchone()
            if row:
                our_sku = row['our_sku'].upper()
            cur.close(); conn.close()
            mapping_ok = True
        except Exception as e:
            # Мовчазний `except: pass` тут і був коренем аварії: помилка бази
            # зникала без сліду, а далі код працював із сирим артикулом, наче
            # маппінг просто нічого не знайшов.
            logger.error(f'  {product_ext_id} — маппінг недоступний: {e}')

        feed_item = feed.get(our_sku) if feed else None
        if not mapping_ok or feed_item is None:
            available = None
            reason = 'маппінг недоступний' if not mapping_ok else 'немає у фіді'
            unknown.append(our_sku)
            logger.warning(f'  {our_sku} — наявність невідома ({reason})')
        else:
            available = bool(feed_item.get('available'))
            if not available:
                out_of_stock.append(our_sku)
                logger.warning(f'  {our_sku} — фід підтверджує відсутність')

        items_info.append({
            'sku':       our_sku,
            'title':     item.get('title', ''),
            'quantity':  item.get('quantity', 1),
            'price':     item.get('price', 0),
            'subtotal':  item.get('subtotal', 0),
            'available': available,
        })

    all_available = not unknown and not out_of_stock

    total = sum(i.get('subtotal', 0) for i in items)
    addr  = details.get('address') or {}
    customer = f"{addr.get('lastName','')} {addr.get('firstName','')}".strip()
    phone    = addr.get('phone', '')

    # Скасовуємо лише за доказом відсутності.
    if out_of_stock:
        # Результат скасування перевіряємо, а не припускаємо (див. той самий
        # дефект у rozetka_order_agent).
        done = cancel_order(order_id)
        save_to_db(details, 'cancelled_no_stock' if done else 'cancel_failed')
        if done:
            tg(f"""❌ <b>{MARKETPLACE} замовлення #{ext_id} — товар відсутній!</b>
Клієнт: {customer} {phone}
Відсутні: {', '.join(out_of_stock)}
Замовлення скасовано автоматично.""")
            logger.warning(f'Замовлення #{ext_id} скасовано — немає товару')
        else:
            tg(f"""⚠️ <b>{MARKETPLACE} #{ext_id} — скасувати НЕ вдалось</b>
Клієнт: {customer} {phone}
Відсутні: {', '.join(out_of_stock)}
Замовлення лишається активним — розібратись вручну.""")
            logger.error(f'Замовлення #{ext_id} — cancel_order повернув False')
        return

    # Перевірити не вдалось — замовлення лишається живим і чекає людини.
    if unknown:
        save_to_db(details, 'manual_review')
        tg(f"""🖐 <b>{MARKETPLACE} замовлення #{ext_id} — ручна обробка</b>
Клієнт: {customer} {phone}
Наявність не перевірена: {', '.join(unknown)}
💰 {total:.0f} грн
<b>Замовлення НЕ скасовано</b> — перевірити вручну в кабінеті.""")
        logger.info(f'#{ext_id} → ручна обробка ({len(unknown)} поз. без перевірки)')
        return

    # Підтверджуємо
    if accept_order(order_id):
        logger.success(f'Замовлення #{ext_id} підтверджено на {MARKETPLACE}')
    else:
        logger.error(f'Не вдалось підтвердити #{ext_id}')
        return

    # Формуємо Excel і відправляємо
    excel = create_order_excel(details, items_info)
    email_sent = send_to_supplier(details, excel, items_info)

    save_to_db(details, 'accepted')

    tg(f"""📧 <b>{MARKETPLACE} замовлення #{ext_id} відправлено постачальнику</b>
Клієнт: {customer} {phone}
Товарів: {len(items_info)}
💰 Сума: {total:.0f} грн
📧 Email: {'✅' if email_sent else '❌'}""")


# === ГОЛОВНИЙ ЦИКЛ ===

def main():
    logger.add('/tmp/epicentr_order_agent.log', rotation='10 MB', level='INFO')
    logger.info(f'{MARKETPLACE} Order Agent запущено')
    tg(f'🚀 <b>{MARKETPLACE} Order Agent запущено</b>')

    while True:
        try:
            logger.info('Перевіряємо нові замовлення...')
            feed   = get_feed_data()
            # Порожній фід = «не знаю». Після рестарту кеш порожній за
            # визначенням, тому цикл пропускаємо, а не обробляємо наосліп.
            if not feed:
                logger.warning('Фід TOPTUL порожній — цикл пропущено, '
                               'замовлення не обробляються')
                time.sleep(POLL_INTERVAL)
                continue
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
