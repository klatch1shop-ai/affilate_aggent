"""Приймальні тести TASK-03 §4.1: приховування телефонів і email.

Написані замовником ДО виконання. Виконавець їх не змінює.
"""
import importlib

import pytest

privacy = importlib.import_module('tg_dispatcher.privacy')
commands = importlib.import_module('tg_dispatcher.ai_brain.commands')

MASK = '[телефон приховано]'

PHONES = [
    '0671234567',
    '+380671234567',
    '380671234567',
    '+38 (067) 123-45-67',
    '067 123 45 67',
    '067-123-45-67',
    '(067)1234567',
    '+38 067 123 45 67',
]


@pytest.mark.parametrize('phone', PHONES)
def test_phone_formats_masked(phone):
    out = privacy.mask_private(f'передзвоніть {phone} будь ласка')
    assert MASK in out
    digits = ''.join(ch for ch in out if ch.isdigit())
    assert digits == '', f'лишились цифри телефону: {out!r}'


@pytest.mark.parametrize('text', [
    'замовлення 906298386',
    'ТТН 20451538685877',
    'дата 2026-09-19',
    'дата 19.09.2026',
    'ціна 1 250 грн',
    'ціна 12500',
    'код 1234567890',
    '906298386 20451538685877',
])
def test_non_phones_untouched(text):
    assert privacy.mask_private(text) == text


def test_several_phones_all_masked():
    out = privacy.mask_private('0671234567 або +38 (050) 765-43-21')
    assert out.count(MASK) == 2


def test_phone_next_to_ttn_and_order():
    out = privacy.mask_private('ТТН 20451538685877, тел. 0671234567, замовлення 906298386')
    assert '20451538685877' in out
    assert '906298386' in out
    assert '0671234567' not in out
    assert MASK in out


def test_email_masked():
    out = privacy.mask_private('пишіть на buyer.name+1@mail.example.com')
    assert '@' not in out
    assert '[email приховано]' in out


def test_empty():
    assert privacy.mask_private('') == ''


def test_commands_use_new_masking():
    """TASK-02 маскував лише суцільні цифри; готовий рядок system має бути чистим."""
    parsed = {'intent': 'system_status', 'confidence': 0.9, 'params': {}}
    out = commands.dispatch(parsed, {'system': lambda: 'клієнт +38 (067) 123-45-67 чекає'})
    assert '123-45-67' not in out
    assert MASK in out
