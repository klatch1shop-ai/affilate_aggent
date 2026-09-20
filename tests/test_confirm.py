"""Приймальні тести TASK-13: механізм підтвердження дій.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib
from datetime import datetime, timedelta, timezone

import pytest

confirm = importlib.import_module('helper.confirm')

UTC = timezone.utc
NOW = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
OWNER, HELPER = 111, 222
PARAMS = {'order_id': '906372863', 'ttn': '20451539117101', 'comment': 'дзвоніть 0671234567'}


def store():
    return confirm.ConfirmStore()


def new(st, **kw):
    kw.setdefault('intent', 'add_ttn'); kw.setdefault('params', dict(PARAMS))
    kw.setdefault('risk', 'R2'); kw.setdefault('preview', 'ТТН буде додано до замовлення')
    kw.setdefault('requested_by', OWNER); kw.setdefault('now', NOW)
    return st.create(**kw)


# ── створення ─────────────────────────────────────────────────────────

def test_create_basic_fields():
    a = new(store())
    assert len(a['id']) == 12 and all(c in '0123456789abcdef' for c in a['id'])
    assert a['status'] == 'pending' and a['risk'] == 'R2' and a['params'] == PARAMS
    assert a['expires_at'] == NOW + timedelta(minutes=confirm.TTL_MIN['R2'])
    assert a['created_at'] == NOW and a['requested_by'] == OWNER


def test_r3_ttl_and_custom_ttl():
    st = store()
    assert new(st, risk='R3', intent='np_ttn')['expires_at'] == NOW + timedelta(minutes=confirm.TTL_MIN['R3'])
    assert new(st, intent='other', ttl_min=45)['expires_at'] == NOW + timedelta(minutes=45)


@pytest.mark.parametrize('risk', ['R0', 'R1', 'RX', None])
def test_create_rejects_non_confirmable_risk(risk):
    with pytest.raises(ValueError):
        new(store(), risk=risk)


def test_create_is_idempotent_by_content():
    st = store()
    a = new(st)
    b = new(st, now=NOW + timedelta(minutes=1))
    assert b['id'] == a['id'] and b['created_at'] == a['created_at']
    c = new(st, params=dict(PARAMS, ttn='20451539117102'))
    assert c['id'] != a['id']
    d = new(st, intent='inne')
    assert d['id'] not in (a['id'], c['id'])


def test_persistence(tmp_path):
    path = str(tmp_path / 'c.db')
    a = confirm.ConfirmStore(path).create(intent='x', params={'a': 1}, risk='R2', preview='p',
                                          requested_by=OWNER, now=NOW)
    again = confirm.ConfirmStore(path).get(a['id'])
    assert again['id'] == a['id'] and again['params'] == {'a': 1} and again['created_at'] == NOW


# ── рішення ───────────────────────────────────────────────────────────

def test_approve_reject_flow():
    st = store()
    a = new(st)
    ok = st.approve(a['id'], user_id=OWNER, now=NOW + timedelta(minutes=1))
    assert ok['status'] == 'approved' and ok['decided_by'] == OWNER
    again = st.approve(a['id'], user_id=HELPER, now=NOW + timedelta(minutes=2))
    assert again['status'] == 'approved' and again['decided_by'] == OWNER      # без змін
    b = new(st, intent='other')
    r = st.reject(b['id'], user_id=OWNER, now=NOW + timedelta(minutes=1))
    assert r['status'] == 'rejected'
    assert st.approve(b['id'], user_id=OWNER, now=NOW + timedelta(minutes=2))['status'] == 'rejected'


def test_expiry():
    st = store()
    a = new(st)
    late = NOW + timedelta(minutes=confirm.TTL_MIN['R2'] + 1)
    out = st.approve(a['id'], user_id=OWNER, now=late)
    assert out['status'] == 'expired'
    assert st.get(a['id'])['status'] == 'expired'
    assert st.pending(late) == []


def test_pending_lists_only_live():
    st = store()
    a = new(st)
    new(st, intent='old', now=NOW - timedelta(hours=1))
    live = st.pending(NOW + timedelta(minutes=1))
    assert [x['id'] for x in live] == [a['id']]


def test_finish_only_after_approve_and_log():
    st = store()
    a = new(st)
    with pytest.raises(ValueError):
        st.finish(a['id'], ok=True, result='зроблено', now=NOW)
    st.approve(a['id'], user_id=OWNER, now=NOW)
    done = st.finish(a['id'], ok=True, result='ТТН додано', now=NOW + timedelta(minutes=1))
    assert done['status'] == 'done' and done['result'] == 'ТТН додано'
    b = new(st, intent='other')
    st.approve(b['id'], user_id=OWNER, now=NOW)
    assert st.finish(b['id'], ok=False, result='помилка API', now=NOW)['status'] == 'failed'
    ids = [x['id'] for x in st.log()]
    assert a['id'] in ids and b['id'] in ids and len(ids) >= 2


# ── режими ────────────────────────────────────────────────────────────

def test_mode_of_and_gate():
    modes = {'np_ttn': 'live', 'supplier_mail': 'test'}
    assert confirm.mode_of('np_ttn', modes) == 'live'
    assert confirm.mode_of('unknown', modes) == 'off'
    assert confirm.mode_of('unknown', modes, default='test') == 'test'
    assert confirm.gate('np_ttn', 'R3', modes) == 'run'
    assert confirm.gate('supplier_mail', 'R3', modes) == 'dry'
    assert confirm.gate('add_ttn', 'R2', modes) == 'skip'
    assert confirm.gate('orders_new', 'R0', modes) == 'run'
    assert confirm.gate('draft_reply', 'R1', {}) == 'run'
    with pytest.raises(ValueError):
        confirm.gate('x', 'R2', {'x': 'yes'})


# ── текст підтвердження ───────────────────────────────────────────────

def test_confirm_text():
    st = store()
    a = new(st, risk='R3', intent='np_ttn', preview='Буде створено ТТН Нової Пошти')
    text = confirm.confirm_text(dict(a, now=None)) if False else confirm.confirm_text(a)
    lines = text.splitlines()
    assert lines[0].startswith('⚠️')
    assert 'np_ttn' in text and '906372863' in text and '20451539117101' in text
    assert 'Буде створено ТТН Нової Пошти' in text
    assert '0671234567' not in text and '[телефон приховано]' in text
    assert 'Діє ще' in lines[-1]
    r2 = confirm.confirm_text(new(st, intent='add_ttn2'))
    assert r2.splitlines()[0].startswith('❓')


def test_confirm_text_truncates_long_values():
    a = new(store(), intent='long', params={'text': 'я' * 500})
    out = confirm.confirm_text(a)
    assert 'я' * 200 + '…' in out and 'я' * 201 not in out


# ── виконання ─────────────────────────────────────────────────────────

class Exec:
    def __init__(self, fail=None, result='ok'):
        self.calls, self.fail, self.result = [], fail, result

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise self.fail
        return self.result


def approved(st, **kw):
    a = new(st, **kw)
    st.approve(a['id'], user_id=OWNER, now=NOW)
    return a


def test_run_requires_approved():
    st, ex = store(), Exec()
    a = new(st)
    out = confirm.run_action(st, a['id'], ex, user_id=OWNER, now=NOW, modes={'add_ttn': 'live'})
    assert out['ok'] is False and out['status'] == 'pending' and ex.calls == []


def test_run_live_test_off():
    st, ex = store(), Exec(result='ТТН 2045…')
    a = approved(st, intent='add_ttn')
    out = confirm.run_action(st, a['id'], ex, user_id=OWNER, now=NOW, modes={'add_ttn': 'live'})
    assert out == {'ok': True, 'status': 'done', 'result': 'ТТН 2045…', 'mode': 'run'}
    assert ex.calls == [PARAMS] and st.get(a['id'])['status'] == 'done'

    st2, ex2 = store(), Exec()
    b = approved(st2, intent='supplier_mail')
    out2 = confirm.run_action(st2, b['id'], ex2, user_id=OWNER, now=NOW, modes={'supplier_mail': 'test'})
    assert out2['mode'] == 'dry' and ex2.calls and ex2.calls[0].get('dry_run') is True

    st3, ex3 = store(), Exec()
    c = approved(st3, intent='cancel_order')
    out3 = confirm.run_action(st3, c['id'], ex3, user_id=OWNER, now=NOW, modes={})
    assert out3['mode'] == 'skip' and ex3.calls == [] and st3.get(c['id'])['status'] == 'failed'


def test_run_error_is_recorded_and_masked():
    st = store()
    a = approved(st, intent='add_ttn')
    ex = Exec(fail=RuntimeError('збій, клієнт 0671234567'))
    out = confirm.run_action(st, a['id'], ex, user_id=OWNER, now=NOW, modes={'add_ttn': 'live'})
    assert out['ok'] is False and out['status'] == 'failed'
    assert '0671234567' not in out['result'] and 'RuntimeError' in out['result']


def test_run_twice_does_not_repeat():
    st, ex = store(), Exec()
    a = approved(st, intent='add_ttn')
    confirm.run_action(st, a['id'], ex, user_id=OWNER, now=NOW, modes={'add_ttn': 'live'})
    again = confirm.run_action(st, a['id'], ex, user_id=OWNER, now=NOW, modes={'add_ttn': 'live'})
    assert len(ex.calls) == 1 and again['ok'] is False and again['status'] == 'done'


# ── §8 «я прочитав» ───────────────────────────────────────────────────

ack_mod = importlib.import_module('helper.ack')


def test_ack_basic_and_expiry():
    a = ack_mod.AckStore()
    assert a.is_acked('rozetka', '42', now=NOW, last_msg_id='7') is False
    a.ack('rozetka', '42', now=NOW, last_msg_id='7', user_id=OWNER)
    assert a.is_acked('rozetka', '42', now=NOW + timedelta(hours=23), last_msg_id='7') is True
    assert a.is_acked('rozetka', '42', now=NOW + timedelta(hours=25), last_msg_id='7') is False


def test_ack_broken_by_new_message():
    a = ack_mod.AckStore()
    a.ack('rozetka', '42', now=NOW, last_msg_id='7')
    assert a.is_acked('rozetka', '42', now=NOW + timedelta(hours=1), last_msg_id='8') is False
    a.ack('rozetka', '42', now=NOW + timedelta(hours=1), last_msg_id='8')
    assert a.is_acked('rozetka', '42', now=NOW + timedelta(hours=2), last_msg_id='8') is True


def test_ack_hours_clear_list_and_persistence(tmp_path):
    path = str(tmp_path / 'a.db')
    a = ack_mod.AckStore(path)
    a.ack('rozetka', '1', now=NOW, last_msg_id='1', hours=2, user_id=OWNER)
    a.ack('prom', '2', now=NOW, last_msg_id='2', hours=5)
    assert [x['chat_id'] for x in a.acked(NOW)] == ['1', '2']
    assert ack_mod.AckStore(path).is_acked('rozetka', '1', now=NOW + timedelta(hours=1), last_msg_id='1') is True
    assert a.is_acked('rozetka', '1', now=NOW + timedelta(hours=3), last_msg_id='1') is False
    a.clear('prom', '2')
    assert a.acked(NOW) == [] or all(x['chat_id'] != '2' for x in a.acked(NOW))
