"""Приймальні тести до ЗАВДАННЯ 01 (docs/tasks/TASK-01-voice-intents.md).

Написані замовником ДО виконання. Виконавець їх не редагує: вони — умова
приймання, а не підказка. Перевіряють контракт, а не реалізацію: будь-який
розбір, що дає правильний намір і параметри, пройде.
"""
import sys
import time
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / 'tg_dispatcher'))

try:
    import ai_brain.intents as intents
except ImportError as e:                      # модуля немає — це ПРОВАЛ, не пропуск
    pytest.fail(f'модуль tg_dispatcher/ai_brain/intents.py не імпортується: {e}',
                pytrace=False)

INTENTS = {'orders_new', 'order_status', 'ttn_status', 'stock', 'price_alerts',
           'feed_status', 'system_status', 'help', 'unknown'}


def p(text):
    return intents.parse(text)


# ── контракт відповіді ────────────────────────────────────────────────
def test_shape():
    r = p('які нові замовлення')
    assert set(r) == {'intent', 'params', 'mutating', 'confidence', 'raw'}
    assert r['intent'] in INTENTS
    assert isinstance(r['params'], dict)
    assert r['mutating'] is False
    assert 0.0 <= r['confidence'] <= 1.0
    assert r['raw'] == 'які нові замовлення'


def test_empty_and_junk():
    for t in ('', '   ', '...', '🙂'):
        r = p(t)
        assert r['intent'] == 'unknown'
        assert r['confidence'] == 0.0


def test_all_intents_are_declared():
    for t in ('які нові замовлення', 'що із замовленням 906209393',
              'де посилка 20451537526626', 'скільки SX2730 на складі',
              'перевір ціни', 'що з фідом розетки', 'статус системи',
              'що ти вмієш', 'яка погода'):
        assert p(t)['intent'] in INTENTS, t


def test_mutating_always_false():
    for t in ('створи ттн на 906209393', 'зміни статус замовлення', 'оплати замовлення'):
        assert p(t)['mutating'] is False


# ── наміри ────────────────────────────────────────────────────────────
@pytest.mark.parametrize('text,intent', [
    ('які нові замовлення', 'orders_new'),
    ('замовлення за сьогодні', 'orders_new'),
    ('щось замовили?', 'orders_new'),
    ('нові заказы', 'orders_new'),
    ('що із замовленням 906209393', 'order_status'),
    ('статус замовлення 906078985', 'order_status'),
    ('де посилка 20451537526626', 'ttn_status'),
    ('статус ттн 20451537526626', 'ttn_status'),
    ('скільки SX2730 на складі', 'stock'),
    ('чи є SO3270', 'stock'),
    ('наявність sx0762', 'stock'),
    ('цінові алерти', 'price_alerts'),
    ('хто демпінгує', 'price_alerts'),
    ('перевір ціни', 'price_alerts'),
    ('що з фідом розетки', 'feed_status'),
    ('фіди оновились?', 'feed_status'),
    ('публікація прому', 'feed_status'),
    ('як справи', 'system_status'),
    ('статус системи', 'system_status'),
    ('сервіси живі?', 'system_status'),
    ('що ти вмієш', 'help'),
    ('допомога', 'help'),
    ('команди', 'help'),
    ('привіт', 'unknown'),
    ('яка погода в Києві', 'unknown'),
])
def test_intent(text, intent):
    assert p(text)['intent'] == intent, f'{text!r} → {p(text)}'


# ── параметри ─────────────────────────────────────────────────────────
def test_order_id():
    assert p('що із замовленням 906209393')['params']['order_id'] == '906209393'


def test_ttn_wins_over_order_word():
    """14 цифр — це ТТН, навіть якщо у фразі слово «замовлення»."""
    r = p('яка ттн у замовлення 20451537526626')
    assert r['intent'] == 'ttn_status'
    assert r['params']['ttn'] == '20451537526626'
    assert 'order_id' not in r['params']


def test_sku_uppercased():
    assert p('чи є sx2730 в наявності')['params']['sku'] == 'SX2730'


def test_marketplace():
    assert p('що з фідом розетки')['params'].get('marketplace') == 'rozetka'
    assert p('публікація прому')['params'].get('marketplace') == 'prom'
    assert p('фід єпіцентру')['params'].get('marketplace') == 'epicentr'


def test_period():
    assert p('замовлення за сьогодні')['params'].get('period') == 'today'
    assert p('замовлення вчора')['params'].get('period') == 'yesterday'
    assert p('замовлення за тиждень')['params'].get('period') == 'week'


def test_marketplace_does_not_set_intent():
    """Маркетплейс — параметр, а не намір."""
    r = p('замовлення розетки')
    assert r['intent'] == 'orders_new'
    assert r['params'].get('marketplace') == 'rozetka'


def test_price_word_does_not_beat_context():
    """Дефект чинного бота: «ціни на Розетці» йшло в гілку Prom."""
    r = p('ціни на розетці')
    assert r['intent'] == 'price_alerts'
    assert r['params'].get('marketplace') == 'rozetka'


def test_sku_with_price_word():
    r = p('яка ціна на SX2730')
    assert r['intent'] == 'price_alerts'
    assert r['params'].get('sku') == 'SX2730'


def test_params_only_when_present():
    assert p('які нові замовлення')['params'].get('order_id') is None


# ── впевненість ───────────────────────────────────────────────────────
def test_confidence_levels():
    assert p('що із замовленням 906209393')['confidence'] == 1.0
    assert p('де посилка 20451537526626')['confidence'] == 1.0
    assert p('яка погода в Києві')['confidence'] == 0.0
    assert p('статус системи')['confidence'] >= 0.8


# ── стійкість ─────────────────────────────────────────────────────────
def test_case_and_spaces():
    a = p('  ЯКІ НОВІ ЗАМОВЛЕННЯ!!!  ')
    assert a['intent'] == 'orders_new'
    assert p('Статус ТТН 20451537526626')['params']['ttn'] == '20451537526626'


def test_speed():
    t0 = time.time()
    for _ in range(100):
        p('скільки SX2730 на складі і що з фідом розетки')
    assert (time.time() - t0) / 100 < 0.01, 'розбір фрази має бути швидшим за 10 мс'


def test_no_side_effects_on_import():
    """Модуль не повинен нічого робити при імпорті (мережа, файли, БД)."""
    src = (BASE / 'tg_dispatcher' / 'ai_brain' / 'intents.py').read_text(encoding='utf-8')
    for bad in ('requests.', 'psycopg2', 'open(', 'subprocess', 'socket'):
        assert bad not in src, f'заборонено в модулі розбору: {bad}'
