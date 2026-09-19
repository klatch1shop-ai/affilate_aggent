"""Приймальні тести TASK-04: синхронізація цін і наявності з Епіцентром.

Написані замовником ДО виконання. Виконавець їх не змінює.
"""
import importlib
from datetime import datetime, timezone
from decimal import Decimal

import pytest

eo = importlib.import_module('sync.epicentr_offers')
D = Decimal
AT = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def row(sku, price=100, floor=None, available=True):
    return {'sku': sku, 'price': price, 'floor': floor, 'available': available}


# ── to_price ──────────────────────────────────────────────────────────

@pytest.mark.parametrize('value,expected', [
    (1499, D('1499.00')), (163.555, D('163.56')), ('163,50', D('163.50')),
    ('99.9', D('99.90')), (D('10'), D('10.00')),
])
def test_to_price_ok(value, expected):
    assert eo.to_price(value) == expected


@pytest.mark.parametrize('value', [None, '', 'абв', 0, -5, '0,00'])
def test_to_price_bad(value):
    assert eo.to_price(value) is None


# ── desired_state ─────────────────────────────────────────────────────

def test_desired_availability_three_states():
    desired, blocked = eo.desired_state([row('A', available=True), row('B', available=False),
                                         row('C', available=None)])
    assert desired['A'] == {'price': D('100.00'), 'availability': 'in_stock'}
    assert desired['B']['availability'] == 'not_available'
    assert desired['C'] == {'price': D('100.00'), 'availability': None}
    assert blocked == []


def test_desired_below_floor_blocked_entirely():
    desired, blocked = eo.desired_state([row('A', price=90, floor=100), row('B', price=100, floor=100)])
    assert 'A' not in desired
    assert {'sku': 'A', 'reason': 'below_floor'} in blocked
    assert desired['B']['price'] == D('100.00')


def test_desired_bad_price_keeps_availability():
    desired, blocked = eo.desired_state([row('A', price='ціна?', floor=50, available=False)])
    assert desired['A'] == {'price': None, 'availability': 'not_available'}
    assert blocked == []


def test_desired_nothing_to_send_and_no_sku():
    desired, blocked = eo.desired_state([row('A', price=None, available=None), row('  ', price=10)])
    assert desired == {}
    reasons = sorted(b['reason'] for b in blocked)
    assert reasons == ['no_sku', 'nothing_to_send']


def test_desired_strip_and_last_wins():
    desired, _ = eo.desired_state([row(' SO1 ', price=10), row('SO1', price=20)])
    assert list(desired) == ['SO1']
    assert desired['SO1']['price'] == D('20.00')


# ── diff ──────────────────────────────────────────────────────────────

def test_diff_only_changed_fields_sorted():
    desired = {'B': {'price': D('10.00'), 'availability': 'in_stock'},
               'A': {'price': D('20.00'), 'availability': 'not_available'},
               'C': {'price': D('30.00'), 'availability': 'in_stock'}}
    sent = {'A': {'price': D('20.00'), 'availability': 'in_stock'},
            'B': {'price': D('11.00'), 'availability': 'in_stock'},
            'C': {'price': D('30.00'), 'availability': 'in_stock'}}
    assert eo.diff(desired, sent) == [{'sku': 'A', 'availability': 'not_available'},
                                      {'sku': 'B', 'price': D('10.00')}]


def test_diff_new_sku_and_none_fields_never_sent():
    desired = {'N': {'price': D('5.00'), 'availability': None},
               'M': {'price': None, 'availability': 'in_stock'}}
    sent = {'M': {'price': D('7.00'), 'availability': 'not_available'}}
    assert eo.diff(desired, sent) == [{'sku': 'M', 'availability': 'in_stock'},
                                      {'sku': 'N', 'price': D('5.00')}]


# ── batches / payload ─────────────────────────────────────────────────

def test_batches():
    items = [{'sku': str(i)} for i in range(450)]
    parts = eo.batches(items)
    assert [len(p) for p in parts] == [200, 200, 50]
    assert eo.batches([]) == []
    with pytest.raises(ValueError):
        eo.batches(items, size=0)


def test_build_payload():
    p = eo.build_payload([{'sku': 'A', 'price': D('163.56'), 'availability': 'in_stock'},
                          {'sku': 'B', 'availability': 'not_available'},
                          {'sku': 'C', 'price': D('1499.00')}])
    assert p == {'items': [
        {'sku': 'A', 'prices': {'price': 163.56}, 'availability': 'in_stock'},
        {'sku': 'B', 'availability': 'not_available'},
        {'sku': 'C', 'prices': {'price': 1499.0}},
    ]}
    assert 'oldPrice' not in repr(p)


# ── parse_results ─────────────────────────────────────────────────────

def resp(*items, rid='req-1'):
    return {'total': len(items), 'requestId': rid,
            'items': [{'id': i, 'idType': 'sku', 'status': st, 'errors': er, 'sku': sku}
                      for i, (sku, st, er) in enumerate(items, 1)]}


def test_parse_results():
    r = eo.parse_results(resp(('A', 'processed', None), ('B', 'forbidden', {'prices': ['validation.positive']}),
                              ('C', 'enqueued', None), ('D', 'skipped', None), ('E', 'mystery', None),
                              (None, 'processed', None)))
    assert r['request_id'] == 'req-1'
    assert r['by_status']['processed'] == ['A', '6']
    assert r['by_status']['forbidden'] == ['B']
    assert r['by_status']['enqueued'] == ['C'] and r['by_status']['skipped'] == ['D']
    assert r['unknown'] == ['E']
    assert r['errors'] == {'B': {'prices': ['validation.positive']}}


def test_parse_results_malformed():
    with pytest.raises(eo.EpicentrError):
        eo.parse_results({'total': 0})


# ── SentStore ─────────────────────────────────────────────────────────

def test_store_lifecycle():
    s = eo.SentStore()
    assert s.get_all() == {}
    s.mark_pending('r1', [{'sku': 'A', 'price': D('10.00'), 'availability': 'in_stock'},
                          {'sku': 'B', 'price': D('20.00')},
                          {'sku': 'C', 'availability': 'not_available'}], AT)
    assert s.pending_requests() == ['r1']
    s.apply_results(eo.parse_results(resp(('A', 'processed', None), ('B', 'forbidden', {'x': ['y']}),
                                          ('C', 'enqueued', None), rid='r1')))
    got = s.get_all()
    assert got['A'] == {'price': D('10.00'), 'availability': 'in_stock'}
    assert 'B' not in got                          # відхилене не підтверджується
    assert 'C' not in got                          # ще в черзі
    assert s.pending_requests() == ['r1']
    s.apply_results(eo.parse_results(resp(('C', 'skipped', None), rid='r1')))
    assert s.get_all()['C'] == {'price': None, 'availability': 'not_available'}
    assert s.pending_requests() == []


def test_store_confirms_only_sent_field():
    s = eo.SentStore()
    s.mark_pending('r1', [{'sku': 'A', 'price': D('10.00'), 'availability': 'in_stock'}], AT)
    s.apply_results(eo.parse_results(resp(('A', 'processed', None), rid='r1')))
    s.mark_pending('r2', [{'sku': 'A', 'price': D('12.00')}], AT)
    s.apply_results(eo.parse_results(resp(('A', 'processed', None), rid='r2')))
    assert s.get_all()['A'] == {'price': D('12.00'), 'availability': 'in_stock'}


def test_store_pending_order_and_persistence(tmp_path):
    path = str(tmp_path / 'sent.db')
    s = eo.SentStore(path)
    s.mark_pending('r1', [{'sku': 'A', 'price': D('1.00')}], AT)
    s.mark_pending('r2', [{'sku': 'B', 'price': D('2.00')}], AT)
    s2 = eo.SentStore(path)
    assert s2.pending_requests() == ['r1', 'r2']
    s2.apply_results(eo.parse_results(resp(('A', 'processed', None), rid='r1')))
    assert eo.SentStore(path).get_all()['A']['price'] == D('1.00')


# ── OffersClient ──────────────────────────────────────────────────────

class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)     # (status, body) по черзі
        self.calls = []

    def post(self, url, json, headers):
        self.calls.append(('POST', url, json, headers))
        return self.responses.pop(0)

    def get(self, url, headers):
        self.calls.append(('GET', url, None, headers))
        return self.responses.pop(0)


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def client(http, t=None, token='SECRET-TOKEN', **kw):
    t = t or FakeTime()
    return eo.OffersClient(http.post, http.get, token, t.clock, t.sleep, **kw)


def test_client_submit_and_results_urls_and_auth():
    http = FakeHTTP([(200, {'ok': 1}), (200, {'ok': 2})])
    c = client(http)
    assert c.submit({'items': []}) == {'ok': 1}
    assert c.results('abc') == {'ok': 2}
    (m1, u1, j1, h1), (m2, u2, _, h2) = http.calls
    assert (m1, u1, j1) == ('POST', 'https://merchant-api.epicentrm.com.ua/v1/offers', {'items': []})
    assert (m2, u2) == ('GET', 'https://merchant-api.epicentrm.com.ua/v1/offers/update-results/abc')
    assert h1['Authorization'] == 'Bearer SECRET-TOKEN' == h2['Authorization']


def test_client_requires_token():
    with pytest.raises(eo.EpicentrAuthError):
        client(FakeHTTP([]), token='')


def test_client_retries_429_and_5xx_with_backoff():
    t = FakeTime()
    http = FakeHTTP([(429, None), (503, None), (200, {'fine': True})])
    assert client(http, t).submit({'items': []}) == {'fine': True}
    assert t.slept == [1, 2]


def test_client_gives_up_after_max_retries():
    t = FakeTime()
    http = FakeHTTP([(500, None)] * 4)
    with pytest.raises(eo.EpicentrError):
        client(http, t, max_retries=3).submit({'items': []})
    assert t.slept == [1, 2, 4]
    assert len(http.calls) == 4


@pytest.mark.parametrize('status', [401, 403])
def test_client_auth_error_no_retry_no_token_leak(status):
    http = FakeHTTP([(status, {'message': 'denied'})])
    with pytest.raises(eo.EpicentrAuthError) as e:
        client(http).submit({'items': []})
    assert len(http.calls) == 1
    assert 'SECRET-TOKEN' not in str(e.value)


def test_client_other_status_error_has_code():
    with pytest.raises(eo.EpicentrError) as e:
        client(FakeHTTP([(404, {'code': 404})])).results('old')
    assert '404' in str(e.value)
    assert not isinstance(e.value, eo.EpicentrAuthError)


def test_client_rate_limit_sliding_window():
    t = FakeTime()
    http = FakeHTTP([(200, {})] * (eo.RATE_LIMIT + 1))
    c = client(http, t)
    for i in range(eo.RATE_LIMIT):
        c.submit({'items': []})
        t.now += 0.5                       # 120 запитів за 60 с
    assert t.slept == []
    c.submit({'items': []})                # 121-й: чекати, поки перший вийде з вікна
    assert len(t.slept) == 1
    assert t.slept[0] == pytest.approx(eo.RATE_WINDOW - eo.RATE_LIMIT * 0.5)


# ── run ───────────────────────────────────────────────────────────────

class FakeClient:
    def __init__(self, submit_plan=None, results_plan=None):
        self.submit_plan = list(submit_plan or [])     # виняток або функція(payload)->resp
        self.results_plan = dict(results_plan or {})
        self.submitted = []
        self.asked = []

    def submit(self, payload):
        self.submitted.append(payload)
        step = self.submit_plan.pop(0) if self.submit_plan else None
        if isinstance(step, Exception):
            raise step
        items = [(it['sku'], 'processed', None) for it in payload['items']]
        return resp(*items, rid=f'r{len(self.submitted)}')

    def results(self, rid):
        self.asked.append(rid)
        r = self.results_plan[rid]
        if isinstance(r, Exception):
            raise r
        return r


def test_run_bad_mode():
    with pytest.raises(ValueError):
        eo.run([], eo.SentStore(), FakeClient(), 'auto')


def test_run_off_and_dry_do_not_touch_http_or_store():
    rows = [row(f'S{i:03}', price=100 + i) for i in range(250)] + [row('LOW', price=1, floor=5)]
    for mode in ('off', 'dry'):
        s, c = eo.SentStore(), FakeClient()
        r = eo.run(rows, s, c, mode)
        assert c.submitted == [] and s.get_all() == {}
        assert r['changes'] == 250 and r['batches'] == 2 and r['sent'] == 0
        assert r['blocked'] == [{'sku': 'LOW', 'reason': 'below_floor'}]
    assert len(r['payloads']) == 2 and len(r['payloads'][0]['items']) == 200


def test_run_live_sends_then_nothing_second_time():
    rows = [row('A', price=10), row('B', price=20, available=False)]
    s, c = eo.SentStore(), FakeClient()
    r = eo.run(rows, s, c, 'live')
    assert r['sent'] == 2 and r['by_status'].get('processed') == 2 and r['errors'] == []
    r2 = eo.run(rows, s, c, 'live')
    assert r2['changes'] == 0 and len(c.submitted) == 1


def test_run_auth_error_stops_everything():
    rows = [row(f'S{i:03}') for i in range(450)]
    s = eo.SentStore()
    c = FakeClient(submit_plan=[None, eo.EpicentrAuthError('401')])
    r = eo.run(rows, s, c, 'live')
    assert len(c.submitted) == 2                   # третя пачка не пішла
    assert r['stopped'] is True and r['errors']
    assert len(s.get_all()) == 200


def test_run_other_error_skips_only_that_batch():
    rows = [row(f'S{i:03}') for i in range(450)]
    s = eo.SentStore()
    c = FakeClient(submit_plan=[eo.EpicentrError('500'), None, None])
    r = eo.run(rows, s, c, 'live')
    assert len(c.submitted) == 3 and r['stopped'] is False
    assert len(r['errors']) == 1 and len(s.get_all()) == 250


def test_run_collects_pending_results_first():
    s = eo.SentStore()
    s.mark_pending('old', [{'sku': 'A', 'price': D('10.00')}], AT)
    s.mark_pending('bad', [{'sku': 'B', 'price': D('20.00')}], AT)
    c = FakeClient(results_plan={'old': resp(('A', 'processed', None), rid='old'),
                                 'bad': eo.EpicentrError('404')})
    r = eo.run([row('A', price=10, available=None)], s, c, 'live')
    assert c.asked == ['old', 'bad']
    assert s.get_all()['A']['price'] == D('10.00')
    assert r['changes'] == 0                       # A вже підтверджено — слати нічого
    assert len(r['errors']) == 1
