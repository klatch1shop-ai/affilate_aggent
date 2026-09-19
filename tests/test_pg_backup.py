"""Приймальні тести TASK-08. Написані замовником ДО виконання; виконавець їх не змінює."""
import importlib
import os
from datetime import datetime, timedelta, timezone

import pytest

pb = importlib.import_module('ops.pg_backup')
NOW = datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc)


class Run:
    def __init__(self, dump_code=0, dump_bytes=b'PGDMP...', list_code=0):
        self.dump_code, self.dump_bytes, self.list_code = dump_code, dump_bytes, list_code
        self.calls = []

    def __call__(self, cmd, stdout_path=None, stdin_path=None):
        self.calls.append((cmd, stdout_path, stdin_path))
        if 'pg_dump' in cmd:
            if stdout_path:
                open(stdout_path, 'wb').write(self.dump_bytes)
            return self.dump_code, '' if self.dump_code == 0 else 'pg_dump: error'
        if 'pg_restore' in cmd:
            assert stdin_path and os.path.exists(stdin_path)
            return self.list_code, ''
        raise AssertionError(cmd)


def test_dump_cmd():
    assert pb.dump_cmd('agent_postgres', 'u', 'd', '/x') == ['docker', 'exec', 'agent_postgres', 'pg_dump', '-Fc', '-U', 'u', 'd']


def test_backup_ok_names_and_part(tmp_path):
    r = Run()
    res = pb.backup(r, str(tmp_path), 'c', 'u', 'agentdb', NOW)
    assert res['ok'] and res['error'] is None and res['size'] == len(b'PGDMP...')
    assert os.path.basename(res['path']) == 'pg_agentdb_20260920-0100.dump'
    assert sorted(os.listdir(tmp_path)) == ['pg_agentdb_20260920-0100.dump']
    assert r.calls[0][1].endswith('.part')                     # дамп пишеться в .part
    assert r.calls[1][0] == ['docker', 'exec', '-i', 'c', 'pg_restore', '--list']


@pytest.mark.parametrize('kw', [dict(dump_code=1), dict(dump_bytes=b''), dict(list_code=1)])
def test_backup_failure_keeps_old_and_no_part(tmp_path, kw):
    old = tmp_path / 'pg_agentdb_20260801-0100.dump'
    old.write_bytes(b'x')
    for i in range(3):
        (tmp_path / f'pg_agentdb_2026080{2 + i}-0100.dump').write_bytes(b'x')
    res = pb.backup(Run(**kw), str(tmp_path), 'c', 'u', 'agentdb', NOW)
    assert res['ok'] is False and res['path'] is None and res['error']
    assert res['removed'] == []
    names = os.listdir(tmp_path)
    assert old.name in names and not any(n.endswith('.part') for n in names)


def test_rotate_keeps_recent_and_min_three(tmp_path):
    for d in (1, 2, 3, 10, 19):
        (tmp_path / f'pg_agentdb_202609{d:02d}-0100.dump').write_bytes(b'x')
    (tmp_path / 'notes.txt').write_text('чуже')
    (tmp_path / 'pg_agentdb_20260801-0100.dump.part').write_bytes(b'x')
    removed = pb.rotate(str(tmp_path), NOW, keep_days=14)
    assert removed == ['pg_agentdb_20260901-0100.dump', 'pg_agentdb_20260902-0100.dump',
                       'pg_agentdb_20260903-0100.dump']
    assert 'notes.txt' in os.listdir(tmp_path)


def test_rotate_min_three_even_if_old(tmp_path):
    for d in (1, 2, 3, 4):
        (tmp_path / f'pg_agentdb_202607{d:02d}-0100.dump').write_bytes(b'x')
    assert pb.rotate(str(tmp_path), NOW, keep_days=14) == ['pg_agentdb_20260701-0100.dump']


def test_backup_runs_rotation_on_success(tmp_path):
    for d in (1, 2, 3, 4):
        (tmp_path / f'pg_agentdb_202607{d:02d}-0100.dump').write_bytes(b'x')
    res = pb.backup(Run(), str(tmp_path), 'c', 'u', 'agentdb', NOW)
    assert res['ok'] and res['removed'] == ['pg_agentdb_20260701-0100.dump', 'pg_agentdb_20260702-0100.dump']
