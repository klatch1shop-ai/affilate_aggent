"""Приймальні тести до ЗАВДАННЯ 02 (docs/tasks/TASK-02-bot-commands.md).

Написані замовником ДО виконання й не редагуються. Запити до API підмінено
підробками — модуль перевіряється без мережі.
"""
import re
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / 'tg_dispatcher'))
try:
    import ai_brain.commands as C
    from ai_brain.intents import parse
except ImportError as e:
    pytest.fail(f'tg_dispatcher/ai_brain/commands.py не імпортується: {e}', pytrace=False)

ORDER = {'id': 906209393, 'created': '2026-09-16 12:21:23', 'status': 61, 'amount': '1113.00',
         'ttn': '20451537526626', 'recipient_phone': '380979489449',
         'purchases': [{'item': {'article': 'SO3270', 'name': 'Лубрикант Sensuva'}, 'quantity': 1, 'price': '819.00'},
                       {'item': {'article': 'SX0762', 'name': 'Презервативи ONE'}, 'quantity': 3, 'price': '49.00'}]}
PHONE = re.compile(r'(?<!\d)(?:380|0)\d{9}(?!\d)')


def fake(**over):
    f = {'orders_new': lambda **k: [ORDER],
         'order_details': lambda order_id, **k: ORDER,
         'ttn_status': lambda ttn, **k: {'Number': ttn, 'Status': 'Прибув у поштомат',
                                         'WarehouseRecipient': 'Поштомат №67236',
                                         'ScheduledDeliveryDate': '17.09.2026'},
         'stock': lambda sku, **k: {'sku': sku, 'name': 'Лубрикант', 'available': True,
                                    'quantity': 5, 'price_retail': 819},
         'feeds': lambda **k: {'rozetka': {'ok': True, 'age_min': 42, 'offers': 4147},
                               'prom': {'ok': False, 'age_min': 900, 'offers': 5359}},
         'system': lambda **k: '✅ сервіси: 5/5',
         'price_alerts': lambda **k: 'Порушень антидемпінгу: 0'}
    f.update(over)
    return f


def run(text, **over):
    return C.dispatch(parse(text), fake(**over))


# ── реєстр ───────────────────────────────────────────────────────────
def test_registry():
    need = {'orders_new': [], 'order_status': ['order_id'], 'ttn_status': ['ttn'],
            'stock': ['sku'], 'feed_status': [], 'system_status': [], 'price_alerts': [], 'help': []}
    assert set(C.COMMANDS) == set(need)
    for k, v in need.items():
        assert C.COMMANDS[k]['needs'] == v, k
        assert isinstance(C.COMMANDS[k]['title'], str) and C.COMMANDS[k]['title']
    assert C.COMMANDS['help']['fetcher'] is None
    assert C.COMMANDS['order_status']['fetcher'] == 'order_details'


# ── маршрут: намір → правильний fetcher з правильним параметром ──────
def test_dispatch_passes_params():
    seen = {}
    def od(order_id, **k):
        seen['order_id'] = order_id
        return ORDER
    out = run('що із замовленням 906209393', order_details=od)
    assert seen['order_id'] == '906209393'
    assert '906209393' in out


def test_marketplace_and_period_forwarded():
    seen = {}
    def on(**k):
        seen.update(k)
        return []
    run('замовлення розетки за сьогодні', orders_new=on)
    assert seen.get('marketplace') == 'rozetka' and seen.get('period') == 'today'


def test_unknown_and_help():
    assert run('яка погода') == C.fmt_help()
    assert run('що ти вмієш') == C.fmt_help()


def test_missing_param_message():
    out = C.dispatch({'intent': 'order_status', 'params': {}, 'mutating': False,
                      'confidence': 0.8, 'raw': 'статус замовлення'}, fake())
    assert 'номер замовлення' in out.lower()
    assert C.missing_params({'intent': 'ttn_status', 'params': {}}) == ['ttn']
    assert C.missing_params({'intent': 'stock', 'params': {'sku': 'SX1'}}) == []


def test_fetcher_error_does_not_crash():
    def boom(**k):
        raise RuntimeError('таймаут Rozetka')
    out = run('які нові замовлення', orders_new=boom)
    assert out.startswith('⚠️')


def test_missing_fetcher():
    f = fake(); f.pop('stock')
    out = C.dispatch(parse('скільки SX2730 на складі'), f)
    assert out.startswith('⚠️') and 'не підключена' in out


def test_string_fetchers_passthrough():
    assert run('статус системи') == '✅ сервіси: 5/5'
    assert run('перевір ціни') == 'Порушень антидемпінгу: 0'


# ── формати ───────────────────────────────────────────────────────────
def test_fmt_orders():
    assert 'немає' in C.fmt_orders([]).lower()
    out = C.fmt_orders([ORDER])
    assert '906209393' in out and '1113' in out


def test_fmt_order_lists_every_item():
    out = C.fmt_order(ORDER)
    for s in ('906209393', 'SO3270', 'SX0762', '20451537526626', '1113'):
        assert s in out, s


def test_fmt_ttn_partial_data():
    assert 'Прибув' in C.fmt_ttn({'Number': '20451537526626', 'Status': 'Прибув у поштомат'})
    C.fmt_ttn({})                                # порожні дані не валять


def test_fmt_stock():
    assert 'не знайдено' in C.fmt_stock(None, 'SX9999').lower()
    assert 'SX9999' in C.fmt_stock(None, 'SX9999')
    out = C.fmt_stock({'sku': 'SO1898', 'name': 'Lubrix', 'available': False,
                       'quantity': 0, 'price_retail': 459}, 'SO1898')
    assert 'немає в наявності' in out.lower()
    assert '5' in C.fmt_stock({'sku': 'SO3270', 'name': 'x', 'available': True,
                               'quantity': 5, 'price_retail': 819}, 'SO3270')


def test_fmt_feeds():
    out = C.fmt_feeds({'rozetka': {'ok': True, 'age_min': 42, 'offers': 4147},
                       'prom': {'ok': False, 'age_min': 900, 'offers': 5359}})
    assert '✅' in out and '❌' in out and '4147' in out and '42' in out


def test_help_lists_commands():
    h = C.fmt_help()
    assert len([l for l in h.splitlines() if l.strip()]) >= len(C.COMMANDS)


# ── захист даних покупців ────────────────────────────────────────────
def test_no_phone_numbers_anywhere():
    outs = [run('що із замовленням 906209393'), run('які нові замовлення'),
            C.fmt_order(ORDER), C.fmt_orders([ORDER])]
    for o in outs:
        assert not PHONE.search(o), f'у відповіді номер телефону: {o}'


def test_pure_module():
    src = (BASE / 'tg_dispatcher' / 'ai_brain' / 'commands.py').read_text(encoding='utf-8')
    for bad in ('requests', 'psycopg2', 'open(', 'subprocess', 'socket', 'urllib'):
        assert bad not in src, bad
