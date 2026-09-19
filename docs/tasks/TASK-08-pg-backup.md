# ЗАВДАННЯ 08: щоденний бекап Postgres із перевіркою відновлення і ротацією

**Виконавець:** Codex. **Приймає:** рецензент за `tests/test_pg_backup.py`. **Дата:** 19.09.2026.
**Чому:** аудит `docs/SYSTEM_DESIGN_AUDIT.md` п.1 — база (262 МБ) без жодного бекапу; власник
підтвердив «виправляй». Розклад (cron) і копіювання на ноутбук робить рецензент.

## Файли
`ops/__init__.py` (порожній), `ops/pg_backup.py`. Лише стандартна бібліотека.

## Інтерфейс
```python
def dump_cmd(container, user, db, out_path) -> list[str]
def list_cmd(container, path_in_container) -> list[str]
def backup(run, backup_dir, container, user, db, now, keep_days=14) -> dict
def rotate(backup_dir, now, keep_days=14) -> list[str]
```
- Середовище: Postgres у Docker-контейнері. `run(cmd: list[str], stdout_path: str | None = None) -> (code: int, stderr: str)`
  передається ззовні (виконує команду; якщо `stdout_path` задано — пише stdout у цей файл).
- `dump_cmd` → `['docker', 'exec', container, 'pg_dump', '-Fc', '-U', user, db]` (вихід іде в `out_path`
  через `stdout_path` у `run`; сам `out_path` у команді не з'являється).
- Файл: `<backup_dir>/pg_<db>_<YYYYMMDD-HHMM>.dump` за `now` (aware datetime; формат — у UTC).
  Спершу пишеться `<ім'я>.part`, і **лише після успішної перевірки** перейменовується на `.dump`
  (напівзаписаний файл ніколи не виглядає готовим бекапом).
- Перевірка: розмір `.part` > 0 **і** `pg_restore --list` на ньому успішний. Для перевірки
  `backup` викликає `run(['docker', 'exec', '-i', container, 'pg_restore', '--list'], stdin_path=<.part>)`
  — **тобто `run` має ще необов'язковий параметр `stdin_path`**; код повернення 0 = ок.
- `backup` повертає `{'ok': bool, 'path': str | None, 'size': int, 'error': str | None, 'removed': list[str]}`.
  Невдача дампу або перевірки → `ok=False`, `.part` видалено, **ротація не запускається**
  (не видаляти старі бекапи, коли новий не вдався). Успіх → `rotate(...)`, у `removed` — видалені файли.
- `rotate` видаляє лише файли `pg_*.dump` у `backup_dir`, чий час у назві старший за `keep_days` від `now`;
  **завжди лишає щонайменше 3 найновіші**, навіть якщо вони старі. Чужі файли не чіпає. Повертає
  список видалених імен (відсортований).
- `list_cmd(container, path)` лишити як допоміжну: `['docker','exec',container,'pg_restore','--list',path]`.
- Жодних паролів у командах; `user`/`db` — аргументами.

## Приймання
```
venv/bin/python -m pytest tests/test_pg_backup.py -q     → зелені
venv/bin/python -m pytest tests/ -q -k "not pg_backup"   → зелені
```
Звіт `docs/reports/TASK-08-report.md` з «Самостійними рішеннями».
