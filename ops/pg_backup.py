"""Резервні копії Postgres із перевіркою архіву та ротацією."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


def dump_cmd(container, user, db, out_path) -> list[str]:
    """Вивід команди записує виконавець у out_path через stdout_path."""
    return ['docker', 'exec', container, 'pg_dump', '-Fc', '-U', user, db]


def list_cmd(container, path_in_container) -> list[str]:
    """Команда перевірки архіву, який уже є в контейнері."""
    return ['docker', 'exec', container, 'pg_restore', '--list', path_in_container]


def _utc(now):
    if now.utcoffset() is None:
        raise ValueError('now має містити часовий пояс')
    return now.astimezone(timezone.utc)


def rotate(backup_dir, now, keep_days=14) -> list[str]:
    """Видалити прострочені архіви, зберігши три найновіші."""
    cutoff = _utc(now) - timedelta(days=keep_days)
    archives = []
    for path in Path(backup_dir).glob('pg_*.dump'):
        if path.is_symlink() or not path.is_file():
            continue
        match = re.fullmatch(r'pg_.+_(\d{8}-\d{4})\.dump', path.name)
        if not match:
            continue
        try:
            timestamp = datetime.strptime(match[1], '%Y%m%d-%H%M').replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        archives.append((timestamp, path.name, path))
    archives.sort(reverse=True)
    removed = []
    for timestamp, name, path in archives[3:]:
        if timestamp < cutoff:
            path.unlink()
            removed.append(name)
    return sorted(removed)


def backup(run, backup_dir, container, user, db, now, keep_days=14) -> dict:
    """Створити й перевірити дамп; таймаути команд забезпечує run."""
    result = {'ok': False, 'path': None, 'size': 0, 'error': None, 'removed': []}
    timestamp = _utc(now).strftime('%Y%m%d-%H%M')
    if not db or '/' in db or '\\' in db:
        result['error'] = 'Назва бази непридатна для імені файлу'
        return result
    directory = Path(backup_dir)
    path = directory / f'pg_{db}_{timestamp}.dump'
    part = path.with_name(path.name + '.part')
    stage = 'створення дампу'
    try:
        directory.mkdir(parents=True, exist_ok=True)
        code, _ = run(dump_cmd(container, user, db, str(part)), stdout_path=str(part))
        if code != 0:
            result['error'] = f'pg_dump завершився з кодом {code}'
        elif part.stat().st_size == 0:
            result['error'] = 'Дамп порожній'
        else:
            stage = 'перевірка дампу'
            code, _ = run(
                ['docker', 'exec', '-i', container, 'pg_restore', '--list'],
                stdin_path=str(part),
            )
            if code != 0:
                result['error'] = f'pg_restore --list завершився з кодом {code}'
            else:
                size = part.stat().st_size
                part.replace(path)
                result.update(ok=True, path=str(path), size=size)
    except Exception:
        # Текст винятку або stderr може містити приватні дані.
        result['error'] = f'Не вдалося виконати етап: {stage}'
    finally:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            result['error'] = 'Не вдалося видалити тимчасовий дамп'
    if result['ok']:
        result['removed'] = rotate(directory, now, keep_days)
    return result
