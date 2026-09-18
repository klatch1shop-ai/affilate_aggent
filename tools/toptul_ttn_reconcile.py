#!/usr/bin/env python3
"""Звірка ТТН TOPTUL о 21:00 (cron). Власник 18.09.2026: «о 21:00 перевіряло, чи всі ТТН
додались — у день замовлення відправляють усе, що надіслано постачальнику до 14:00».

Тривоги й знайдені ТТН — у Telegram одразу; «усе гаразд» — у щоденне зведення
(shared/utils/tg_digest.py, рішення власника 13.09 про тишу в Telegram).

    venv/bin/python3 tools/toptul_ttn_reconcile.py            # лише звіт
    venv/bin/python3 tools/toptul_ttn_reconcile.py --write    # підтверджені ТТН → Rozetka (статус 61)
"""
import argparse
import os
import sys

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'agents', 'orders'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE, '.env'))
import toptul_supplier as TS  # noqa: E402


def tg(text):
    tok = os.getenv('TG_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
    chat = os.getenv('TG_CHAT_ID') or os.getenv('TELEGRAM_ADMIN_ID')
    r = requests.post(f'https://api.telegram.org/bot{tok}/sendMessage', timeout=30,
                      data={'chat_id': chat, 'text': text, 'parse_mode': 'HTML'})
    return r.ok


def stale_rozetka(hours=20):
    """Усі підтверджені замовлення Rozetka без ТТН довше `hours` — будь-який постачальник.

    18.09.2026: два замовлення Carvol від 17.09 добу стояли підтвердженими без ТТН.
    Carvol надіслав номери ТЕКСТОМ, диспетчер приймає від нього лише PDF і
    проігнорував їх — ніхто не помітив. Ця перевірка ловить наслідок, хоч би
    яка була причина.
    """
    import datetime as dt
    import rozetka_order_agent as RZ
    noire = RZ.get_noire_articles() or set()
    toptul = TS.toptul_articles() or set()
    out = []
    for st in (2, 26):
        for o in RZ.get_orders_by_status(st) or []:
            d = RZ.get_order_details(o['id']) or o
            if RZ._ttn_of(d):
                continue
            created = dt.datetime.fromisoformat(str(d.get('created'))[:19])
            age = (dt.datetime.now() - created).total_seconds() / 3600
            if age < hours:
                continue
            arts = [str((p.get('item') or {}).get('article') or '') for p in d.get('purchases') or []]
            sup = ('NOIRE' if all(a in noire for a in arts) else 'TOPTUL' if all(a in toptul for a in arts)
                   else 'Carvol' if arts else '?')
            out.append(f"🚨 #{o['id']} ({sup}) — підтверджено {created:%d.%m %H:%M}, ТТН немає вже {age:.0f} год")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--no-tg', action='store_true')
    a = ap.parse_args()
    TS.init_table()
    report = TS.reconcile(write_ttn=a.write)
    stale = stale_rozetka()
    if stale:
        report += '\n\n<b>Rozetka: підтверджені без ТТН</b>\n' + '\n'.join(stale)
    print(report)
    if a.no_tg:
        return
    urgent = any(m in report for m in ('🚨', '❓', '✅ #', 'НЕ записано'))
    if urgent:
        print('Telegram:', 'надіслано' if tg(report) else 'НЕ надіслано')
    else:
        from shared.utils import tg_digest
        tg_digest.add('toptul_ttn', report.replace('<b>', '').replace('</b>', ''))
        print('у щоденне зведення')


if __name__ == '__main__':
    main()
