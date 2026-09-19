"""Стійка черга карток, збирання чатів і нагадування без повторного спаму."""

import sqlite3
from datetime import timedelta
from html import escape

from tg_dispatcher.inbox import collect, render
from tg_dispatcher.privacy import mask_private


class DeliveryQueue:
    def __init__(self, path: str = ':memory:'):
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.execute('''
                CREATE TABLE IF NOT EXISTS delivery_queue (
                    position INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE, text TEXT NOT NULL,
                    marketplace TEXT NOT NULL, chat_id TEXT NOT NULL
                )
            ''')

    def push(self, key: str, text: str, marketplace: str, chat_id: str) -> None:
        with self._db:
            self._db.execute('''
                INSERT INTO delivery_queue (key, text, marketplace, chat_id)
                VALUES (?, ?, ?, ?) ON CONFLICT (key) DO NOTHING
            ''', (key, text, marketplace, chat_id))

    def pending(self) -> list[dict]:
        return [dict(row) for row in self._db.execute('''
            SELECT key, text, marketplace, chat_id
            FROM delivery_queue ORDER BY position
        ''')]

    def done(self, key: str) -> None:
        with self._db:
            self._db.execute('DELETE FROM delivery_queue WHERE key=?', (key,))


class InboxCycle:
    def __init__(self, store, queue, list_page, get_chat, send, clock,
                 remind_after_min: int = 30, remind_every_min: int = 60):
        self.store = store
        self.queue = queue
        self.list_page = list_page
        self.get_chat = get_chat
        self.send = send
        self.clock = clock
        self.remind_after_min = remind_after_min
        self.remind_every_min = remind_every_min
        self._alert_errors = frozenset()
        self._reminded_at = None
        self._reminded_chats = frozenset()

    def poll(self) -> dict:
        res = collect.collect_rozetka(self.list_page, self.get_chat, self.store,
                                      now=self.clock())
        for msg in res['new']:
            self.queue.push(f'{msg.marketplace}:{msg.msg_id}', render.card(msg),
                            msg.marketplace, msg.chat_id)

        errors = [mask_private(str(error)) for error in res['errors']]
        delivered = 0
        for item in self.queue.pending():
            try:
                tg_id = self.send(item['text'])
            except Exception:
                # Не включаємо текст винятку: він може містити дані покупця.
                errors.append('Не вдалося доставити картку в Telegram')
                break
            self.store.link_tg(tg_id, item['marketplace'], item['chat_id'])
            self.queue.done(item['key'])
            delivered += 1

        current_errors = frozenset(errors)
        alert = None
        if current_errors != self._alert_errors:
            if current_errors:
                text = '⚠️ Чат покупців:\n' + '\n'.join(
                    escape(error) for error in dict.fromkeys(errors))
            else:
                text = '✅ Чат покупців знову працює'
            try:
                self.send(text)
            except Exception:
                pass
            else:
                self._alert_errors = current_errors
                alert = text
        return {'new': len(res['new']), 'delivered': delivered,
                'queued': len(self.queue.pending()), 'errors': errors, 'alert': alert}

    def remind(self) -> str | None:
        now = self.clock()
        items = self.store.unanswered(now, self.remind_after_min)
        if not items:
            return None
        chats = frozenset((item['marketplace'], item['chat_id']) for item in items)
        if (self._reminded_at is not None
                and now - self._reminded_at < timedelta(minutes=self.remind_every_min)
                and not chats.difference(self._reminded_chats)):
            return None
        text = render.reminder(items)
        try:
            self.send(text)
        except Exception:
            return None
        self._reminded_at = now
        self._reminded_chats = chats
        return text
