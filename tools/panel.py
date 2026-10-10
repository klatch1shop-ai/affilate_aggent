#!/usr/bin/env python3
"""Мій бік живої панелі: читати дошку й чат, відповідати, вести завдання.

Власник додає ідеї з телефона → я забираю їх звідси на обговорення →
повертаю висновок у чат і міняю стан завдання. Без цього інструменту
дошка була б однобічною.

    venv/bin/python tools/panel.py нове           # що власник додав, а я ще не брав
    venv/bin/python tools/panel.py дошка          # уся дошка
    venv/bin/python tools/panel.py чат            # листування
    venv/bin/python tools/panel.py відповісти "текст"
    venv/bin/python tools/panel.py завдання "назва" --тіло "..." --напрям epicentr
    venv/bin/python tools/panel.py стан 3 "зроблено"
    venv/bin/python tools/panel.py взято 3        # позначити ідею як забрану
"""
import argparse
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from dotenv import load_dotenv                                      # noqa: E402
load_dotenv(os.path.join(BASE, '.env'))

from helper import panel_db as DB                                   # noqa: E402

STATUSES = ('нове', 'в роботі', 'чекає рішення', 'зроблено', 'відкинуто')


def дата(t):
    return time.strftime('%d.%m %H:%M', time.localtime(t))


def show_board(rows):
    if not rows:
        print('  порожньо')
        return
    for r in rows:
        mark = '✓' if r['обговорено'] else ' '
        who = 'власник' if r['author'] == 'власник' else 'claude'
        print(f'  {mark} #{r["id"]:<3} [{r["status"]:14}] {r["kind"]:9} {who:8} '
              f'{дата(r["updated"])}  {r["title"]}')
        if r['body']:
            print(f'        {r["body"][:140]}')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('нове')
    d = sub.add_parser('дошка'); d.add_argument('--стан')
    c = sub.add_parser('чат'); c.add_argument('--скільки', type=int, default=30)
    r = sub.add_parser('відповісти'); r.add_argument('текст')
    t = sub.add_parser('завдання')
    t.add_argument('назва'); t.add_argument('--тіло', default='')
    t.add_argument('--напрям', default=''); t.add_argument('--вид', default='завдання')
    s = sub.add_parser('стан'); s.add_argument('id', type=int); s.add_argument('новий')
    b = sub.add_parser('взято'); b.add_argument('id', type=int)
    a = ap.parse_args()

    if a.cmd == 'нове':
        rows = DB.board_new_for_claude()
        unread = DB.chat_unread('власник')
        # Останні 10 — завжди перед очима. Прохання власника 10.10: без
        # попередніх реплік відповідь виходить відірваною від розмови.
        print('ОСТАННІ 10 РЕПЛІК:')
        for m in DB.chat_tail(10):
            хто = 'Claude ' if m['role'] == 'claude' else 'власник'
            print(f'  [{дата(m["created"])}] {хто} {m["text"][:150]}')
        print(f'\nНОВІ ІДЕЇ ВЛАСНИКА ({len(rows)}):')
        show_board(rows)
        print(f'\nНЕПРОЧИТАНІ ПОВІДОМЛЕННЯ ({len(unread)}):')
        for m in unread:
            print(f'  #{m["id"]} {дата(m["created"])}  {m["text"]}')
        if unread:
            DB.chat_mark_read([m['id'] for m in unread])
            print('  (позначено прочитаними)')

    elif a.cmd == 'дошка':
        show_board(DB.board_list(status=a.стан))

    elif a.cmd == 'чат':
        for m in DB.chat_tail(a.скільки):
            хто = 'Claude' if m['role'] == 'claude' else 'власник'
            print(f'  [{дата(m["created"])}] {хто:8} {m["text"]}')

    elif a.cmd == 'відповісти':
        i = DB.chat_add('claude', a.текст)
        # У помічника не дублюємо — рішення власника 10.10: взаємодію
        # відпрацьовуємо через веб. Увімкнути назад: PANEL_TG_ECHO=1.
        print('контекст (останні 10):')
        for m in DB.chat_tail(10):
            хто = 'Claude ' if m['role'] == 'claude' else 'власник'
            print(f'  [{дата(m["created"])}] {хто} {m["text"][:110]}')
        if os.getenv('PANEL_TG_ECHO', '0') == '1':
            try:
                from tools.notify_owner import notify
                notify(f'💬 Відповідь у панелі:\n{a.текст[:900]}')
            except Exception:
                pass
        print(f'надіслано (#{i}) — видно в панелі')

    elif a.cmd == 'завдання':
        i = DB.board_add(a.вид, a.назва, a.тіло, author='claude', напрям=a.напрям)
        print(f'додано #{i}')

    elif a.cmd == 'стан':
        if a.новий not in STATUSES:
            sys.exit(f'стан має бути одним із: {", ".join(STATUSES)}')
        print('оновлено' if DB.board_update(a.id, status=a.новий) else 'не знайдено')

    elif a.cmd == 'взято':
        print('позначено' if DB.board_update(a.id, обговорено=1) else 'не знайдено')


if __name__ == '__main__':
    main()
