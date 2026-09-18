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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--no-tg', action='store_true')
    a = ap.parse_args()
    TS.init_table()
    report = TS.reconcile(write_ttn=a.write)
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
