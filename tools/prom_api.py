#!/usr/bin/env python3
"""Публічне API Prom.ua — звірка фактичного стану товарів.

Навіщо: після імпорту Prom самостійно перевизначає портальну категорію, якщо
вважає нашу помилковою (806 товарів у першому імпорті). З кабінету цього не
видно — у лівому меню показані ГРУПИ магазину, а не категорії каталогу.
API повертає обидва поля, тож дає точну відповідь замість здогадок за назвою.

Ключова відмінність, яку легко переплутати:
    group   — папка в дереві нашого магазину, її створює <categoryId>
    category — категорія маркетплейсу, її задає <portal_category_id>,
               і саме її Prom може змінити на свій розсуд

Ліміти: жорстких квот у документації немає. Пагінація по 1000 (максимум
методу) замість поштучних запитів, пауза 0.5 с між сторінками. Для запису
використовуються пакетні виклики — там паузи не потрібні.

Запуск:
    python3 tools/prom_api.py --health          # перевірка токена і прав
    python3 tools/prom_api.py --test-write SKU  # безпечний no-op запис
    python3 tools/prom_api.py --sync            # витягти всі товари в БД
    python3 tools/prom_api.py --report          # таблиця розбіжностей
"""
import argparse
import json
import os
import sys
import time

import requests
import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

API = 'https://my.prom.ua/api/v1'
TOKEN = os.getenv('PROM_API_TOKEN', '')
PAGE = 1000
PAUSE = 0.5


def _headers():
    return {'Authorization': f'Bearer {TOKEN}',
            'Content-Type': 'application/json'}


def call(method: str, path: str, cur=None, **kw):
    """Запит із записом у api_test_log — щоб історія викликів велася."""
    t0 = time.time()
    r = requests.request(method, API + path, headers=_headers(), timeout=90, **kw)
    elapsed = round(time.time() - t0, 3)
    if cur is not None:
        try:
            cur.execute("""INSERT INTO api_test_log
                (marketplace, method, endpoint, params, status_code,
                 response_body, elapsed)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        ('prom', method, path,
                         json.dumps(kw.get('params') or kw.get('json'),
                                    ensure_ascii=False)[:2000],
                         r.status_code, r.text[:2000], elapsed))
            cur.connection.commit()
        except Exception as e:
            cur.connection.rollback()
            logger.warning(f'api_test_log: {e}')
    return r


def ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prom_product_state (
            external_id        TEXT PRIMARY KEY,
            prom_id            BIGINT,
            name               TEXT,
            group_id           BIGINT,
            group_name         TEXT,
            portal_category_id TEXT,
            portal_category    TEXT,
            price              NUMERIC,
            presence           TEXT,
            status             TEXT,
            quantity_in_stock  INTEGER,
            is_variation       BOOLEAN,
            variation_group_id BIGINT,
            fetched_at         TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def cmd_health(cur):
    """Легка перевірка: 200 — токен живий і права на «Продукти та групи» є."""
    r = call('GET', '/groups/list?limit=1', cur)
    verdict = {200: 'токен валідний, права на читання є',
               401: 'токен прострочений або видалений',
               403: 'токен валідний, але немає прав на цей блок'}
    print(f"GET /groups/list?limit=1 → HTTP {r.status_code}  "
          f"{verdict.get(r.status_code, 'несподіваний код')}")
    return r.status_code == 200


def cmd_test_write(cur, sku: str):
    """Перевірка прав на запис БЕЗ фактичної зміни даних.

    Надсилаємо той самий group_id, який у товару вже стоїть: якщо прав немає,
    прийде 403, якщо є — 200, а дані лишаться незмінними. Частковий update
    у Prom оновлює тільки передані поля, тож ціна й опис не зачіпаються.
    """
    r = call('GET', f'/products/by_external_id/{sku}', cur)
    if r.status_code != 200:
        print(f'Товар {sku} не прочитався: HTTP {r.status_code}')
        return False
    p = r.json().get('product', {})
    gid = (p.get('group') or {}).get('id') if isinstance(p.get('group'), dict) \
        else p.get('group_id')
    print(f"ДО:  {sku} | група {gid} | ціна {p.get('price')} | "
          f"{str(p.get('name'))[:44]}")

    w = call('POST', '/products/edit_by_external_id', cur,
             json=[{'external_id': sku, 'group_id': gid}])
    print(f'POST /products/edit_by_external_id → HTTP {w.status_code}')
    if w.status_code == 403:
        print('   403: токен має права лише на читання — потрібен «Читання і запис»')
        return False
    if w.status_code != 200:
        print('   ', w.text[:300])
        return False
    print('   ', w.text[:200])

    r2 = call('GET', f'/products/by_external_id/{sku}', cur)
    p2 = r2.json().get('product', {})
    gid2 = (p2.get('group') or {}).get('id') if isinstance(p2.get('group'), dict) \
        else p2.get('group_id')
    print(f"ПІСЛЯ: {sku} | група {gid2} | ціна {p2.get('price')}")
    ok = (gid == gid2 and p.get('price') == p2.get('price')
          and p.get('name') == p2.get('name'))
    print('   дані не змінились:', 'так ✓' if ok else 'ЗМІНИЛИСЬ ✗')
    return ok


def cmd_sync(cur, conn):
    """Усі товари кабінету → prom_product_state, пагінація через last_id."""
    ensure_table(cur)
    conn.commit()
    rows, last_id, page = [], None, 0
    while True:
        params = {'limit': PAGE}
        if last_id:
            params['last_id'] = last_id
        r = call('GET', '/products/list', cur, params=params)
        if r.status_code != 200:
            logger.error(f'HTTP {r.status_code}: {r.text[:200]}')
            break
        items = r.json().get('products', [])
        if not items:
            break
        page += 1
        for p in items:
            g = p.get('group') if isinstance(p.get('group'), dict) else {}
            c = p.get('category') if isinstance(p.get('category'), dict) else {}
            rows.append((
                p.get('external_id'), p.get('id'), p.get('name'),
                g.get('id'), g.get('name'),
                str(c.get('id')) if c.get('id') is not None else None,
                c.get('caption'), p.get('price'), p.get('presence'),
                p.get('status'), p.get('quantity_in_stock'),
                p.get('is_variation'), p.get('variation_group_id')))
        last_id = items[-1]['id']
        logger.info(f'сторінка {page}: отримано {len(rows)} товарів')
        time.sleep(PAUSE)

    rows = [r for r in rows if r[0]]
    psycopg2.extras.execute_values(cur, """
        INSERT INTO prom_product_state
          (external_id, prom_id, name, group_id, group_name,
           portal_category_id, portal_category, price, presence, status,
           quantity_in_stock, is_variation, variation_group_id)
        VALUES %s
        ON CONFLICT (external_id) DO UPDATE SET
          prom_id=EXCLUDED.prom_id, name=EXCLUDED.name,
          group_id=EXCLUDED.group_id, group_name=EXCLUDED.group_name,
          portal_category_id=EXCLUDED.portal_category_id,
          portal_category=EXCLUDED.portal_category, price=EXCLUDED.price,
          presence=EXCLUDED.presence, status=EXCLUDED.status,
          quantity_in_stock=EXCLUDED.quantity_in_stock,
          is_variation=EXCLUDED.is_variation,
          variation_group_id=EXCLUDED.variation_group_id,
          fetched_at=NOW()
    """, rows, page_size=500)
    conn.commit()
    logger.success(f'Збережено {len(rows)} товарів у prom_product_state')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--health', action='store_true')
    ap.add_argument('--test-write', metavar='SKU')
    ap.add_argument('--sync', action='store_true')
    a = ap.parse_args()

    if not TOKEN:
        sys.exit('PROM_API_TOKEN не заданий у .env')
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if a.health:
        cmd_health(cur)
    elif a.test_write:
        cmd_test_write(cur, a.test_write)
    elif a.sync:
        if cmd_health(cur):
            cmd_sync(cur, conn)
    else:
        ap.print_help()
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
