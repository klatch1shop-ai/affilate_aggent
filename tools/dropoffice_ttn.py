#!/usr/bin/env python3
"""ТТН dropoffice з таблиці постачальника → у замовлення Rozetka.

ЯК ЦЕ ВЛАШТОВАНО У ПОСТАЧАЛЬНИКА. Таблиця — звичайний .xlsx на Google
Drive, відкритий за посиланням. Ключова колонка «отримувач/ттн» містить
14 цифр накладної і далі ім'я ДРОПШИПЕРА (власника), а не покупця —
накладна оформлена на нього. Номера нашого замовлення в таблиці НЕМАЄ.

ЗВІДСИ ГОЛОВНЕ ОБМЕЖЕННЯ. Зіставляти можна лише за сумою післяплати
(«наложка/предоплата») і датою. Якщо в один день дві накладні на ту саму
суму — кандидатів два, і це йде ЛЮДИНІ, а не вгадується. Та сама
причина, що й у звірці ТТН TOPTUL: помилка тут означає чужу накладну в
чужому замовленні.

    venv/bin/python tools/dropoffice_ttn.py              # показати, нічого не писати
    venv/bin/python tools/dropoffice_ttn.py --write      # внести в Rozetka
"""
import argparse
import csv
import io
import os
import re
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'agents', 'orders'))
from dotenv import load_dotenv                                      # noqa: E402
load_dotenv(os.path.join(BASE, '.env'))

import requests                                                     # noqa: E402

ТАБЛИЦЯ = os.getenv('DROPOFFICE_SHEET_ID', '1cQ_VS_f3444CR8RmYJPA_hoZsBG-iABo')
АРКУШ = os.getenv('DROPOFFICE_SHEET_GID', '124041149')
ТТН = re.compile(r'\b(\d{14})\b')


def рядки():
    """Таблиця постачальника → [{ттн, сума, дата}]. Лише читання."""
    url = (f'https://docs.google.com/spreadsheets/d/{ТАБЛИЦЯ}'
           f'/export?format=csv&gid={АРКУШ}')
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    if 'html' in (r.headers.get('content-type') or ''):
        raise RuntimeError('замість таблиці прийшов HTML — доступ за '
                           'посиланням, схоже, закрили')
    out = []
    for row in csv.DictReader(io.StringIO(r.text)):
        кол = row.get('отримувач/ттн') or ''
        m = ТТН.search(кол)
        if not m:
            continue
        сума = (row.get('наложка/предоплата') or '').replace(',', '.').strip()
        try:
            сума = float(сума)
        except ValueError:
            сума = None
        out.append({'ттн': m.group(1), 'сума': сума,
                    'дата': (row.get('дата') or '').strip(),
                    'імʼя': кол.replace(m.group(1), '').strip()})
    return out


def наші_без_ттн():
    """Замовлення dropoffice, у яких ТТН ще немає."""
    import rozetka_order_agent as RZ
    out = []
    for st in (1, 2, 26, 4):
        try:
            for o in (RZ.get_orders_by_status(st) or []):
                d = RZ.get_order_details(o['id']) or o
                if d.get('ttn') or RZ._ttn_of(d):
                    continue
                if RZ._supplier_of(o['id'], RZ.get_carvol_feed()) != 'dropoffice':
                    continue
                ri = RZ._order_recipient_info(d)
                out.append({'id': o['id'], 'сума': float(ri.get('total') or 0),
                            'клієнт': ri.get('customer'), 'деталі': d})
        except Exception as e:
            print(f'  статус {st}: {type(e).__name__}: {str(e)[:70]}')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true',
                    help='внести знайдені ТТН у Rozetka')
    a = ap.parse_args()
    import rozetka_order_agent as RZ

    таб = рядки()
    наші = наші_без_ттн()
    print(f'у таблиці постачальника: {len(таб)} накладних · '
          f'наших замовлень без ТТН: {len(наші)}')
    if not наші:
        print('нічого зіставляти')
        return

    # ТТН, які вже стоять у наших замовленнях, — щоб не внести двічі.
    зайняті = set()
    for st in (1, 2, 4, 26, 61):
        try:
            for o in (RZ.get_orders_by_status(st) or []):
                d = RZ.get_order_details(o['id']) or o
                t = d.get('ttn') or RZ._ttn_of(d)
                if t:
                    зайняті.add(str(t))
        except Exception:
            pass

    for n in наші:
        канд = [r for r in таб
                if r['ттн'] not in зайняті and r['сума'] == n['сума']]
        if len(канд) == 1:
            r = канд[0]
            print(f"  #{n['id']} {n['сума']:.0f} грн ({n['клієнт']}) → "
                  f"ТТН {r['ттн']} від {r['дата']}")
            if a.write:
                ok = RZ.set_ttn(n['id'], r['ттн'])
                print(f"     {'записано в Rozetka' if ok else 'НЕ записалось — вручну'}")
                if ok:
                    RZ.tg(f"🚚 <b>Rozetka #{n['id']}</b> — ТТН dropoffice "
                          f"<code>{r['ттн']}</code> внесено з таблиці")
        elif not канд:
            print(f"  #{n['id']} {n['сума']:.0f} грн — накладної на цю суму "
                  f"в таблиці немає")
        else:
            print(f"  #{n['id']} {n['сума']:.0f} грн — кандидатів {len(канд)}: "
                  f"{', '.join(c['ттн'] for c in канд)} — НА РОЗГЛЯД ЛЮДИНІ")


if __name__ == '__main__':
    main()
