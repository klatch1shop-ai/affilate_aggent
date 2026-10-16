#!/usr/bin/env python3
"""Видаткові накладні «Гранд Інструменту» з пошти → справжні закупівельні ціни.

НАВІЩО. Прайс-лист постачальника містить лише РРЦ з приміткою
«уточнюйте знижку у менеджера»: колонки «Великий опт» і «Опт безготівка»
порожні. Єдине місце, де видно, скільки ми ЗАПЛАТИЛИ, — видаткові
накладні у листах «Розсилка документів» (файли `Отгрузка_*.XLS`).

Без цих цін будь-який розрахунок маржі — припущення. З ними — факт:
15.10 артикул SK2R1U куплений за 132.44 і проданий за 166.00, а комісія
Rozetka 32.27 і доставка 35 роблять цю угоду збитковою на 33.71.

Пошта відкривається лише на читання. openpyxl на сервері падає
(Illegal instruction), тому .XLS читаємо через xlrd — він і потрібен,
бо формат старий.

    venv/bin/python tools/grand_invoices.py --днів 180
"""
import argparse
import datetime
import email
import email.header
import imaplib
import json
import os
import re
import sys

import xlrd
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
OUT = os.path.join(BASE, 'data', 'grand_purchase_prices.json')
ТЕКА = '/tmp/grand_invoices'


def _заголовок(s):
    return str(email.header.make_header(email.header.decode_header(s or '')))


def завантажити(днів):
    os.makedirs(ТЕКА, exist_ok=True)
    M = imaplib.IMAP4_SSL('imap.gmail.com')
    M.login(os.environ['SMTP_USER'], os.environ['SMTP_PASS'])
    M.select('INBOX', readonly=True)
    since = (datetime.date.today() - datetime.timedelta(days=днів)).strftime('%d-%b-%Y')
    typ, data = M.search(None, 'FROM', '"grandinstrument"', 'SINCE', since)
    файли = []
    for i in data[0].split():
        typ, raw = M.fetch(i, '(BODY.PEEK[])')
        msg = email.message_from_bytes(raw[0][1])
        for part in msg.walk():
            імʼя = _заголовок(part.get_filename())
            if не_накладна(імʼя):
                continue
            шлях = os.path.join(ТЕКА, імʼя)
            if not os.path.exists(шлях):
                with open(шлях, 'wb') as f:
                    f.write(part.get_payload(decode=True))
            файли.append(шлях)
    try:
        M.logout()
    except Exception:
        pass
    return файли


def не_накладна(імʼя):
    return not (імʼя and імʼя.lower().startswith('отгрузка') and
                імʼя.lower().endswith('.xls'))


def розібрати(шлях):
    """[(артикул, ціна, кількість, дата)] з однієї накладної."""
    try:
        wb = xlrd.open_workbook(шлях)
    except Exception as e:
        print(f'  {os.path.basename(шлях)}: {e}', file=sys.stderr)
        return []
    ws = wb.sheet_by_index(0)
    колонки, рядки = {}, []
    for r in range(ws.nrows):
        значення = {c: str(ws.cell_value(r, c)).strip() for c in range(ws.ncols)}
        if 'Артикул' in значення.values() and 'Ціна' in значення.values():
            колонки = {v: c for c, v in значення.items() if v}
            continue
        if not колонки:
            continue
        арт = значення.get(колонки.get('Артикул', -1), '').strip()
        if not арт or арт.lower().startswith('всього'):
            continue
        try:
            ціна = float(значення.get(колонки.get('Ціна', -1), '') or 0)
            к_ть = float(значення.get(колонки.get('Кількість', -1), '') or 0)
        except ValueError:
            continue
        if ціна > 0:
            рядки.append((арт, ціна, к_ть))
    дата = re.search(r'_(\d{8})\.XLS$', шлях, re.I)
    дата = дата.group(1) if дата else ''
    return [(а, ц, к, дата) for а, ц, к in рядки]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--днів', type=int, default=180)
    a = ap.parse_args()
    файли = завантажити(a.днів)
    print(f'накладних знайдено: {len(файли)}')
    ціни = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    нових = 0
    for ф in файли:
        for арт, ціна, к_ть, дата in розібрати(ф):
            зап = ціни.setdefault(арт, {'ціна': ціна, 'дата': дата, 'разів': 0})
            if дата >= зап['дата']:
                зап['ціна'], зап['дата'] = ціна, дата
            зап['разів'] += 1
            нових += 1
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(ціни, f, ensure_ascii=False, indent=1)
    print(f'рядків розібрано: {нових} · унікальних артикулів: {len(ціни)} → {OUT}')


if __name__ == '__main__':
    main()
