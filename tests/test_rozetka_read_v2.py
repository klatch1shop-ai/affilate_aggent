"""Приймальні тести TASK-10: нові методи читання адаптера Rozetka.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib

import pytest

rz = importlib.import_module('integrations.rozetka')
errors = importlib.import_module('integrations.errors')


class FakeGet:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, params, headers):
        self.calls.append((url.split('.com.ua', 1)[-1], dict(params or {})))
        path = url.split('.com.ua', 1)[-1]
        return self.routes[path].pop(0)


def ok(content):
    return 200, {'success': True, 'content': content}


def client(routes, **kw):
    g = FakeGet(routes)
    return rz.RozetkaClient(g, 'TOKEN', lambda s: None, **kw), g


PII = ('Іваненко', 'Іван', '+380671234567', '0671234567', '4321', 'UA213223130000026007233566001', 'buyer@mail.example')


def assert_no_pii(obj):
    flat = repr(obj)
    for s in PII:
        assert s not in flat, s


REFUND = {'id': 'R1', 'status_title': 'Нова', 'reason_title': 'Повернення', 'order_id': 906372863,
          'item_name': 'CAN-адаптер', 'item_id': 777, 'datetime': '2026-09-19 22:48:00', 'read': False,
          'delivery_id': 7, 'buyer_surname': 'Іваненко', 'buyer_name': 'Іван', 'buyer_patronymic': 'Іванович',
          'buyer_phone': '+380671234567'}
REFUND_DETAIL = dict(REFUND, order_date='2026-09-18 09:46:44', chat_id=115089894,
                     sub_reason_title='Не підійшов', sub_reason_comment='дзвоніть 0671234567',
                     decision_title='Повернення', sub_decision_title="Зв'яжіться зі мною",
                     card_last_digits=4321, iban='UA213223130000026007233566001')


def test_order_counts_mapping():
    c, _ = client({'/orders/counts': [ok({'unwatched': 0, 'new': 2, 'inNotDone': 25, 'delivering': 3, 'inDone': 59})]})
    assert c.order_counts() == {'new': 2, 'in_work': 25, 'delivering': 3, 'done': 59, 'unwatched': 0}
    c2, _ = client({'/orders/counts': [ok({'new': 1})]})
    assert c2.order_counts() == {'new': 1, 'in_work': None, 'delivering': None, 'done': None, 'unwatched': None}


def test_clean_refund_whitelist():
    r = rz.clean_refund(REFUND)
    assert set(r) == set(rz.REFUND_FIELDS)
    assert r['order_id'] == 906372863 and r['item_name'] == 'CAN-адаптер'
    assert_no_pii(r)
    d = rz.clean_refund(REFUND_DETAIL, detail=True)
    assert set(d) == set(rz.REFUND_DETAIL_FIELDS)
    assert d['chat_id'] == 115089894 and '0671234567' not in d['sub_reason_comment']
    assert_no_pii(d)
    assert rz.clean_refund({'id': 'X'})['order_id'] is None


def test_refunds_pagination_and_empty():
    c, g = client({'/order-refund/search': [ok({'orderRefunds': [REFUND], '_meta': {'pageCount': 2}}),
                                            ok({'orderRefunds': [dict(REFUND, id='R2')], '_meta': {'pageCount': 2}})]})
    out = c.refunds()
    assert [r['id'] for r in out] == ['R1', 'R2'] and [p['page'] for _, p in g.calls] == [1, 2]
    assert_no_pii(out)
    c2, g2 = client({'/order-refund/search': [ok({'orderRefunds': [], '_meta': {'pageCount': 0}})]})
    assert c2.refunds() == [] and len(g2.calls) == 1


def test_refunds_too_many_pages_error():
    c, _ = client({'/order-refund/search': [ok({'orderRefunds': [REFUND], '_meta': {'pageCount': 50}})]}, max_pages=3)
    with pytest.raises(errors.ApiError):
        c.refunds()


def test_refund_detail_and_for_order():
    c, g = client({'/order-refund/detail/R1': [ok(REFUND_DETAIL)],
                   '/order-refund/search': [ok({'orderRefunds': [REFUND], '_meta': {'pageCount': 1}})]})
    d = c.refund_detail('R1')
    assert d['decision_title'] == 'Повернення'
    assert_no_pii(d)
    out = c.refund_for_order('906372863')
    assert out[0]['id'] == 'R1'
    assert g.calls[1] == ('/order-refund/search', {'order_id': '906372863', 'page': 1})
    for bad in ('', None):
        with pytest.raises(ValueError):
            c.refund_detail(bad)
    with pytest.raises(ValueError):
        c.refund_for_order('123')


def test_return_tickets_shape():
    t = {'id': 42, 'order_id': 906372863, 'carrier': 'nova_poshta', 'ttn': '20450123456789', 'status': 1,
         'expires_at': '2026-09-30 12:00:00', 'buyer_phone': '+380671234567',
         'items': [{'id': 1, 'purchase_id': 5, 'item_id': 7, 'name': 'CAN-адаптер', 'qty_expected': 1,
                    'qty_received': 0, 'status': 0, 'price': '550.00'}]}
    c, _ = client({'/item-return/ticket/search': [ok({'tickets': [t], '_meta': {'pageCount': 1}})]})
    out = c.return_tickets()
    assert out == [{'id': 42, 'order_id': 906372863, 'carrier': 'nova_poshta', 'ttn': '20450123456789',
                    'status': 1, 'expires_at': '2026-09-30 12:00:00',
                    'items': [{'name': 'CAN-адаптер', 'qty_expected': 1, 'qty_received': 0, 'status': 0}]}]


COMMENT = {'id': 64420929, 'type': 'question', 'created': '2026-09-05 22:25:16', 'status': 'auto_activated',
           'text': 'Чи підійде на Mazda? тел 067 123 45 67', 'mark': 0, 'is_reade': False, 'has_children': False,
           'record': {'id': '1', 'title': 'Питання про CAN-адаптер'}, 'name': 'Іван', 'email': 'buyer@mail.example',
           'user_id': 'u1', 'item': {'article': 'QBR-A0008', 'name_ua': 'CAN-адаптер укр', 'name': 'CAN-адаптер'}}


def test_clean_comment():
    c = rz.clean_comment(COMMENT)
    assert c == {'id': 64420929, 'type': 'question', 'created': '2026-09-05 22:25:16', 'status': 'auto_activated',
                 'read': False, 'mark': 0, 'has_answer': False, 'title': 'Питання про CAN-адаптер',
                 'article': 'QBR-A0008', 'item_name': 'CAN-адаптер укр',
                 'text': 'Чи підійде на Mazda? тел [телефон приховано]'}
    assert_no_pii(c)


def test_item_comments_list():
    c, _ = client({'/item-comments/search': [ok({'itemComments': [COMMENT], '_meta': {'pageCount': 1}})]})
    out = c.item_comments()
    assert out[0]['type'] == 'question'
    assert_no_pii(out)


def test_clean_review_and_list():
    r = {'id': 6098971, 'order_id': 906000001, 'vote': 'like', 'status': 'active', 'created_at': '2026-09-01 10:00:00',
         'read': True, 'problem_solved': None, 'comment': 'Все супер, дзвоніть 0671234567', 'reply': 1, 'user': 'Іван'}
    cr = rz.clean_review(r)
    assert cr['comment'] == 'Все супер, дзвоніть [телефон приховано]' and cr['reply'] is None
    assert set(cr) == {'id', 'order_id', 'vote', 'status', 'created_at', 'read', 'problem_solved', 'comment', 'reply'}
    assert_no_pii(cr)
    c, _ = client({'/market-reviews/search': [ok({'marketReviews': [r], '_meta': {'pageCount': 1}})]})
    assert c.shop_reviews()[0]['vote'] == 'like'


def test_balance():
    c, _ = client({'/balances/total': [ok({'totalBalance': [{'balance': '2409.46', 'sumInGray': '1753.56',
                                                             'subscription_balance': '240.00'}]})]})
    assert c.balance() == {'balance': '2409.46', 'sum_in_gray': '1753.56', 'subscription_balance': '240.00'}
    c2, _ = client({'/balances/total': [ok({'totalBalance': []})]})
    with pytest.raises(errors.ApiError):
        c2.balance()


def test_goods_count_with_source():
    c, g = client({'/goods/moderation': [ok({'count': 20, 'items': [], '_meta': {'totalCount': 5917}})],
                   '/goods/errors': [ok({'items': [], '_meta': {'totalCount': 0}})]})
    assert c.goods_count('moderation', 'toptul') == 5917
    assert g.calls[0] == ('/goods/moderation', {'page': 1, 'sync_source_id': 55634})
    assert c.goods_count('errors') == 0
    assert g.calls[1] == ('/goods/errors', {'page': 1})
    for bad in (('archive', None), ('moderation', 'unknown')):
        with pytest.raises(ValueError):
            c.goods_count(*bad)


def test_goods_count_missing_meta_is_error():
    c, _ = client({'/goods/hidden': [ok({'items': []})]})
    with pytest.raises(errors.ApiError):
        c.goods_count('hidden')


def test_messages_counts():
    c, _ = client({'/messages/counts': [ok({'ordersChatUnread': 1, 'itemsChatAll': 20, 'feedback': {'all': 4}})]})
    assert c.messages_counts() == {'ordersChatUnread': 1, 'itemsChatAll': 20}


def test_auth_error_still_raised():
    c, _ = client({'/orders/counts': [(200, {'success': False, 'errors': {'code': 1020, 'message': 'incorrect_access_token'}})]})
    with pytest.raises(errors.AuthError):
        c.order_counts()
