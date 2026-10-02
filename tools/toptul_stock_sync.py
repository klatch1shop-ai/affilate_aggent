#!/usr/bin/env python3
"""Синхронізація наявності й цін TOPTUL у фіді Rozetka.

Навіщо: 02.10.2026 прийшло замовлення на товар, якого в постачальника немає.
Причина — опублікований `toptul_rozetka.xml` не оновлювався з 11.09: у crontab
сервера для TOPTUL був лише звіт по ТТН о 21:00, а синхронізації наявності,
на відміну від NOIRE, не було взагалі. На момент виявлення: 90 позицій
продавались за відсутності в постачальника, 132 були вимкнені дарма,
11 цін розійшлись.

Чому НЕ перегенерація фіду: вміст фіду після модерації заморожений — міняти
можна лише ціну й наявність (правило для всіх наших фідів Rozetka). Тому тут
хірургічна правка опублікованого XML: атрибут `available`, `stock_quantity`
і `price`. Решта тегів не чіпається взагалі, файл не перебудовується.

`stock_quantity` 0 при `available="false"` — штатне позначення Rozetka, а не
помилка валідатора.

    venv/bin/python3 tools/toptul_stock_sync.py --dry
    venv/bin/python3 tools/toptul_stock_sync.py --write
    venv/bin/python3 tools/toptul_stock_sync.py --write --publish
"""
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

FEED = os.path.join(BASE, 'output', 'toptul_rozetka.xml')
GH_FILE = 'toptul_rozetka.xml'
# Основа для правки — ОПУБЛІКОВАНИЙ файл, а не наш output/. Вони розійшлись:
# 02.10 в репозиторії лежала версія від 11.09 на 5988 офферів, а в output/ —
# від 02.09 на 5783. Якби синхронізація взяла output/, публікація відкотила б
# фід назад і зняла з продажу 205 позицій.
PUBLISHED = os.path.join(os.path.expanduser('~'), 'noire-feed', GH_FILE)
RAW_URL = ('https://raw.githubusercontent.com/klatch1shop-ai/noire-feed/'
           'main/' + GH_FILE)
SRC_URL = os.getenv('TOPTUL_FEED_URL')

# Запобіжник того ж роду, що й у toptul_rozetka_generator: цей інструмент не
# має права писати у фіди NOIRE — під ними картки на модерації.
FORBIDDEN = ('noire', 'dropoffice')


def _safe(path):
    name = os.path.basename(path).lower()
    if any(name.startswith(p) for p in FORBIDDEN):
        raise SystemExit(f'ВІДМОВА: {name} — чужий фід, його чіпати не можна')
    return path


def supplier_state():
    """id → (у наявності, ціна) з живого фіду постачальника."""
    r = requests.get(SRC_URL, timeout=600)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = {}
    for o in root.iter('offer'):
        p = o.findtext('price')
        try:
            price = float(p) if p else None
        except ValueError:
            price = None
        out[o.get('id')] = (o.get('available', 'true').lower() != 'false', price)
    return out


def sync(write=False, publish=False):
    src = supplier_state()
    print(f'постачальник: {len(src)} офферів', flush=True)

    base = PUBLISHED if os.path.exists(PUBLISHED) else FEED
    print(f'основа: {base}', flush=True)
    tree = ET.parse(base)
    offers = list(tree.getroot().iter('offer'))
    print(f'наш фід: {len(offers)} офферів', flush=True)

    off_on = off_off = price_fix = missing = 0
    for o in offers:
        st = src.get(o.get('id'))
        if st is None:
            missing += 1
            continue
        avail, price = st
        cur = o.get('available', 'true').lower() != 'false'
        if cur != avail:
            o.set('available', 'true' if avail else 'false')
            if avail:
                off_on += 1
            else:
                off_off += 1
            sq = o.find('stock_quantity')
            if sq is not None:
                sq.text = '1' if avail else '0'
        pe = o.find('price')
        if pe is not None and price and abs(float(pe.text or 0) - price) > 0.01:
            pe.text = f'{price:.2f}'.rstrip('0').rstrip('.')
            price_fix += 1

    print(f'\nзнято з продажу (нема в постачальника): {off_off}')
    print(f'повернуто у продаж (зʼявились):          {off_on}')
    print(f'виправлено цін:                          {price_fix}')
    print(f'немає у фіді постачальника взагалі:      {missing}')

    if not write:
        print('\n--dry: нічого не записано')
        return
    _safe(FEED)
    tree.write(FEED, encoding='utf-8', xml_declaration=True)
    print(f'\nзаписано: {FEED} ({os.path.getsize(FEED)} байт)')
    ET.parse(FEED)
    print('XML валідний')

    if publish:
        from tools.noire_stock_sync import publish_github
        res = publish_github(FEED, GH_FILE, RAW_URL)
        print('публікація:', res)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--publish', action='store_true')
    a = ap.parse_args()
    if not SRC_URL:
        sys.exit('немає TOPTUL_FEED_URL у .env')
    sync(write=a.write, publish=a.publish)
