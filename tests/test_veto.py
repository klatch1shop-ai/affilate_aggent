"""Приймальні тести TASK-27: ризик-вето над планом дії.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib

import pytest

veto = importlib.import_module('research.veto')

CTX = {'floor': {'SO3142': 120.0}, 'approved': True, 'evidence': ['лист постачальника']}


def act(**over):
    a = {'kind': 'price_update', 'sku': 'SO3142', 'marketplace': 'rozetka',
         'source': 'noire', 'mode': 'test', 'fields': {}, 'files': [], 'text': ''}
    a.update(over)
    return a


def rules(problems):
    return [p['rule'] for p in problems]


def by_rule(problems, rule):
    return next(p for p in problems if p['rule'] == rule)


# ── ціна ──────────────────────────────────────────────────────────────

def test_price_below_floor_stops():
    p = veto.check(act(fields={'price': 100}), CTX)
    assert rules(p) == ['price_floor'] and by_rule(p, 'price_floor')['level'] == 'stop'
    assert by_rule(p, 'price_floor')['message'] == 'ціна 100.00 нижча за поріг 120.00'


def test_price_equal_floor_is_allowed():
    assert veto.check(act(fields={'price': 120.0}), CTX) == []


def test_price_without_known_floor_asks():
    p = veto.check(act(sku='НОВИЙ', fields={'price': 500}), CTX)
    assert by_rule(p, 'price_floor')['level'] == 'ask'
    assert by_rule(p, 'price_floor')['message'] == 'поріг ціни невідомий'


def test_price_not_a_number_stops():
    p = veto.check(act(fields={'price': 'домовимось'}), CTX)
    assert by_rule(p, 'price_floor') == {'rule': 'price_floor', 'level': 'stop',
                                         'message': 'ціна не число: домовимось'}


# ── заморожений зміст, Carvol, файли ──────────────────────────────────

def test_frozen_feed_content():
    p = veto.check(act(kind='feed_content', marketplace='rozetka'), CTX)
    assert by_rule(p, 'frozen_content')['level'] == 'stop'
    assert 'rozetka' in by_rule(p, 'frozen_content')['message']
    assert veto.check(act(kind='feed_content', marketplace='prom'), CTX) == []
    assert veto.check(act(kind='price_update', marketplace='rozetka'), CTX) == []


def test_carvol_is_read_only():
    p = veto.check(act(source='carvol'), CTX)
    assert rules(p) == ['read_only_source'] and by_rule(p, 'read_only_source')['level'] == 'stop'


def test_protected_file():
    p = veto.check(act(files=['output/other.xml', 'output/noire_epicentr_phase1.xml']), CTX)
    assert by_rule(p, 'protected_file')['level'] == 'stop'
    assert 'noire_epicentr_phase1.xml' in by_rule(p, 'protected_file')['message']
    assert veto.check(act(files=['output/other.xml']), CTX) == []


# ── наявність ─────────────────────────────────────────────────────────

def test_availability_unknown_value():
    p = veto.check(act(fields={'availability': 'мабуть є'}), CTX)
    assert by_rule(p, 'availability') == {'rule': 'availability', 'level': 'stop',
                                          'message': 'невідомий стан наявності: мабуть є'}


def test_availability_not_available_needs_evidence():
    ctx = dict(CTX, evidence=[])
    p = veto.check(act(fields={'availability': 'not_available'}), ctx)
    assert by_rule(p, 'availability') == {'rule': 'availability', 'level': 'ask',
                                          'message': 'нема доказу відсутності'}
    assert veto.check(act(fields={'availability': 'not_available'}), CTX) == []
    assert veto.check(act(fields={'availability': 'under_the_order'}), ctx) == []


# ── режим і особисті дані ─────────────────────────────────────────────

def test_live_without_approval():
    p = veto.check(act(mode='live'), dict(CTX, approved=False))
    assert by_rule(p, 'live_without_approval')['level'] == 'ask'
    assert veto.check(act(mode='live'), CTX) == []
    assert veto.check(act(mode='test'), dict(CTX, approved=False)) == []


def test_personal_data_in_text():
    p = veto.check(act(text='Напишіть на 0671234567'), CTX)
    assert by_rule(p, 'personal_data')['level'] == 'stop'
    assert veto.check(act(text='Звичайний текст без контактів'), CTX) == []
    assert veto.check(act(text='пошта shop@example.com'), CTX) != []


# ── порядок, підсумок, звіт ───────────────────────────────────────────

def test_rules_order_and_single_entry_per_rule():
    p = veto.check(act(source='carvol', mode='live', fields={'price': 10, 'availability': 'нема'},
                       text='0671234567', files=['output/noire_epicentr_phase1.xml'],
                       kind='feed_content'), dict(CTX, approved=False))
    assert rules(p) == list(veto.RULES)
    assert len(rules(p)) == len(set(rules(p)))


def test_empty_action():
    assert veto.check({}, CTX) == [] and veto.verdict([]) == 'ok'


@pytest.mark.parametrize('levels,out', [
    ([], 'ok'), (['ask'], 'ask'), (['ask', 'stop'], 'stop'), (['stop'], 'stop'),
])
def test_verdict(levels, out):
    assert veto.verdict([{'rule': 'r', 'level': l, 'message': 'm'} for l in levels]) == out


def test_report_stop():
    a = act(fields={'price': 100})
    lines = veto.report(a, veto.check(a, CTX)).splitlines()
    assert lines[0] == '🛑 Зупинено'
    assert lines[1] == 'price_update · SO3142 · rozetka'
    assert lines[2] == '• price_floor: ціна 100.00 нижча за поріг 120.00'


def test_report_ask_and_ok():
    a = act(mode='live')
    assert veto.report(a, veto.check(a, dict(CTX, approved=False))).splitlines()[0] == \
        '❓ Потрібне підтвердження'
    assert veto.report({}, []).splitlines() == ['✅ Перешкод немає']
