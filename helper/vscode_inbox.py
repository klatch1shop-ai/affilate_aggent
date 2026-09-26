"""Поштова скринька «власник → Claude у VSCode», 26.09.2026.

Власник пише в @NOIRE_helper_Bot: `VSCODE <текст>` — бот **лише записує**
цей текст у файл-скриньку й підтверджує прийом. Нічого не запускається й
не виконується: це пошта, а не пульт. Claude читає файл під час роботи як
звичайний файл і сам вирішує, що робити, — рівно так само, як коли власник
пише у вікні VSCode. Зворотний бік каналу — tools/notify_owner.py.

Формат — JSONL, по рядку на повідомлення: {ts, from_id, text, read}.
"""
import json
import os
from datetime import datetime, timezone

PREFIX = 'VSCODE'


def parse(text):
    """Текст команди, якщо повідомлення починається з `VSCODE` і пробілу, інакше None.

    Регістр не має значення (`vscode`, `VSCode`). Сам префікс без тексту —
    не команда: порожню пошту записувати нема сенсу.
    """
    if not isinstance(text, str):
        return None
    stripped = text.lstrip()
    if len(stripped) <= len(PREFIX):
        return None
    if stripped[:len(PREFIX)].upper() != PREFIX:
        return None
    if not stripped[len(PREFIX)].isspace():
        return None
    body = stripped[len(PREFIX):].strip()
    return body or None


def append(path, text, from_id=None, now=None):
    """Дописує одне повідомлення у скриньку. Повертає записаний рядок як dict."""
    entry = {
        'ts': (now or datetime.now(timezone.utc)).strftime('%Y-%m-%d %H:%M:%S'),
        'from_id': from_id,
        'text': text,
        'read': False,
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return entry


def unread(path):
    """Непрочитані повідомлення. Немає файлу — порожній список, не помилка."""
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:                      # побитий рядок не має ховати решту пошти
            continue
        if not entry.get('read'):
            out.append(entry)
    return out


def mark_read(path):
    """Позначає всю скриньку прочитаною. Повертає, скільки позначив."""
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return 0
    entries, count = [], 0
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not entry.get('read'):
            entry['read'] = True
            count += 1
        entries.append(entry)
    with open(path, 'w', encoding='utf-8') as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return count
