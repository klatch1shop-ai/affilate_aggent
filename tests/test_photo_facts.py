"""Приймальні тести TASK-31: перевірка фактів за фото упаковки.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib
import json

import pytest

pf = importlib.import_module('content.photo_facts')


def reading(**over):
    d = {'brand': 'Sensuva', 'name': ' Крем ', 'volume': '57 мл', 'weight': None,
         'country': '-', 'ingredients': ['вода', 'гліцерин'], 'warnings': 'невідомо'}
    d.update(over)
    return json.dumps(d, ensure_ascii=False)


# ── запит ─────────────────────────────────────────────────────────────

def test_question_demands_json_and_forbids_invention():
    q = pf.QUESTION.lower()
    assert 'json' in q and ('null' in q or 'не вигад' in q)
    for f in pf.FIELDS:
        assert f in pf.QUESTION


def test_fields_order():
    assert pf.FIELDS == ('brand', 'name', 'volume', 'weight', 'country', 'ingredients', 'warnings')


# ── розбір відповіді ──────────────────────────────────────────────────

def test_parse_reading_normalizes():
    d = pf.parse_reading('```json\n' + reading() + '\n```')
    assert tuple(d) == pf.FIELDS
    assert d['brand'] == 'Sensuva' and d['name'] == 'Крем'
    assert d['weight'] is None and d['country'] is None and d['warnings'] is None
    assert d['ingredients'] == 'вода, гліцерин'


def test_parse_reading_empty_values_and_numbers():
    d = pf.parse_reading(reading(volume=57, name='   ', brand='n/a'))
    assert d['volume'] == '57' and d['name'] is None and d['brand'] is None


def test_parse_reading_missing_and_bad():
    d = pf.parse_reading('{"brand": "лише бренд"}')
    assert tuple(d) == pf.FIELDS and d['brand'] == 'лише бренд'
    assert all(d[f] is None for f in pf.FIELDS if f != 'brand')
    with pytest.raises(ValueError):
        pf.parse_reading('зовсім не json')


# ── числа ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize('text,out', [
    ('180 g', [(180.0, 'g')]),
    ('190 г', [(190.0, 'g')]),
    ('1,5 кг', [(1500.0, 'g')]),
    ('57мл', [(57.0, 'ml')]),
    ('0,5 л', [(500.0, 'ml')]),
    ('96%', [(96.0, '%')]),
    ('96 %', [(96.0, '%')]),
    ('артикул 3142', []),
    ('без чисел', []),
    ('2 шт по 50 мл, ще 50 мл', [(2.0, 'pcs'), (50.0, 'ml')]),
])
def test_numbers(text, out):
    assert pf.numbers(text) == out


# ── читання фото ──────────────────────────────────────────────────────

class Reader:
    def __init__(self, by_path=None, fail=None):
        self.by_path, self.fail, self.calls = by_path or {}, fail or {}, []

    def __call__(self, path, question):
        self.calls.append(path)
        if path in self.fail:
            raise self.fail[path]
        return self.by_path.get(path, reading())


def test_read_photos_dedups_and_limits():
    r = Reader()
    out = pf.read_photos(['p1', 'p2', 'p1', 'p3', 'p4'], r, limit=3)
    assert r.calls == ['p1', 'p2', 'p3']
    assert [i['path'] for i in out['items']] == ['p1', 'p2', 'p3'] and out['errors'] == []


def test_read_photos_merges_first_non_empty():
    r = Reader(by_path={'p1': reading(brand=None, volume='57 мл'),
                        'p2': reading(brand='Sensuva', volume='60 мл', weight='180 g')})
    out = pf.read_photos(['p1', 'p2'], r)
    assert out['merged']['brand'] == 'Sensuva'
    assert out['merged']['volume'] == '57 мл'
    assert out['merged']['weight'] == '180 g'
    assert out['merged']['country'] is None


def test_read_photos_survives_errors():
    r = Reader(by_path={'p2': 'не json'}, fail={'p1': TimeoutError('довго')})
    out = pf.read_photos(['p1', 'p2', 'p3'], r)
    assert [i['path'] for i in out['items']] == ['p3']
    assert len(out['errors']) == 2 and any(e.startswith('p1:') for e in out['errors'])


def test_read_photos_limit_zero():
    r = Reader()
    out = pf.read_photos(['p1'], r, limit=0)
    assert r.calls == [] and out['items'] == [] and out['errors'] == []
    assert out['merged'] == {f: None for f in pf.FIELDS}


# ── звірка ────────────────────────────────────────────────────────────

SUPPLIER = {'weight': '190 г', 'volume': '57 мл', 'brand': 'Sensuva', 'country': 'США'}
PHOTO = {'weight': '180 g', 'volume': '57мл', 'brand': ' sensuva ', 'country': None, 'name': 'Крем'}


def test_compare_basic():
    c = pf.compare(SUPPLIER, PHOTO)
    assert [m['field'] for m in c['mismatch']] == ['weight']
    assert c['mismatch'][0] == {'field': 'weight', 'supplier': '190 г', 'photo': '180 g'}
    assert c['match'] == ['volume', 'brand']
    assert c['unreadable'] == ['country']
    assert c['only_photo'] == ['name'] and c['only_supplier'] == []


def test_compare_apostrophe_and_spaces():
    c = pf.compare({'name': "Об’єм  великий"}, {'name': "об'єм великий"})
    assert c['match'] == ['name'] and c['mismatch'] == []


def test_compare_numbers_on_one_side_only():
    c = pf.compare({'ingredients': 'вода 5%'}, {'ingredients': 'вода'})
    assert [m['field'] for m in c['mismatch']] == ['ingredients']


def test_compare_none_in_supplier_is_absent():
    c = pf.compare({'name': None}, {'name': 'Крем'})
    assert c['only_photo'] == ['name'] and c['match'] == [] and c['unreadable'] == []


def test_compare_only_supplier():
    c = pf.compare({'brand': 'X', 'ingredients': 'вода'}, {'brand': 'X'})
    assert c['only_supplier'] == ['ingredients'] and c['match'] == ['brand']


def test_compare_empty():
    c = pf.compare({}, {})
    assert c == {'match': [], 'mismatch': [], 'unreadable': [],
                 'only_supplier': [], 'only_photo': []}


# ── звіт ──────────────────────────────────────────────────────────────

def test_report_with_mismatch():
    text = pf.report(pf.compare(SUPPLIER, PHOTO))
    lines = text.splitlines()
    assert lines[0] == '❗ Розбіжності: 1'
    assert '• weight: постачальник «190 г» / упаковка «180 g»' in lines
    assert 'Збіглося: 2' in lines
    assert 'Не прочитано на фото: country' in lines
    assert 'Немає у постачальника: name' in lines
    assert not any(l.startswith('Немає на фото') for l in lines)


def test_report_clean():
    text = pf.report(pf.compare({'brand': 'X'}, {'brand': 'x'}))
    assert text.splitlines()[0] == '✅ Розбіжностей немає'
    assert 'Збіглося: 1' in text


def test_report_empty():
    assert pf.report(pf.compare({}, {})) == 'Нема даних'
