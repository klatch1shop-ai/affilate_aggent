"""Пошта від власника з @NOIRE_helper_Bot — читання з боку Claude/VSCode.

Власник пише боту `VSCODE <текст>`, бот кладе це у скриньку (helper/vscode_inbox.py).
Тут — лише перегляд: жодна команда звідси не виконується автоматично, Claude
читає й вирішує сам. Відповідь назад — tools/notify_owner.py.

    venv/bin/python tools/vscode_mail.py            # непрочитане
    venv/bin/python tools/vscode_mail.py --read     # показати й позначити прочитаним
"""
import argparse
import os
import sys

from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

from helper import vscode_inbox                                     # noqa: E402

DATA = os.getenv('HELPER_DATA_DIR', os.path.join(os.path.expanduser('~'), 'helper_data'))
INBOX = os.getenv('VSCODE_INBOX', os.path.join(DATA, 'vscode_inbox.jsonl'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--read', action='store_true', help='позначити показане прочитаним')
    ap.add_argument('--path', default=INBOX)
    a = ap.parse_args()

    letters = vscode_inbox.unread(a.path)
    if not letters:
        print(f'порожньо ({a.path})')
        return
    for i, letter in enumerate(letters, 1):
        print(f'{i}. [{letter.get("ts")} UTC] {letter.get("text")}')
    if a.read:
        print(f'\nпозначено прочитаним: {vscode_inbox.mark_read(a.path)}')


if __name__ == '__main__':
    main()
