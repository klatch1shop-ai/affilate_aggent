"""Приведення значень до букви довідника, 27.09.2026. Приклади — зі
справжнього набору 7216, де з 1249 значень записалось лише 63."""
import pytest

from content import epicentr_value_map as vm

STAT = {'для чоловіків': 'c1', 'для жінок': 'c2'}
TYPE = {'сукня': 't1', 'боді': 't2', 'пеньюар': 't3', 'панчохи': 't4'}


@pytest.mark.parametrize('value,expected', [
    ('Жіноча', 'для жінок'), ('жіноча', 'для жінок'),
    ('жіночий', 'для жінок'), ('Жіночий', 'для жінок'),
    ('Чоловіча', 'для чоловіків'), ('чоловічий', 'для чоловіків'),
])
def test_gender_wording_differs_from_dictionary(value, expected):
    """616 значень статі провалювались саме тут."""
    found, how = vm.match(value, STAT, 'Стать')
    assert found == expected and how == 'синонім'


@pytest.mark.parametrize('value,expected', [
    ('Сукня', 'сукня'), ('Боді', 'боді'), ('Пеньюар', 'пеньюар'),
])
def test_capital_letter_alone_broke_hundreds(value, expected):
    found, how = vm.match(value, TYPE, 'Тип товару')
    assert found == expected and how == 'регістр'


def test_exact_match_is_reported_as_exact():
    assert vm.match('сукня', TYPE, 'Тип товару') == ('сукня', 'точний')


def test_multiword_value_matched_by_unique_word():
    """«Еротична сукня» → «сукня», бо серед дозволених це єдиний відповідник."""
    found, how = vm.match('Еротична сукня', TYPE, 'Тип товару')
    assert found == 'сукня' and how == 'частина'


def test_ambiguous_match_is_refused_not_guessed():
    options = {'сукня': 'a', 'сукня вечірня': 'b'}
    found, how = vm.match('вечірня сукня', options, 'Тип товару')
    assert found is None and how in ('неоднозначно', 'немає відповідника')


def test_unknown_value_is_not_forced():
    found, how = vm.match('Бейбідол', TYPE, 'Тип товару')
    assert found is None and how == 'немає відповідника'


def test_apostrophe_and_spacing_do_not_break_match():
    options = {"пов'язка": 'x'}
    assert vm.match('Пов’язка', options, 'Тип')[0] == "пов'язка"
    assert vm.match('  пов`язка  ', options, 'Тип')[0] == "пов'язка"


def test_map_values_reports_every_decision():
    out, report = vm.map_values({'Стать': 'Жіноча', 'Тип товару': 'Бейбідол'},
                                {'Стать': STAT, 'Тип товару': TYPE})
    assert out == {'Стать': 'для жінок'}
    assert {r['як'] for r in report} == {'синонім', 'немає відповідника'}


def test_empty_inputs_are_safe():
    assert vm.match('', TYPE, 'Тип')[0] is None
    assert vm.match('сукня', {}, 'Тип')[0] is None
    assert vm.map_values(None, {}) == ({}, [])
