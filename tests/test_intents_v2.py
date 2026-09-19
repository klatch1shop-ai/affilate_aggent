"""Приймальні тести TASK-09: розбір намірів v2 і каталог команд.

Написані замовником ДО виконання. Виконавець їх не змінює.
"""
import importlib

import pytest

intents = importlib.import_module('tg_dispatcher.ai_brain.intents')
catalog = importlib.import_module('tg_dispatcher.ai_brain.catalog')

NEW = [
    # (фраза, намір, очікувані параметри — підмножина)
    ('скільки замовлень у роботі', 'orders_counts', {}),
    ('кількість замовлень', 'orders_counts', {}),
    ('скільки заказов', 'orders_counts', {}),
    ('скасовані замовлення за тиждень', 'orders_search', {'status': 'cancelled', 'period': 'week'}),
    ('виконані замовлення вчора', 'orders_search', {'status': 'completed', 'period': 'yesterday'}),
    ('які замовлення в дорозі', 'orders_search', {'status': 'delivering'}),
    ('замовлення без ттн', 'orders_without_ttn', {}),
    ('що без ттн', 'orders_without_ttn', {}),
    ('де нема ттн', 'orders_without_ttn', {}),
    ('викуп покупця 906372863', 'buyer_rating', {'order_id': '906372863'}),
    ('рейтинг покупця 906372863', 'buyer_rating', {'order_id': '906372863'}),
    ('посилки без руху', 'ttn_stuck', {}),
    ('що застрягло на пошті', 'ttn_stuck', {}),
    ('які посилки не забрали', 'ttn_stuck', {}),
    ('етикетка 20451539117101', 'label', {'ttn': '20451539117101'}),
    ('надрукуй ттн 20451539117101', 'label', {'ttn': '20451539117101'}),
    ('повернення', 'refunds', {}),
    ('заявки на повернення', 'refunds', {}),
    ('які є повернення', 'refunds', {}),
    ('повернення по 906372863', 'refund_detail', {'order_id': '906372863'}),
    ('що з поверненням 906372863', 'refund_detail', {'order_id': '906372863'}),
    ('нові відгуки', 'item_comments', {}),
    ('питання про товари', 'item_comments', {}),
    ('відгуки про товари', 'item_comments', {}),
    ('відгуки про магазин', 'shop_reviews', {}),
    ('оцінки магазину', 'shop_reviews', {}),
    ('хто чекає відповіді', 'unanswered_chats', {}),
    ('чати без відповіді', 'unanswered_chats', {}),
    ('нові повідомлення покупців', 'unanswered_chats', {}),
    ('модерація toptul', 'moderation', {'source': 'toptul'}),
    ('товари на модерації', 'moderation', {'goods_tab': 'moderation'}),
    ('помилки товарів dropoffice', 'moderation', {'source': 'dropoffice', 'goods_tab': 'errors'}),
    ('приховані товари топтул', 'moderation', {'source': 'toptul', 'goods_tab': 'hidden'}),
    ('є у постачальника KAAA1404', 'supplier_stock', {'article': 'KAAA1404'}),
    ('є у постачальника gaai4601-b', 'supplier_stock', {'article': 'GAAI4601-B'}),
    ('наявність у постачальника SO3270', 'supplier_stock', {'sku': 'SO3270'}),
    ('ттн від постачальників', 'supplier_ttn', {}),
    ('чи прийшли ттн від постачальника', 'supplier_ttn', {}),
    ('баланс розетки', 'balance', {'marketplace': 'rozetka'}),
    ('який баланс', 'balance', {}),
    ('скільки грошей на балансі', 'balance', {}),
    ('рахунки розетки', 'invoices', {}),
    ('рахунки на оплату', 'invoices', {}),
    ('бекап', 'backup_status', {}),
    ('резервна копія бази', 'backup_status', {}),
    ('коли був бекап', 'backup_status', {}),
]


@pytest.mark.parametrize('phrase,intent,params', NEW)
def test_new_intents(phrase, intent, params):
    r = intents.parse(phrase)
    assert r['intent'] == intent, (phrase, r)
    assert r['confidence'] >= 0.5
    assert r['mutating'] is False
    for k, v in params.items():
        assert r['params'].get(k) == v, (phrase, k, r['params'])


@pytest.mark.parametrize('phrase,intent', [
    # старі команди не зламались поруч із новими словами
    ('що із замовленням 906209393', 'order_status'),
    ('де посилка 20451537526626', 'ttn_status'),
    ('скільки SX2730 на складі', 'stock'),
    ('нові замовлення', 'orders_new'),
    ('замовлення за сьогодні', 'orders_new'),
    ('статус ттн 20451537526626', 'ttn_status'),
    ('перевір ціни', 'price_alerts'),
    ('стан фідів', 'feed_status'),
])
def test_old_intents_still_win(phrase, intent):
    assert intents.parse(phrase)['intent'] == intent


def test_article_not_confused_with_noire_sku():
    p = intents.parse('скільки SO3270 на складі')['params']
    assert p.get('sku') == 'SO3270' and 'article' not in p


def test_status_param_absent_without_status_words():
    assert 'status' not in intents.parse('нові замовлення')['params']


# ── каталог ───────────────────────────────────────────────────────────

ALL_INTENTS = {'orders_new', 'order_status', 'ttn_status', 'stock', 'price_alerts', 'feed_status',
               'system_status', 'help'} | {i for _, i, _ in NEW}


def test_catalog_covers_every_intent():
    assert set(catalog.CATALOG) == ALL_INTENTS
    assert 'unknown' not in catalog.CATALOG


@pytest.mark.parametrize('intent', sorted(ALL_INTENTS))
def test_catalog_entry_valid(intent):
    e = catalog.CATALOG[intent]
    assert e['risk'] in catalog.RISK_LEVELS and e['risk'] == 'R0'
    assert e['group'] in catalog.GROUPS and e['title'] and isinstance(e['needs'], list)
    r = intents.parse(e['example'])
    assert r['intent'] == intent and r['confidence'] >= 0.5, (intent, e['example'], r)


def test_catalog_needs_for_param_intents():
    c = catalog.CATALOG
    assert c['order_status']['needs'] == ['order_id'] and c['ttn_status']['needs'] == ['ttn']
    assert c['refund_detail']['needs'] == ['order_id'] and c['buyer_rating']['needs'] == ['order_id']
    assert c['label']['needs'] == ['ttn'] and c['supplier_stock']['needs'] == ['article']
    assert c['orders_search']['needs'] == ['status'] and c['refunds']['needs'] == []


def test_by_group_order_and_nonempty():
    g = catalog.by_group()
    assert list(g) == [x for x in catalog.GROUPS if x in g]
    assert all(g.values())
    assert sorted(i for v in g.values() for i in v) == sorted(catalog.CATALOG)


def test_help_text_filters():
    full = catalog.help_text()
    assert 'Замовлення:' in full and 'Повернення:' in full
    assert catalog.CATALOG['balance']['example'] in full
    assert 'help' not in {l.strip() for l in full.splitlines()}
    part = catalog.help_text({'orders_new', 'ttn_status'})
    lines = [l for l in part.splitlines() if l.strip()]
    assert lines[0] == 'Замовлення:' and 'Посилки:' in lines
    assert 'Повернення:' not in part and catalog.CATALOG['balance']['example'] not in part
    assert sum(l.startswith('•') for l in lines) == 2
