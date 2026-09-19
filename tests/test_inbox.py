"""Приймальні тести TASK-03: єдиний чат покупців — ядро.

Написані замовником ДО виконання. Виконавець їх не змінює.
Усі дані вигадані; справжніх покупців тут немає.
"""
import importlib
from datetime import datetime, timedelta, timezone

import pytest

model = importlib.import_module('tg_dispatcher.inbox.model')
normalize = importlib.import_module('tg_dispatcher.inbox.normalize')
store_mod = importlib.import_module('tg_dispatcher.inbox.store')
collect = importlib.import_module('tg_dispatcher.inbox.collect')
render = importlib.import_module('tg_dispatcher.inbox.render')
reply = importlib.import_module('tg_dispatcher.inbox.reply')

BuyerMessage = model.BuyerMessage
InboxStore = store_mod.InboxStore
UTC = timezone.utc


def msg(msg_id='1', chat_id='10', direction='in', created=None, marketplace='rozetka', **kw):
    return BuyerMessage(marketplace=marketplace, chat_id=chat_id, msg_id=msg_id,
                        direction=direction, body=kw.pop('body', 'текст'),
                        created=created or datetime(2026, 9, 19, 9, 0, tzinfo=UTC), **kw)


def rz_chat(chat_id, updated, messages=None, **kw):
    chat = {'id': chat_id, 'created': '2026-09-01 10:00:00', 'updated': updated,
            'subject': kw.get('subject', 'Питання про товар'),
            'user': {'id': 555, 'contact_fio': kw.get('fio', 'Тестовий Покупець'),
                     'email': 'x@example.com', 'has_email': True},
            'order_id': kw.get('order_id'), 'item_id': kw.get('item_id', 777),
            'type': 1, 'unread_messages_count': 0}
    if messages is not None:
        chat['messages'] = messages
    return chat


def rz_msg(mid, sender, created, body='Добрий день', files=None):
    return {'id': mid, 'chat_id': 1, 'body': body, 'created': created, 'sender': sender,
            'receiver_id': 1, 'seller_id': None, 'files': files or [], 'status': 5}


# ── model ─────────────────────────────────────────────────────────────

def test_kyiv_to_utc_summer_and_winter():
    assert model.kyiv_to_utc('2026-07-01 12:00:00') == datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    assert model.kyiv_to_utc('2026-01-15 12:00:00') == datetime(2026, 1, 15, 10, 0, tzinfo=UTC)


def test_kyiv_to_utc_bad_string():
    with pytest.raises(ValueError):
        model.kyiv_to_utc('вчора')


@pytest.mark.parametrize('field,value', [
    ('marketplace', 'olx'), ('direction', 'both'), ('chat_id', ''), ('msg_id', ''),
])
def test_model_rejects_bad_fields(field, value):
    kw = dict(marketplace='rozetka', chat_id='1', msg_id='1', direction='in', body='',
              created=datetime(2026, 9, 19, tzinfo=UTC))
    kw[field] = value
    with pytest.raises(ValueError):
        BuyerMessage(**kw)


def test_model_rejects_naive_datetime():
    with pytest.raises(ValueError):
        BuyerMessage(marketplace='rozetka', chat_id='1', msg_id='1', direction='in',
                     body='', created=datetime(2026, 9, 19, 12, 0))


def test_model_converts_to_utc():
    kyiv = timezone(timedelta(hours=3))
    m = msg(created=datetime(2026, 9, 19, 12, 0, tzinfo=kyiv))
    assert m.created == datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
    assert m.created.utcoffset() == timedelta(0)


def test_model_has_no_contact_fields():
    names = set(BuyerMessage.__dataclass_fields__)
    assert not names & {'phone', 'email', 'buyer_phone', 'buyer_email'}


# ── normalize ─────────────────────────────────────────────────────────

def test_from_rozetka_directions_and_order():
    chat = rz_chat(42, '2026-09-18 10:00:00', messages=[
        rz_msg(3, 2, '2026-09-18 09:30:00', 'Відповідь магазину'),
        rz_msg(2, 3, '2026-09-18 09:00:00', 'Чи є в наявності?'),
        rz_msg(4, 99, '2026-09-18 09:45:00', 'Невідомий відправник'),
    ])
    out = normalize.from_rozetka(chat)
    assert [m.msg_id for m in out] == ['2', '3', '4']
    assert [m.direction for m in out] == ['in', 'out', 'in']
    assert all(m.chat_id == '42' and m.marketplace == 'rozetka' for m in out)
    assert out[0].created == datetime(2026, 9, 18, 6, 0, tzinfo=UTC)
    assert out[0].buyer_name == 'Тестовий Покупець'
    assert out[0].item_id == '777' and out[0].order_id is None


def test_from_rozetka_files_and_missing_parts():
    chat = rz_chat(5, '2026-09-18 10:00:00', messages=[
        rz_msg(1, 3, '2026-09-18 09:00:00', None, files=[{'url': 'x'}])])
    del chat['user']
    out = normalize.from_rozetka(chat)
    assert out[0].has_files is True
    assert out[0].body == ''
    assert out[0].buyer_name == ''


def test_from_rozetka_without_messages_key():
    assert normalize.from_rozetka(rz_chat(5, '2026-09-18 10:00:00')) == []


def test_from_prom_basic_and_phone_dropped():
    m = normalize.from_prom({'id': 901, 'date_created': '2026-09-19T08:00:00+00:00',
                             'client_full_name': 'Покупець Prom', 'phone': '+380671234567',
                             'message': 'Є розмір L?', 'subject': 'Товар', 'status': 'unread',
                             'product_id': 123})
    assert (m.marketplace, m.chat_id, m.msg_id, m.direction) == ('prom', '901', '901', 'in')
    assert m.created == datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
    assert m.item_id == '123'
    assert '380671234567' not in repr(m)


def test_from_prom_naive_date_is_kyiv_and_deleted_skipped():
    m = normalize.from_prom({'id': 1, 'date_created': '2026-07-01T12:00:00',
                             'client_full_name': '', 'message': 'x', 'status': 'read',
                             'product_id': None})
    assert m.created == datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    assert m.item_id is None
    assert normalize.from_prom({'id': 2, 'date_created': '2026-07-01T12:00:00',
                                'message': 'x', 'status': 'deleted'}) is None


# ── store ─────────────────────────────────────────────────────────────

def test_add_new_dedup_and_sorted():
    s = InboxStore()
    a = msg('2', created=datetime(2026, 9, 19, 10, 0, tzinfo=UTC))
    b = msg('1', created=datetime(2026, 9, 19, 9, 0, tzinfo=UTC))
    first = s.add_new([a, b, a])
    assert [m.msg_id for m in first] == ['1', '2']
    assert s.add_new([a, b]) == []


def test_same_msg_id_different_marketplace_is_new():
    s = InboxStore()
    s.add_new([msg('1')])
    assert len(s.add_new([msg('1', marketplace='prom')])) == 1


def test_store_persists_to_file(tmp_path):
    path = str(tmp_path / 'inbox.db')
    InboxStore(path).add_new([msg('1')])
    s2 = InboxStore(path)
    assert s2.add_new([msg('1')]) == []


def test_link_tg_and_overwrite():
    s = InboxStore()
    assert s.chat_for_tg(100) is None
    s.link_tg(100, 'rozetka', '42')
    assert s.chat_for_tg(100) == ('rozetka', '42')
    s.link_tg(100, 'prom', '7')
    assert s.chat_for_tg(100) == ('prom', '7')


def test_cursor_roundtrip():
    s = InboxStore()
    assert s.get_cursor('rozetka') is None
    s.set_cursor('rozetka', '2026-09-18 10:00:00')
    s.set_cursor('rozetka', '2026-09-18 11:00:00')
    assert s.get_cursor('rozetka') == '2026-09-18 11:00:00'
    assert s.get_cursor('prom') is None


def test_unanswered():
    s = InboxStore()
    t = lambda h, m=0: datetime(2026, 9, 19, h, m, tzinfo=UTC)
    s.add_new([
        msg('1', chat_id='A', direction='in', created=t(8), buyer_name='Перший'),   # чекає 120 хв
        msg('2', chat_id='B', direction='in', created=t(9)),                        # чекає 60 хв
        msg('3', chat_id='C', direction='in', created=t(8)),
        msg('4', chat_id='C', direction='out', created=t(8, 30)),                   # ми відповіли
        msg('5', chat_id='D', direction='in', created=t(9, 50)),                    # лише 10 хв
    ])
    out = s.unanswered(now=t(10), older_than_min=30)
    assert [x['chat_id'] for x in out] == ['A', 'B']
    assert out[0]['waiting_min'] == 120 and out[0]['buyer_name'] == 'Перший'
    assert out[0]['marketplace'] == 'rozetka'


# ── collect ───────────────────────────────────────────────────────────

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)          # 15:00 за Києвом


class FakeRozetka:
    def __init__(self, chats, per_page=2, fail_chat=None, fail_list=False):
        self.chats = chats                 # id → повний чат з messages
        self.per_page = per_page
        self.fail_chat = fail_chat
        self.fail_list = fail_list
        self.fetched = []

    def list_page(self, page):
        if self.fail_list:
            raise ConnectionError('Rozetka недоступна')
        items = [{k: v for k, v in c.items() if k != 'messages'} for c in self.chats.values()]
        pages = max(1, -(-len(items) // self.per_page))
        chunk = items[(page - 1) * self.per_page: page * self.per_page]
        return {'chats': chunk, '_meta': {'pageCount': pages, 'currentPage': page}}

    def get_chat(self, chat_id):
        self.fetched.append(chat_id)
        if chat_id == self.fail_chat:
            raise TimeoutError('таймаут')
        return self.chats[chat_id]


def three_chats():
    return {
        1: rz_chat(1, '2026-09-19 14:00:00', [rz_msg(11, 3, '2026-09-19 13:50:00', 'свіже')]),
        2: rz_chat(2, '2026-09-10 10:00:00', [rz_msg(21, 3, '2026-09-10 09:00:00', 'старе'),
                                              rz_msg(22, 2, '2026-09-10 10:00:00', 'наше')]),
        3: rz_chat(3, '2026-09-19 11:00:00', [rz_msg(31, 2, '2026-09-19 11:00:00', 'лише наше')]),
    }


def test_first_run_stores_all_but_shows_recent_incoming_only():
    s = InboxStore()
    fake = FakeRozetka(three_chats())
    res = collect.collect_rozetka(fake.list_page, fake.get_chat, s, now=NOW)
    assert [m.msg_id for m in res['new']] == ['11']
    assert res['errors'] == []
    assert res['chats_checked'] == 3
    assert res['cursor'] == '2026-09-19 14:00:00'
    assert s.get_cursor('rozetka') == '2026-09-19 14:00:00'
    assert s.add_new(normalize.from_rozetka(fake.chats[2])) == []     # старе теж у базі


def test_second_run_fetches_only_updated_chats():
    s = InboxStore()
    chats = three_chats()
    fake = FakeRozetka(chats)
    collect.collect_rozetka(fake.list_page, fake.get_chat, s, now=NOW)
    chats[2]['updated'] = '2026-09-19 14:30:00'
    chats[2]['messages'].append(rz_msg(23, 3, '2026-09-19 14:30:00', 'нове питання'))
    fake2 = FakeRozetka(chats)
    res = collect.collect_rozetka(fake2.list_page, fake2.get_chat, s, now=NOW)
    assert fake2.fetched == [2]
    assert [m.msg_id for m in res['new']] == ['23']
    assert res['cursor'] == '2026-09-19 14:30:00'


def test_all_pages_visited_regardless_of_order():
    chats = three_chats()
    reordered = {k: chats[k] for k in (2, 3, 1)}           # свіжий чат на останній сторінці
    fake = FakeRozetka(reordered, per_page=1)
    s = InboxStore()
    s.set_cursor('rozetka', '2026-09-19 12:00:00')
    res = collect.collect_rozetka(fake.list_page, fake.get_chat, s, now=NOW)
    assert fake.fetched == [1]
    assert [m.msg_id for m in res['new']] == ['11']


def test_failed_chat_does_not_move_cursor_and_others_processed():
    s = InboxStore()
    s.set_cursor('rozetka', '2026-09-01 00:00:00')
    fake = FakeRozetka(three_chats(), fail_chat=3)
    res = collect.collect_rozetka(fake.list_page, fake.get_chat, s, now=NOW)
    assert {m.msg_id for m in res['new']} == {'11', '21'}
    assert len(res['errors']) == 1 and '3' in res['errors'][0]
    assert res['cursor'] == '2026-09-01 00:00:00'
    assert s.get_cursor('rozetka') == '2026-09-01 00:00:00'
    # наступний запуск без збою добирає пропущене й не дублює вже показане
    fake2 = FakeRozetka(three_chats())
    res2 = collect.collect_rozetka(fake2.list_page, fake2.get_chat, s, now=NOW)
    assert res2['new'] == []          # у чаті 3 лише наше повідомлення
    assert res2['errors'] == []
    assert s.get_cursor('rozetka') == '2026-09-19 14:00:00'


def test_list_failure_is_reported_not_raised():
    s = InboxStore()
    s.set_cursor('rozetka', '2026-09-01 00:00:00')
    fake = FakeRozetka(three_chats(), fail_list=True)
    res = collect.collect_rozetka(fake.list_page, fake.get_chat, s, now=NOW)
    assert res['new'] == [] and res['errors']
    assert s.get_cursor('rozetka') == '2026-09-01 00:00:00'


def test_max_pages_limit():
    chats = {i: rz_chat(i, '2026-09-19 14:00:00', [rz_msg(i * 10, 3, '2026-09-19 13:00:00')])
             for i in range(1, 11)}
    fake = FakeRozetka(chats, per_page=1)
    res = collect.collect_rozetka(fake.list_page, fake.get_chat, InboxStore(), now=NOW, max_pages=3)
    assert res['chats_checked'] == 3


# ── render ────────────────────────────────────────────────────────────

def test_card_contents_escaped_and_masked():
    m = msg(body='<b>Терміново</b> дзвоніть 067 123 45 67', buyer_name='Іван <script>',
            subject='Питання', order_id='906298386', item_id='777', has_files=True, chat_id='42')
    out = render.card(m)
    first = out.splitlines()[0]
    assert '🟢 Rozetka' in first and 'чат 42' in first
    assert '<script>' not in out and '&lt;script&gt;' in out
    assert '<b>Терміново</b>' not in out
    assert '123 45 67' not in out and '[телефон приховано]' in out
    assert 'Замовлення: 906298386' in out and 'Товар: 777' in out
    assert '📎' in out
    assert 'реплаєм' in out.splitlines()[-1]


def test_card_truncates_long_body():
    out = render.card(msg(body='я' * 5000))
    assert 'я' * render.MAX_BODY + '…' in out
    assert 'я' * (render.MAX_BODY + 1) not in out


def test_card_other_marketplaces():
    assert '🟣 Prom' in render.card(msg(marketplace='prom'))
    assert '🟠 Епіцентр' in render.card(msg(marketplace='epicentr'))


def test_reminder():
    assert render.reminder([]) == ''
    out = render.reminder([{'marketplace': 'rozetka', 'chat_id': 'A', 'buyer_name': 'X', 'waiting_min': 120},
                           {'marketplace': 'prom', 'chat_id': 'B', 'buyer_name': '', 'waiting_min': 45}])
    first = out.splitlines()[0]
    assert '⏰' in first and '2' in first
    assert 'чат A' in out and '120' in out and 'чат B' in out and '45' in out


# ── reply ─────────────────────────────────────────────────────────────

@pytest.fixture
def linked():
    s = InboxStore()
    s.link_tg(500, 'rozetka', '42')
    return s


def test_reply_bad_mode(linked):
    with pytest.raises(ValueError):
        reply.plan_reply(500, 'Добрий день', linked, 'auto')


def test_reply_not_linked(linked):
    for tg_id in (None, 999):
        r = reply.plan_reply(tg_id, 'Добрий день', linked, 'live')
        assert r['ok'] is False and r['action'] == 'none'


def test_reply_empty_and_too_long(linked):
    assert reply.plan_reply(500, '   ', linked, 'live')['ok'] is False
    r = reply.plan_reply(500, 'а' * 2001, linked, 'live')
    assert r['ok'] is False and '2000' in r['message']
    assert r['marketplace'] == 'rozetka' and r['chat_id'] == '42'


@pytest.mark.parametrize('text', [
    'Подзвоніть 067 123 45 67', 'пишіть на shop@example.com', 'дивіться https://example.com',
    'www.example.com', 'наш t.me/shop', 'пишіть у Viber', 'або в TELEGRAM', 'WhatsApp теж',
])
def test_reply_contacts_forbidden(linked, text):
    r = reply.plan_reply(500, text, linked, 'live')
    assert r['ok'] is False and r['action'] == 'none'


def test_reply_modes(linked):
    off = reply.plan_reply(500, 'Так, є в наявності', linked, 'off')
    assert off['ok'] is False and off['action'] == 'none' and 'вимкнено' in off['message']
    draft = reply.plan_reply(500, '  Так, є в наявності  ', linked, 'draft')
    assert draft['ok'] is True and draft['action'] == 'none'
    assert draft['body'] == 'Так, є в наявності' and 'чернетка' in draft['message'].lower()
    live = reply.plan_reply(500, 'Так, є в наявності. Замовлення 906298386 відправимо сьогодні', linked, 'live')
    assert live['ok'] is True and live['action'] == 'send'
    assert (live['marketplace'], live['chat_id']) == ('rozetka', '42')
    assert '906298386' in live['body']
