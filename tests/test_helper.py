"""Приймальні тести TASK-06: сервісний шар бота-помічника.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

access = importlib.import_module('helper.access')
services = importlib.import_module('helper.services')
feeds = importlib.import_module('helper.feeds')
cycle = importlib.import_module('helper.inbox_cycle')
commands = importlib.import_module('tg_dispatcher.ai_brain.commands')
errors = importlib.import_module('integrations.errors')
store_mod = importlib.import_module('tg_dispatcher.inbox.store')

UTC = timezone.utc


# ── access ────────────────────────────────────────────────────────────

def test_parse_ids():
    assert access.parse_ids('123, 456 ,789') == frozenset({123, 456, 789})
    for empty in (None, '', '   '):
        assert access.parse_ids(empty) == frozenset()
    with pytest.raises(ValueError):
        access.parse_ids('123, abc')


def test_is_allowed_closed_by_default():
    allowed = frozenset({111})
    assert access.is_allowed(111, allowed) and access.is_allowed('111', allowed)
    assert not access.is_allowed(222, allowed)
    assert not access.is_allowed(None, allowed)
    assert not access.is_allowed(111, frozenset())


# ── services ──────────────────────────────────────────────────────────

ORDER = {'id': 906298386, 'created': '2026-09-19 10:00:00', 'status': 1, 'status_group': 1,
         'amount': '551.25', 'cost': '551.25', 'ttn': None, 'total_quantity': 1,
         'purchases': [{'quantity': 1, 'price': '551.25', 'cost': '551.25', 'ttn': None,
                        'item': {'article': 'SO3270', 'name': 'Товар'}}]}


class FakeRozetka:
    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []

    def active_orders(self):
        self.calls.append('active')
        if self.fail:
            raise self.fail
        return [ORDER]

    def order(self, order_id):
        self.calls.append(('order', order_id))
        return dict(ORDER, id=int(order_id))


class FakeNP:
    def ttn_status(self, ttn):
        return {'Number': ttn, 'Status': 'Прибув у відділення'}


def test_fetchers_only_for_given_dependencies():
    assert services.build_fetchers() == {}
    f = services.build_fetchers(rozetka=FakeRozetka())
    assert set(f) == {'orders_new', 'order_details'}
    f = services.build_fetchers(novaposhta=FakeNP(), stock_lookup=lambda s: None,
                                feeds_status=lambda: {}, system_status=lambda: 'ok')
    assert set(f) == {'ttn_status', 'stock', 'feeds', 'system'}


def test_fetchers_call_through_and_ignore_extra_kwargs():
    rz = FakeRozetka()
    f = services.build_fetchers(rozetka=rz, novaposhta=FakeNP(), stock_lookup=lambda sku: {'sku': sku})
    assert f['orders_new'](marketplace='rozetka', period='today') == [ORDER]
    assert f['orders_new']() == [ORDER]
    assert f['order_details'](order_id='906298386', marketplace=None)['id'] == 906298386
    assert f['ttn_status'](ttn='20451538685877')['Number'] == '20451538685877'
    assert f['stock'](sku='SO3270', period=None) == {'sku': 'SO3270'}


def test_orders_other_marketplace_is_visible_error():
    f = services.build_fetchers(rozetka=FakeRozetka())
    with pytest.raises(errors.ApiError) as e:
        f['orders_new'](marketplace='prom')
    assert 'prom' in str(e.value)


def test_answer_end_to_end():
    f = services.build_fetchers(rozetka=FakeRozetka(), novaposhta=FakeNP())
    out = services.answer('що із замовленням 906298386', f)
    assert '906298386' in out and 'SO3270' in out
    out = services.answer('де посилка 20451538685877', f)
    assert 'Прибув у відділення' in out
    assert services.answer('', f) == commands.fmt_help()


def test_answer_command_not_connected():
    out = services.answer('де посилка 20451538685877', services.build_fetchers(rozetka=FakeRozetka()))
    assert out.startswith('⚠️') and 'не підключена' in out


def test_dispatch_shows_api_error_reason_but_hides_other_exceptions():
    f = services.build_fetchers(rozetka=FakeRozetka(
        fail=errors.AuthError('rozetka', 'невірний або прострочений токен', code=1020)))
    out = services.answer('нові замовлення', f)
    assert out.startswith('⚠️') and 'rozetka' in out and '1020' in out
    f2 = services.build_fetchers(rozetka=FakeRozetka(fail=RuntimeError('клієнт 0671234567 секрет')))
    out2 = services.answer('нові замовлення', f2)
    assert out2.startswith('⚠️') and 'секрет' not in out2 and '0671234567' not in out2


# ── feeds ─────────────────────────────────────────────────────────────

def test_count_offers_across_chunk_boundaries(tmp_path, monkeypatch):
    body = '<yml>' + ''.join(f'<offer id="{i}"></offer>' for i in range(5000)) + '</yml>'
    p = tmp_path / 'f.xml'
    p.write_text(body, encoding='utf-8')
    assert feeds.count_offers(str(p)) == 5000
    p2 = tmp_path / 'g.xml'
    p2.write_text('<offers><offerx/><offer >a</offer></offers>', encoding='utf-8')
    assert feeds.count_offers(str(p2)) == 1


def test_feeds_status():
    now = 1_000_000.0
    stats = {'/a.xml': SimpleNamespace(st_mtime=now - 42 * 60),
             '/b.xml': SimpleNamespace(st_mtime=now - 500 * 60),
             '/c.xml': SimpleNamespace(st_mtime=now - 10 * 60)}

    def stat(path):
        if path not in stats:
            raise FileNotFoundError(path)
        return stats[path]
    counts = {'/a.xml': 4147, '/b.xml': 100, '/c.xml': 0}
    out = feeds.feeds_status({'rozetka': '/a.xml', 'prom': '/b.xml', 'epicentr': '/c.xml', 'x': '/none.xml'},
                             now, stat=stat, counter=lambda p: counts[p])
    assert list(out) == ['rozetka', 'prom', 'epicentr', 'x']
    assert out['rozetka'] == {'ok': True, 'age_min': 42, 'offers': 4147}
    assert out['prom'] == {'ok': False, 'age_min': 500, 'offers': 100}
    assert out['epicentr'] == {'ok': False, 'age_min': 10, 'offers': 0}
    assert out['x'] == {'ok': False, 'age_min': None, 'offers': 0}


# ── DeliveryQueue ─────────────────────────────────────────────────────

def test_queue_idempotent_ordered_persistent(tmp_path):
    path = str(tmp_path / 'q.db')
    q = cycle.DeliveryQueue(path)
    q.push('rozetka:1', 'A', 'rozetka', '10')
    q.push('rozetka:2', 'B', 'rozetka', '10')
    q.push('rozetka:1', 'A2', 'rozetka', '10')
    assert [x['key'] for x in q.pending()] == ['rozetka:1', 'rozetka:2']
    assert q.pending()[0]['text'] == 'A'
    q.done('rozetka:1')
    q2 = cycle.DeliveryQueue(path)
    assert q2.pending() == [{'key': 'rozetka:2', 'text': 'B', 'marketplace': 'rozetka', 'chat_id': '10'}]


# ── InboxCycle ────────────────────────────────────────────────────────

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)       # 15:00 за Києвом


def rz_chat(cid, updated, msgs):
    return {'id': cid, 'created': '2026-09-01 10:00:00', 'updated': updated, 'subject': 'Питання',
            'user': {'contact_fio': 'Тестовий Покупець'}, 'order_id': None, 'item_id': 777,
            'messages': [{'id': mid, 'chat_id': cid, 'body': body, 'created': created,
                          'sender': sender, 'files': []} for mid, sender, created, body in msgs]}


class Rz:
    def __init__(self, chats, fail_list=False):
        self.chats, self.fail_list = chats, fail_list

    def list_page(self, page):
        if self.fail_list:
            raise ConnectionError('нема звʼязку')
        return {'chats': [{k: v for k, v in c.items() if k != 'messages'} for c in self.chats.values()],
                '_meta': {'pageCount': 1}}

    def get_chat(self, cid):
        return self.chats[cid]


class Sender:
    def __init__(self, fail_times=0):
        self.sent, self.fail_times, self.next_id = [], fail_times, 1000

    def __call__(self, text):
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError('Telegram недоступний')
        self.next_id += 1
        self.sent.append(text)
        return self.next_id


def make(chats, sender, clock=lambda: NOW, fail_list=False, **kw):
    rz = Rz(chats, fail_list)
    st = store_mod.InboxStore()
    q = cycle.DeliveryQueue()
    return cycle.InboxCycle(st, q, rz.list_page, rz.get_chat, sender, clock, **kw), st, q, rz


def two_new():
    return {1: rz_chat(1, '2026-09-19 14:00:00', [(11, 3, '2026-09-19 13:50:00', 'Чи є в наявності?')]),
            2: rz_chat(2, '2026-09-19 14:10:00', [(21, 3, '2026-09-19 14:05:00', 'Коли відправите?')])}


def test_poll_delivers_cards_and_links():
    s = Sender()
    c, st, q, _ = make(two_new(), s)
    r = c.poll()
    assert r['new'] == 2 and r['delivered'] == 2 and r['queued'] == 0 and r['errors'] == []
    assert r['alert'] is None
    assert 'Чи є в наявності?' in s.sent[0] and 'Коли відправите?' in s.sent[1]
    assert st.chat_for_tg(1001) == ('rozetka', '1') and st.chat_for_tg(1002) == ('rozetka', '2')
    assert c.poll()['new'] == 0 and len(s.sent) == 2


def test_poll_telegram_down_keeps_queue_then_delivers():
    s = Sender(fail_times=2)          # падає доставка першої картки й тривога
    c, st, q, _ = make(two_new(), s)
    r = c.poll()
    assert r['new'] == 2 and r['delivered'] == 0 and r['queued'] == 2 and r['errors']
    assert len(q.pending()) == 2
    r2 = c.poll()                      # Telegram ожив
    assert r2['new'] == 0 and r2['delivered'] == 2 and r2['queued'] == 0
    assert any('Чи є в наявності?' in t for t in s.sent)


def test_poll_alert_once_then_recovery_once():
    s = Sender()
    c, st, q, rz = make(two_new(), s, fail_list=True)
    r1 = c.poll()
    assert r1['alert'] and r1['alert'].startswith('⚠️ Чат покупців:')
    r2 = c.poll()
    assert r2['alert'] is None                         # той самий збій — без повтору
    assert sum(t.startswith('⚠️ Чат покупців:') for t in s.sent) == 1
    rz.fail_list = False
    r3 = c.poll()
    assert r3['alert'] == '✅ Чат покупців знову працює'
    assert r3['delivered'] == 2
    assert c.poll()['alert'] is None


def test_remind_throttle_and_new_chat():
    t = {'now': NOW}
    s = Sender()
    # 15:00 за Києвом = 12:00 UTC = NOW: покупець щойно написав
    chats = {1: rz_chat(1, '2026-09-19 15:00:00', [(11, 3, '2026-09-19 15:00:00', 'Питання 1')])}
    c, st, q, rz = make(chats, s, clock=lambda: t['now'], remind_after_min=30, remind_every_min=60)
    c.poll()
    assert c.remind() is None                          # чекає 0 хв
    t['now'] = NOW + timedelta(minutes=40)
    first = c.remind()
    assert first and '⏰' in first
    t['now'] = NOW + timedelta(minutes=50)
    assert c.remind() is None                          # не частіше ніж раз на 60 хв
    chats[2] = rz_chat(2, '2026-09-19 15:10:00', [(21, 3, '2026-09-19 15:10:00', 'Питання 2')])
    c.poll()
    t['now'] = NOW + timedelta(minutes=45 + 10)        # чат 2 чекає 45 хв — новий у нагадуванні
    second = c.remind()
    assert second and 'чат 2' in second
    t['now'] = NOW + timedelta(minutes=60)
    assert c.remind() is None


def test_remind_send_failure_keeps_state():
    t = {'now': NOW}
    s = Sender()
    chats = {1: rz_chat(1, '2026-09-19 14:00:00', [(11, 3, '2026-09-19 14:00:00', 'Питання')])}
    c, *_ = make(chats, s, clock=lambda: t['now'])
    c.poll()
    t['now'] = NOW + timedelta(minutes=40)
    s.fail_times = 1
    assert c.remind() is None
    assert c.remind() is not None                      # стан не зсунувся — наступна спроба йде
