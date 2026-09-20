"""Приймальні тести TASK-19: пакетний розбір відео конкурентів.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib
import json

import pytest

comp = importlib.import_module('content.competitors')


def analysis(**over):
    d = {'hook': 'Три помилки при виборі ключа', 'hook_type': 'проблема', 'length_sec': 42,
         'format': 'огляд товару', 'topic': 'ключі TOPTUL', 'has_face': True,
         'cta': 'підписка', 'claims': ['хром-ванадій міцніший']}
    d.update(over)
    return json.dumps(d, ensure_ascii=False)


# ── розбір відповіді ──────────────────────────────────────────────────

def test_parse_analysis_normalizes():
    d = comp.parse_analysis('```json\n' + analysis(hook_type='жарт', length_sec='45 с',
                                                   has_face='ні', claims='одне твердження') + '\n```')
    assert set(d) == set(comp.FIELDS)
    assert d['hook_type'] == 'інше' and d['length_sec'] == 45
    assert d['has_face'] is False and d['claims'] == ['одне твердження']


def test_parse_analysis_missing_and_bad():
    d = comp.parse_analysis('{"hook": "лише гачок"}')
    assert d['hook'] == 'лише гачок' and d['length_sec'] is None and d['claims'] == []
    assert d['hook_type'] == 'інше'
    with pytest.raises(ValueError):
        comp.parse_analysis('зовсім не json')


def test_question_demands_json_and_forbids_invention():
    q = comp.QUESTION.lower()
    assert 'json' in q and ('null' in q or 'не вигад' in q)
    for f in comp.FIELDS:
        assert f in comp.QUESTION


# ── пакет ─────────────────────────────────────────────────────────────

class Analyzer:
    def __init__(self, by_url=None, fail=None):
        self.by_url, self.fail, self.calls = by_url or {}, fail or {}, []

    def __call__(self, url, question):
        self.calls.append(url)
        if url in self.fail:
            raise self.fail[url]
        return self.by_url.get(url, analysis())


def test_analyze_batch_dedups_and_limits():
    a = Analyzer()
    urls = ['u1', 'u2', 'u1', 'u3', 'u4']
    out = comp.analyze_batch(urls, a, limit=3)
    assert a.calls == ['u1', 'u2', 'u3'] and out['asked'] == 3
    assert [i['url'] for i in out['items']] == ['u1', 'u2', 'u3'] and out['errors'] == []


def test_analyze_batch_survives_errors():
    a = Analyzer(by_url={'u2': 'не json'}, fail={'u1': TimeoutError('довго')})
    out = comp.analyze_batch(['u1', 'u2', 'u3'], a)
    assert [i['url'] for i in out['items']] == ['u3']
    assert len(out['errors']) == 2 and any('u1' in e for e in out['errors'])


# ── зведення ──────────────────────────────────────────────────────────

def items():
    return [
        {'hook_type': 'проблема', 'length_sec': 40, 'format': 'огляд', 'topic': 'Ключі TOPTUL',
         'has_face': True, 'claims': ['хром-ванадій міцніший'], 'url': 'u1', 'hook': 'a', 'cta': 'c'},
        {'hook_type': 'цифра', 'length_sec': 20, 'format': 'огляд', 'topic': 'ключі toptul  ',
         'has_face': False, 'claims': ['хром-ванадій міцніший', 'гарантія 10 років'], 'url': 'u2', 'hook': 'b', 'cta': 'c'},
        {'hook_type': 'проблема', 'length_sec': None, 'format': 'порівняння', 'topic': 'набори',
         'has_face': False, 'claims': [], 'url': 'u3', 'hook': 'c', 'cta': None},
    ]


def test_summarize():
    s = comp.summarize(items())
    assert s['total'] == 3 and s['median_length'] == 30
    assert list(s['hook_types'].items())[0] == ('проблема', 2)
    assert list(s['formats'].items())[0] == ('огляд', 2)
    assert s['with_face'] == 1
    assert s['topics'][0][0].strip().lower() == 'ключі toptul' and s['topics'][0][1] == 2
    assert s['claims_top'][0] == ('хром-ванадій міцніший', 2)


def test_summarize_empty():
    s = comp.summarize([])
    assert s['total'] == 0 and s['median_length'] is None and s['topics'] == []


def test_report_text():
    text = comp.report(comp.summarize(items()))
    assert 'Розібрано: 3' in text and '30' in text
    assert 'проблема' in text and 'огляд' in text and 'ключі toptul' in text.lower()
    assert 'З обличчям: 1' in text
    assert comp.report(comp.summarize([])) == 'Нема даних'
