"""Приймальні тести TASK-25: памʼять гіпотез і звірка з фактом.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib
from datetime import datetime, timedelta, timezone

import pytest

hyp = importlib.import_module('research.hypotheses')

UTC = timezone.utc
NOW = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
BASE = {'trigger': 'питання покупця', 'subject': 'SO3142', 'text': 'ціна зависока',
        'evidence': ['5 питань за тиждень', 'конкурент дешевший'], 'decision': 'знизити на 5%'}


def store(path=None):
    return hyp.HypothesisStore(path) if path else hyp.HypothesisStore()


def new(st, **over):
    kw = dict(BASE); kw.update(over); kw.setdefault('now', NOW)
    return st.create(**kw)


# ── створення ─────────────────────────────────────────────────────────

def test_create_fields_and_checks():
    h = new(store())
    assert len(h['id']) == 12 and all(c in '0123456789abcdef' for c in h['id'])
    assert h['status'] == 'open' and h['created_at'] == NOW
    assert h['evidence'] == BASE['evidence'] and h['decision'] == BASE['decision']
    assert [c['stage'] for c in h['checks']] == list(hyp.STAGES)
    assert h['checks'][0]['due'] == NOW + timedelta(days=7)
    assert h['checks'][-1]['due'] == NOW + timedelta(days=30)
    assert all(c['fact'] is None and c['verdict'] is None and c['recorded_at'] is None
               for c in h['checks'])


def test_create_idempotent_by_content():
    st = store()
    a = new(st)
    b = new(st, now=NOW + timedelta(hours=3), trigger='інший привід')
    assert b['id'] == a['id'] and b['created_at'] == NOW and b['trigger'] == BASE['trigger']
    assert len(st.open_items()) == 1
    assert new(st, text='ціна нормальна')['id'] != a['id']


@pytest.mark.parametrize('over', [
    {'evidence': []}, {'evidence': 'рядок'}, {'evidence': None},
    {'text': ''}, {'text': '   '}, {'subject': ''}, {'stages': ()},
])
def test_create_validation(over):
    with pytest.raises(ValueError):
        new(store(), **over)


def test_custom_stages():
    h = new(store(), stages=(3, 9))
    assert [c['stage'] for c in h['checks']] == [3, 9]
    assert h['checks'][1]['due'] == NOW + timedelta(days=9)


def test_persistence(tmp_path):
    path = str(tmp_path / 'h.db')
    a = new(store(path))
    again = store(path).get(a['id'])
    assert again['id'] == a['id'] and again['created_at'] == NOW
    assert again['evidence'] == BASE['evidence']
    assert again['checks'][0]['due'] == NOW + timedelta(days=7)
    assert store(path).get('нема') is None


# ── звірки ────────────────────────────────────────────────────────────

def test_due_appears_by_schedule():
    st = store()
    a = new(st)
    assert st.due(NOW) == []
    d = st.due(NOW + timedelta(days=7))
    assert [x['stage'] for x in d] == [7]
    assert d[0]['id'] == a['id'] and d[0]['subject'] == 'SO3142' and d[0]['text'] == 'ціна зависока'
    assert [x['stage'] for x in st.due(NOW + timedelta(days=30))] == [7, 14, 30]


def test_due_sorted_by_date():
    st = store()
    old = new(st, subject='A', text='рано', now=NOW - timedelta(days=5))
    new_one = new(st, subject='B', text='пізно')
    d = st.due(NOW + timedelta(days=10))
    # old: +2, +9, +25 днів; new_one: +7, +14, +30 → за датою: old-7, new-7, old-14
    assert [x['id'] for x in d] == [old['id'], new_one['id'], old['id']]
    assert [x['stage'] for x in d] == [7, 7, 14]


def test_record_marks_check_and_keeps_open():
    st = store()
    a = new(st)
    out = st.record(a['id'], 7, fact='продажі зросли на 12%', verdict='confirmed',
                    now=NOW + timedelta(days=7))
    assert out['status'] == 'open'                     # ще дві звірки попереду
    c = out['checks'][0]
    assert c['fact'] == 'продажі зросли на 12%' and c['verdict'] == 'confirmed'
    assert c['recorded_at'] == NOW + timedelta(days=7)
    assert [x['stage'] for x in st.due(NOW + timedelta(days=14))] == [14]


def test_status_from_last_stage():
    st = store()
    a = new(st, stages=(7, 14))
    st.record(a['id'], 14, fact='без змін', verdict='unclear', now=NOW + timedelta(days=14))
    assert st.get(a['id'])['status'] == 'open'
    st.record(a['id'], 7, fact='спершу зросло', verdict='confirmed', now=NOW + timedelta(days=15))
    assert st.get(a['id'])['status'] == 'unclear'      # підсумкова — найбільша стадія
    assert st.due(NOW + timedelta(days=30)) == []
    assert st.open_items() == []


@pytest.mark.parametrize('args', [
    ('нема', 7, 'факт', 'confirmed'),
    (None, 9, 'факт', 'confirmed'),
    (None, 7, 'факт', 'maybe'),
    (None, 7, '', 'confirmed'),
    (None, 7, '   ', 'confirmed'),
])
def test_record_validation(args):
    st = store()
    a = new(st)
    hid = args[0] if args[0] is not None else a['id']
    with pytest.raises(ValueError):
        st.record(hid, args[1], fact=args[2], verdict=args[3], now=NOW + timedelta(days=7))


def test_record_twice_rejected():
    st = store()
    a = new(st)
    st.record(a['id'], 7, fact='факт', verdict='rejected', now=NOW + timedelta(days=7))
    with pytest.raises(ValueError):
        st.record(a['id'], 7, fact='інший факт', verdict='confirmed', now=NOW + timedelta(days=8))


# ── перелік і зведення ────────────────────────────────────────────────

def test_open_items_newest_first():
    st = store()
    old = new(st, text='стара', now=NOW - timedelta(days=2))
    fresh = new(st, text='нова')
    assert [h['id'] for h in st.open_items()] == [fresh['id'], old['id']]


def test_summary():
    st = store()
    a = new(st, text='перша', stages=(7,))
    new(st, text='друга')
    st.record(a['id'], 7, fact='факт', verdict='rejected', now=NOW + timedelta(days=7))
    s = st.summary(NOW + timedelta(days=8))
    assert s == {'open': 1, 'confirmed': 0, 'rejected': 1, 'unclear': 0, 'due': 1}


# ── картка ────────────────────────────────────────────────────────────

def test_render():
    st = store()
    a = new(st)
    st.record(a['id'], 7, fact='продажі зросли', verdict='confirmed', now=NOW + timedelta(days=7))
    lines = hyp.render(st.get(a['id'])).splitlines()
    assert lines[0] == '🔎 SO3142: ціна зависока'
    assert lines[1] == 'Привід: питання покупця'
    assert lines[2] == 'Докази: • 5 питань за тиждень • конкурент дешевший'
    assert lines[3] == 'Рішення: знизити на 5%'
    assert lines[4] == 'Звірки: 7 — ✅ продажі зросли · 14 — ⏳ 04.10 · 30 — ⏳ 20.10'


def test_render_no_trigger_and_long_fact():
    st = store()
    a = new(st, trigger='', stages=(7,))
    st.record(a['id'], 7, fact='я' * 200, verdict='unclear', now=NOW + timedelta(days=7))
    text = hyp.render(st.get(a['id']))
    assert 'Привід' not in text
    assert '🤔 ' + 'я' * 120 + '…' in text and 'я' * 121 not in text


def test_render_rejected_mark():
    st = store()
    a = new(st, stages=(7,))
    st.record(a['id'], 7, fact='продажі впали', verdict='rejected', now=NOW + timedelta(days=7))
    assert '❌ продажі впали' in hyp.render(st.get(a['id']))
