"""Тести генератора команд Telegram з реєстру методів Prom API (26.09.2026).

Реєстр → короткий опис методу → Gemini → команда каталогу (title/example/needs/group).
"""
import importlib

import pytest

gen = importlib.import_module('content.prom_command_gen')
reg = importlib.import_module('content.prom_api_registry')


def test_build_prompt_mentions_method_and_params():
    p = gen.build_prompt('orders_list', reg.METHODS['orders_list'])
    assert 'orders_list' in p and 'JSON' in p.upper()
    assert 'status' in p and 'date_from' in p
    assert 'не вигад' in p.lower()


def test_build_prompt_forbids_invented_params():
    p = gen.build_prompt('groups_list', reg.METHODS['groups_list'])
    assert 'лише' in p.lower() or 'тільки' in p.lower()


def test_parse_command_ok():
    text = '```json\n{"title": "Нові замовлення Prom", "example": "нові замовлення пром", "needs": ["status"]}\n```'
    d = gen.parse_command(text)
    assert d == {'title': 'Нові замовлення Prom', 'example': 'нові замовлення пром', 'needs': ['status']}


def test_parse_command_missing_needs_defaults_empty():
    d = gen.parse_command('{"title": "Групи товарів", "example": "групи товарів пром"}')
    assert d['needs'] == []


def test_parse_command_bad_json_raises():
    with pytest.raises(ValueError):
        gen.parse_command('не json')


def test_parse_command_missing_title_raises():
    with pytest.raises(ValueError):
        gen.parse_command('{"example": "x"}')


@pytest.mark.parametrize('needs,allowed,ok', [
    (['status'], {'status', 'limit'}, True),
    (['status', 'wizard'], {'status', 'limit'}, False),   # вигадав параметр
    ([], {'status'}, True),
])
def test_validate_needs_against_real_params(needs, allowed, ok):
    assert gen.needs_are_real(needs, allowed) is ok


def test_tag_to_group_covers_all_registry_tags():
    tags = {m['tag'] for m in reg.METHODS.values()}
    for t in tags:
        assert gen.TAG_TO_GROUP[t] in ('Замовлення', 'Посилки', 'Покупці', 'Повернення',
                                       'Товари', 'Постачальники', 'Гроші', 'Система')


def test_to_catalog_entry_shape():
    cmd = {'title': 'Нові замовлення Prom', 'example': 'нові замовлення пром', 'needs': ['status']}
    entry = gen.to_catalog_entry('orders_list', cmd, reg.METHODS['orders_list'])
    assert entry == {'title': 'Нові замовлення Prom', 'risk': 'R0', 'needs': ['status'],
                     'example': 'нові замовлення пром', 'group': 'Замовлення'}


def test_to_catalog_entry_risk_from_registry_not_gemini():
    cmd = {'title': 'Відповідь покупцю', 'example': 'відповісти покупцю', 'needs': ['id', 'message']}
    entry = gen.to_catalog_entry('messages_reply', cmd, reg.METHODS['messages_reply'])
    assert entry['risk'] == 'R3'   # ризик береться з реєстру (перевірений факт), не з тексту Gemini
