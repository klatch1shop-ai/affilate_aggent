"""Приймальні тести TASK-18: ядро контент-заводу.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib

import pytest

topics = importlib.import_module('content.topics')
script = importlib.import_module('content.script')
subs = importlib.import_module('content.subtitles')
cmd = importlib.import_module('content.ffmpeg_cmd')


def comment(cid, article, created, type_='question', has_answer=False, text='Чи підійде?'):
    return {'id': cid, 'type': type_, 'created': created, 'read': False, 'has_answer': has_answer,
            'title': f'Питання {cid}', 'article': article, 'item_name': f'Товар {article}', 'text': text}


# ── теми ──────────────────────────────────────────────────────────────

def test_from_questions_filters_and_dedups():
    out = topics.from_questions([
        comment(1, 'A1', '2026-09-01 10:00:00'),
        comment(2, 'A1', '2026-09-10 10:00:00', text='Новіше питання'),
        comment(3, 'B2', '2026-09-05 10:00:00', has_answer=True),
        comment(4, 'C3', '2026-09-07 10:00:00', type_='comment'),
        comment(5, 'D4', '2026-09-09 10:00:00'),
    ])
    assert [t['article'] for t in out] == ['A1', 'D4']
    assert out[0]['kind'] == 'question' and out[0]['source'] == 'Новіше питання'
    assert out[0]['title'] == 'Товар A1'


def test_from_catalog_sorted_and_filtered():
    prods = [{'sku': 'S1', 'name': 'Перший', 'price': 100, 'sold': 5, 'available': True},
             {'sku': 'S2', 'name': 'Другий', 'price': 900, 'sold': 50, 'available': True},
             {'sku': 'S3', 'name': 'Нема', 'price': 900, 'sold': 99, 'available': False},
             {'sku': 'S4', 'name': 'Дешевий', 'price': 10, 'sold': 80, 'available': True}]
    out = topics.from_catalog(prods, min_price=50)
    assert [t['article'] for t in out] == ['S2', 'S1']
    assert out[0]['kind'] == 'product' and out[0]['title'] == 'Другий'


def test_merge_alternates_and_dedups():
    q = [{'kind': 'question', 'article': 'A1', 'title': 'q1'}, {'kind': 'question', 'article': 'B2', 'title': 'q2'}]
    p = [{'kind': 'product', 'article': 'B2', 'title': 'p1'}, {'kind': 'product', 'article': 'C3', 'title': 'p2'}]
    out = topics.merge(q, p, limit=3)
    assert [t['article'] for t in out] == ['A1', 'B2', 'C3']
    assert out[1]['kind'] == 'question'                      # перша поява виграє


# ── сценарій ──────────────────────────────────────────────────────────

FACTS = {"об'єм": '57 мл', 'основа': 'гібридна', 'бренд': 'Sensuva'}
TOPIC = {'kind': 'product', 'article': 'SO3270', 'title': 'Змазка Sensuva', 'source': ''}


def test_build_prompt_contains_topic_and_facts():
    p = script.build_prompt(TOPIC, FACTS)
    assert 'Змазка Sensuva' in p and 'JSON' in p
    for k, v in FACTS.items():
        assert k in p and v in p


def test_parse_script_ok_and_errors():
    good = '```json\n{"hook": "Гачок", "points": ["раз", "два", "три"], "cta": "Купуй"}\n```'
    s = script.parse_script(good)
    assert s['hook'] == 'Гачок' and s['points'] == ['раз', 'два', 'три'] and s['cta'] == 'Купуй'
    assert script.DISCLOSURE in s['disclosure']
    for bad in ['не json', '{"hook": "а"}', '{"hook":"а","points":"не список","cta":"c"}']:
        with pytest.raises(ValueError):
            script.parse_script(bad)


def ok_script(**over):
    s = {'hook': 'Гачок про змазку', 'points': ['гібридна основа', "об'єм 57 мл", 'бренд Sensuva'],
         'cta': 'Замовляй на Rozetka', 'disclosure': script.DISCLOSURE}
    s.update(over)
    return s


def test_check_script_accepts_good():
    assert script.check_script(ok_script(), FACTS) == []


@pytest.mark.parametrize('over,fragment', [
    ({'hook': 'г' * (script.MAX_HOOK + 1)}, 'гачок задовгий'),
    ({'points': ['п' * (script.MAX_POINT + 1), 'два', 'три']}, 'пункт задовгий'),
    ({'points': ['раз', 'два']}, 'мало пунктів'),
    ({'points': ['1', '2', '3', '4', '5', '6']}, 'забагато пунктів'),
    ({'points': ['лікує подразнення', 'два', 'три']}, 'заборонене твердження'),
    ({'points': ["об'єм 100 мл", 'два', 'три']}, 'число не з фактів'),
    ({'disclosure': ''}, 'нема позначки ШІ'),
    ({'cta': 'пишіть 0671234567'}, 'контакти у тексті'),
])
def test_check_script_finds_problems(over, fragment):
    problems = script.check_script(ok_script(**over), FACTS)
    assert any(fragment in p for p in problems), problems


def test_check_script_number_normalization():
    assert script.check_script(ok_script(points=['об’єм 57 мл', 'два', 'три']), {"об'єм": '57мл'}) == []
    assert script.check_script(ok_script(points=['вага 1,5 кг', 'два', 'три']), {'вага': '1.5 кг'}) == []


# ── субтитри ──────────────────────────────────────────────────────────

def test_split_lines():
    out = subs.split_lines('дуже довгий рядок тексту для субтитрів у вертикальному відео', width=20)
    assert all(len(l) <= 20 for l in out) and ' '.join(out).split() == \
        'дуже довгий рядок тексту для субтитрів у вертикальному відео'.split()
    assert subs.split_lines('супердовгеслововідеофрагмент', width=10) == ['супердовгеслововідеофрагмент']


def test_timings_and_srt():
    items = subs.timings(['короткий', 'а' * 60])
    assert items[0][0] == 0.0 and items[0][1] == pytest.approx(subs.MIN_SEC)
    assert items[1][0] == items[0][1] and items[1][1] - items[1][0] == pytest.approx(60 / subs.CPS)
    srt = subs.to_srt(items)
    lines = srt.splitlines()
    assert lines[0] == '1' and '-->' in lines[1] and lines[2] == 'короткий' and lines[3] == ''
    assert lines[1].startswith('00:00:00,000') and ',' in lines[1].split('--> ')[1]


# ── команда ffmpeg ────────────────────────────────────────────────────

def test_slideshow_command():
    c = cmd.slideshow(['/a.jpg', '/b.jpg'], [3.0, 4.0], '/out.mp4', srt='/s.srt')
    assert c[0] == 'ffmpeg' and c[-1] == '/out.mp4'
    assert c.count('-loop') == 2 and '/a.jpg' in c and '/b.jpg' in c
    joined = ' '.join(c)
    assert 'concat=n=2:v=1:a=0' in joined and 'subtitles=/s.srt' in joined
    assert '1080' in joined and '1920' in joined and 'libx264' in joined and 'yuv420p' in joined
    assert '-shortest' not in c                                  # без аудіо не треба


def test_slideshow_with_audio():
    c = cmd.slideshow(['/a.jpg'], [5.0], '/o.mp4', audio='/a.mp3')
    assert '/a.mp3' in c and '-shortest' in c


@pytest.mark.parametrize('images,durations', [
    ([], []), (['/a.jpg'], [1.0, 2.0]), (['/a.jpg'], [0]), (['/a.jpg'], [-1]),
    (['/a.jpg', '/b.jpg'], [40.0, 30.0]),
])
def test_slideshow_validation(images, durations):
    with pytest.raises(ValueError):
        cmd.slideshow(images, durations, '/o.mp4')


def test_total_duration():
    assert cmd.total_duration([1.5, 2.5]) == pytest.approx(4.0)
