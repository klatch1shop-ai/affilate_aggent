"""Приймальні тести TASK-11: нові команди читання в боті.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

commands = importlib.import_module('tg_dispatcher.ai_brain.commands')
catalog = importlib.import_module('tg_dispatcher.ai_brain.catalog')
views = importlib.import_module('tg_dispatcher.ai_brain.views')
services = importlib.import_module('helper.services')


# Дата «вчора» рахується під час запуску: із зашитою датою тест «виконані замовлення
# вчора» зеленів лише в один конкретний день (упав 21.09, коли вчора стало 20.09).
YESTERDAY = (datetime.now(ZoneInfo('Europe/Kyiv')) - timedelta(days=1)).strftime('%Y-%m-%d 10:00:00')


def order(oid, group, ttn=None, amount='100.00'):
    return {'id': oid, 'created': YESTERDAY, 'status': 1, 'status_group': group, 'amount': amount,
            'cost': amount, 'ttn': ttn, 'total_quantity': 1, 'purchases': []}


class FakeRz:
    SOURCES = {'dropoffice': 55861, 'toptul': 55634, 'noire': 54788, 'carvol': 51949}

    def __init__(self):
        self.calls = []

    def order_counts(self):
        return {'new': 2, 'not_done': 25, 'delivering': None, 'done': 59, 'unwatched': 0}

    def orders(self, types):
        self.calls.append(('orders', types))
        return [order(906000001, 2), order(906000002, 3), order(906000003, 1, ttn='20451539117101'),
                order(906000004, 1)]

    def active_orders(self):
        return []

    def order(self, oid):
        return order(int(oid), 1)

    def refunds(self):
        return [{'id': 'R1', 'status_title': 'Нова', 'reason_title': 'Повернення', 'order_id': 906372863,
                 'item_name': 'CAN-адаптер', 'item_id': 1, 'datetime': '2026-09-19 22:48:00', 'read': False}]

    def return_tickets(self):
        return [{'id': 42, 'order_id': 906111111, 'carrier': 'nova_poshta', 'ttn': '20450123456789', 'status': 1,
                 'expires_at': '2026-09-30 12:00:00', 'items': []}]

    def refund_for_order(self, oid):
        self.calls.append(('refund_for_order', oid))
        return [dict(self.refunds()[0], order_date='2026-09-18', chat_id=1, sub_reason_title='Не підійшов',
                     sub_reason_comment='авто Mazda', decision_title='Повернення', sub_decision_title='Зв’язатися')]

    def item_comments(self):
        return [{'id': 1, 'type': 'question', 'created': '2026-09-05 22:25:16', 'status': 'active', 'read': False,
                 'mark': 0, 'has_answer': False, 'title': 'Питання', 'article': 'QBR-A0008',
                 'item_name': 'CAN-адаптер', 'text': 'Чи підійде на Mazda? 0671234567'},
                {'id': 2, 'type': 'comment', 'created': '2026-06-07 10:00:00', 'status': 'active', 'read': True,
                 'mark': 5, 'has_answer': True, 'title': 'Відгук', 'article': 'X', 'item_name': 'Y', 'text': 'Супер'}]

    def shop_reviews(self):
        return [{'id': 9, 'order_id': 906000009, 'vote': 'like', 'status': 'active', 'created_at': '2026-09-01',
                 'read': True, 'problem_solved': None, 'comment': 'Швидко', 'reply': None}]

    def balance(self):
        return {'balance': '2409.46', 'sum_in_gray': '1753.56', 'subscription_balance': '240.00'}

    def goods_count(self, tab, source=None):
        self.calls.append(('goods_count', tab, source))
        return {'moderation': 5917, 'errors': 0, 'hidden': 3}[tab]


def fx(**extra):
    rz = FakeRz()
    deps = dict(rozetka=rz,
                unanswered=lambda: [{'marketplace': 'rozetka', 'chat_id': '42', 'buyer_name': 'X', 'waiting_min': 2256}],
                backup_status=lambda: {'last': '2026-09-20 04:00', 'size_mb': 31.0, 'age_h': 5.2, 'ok': True},
                supplier_stock=lambda article: {'article': article, 'state': 'unknown', 'qty': None, 'price': None},
                supplier_ttn=lambda: [],
                orders_without_ttn=lambda: [{'id': 906000004, 'created': '2026-09-19 10:00', 'source': 'toptul'}],
                ttn_stuck=lambda: [])
    deps.update(extra)
    return services.build_fetchers(**deps), rz


def ask(text, **extra):
    f, rz = fx(**extra)
    return services.answer(text, f), rz


# ── реєстр ───────────────────────────────────────────────────────────

def test_old_registry_untouched_and_all_commands():
    assert len(commands.COMMANDS) == 8
    new = set(catalog.CATALOG) - set(commands.COMMANDS)
    assert new <= set(commands.ALL_COMMANDS)
    for i in new:
        c = commands.ALL_COMMANDS[i]
        assert c['needs'] == catalog.CATALOG[i]['needs'] and c['fetcher'] == i and c['title']


def test_label_and_buyer_rating_not_connected():
    f, _ = fx()
    assert 'label' not in f and 'buyer_rating' not in f
    out, _ = ask('етикетка 20451539117101')
    assert out.startswith('⚠️') and 'не підключена' in out


# ── відповіді ─────────────────────────────────────────────────────────

def test_orders_counts():
    out, _ = ask('скільки замовлень у роботі')
    assert 'Нових: 2' in out and 'Невиконані (скасовані): 25' in out and 'В дорозі: —' in out and 'Виконано: 59' in out


@pytest.mark.parametrize('phrase,shown,hidden', [
    ('скасовані замовлення за тиждень', ['906000002'], ['906000001', '906000003', '906000004']),
    ('виконані замовлення вчора', ['906000001'], ['906000002', '906000003']),
    ('які замовлення в дорозі', ['906000003'], ['906000004', '906000001']),
])
def test_orders_search_filters_by_status_group(phrase, shown, hidden):
    out, rz = ask(phrase)
    assert ('orders', 1) in rz.calls
    for s in shown:
        assert s in out
    for h in hidden:
        assert h not in out


def test_orders_without_ttn_and_empty_variants():
    out, _ = ask('замовлення без ттн')
    assert 'Без ТТН: 1' in out and '906000004' in out and 'toptul' in out
    out, _ = ask('замовлення без ттн', orders_without_ttn=lambda: [])
    assert '✅ Усі замовлення мають ТТН' in out
    out, _ = ask('посилки без руху')
    assert '✅ Посилок без руху немає' in out


def test_refunds_merge_kinds():
    out, _ = ask('повернення')
    assert 'Повернення: 2' in out
    assert '906372863' in out and 'CAN-адаптер' in out and 'Нова' in out
    assert '906111111' in out and '20450123456789' in out


def test_refund_detail():
    out, rz = ask('повернення по 906372863')
    assert ('refund_for_order', '906372863') in rz.calls
    assert 'Не підійшов' in out and 'Повернення' in out and 'CAN-адаптер' in out


def test_item_comments_masks_and_marks_new():
    out, _ = ask('нові відгуки')
    assert 'Питання й відгуки: 2 (нових: 1)' in out
    assert '🆕' in out and '0671234567' not in out and 'Mazda' in out


def test_shop_reviews():
    out, _ = ask('відгуки про магазин')
    assert 'Відгуки про магазин: 1' in out and '👍' in out and '906000009' in out


def test_unanswered_duration_format():
    out, _ = ask('хто чекає відповіді')
    assert 'Без відповіді: 1' in out and 'чат 42' in out and '1 д 13 год' in out
    out, _ = ask('хто чекає відповіді', unanswered=lambda: [])
    assert '✅ Усім покупцям відповіли' in out


@pytest.mark.parametrize('minutes,text', [(45, '45 хв'), (125, '2 год 5 хв'), (2256, '1 д 13 год')])
def test_duration_helper(minutes, text):
    out = views.FORMATTERS['unanswered_chats'](
        [{'marketplace': 'rozetka', 'chat_id': '1', 'buyer_name': '', 'waiting_min': minutes}], {})
    assert text in out


def test_moderation_phrase_source_and_tab():
    out, rz = ask('модерація toptul')            # розбір дає source=toptul, goods_tab=moderation
    assert 'toptul' in out and '5917' in out and 'dropoffice' not in out
    assert [c[1:] for c in rz.calls if c[0] == 'goods_count'] == [('moderation', 'toptul')]


def test_moderation_fetcher_without_tab_takes_all_three():
    f, rz = fx()
    res = f['moderation'](source='toptul')
    assert res == {'toptul': {'moderation': 5917, 'errors': 0, 'hidden': 3}}


def test_moderation_all_sources_one_tab():
    out, rz = ask('товари на модерації')
    gc = [c for c in rz.calls if c[0] == 'goods_count']
    assert {c[2] for c in gc} == set(FakeRz.SOURCES) and {c[1] for c in gc} == {'moderation'}


@pytest.mark.parametrize('state,word', [('in_stock', 'є'), ('out', 'немає'), ('unknown', 'невідомо')])
def test_supplier_stock_three_states(state, word):
    out, _ = ask('є у постачальника KAAA1404',
                 supplier_stock=lambda article: {'article': article, 'state': state, 'qty': None, 'price': None})
    assert 'KAAA1404' in out and word in out.lower()


def test_supplier_stock_sku_passed_as_article():
    seen = {}

    def ss(article):
        seen['a'] = article
        return {'article': article, 'state': 'in_stock', 'qty': 3, 'price': '100'}
    ask('наявність у постачальника SO3270', supplier_stock=ss)
    assert seen['a'] == 'SO3270'


def test_supplier_ttn_empty():
    out, _ = ask('ттн від постачальників')
    assert 'ТТН сьогодні ще не надходили' in out


def test_balance_and_backup():
    out, _ = ask('баланс розетки')
    assert 'Баланс: 2409.46 грн' in out and 'Заблоковано: 1753.56 грн' in out
    out, _ = ask('коли був бекап')
    assert '✅' in out and '2026-09-20 04:00' in out
    out, _ = ask('бекап', backup_status=lambda: {'last': None, 'size_mb': None, 'age_h': None, 'ok': False})
    assert '❌ Бекапів не знайдено' in out


def test_help_is_catalog():
    assert commands.fmt_help() == catalog.help_text()


def test_missing_dependency_says_not_connected():
    f, _ = fx(backup_status=None)
    assert 'backup_status' not in f
    out = services.answer('бекап', f)
    assert out.startswith('⚠️') and 'не підключена' in out


def test_orders_search_respects_period():
    """Живий прогін 20.09: період ігнорувався — «за тиждень» показувало все."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    assert services._period_start('week', datetime(2026, 9, 20, 10, 0, tzinfo=ZoneInfo('Europe/Kyiv'))) == '2026-09-13 00:00:00'
    assert services._period_start(None) is None
    fresh = (datetime.now(ZoneInfo('Europe/Kyiv')) - timedelta(days=1)).strftime('%Y-%m-%d 10:00:00')

    class Rz(FakeRz):
        def orders(self, types):
            return [dict(order(906000010, 3), created='2020-01-01 10:00:00'),
                    dict(order(906000011, 3), created=fresh)]
    f = services.build_fetchers(rozetka=Rz())
    assert [o['id'] for o in f['orders_search'](status='cancelled', period='week')] == [906000011]
    assert [o['id'] for o in f['orders_search'](status='cancelled')] == [906000010, 906000011]
