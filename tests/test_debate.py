"""Приймальні тести TASK-26: спір «за / проти».

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib
import json

import pytest

deb = importlib.import_module('research.debate')

CLAIM = 'ціна на SO3142 зависока'
EV = [{'id': 'e1', 'text': '5 питань про ціну за тиждень'},
      {'id': 'e2', 'text': 'конкурент на 12% дешевший'},
      {'id': 'e3', 'text': 'продажі не впали'},
      {'id': 'e4', 'text': 'залишок 40 шт'}]


def side(points):
    return json.dumps([{'point': p, 'refs': r} for p, r in points], ensure_ascii=False)


# ── запити ────────────────────────────────────────────────────────────

def test_build_prompts():
    p = deb.build_prompts(CLAIM, EV)
    assert set(p) == set(deb.SIDES)
    for text in p.values():
        assert CLAIM in text and 'JSON' in text.upper()
        for e in EV:
            assert f"[{e['id']}]" in text and e['text'] in text
        assert 'не вигад' in text.lower()
    assert p['за'] != p['проти']


@pytest.mark.parametrize('claim,ev', [('', EV), ('   ', EV), (CLAIM, []),
                                      (CLAIM, [{'id': 'e1', 'text': 'a'}, {'id': 'e1', 'text': 'b'}])])
def test_build_prompts_validation(claim, ev):
    with pytest.raises(ValueError):
        deb.build_prompts(claim, ev)


# ── розбір ────────────────────────────────────────────────────────────

def test_parse_side():
    raw = '```json\n' + json.dumps([
        {'point': '  питання про ціну  ', 'refs': ['e1', ' e2 ']},
        {'point': 'один доказ', 'refs': 'e3'},
        {'point': 'без доказів'},
        {'point': '   '},
        {'refs': ['e1']},
        {'point': 'зайві ключі', 'refs': ['e1'], 'score': 5},
    ], ensure_ascii=False) + '\n```'
    out = deb.parse_side(raw)
    assert [p['point'] for p in out] == ['питання про ціну', 'один доказ', 'без доказів', 'зайві ключі']
    assert out[0]['refs'] == ['e1', 'e2'] and out[1]['refs'] == ['e3'] and out[2]['refs'] == []
    assert set(out[3]) == {'point', 'refs'}


@pytest.mark.parametrize('bad', ['не json', '{"point": "словник"}', '5'])
def test_parse_side_bad(bad):
    with pytest.raises(ValueError):
        deb.parse_side(bad)


# ── зведення ──────────────────────────────────────────────────────────

def merged():
    pro = deb.parse_side(side([('питання про ціну', ['e1']), ('конкурент дешевший', ['e2', 'e3'])]))
    con = deb.parse_side(side([('продажі тримаються', ['e3']), ('здогад', []),
                               ('вигадка', ['e9'])]))
    return deb.merge(pro, con, EV)


def test_merge_counts_and_drops():
    m = merged()
    assert [p['point'] for p in m['for']] == ['питання про ціну', 'конкурент дешевший']
    assert [p['point'] for p in m['against']] == ['продажі тримаються']
    assert [(d['side'], d['reason']) for d in m['dropped']] == \
        [('проти', 'без доказу'), ('проти', 'невідомий доказ: e9')]
    assert m['unused'] == ['e4']
    assert m['balance'] == 'за'


def test_merge_balance_variants():
    pro = deb.parse_side(side([('а', ['e1'])]))
    con = deb.parse_side(side([('б', ['e2'])]))
    assert deb.merge(pro, con, EV)['balance'] == 'рівно'
    assert deb.merge(pro, [], EV)['balance'] == 'однобоко'
    assert deb.merge([], con, EV)['balance'] == 'однобоко'
    assert deb.merge(deb.parse_side(side([('а', ['e1']), ('б', ['e2'])])), con, EV)['balance'] == 'за'
    assert deb.merge(pro, deb.parse_side(side([('б', ['e2']), ('в', ['e3'])])), EV)['balance'] == 'проти'


def test_merge_all_dropped():
    m = deb.merge(deb.parse_side(side([('здогад', [])])), [], EV)
    assert m['for'] == [] and m['balance'] == 'однобоко' and len(m['dropped']) == 1
    assert m['unused'] == ['e1', 'e2', 'e3', 'e4']


# ── звіт ──────────────────────────────────────────────────────────────

def test_report():
    lines = deb.report(CLAIM, merged()).splitlines()
    assert lines[0] == '⚖️ ' + CLAIM
    assert lines[1] == 'За (2):'
    assert lines[2] == '• питання про ціну [e1]'
    assert lines[3] == '• конкурент дешевший [e2, e3]'
    assert lines[4] == 'Проти (1):'
    assert lines[5] == '• продажі тримаються [e3]'
    assert 'Відкинуто без доказу: 1' in lines
    assert 'Не використані докази: e4' in lines
    assert lines[-1] == 'Підсумок: за'


def test_report_empty_side():
    m = deb.merge(deb.parse_side(side([('а', ['e1'])])), [], EV)
    lines = deb.report(CLAIM, m).splitlines()
    assert 'Проти (0):' in lines and '• —' in lines
    assert not any(l.startswith('Відкинуто') for l in lines)
    assert lines[-1] == 'Підсумок: однобоко'
