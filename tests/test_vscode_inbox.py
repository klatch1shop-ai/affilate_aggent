"""Скринька «власник → Claude», 26.09.2026: бот лише ЗАПИСУЄ команду, нічого
не виконує. Тести стережуть саме цю межу — розбір префікса й чесне зберігання.
"""
import json
from datetime import datetime, timezone

import pytest

from helper import vscode_inbox as inbox


@pytest.mark.parametrize('text,expected', [
    ('VSCODE перевір ціни', 'перевір ціни'),
    ('vscode перевір ціни', 'перевір ціни'),
    ('VSCode  подвійний пробіл', 'подвійний пробіл'),
    ('   VSCODE з відступом на початку', 'з відступом на початку'),
    ('VSCODE\nтекст з нового рядка', 'текст з нового рядка'),
])
def test_parse_accepts_prefix(text, expected):
    assert inbox.parse(text) == expected


@pytest.mark.parametrize('text', [
    'VSCODE',                      # сам префікс — не команда
    'VSCODE   ',                   # префікс і порожнеча
    'VSCODEперевір',               # без пробілу — це інше слово
    'подивись у VSCODE щось',      # префікс не на початку
    'нові замовлення',             # звичайна команда бота
    '',
    None,
    123,
])
def test_parse_rejects_everything_else(text):
    assert inbox.parse(text) is None


def test_append_and_unread_roundtrip(tmp_path):
    path = tmp_path / 'sub' / 'inbox.jsonl'      # теку створює сам
    now = datetime(2026, 9, 26, 10, 30, tzinfo=timezone.utc)
    entry = inbox.append(str(path), 'перевір Prom', from_id=42, now=now)
    assert entry['text'] == 'перевір Prom' and entry['read'] is False
    assert entry['ts'] == '2026-09-26 10:30:00' and entry['from_id'] == 42

    got = inbox.unread(str(path))
    assert [e['text'] for e in got] == ['перевір Prom']


def test_unread_missing_file_is_empty_not_error(tmp_path):
    assert inbox.unread(str(tmp_path / 'nope.jsonl')) == []
    assert inbox.mark_read(str(tmp_path / 'nope.jsonl')) == 0


def test_mark_read_hides_old_but_keeps_new(tmp_path):
    path = str(tmp_path / 'inbox.jsonl')
    inbox.append(path, 'перше')
    inbox.append(path, 'друге')
    assert inbox.mark_read(path) == 2
    assert inbox.unread(path) == []

    inbox.append(path, 'третє')
    assert [e['text'] for e in inbox.unread(path)] == ['третє']
    # прочитані не губляться — історія лишається у файлі
    assert len(open(path, encoding='utf-8').read().strip().splitlines()) == 3


def test_broken_line_does_not_hide_rest(tmp_path):
    path = tmp_path / 'inbox.jsonl'
    path.write_text('це не json\n' + json.dumps({'text': 'живе', 'read': False},
                                                ensure_ascii=False) + '\n',
                    encoding='utf-8')
    assert [e['text'] for e in inbox.unread(str(path))] == ['живе']
