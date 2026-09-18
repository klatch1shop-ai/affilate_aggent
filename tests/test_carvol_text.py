"""Тести розбору ТТН з тексту Carvol (tg_dispatcher/ai_brain/carvol_text.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tg_dispatcher'))
from ai_brain.carvol_text import extract_ttns, extract_order_ids, resolve  # noqa: E402

A = {'order_id': 906298386, 'phone': '380671112233', 'recipient': 'Петренко Іван'}
B = {'order_id': 906311571, 'phone': '380504445566', 'recipient': 'Коваль Ольга'}


def np_fake(owner_phone_by_ttn):
    def look(ttn, phone):
        real = owner_phone_by_ttn.get(ttn)
        if real and phone and phone[-9:] == real[-9:]:
            return {'recipient_phone': real, 'recipient_name': 'X', 'city': 'Київ'}
        return {'recipient_phone': None}          # НП ховає дані при чужому телефоні
    return look


def test_extract():
    t = 'ттн 20451539117101, 20451539117102 ; замовл. 906298386\n20451539117101'
    assert extract_ttns(t) == ['20451539117101', '20451539117102']
    assert extract_order_ids(t) == ['906298386']
    assert extract_ttns('ttn: 2045 1539 1171 01') == []          # з пробілами не вгадуємо
    assert extract_ttns('') == [] and extract_order_ids(None) == []


def test_resolve_by_phone():
    look = np_fake({'20450000000001': A['phone']})
    oid, why = resolve('20450000000001', [A, B], look)
    assert oid == 906298386 and 'підтвердила' in why


def test_resolve_none():
    oid, why = resolve('20450000000009', [A, B], np_fake({}))
    assert oid is None


def test_resolve_ambiguous():
    same = dict(B, phone=A['phone'])
    oid, why = resolve('20450000000001', [A, same], np_fake({'20450000000001': A['phone']}))
    assert oid is None and 'неоднозначно' in why


def test_order_hint_limits_pool():
    look = np_fake({'20450000000001': A['phone']})
    assert resolve('20450000000001', [A, B], look, order_hint='906311571')[0] is None
    assert resolve('20450000000001', [A, B], look, order_hint='906298386')[0] == 906298386
    assert 'немає' in resolve('20450000000001', [A, B], look, order_hint='900000000')[1]


def test_np_error_is_not_confirmation():
    look = lambda t, p: {'error': 'таймаут'}
    assert resolve('20450000000001', [A], look)[0] is None


def test_parse_ttn_command():
    from ai_brain.carvol_text import parse_ttn_command
    assert parse_ttn_command('/ttn 906298386 20451539117101') == ('906298386', '20451539117101')
    assert parse_ttn_command('/ttn@bot 906298386 20451539117101') == ('906298386', '20451539117101')
    for bad in ('/ttn 906298386', '/ttn 12345 20451539117101', '/ttn 906298386 2045153911710',
                '/status 906298386 20451539117101', ''):
        assert parse_ttn_command(bad) is None, bad
