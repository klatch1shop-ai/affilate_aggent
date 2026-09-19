"""Приймальні тести TASK-05: адаптери API лише для читання.

Написані замовником ДО виконання. Виконавець їх не змінює.
Усі дані вигадані; телефони — тестові.
"""
import importlib

import pytest

errors = importlib.import_module('integrations.errors')
retry = importlib.import_module('integrations.retry')
rz = importlib.import_module('integrations.rozetka')
np_ = importlib.import_module('integrations.novaposhta')
prom = importlib.import_module('integrations.prom')

TOKEN = 'TOKEN-SECRET-123'


class Sleep:
    def __init__(self):
        self.calls = []

    def __call__(self, s):
        self.calls.append(s)


class FakeGet:
    """Відповіді за шляхом (без BASE) і, за потреби, за сторінкою."""

    def __init__(self, routes):
        self.routes = routes           # path → list[(status, body) | Exception] по черзі
        self.calls = []

    def __call__(self, url, params, headers):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        path = url.split('.com.ua', 1)[-1] if '.com.ua' in url else url.split('/api/v1', 1)[-1]
        step = self.routes[path].pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def ok(content):
    return 200, {'success': True, 'content': content}


def fail(code, message='x', status=200):
    return status, {'success': False, 'errors': {'message': message, 'code': code, 'description': 'd'}}


def rz_order(oid, **kw):
    o = {'id': oid, 'created': '2026-09-19 10:00:00', 'status': 1, 'status_group': 1,
         'amount': '551.25', 'cost': '551.25', 'ttn': None, 'total_quantity': 2,
         'comment': 'дзвоніть 0671234567', 'user_phone': '380671234567',
         'recipient_phone': '380501112233', 'user_title': {'full_name': 'Покупець'},
         'recipient_title': {'full_name': 'Отримувач'}, 'items_photos': [],
         'purchases': [{'id': 1, 'item_id': 5, 'item_name': 'Назва позиції', 'quantity': 2,
                        'price': '275.63', 'cost': '551.25', 'ttn': None, 'status': 1,
                        'item': {'article': 'SO3270', 'name': 'Назва', 'name_ua': 'Назва укр',
                                 'price': '1', 'url': 'u', 'photo': []}}]}
    o.update(kw)
    return o


def page(orders, page_count, current=1):
    return ok({'orders': orders, '_meta': {'totalCount': len(orders), 'pageCount': page_count,
                                           'currentPage': current, 'perPage': 20}})


# ── errors / retry ────────────────────────────────────────────────────

def test_error_text_and_masking():
    e = errors.ApiError('rozetka', 'клієнт 067 123 45 67 не знайдений', code=77)
    assert str(e).startswith('rozetka: ')
    assert '(код 77)' in str(e)
    assert '123 45 67' not in str(e)
    assert issubclass(errors.AuthError, errors.ApiError)
    assert issubclass(errors.NotFound, errors.ApiError)


def test_retry_success_after_failures():
    s, n = Sleep(), {'i': 0}

    def fn():
        n['i'] += 1
        if n['i'] < 3:
            raise TimeoutError('t')
        return 'ok'
    assert retry.call_with_retry(fn, sleep=s) == 'ok'
    assert s.calls == [1, 2]


def test_retry_gives_up_and_other_errors_immediate():
    s = Sleep()
    with pytest.raises(ConnectionError):
        retry.call_with_retry(lambda: (_ for _ in ()).throw(ConnectionError('c')), sleep=s)
    assert s.calls == [1, 2, 4]
    s2 = Sleep()
    with pytest.raises(KeyError):
        retry.call_with_retry(lambda: {}['x'], sleep=s2)
    assert s2.calls == []


# ── Rozetka ───────────────────────────────────────────────────────────

def rz_client(routes, **kw):
    g = FakeGet(routes)
    return rz.RozetkaClient(g, TOKEN, Sleep(), **kw), g


def test_rz_requires_token():
    with pytest.raises(errors.AuthError):
        rz.RozetkaClient(FakeGet({}), '', Sleep())


def test_clean_order_whitelist_no_personal_data():
    c = rz.clean_order(rz_order(906298386))
    assert set(c) == set(rz.ORDER_FIELDS) | {'purchases'}
    assert c['amount'] == '551.25'
    p = c['purchases'][0]
    assert set(p) == set(rz.PURCHASE_FIELDS) | {'item'}
    assert p['item'] == {'article': 'SO3270', 'name': 'Назва укр'}
    flat = repr(c)
    for secret in ('380671234567', '380501112233', '0671234567', 'Покупець', 'Отримувач', 'дзвоніть'):
        assert secret not in flat


def test_clean_order_name_fallbacks_and_missing_fields():
    o = rz_order(906298386)
    o['purchases'][0]['item'].update(name_ua='', name='Рос назва')
    assert rz.clean_order(o)['purchases'][0]['item']['name'] == 'Рос назва'
    o['purchases'][0]['item'].update(name_ua=None, name=None)
    assert rz.clean_order(o)['purchases'][0]['item']['name'] == 'Назва позиції'
    bare = rz.clean_order({'id': 1})
    assert bare['ttn'] is None and bare['purchases'] == []


def test_rz_orders_pagination_params_and_headers():
    client, g = rz_client({'/orders/search': [page([rz_order(3)], 2), page([rz_order(2)], 2, 2)]})
    out = client.orders(1)
    assert [o['id'] for o in out] == [3, 2]
    (u1, p1, h1), (_, p2, _) = g.calls
    assert u1 == 'https://api-seller.rozetka.com.ua/orders/search'
    assert p1 == {'types': 1, 'page': 1, 'expand': 'purchases', 'sort': '-id'} and p2['page'] == 2
    assert h1['Authorization'] == f'Bearer {TOKEN}' and h1['Content-Language'] == 'uk'


def test_rz_orders_empty_page_count_zero():
    client, g = rz_client({'/orders/search': [page([], 0)]})
    assert client.orders(4) == []
    assert len(g.calls) == 1


def test_rz_orders_too_many_pages_is_error_not_truncation():
    client, _ = rz_client({'/orders/search': [page([rz_order(1)], 5)]}, max_pages=3)
    with pytest.raises(errors.ApiError) as e:
        client.orders(1)
    assert '5' in str(e.value)


@pytest.mark.parametrize('response', [fail(1020, 'incorrect_access_token'), fail(1004),
                                      fail(6001, 'session_expired', status=401), fail(5401)])
def test_rz_auth_errors(response):
    client, _ = rz_client({'/orders/search': [response]})
    with pytest.raises(errors.AuthError) as e:
        client.orders(4)
    assert TOKEN not in str(e.value)


def test_rz_other_errors():
    client, _ = rz_client({'/orders/search': [fail(1010, 'access_denied')],
                           '/orders/906298386': [fail(5404, 'not_found')],
                           '/messages/search': [(502, None)]})
    with pytest.raises(errors.ApiError) as e1:
        client.orders(4)
    assert not isinstance(e1.value, errors.AuthError) and e1.value.code == 1010
    with pytest.raises(errors.NotFound):
        client.order(906298386)
    with pytest.raises(errors.ApiError) as e3:
        client.chats_page(1)
    assert '502' in str(e3.value)


def test_rz_missing_content_is_error():
    client, _ = rz_client({'/orders/search': [(200, {'success': True})]})
    with pytest.raises(errors.ApiError):
        client.orders(4)


def test_rz_active_orders_merge_dedup_sorted():
    client, g = rz_client({'/orders/search': [page([rz_order(5), rz_order(3)], 1),
                                              page([rz_order(4), rz_order(3)], 1)]})
    assert [o['id'] for o in client.active_orders()] == [5, 4, 3]
    assert [c[1]['types'] for c in g.calls] == [4, 2]


def test_rz_order_validation_and_params():
    client, g = rz_client({'/orders/906298386': [ok(rz_order(906298386))]})
    assert client.order('906298386')['id'] == 906298386
    assert g.calls[0][1] == {'expand': 'purchases,delivery,payment'}
    for bad in ('12345', 'abc', 1234567890):
        with pytest.raises(ValueError):
            client.order(bad)


def test_rz_chats_passthrough():
    chats = {'chats': [{'id': 7, 'updated': '2026-09-19 10:00:00'}], '_meta': {'pageCount': 1}}
    chat = {'id': 7, 'messages': [{'id': 1, 'sender': 3, 'body': 'x', 'created': '2026-09-19 10:00:00'}]}
    client, g = rz_client({'/messages/search': [ok(chats)], '/messages/7': [ok(chat)]})
    assert client.chats_page(2) == chats
    assert client.chat(7) == chat
    assert g.calls[0][1] == {'page': 2} and g.calls[1][1] == {'expand': 'messages'}


def test_rz_transport_retry_then_error():
    client, g = rz_client({'/orders/search': [TimeoutError('t'), page([rz_order(1)], 1)]})
    assert len(client.orders(1)) == 1
    client2, _ = rz_client({'/orders/search': [ConnectionError('c')] * 4})
    with pytest.raises(errors.ApiError) as e:
        client2.orders(1)
    assert not isinstance(e.value, ConnectionError)


# ── Нова Пошта ────────────────────────────────────────────────────────

class FakePost:
    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    def __call__(self, url, json, headers):
        self.calls.append((url, json, headers))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


DOC = {'Number': '20451538685877', 'Status': 'Відправлення отримано', 'StatusCode': '9',
       'CityRecipient': 'Київ', 'WarehouseRecipient': 'Відділення №1',
       'ScheduledDeliveryDate': '20.09.2026', 'PhoneRecipient': '380671234567',
       'RecipientFullName': 'Тестовий Отримувач', 'PhoneSender': '380501112233',
       'SenderFullNameEW': 'Відправник', 'CashPaymentAmount': '100'}


def np_ok(doc=DOC):
    return 200, {'success': True, 'data': [doc] if doc else [], 'errors': [], 'warnings': []}


def np_err(*msgs):
    return 200, {'success': False, 'data': [], 'errors': list(msgs), 'warnings': []}


def np_client(steps):
    p, s = FakePost(steps), Sleep()
    return np_.NovaPoshtaClient(p, 'NP-KEY-SECRET', s), p, s


def test_np_requires_key():
    with pytest.raises(errors.AuthError):
        np_.NovaPoshtaClient(FakePost([]), None, Sleep())


def test_np_status_whitelist_and_request_body():
    c, p, _ = np_client([np_ok()])
    out = c.ttn_status('2045 1538 6858 77', phone='0671234567')
    assert out == {k: DOC[k] for k in np_.SAFE_FIELDS if k in DOC}
    assert 'PhoneRecipient' not in out and 'RecipientFullName' not in out
    url, body, _ = p.calls[0]
    assert url == np_.URL
    assert body['modelName'] == 'TrackingDocument' and body['calledMethod'] == 'getStatusDocuments'
    assert body['methodProperties'] == {'Documents': [{'DocumentNumber': '20451538685877',
                                                       'Phone': '0671234567'}]}
    assert body['apiKey'] == 'NP-KEY-SECRET'


@pytest.mark.parametrize('ttn', ['123', '2045153868587', '204515386858770', 'abcdefghijklmn'])
def test_np_bad_ttn(ttn):
    c, _, _ = np_client([])
    with pytest.raises(ValueError):
        c.ttn_status(ttn)


def test_np_rate_limit_retry_then_ok():
    c, _, s = np_client([np_err('To many requests'), np_err('to many requests, try later'), np_ok()])
    assert c.ttn_status('20451538685877')['Number'] == '20451538685877'
    assert s.calls == [5, 15]


def test_np_rate_limit_exhausted():
    c, _, s = np_client([np_err('To many requests')] * 4)
    with pytest.raises(errors.ApiError) as e:
        c.ttn_status('20451538685877')
    assert e.value.code == 'rate_limit' and s.calls == [5, 15, 30]


def test_np_empty_data_retry_then_not_found():
    c, _, _ = np_client([np_ok(None), np_ok()])
    assert c.ttn_status('20451538685877')['Status'] == DOC['Status']
    c2, _, _ = np_client([np_ok(None)] * 4)
    with pytest.raises(errors.NotFound):
        c2.ttn_status('20451538685877')


def test_np_other_errors():
    c, _, s = np_client([np_err('Document number is not correct', 'Телефон 0671234567 невірний')])
    with pytest.raises(errors.ApiError) as e:
        c.ttn_status('20451538685877')
    assert 'Document number is not correct' in str(e.value)
    assert '0671234567' not in str(e.value) and 'NP-KEY-SECRET' not in str(e.value)
    assert s.calls == []
    c2, _, _ = np_client([(500, None)])
    with pytest.raises(errors.ApiError):
        c2.ttn_status('20451538685877')


# ── Prom ──────────────────────────────────────────────────────────────

def prom_client(routes):
    g = FakeGet(routes)
    return prom.PromClient(g, TOKEN, Sleep()), g


def test_prom_messages_and_params():
    msgs = [{'id': 1, 'message': 'x', 'status': 'unread'}]
    c, g = prom_client({'/messages/list': [(200, {'messages': msgs}), (200, {'messages': []})]})
    assert c.messages() == msgs
    assert c.messages(limit=10, last_id=55) == []
    (u1, p1, h1), (_, p2, _) = g.calls
    assert u1 == 'https://my.prom.ua/api/v1/messages/list'
    assert p1 == {'limit': 100} and p2 == {'limit': 10, 'last_id': 55}
    assert h1['Authorization'] == f'Bearer {TOKEN}'


def test_prom_orders_status_param():
    c, g = prom_client({'/orders/list': [(200, {'orders': [{'id': 9}]})]})
    assert c.orders(limit=20, status='pending') == [{'id': 9}]
    assert g.calls[0][1] == {'limit': 20, 'status': 'pending'}


@pytest.mark.parametrize('status', [401, 403])
def test_prom_auth_error_not_empty_list(status):
    c, _ = prom_client({'/orders/list': [(status, {'error': 'Unauthorized'})]})
    with pytest.raises(errors.AuthError) as e:
        c.orders()
    assert TOKEN not in str(e.value)


def test_prom_bad_body_and_limits():
    c, _ = prom_client({'/messages/list': [(200, {'unexpected': []})], '/orders/list': [(500, None)]})
    with pytest.raises(errors.ApiError):
        c.messages()
    with pytest.raises(errors.ApiError):
        c.orders()
    for bad in (0, 101):
        with pytest.raises(ValueError):
            c.messages(limit=bad)
