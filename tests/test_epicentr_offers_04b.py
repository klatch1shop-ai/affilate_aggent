"""Приймальні тести TASK-04b: три прогалини TASK-04.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

eo = importlib.import_module('sync.epicentr_offers')
D = Decimal
NOW = datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)


def store():
    return eo.SentStore()


def item(sku='SO1', price=100, availability='in_stock'):
    return {'sku': sku, 'price': price, 'availability': availability}


# ── прогалина 1: pending старше 14 діб ──────────────────────────────────

def test_pending_requests_needs_tz_aware_now():
    st = store()
    with pytest.raises(ValueError):
        st.pending_requests(datetime(2026, 9, 25))


def test_fresh_pending_returned():
    st = store()
    st.mark_pending('r1', [item()], NOW)
    assert st.pending_requests(NOW) == ['r1']
    assert st.pending_requests(NOW + timedelta(days=13, hours=23)) == ['r1']


def test_stale_pending_excluded_and_marked():
    st = store()
    st.mark_pending('r1', [item(), item(sku='SO2')], NOW)
    later = NOW + timedelta(days=14, minutes=1)
    assert st.pending_requests(later) == []
    row = st.connection.execute(
        "SELECT status FROM pending WHERE request_id='r1' AND sku='SO1'").fetchone()
    assert row[0] == 'stale'
    row2 = st.connection.execute(
        "SELECT status FROM pending WHERE request_id='r1' AND sku='SO2'").fetchone()
    assert row2[0] == 'stale'


def test_stale_boundary_exactly_14_days_still_fresh():
    st = store()
    st.mark_pending('r1', [item()], NOW)
    assert st.pending_requests(NOW + timedelta(days=14)) == ['r1']


def test_stale_uses_earliest_at_of_the_request():
    st = store()
    st.mark_pending('r1', [item(sku='SO1')], NOW)
    st.mark_pending('r1', [item(sku='SO2')], NOW + timedelta(days=10))
    # найраніший at (NOW) визначає застарілість усього request_id
    assert st.pending_requests(NOW + timedelta(days=14, minutes=1)) == []


def test_stale_after_days_param_zero():
    st = store()
    st.mark_pending('r1', [item()], NOW)
    assert st.pending_requests(NOW + timedelta(seconds=1), stale_after_days=0) == []


def test_run_skips_stale_pending_without_querying_client():
    st = store()
    st.mark_pending('r1', [item(sku='SO1', price=None, availability=None)],
                    NOW - timedelta(days=20))

    class Client:
        def submit(self, payload):
            raise AssertionError('не має викликатись — товарів на відправку немає')

        def results(self, request_id):
            raise AssertionError('застарілий request_id не має опитуватись')

    report = eo.run([], st, Client(), mode='live')
    assert 'stale' in report['by_status'] and report['by_status']['stale'] == 0
    assert report['stopped'] is False


# ── прогалина 2: forbidden відкладається ────────────────────────────────

def resp(request_id, entries):
    return {'requestId': request_id,
            'items': [{'sku': sku, 'status': status} for sku, status in entries]}


def test_apply_results_forbidden_needs_tz_aware_now():
    st = store()
    st.mark_pending('r1', [item()], NOW)
    parsed = eo.parse_results(resp('r1', [('SO1', 'forbidden')]))
    with pytest.raises(ValueError):
        st.apply_results(parsed, datetime(2026, 9, 25))


def test_forbidden_recorded_and_map():
    st = store()
    st.mark_pending('r1', [item(sku='SO1', price=150, availability='in_stock')], NOW)
    parsed = eo.parse_results(resp('r1', [('SO1', 'forbidden')]))
    st.apply_results(parsed, NOW)
    fm = st.forbidden_map()
    assert fm == {'SO1': {'price': D('150'), 'availability': 'in_stock'}}


def test_diff_skips_same_forbidden_value():
    desired = {'SO1': {'price': D('150'), 'availability': 'in_stock'}}
    forbidden = {'SO1': {'price': D('150'), 'availability': 'in_stock'}}
    assert eo.diff(desired, {}, forbidden) == []


def test_diff_retries_when_desired_changed():
    desired = {'SO1': {'price': D('160'), 'availability': 'in_stock'}}
    forbidden = {'SO1': {'price': D('150'), 'availability': 'in_stock'}}
    out = eo.diff(desired, {}, forbidden)
    assert out == [{'sku': 'SO1', 'price': D('160'), 'availability': 'in_stock'}]


def test_diff_default_forbidden_none_is_backward_compatible():
    desired = {'SO1': {'price': D('150'), 'availability': 'in_stock'}}
    assert eo.diff(desired, {}) == [{'sku': 'SO1', 'price': D('150'), 'availability': 'in_stock'}]


def test_forbidden_does_not_block_processed_sku_later():
    st = store()
    st.mark_pending('r1', [item(sku='SO1', price=150, availability='in_stock')], NOW)
    st.apply_results(eo.parse_results(resp('r1', [('SO1', 'forbidden')])), NOW)
    # той самий SKU пізніше успішно пройшов з ІНШОЮ ціною
    st.mark_pending('r2', [item(sku='SO1', price=200, availability='in_stock')], NOW)
    st.apply_results(eo.parse_results(resp('r2', [('SO1', 'processed')])), NOW)
    assert st.get_all()['SO1']['price'] == D('200')
    # forbidden-запис лишається (не видаляється), але з desired=200 більше не збігається
    desired = {'SO1': {'price': D('200'), 'availability': 'in_stock'}}
    assert eo.diff(desired, st.get_all(), st.forbidden_map()) == []  # уже sent == desired


# ── прогалина 3: нормалізація sku у відповіді ───────────────────────────

@pytest.mark.parametrize('raw,expected', [(' SO1 ', 'SO1'), ('SO2\t', 'SO2'), ('SO3', 'SO3')])
def test_parse_results_strips_sku_whitespace(raw, expected):
    parsed = eo.parse_results(resp('r1', [(raw, 'processed')]))
    assert parsed['by_status']['processed'] == [expected]


def test_parse_results_strips_sku_in_errors_key():
    body = {'requestId': 'r1', 'items': [{'sku': ' SO1 ', 'status': 'forbidden',
                                          'errors': ['артикул не знайдено']}]}
    parsed = eo.parse_results(body)
    assert 'SO1' in parsed['errors'] and ' SO1 ' not in parsed['errors']


def test_parse_results_strips_sku_from_id_fallback():
    body = {'requestId': 'r1', 'items': [{'id': ' 123 ', 'status': 'skipped'}]}
    parsed = eo.parse_results(body)
    assert parsed['by_status']['skipped'] == ['123']
