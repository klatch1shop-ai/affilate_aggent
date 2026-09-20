"""Приймальні тести TASK-20: перенесення звітів у сховище знань.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib

import pytest

ing = importlib.import_module('content.ingest')

REPORT = """# Радар трендів ніші

**Дата:** 20.09.2026. **Джерело:** перевірка вручну.

Короткий вступ про ніші.

## Що зроблено

Зібрано ролики з Rozetka і Нова Пошта, телефон 0671234567 у примітці.

## Висновки

Prom дає менше переглядів, ніж Rozetka.
"""


# ── slug ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('title,slug', [
    ('Радар трендів ніші', 'радар-трендів-ніші'),
    ('ЗАВДАННЯ 31: перевірка фактів', 'завдання-31-перевірка-фактів'),
    ('  Кілька   пробілів  ', 'кілька-пробілів'),
    ('A_B — C', 'a-b-c'),
])
def test_slugify(title, slug):
    assert ing.slugify(title) == slug


def test_slugify_length_and_empty():
    assert len(ing.slugify('слово ' * 30)) <= 60
    assert not ing.slugify('слово ' * 30).endswith('-')
    with pytest.raises(ValueError):
        ing.slugify('!!! ??? ...')


# ── розбір звіту ──────────────────────────────────────────────────────

def test_parse_report():
    r = ing.parse_report(REPORT)
    assert r['title'] == 'Радар трендів ніші' and r['date'] == '2026-09-20'
    assert [s['heading'] for s in r['sections']] == ['Вступ', 'Що зроблено', 'Висновки']
    assert r['sections'][0]['body'] == 'Короткий вступ про ніші.'
    assert r['sections'][-1]['body'] == 'Prom дає менше переглядів, ніж Rozetka.'


def test_parse_report_without_date_and_sections():
    r = ing.parse_report('# Лише заголовок\n')
    assert r['title'] == 'Лише заголовок' and r['date'] is None and r['sections'] == []
    with pytest.raises(ValueError):
        ing.parse_report('без заголовка\n## Секція\n')


# ── звʼязки ───────────────────────────────────────────────────────────

def test_wikify_first_occurrence_only():
    out = ing.wikify('Rozetka і ще раз Rozetka', ['Rozetka'])
    assert out == '[[Rozetka]] і ще раз Rozetka'


def test_wikify_case_and_word_boundary():
    assert ing.wikify('розетка інша', ['Rozetka']) == 'розетка інша'
    assert ing.wikify('ROZETKA велика', ['Rozetka']) == '[[ROZETKA]] велика'
    assert ing.wikify('Прометей там', ['Prom']) == 'Прометей там'
    assert ing.wikify('Prom там', ['Prom']) == '[[Prom]] там'


def test_wikify_longest_first_and_existing_links():
    out = ing.wikify('Нова Пошта і Пошта окремо', ['Пошта', 'Нова Пошта'])
    assert out == '[[Нова Пошта]] і [[Пошта]] окремо'
    assert ing.wikify('[[Rozetka]] уже звʼязана', ['Rozetka']) == '[[Rozetka]] уже звʼязана'
    assert ing.wikify('текст', []) == 'текст'
    assert ing.wikify('текст', ['']) == 'текст'


# ── нотатка ───────────────────────────────────────────────────────────

def note():
    return ing.build_note(ing.parse_report(REPORT), source='docs/research/TRENDS.md',
                          known=['Rozetka', 'Нова Пошта', 'Prom'])


def test_build_note_path_and_frontmatter():
    n = note()
    assert n['path'] == f'{ing.VAULT}/радар-трендів-ніші.md'
    lines = n['content'].splitlines()
    assert lines[0] == '---'
    assert 'title: Радар трендів ніші' in lines
    assert 'date: 2026-09-20' in lines
    assert 'source: docs/research/TRENDS.md' in lines
    assert lines[lines.index('---', 1)] == '---'
    assert n['content'].endswith('\n') and not n['content'].endswith('\n\n')


def test_build_note_masks_then_links():
    body = note()['content']
    assert '0671234567' not in body and '[телефон приховано]' in body
    assert '[[Rozetka]]' in body and '[[Нова Пошта]]' in body
    assert '## Що зроблено' in body and '## Висновки' in body
    assert body.count('[[Rozetka]]') == 1                 # лише перша поява


def test_build_note_quotes_colon_in_title():
    n = ing.build_note(ing.parse_report('# ЗАВДАННЯ 31: перевірка\n'), source='s')
    assert 'title: "ЗАВДАННЯ 31: перевірка"' in n['content']


# ── журнал і план ─────────────────────────────────────────────────────

def test_log_line():
    n = note()
    assert ing.log_line(n) == '- [[радар-трендів-ніші]] — Радар трендів ніші (2026-09-20)'
    no_date = ing.build_note(ing.parse_report('# Без дати\n'), source='s')
    assert ing.log_line(no_date) == '- [[без-дати]] — Без дати'


def test_plan_create_skip_conflict():
    n = note()
    assert ing.plan([n], {}) == {'create': [n], 'skip': [], 'conflict': []}
    same = ing.plan([n], {n['path']: n['content']})
    assert same['create'] == [] and same['skip'] == [n['path']] and same['conflict'] == []
    other = ing.plan([n], {n['path']: 'чужий текст'})
    assert other['create'] == [] and other['conflict'] == [n['path']] and other['skip'] == []


def test_plan_duplicate_paths_inside_batch():
    n = note()
    out = ing.plan([n, dict(n)], {})
    assert out['create'] == [n] and out['conflict'] == [n['path']]
