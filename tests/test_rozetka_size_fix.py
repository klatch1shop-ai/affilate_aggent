"""Звірка розміру назва ↔ параметр, 26.09.2026. Приклади — зі справжніх
повернутих карток Rozetka, не вигадані."""
import pytest

from content import rozetka_size_fix as sz


@pytest.mark.parametrize('name,expected', [
    ('Боді Passion ADARA L/XL Чорний (EL10101)', ('L/XL', 'L', 'XL')),
    ('Боді Passion ADARA S/M Чорний (EL10102)', ('S/M', 'S', 'M')),
    ('Боді Passion ADARA XXL/XXXL Чорний (EL10103)', ('XXL/XXXL', '2XL', '3XL')),
    ('Боді Obsessive Donna Dream crotchless teddy XL/2XL Чорний (SO8635)',
     ('XL/2XL', 'XL', '2XL')),
    ('Корсет Passion JANET CORSET L Білий', ('L', 'L', None)),
])
def test_size_in_name_real_examples(name, expected):
    whole, first, second = sz.size_in_name(name)
    assert (whole.strip(), first, second) == expected


def test_xxl_and_2xl_are_the_same_value():
    assert sz.canon('XXL') == sz.canon('2XL') == '2XL'
    assert sz.canon('XXXL') == '3XL'
    assert sz.canon('l') == 'L'


@pytest.mark.parametrize('name', [
    'Вібратор Satisfyer Pro 2 Чорний (SO1234)',     # нема розміру
    'Мастило Durex Play 50 мл',
    '',
    None,
])
def test_no_size_found(name):
    assert sz.size_in_name(name) is None


def test_does_not_match_letters_inside_words():
    """«S» у слові не є розміром, інакше ми б «виправляли» назви навмання."""
    assert sz.size_in_name('Боді Passion CHARMING Чорний') is None


# ── вердикти ──────────────────────────────────────────────────────────

def test_range_in_name_gets_proposal():
    out = sz.check('Боді Passion ADARA L/XL Чорний (EL10101)', 'L')
    assert out['status'] == 'діапазон у назві'
    assert out['proposed_name'] == 'Боді Passion ADARA L Чорний (EL10101)'


def test_range_notation_difference_is_still_a_match():
    """У назві XXL/XXXL, у параметрі 2XL — це те саме значення."""
    out = sz.check('Боді Passion ADARA XXL/XXXL Чорний', '2XL')
    assert out['status'] == 'діапазон у назві'
    assert out['proposed_name'] == 'Боді Passion ADARA 2XL Чорний'


def test_exact_match_needs_no_change():
    out = sz.check('Корсет Passion JANET L Білий', 'L')
    assert out['status'] == 'збігається'
    assert 'proposed_name' not in out


def test_real_disagreement_is_flagged_not_auto_fixed():
    """Назва каже S, параметр L — це не нотація, це суперечність, і
    пропозиції тут не буде: потрібна людина."""
    out = sz.check('Боді Passion ADARA S Чорний', 'L')
    assert out['status'] == 'розбіжність'
    assert 'proposed_name' not in out


def test_range_matching_neither_side_is_disagreement():
    out = sz.check('Боді Passion ADARA S/M Чорний', '2XL')
    assert out['status'] == 'розбіжність'


def test_missing_param_is_its_own_case():
    """78 із 536 карток узагалі не мають параметра «Розмір»."""
    out = sz.check('Боді Passion ADARA L/XL Чорний', None)
    assert out['status'] == 'немає параметра'
    assert out['name_size'] == 'L'


def test_missing_size_in_name():
    out = sz.check('Вібратор Satisfyer Pro 2 Чорний', 'One Size')
    assert out['status'] == 'немає розміру в назві'


def test_propose_replaces_only_first_occurrence():
    name = 'Комплект L/XL для розміру L/XL'
    assert sz.propose(name, 'L/XL', 'L') == 'Комплект L для розміру L/XL'
