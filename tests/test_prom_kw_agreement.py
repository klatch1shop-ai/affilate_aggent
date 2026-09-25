"""Регресія 25.09.2026: `_adj_noun_agree` у tools/prom_kw_matrix.py — заміна
`_is_adj` (закінчення) для шару 3 справжньою морфологією (pymorphy3).

Перевірено живим прогоном на фіді 5384 офферів: 2721 фраза додатково до 859
чинних (_strict_pair), 0 нових суперечностей із «Призначенням» (після
виправлення самого --report, який рахував без `name` — tools/prom_kw_matrix.py
`main()`), 97→52 карток із < 4 фраз. Деталі: docs/research/PROM_KEYWORDS_MORPH_25.09.md
"""
import importlib
import sys

import pytest

sys.path.insert(0, '/home/tekken/agent-system/tools')
kw = importlib.import_module('prom_kw_matrix')


@pytest.mark.parametrize('adj,noun,expected', [
    ('ерекційне', 'кільце', True),
    ('анальний', 'вібратор', True),
    ('потужний', 'вібратор', True),
    ('жіночий', 'вібратор', True),
    ('кліторальний', 'стимулятор', True),
    ('якісний', 'фалоімітатор', True),
])
def test_agrees_real_phrases_from_feed(adj, noun, expected):
    assert kw._adj_noun_agree(adj, noun) is expected


@pytest.mark.parametrize('adj,noun', [
    ('кільце', 'ерекційне'),        # порядок навпаки — не приймаємо
    ('класичного', 'вібратора'),    # родовий відмінок, не називний
    ('вазі', 'вагінальні'),         # місцевий іменник + мн. прикметник — не узгоджені
])
def test_agrees_rejects_bad_pairs(adj, noun):
    assert kw._adj_noun_agree(adj, noun) is False


def test_agrees_requires_gender_agreement_singular():
    # «потужна» (жін.) не узгоджується з «вібратор» (чол.)
    assert kw._adj_noun_agree('потужна', 'вібратор') is False
    assert kw._adj_noun_agree('потужний', 'вібратор') is True


def test_agrees_plural_does_not_need_gender_match():
    # «вагінальні кульки» — pymorphy без контексту ранжує «кульки» як родовий
    # однини й називний множини РІВНОЗНАЧНО (score 1.0 обидва) — тому
    # перевіряються ВСІ розбори, не лише parse()[0] (знайдено 25.09.2026).
    assert kw._adj_noun_agree('вагінальні', 'кульки') is True


def test_agrees_known_limitation_predicate_adjective_before_noun():
    """«здатний» граматично узгоджується з «вібратор» (обидва чол. одн. наз.),
    хоч у природній мові це присудкова конструкція, не означення. Реальний
    прогін на фіді (5384 офферів) не показав жодного випадку «здатний» чи
    подібних слів ПЕРЕД іменником — лише ПІСЛЯ («вібратор здатний»), що вже
    відсікається вимогою порядку. Це задокументоване залишкове обмеження,
    не тест на бажану поведінку."""
    assert kw._adj_noun_agree('здатний', 'вібратор') is True


def test_selftest_name_type_still_passes():
    """Новий фільтр не зачіпає розбір НАЗВИ (інша функція, _is_adj там лишився)."""
    assert kw.selftest_name_type(verbose=False) is True
