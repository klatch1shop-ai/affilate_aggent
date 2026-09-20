"""Приймальні тести TASK-32: радар трендів ніші.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib
from datetime import date, timedelta

import pytest

tr = importlib.import_module('content.trends')

NOW = date(2026, 9, 20)


def vid(vid_id, days_ago=5, views=1000, title=None, channel='Канал', url=None):
    d = {'id': vid_id, 'title': title if title is not None else f'Ролик {vid_id}',
         'url': url or f'https://y/{vid_id}', 'channel': channel, 'views': views,
         'duration': 45}
    if days_ago is not None:
        d['upload_date'] = (NOW - timedelta(days=days_ago)).strftime('%Y%m%d')
    return d


# ── дата ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('value,out', [
    ('20260915', date(2026, 9, 15)),
    ('2026-09-15', date(2026, 9, 15)),
    ('', None), (None, None), ('вчора', None), ('2026-13-40', None),
])
def test_parse_date(value, out):
    assert tr.parse_date(value) == out


# ── швидкість і свіжість ──────────────────────────────────────────────

def test_velocity():
    assert tr.velocity(vid('a', days_ago=10, views=1000), NOW) == pytest.approx(100.0)
    assert tr.velocity(vid('b', days_ago=0, views=500), NOW) == pytest.approx(500.0)
    assert tr.velocity(vid('c', days_ago=-5, views=300), NOW) == pytest.approx(300.0)
    assert tr.velocity(vid('d', days_ago=None), NOW) is None
    assert tr.velocity(vid('e', views=None), NOW) is None
    assert tr.velocity(vid('f', views='багато'), NOW) is None


def test_fresh():
    videos = [vid('a', days_ago=5), vid('b', days_ago=30), vid('c', days_ago=31),
              vid('d', days_ago=None)]
    assert [v['id'] for v in tr.fresh(videos, NOW)] == ['a', 'b']
    assert [v['id'] for v in tr.fresh(videos, NOW, days=4)] == []


def test_rank_sorts_and_copies():
    videos = [vid('A', days_ago=10, views=1000), vid('B', days_ago=2, views=400),
              vid('C', days_ago=5, views=500), vid('D', views=None)]
    out = tr.rank(videos, NOW)
    assert [v['id'] for v in out] == ['B', 'C', 'A']       # 200 · 100(новіший) · 100
    assert out[0]['velocity'] == pytest.approx(200.0)
    assert 'velocity' not in videos[0]                      # вхідні не змінені
    assert [v['id'] for v in tr.rank(videos, NOW, limit=2)] == ['B', 'C']
    assert tr.rank([], NOW) == []


# ── збір ──────────────────────────────────────────────────────────────

class Searcher:
    def __init__(self, by_query=None, fail=None):
        self.by_query, self.fail, self.calls = by_query or {}, fail or {}, []

    def __call__(self, query, per_query):
        self.calls.append((query, per_query))
        if query in self.fail:
            raise self.fail[query]
        return self.by_query.get(query, [vid(f'{query}-1'), vid(f'{query}-2')])


def test_collect_dedups_queries_and_videos():
    s = Searcher(by_query={'q1': [vid('x'), vid('y')], 'q2': [vid('y'), vid('z')]})
    out = tr.collect(['q1', ' Q1 ', '', 'q2'], s, per_query=3)
    assert [c[0] for c in s.calls] == ['q1', 'q2'] and s.calls[0][1] == 3
    assert [v['id'] for v in out['videos']] == ['x', 'y', 'z']
    assert out['asked'] == 2 and out['errors'] == []


def test_collect_limit_stops_further_queries():
    s = Searcher()
    out = tr.collect(['q1', 'q2', 'q3'], s, limit=3)
    assert len(out['videos']) == 3 and out['asked'] == 2


def test_collect_limit_zero():
    s = Searcher()
    out = tr.collect(['q1'], s, limit=0)
    assert s.calls == [] and out['videos'] == [] and out['asked'] == 0


def test_collect_survives_errors_and_bad_items():
    s = Searcher(by_query={'q2': [{'id': 'нема назви'}, {'title': 'нема id'}, vid('ok')]},
                 fail={'q1': TimeoutError('довго')})
    out = tr.collect(['q1', 'q2'], s)
    assert [v['id'] for v in out['videos']] == ['ok']
    assert len(out['errors']) == 1 and out['errors'][0].startswith('q1:')


# ── зміни тем ─────────────────────────────────────────────────────────

def test_diff_topics():
    d = tr.diff_topics(['Ключі TOPTUL', ' свічки ', 'Свічки'], ['свічки', 'набори'])
    assert d == {'new': ['ключі toptul'], 'gone': ['набори'], 'kept': ['свічки']}
    assert tr.diff_topics([], []) == {'new': [], 'gone': [], 'kept': []}


# ── звіт ──────────────────────────────────────────────────────────────

def ranked():
    return [{'id': 'a', 'title': 'Перший', 'channel': 'Канал', 'url': 'u1', 'velocity': 200.0},
            {'id': 'b', 'title': 'Другий', 'channel': '', 'url': 'u2', 'velocity': 99.6}]


def test_report():
    text = tr.report(ranked(), {'new': ['свічки', 'ключі'], 'gone': ['набори'], 'kept': []}, NOW)
    lines = text.splitlines()
    assert lines[0] == '📈 Радар трендів на 20.09.2026'
    assert lines[1] == 'Свіжих роликів: 2'
    assert lines[2] == '• 200/день · «Перший» — Канал'
    assert lines[3] == '  u1'
    assert lines[4].startswith('• 100/день · «Другий» —')
    assert lines[5] == '  u2'
    assert 'Нові теми: свічки, ключі' in lines
    assert 'Зникли: набори' in lines


def test_report_empty():
    lines = tr.report([], {'new': [], 'gone': [], 'kept': []}, NOW).splitlines()
    assert lines[1] == 'Свіжих роликів: 0' and lines[2] == 'Нема свіжих роликів'
    assert not any(l.startswith('Нові теми') for l in lines)
