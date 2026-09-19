"""Приймальні тести TASK-07: бот-помічник, версія 2.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib
from datetime import date, datetime, timedelta, timezone

import pytest

digest = importlib.import_module('helper.digest')
keyboards = importlib.import_module('helper.keyboards')
services = importlib.import_module('helper.services')
commands = importlib.import_module('tg_dispatcher.ai_brain.commands')
intents = importlib.import_module('tg_dispatcher.ai_brain.intents')
store_mod = importlib.import_module('tg_dispatcher.inbox.store')
model = importlib.import_module('tg_dispatcher.inbox.model')
errors = importlib.import_module('integrations.errors')

UTC = timezone.utc


# ── §3 unanswered max_age ─────────────────────────────────────────────

def test_unanswered_max_age():
    s = store_mod.InboxStore()
    t = lambda d, h: datetime(2026, 9, d, h, 0, tzinfo=UTC)
    mk = lambda mid, chat, when: model.BuyerMessage(marketplace='rozetka', chat_id=chat, msg_id=mid,
                                                    direction='in', body='x', created=when)
    s.add_new([mk('1', 'OLD', t(10, 9)), mk('2', 'NEW', t(19, 9))])
    now = t(19, 12)
    assert {x['chat_id'] for x in s.unanswered(now, 30)} == {'OLD', 'NEW'}
    assert [x['chat_id'] for x in s.unanswered(now, 30, max_age_min=48 * 60)] == ['NEW']
    assert s.unanswered(now, 30, max_age_min=180) == [x for x in s.unanswered(now, 30) if x['chat_id'] == 'NEW']


# ── §4 fmt_order ──────────────────────────────────────────────────────

ORDER = {'id': 906298386, 'status': 26, 'amount': '551.25', 'ttn': '20451538685877',
         'purchases': [{'quantity': 2, 'item': {'article': 'SO3270', 'name': 'Товар'}}]}


def test_fmt_order_unchanged_without_ttn_info():
    out = commands.fmt_order(ORDER)
    assert 'Посилка' not in out and out.endswith('ТТН: 20451538685877')


def test_fmt_order_with_ttn_info():
    info = {'Status': 'Прибув у відділення', 'WarehouseRecipient': 'Відділення №1',
            'ScheduledDeliveryDate': '20.09.2026'}
    lines = commands.fmt_order(dict(ORDER, ttn_info=info)).splitlines()
    i = lines.index('ТТН: 20451538685877')
    assert lines[i + 1:] == ['Посилка: Прибув у відділення', 'Відділення: Відділення №1',
                             'Очікується: 20.09.2026']


def test_fmt_order_ttn_info_partial_and_error():
    out = commands.fmt_order(dict(ORDER, ttn_info={'Status': 'Створено', 'WarehouseRecipient': ''}))
    assert 'Посилка: Створено' in out and 'Відділення' not in out
    out = commands.fmt_order(dict(ORDER, ttn_info={'error': 'novaposhta: вичерпано ліміт'}))
    assert 'Посилка: ⚠️ novaposhta: вичерпано ліміт' in out


# ── §5 enriched order_details ─────────────────────────────────────────

class Rz:
    def __init__(self, ttn):
        self.ttn = ttn
        self.last = None

    def order(self, order_id):
        self.last = dict(ORDER, id=int(order_id), ttn=self.ttn)
        return self.last

    def active_orders(self):
        return []


class NP:
    def __init__(self, fail=None):
        self.fail, self.asked = fail, []

    def ttn_status(self, ttn):
        self.asked.append(ttn)
        if self.fail:
            raise self.fail
        return {'Number': ttn, 'Status': 'У дорозі'}


def test_order_details_enriched_with_np():
    rz, np = Rz('2045 1538 6858 77'), NP()
    out = services.build_fetchers(rozetka=rz, novaposhta=np)['order_details'](order_id='906298386')
    assert out['ttn_info'] == {'Number': '20451538685877', 'Status': 'У дорозі'}
    assert np.asked == ['20451538685877']
    assert 'ttn_info' not in rz.last                 # оригінал не мутується


def test_order_details_np_error_still_shows_order():
    out = services.build_fetchers(rozetka=Rz('20451538685877'),
                                  novaposhta=NP(fail=errors.ApiError('novaposhta', 'вичерпано ліміт')))['order_details'](order_id='906298386')
    assert out['id'] == 906298386 and 'вичерпано ліміт' in out['ttn_info']['error']
    text = services.answer('що із замовленням 906298386', services.build_fetchers(
        rozetka=Rz('20451538685877'), novaposhta=NP(fail=errors.ApiError('novaposhta', 'вичерпано ліміт'))))
    assert 'SO3270' in text and 'Посилка: ⚠️' in text


def test_order_details_without_ttn_or_np():
    np = NP()
    for ttn in (None, '', '123'):
        out = services.build_fetchers(rozetka=Rz(ttn), novaposhta=np)['order_details'](order_id='906298386')
        assert 'ttn_info' not in out
    assert np.asked == []
    out = services.build_fetchers(rozetka=Rz('20451538685877'))['order_details'](order_id='906298386')
    assert 'ttn_info' not in out


def test_answer_full_card_end_to_end():
    text = services.answer('що із замовленням 906298386',
                           services.build_fetchers(rozetka=Rz('20451538685877'), novaposhta=NP()))
    assert 'ТТН: 20451538685877' in text and 'Посилка: У дорозі' in text


# ── §6 keyboards ──────────────────────────────────────────────────────

def test_menu_layout():
    assert keyboards.MENU == [['🆕 Нові замовлення', '📦 Стан фідів'], ['🖥 Статус системи', '❓ Довідка']]
    assert set(keyboards.BUTTONS) == {b for row in keyboards.MENU for b in row}


@pytest.mark.parametrize('button,intent', [('🆕 Нові замовлення', 'orders_new'), ('📦 Стан фідів', 'feed_status'),
                                           ('🖥 Статус системи', 'system_status'), ('❓ Довідка', 'help')])
def test_buttons_parse_to_intents(button, intent):
    p = intents.parse(keyboards.to_query(button))
    assert p['intent'] == intent and p['confidence'] >= 0.5


def test_to_query_passthrough():
    assert keyboards.to_query('  🆕 Нові замовлення ') == keyboards.BUTTONS['🆕 Нові замовлення']
    assert keyboards.to_query('де посилка 20451538685877') == 'де посилка 20451538685877'


# ── §7 digest ─────────────────────────────────────────────────────────

def test_due_kyiv_time():
    # 05:59 UTC = 08:59 Київ (літо), 06:00 UTC = 09:00 Київ
    assert digest.due(datetime(2026, 9, 19, 5, 59, tzinfo=UTC), None) is False
    assert digest.due(datetime(2026, 9, 19, 6, 0, tzinfo=UTC), None) is True
    assert digest.due(datetime(2026, 9, 19, 6, 0, tzinfo=UTC), date(2026, 9, 19)) is False
    assert digest.due(datetime(2026, 9, 19, 6, 0, tzinfo=UTC), date(2026, 9, 18)) is True
    # 22:30 UTC 19.09 = 01:30 Київ 20.09 — до 9:00, ще рано
    assert digest.due(datetime(2026, 9, 19, 22, 30, tzinfo=UTC), date(2026, 9, 19)) is False
    assert digest.due(datetime(2026, 9, 19, 12, 0, tzinfo=UTC), None, hour=16) is False
    with pytest.raises(ValueError):
        digest.due(datetime(2026, 9, 19, 12, 0), None)


NOW = datetime(2026, 9, 19, 6, 5, tzinfo=UTC)


def test_digest_all_good():
    out = digest.build_digest(NOW, [], [], {'rozetka': {'ok': True, 'age_min': 5, 'offers': 10}},
                              {'tg-dispatcher': 'active'}).splitlines()
    assert out == ['☀️ Ранковий звіт 19.09', '🆕 Замовлень у роботі: 0', '💬 Чати без відповіді: 0',
                   '📦 Фіди: усі в нормі', '🖥 Служби: усі працюють']


def test_digest_problems_and_limits():
    orders = [{'id': 906000000 + i, 'amount': f'{100 + i}.00'} for i in range(12)]
    un = [{'marketplace': 'rozetka', 'chat_id': '42', 'buyer_name': 'X', 'waiting_min': 95}]
    feeds = {'rozetka': {'ok': True, 'age_min': 5, 'offers': 10},
             'prom': {'ok': False, 'age_min': 500, 'offers': 5403},
             'epicentr': {'ok': False, 'age_min': None, 'offers': 0}}
    out = digest.build_digest(NOW, orders, un, feeds, {'a': 'active', 'rozetka-order-agent': 'failed'})
    lines = out.splitlines()
    assert '🆕 Замовлень у роботі: 12' in lines
    assert '№906000000 — 100.00 грн' in lines and '… ще 2' in lines
    assert '№906000010 — 110.00 грн' not in lines
    assert '💬 Чати без відповіді: 1' in lines and '🟢 Rozetka · чат 42: 95 хв' in lines
    assert '📦 Фіди з проблемами:' in lines
    assert '❌ prom: вік 500 хв; офферів: 5403' in lines and '❌ epicentr: вік — хв; офферів: 0' in lines
    assert not any(l.startswith('❌ rozetka') for l in lines)
    assert '🖥 Служби з проблемами:' in lines and '❌ rozetka-order-agent: failed' in lines


def test_digest_unknown_is_visible():
    out = digest.build_digest(NOW, None, None, None, None).splitlines()
    assert out == ['☀️ Ранковий звіт 19.09', '⚠️ Замовлення: не вдалося отримати',
                   '⚠️ Чати покупців: не вдалося отримати', '⚠️ Фіди: не вдалося отримати',
                   '⚠️ Служби: не вдалося отримати']


def test_digest_masks_private():
    out = digest.build_digest(NOW, [{'id': 906298386, 'amount': 'дзвоніть 067 123 45 67'}], [], {}, {})
    assert '123 45 67' not in out and '906298386' in out
