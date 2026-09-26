"""Пошта від власника з @NOIRE_helper_Bot — читання з боку Claude/VSCode.

Власник пише боту `VSCODE <текст>`, бот кладе це у скриньку на СЕРВЕРІ
(бот живе на usa1). Тут — лише перегляд: жодна команда звідси не виконується
автоматично, Claude читає й вирішує сам. Відповідь назад — tools/notify_owner.py.

Читання віддалене й лише на читання (`ssh … cat`): позначку «прочитано»
тримаємо локальним курсором, щоб нічого не писати на робочий сервер.

    venv/bin/python tools/vscode_mail.py            # нове з останнього разу
    venv/bin/python tools/vscode_mail.py --read     # показати й зсунути курсор
    venv/bin/python tools/vscode_mail.py --all      # усе листування
"""
import argparse
import os
import subprocess
import sys

from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

from helper import vscode_inbox                                     # noqa: E402

HOST = os.getenv('VSCODE_INBOX_HOST', 'tek@192.168.3.28')
REMOTE_PATH = os.getenv('VSCODE_INBOX_REMOTE', '/home/tek/helper_data/vscode_inbox.jsonl')
CURSOR = os.path.join(BASE, 'scratchpad', 'vscode_mail_cursor.txt')


def fetch(host, path, timeout=30):
    """Вміст скриньки. Немає файлу (ще ніхто не писав) — порожньо, не помилка."""
    if not host:
        try:
            with open(path, encoding='utf-8') as f:
                return f.read()
        except OSError:
            return ''
    r = subprocess.run(['ssh', '-o', 'BatchMode=yes', host, f'cat {path} 2>/dev/null || true'],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f'ssh {host}: {r.stderr.strip()[:200]}')
    return r.stdout


def read_cursor():
    try:
        with open(CURSOR, encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


def write_cursor(value):
    os.makedirs(os.path.dirname(CURSOR), exist_ok=True)
    with open(CURSOR, 'w', encoding='utf-8') as f:
        f.write(value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--read', action='store_true', help='зсунути курсор на останнє показане')
    ap.add_argument('--all', action='store_true', help='усе листування, не лише нове')
    ap.add_argument('--host', default=HOST, help='порожньо = читати локальний файл')
    ap.add_argument('--path', default=REMOTE_PATH)
    a = ap.parse_args()

    entries = vscode_inbox.parse_lines(fetch(a.host or None, a.path))
    cursor = '' if a.all else read_cursor()
    letters = vscode_inbox.after(entries, cursor)

    if not letters:
        where = f'{a.host}:{a.path}' if a.host else a.path
        print(f'порожньо ({where}, усього в скриньці: {len(entries)})')
        return
    for i, letter in enumerate(letters, 1):
        print(f'{i}. [{letter.get("ts")} UTC] {letter.get("text")}')
    if a.read:
        write_cursor(str(letters[-1].get('ts') or ''))
        print(f'\nкурсор зсунуто на {letters[-1].get("ts")}')


if __name__ == '__main__':
    main()
