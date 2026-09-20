"""Приймальні тести TASK-28: воронка товару.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib
from datetime import datetime, timedelta, timezone

import pytest

fn = importlib.import_module('research.funnel')

UTC = timezone.utc
NOW = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)


def ago(days):
    return NOW - timedelta(days=days)


ORDERS = [
    {'id': 1, 'created': ago(2), 'status': 'done', 'sum': 500},
    {'id': 2, 'created': ago(10), 'status': 'done', 'sum': 750.5},
    {'id': 3, 'created': ago(20), 'status': 'cancelled', 'sum': 300},
    {'id': 4, 'created': ago(29), 'status': 'processing', 'sum': 200},
    {'id': 5, 'created': ago(60), 'status': 'done', 'sum': 400},
    {'id': 6, 'created': ago(80), 'status': 'cancelled', 'sum': 100},
    {'id': 7, 'created': ago(200), 'status': 'done', 'sum': 999},
]
RETURNS = [{'order_id': 2, 'created': ago(5), 'reason': 'не підійшло'},
           {'order_id': 5, 'created': ago(70), 'reason': 'брак'}]
QUESTIONS = [{'id': 'q1', 'created': ago(1), 'answered': False},
             {'id': 'q2', 'created': ago(3), 'answered': True},
             {'id': 'q3', 'created': ago(300), 'answered': False}]
REVIEWS = [{'id': 'r1', 'created': ago(5), 'rating': 5},
           {'id': 'r2', 'created': ago(40), 'rating': 4},
           {'id': 'r3', 'created': ago(200), 'rating': 1}]
PRICES = [{'seller': 'Конкурент А', 'price': 132.0}, {'seller': 'Конкурент Б', 'price': 140.0}]


def build(**over):
    kw = {'orders': ORDERS, 'returns': RETURNS, 'questions': QUESTIONS, 'reviews': REVIEWS,
          'prices': PRICES, 'our_price': 149.0, 'now': NOW}
    kw.update(over)
    return fn.build('SO3142', **kw)


# ── підрахунки ────────────────────────────────────────────────────────

def test_counts_and_sums():
    f = build()
    assert f['sku'] == 'SO3142'
    assert f['orders_30'] == 4 and f['orders_90'] == 6
    assert f['sum_30'] == pytest.approx(1250.5)          # лише done за 30 днів
    assert f['returns_30'] == 1
    assert f['questions_open'] == 2                       # без обмеження за часом


def test_buyout():
    f = build()
    assert f['buyout'] == pytest.approx(0.6)              # done 3 / (3 done + 2 cancelled) за 90 дн
    only_processing = [{'id': 9, 'created': ago(1), 'status': 'processing', 'sum': 10}]
    assert build(orders=only_processing)['buyout'] is None


def test_reviews_and_rating():
    f = build()
    assert f['reviews_count'] == 2 and f['rating'] == pytest.approx(4.5)
    empty = build(reviews=[])
    assert empty['reviews_count'] == 0 and empty['rating'] is None


def test_prices():
    f = build()
    assert f['min_price'] == pytest.approx(132.0) and f['min_seller'] == 'Конкурент А'
    assert f['our_price'] == pytest.approx(149.0)
    assert f['price_gap'] == pytest.approx(12.9)
    assert build(our_price=120.0)['price_gap'] == pytest.approx(-9.1)
    assert build(prices=[])['price_gap'] is None and build(our_price=None)['price_gap'] is None
    tie = build(prices=[{'seller': 'Перший', 'price': 100}, {'seller': 'Другий', 'price': 100}])
    assert tie['min_seller'] == 'Перший'


def test_gaps():
    f = build()
    assert f['gaps'] == list(fn.KNOWN_GAPS)
    empty = fn.build('X', orders=[], returns=[], questions=[], reviews=[], prices=[],
                     our_price=None, now=NOW)
    assert empty['gaps'] == list(fn.KNOWN_GAPS) + ['немає цін конкурентів', 'немає відгуків',
                                                   'немає замовлень за 90 днів']


# ── звіт ──────────────────────────────────────────────────────────────

def test_report_full():
    lines = fn.report(build()).splitlines()
    assert lines[0] == '📊 SO3142'
    assert lines[1] == 'Замовлення: 4 за 30 дн · 6 за 90 дн · виконано на 1 250.50 ₴'
    assert lines[2] == 'Викуп: 60% · повернень за 30 дн: 1'
    assert lines[3] == 'Питання без відповіді: 2'
    assert lines[4] == 'Відгуки: 2 · середня 4.50'
    assert lines[5] == ('Ціна: 149.00 ₴ · найдешевший конкурент 132.00 ₴ (Конкурент А)'
                        ' · ми дорожчі на 12.9%')
    assert lines[6] == ('Чого не знаємо: покази й кліки на маркетплейсі;'
                        ' перегляди й переходи із соцмереж')


def test_report_cheaper_and_equal():
    assert 'ми дешевші на 9.1%' in fn.report(build(our_price=120.0))
    assert 'ціна однакова' in fn.report(build(our_price=132.0))


def test_report_missing_data():
    f = fn.build('X', orders=[], returns=[], questions=[], reviews=[], prices=[],
                 our_price=None, now=NOW)
    text = fn.report(f)
    assert 'Викуп: даних нема' in text
    assert 'Відгуки: 0' in text and 'середня' not in text
    assert not any(l.startswith('Ціна:') for l in text.splitlines())
    assert 'немає замовлень за 90 днів' in text


def test_report_price_without_competitors():
    text = fn.report(build(prices=[]))
    price_line = [l for l in text.splitlines() if l.startswith('Ціна:')][0]
    assert price_line == 'Ціна: 149.00 ₴'
