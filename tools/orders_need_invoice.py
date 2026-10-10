#!/usr/bin/env python3
"""Окреме нагадування власнику: замовлення з оплатою НА РАХУНОК ПРОДАВЦЯ.

Власник 07.10.2026: «вони запросили в мене реквізити, тому треба окреме мені
нагадування і прохання надіслати рахунок для оплати».

ЧОМУ ОКРЕМЕ ПОВІДОМЛЕННЯ, а не рядок у зведенні. Такі замовлення Rozetka не
відстежує: `payment_paid()` повертає None, бо гроші йдуть власникові напряму
(«Оплата на рахунок продавця», payment_type=no_cash). Ніхто, крім власника, не
може підтвердити оплату, і ніхто, крім нього, не виставить рахунок. У спільному
зведенні такий рядок губиться, а замовлення тим часом стоїть.

Нагадуємо ОДИН раз на замовлення: повтор щодня перетворює сигнал на шум.
Стан — у logs/invoice_notified.json.

    venv/bin/python3 tools/orders_need_invoice.py          # лише показати
    venv/bin/python3 tools/orders_need_invoice.py --notify # і надіслати
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'agents', 'orders'))
from dotenv import load_dotenv                                      # noqa: E402
load_dotenv(os.path.join(BASE, '.env'), override=True)
import requests                                                     # noqa: E402
import rozetka_order_agent as RZ                                    # noqa: E402

STATE = os.path.join(BASE, 'logs', 'invoice_notified.json')
# Статуси, у яких замовлення ще живе й рахунок доречний. 26 — саме той
# «нестандартний», у якому 07.10 прийшло замовлення Стеценко.
OPEN_STATUSES = (1, 2, 26, 61)


def tg(text):
    tok = os.getenv('TG_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
    chat = os.getenv('TG_CHAT_ID') or os.getenv('TELEGRAM_ADMIN_ID')
    if not (tok and chat):
        return False
    r = requests.post(f'https://api.telegram.org/bot{tok}/sendMessage', timeout=30,
                      data={'chat_id': chat, 'text': text, 'parse_mode': 'HTML'})
    return bool(r.json().get('ok'))


def load():
    try:
        with open(STATE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(d):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def find():
    out = []
    for st in OPEN_STATUSES:
        try:
            rows = RZ.get_orders_by_status(st)
        except Exception:
            continue
        for o in rows:
            d = RZ.get_order_details(int(o['id'])) or {}
            pay = d.get('payment') or {}
            name = (pay.get('payment_method_name') or '')
            # Ознака саме «на рахунок продавця». Перевіряємо назву методу, а
            # не payment_type: no_cash буває і в інших способів.
            if 'рахунок продавця' not in name.lower():
                continue
            dl = d.get('delivery') or {}
            out.append({
                'id': str(o['id']), 'статус': st, 'сума': d.get('amount'),
                'спосіб': name,
                'покупець': f"{dl.get('recipient_last_name') or ''} "
                            f"{dl.get('recipient_first_name') or ''}".strip(),
                'телефон': dl.get('recipient_phone') or d.get('user_phone'),
                'ттн': d.get('ttn') or RZ._ttn_of(d) or '',
            })
    return out


def main(notify):
    rows = find()
    done = load()
    fresh = [r for r in rows if r['id'] not in done]
    for r in rows:
        print(f"#{r['id']} ст.{r['статус']} {r['сума']} ₴ · {r['спосіб']} · "
              f"{r['покупець']} · ТТН {r['ттн'] or '—'}"
              + ('' if r['id'] not in done else '  (уже нагадували)'))
    if not rows:
        print('замовлень з оплатою на рахунок продавця немає')
        return 0
    if not fresh:
        print('\nнових немає — нагадування не надсилаю')
        return 0
    for r in fresh:
        msg = ('💳 <b>ПОТРІБЕН РАХУНОК</b>\n'
               f"Замовлення Rozetka <b>{r['id']}</b> на <b>{r['сума']} ₴</b>\n"
               f"Оплата: {r['спосіб']} — гроші йдуть вам напряму, "
               'Rozetka цю оплату НЕ відстежує.\n'
               f"Покупець: {r['покупець']}\n"
               f"Телефон: {r['телефон'] or '—'}\n"
               f"ТТН: {r['ттн'] or 'ще немає'}\n\n"
               '❗ Надішліть покупцю реквізити та рахунок на оплату.\n'
               'Підтвердити надходження коштів можете лише ви — Rozetka '
               'цього не бачить.\n\n'
               '➡️ Коли гроші прийдуть, змініть статус замовлення в кабінеті '
               'Rozetka (зі статусу 26). Агент одразу підхопить його сам і '
               'надішле постачальнику з приміткою «без післяплати».')
        if notify and tg(msg):
            done[r['id']] = True
        print('\n' + msg.replace('<b>', '').replace('</b>', ''))
    if notify:
        save(done)
        print(f'\nнадіслано нагадувань: {len(fresh)}')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--notify', action='store_true')
    sys.exit(main(ap.parse_args().notify))
