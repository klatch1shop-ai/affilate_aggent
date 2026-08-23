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
from agents.orders import supplier_stock  # noqa: E402

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

# Автопідтвердження вимкнене доки не ввімкнуть явно: підтвердження — це запис
# у живий маркетплейс. Вмикається прапорцем --confirm або NOIRE_AUTOCONFIRM=1.
AUTOCONFIRM = os.getenv('NOIRE_AUTOCONFIRM', '') == '1'

# Наявність Carvol доведено ненадійною (артикул був у фіді, а в постачальника
# його не було, 08.2026). Тому позиція Carvol сама по собі НЕ дає підстави
# підтвердити замовлення. Змінити лише свідомим рішенням власника.
TRUST_CARVOL = os.getenv('NOIRE_TRUST_CARVOL', '') == '1'


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
    """
    Замовлення потрібного статусу.

    ВАЖЛИВО: параметр statusCode Єпіцентр НЕ застосовує — повертає замовлення
    будь-яких статусів (перевірено 17.08.2026, підтверджено повторно 23.08.2026:
    на запит 'new' прийшло 5 замовлень, усі 'canceled'). Тому фільтруємо самі.
    Без цього фільтра автопідтвердження намагалося б підтвердити скасоване.
    """
    r = requests.get(f'{EPICENTR_BASE}/v3/oms/orders', headers=HEADERS,
                     params={'statusCode': status, 'limit': 50}, timeout=30)
    if r.status_code != 200:
        logger.error(f'OMS {r.status_code}: {r.text[:200]}')
        return []
    items = r.json().get('items', [])
    fresh = [o for o in items if (o.get('statusCode') or '').lower() == status]
    if len(fresh) != len(items):
        logger.info(f'OMS повернув {len(items)}, зі статусом {status}: {len(fresh)}')
    return fresh


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


def decide(items, stock) -> tuple:
    """
    Чи можна підтвердити замовлення. Повертає (можна, причина).

    Підтверджуємо ТІЛЬКИ якщо кожна позиція замовлення є в постачальника.
    Замовлення підтверджується цілком, а не по позиціях, тому перевіряти треба
    ВСІ позиції — включно з чужими (Toptul/Carvol), а не лише NOIRE.
    """
    if not stock:
        return False, 'наявність не перевірено'
    bad, unk, weak = [], [], []
    for it in items:
        sku = item_sku(it)
        r = stock.get(sku)
        if not r or r['state'] == supplier_stock.UNKNOWN:
            unk.append(sku)
        elif r['state'] == supplier_stock.OUT:
            bad.append(sku)
        elif r.get('supplier') == 'carvol' and not TRUST_CARVOL:
            weak.append(sku)
    if bad:
        return False, f"немає в постачальника: {', '.join(bad)}"
    if unk:
        return False, f"наявність невідома: {', '.join(unk)}"
    if weak:
        return False, f"позиції Carvol потребують ручної звірки: {', '.join(weak)}"
    return True, 'усі позиції є в постачальника'


def accept_order(order_id: str) -> bool:
    """
    new → confirmed_by_merchant. Механізм той самий, що в
    agents/orders/epicentr_order_agent.py: спершу allowed-statuses, потім зміна.
    """
    try:
        r = requests.get(f'{EPICENTR_BASE}/v2/oms/orders/{order_id}/allowed-statuses',
                         headers=HEADERS, timeout=15)
        if r.status_code == 200:
            allowed = [x.get('code') for x in r.json().get('items', [])]
            if 'confirmed_by_merchant' not in allowed:
                logger.warning(f'{order_id}: confirmed_by_merchant недоступний, '
                               f'дозволено: {allowed}')
                return False
        r2 = requests.post(
            f'{EPICENTR_BASE}/v2/oms/orders/{order_id}/change-status/to/confirmed_by_merchant',
            headers=HEADERS, json={'comment': 'Наявність підтверджено за фідом постачальника'},
            timeout=20)
        if r2.status_code not in (200, 202, 204):
            logger.error(f'{order_id}: підтвердження {r2.status_code} {r2.text[:200]}')
            return False
        return True
    except Exception as e:
        logger.error(f'accept_order {order_id}: {e}')
        return False


def build_message(ext_id, details, mine, foreign_cnt, stock=None, verdict=None) -> str:
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
        sku = item_sku(it)
        av = (stock or {}).get(sku)
        mark = f"  {supplier_stock.ICON[av['state']]}" if av else ''
        if av and av.get('qty') is not None:
            mark += f" {av['qty']:g} шт у постачальника"
        elif av:
            mark += {'in_stock': ' є в постачальника',
                     'out_of_stock': ' НЕМАЄ в постачальника',
                     'unknown': ' наявність невідома'}[av['state']]
        lines.append(f"• {it.get('name', '')[:70]}\n  <code>{sku}</code>"
                     f" × {qty} — {price:.2f} грн{mark}")
    lines += ['', f'💰 Сума NOIRE: <b>{total:.2f} грн</b>']
    if foreign_cnt:
        lines.append(f'⚠️ У замовленні ще {foreign_cnt} поз. інших напрямків '
                     f'(Toptul/Carvol) — їх обробляє окремий агент')
    lines += ['', f'👤 {name}', f'📞 {phone}']
    if city or addr:
        lines.append(f'📍 {city} {addr}'.strip())
    if stock:
        bad = [k for k, v in stock.items() if v['state'] == supplier_stock.OUT]
        unk = [k for k, v in stock.items() if v['state'] == supplier_stock.UNKNOWN]
        if bad:
            lines += ['', f"⛔️ НЕМАЄ в постачальника: {', '.join(bad)}",
                      'Підтверджувати не можна — спершу звір із постачальником']
        if unk:
            lines += ['', f"❓ Наявність невідома: {', '.join(unk)}",
                      'Невідомо ≠ немає. Перевір вручну, не скасовуй наосліп']
    if verdict:
        ok, why, acted = verdict
        if acted:
            lines += ['', f'✅ <b>ПІДТВЕРДЖЕНО автоматично</b> — {why}']
        elif ok:
            lines += ['', f'✅ Можна підтверджувати — {why}',
                      'Автопідтвердження вимкнене — підтвердь у кабінеті']
        else:
            lines += ['', f'✋ <b>НЕ підтверджено</b> — {why}']
    lines += ['', '⏱ На підтвердження 2 год, далі блокування компанії']
    if not (verdict and verdict[2]):
        lines.append('⚠️ Статус НЕ змінено — дія за тобою')
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
        try:
            stock = supplier_stock.check([item_sku(i) for i in items])
        except Exception as e:
            logger.error(f'перевірка наявності: {e}')
            stock = None          # сповіщення важливіше за перевірку — не падаємо
        ok, why = decide(items, stock)
        acted = False
        if ok and AUTOCONFIRM and not dry:
            acted = accept_order(oid)
            if not acted:
                why += ' (підтвердити не вдалось — дивись лог)'
            logger.info(f'#{ext}: автопідтвердження={acted}')
        msg = build_message(ext, det, mine, len(items) - len(mine), stock, (ok, why, acted))
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
    ap.add_argument('--confirm', action='store_true',
                    help='увімкнути автопідтвердження (запис у маркетплейс)')
    a = ap.parse_args()
    global AUTOCONFIRM
    if a.confirm:
        AUTOCONFIRM = True
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
