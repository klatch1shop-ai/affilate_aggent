#!/usr/bin/env python3
"""
NOIRE / SexOpt — сповіщення про нові замовлення з Єпіцентру
============================================================
Мінімальний функціонал: тільки читання й сповіщення.

Свідомо НЕ робить:
  • не змінює статуси замовлень (жодного change-status)
  • не чіпає замовлення Toptul і Carvol — ані статус, ані наявність
  • не пише в epicentr_processed_orders (див. коментар до NOIRE_TABLE)

Запуск:
    python3 agents/orders/noire_order_notifier.py            # демон
    python3 agents/orders/noire_order_notifier.py --once     # один цикл
    python3 agents/orders/noire_order_notifier.py --selftest # перевірка звʼязків
"""
import os
import sys
import json
import time
import argparse

import requests
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

EPICENTR_BASE = 'https://merchant-api.epicentrm.com.ua'
HEADERS = {'Authorization': f"Bearer {os.getenv('EPICENTR_TOKEN')}",
           'Content-Type': 'application/json'}

# На різних машинах змінні названі по-різному — підтримуємо обидва варіанти
TG_TOKEN = os.getenv('TG_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT = os.getenv('TG_CHAT_ID') or os.getenv('TELEGRAM_ADMIN_ID')

# Окрема таблиця, а НЕ epicentr_processed_orders: у тій таблиці
# epicentr_order_agent.py (Toptul) робить is_already_processed() за одним лише
# order_id. Якщо ми запишемо туди змішане замовлення (Toptul + NOIRE в одному
# кошику), Toptul-агент вважатиме його обробленим і пропустить назавжди.
NOIRE_TABLE = 'noire_processed_orders'

POLL_INTERVAL = int(os.getenv('NOIRE_POLL_INTERVAL', '300'))


def tg(text: str) -> bool:
    if not TG_TOKEN or not TG_CHAT:
        logger.warning('Telegram не налаштовано — пропускаю сповіщення')
        return False
    try:
        r = requests.post(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                          json={'chat_id': TG_CHAT, 'text': text,
                                'parse_mode': 'HTML',
                                'disable_web_page_preview': True}, timeout=15)
        if r.status_code != 200:
            logger.error(f'TG {r.status_code}: {r.text[:200]}')
        return r.status_code == 200
    except Exception as e:
        logger.error(f'TG: {e}')
        return False


def ensure_table():
    conn = get_connection(); cur = conn.cursor()
    cur.execute(f'''CREATE TABLE IF NOT EXISTS {NOIRE_TABLE} (
        order_id VARCHAR(100) PRIMARY KEY,
        ext_id VARCHAR(100), source VARCHAR(20) DEFAULT 'noire',
        total_price NUMERIC(12,2), noire_skus TEXT, items JSONB,
        notified BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW())''')
    conn.commit(); cur.close(); conn.close()


def noire_skus() -> set:
    """Усі SKU NOIRE. Toptul (my_products) і Carvol (carvol_products) сюди
    не потрапляють — це окремі таблиці з іншими форматами артикулів."""
    conn = get_connection(); cur = conn.cursor()
    cur.execute('SELECT sku FROM sexopt_products')
    skus = {str(r['sku']).strip().upper() for r in cur.fetchall()}
    cur.close(); conn.close()
    return skus


def seen(order_id: str) -> bool:
    conn = get_connection(); cur = conn.cursor()
    cur.execute(f'SELECT 1 FROM {NOIRE_TABLE} WHERE order_id=%s', (order_id,))
    r = cur.fetchone() is not None
    cur.close(); conn.close()
    return r


def remember(order_id, ext_id, total, skus, items, notified):
    conn = get_connection(); cur = conn.cursor()
    cur.execute(f'''INSERT INTO {NOIRE_TABLE}
        (order_id, ext_id, source, total_price, noire_skus, items, notified)
        VALUES (%s,%s,'noire',%s,%s,%s,%s) ON CONFLICT (order_id) DO NOTHING''',
        (order_id, ext_id, total, ','.join(skus),
         json.dumps(items, ensure_ascii=False), notified))
    conn.commit(); cur.close(); conn.close()


def get_orders(status='new') -> list:
    r = requests.get(f'{EPICENTR_BASE}/v3/oms/orders', headers=HEADERS,
                     params={'statusCode': status, 'limit': 50}, timeout=30)
    if r.status_code != 200:
        logger.error(f'OMS {r.status_code}: {r.text[:200]}')
        return []
    return r.json().get('items', [])


def get_details(order_id: str) -> dict:
    r = requests.get(f'{EPICENTR_BASE}/v5/oms/orders/{order_id}',
                     headers=HEADERS, timeout=30)
    return r.json() if r.status_code == 200 else {}


def item_sku(item: dict) -> str:
    for k in ('productExternalId', 'sku', 'article', 'externalId'):
        v = item.get(k)
        if v:
            return str(v).strip().upper()
    return ''


def build_message(ext_id, details, mine, foreign_cnt) -> str:
    d = details.get('deliveryAddress') or details.get('delivery') or {}
    c = details.get('customer') or details.get('recipient') or {}
    name = ' '.join(filter(None, [c.get('lastName'), c.get('firstName'),
                                  c.get('middleName')])) or c.get('name') or '—'
    phone = c.get('phone') or details.get('phone') or '—'
    addr = d.get('address') or d.get('title') or ''
    city = d.get('city') or d.get('cityName') or ''

    lines = [f'🛒 <b>Нове замовлення NOIRE</b>  #{ext_id}', '']
    total = 0.0
    for it in mine:
        qty = it.get('quantity', 1)
        price = float(it.get('price') or it.get('subtotal') or 0)
        total += price * (qty if not it.get('subtotal') else 1)
        lines.append(f"• {it.get('name', '')[:70]}\n  <code>{item_sku(it)}</code>"
                     f" × {qty} — {price:.2f} грн")
    lines += ['', f'💰 Сума NOIRE: <b>{total:.2f} грн</b>']
    if foreign_cnt:
        lines.append(f'⚠️ У замовленні ще {foreign_cnt} поз. інших напрямків '
                     f'(Toptul/Carvol) — їх обробляє окремий агент')
    lines += ['', f'👤 {name}', f'📞 {phone}']
    if city or addr:
        lines.append(f'📍 {city} {addr}'.strip())
    lines += ['', '⚠️ Статус НЕ змінено автоматично — підтвердь у кабінеті']
    return '\n'.join(lines)


def cycle(dry=False) -> int:
    skus = noire_skus()
    orders = get_orders()
    logger.info(f'Замовлень зі статусом new: {len(orders)} | SKU NOIRE у базі: {len(skus)}')
    sent = 0
    for o in orders:
        oid = o.get('id', '')
        ext = o.get('externalId') or oid[:8]
        if not oid or seen(oid):
            continue
        det = get_details(oid) or o
        items = det.get('items', [])
        mine = [i for i in items if item_sku(i) in skus]
        if not mine:
            logger.debug(f'#{ext}: немає позицій NOIRE — пропускаю')
            continue
        msg = build_message(ext, det, mine, len(items) - len(mine))
        ok = True if dry else tg(msg)
        if dry:
            print(msg)
        total = sum(float(i.get('subtotal') or 0) for i in mine)
        remember(oid, ext, total, [item_sku(i) for i in mine], mine, ok)
        sent += 1
        logger.info(f'#{ext}: {len(mine)} поз. NOIRE, сповіщено={ok}')
    return sent


def selftest():
    print('EPICENTR_TOKEN :', 'є' if os.getenv('EPICENTR_TOKEN') else 'НЕМАЄ')
    print('Telegram       :', 'є' if (TG_TOKEN and TG_CHAT) else 'НЕМАЄ')
    ensure_table(); print(f'Таблиця {NOIRE_TABLE}: ok')
    print('SKU NOIRE      :', len(noire_skus()))
    for st in ('new', 'confirmed_by_merchant'):
        r = requests.get(f'{EPICENTR_BASE}/v3/oms/orders', headers=HEADERS,
                         params={'statusCode': st, 'limit': 5}, timeout=30)
        print(f'GET /v3/oms/orders [{st}] → HTTP {r.status_code}, '
              f'позицій: {len(r.json().get("items", [])) if r.status_code == 200 else "—"}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--dry', action='store_true', help='не слати в TG, друкувати')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    logger.add(os.path.join(BASE_DIR, 'logs', 'noire_orders.log'),
               rotation='10 MB', retention='30 days')
    if a.selftest:
        selftest(); return
    ensure_table()
    if a.once or a.dry:
        cycle(dry=a.dry); return
    logger.info(f'NOIRE notifier запущено, інтервал {POLL_INTERVAL}s')
    tg('🟢 NOIRE-нотифікатор запущено')
    while True:
        try:
            cycle()
        except Exception as e:
            logger.error(f'цикл: {e}')
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
