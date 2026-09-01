#!/usr/bin/env python3
"""Заморожування опублікованих карток Rozetka.

Після модерації картку змінювати не можна: правити дозволено лише ціну та
залишок. Наш фід перезбирається з бази щогодини, тож будь-яка зміна в
sexopt_products чи sexopt_extracted_params — оновлення від постачальника,
допрогін EasyToys-скрейпера, нове правило в генераторі — мовчки переписала б
назву, опис, фото чи характеристики вже опублікованої картки.

Знімок робиться З ОПУБЛІКОВАНОГО XML, а не з бази: заморозити треба саме те,
що побачила Rozetka. І тільки після успішного push — інакше зафіксували б
картку, якої на сайті ще немає.

Розморожування свідоме й точкове: --unfreeze --sku з підтвердженням. Це
означає, що товар піде на повторну модерацію, тому робиться лише коли є
реальна помилка в опублікованій картці.

Запуск:
    # після успішної публікації (викликається з noire_stock_sync.py)
    noire_freeze_snapshot.py --from-feed output/noire_rozetka.xml

    noire_freeze_snapshot.py --status
    noire_freeze_snapshot.py --diff --sku SO7368     # що змінилось з моменту
    noire_freeze_snapshot.py --unfreeze --sku SO7368 --yes
"""
import argparse
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET

import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

FEED = os.path.join(BASE_DIR, 'output', 'noire_rozetka.xml')

# Поля, які заморожуються. Ціни та наявності тут свідомо немає — саме вони
# й мають лишатись живими.
FROZEN_FIELDS = ('name', 'description', 'vendor', 'pictures', 'params',
                 'rz_id', 'category_name')


def ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rozetka_published_snapshot (
            sku           TEXT PRIMARY KEY,
            rz_id         TEXT,
            category_name TEXT,
            name          TEXT NOT NULL,
            description   TEXT,
            vendor        TEXT,
            pictures      JSONB NOT NULL,
            params        JSONB NOT NULL,
            snapshot_hash TEXT NOT NULL,
            published_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def snapshot_hash(rec: dict) -> str:
    """Відбиток замороженого вмісту — щоб бачити розходження без порівняння полів."""
    payload = json.dumps({k: rec[k] for k in FROZEN_FIELDS},
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def parse_feed(path: str) -> dict:
    """Опублікований XML → {sku: заморожувані поля}."""
    root = ET.parse(path).getroot()
    cats = {c.get('id'): (c.get('rz_id'), (c.text or '').strip())
            for c in root.findall('.//category')}
    out = {}
    for o in root.findall('.//offer'):
        rz, cname = cats.get(o.findtext('categoryId'), (None, None))
        out[o.get('id')] = {
            'name': o.findtext('name_ua') or o.findtext('name') or '',
            'description': o.findtext('description_ua') or '',
            'vendor': o.findtext('vendor') or '',
            'pictures': [p.text for p in o.findall('picture') if p.text],
            'params': {p.get('name'): (p.text or '')
                       for p in o.findall('param')},
            'rz_id': rz,
            'category_name': cname,
        }
    return out


def cmd_freeze(conn, cur, path: str, dry: bool):
    if not os.path.exists(path):
        logger.error(f'Фіду {path} немає — заморожувати нічого')
        return
    live = parse_feed(path)
    cur.execute('SELECT sku FROM rozetka_published_snapshot')
    known = {r['sku'] for r in cur.fetchall()}
    fresh = {s: v for s, v in live.items() if s not in known}

    logger.info(f'У фіді {len(live)} карток, уже заморожено {len(known)}, '
                f'нових до заморожування {len(fresh)}')
    if not fresh:
        return
    if dry:
        for sku in list(fresh)[:10]:
            print(f'   {sku}: {fresh[sku]["name"][:60]}')
        print(f'(--dry: нічого не записано, {len(fresh)} чекають)')
        return

    psycopg2.extras.execute_values(cur, """
        INSERT INTO rozetka_published_snapshot
          (sku, rz_id, category_name, name, description, vendor,
           pictures, params, snapshot_hash)
        VALUES %s
        ON CONFLICT (sku) DO NOTHING
    """, [(sku, v['rz_id'], v['category_name'], v['name'], v['description'],
           v['vendor'], psycopg2.extras.Json(v['pictures']),
           psycopg2.extras.Json(v['params']), snapshot_hash(v))
          for sku, v in fresh.items()], page_size=500)
    conn.commit()
    logger.success(f'Заморожено {len(fresh)} нових карток')


def cmd_status(cur):
    cur.execute("""SELECT count(*) n, min(published_at) f, max(published_at) l
                   FROM rozetka_published_snapshot""")
    r = cur.fetchone()
    print(f"Заморожених карток: {r['n']}")
    if r['n']:
        print(f"   перша: {r['f']:%Y-%m-%d %H:%M}   остання: {r['l']:%Y-%m-%d %H:%M}")
    cur.execute("""SELECT category_name, count(*) n
                   FROM rozetka_published_snapshot
                   GROUP BY 1 ORDER BY n DESC""")
    for x in cur.fetchall():
        print(f"   {str(x['category_name'])[:38]:40} {x['n']}")


def cmd_diff(cur, skus: list, path: str):
    """Що змінилося б, якби картку не було заморожено."""
    live = parse_feed(path) if os.path.exists(path) else {}
    cur.execute('SELECT * FROM rozetka_published_snapshot WHERE sku = ANY(%s)',
                (skus,))
    for snap in cur.fetchall():
        cur_v = live.get(snap['sku'])
        print(f"\n═══ {snap['sku']}  заморожено {snap['published_at']:%Y-%m-%d %H:%M}")
        if not cur_v:
            print('   у поточному фіді відсутній')
            continue
        for f in FROZEN_FIELDS:
            a, b = snap[f], cur_v[f]
            if isinstance(a, list):
                a, b = list(a or []), list(b or [])
            if a != b:
                print(f'   ▸ {f}:\n      було : {str(a)[:110]}\n      стало: {str(b)[:110]}')


def cmd_unfreeze(conn, cur, skus: list, yes: bool):
    cur.execute('SELECT sku, name FROM rozetka_published_snapshot '
                'WHERE sku = ANY(%s)', (skus,))
    rows = cur.fetchall()
    if not rows:
        print('Заморожених карток за цими SKU немає.')
        return
    print(f'До розморожування: {len(rows)}')
    for r in rows:
        print(f"   {r['sku']:10} {r['name'][:64]}")
    print('\nПісля розморожування картка при наступній перегенерації візьме '
          'поточні дані з бази.')
    print('Rozetka може відправити змінений товар на ПОВТОРНУ МОДЕРАЦІЮ.')
    if not yes:
        print('\nЯкщо це свідома дія — повтори з --yes')
        return
    cur.execute('DELETE FROM rozetka_published_snapshot WHERE sku = ANY(%s)',
                (skus,))
    conn.commit()
    logger.success(f'Розморожено {len(rows)} карток')


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__)
    ap.add_argument('--from-feed', nargs='?', const=FEED,
                    help='заморозити нові картки з опублікованого XML')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--diff', action='store_true')
    ap.add_argument('--unfreeze', action='store_true')
    ap.add_argument('--sku', help='через кому')
    ap.add_argument('--yes', action='store_true', help='підтвердити --unfreeze')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure_table(cur)
    conn.commit()

    skus = [s.strip().upper() for s in (a.sku or '').split(',') if s.strip()]
    if a.unfreeze:
        if not skus:
            ap.error('--unfreeze потребує --sku')
        cmd_unfreeze(conn, cur, skus, a.yes)
    elif a.diff:
        if not skus:
            ap.error('--diff потребує --sku')
        cmd_diff(cur, skus, FEED)
    elif a.status:
        cmd_status(cur)
    elif a.from_feed:
        cmd_freeze(conn, cur, a.from_feed, a.dry)
    else:
        ap.print_help()

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
