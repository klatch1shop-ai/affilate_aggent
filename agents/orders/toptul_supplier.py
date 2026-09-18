"""TOPTUL на Rozetka → постачальник «Гранд Інструмент»: лист із замовленням, облік, звірка ТТН.

Власник 18.09.2026: «розетку треба автоматизувати як з NOIRE — щоб розділяло на
цього постачальника та відправляло замовлення, а о 21:00 перевіряло, чи всі ТТН
додались: у день замовлення відправляють усе, що надіслано постачальнику до 14:00».

Потік (як працював TOPTUL на Prom, agents/orders/order_agent.py, але для Rozetka):
  1. агент Rozetka розпізнає товар TOPTUL за артикулом фіду TOPTUL;
  2. наявність — із живого фіду постачальника (три стани; TOPTUL НІКОЛИ не
     скасовується автоматично — без доказу не скасовуємо, SKILL-19);
  3. після підтвердження замовлення — бланк Excel і лист на opt@grandinstrument.ua
     у форматі, який постачальник уже знає;
  4. запис у toptul_supplier_orders: коли надіслано і коли чекати ТТН
     (до 14:00 — того ж дня, пізніше — наступного робочого);
  5. о 21:00 — reconcile(): лист «Рассылка ТТН» → зіставлення → звіт у Telegram.

Режим відправки TOPTUL_SEND_MODE (у .env, за замовчуванням test):
  off  — листа немає, лише запис і Telegram;
  test — лист іде НА НАШУ скриньку з позначкою [ТЕСТ]: перевірити бланк очима;
  live — лист постачальнику.
"""
import json
import os
import re
import smtplib
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from loguru import logger

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOPTUL_ROZETKA_FEED = os.getenv('TOPTUL_ROZETKA_FEED', os.path.join(BASE, 'output', 'toptul_rozetka.xml'))
SUPPLIER_EMAIL = 'opt@grandinstrument.ua'
SUPPLIER_CODE = '000160594'          # персональний код клієнта (лист Русанова 27.04.2026)
CUTOFF_HOUR = 14                     # відправлене до 14:00 постачальник везе того ж дня
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASS = os.getenv('SMTP_PASS')
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))

_arts = {'data': None, 't': 0}
_stock = {'data': None, 't': 0}


def send_mode():
    m = (os.getenv('TOPTUL_SEND_MODE') or 'test').strip().lower()
    return m if m in ('off', 'test', 'live') else 'test'


# ── хто постачальник ─────────────────────────────────────────────────
def toptul_articles():
    """{артикул} TOPTUL з нашого фіду Rozetka. None — прочитати не вдалось (тоді НЕ скасовувати)."""
    if _arts['data'] and time.time() - _arts['t'] < 3600:
        return _arts['data']
    try:
        arts = set()
        for _, el in ET.iterparse(TOPTUL_ROZETKA_FEED, events=('end',)):
            if el.tag == 'offer':
                a = (el.findtext('article') or '').strip()
                if a:
                    arts.add(a)
                el.clear()
        if not arts:
            raise ValueError('у фіді TOPTUL немає артикулів')
        _arts.update(data=arts, t=time.time())
        logger.info(f'Артикулів TOPTUL: {len(arts)}')
        return arts
    except Exception as e:
        logger.error(f'Фід TOPTUL (Rozetka) недоступний: {e}')
        return _arts['data']


def supplier_stock():
    """{АРТИКУЛ: {'available', 'stock'}} з живого фіду постачальника. None — недоступний."""
    if _stock['data'] and time.time() - _stock['t'] < 3600:
        return _stock['data']
    url = os.getenv('TOPTUL_FEED_URL')
    if not url:
        return None
    try:
        root = ET.fromstring(requests.get(url, timeout=120).content)
        out = {}
        for o in root.iter('offer'):
            sku = (o.findtext('vendorCode') or o.get('id') or '').strip().upper()
            if sku:
                out[sku] = {'available': o.get('available', 'true') == 'true',
                            'stock': (o.findtext('stock_quantity') or '').strip()}
        if not out:
            raise ValueError('порожній фід')
        _stock.update(data=out, t=time.time())
        return out
    except Exception as e:
        logger.error(f'Живий фід TOPTUL недоступний: {e}')
        return _stock['data']


def check_stock(items):
    """→ (True / False / None, рядки для Telegram). None — перевірити не вдалось."""
    st = supplier_stock()
    if st is None:
        return None, ['⚠️ живий фід TOPTUL недоступний — наявність не перевірено']
    states, lines = [], []
    for it in items:
        s = st.get(it['sku'].upper())
        if s is None:                       # у фіді немає — не доказ відсутності
            states.append(None)
            lines.append(f"❓ {it['sku']} × {it['quantity']} — немає у фіді постачальника")
        elif not s['available']:
            states.append(False)
            lines.append(f"❌ {it['sku']} × {it['quantity']} — немає в наявності")
        else:
            states.append(True)
            lines.append(f"✅ {it['sku']} × {it['quantity']} — є ({s['stock'] or 'в наявності'})")
    ok = False if False in states else (None if None in states else True)
    return ok, lines


# ── облік ────────────────────────────────────────────────────────────
def _db():
    import sys
    sys.path.insert(0, BASE)
    from shared.utils.db import get_connection
    return get_connection()


def init_table():
    conn = _db(); cur = conn.cursor()
    cur.execute("""create table if not exists toptul_supplier_orders (
        rozetka_order_id bigint primary key,
        sent_at timestamptz, send_mode text, expected_ttn_date date,
        customer_name text, customer_phone text, delivery_city text, delivery_place text,
        items jsonb, amount numeric, prepaid boolean,
        ttn text, ttn_at timestamptz, ttn_source text,
        status text, note text, updated_at timestamptz default now())""")
    conn.commit(); cur.close(); conn.close()


def expected_ttn_date(sent_at: datetime) -> date:
    """До 14:00 — того ж дня; пізніше — наступного робочого (сб, нд пропускаємо)."""
    d = sent_at.date() if sent_at.hour < CUTOFF_HOUR else sent_at.date() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


# ── лист постачальнику ───────────────────────────────────────────────
def build_excel(order_id, ri, items, prepaid):
    """Бланк у форматі «Гранд Інструменту» (той самий, що в order_agent.create_order_excel)."""
    import xlsxwriter
    fn = f'/tmp/order_rozetka_{order_id}_{datetime.now():%Y%m%d_%H%M}.xlsx'
    wb = xlsxwriter.Workbook(fn); ws = wb.add_worksheet('Замовлення')
    bold = wb.add_format({'bold': True, 'font_size': 11})
    head = wb.add_format({'bold': True, 'bg_color': '#1F4E79', 'font_color': 'white', 'border': 1, 'align': 'center'})
    cell = wb.add_format({'border': 1}); skuf = wb.add_format({'border': 1, 'bold': True})
    red = wb.add_format({'bold': True, 'font_color': 'red'}); wrap = wb.add_format({'text_wrap': True})
    ws.set_column('A:A', 5); ws.set_column('B:B', 22); ws.set_column('C:C', 55); ws.set_column('D:D', 14)
    ws.write('A1', 'Перевозчик', bold); ws.write('C1', 'Новая Почта')
    ws.write('A2', 'Оплата', bold)
    ws.write('C2', f"Передоплата (Rozetka) {ri['total']:.0f} грн" if prepaid
             else f"Наложенным платежом {ri['total']:.0f} грн")
    ws.write('A3', 'Коментарий', bold)
    ws.write('C3', f"{ri['customer']}  {ri['phone']}\n{ri['city']} {ri['warehouse']}", wrap)
    ws.set_row(2, 35)
    ws.write('A4', f'Замовлення Rozetka #{order_id}')
    ws.write('C4', f'Дата: {datetime.now():%d.%m.%Y %H:%M}')
    ws.write('A5', f'Код клієнта: {SUPPLIER_CODE}', red)
    for c, h in enumerate(['№', 'Артикул', 'Наименование', 'Количество']):
        ws.write(6, c, h, head)
    for i, it in enumerate(items, 1):
        ws.write(6 + i, 0, i, cell); ws.write(6 + i, 1, it['sku'], skuf)
        ws.write(6 + i, 2, str(it['name'])[:80], cell); ws.write(6 + i, 3, it['quantity'], cell)
    wb.close()
    return fn


def email_body(order_id, ri, items, prepaid):
    lines = '\n'.join(f"{i}. {it['sku']} | {str(it['name'])[:50]} | {it['quantity']} шт."
                      for i, it in enumerate(items, 1))
    pay = (f"Передоплата (Rozetka) {ri['total']:.0f} грн" if prepaid
           else f"Наложенным платежом {ri['total']:.0f} грн")
    return (f"Добрый день!\n\nЗаказ #{order_id}\nКод клиента: {SUPPLIER_CODE}\n\nТовары:\n{lines}\n\n"
            f"Получатель: {ri['customer']}\nТелефон: {ri['phone']}\n"
            f"Доставка: Нова Пошта, {ri['city']} {ri['warehouse']}\nОплата: {pay}\n\n"
            f"Детали в приложении (Excel).\n\nС уважением,\nklatch1.shop")


def send_to_supplier(order_id, ri, items, prepaid):
    """→ (надіслано?, кому, режим). Режим off — нічого не шле."""
    mode = send_mode()
    if mode == 'off':
        return False, '', mode
    to = SUPPLIER_EMAIL if mode == 'live' else SMTP_USER
    xls = build_excel(order_id, ri, items, prepaid)
    msg = MIMEMultipart()
    msg['From'], msg['To'] = SMTP_USER, to
    msg['Subject'] = (('[ТЕСТ — не постачальнику] ' if mode == 'test' else '')
                      + f'Заказ #{order_id} от {datetime.now():%d.%m.%Y}')
    msg.attach(MIMEText(email_body(order_id, ri, items, prepaid), 'plain', 'utf-8'))
    with open(xls, 'rb') as f:
        part = MIMEBase('application', 'octet-stream'); part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(xls)}"')
        msg.attach(part)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(msg)
    try:
        os.remove(xls)
    except OSError:
        pass
    return True, to, mode


def record_sent(order_id, ri, items, prepaid, mode, note=''):
    init_table()                       # create if not exists — дешево й безпечно
    now = datetime.now()
    exp = expected_ttn_date(now)
    conn = _db(); cur = conn.cursor()
    cur.execute("""insert into toptul_supplier_orders
        (rozetka_order_id, sent_at, send_mode, expected_ttn_date, customer_name, customer_phone,
         delivery_city, delivery_place, items, amount, prepaid, status, note, updated_at)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'sent',%s,now())
        on conflict (rozetka_order_id) do update set sent_at=excluded.sent_at, send_mode=excluded.send_mode,
          expected_ttn_date=excluded.expected_ttn_date, status='sent', note=excluded.note, updated_at=now()""",
                (order_id, now, mode, exp, ri['customer'], ri['phone'], ri['city'], ri['warehouse'],
                 json.dumps([{'sku': i['sku'], 'qty': i['quantity']} for i in items]),
                 ri['total'], prepaid, note))
    conn.commit(); cur.close(); conn.close()
    return exp


# ── звірка о 21:00 ───────────────────────────────────────────────────
def reconcile(today=None, write_ttn=False):
    """Лист «Рассылка ТТН» → наші відкриті замовлення TOPTUL. → текст звіту для Telegram.

    write_ttn=False — лише звіт (перші вечори). True — підтверджені ТТН
    записуються в Rozetka (статус 61) і перевіряються окремим читанням.
    """
    import sys
    sys.path.insert(0, os.path.join(BASE, 'tools'))
    import supplier_ttn_mail as M
    today = today or date.today()
    conn = _db(); cur = conn.cursor()
    cur.execute("""select * from toptul_supplier_orders where ttn is null and status in ('sent','alert')""")
    open_rows = cur.fetchall()
    mails = M.fetch_ttn_mails(today - timedelta(days=3))
    recs = [r for _, body in mails for r in M.parse(body)]
    orders = [{'prom_order_id': None, 'epicentr_order_id': None, 'rozetka_order_id': o['rozetka_order_id'],
               'customer_name': o['customer_name'], 'customer_phone': o['customer_phone'],
               'delivery_city': o['delivery_city']} for o in open_rows]
    matched, unmatched = {}, []
    for rec in recs:
        o, why = M.match(rec, orders)
        if o and ('✅' in why or 'ПІДТВЕРДИТИ' in why):
            matched[o['rozetka_order_id']] = (rec, why)
        else:
            unmatched.append((rec, why))
    lines = [f'📦 <b>TOPTUL · звірка ТТН {today:%d.%m}</b>']
    written = 0
    for o in open_rows:
        oid = o['rozetka_order_id']
        if oid in matched:
            rec, why = matched[oid]
            state = 'знайдено'
            if write_ttn and '✅' in why:
                sys.path.insert(0, os.path.join(BASE, 'agents', 'orders'))
                import rozetka_order_agent as RZ
                ok = RZ.set_ttn(oid, rec['ttn'])
                d = RZ.get_order_details(oid) or {}
                ok = ok and RZ._ttn_of(d) == rec['ttn']
                state = 'записано в Rozetka ✅' if ok else 'НЕ записано — вручну ⚠️'
                written += ok
            cur.execute("""update toptul_supplier_orders set ttn=%s, ttn_at=now(), ttn_source='email',
                           status=%s, note=%s, updated_at=now() where rozetka_order_id=%s""",
                        (rec['ttn'], 'ttn_written' if 'записано в Rozetka ✅' in state else 'ttn_found',
                         why, oid))
            lines.append(f"✅ #{oid} → ТТН {rec['ttn']} ({state})")
        elif o['expected_ttn_date'] and o['expected_ttn_date'] <= today:
            cur.execute("update toptul_supplier_orders set status='alert', updated_at=now() where rozetka_order_id=%s", (oid,))
            lines.append(f"🚨 #{oid} — ТТН немає, хоча очікувалась {o['expected_ttn_date']:%d.%m} "
                         f"(надіслано {o['sent_at']:%d.%m %H:%M})")
        else:
            lines.append(f"⏳ #{oid} — ТТН чекаємо {o['expected_ttn_date']:%d.%m} (надіслано після {CUTOFF_HOUR}:00)")
    for rec, why in unmatched:
        lines.append(f"❓ ТТН {rec['ttn']} ({rec['name']}) — не зіставлено: {why}")
    if len(lines) == 1:
        lines.append('Відкритих замовлень TOPTUL немає, листів з ТТН теж.')
    conn.commit(); cur.close(); conn.close()
    return '\n'.join(lines)
