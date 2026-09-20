"""Збереження гіпотез і планових звірок із фактами."""

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

STAGES = (7, 14, 30)
VERDICTS = ('confirmed', 'rejected', 'unclear')


def _utc(value):
    """Відхилити час без зони та нормалізувати до UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Час має містити часову зону')
    return value.astimezone(timezone.utc)


def _encode_checks(checks):
    return json.dumps([
        {key: value.isoformat() if isinstance(value, datetime) else value
         for key, value in check.items()} for check in checks
    ], ensure_ascii=False)


class HypothesisStore:
    def __init__(self, path: str | None = None):
        self._db = sqlite3.connect(':memory:' if path is None else path)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.execute('''CREATE TABLE IF NOT EXISTS hypotheses (
                id TEXT PRIMARY KEY, trigger TEXT, subject TEXT NOT NULL,
                text TEXT NOT NULL, evidence TEXT NOT NULL, decision TEXT,
                created_at TEXT NOT NULL, status TEXT NOT NULL,
                checks TEXT NOT NULL)''')

    @staticmethod
    def _record(row):
        if row is None:
            return None
        result = dict(row)
        result['evidence'] = json.loads(result['evidence'])
        result['created_at'] = _utc(datetime.fromisoformat(result['created_at']))
        result['checks'] = json.loads(result['checks'])
        for check in result['checks']:
            for key in ('due', 'recorded_at'):
                if check[key] is not None:
                    check[key] = _utc(datetime.fromisoformat(check[key]))
        return result

    def create(self, *, trigger, subject, text, evidence, decision, now,
               stages=STAGES) -> dict:
        if (not isinstance(evidence, list) or not evidence
                or any(not isinstance(item, str) for item in evidence)):
            raise ValueError('Докази мають бути непорожнім списком рядків')
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError('Предмет гіпотези не може бути порожнім')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Текст гіпотези не може бути порожнім')
        stages = tuple(stages)
        if not stages:
            raise ValueError('Потрібна хоча б одна звірка')
        if any(type(stage) is not int or stage <= 0 for stage in stages):
            raise ValueError('Етапи мають бути додатними цілими днями')
        if len(set(stages)) != len(stages):
            raise ValueError('Етапи не можуть повторюватися')
        now = _utc(now)
        content = json.dumps([subject, text, decision], ensure_ascii=False)
        hid = hashlib.sha256(content.encode('utf-8')).hexdigest()[:12]
        checks = [{'stage': stage, 'due': now + timedelta(days=stage),
                   'fact': None, 'verdict': None, 'recorded_at': None}
                  for stage in sorted(stages)]
        with self._db:
            self._db.execute('''INSERT INTO hypotheses
                (id, trigger, subject, text, evidence, decision, created_at, status, checks)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
                ON CONFLICT(id) DO NOTHING''',
                (hid, trigger, subject, text, json.dumps(evidence, ensure_ascii=False),
                 decision, now.isoformat(timespec='microseconds'), _encode_checks(checks)))
            return self.get(hid)

    def get(self, hid) -> dict | None:
        return self._record(self._db.execute(
            'SELECT * FROM hypotheses WHERE id = ?', (hid,)).fetchone())

    def due(self, now) -> list[dict]:
        now = _utc(now)
        result = []
        for h in self.open_items():
            for check in h['checks']:
                if check['recorded_at'] is None and check['due'] <= now:
                    result.append({'id': h['id'], 'stage': check['stage'],
                                   'due': check['due'], 'subject': h['subject'],
                                   'text': h['text']})
        return sorted(result, key=lambda item: (item['due'], item['id']))

    def record(self, hid, stage, *, fact, verdict, now) -> dict:
        if verdict not in VERDICTS:
            raise ValueError('Невідомий висновок звірки')
        if not isinstance(fact, str) or not fact.strip():
            raise ValueError('Факт не може бути порожнім')
        now = _utc(now)
        with self._db:
            # Блокування не дозволяє двом з’єднанням переписати ту саму звірку.
            self._db.execute('BEGIN IMMEDIATE')
            h = self.get(hid)
            if h is None:
                raise ValueError('Гіпотезу не знайдено')
            check = next((item for item in h['checks'] if item['stage'] == stage), None)
            if check is None:
                raise ValueError('Етап звірки не знайдено')
            if check['recorded_at'] is not None:
                raise ValueError('Факт цієї звірки вже записано')
            check.update(fact=fact, verdict=verdict, recorded_at=now)
            status = 'open'
            if all(item['recorded_at'] is not None for item in h['checks']):
                status = max(h['checks'], key=lambda item: item['stage'])['verdict']
            self._db.execute('UPDATE hypotheses SET checks = ?, status = ? WHERE id = ?',
                             (_encode_checks(h['checks']), status, hid))
            return self.get(hid)

    def open_items(self) -> list[dict]:
        return [self._record(row) for row in self._db.execute(
            "SELECT * FROM hypotheses WHERE status = 'open' ORDER BY created_at DESC, id")]

    def summary(self, now) -> dict:
        result = dict.fromkeys(('open',) + VERDICTS, 0)
        for row in self._db.execute('SELECT status, COUNT(*) AS n FROM hypotheses GROUP BY status'):
            result[row['status']] = row['n']
        result['due'] = len(self.due(now))
        return result


def render(h: dict) -> str:
    lines = [f"🔎 {h['subject']}: {h['text']}"]
    if h['trigger']:
        lines.append(f"Привід: {h['trigger']}")
    lines.append('Докази: ' + ' '.join('• ' + item for item in h['evidence']))
    lines.append(f"Рішення: {h['decision']}")
    marks = {'confirmed': '✅', 'rejected': '❌', 'unclear': '🤔'}
    checks = []
    for check in sorted(h['checks'], key=lambda item: item['stage']):
        if check['verdict'] is None:
            outcome = '⏳ ' + _utc(check['due']).strftime('%d.%m')
        else:
            fact = check['fact']
            if len(fact) > 120:
                fact = fact[:120] + '…'
            outcome = marks[check['verdict']] + ' ' + fact
        checks.append(f"{check['stage']} — {outcome}")
    lines.append('Звірки: ' + ' · '.join(checks))
    return '\n'.join(lines)
