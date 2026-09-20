"""Приймальні тести TASK-12: чати покупців v2.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib
from datetime import datetime, timedelta, timezone

import pytest

collect = importlib.import_module('tg_dispatcher.inbox.collect')
render = importlib.import_module('tg_dispatcher.inbox.render')
model = importlib.import_module('tg_dispatcher.inbox.model')
store_mod = importlib.import_module('tg_dispatcher.inbox.store')
cycle = importlib.import_module('helper.inbox_cycle')

UTC = timezone.utc
NOW = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)          # 12:00 за Києвом


def msg(mid, chat, direction, minutes_ago, body='текст', subject='Питання про товар', marketplace='rozetka'):
    return model.BuyerMessage(marketplace=marketplace, chat_id=chat, msg_id=mid, direction=direction,
                              body=body, created=NOW - timedelta(minutes=minutes_ago),
                              subject=subject, buyer_name='Покупець')


# ── §3 окремі курсори типів чатів ─────────────────────────────────────

def rz_chat(cid, updated, msgs):
    return {'id': cid, 'created': '2026-09-01 10:00:00', 'updated': updated, 'subject': 'Тема',
            'user': {'contact_fio': 'Покупець'}, 'order_id': None, 'item_id': 1,
            'messages': [{'id': m, 'chat_id': cid, 'body': b, 'created': c, 'sender': s, 'files': []}
                         for m, s, c, b in msgs]}


class Rz:
    def __init__(self, by_type):
        self.by_type, self.calls = by_type, []

    def list_page(self, page, msg_type=None):
        self.calls.append((page, msg_type))
        chats = self.by_type[msg_type] if msg_type else [c for v in self.by_type.values() for c in v]
        return {'chats': [{k: v for k, v in c.items() if k != 'messages'} for c in chats],
                '_meta': {'pageCount': 1}}

    def get_chat(self, cid):
        for chats in self.by_type.values():
            for c in chats:
                if c['id'] == cid:
                    return c
        raise LookupError(cid)


def test_separate_cursors_per_msg_type():
    items = [rz_chat(1, '2026-09-20 11:50:00', [(11, 3, '2026-09-20 11:50:00', 'питання про товар')])]
    orders = [rz_chat(2, '2026-09-20 11:55:00', [(21, 3, '2026-09-20 11:55:00', 'питання по замовленню')])]
    rz, st = Rz({'items': items, 'orders': orders}), store_mod.InboxStore()
    r1 = collect.collect_rozetka(rz.list_page, rz.get_chat, st, now=NOW, msg_type='items')
    r2 = collect.collect_rozetka(rz.list_page, rz.get_chat, st, now=NOW, msg_type='orders')
    assert [m.msg_id for m in r1['new']] == ['11'] and [m.msg_id for m in r2['new']] == ['21']
    assert st.get_cursor('rozetka:items') == '2026-09-20 11:50:00'
    assert st.get_cursor('rozetka:orders') == '2026-09-20 11:55:00'
    assert st.get_cursor('rozetka') is None
    assert {c[1] for c in rz.calls} == {'items', 'orders'}
    # другий прохід кожного типу — нічого нового
    assert collect.collect_rozetka(rz.list_page, rz.get_chat, st, now=NOW, msg_type='items')['new'] == []


def test_old_call_without_msg_type_unchanged():
    items = [rz_chat(1, '2026-09-20 11:50:00', [(11, 3, '2026-09-20 11:50:00', 'x')])]
    rz, st = Rz({None: items}), store_mod.InboxStore()

    def list_page(page):                      # старий виклик — рівно один аргумент
        return rz.list_page(page)
    r = collect.collect_rozetka(list_page, rz.get_chat, st, now=NOW)
    assert [m.msg_id for m in r['new']] == ['11'] and st.get_cursor('rozetka') == '2026-09-20 11:50:00'


# ── §4 store ──────────────────────────────────────────────────────────

def test_linked_chats():
    st = store_mod.InboxStore()
    assert st.linked_chats() == set()
    st.link_tg(100, 'rozetka', '42'); st.link_tg(101, 'prom', '7')
    assert st.linked_chats() == {('rozetka', '42'), ('prom', '7')}


def test_open_chats_and_unanswered_context():
    st = store_mod.InboxStore()
    st.add_new([
        msg('1', 'A', 'in', 60 * 34, body='Чи підійде до Mazda? тел 067 123 45 67', subject='Питання A'),
        msg('2', 'B', 'in', 90, body='Коли відправите?', subject='Питання B'),
        msg('3', 'B', 'out', 30, body='Сьогодні', subject='Питання B'),
        msg('4', 'C', 'in', 60 * 24 * 9, body='Старе', subject='Питання C'),
    ])
    out = st.open_chats(NOW, max_age_days=7)
    assert [x['chat_id'] for x in out] == ['A']              # B відповіли, C застаре
    a = out[0]
    assert a['subject'] == 'Питання A' and a['waiting_min'] == 60 * 34
    assert '123 45 67' not in a['last_text'] and 'Mazda' in a['last_text']
    un = st.unanswered(NOW, 30)
    assert {x['chat_id'] for x in un} == {'A', 'C'}
    assert all('subject' in x and 'last_text' in x for x in un)


# ── §5 render ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('minutes,text', [(45, '45 хв'), (125, '2 год 5 хв'), (2256, '1 д 13 год')])
def test_human_duration(minutes, text):
    assert render.human_duration(minutes) == text


def test_thread_card():
    msgs = [msg('1', '42', 'in', 200, body='Перше питання'), msg('2', '42', 'out', 150, body='Наша відповідь'),
            msg('3', '42', 'in', 100, body='<b>Друге</b> питання, тел 0671234567'),
            msg('4', '42', 'in', 50, body='Ще одне')]
    out = render.thread_card(msgs, limit=3)
    assert 'Перше питання' not in out                          # лише останні 3
    assert '👤' in out and '🏪' in out
    assert 'Наша відповідь' in out and 'Ще одне' in out
    assert '&lt;b&gt;' in out and '<b>Друге</b>' not in out
    assert '0671234567' not in out and '[телефон приховано]' in out
    assert 'чат 42' in out.splitlines()[0] and 'реплаєм' in out.splitlines()[-1]
    assert render.thread_card([]) == ''


def test_reminder_detail():
    items = [{'marketplace': 'rozetka', 'chat_id': '42', 'buyer_name': 'X', 'waiting_min': 2256,
              'subject': 'Питання про товар', 'last_text': 'Чи підійде? 0671234567'},
             {'marketplace': 'prom', 'chat_id': '7', 'buyer_name': '', 'waiting_min': 45,
              'subject': '', 'last_text': ''}]
    out = render.reminder_detail(items)
    lines = out.splitlines()
    assert lines[0] == '⏰ Чекають відповіді: 2'
    assert 'чат 42' in lines[1] and '1 д 13 год' in lines[1]
    assert 'Питання про товар' in lines[2] and '0671234567' not in out
    assert any('чат 7' in l and '45 хв' in l for l in lines)
    assert render.reminder_detail([]) == ''


# ── §6 цикл: дозавантаження й наростаючі нагадування ──────────────────

class Sender:
    def __init__(self):
        self.sent, self.next_id, self.fail = [], 500, 0

    def __call__(self, text):
        if self.fail:
            self.fail -= 1
            raise ConnectionError('Telegram')
        self.next_id += 1
        self.sent.append(text)
        return self.next_id


def make(clock_holder, **kw):
    st, q, s = store_mod.InboxStore(), cycle.DeliveryQueue(), Sender()
    c = cycle.InboxCycle(st, q, lambda page, msg_type=None: {'chats': [], '_meta': {'pageCount': 0}},
                         lambda cid: {}, s, lambda: clock_holder['now'], **kw)
    return c, st, q, s


def test_backfill_only_unlinked_open_chats():
    t = {'now': NOW}
    c, st, q, s = make(t)
    st.add_new([msg('1', 'A', 'in', 200, body='Питання A'), msg('2', 'A', 'in', 100, body='Ще раз'),
                msg('3', 'B', 'in', 120, body='Питання B'),
                msg('4', 'C', 'in', 60 * 24 * 10, body='Старе')])
    st.link_tg(900, 'rozetka', 'B')                            # B уже показували
    assert c.backfill() == 1                                   # лише A (C застарий, B привʼязаний)
    assert [x['key'] for x in q.pending()] == ['rozetka:thread:A']
    assert 'Питання A' in q.pending()[0]['text'] and 'Ще раз' in q.pending()[0]['text']
    assert c.backfill() == 1 and len(q.pending()) == 1          # повторно — без дублю в черзі
    r = c.poll()
    assert r['delivered'] == 1 and st.chat_for_tg(501) == ('rozetka', 'A')


def test_remind_escalating_schedule():
    t = {'now': NOW}
    c, st, q, s = make(t, remind_after_min=30, remind_schedule=(60, 180, 360, 1440))
    st.add_new([msg('1', 'A', 'in', 40, body='Питання A')])
    first = c.remind()
    assert first and 'чат A' in first                           # перший раз — одразу
    t['now'] = NOW + timedelta(minutes=59)
    assert c.remind() is None                                   # ще не минуло 60
    t['now'] = NOW + timedelta(minutes=61)
    assert c.remind() is not None                               # другий раз
    t['now'] = NOW + timedelta(minutes=61 + 179)
    assert c.remind() is None                                   # третій — через 180
    t['now'] = NOW + timedelta(minutes=61 + 181)
    assert c.remind() is not None
    assert len(s.sent) == 3


def test_remind_only_due_chats_and_new_immediately():
    t = {'now': NOW}
    c, st, q, s = make(t, remind_after_min=30)
    st.add_new([msg('1', 'A', 'in', 40, body='A')])
    c.remind()
    t['now'] = NOW + timedelta(minutes=10)
    st.add_new([msg('2', 'B', 'in', 0, body='B')])               # новий чат чекає 40 хв на +50
    t['now'] = NOW + timedelta(minutes=50)
    out = c.remind()
    assert out and 'чат B' in out and 'чат A' not in out         # A ще не час
    assert s.fail == 0


def test_remind_send_failure_keeps_counters():
    t = {'now': NOW}
    c, st, q, s = make(t, remind_after_min=30)
    st.add_new([msg('1', 'A', 'in', 40, body='A')])
    s.fail = 1
    assert c.remind() is None
    assert c.remind() is not None
