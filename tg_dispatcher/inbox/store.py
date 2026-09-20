"""Збереження повідомлень, прив'язок Telegram та курсорів у SQLite."""

import sqlite3
from dataclasses import astuple
from datetime import datetime, timedelta, timezone

from tg_dispatcher.privacy import mask_private
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
            CREATE TABLE IF NOT EXISTS reminder_state (
                marketplace TEXT NOT NULL, chat_id TEXT NOT NULL,
                sent_at TEXT NOT NULL, sent_count INTEGER NOT NULL,
                PRIMARY KEY (marketplace, chat_id)
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

    def linked_chats(self) -> set[tuple[str, str]]:
        """Повернути чати, картки яких уже доставлено."""
        return set(self._db.execute('SELECT DISTINCT marketplace, chat_id FROM tg_links'))

    def _last_messages(self, marketplace: str, chat_id: str,
                       limit: int = 3) -> list[BuyerMessage]:
        """Прочитати останні повідомлення чату в часовому порядку."""
        if limit <= 0:
            return []
        rows = self._db.execute('''
            SELECT marketplace, chat_id, msg_id, direction, body, created,
                   buyer_name, subject, order_id, item_id, has_files
            FROM messages WHERE marketplace=? AND chat_id=?
            ORDER BY created DESC, rowid DESC LIMIT ?
        ''', (marketplace, chat_id, limit)).fetchall()
        messages = []
        for row in reversed(rows):
            values = list(row)
            values[5] = datetime.fromisoformat(values[5])
            values[10] = bool(values[10])
            messages.append(BuyerMessage(*values))
        return messages

    def _reminder_state(self, marketplace: str, chat_id: str):
        """Прочитати час і кількість успішних нагадувань."""
        row = self._db.execute('''
            SELECT sent_at, sent_count FROM reminder_state
            WHERE marketplace=? AND chat_id=?
        ''', (marketplace, chat_id)).fetchone()
        return (datetime.fromisoformat(row[0]), row[1]) if row else None

    def _record_reminders(self, items: list[dict], now: datetime) -> None:
        """Атомарно врахувати лише успішно надіслані нагадування."""
        with self._db:
            self._db.executemany('''
                INSERT INTO reminder_state VALUES (?, ?, ?, 1)
                ON CONFLICT (marketplace, chat_id) DO UPDATE SET
                    sent_at=excluded.sent_at, sent_count=reminder_state.sent_count + 1
            ''', [(item['marketplace'], item['chat_id'],
                   now.astimezone(timezone.utc).isoformat()) for item in items])

    def open_chats(self, now: datetime, max_age_days: int = 7) -> list[dict]:
        """Знайти відкриті чати, молодші за задану кількість діб."""
        max_age = timedelta(days=max_age_days)
        return [item for item, waiting in self._waiting_chats(now)
                if timedelta(0) <= waiting < max_age]

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
        result = []
        for item, waiting in self._waiting_chats(now):
            if max_age_min is not None and item['waiting_min'] > max_age_min:
                continue
            if waiting > timedelta(minutes=older_than_min):
                result.append(item)
        return result

    def _waiting_chats(self, now: datetime):
        """Прочитати контекст останніх вхідних повідомлень відкритих чатів."""
        if now.utcoffset() is None:
            raise ValueError('Поточний час має містити часову зону')
        rows = self._db.execute('''
            SELECT marketplace, chat_id, buyer_name, created, subject, body FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY marketplace, chat_id ORDER BY created DESC, rowid DESC
                ) AS position FROM messages
            ) WHERE position=1 AND direction='in'
            ORDER BY created
        ''')
        for marketplace, chat_id, buyer_name, created, subject, body in rows:
            waiting = now - datetime.fromisoformat(created)
            waiting_min = int(waiting.total_seconds() // 60)
            yield (dict(marketplace=marketplace, chat_id=chat_id,
                        buyer_name=buyer_name, subject=subject,
                        last_text=mask_private(body)[:200], waiting_min=waiting_min), waiting)
