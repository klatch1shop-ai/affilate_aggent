"""Довговічна черга задач для виконання через різних провайдерів.

Навіщо саме так. 26.09.2026 ми двічі втратили стан довгої роботи: вартовий жив
у `/tmp` і зник при вимкненні ноутбука, а облік зробленого тримався в контексті
розмови й зникав при обриві. Тому черга — SQLite на диску: запис фіксується
одразу після кожної відповіді, перезапуск підхоплює з того самого місця, а
незавершена задача сама повертається в роботу за строком.

Головне число цієї черги — не «скільки зроблено», а `verified_by_two()`:
скільки рядків перевірено ДВОМА РІЗНИМИ вендорами. Попередній прогін дав
2557 «оброблених» рядків, з яких 94% перевірки були однією моделлю самою з
собою — саме через те, що дивились на лічильник.

    q = TaskQueue('data/tasks/epicentr.db')
    q.add_many([{'key': 'SO123|Колір', 'kind': 'attr', 'payload': {...}}, ...])
    for task in q.take(10):
        ...
        q.finish(task['key'], verdict='ЗБІГ', vendor_a='openrouter', vendor_b='codex')
"""
import json
import os
import sqlite3
import time

NEW = 'нова'
RUNNING = 'в роботі'
DONE = 'готова'
FAILED = 'збій'

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    key        TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    payload    TEXT NOT NULL,
    state      TEXT NOT NULL DEFAULT 'нова',
    attempts   INTEGER NOT NULL DEFAULT 0,
    vendor_a   TEXT,
    vendor_b   TEXT,
    answer_a   TEXT,
    answer_b   TEXT,
    verdict    TEXT,
    error      TEXT,
    updated_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_state ON tasks(state, kind);
"""


class TaskQueue:
    def __init__(self, path):
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, timeout=30)
        self._conn.row_factory = sqlite3.Row
        # WAL: запис не блокує читання — дошка може дивитись стан під час прогону
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def add_many(self, tasks, now=None):
        """Додає задачі. Уже наявні за `key` не чіпає — щоб повторний запуск
        наповнення не скидав зроблене. Повертає, скільки додано нових."""
        now = now if now is not None else time.time()
        rows = [(t['key'], t['kind'], json.dumps(t.get('payload') or {}, ensure_ascii=False),
                 NEW, now) for t in tasks]
        cur = self._conn.executemany(
            'INSERT OR IGNORE INTO tasks (key, kind, payload, state, updated_at)'
            ' VALUES (?, ?, ?, ?, ?)', rows)
        self._conn.commit()
        return cur.rowcount

    def take(self, limit=1, kind=None, now=None):
        """Позначає задачі як «в роботі» й повертає їх. Позначення й видача —
        в одній транзакції, інакше два прогони взяли б ту саму задачу."""
        now = now if now is not None else time.time()
        where = 'state = ?' + (' AND kind = ?' if kind else '')
        params = [NEW] + ([kind] if kind else [])
        with self._conn:
            rows = self._conn.execute(
                f'SELECT * FROM tasks WHERE {where} ORDER BY updated_at LIMIT ?',
                params + [limit]).fetchall()
            for row in rows:
                self._conn.execute(
                    'UPDATE tasks SET state = ?, attempts = attempts + 1, updated_at = ?'
                    ' WHERE key = ?', (RUNNING, now, row['key']))
        return [self._as_dict(r) for r in rows]

    def finish(self, key, verdict=None, vendor_a=None, vendor_b=None,
               answer_a=None, answer_b=None, error=None, state=None, now=None):
        """Фіксує результат ОДРАЗУ. Стан за замовчуванням — «готова», а при
        помилці «збій»: мовчазне «готова» без результату — те, через що
        зіпсований прогін виглядав успішним."""
        now = now if now is not None else time.time()
        if state is None:
            state = FAILED if error else DONE
        with self._conn:
            self._conn.execute(
                'UPDATE tasks SET state = ?, verdict = ?, vendor_a = ?, vendor_b = ?,'
                ' answer_a = ?, answer_b = ?, error = ?, updated_at = ? WHERE key = ?',
                (state, verdict, vendor_a, vendor_b, answer_a, answer_b, error, now, key))

    def requeue_stale(self, older_than_sec=1800, now=None):
        """Задачі, що зависли «в роботі» (обрив, вимкнення) — назад у чергу."""
        now = now if now is not None else time.time()
        with self._conn:
            cur = self._conn.execute(
                'UPDATE tasks SET state = ?, updated_at = ? WHERE state = ? AND updated_at < ?',
                (NEW, now, RUNNING, now - older_than_sec))
        return cur.rowcount

    def counts(self):
        rows = self._conn.execute(
            'SELECT state, COUNT(*) n FROM tasks GROUP BY state').fetchall()
        return {r['state']: r['n'] for r in rows}

    def verdict_counts(self):
        rows = self._conn.execute(
            'SELECT verdict, COUNT(*) n FROM tasks WHERE verdict IS NOT NULL'
            ' GROUP BY verdict ORDER BY n DESC').fetchall()
        return {r['verdict']: r['n'] for r in rows}

    def verified_by_two(self):
        """ГОЛОВНЕ ЧИСЛО: скільки задач перевірено двома РІЗНИМИ вендорами."""
        row = self._conn.execute(
            'SELECT COUNT(*) n FROM tasks WHERE vendor_a IS NOT NULL'
            ' AND vendor_b IS NOT NULL AND vendor_a <> vendor_b').fetchone()
        return row['n']

    def vendor_usage(self):
        """Скільки разів кожен вендор був джерелом — видно звуження пулу."""
        usage = {}
        for column in ('vendor_a', 'vendor_b'):
            rows = self._conn.execute(
                f'SELECT {column} v, COUNT(*) n FROM tasks WHERE {column} IS NOT NULL'
                f' GROUP BY {column}').fetchall()
            for r in rows:
                usage[r['v']] = usage.get(r['v'], 0) + r['n']
        return usage

    def failures(self, limit=10):
        rows = self._conn.execute(
            'SELECT key, error, attempts FROM tasks WHERE state = ?'
            ' ORDER BY updated_at DESC LIMIT ?', (FAILED, limit)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _as_dict(row):
        task = dict(row)
        try:
            task['payload'] = json.loads(task['payload'])
        except (ValueError, TypeError):
            task['payload'] = {}
        return task
