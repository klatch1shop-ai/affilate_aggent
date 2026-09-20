"""Локальні позначки прочитаних чатів з обмеженим строком дії."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

DEFAULT_HOURS = 24


def _utc(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Час має містити часову зону')
    return value.astimezone(timezone.utc)


class AckStore:
    def __init__(self, path: str = ':memory:'):
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.execute('''CREATE TABLE IF NOT EXISTS acknowledgements (
                marketplace TEXT NOT NULL, chat_id TEXT NOT NULL, last_msg_id TEXT NOT NULL,
                until TEXT NOT NULL, user_id, PRIMARY KEY (marketplace, chat_id))''')

    @staticmethod
    def _record(row):
        record = dict(row)
        record['until'] = datetime.fromisoformat(record['until'])
        return record

    def ack(self, marketplace, chat_id, *, now, last_msg_id, hours=DEFAULT_HOURS, user_id=None):
        until = _utc(now) + timedelta(hours=hours)
        with self._db:
            self._db.execute('''INSERT INTO acknowledgements
                (marketplace, chat_id, last_msg_id, until, user_id) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(marketplace, chat_id) DO UPDATE SET
                last_msg_id = excluded.last_msg_id, until = excluded.until,
                user_id = excluded.user_id''',
                (marketplace, str(chat_id), json.dumps(last_msg_id), until.isoformat(), user_id))
        return {'marketplace': marketplace, 'chat_id': str(chat_id),
                'last_msg_id': last_msg_id, 'until': until, 'user_id': user_id}

    def is_acked(self, marketplace, chat_id, *, now, last_msg_id):
        now = _utc(now)
        row = self._db.execute('''SELECT last_msg_id, until FROM acknowledgements
            WHERE marketplace = ? AND chat_id = ?''', (marketplace, str(chat_id))).fetchone()
        return (row is not None and now < datetime.fromisoformat(row['until'])
                and json.loads(row['last_msg_id']) == last_msg_id)

    def clear(self, marketplace, chat_id):
        with self._db:
            self._db.execute('DELETE FROM acknowledgements WHERE marketplace = ? AND chat_id = ?',
                             (marketplace, str(chat_id)))

    def acked(self, now):
        return [self._record(row) for row in self._db.execute('''
            SELECT marketplace, chat_id, until, user_id FROM acknowledgements
            WHERE until > ? ORDER BY until, marketplace, chat_id''', (_utc(now).isoformat(),))]
