#!/usr/bin/env python3
"""Пошук фотографій, що показують не цей товар, а всю лінійку.

Зауваження Ольги, раунд 1 п.6 і раунд 2 п.4: «в товарах не повинно бути
асортименту… фото має бути тільки що стосується даного конкретного товару».
Її приклад — знімок pjur AQUA, де в кадрі чотири пляшки 500/250/100/30 мл;
цей самий файл стоїть у картках усіх чотирьох фасовок.

Маркер детермінований і не потребує розпізнавання зображень: якщо ОДНЕ
зображення (той самий перцептивний хеш) використане в картках, у яких
РІЗНЕ значення характеристики, воно не може бути правдивим для всіх.

Що вважаємо конфліктом, а що ні:
  Об'єм  — конфлікт. Пляшка 30 мл і 500 мл виглядають по-різному, спільне
           фото означає знімок лінійки.
  Колір  — конфлікт. Чорна й червона білизна не можуть мати один кадр.
  Розмір — НЕ конфлікт. Сукня S і L на фото однакові, і спільний знімок
           тут норма: 15 313 карток, жодна з них не є дефектом.

Пише в rozetka_photo_conflicts; генератор читає таблицю й прибирає ці URL,
лишаючи щонайменше одне фото на картку.

Запуск:
    python3 tools/rozetka_photo_conflicts.py --param "Об'єм"
    python3 tools/rozetka_photo_conflicts.py --param Колір --dry-run
    python3 tools/rozetka_photo_conflicts.py --report
"""
import argparse
import collections
import os
import sys
import xml.etree.ElementTree as ET

import psycopg2.extras

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

FEED = os.path.join(BASE_DIR, 'output', 'noire_rozetka.xml')


def ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS rozetka_photo_conflicts (
        sku        TEXT NOT NULL,
        url        TEXT NOT NULL,
        param      TEXT NOT NULL,
        values_seen TEXT,
        found_at   TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (sku, url, param))""")


def find(cur, param: str):
    cur.execute('SELECT url, phash FROM noire_photo_audit WHERE phash IS NOT NULL')
    ph_of = {r['url']: r['phash'] for r in cur.fetchall()}

    offers = ET.parse(FEED).getroot().findall('.//offer')
    prm, pics = {}, {}
    for o in offers:
        sku = o.get('id')
        prm[sku] = {p.get('name'): (p.text or '') for p in o.findall('param')}
        pics[sku] = [p.text for p in o.findall('picture') if p.text]

    by_hash = collections.defaultdict(set)
    for sku, urls in pics.items():
        for u in urls:
            if u in ph_of:
                by_hash[ph_of[u]].add(sku)

    out = []
    for ph, skus in by_hash.items():
        vals = {prm[s].get(param) for s in skus if prm.get(s, {}).get(param)}
        vals.discard(None)
        if len(vals) < 2:
            continue
        seen = ', '.join(sorted(vals)[:6])
        for sku in skus:
            for u in pics[sku]:
                if ph_of.get(u) == ph:
                    out.append((sku, u, param, seen))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--param', default="Об'єм")
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()

    if a.report:
        cur.execute("""SELECT param, count(*) n, count(DISTINCT sku) skus
                       FROM rozetka_photo_conflicts GROUP BY param""")
        for r in cur.fetchall():
            print(f"   {r['param']:8} {r['n']:5} фото на {r['skus']:5} картках")
        return

    rows = find(cur, a.param)
    cards = {r[0] for r in rows}
    print(f'{a.param}: конфліктних фото {len(rows)} на {len(cards)} картках')

    # запобіжник: картка не має лишитись без жодного фото
    offers = ET.parse(FEED).getroot().findall('.//offer')
    pics = {o.get('id'): [p.text for p in o.findall('picture') if p.text]
            for o in offers}
    drop = collections.Counter(r[0] for r in rows)
    empty = [s for s in cards if drop[s] >= len(pics.get(s, []))]
    if empty:
        print(f'   УВАГА: {len(empty)} карток лишились би без фото — '
              f'їх пропускаємо: {" ".join(sorted(empty)[:10])}')
        rows = [r for r in rows if r[0] not in set(empty)]

    for sku, url, param, seen in rows[:8]:
        print(f'   {sku:10} {seen[:44]}')
    if a.dry_run:
        print('\n--dry-run: у базу не записано')
        return
    psycopg2.extras.execute_values(cur, """
        INSERT INTO rozetka_photo_conflicts (sku, url, param, values_seen)
        VALUES %s ON CONFLICT DO NOTHING""", rows)
    conn.commit()
    print(f'\nзаписано: {len(rows)}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
