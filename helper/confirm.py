"""Збереження пропозицій дій і виконання після підтвердження."""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from tg_dispatcher.privacy import mask_private

RISKS = ('R0', 'R1', 'R2', 'R3')
STATUSES = ('pending', 'approved', 'done', 'failed', 'rejected', 'expired')
TTL_MIN = {'R2': 10, 'R3': 5}
MODES = ('off', 'test', 'live')


def _utc(value):
    """Відхилити час без зони та нормалізувати до UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Час має містити часову зону')
    return value.astimezone(timezone.utc)


class ConfirmStore:
    def __init__(self, path: str = ':memory:'):
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.execute('''CREATE TABLE IF NOT EXISTS confirmations (
                id TEXT PRIMARY KEY, intent TEXT NOT NULL, params TEXT NOT NULL,
                content_key TEXT NOT NULL, risk TEXT NOT NULL, preview TEXT NOT NULL,
                status TEXT NOT NULL, requested_by, created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL, decided_by, decided_at TEXT, result TEXT,
                claimed INTEGER NOT NULL DEFAULT 0)''')
            self._db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS pending_content
                ON confirmations(intent, content_key) WHERE status = 'pending' ''')

    @staticmethod
    def _record(row):
        if row is None:
            return None
        record = dict(row)
        record.pop('content_key')
        record.pop('claimed')
        record['params'] = json.loads(record['params'])
        for key in ('created_at', 'expires_at', 'decided_at'):
            if record[key] is not None:
                record[key] = datetime.fromisoformat(record[key])
        return record

    def _expire(self, now):
        self._db.execute("UPDATE confirmations SET status = 'expired' "
                         "WHERE status = 'pending' AND expires_at < ?", (now.isoformat(),))

    def create(self, *, intent, params, risk, preview, requested_by, now, ttl_min=None):
        if risk not in TTL_MIN:
            raise ValueError('Підтвердження потрібне лише для R2/R3')
        if not isinstance(params, dict):
            raise ValueError('Параметри мають бути словником')
        now = _utc(now)
        expires = now + timedelta(minutes=TTL_MIN[risk] if ttl_min is None else ttl_min)
        encoded = json.dumps(params, ensure_ascii=False, allow_nan=False)
        key = json.dumps(params, sort_keys=True, ensure_ascii=False, allow_nan=False)
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            self._expire(now)
            row = self._db.execute("SELECT * FROM confirmations WHERE intent = ? "
                                   "AND content_key = ? AND status = 'pending'", (intent, key)).fetchone()
            if row is not None:
                return self._record(row)
            action_id = uuid.uuid4().hex[:12]
            self._db.execute('''INSERT INTO confirmations
                (id, intent, params, content_key, risk, preview, status, requested_by,
                 created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)''',
                (action_id, intent, encoded, key, risk, preview, requested_by,
                 now.isoformat(), expires.isoformat()))
            return self.get(action_id)

    def get(self, action_id):
        return self._record(self._db.execute('SELECT * FROM confirmations WHERE id = ?',
                                            (action_id,)).fetchone())

    def pending(self, now):
        with self._db:
            self._expire(_utc(now))
            return [self._record(row) for row in self._db.execute(
                "SELECT * FROM confirmations WHERE status = 'pending' ORDER BY created_at, rowid")]

    def _decide(self, action_id, user_id, now, status):
        now = _utc(now)
        with self._db:
            self._db.execute('''UPDATE confirmations SET
                status = CASE WHEN expires_at < ? THEN 'expired' ELSE ? END,
                decided_by = CASE WHEN expires_at < ? THEN decided_by ELSE ? END,
                decided_at = CASE WHEN expires_at < ? THEN decided_at ELSE ? END
                WHERE id = ? AND status = 'pending' ''',
                (now.isoformat(), status, now.isoformat(), user_id,
                 now.isoformat(), now.isoformat(), action_id))
            record = self.get(action_id)
            if record is None:
                raise ValueError('Дію не знайдено')
            return record

    def approve(self, action_id, *, user_id, now):
        return self._decide(action_id, user_id, now, 'approved')

    def reject(self, action_id, *, user_id, now):
        return self._decide(action_id, user_id, now, 'rejected')

    def finish(self, action_id, *, ok: bool, result: str, now):
        _utc(now)
        with self._db:
            changed = self._db.execute('''UPDATE confirmations SET status = ?, result = ?
                WHERE id = ? AND status = 'approved' ''',
                ('done' if ok else 'failed', mask_private(str(result))[:200], action_id))
            if changed.rowcount != 1:
                raise ValueError('Завершити можна лише підтверджену дію')
            return self.get(action_id)

    def log(self, limit: int = 50):
        if limit < 0:
            raise ValueError('Ліміт не може бути від’ємним')
        return [self._record(row) for row in self._db.execute(
            'SELECT * FROM confirmations ORDER BY created_at DESC, rowid DESC LIMIT ?', (limit,))]

    def _claim(self, action_id):
        """Зарезервувати виконання атомарно, зокрема між різними з'єднаннями."""
        with self._db:
            return self._db.execute('''UPDATE confirmations SET claimed = 1
                WHERE id = ? AND status = 'approved' AND claimed = 0''',
                (action_id,)).rowcount == 1


def mode_of(intent: str, modes: dict, default: str = 'off') -> str:
    mode = modes.get(intent, default)
    if mode not in MODES:
        raise ValueError('Невідомий режим виконання')
    return mode


def gate(intent: str, risk: str, modes: dict) -> str:
    if risk not in RISKS:
        raise ValueError('Невідомий рівень ризику')
    if risk in ('R0', 'R1'):
        return 'run'
    return {'off': 'skip', 'test': 'dry', 'live': 'run'}[mode_of(intent, modes)]


def confirm_text(action: dict) -> str:
    lines = [('⚠️' if action['risk'] == 'R3' else '❓') + ' Підтвердіть дію', action['intent']]
    for key, value in action['params'].items():
        value = mask_private(str(value))
        lines.append(f'{key}: ' + (value[:200] + '…' if len(value) > 200 else value))
    lines.append(action['preview'])
    seconds = (_utc(action['expires_at']) - datetime.now(timezone.utc)).total_seconds()
    minutes = max(0, int(-(-seconds // 60)))
    lines.append(f'Діє ще {minutes} хв')
    return mask_private('\n'.join(lines))


def run_action(store, action_id, executor, *, user_id, now, modes, dry_result='') -> dict:
    _utc(now)
    action = store.get(action_id)
    if action is None or action['status'] != 'approved':
        return {'ok': False, 'status': action['status'] if action else 'missing',
                'message': 'Дію не підтверджено або вже завершено'}
    mode = gate(action['intent'], action['risk'], modes)
    if not store._claim(action_id):
        return {'ok': False, 'status': store.get(action_id)['status'],
                'message': 'Виконання вже розпочато'}
    ok = False
    if mode == 'skip':
        result = 'режим off'
    else:
        try:
            params = dict(action['params'])
            if mode == 'dry':
                params['dry_run'] = True
            result = mask_private(str(executor(**params)))[:200]
            ok = True
        except Exception as exc:
            result = mask_private(f'{type(exc).__name__}: {exc}')[:200]
    finished = store.finish(action_id, ok=ok, result=result, now=now)
    return {'ok': ok, 'status': finished['status'], 'result': finished['result'], 'mode': mode}
