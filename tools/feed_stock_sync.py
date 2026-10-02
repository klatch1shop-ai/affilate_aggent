#!/usr/bin/env python3
"""Наявність і ціни в опублікованих фідах маркетплейсів — для всіх постачальників.

ПРАВИЛО (власник, 02.10.2026): щойно фід відправлено на валідацію, ціна й
наявність у ньому мають бути РЕАЛЬНІ й ОНОВЛЮВАТИСЬ. Фід, який ніхто не
оновлює, продає те, чого немає.

Звідки правило: 02.10 прийшло замовлення на Rozetka на товар, якого в
постачальника немає. `toptul_rozetka.xml` не оновлювався з 11.09, бо для
TOPTUL у crontab була лише звірка ТТН. Замір на момент виявлення:
  TOPTUL     — 90 позицій продавались без наявності, 132 вимкнені дарма,
               11 цін розійшлись;
  dropoffice — та сама дірка, фід від 15.09: 40 і 9.
NOIRE цього не мав, бо для нього синхронізація була написана окремо.

Чому правка, а не перегенерація: вміст фіду після подачі на модерацію
заморожений — міняти можна лише ціну й наявність. Тому тут хірургічна правка
`available`, `stock_quantity` і `price`; решта тегів не чіпається.

Основа для правки — ОПУБЛІКОВАНИЙ файл із репозиторію фідів, а не наш
`output/`. Вони розходяться: 02.10 в репозиторії лежав TOPTUL від 11.09 на
5988 офферів, а в `output/` — від 02.09 на 5783. Взяти `output/` означало б
відкотити фід і зняти з продажу 205 позицій.

`stock_quantity` 0 при `available="false"` — штатне позначення Rozetka.

    venv/bin/python3 tools/feed_stock_sync.py --profile toptul --dry
    venv/bin/python3 tools/feed_stock_sync.py --profile dropoffice --write --publish
    venv/bin/python3 tools/feed_stock_sync.py --audit        # розбіг по всіх
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

REPO = os.path.join(os.path.expanduser('~'), 'noire-feed')
RAW = 'https://raw.githubusercontent.com/klatch1shop-ai/noire-feed/main/'

PROFILES = {
    'toptul': {
        'gh_file': 'toptul_rozetka.xml',
        'source': os.getenv('TOPTUL_FEED_URL'),
        # ціна у фіді постачальника вже наша відпускна
        'price_rules': None,
    },
    'dropoffice': {
        'gh_file': 'dropoffice_rozetka.xml',
        'source': ('https://kabinet.dropoffice.com.ua/data/'
                   '7584005b2498aebb572fa6a91bfda027.xml'),
        # ціна = РРЦ постачальника × множник із data/price_rules.json
        # (рішення власника 12.09 за заміром конкурентів: ×1.10 типово,
        # ×1.00 у п'яти категоріях). Множник ніколи не менший за 1.0 —
        # нижче роздрібної ціни постачальника ми не опускаємось.
        'price_rules': 'dropoffice',
    },
}


def load_rules(name):
    if not name:
        return None
    return json.load(open(os.path.join(BASE, 'data', 'price_rules.json'),
                          encoding='utf-8'))[name]


def supplier_state(url):
    r = requests.get(url, timeout=600)
    r.raise_for_status()
    out = {}
    for o in ET.fromstring(r.content).iter('offer'):
        p = o.findtext('price')
        try:
            price = float(p) if p else None
        except ValueError:
            price = None
        out[o.get('id')] = (o.get('available', 'true').lower() != 'false', price)
    return out


def target_price(raw_price, category, rules):
    if raw_price is None:
        return None
    if not rules:
        return raw_price
    mult = rules['category'].get(str(category), rules['default'])
    if mult < 1.0:                     # запобіжник проти демпінгу
        mult = 1.0
    return round(raw_price * mult, 2)


def sync(profile, write=False, publish=False):
    cfg = PROFILES[profile]
    if not cfg['source']:
        sys.exit(f'{profile}: немає адреси фіду постачальника')
    rules = load_rules(cfg['price_rules'])
    src = supplier_state(cfg['source'])
    base = os.path.join(REPO, cfg['gh_file'])
    if not os.path.exists(base):
        sys.exit(f'немає опублікованого фіду {base}')
    print(f'{profile}: постачальник {len(src)} · основа {base}', flush=True)

    tree = ET.parse(base)
    offers = list(tree.getroot().iter('offer'))
    on = off = price_fix = missing = 0
    for o in offers:
        st = src.get(o.get('id'))
        if st is None:
            # Зник із фіду постачальника = знятий з продажу (рішення власника
            # 02.10). Раніше такі позиції лишались у продажу й давали
            # замовлення, які нема чим виконати.
            missing += 1
            if o.get('available', 'true').lower() != 'false':
                o.set('available', 'false')
                off += 1
                sq = o.find('stock_quantity')
                if sq is not None:
                    sq.text = '0'
            continue
        avail, raw = st
        if (o.get('available', 'true').lower() != 'false') != avail:
            o.set('available', 'true' if avail else 'false')
            on, off = (on + 1, off) if avail else (on, off + 1)
            sq = o.find('stock_quantity')
            if sq is not None:
                sq.text = '1' if avail else '0'
        pe = o.find('price')
        want = target_price(raw, o.findtext('categoryId'), rules)
        if pe is not None and want and abs(float(pe.text or 0) - want) > 0.01:
            pe.text = f'{want:.2f}'.rstrip('0').rstrip('.')
            price_fix += 1

    print(f'  офферів у фіді: {len(offers)}')
    print(f'  знято з продажу (нема в постачальника): {off}')
    print(f'  повернуто у продаж:                     {on}')
    print(f'  виправлено цін:                         {price_fix}')
    print(f'  зникли з фіду постачальника (знято):    {missing}')
    if not write:
        print('  --dry: нічого не записано')
        return

    out = os.path.join(BASE, 'output', cfg['gh_file'])
    tree.write(out, encoding='utf-8', xml_declaration=True)
    ET.parse(out)
    print(f'  записано {out} ({os.path.getsize(out)} байт), XML валідний')
    if publish:
        from tools.noire_stock_sync import publish_github
        print('  публікація:', publish_github(out, cfg['gh_file'],
                                              RAW + cfg['gh_file']))


def audit():
    """Розбіг між опублікованим фідом і постачальником — без правок."""
    for name, cfg in PROFILES.items():
        base = os.path.join(REPO, cfg['gh_file'])
        if not cfg['source'] or not os.path.exists(base):
            print(f'{name}: пропущено (немає джерела або фіду)')
            continue
        src = supplier_state(cfg['source'])
        sell_gone = gone_sell = 0
        for o in ET.parse(base).getroot().iter('offer'):
            cur = o.get('available', 'true').lower() != 'false'
            st = src.get(o.get('id'))
            if st is None:
                # зник у постачальника, а ми досі продаємо — та сама біда
                if cur:
                    sell_gone += 1
                continue
            if cur and not st[0]:
                sell_gone += 1
            elif not cur and st[0]:
                gone_sell += 1
        flag = 'УВАГА' if sell_gone else 'ок'
        print(f'{name:<12} продаємо без наявності: {sell_gone:>4} · '
              f'вимкнено дарма: {gone_sell:>4}   [{flag}]')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile', choices=sorted(PROFILES))
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--publish', action='store_true')
    ap.add_argument('--audit', action='store_true')
    a = ap.parse_args()
    if a.audit:
        audit()
    elif a.profile:
        sync(a.profile, write=a.write, publish=a.publish)
    else:
        ap.print_help()
