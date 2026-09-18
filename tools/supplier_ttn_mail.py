#!/usr/bin/env python3
"""ТТН від постачальника з пошти → наше замовлення. Лише читання, нічого не записує.

Як працював потік TOPTUL на Prom (agents/orders/order_agent.py):
  замовлення → бланк Excel листом на opt@grandinstrument.ua → увечері
  «Гранд Інструмент» надсилає лист «Рассылка ТТН» → ТТН вносили ВРУЧНУ.
Цей скрипт закриває ручний крок.

Формат листа (info@grandinstrument.ua, ~18:00, тема «Рассылка ТТН»):
    Нова Пошта Руссо Оксана 20400527554172 до сплати 95 грн. отримувати 26.05.26 ;
Кожна ТТН — відрізок до «;». **Номера нашого замовлення в листі немає** —
лише ім'я одержувача. Тому зіставлення двоступеневе:

  1. ім'я: усі слова з листа є серед слів customer_name замовлення (порядок
     «ім'я прізвище» чи навпаки не важить). Кандидат має бути РІВНО ОДИН серед
     відкритих замовлень (відправлені постачальнику, без ТТН, за останні дні);
  2. підтвердження Новою Поштою: трекінг ТТН з телефоном одержувача дає місто —
     воно має збігтися з містом доставки замовлення.

Будь-що інше (0 або ≥2 кандидатів, місто не збіглось, ім'я не з наших
замовлень) — на розгляд людині, а не «найімовірніший варіант».

Перевірено 18.09.2026 на трьох історичних листах: кожен зіставився рівно з
одним замовленням.

    venv/bin/python tools/supplier_ttn_mail.py --since 2026-04-01 --all-orders   # на історії
    venv/bin/python tools/supplier_ttn_mail.py                                   # за 3 дні, відкриті замовлення
"""
import argparse
import datetime
import email
import imaplib
import os
import re
import sys
from email.header import decode_header

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE, '.env'))

SENDER = 'info@grandinstrument.ua'
LINE = re.compile(r'(?P<carrier>Нова Пошта|Укрпошта|Meest|Делівері)\s+(?P<name>.+?)\s+(?P<ttn>\d{14})\s+'
                  r'до сплати\s+(?P<pay>[\d.,]+)\s*грн\.?\s*отримувати\s+(?P<date>\d{2}\.\d{2}\.\d{2})', re.I)
WORD = re.compile(r"[A-Za-zА-Яа-яІіЇїЄєҐґ']{2,}")


def words(s):
    return {w.lower().replace('ё', 'е') for w in WORD.findall(s or '')}


def _dec(s):
    return ''.join(t.decode(c or 'utf-8', 'replace') if isinstance(t, bytes) else t
                   for t, c in decode_header(s or ''))


def fetch_ttn_mails(since: datetime.date):
    """[(дата листа, текст)] з листів «Рассылка ТТН». Скринька лише для читання."""
    M = imaplib.IMAP4_SSL('imap.gmail.com')
    M.login(os.environ['SMTP_USER'], os.environ['SMTP_PASS'])
    M.select('INBOX', readonly=True)                  # листи не позначаються прочитаними
    typ, data = M.search(None, 'FROM', f'"{SENDER}"', 'SINCE', since.strftime('%d-%b-%Y'))
    out = []
    for i in data[0].split():
        typ, raw = M.fetch(i, '(BODY.PEEK[])')
        msg = email.message_from_bytes(raw[0][1])
        if 'ТТН' not in _dec(msg.get('Subject')).upper():
            continue
        body = ''
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                body += part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', 'replace')
        out.append((msg.get('Date'), body))
    M.logout()
    return out


def parse(body):
    return [m.groupdict() for m in LINE.finditer(body)]


def open_orders(all_orders=False, days=7):
    from shared.utils.db import get_connection
    cur = get_connection().cursor()
    q = ('select prom_order_id, epicentr_order_id, customer_name, customer_phone, delivery_city, '
         'status, ttn, supplier_email_sent, created_at from orders')
    if not all_orders:
        q += (" where supplier_email_sent and ttn is null"
              f" and created_at > now() - interval '{int(days)} days'")
    cur.execute(q)
    return cur.fetchall()


def np_city(ttn, phone):
    """Місто одержувача з трекінгу НП (потрібен телефон одержувача). None — не вдалося."""
    import requests
    key = os.getenv('NP_API_KEY')
    if not key:
        return None
    r = requests.post('https://api.novaposhta.ua/v2.0/json/', timeout=30, json={
        'apiKey': key, 'modelName': 'TrackingDocument', 'calledMethod': 'getStatusDocuments',
        'methodProperties': {'Documents': [{'DocumentNumber': ttn, 'Phone': re.sub(r'\D', '', phone or '')}]}}).json()
    d = (r.get('data') or [{}])[0]
    return d.get('CityRecipient') or None


def match(rec, orders):
    """→ (замовлення або None, пояснення)."""
    need = words(rec['name'])
    cands = [o for o in orders if need and need <= words(o['customer_name'])]
    if len(cands) != 1:
        return None, (f'кандидатів за іменем: {len(cands)} — на розгляд людині' if cands
                      else 'імені немає серед відкритих замовлень — на розгляд людині')
    o = cands[0]
    city = np_city(rec['ttn'], o['customer_phone'])
    if city is None:
        return o, 'збіг за іменем; місто НП не перевірено (немає ключа НП або відповіді) — ПІДТВЕРДИТИ'
    if o['delivery_city'] and words(o['delivery_city']) & words(city):
        return o, f'збіг за іменем і містом НП ({city}) ✅'
    return None, f'ім\'я збіглось, але місто НП «{city}» ≠ «{o["delivery_city"]}» — на розгляд людині'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', help='YYYY-MM-DD, за замовчуванням 3 дні тому')
    ap.add_argument('--all-orders', action='store_true', help='шукати серед усіх замовлень (перевірка на історії)')
    ap.add_argument('--days', type=int, default=7)
    a = ap.parse_args()
    since = (datetime.date.fromisoformat(a.since) if a.since
             else datetime.date.today() - datetime.timedelta(days=3))
    mails = fetch_ttn_mails(since)
    orders = open_orders(a.all_orders, a.days)
    print(f'листів «Рассылка ТТН» з {since}: {len(mails)} · замовлень для зіставлення: {len(orders)}')
    ok = review = 0
    for date, body in mails:
        recs = parse(body)
        if not recs:
            print(f'  {date}: рядків з ТТН не розпізнано — формат змінився? «{body.strip()[:80]}»')
            review += 1
            continue
        for rec in recs:
            o, why = match(rec, orders)
            oid = (o or {}).get('prom_order_id') or (o or {}).get('epicentr_order_id')
            ok += bool(o and '✅' in why)
            review += not (o and '✅' in why)
            print(f"  ТТН {rec['ttn']} · до сплати {rec['pay']} грн · отримувати {rec['date']} → "
                  f"{'замовлення ' + str(oid) if oid else '—'} · {why}")
    print(f'\nпідтверджено: {ok} · на розгляд людині: {review}. Нічого не записано.')


if __name__ == '__main__':
    main()
