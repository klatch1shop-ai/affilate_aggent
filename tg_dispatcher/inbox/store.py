"""Збереження повідомлень, прив'язок Telegram та курсорів у SQLite."""

import sqlite3
from dataclasses import astuple
from datetime import datetime, timedelta

from .model import BuyerMessage


class InboxStore:
    def __init__(self, path: str = ':memory:'):
        self._db = sqlite3.connect(path)
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS messages (
                marketplace TEXT NOT NULL, chat_id TEXT NOT NULL,
                msg_id TEXT NOT NULL, direction TEXT NOT NULL, body TEXT NOT NULL,
                created TEXT NOT NULL, buyer_name TEXT NOT NULL, subject TEXT NOT NULL,
                order_id TEXT, item_id TEXT, has_files INTEGER NOT NULL,
                UNIQUE (marketplace, msg_id)
            );
            CREATE INDEX IF NOT EXISTS messages_chat_time
                ON messages (marketplace, chat_id, created);
            CREATE TABLE IF NOT EXISTS tg_links (
                tg_message_id INTEGER PRIMARY KEY, marketplace TEXT NOT NULL,
                chat_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cursors (
                marketplace TEXT PRIMARY KEY, value TEXT NOT NULL
            );
        ''')

    def add_new(self, messages: list[BuyerMessage]) -> list[BuyerMessage]:
        """Атомарно записати набір і повернути лише нові повідомлення."""
        added = []
        with self._db:
            for msg in messages:
                values = list(astuple(msg))
                values[5] = msg.created.isoformat(timespec='microseconds')
                inserted = self._db.execute('''
                    INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (marketplace, msg_id) DO NOTHING
                ''', values)
                if inserted.rowcount:
                    added.append(msg)
        return sorted(added, key=lambda msg: msg.created)

    def link_tg(self, tg_message_id: int, marketplace: str, chat_id: str) -> None:
        with self._db:
            self._db.execute('''
                INSERT INTO tg_links VALUES (?, ?, ?)
                ON CONFLICT (tg_message_id) DO UPDATE SET
                    marketplace=excluded.marketplace, chat_id=excluded.chat_id
            ''', (tg_message_id, marketplace, chat_id))

    def chat_for_tg(self, tg_message_id: int) -> tuple[str, str] | None:
        return self._db.execute(
            'SELECT marketplace, chat_id FROM tg_links WHERE tg_message_id=?',
            (tg_message_id,)).fetchone()

    def get_cursor(self, marketplace: str) -> str | None:
        row = self._db.execute('SELECT value FROM cursors WHERE marketplace=?',
                               (marketplace,)).fetchone()
        return row[0] if row else None

    def set_cursor(self, marketplace: str, value: str) -> None:
        with self._db:
            self._db.execute('''
                INSERT INTO cursors VALUES (?, ?)
                ON CONFLICT (marketplace) DO UPDATE SET value=excluded.value
            ''', (marketplace, value))

    def unanswered(self, now: datetime, older_than_min: int,
                   max_age_min: int | None = None) -> list[dict]:
        """Знайти чати, останнє повідомлення яких очікує відповіді."""
        if now.utcoffset() is None:
            raise ValueError('Поточний час має містити часову зону')
        rows = self._db.execute('''
            SELECT marketplace, chat_id, buyer_name, created FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY marketplace, chat_id ORDER BY created DESC, rowid DESC
                ) AS position FROM messages
            ) WHERE position=1 AND direction='in'
            ORDER BY created
        ''')
        result = []
        for marketplace, chat_id, buyer_name, created in rows:
            waiting = now - datetime.fromisoformat(created)
            waiting_min = int(waiting.total_seconds() // 60)
            if max_age_min is not None and waiting_min > max_age_min:
                continue
            if waiting > timedelta(minutes=older_than_min):
                result.append(dict(marketplace=marketplace, chat_id=chat_id,
                                   buyer_name=buyer_name,
                                   waiting_min=waiting_min))
        return result
