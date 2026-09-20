"""Приймальні тести TASK-35: оцінка ролика до публікації.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib

import pytest

hs = importlib.import_module('content.hook_score')


def timings(spec):
    """[(тривалість, текст)] → [(початок, кінець, текст)]"""
    out, t = [], 0.0
    for dur, text in spec:
        out.append((t, t + dur, text))
        t += dur
    return out


GOOD = timings([
    (2.2, 'Три помилки при виборі ключа'),
    (7.0, 'Перша помилка це брати хром ванадій замість хром молібдену бо ударні головки '
          'з ванадію тріскають уже на другий місяць роботи'),
    (7.0, 'Друга помилка це купувати набір заради кейса а не заради самих ключів бо кейс '
          'ви викинете за тиждень а ключами працювати роками'),
    (7.0, 'Третя помилка це ігнорувати гарантію бо в Toptul вона довічна на ручний інструмент '
          'і це єдине що реально відрізняє його від дешевих копій'),
    (1.8, 'Замовляй на Rozetka'),
])                                                     # разом 25.0 с, 73 слова ≈ 2.9 слова/с


def video(**over):
    v = {'hook': 'Три помилки при виборі ключа', 'timings': GOOD,
         'shots': [{'duration': 2.5}, {'duration': 2.5}, {'duration': 10.0}, {'duration': 10.0}],
         'has_subtitles': True, 'supplier_text': 'Зовсім інший текст постачальника про набір'}
    v.update(over)
    return v


def check(result, cid):
    return next(c for c in result['checks'] if c['id'] == cid)


# ── дрібні функції ────────────────────────────────────────────────────

@pytest.mark.parametrize('text,n', [
    ('Три, два — один!', 3), ('  ', 0), ('одне', 1), ('19-в-1 набір', 2),
])
def test_words(text, n):
    assert hs.words(text) == n


def test_shingles_and_similarity():
    a = hs.shingles('один два три чотири пʼять')
    assert len(a) == 2 and 'один два три чотири' in a
    assert hs.shingles('мало слів') == {'мало слів'}
    assert hs.shingles('') == set()
    assert hs.similarity('один два три чотири', 'нуль один два три чотири пʼять') == 1.0
    assert hs.similarity('зовсім інший короткий текст тут', 'один два три чотири') == 0.0
    assert hs.similarity('', 'будь-що') == 0.0


def test_similarity_is_overlap_not_jaccard():
    ours = 'один два три чотири'
    theirs = ' '.join(['один два три чотири'] + [f'слово{i}' for i in range(50)])
    assert hs.similarity(ours, theirs) == 1.0          # Жаккар дав би майже нуль


# ── повна оцінка ──────────────────────────────────────────────────────

def test_good_video_scores_high():
    r = hs.score(video())
    assert r['max_score'] == 100 and sum(hs.WEIGHTS.values()) == 100
    assert r['score'] == 100 and r['verdict'] == 'публікувати' and r['losses'] == []
    assert [c['id'] for c in r['checks']] == list(hs.WEIGHTS)
    assert all(c['ok'] for c in r['checks'])


def test_hook_too_long():
    r = hs.score(video(timings=timings([(4.0, GOOD[0][2])] + [(d[1] - d[0], d[2]) for d in GOOD[1:]])))
    c = check(r, 'hook_time')
    assert c['ok'] is False and c['got'] == pytest.approx(4.0)
    assert 'скоротіть' in c['hint'] and r['score'] <= 100 - hs.WEIGHTS['hook_time']


def test_hook_without_specifics():
    r = hs.score(video(hook='Цей інструмент дуже гарний і надійний'))
    assert check(r, 'hook_specific')['ok'] is False
    assert check(r, 'no_greeting')['ok'] is True


def test_hook_specific_accepts_question_and_problem():
    assert hs.score(video(hook='Що не так із цим ключем?'))['checks'][1]['ok'] is True
    assert check(hs.score(video(hook='Яку помилку роблять усі')), 'hook_specific')['ok'] is True
    assert check(hs.score(video(hook='19-в-1 у кишені')), 'hook_specific')['ok'] is True


def test_greeting_detected():
    r = hs.score(video(hook='Привіт, сьогодні про ключі Toptul'))
    c = check(r, 'no_greeting')
    assert c['ok'] is False and c['got'] == 'привіт'


def test_length_windows():
    # 11 с — поза допустимим (0 балів); 17.5 с — поза цільовим, але в допустимому (пів ваги)
    short = timings([(2.0, 'Три помилки при виборі ключа'),
                     (8.0, ' '.join(['слово'] * 25)), (1.0, 'Замовляй зараз')])      # 11 с
    mid = timings([(2.0, 'Три помилки при виборі ключа'),
                   (14.0, ' '.join(['слово'] * 45)), (1.5, 'Замовляй зараз')])       # 17.5 с
    r_short, r_mid = hs.score(video(timings=short)), hs.score(video(timings=mid))
    assert check(r_short, 'length')['ok'] is False and check(r_mid, 'length')['ok'] is False
    assert check(r_short, 'pace')['ok'] is True and check(r_mid, 'pace')['ok'] is True
    assert r_mid['score'] - r_short['score'] == hs.WEIGHTS['length'] // 2


def test_pace():
    slow = timings([(2.0, 'Три помилки тут'), (20.0, 'одне два три чотири пʼять'),
                    (1.5, 'Замовляй')])                                    # 23.5 с, 9 слів
    c = check(hs.score(video(timings=slow)), 'pace')
    assert c['ok'] is False and c['got'] < hs.PACE[0]


def test_cuts():
    assert check(hs.score(video(shots=[{'duration': 25.0}])), 'cuts')['ok'] is False
    assert check(hs.score(video(shots=[])), 'cuts')['got'] == 0
    assert check(hs.score(video(shots=[{'duration': 3.0}, {'duration': 3.0}])), 'cuts')['ok'] is True


def test_subtitles_and_cta():
    assert check(hs.score(video(has_subtitles=False)), 'subtitles')['ok'] is False
    long_cta = timings([(d[1] - d[0], d[2]) for d in GOOD[:-1]] + [(5.0, 'Замовляй на Rozetka')])
    assert check(hs.score(video(timings=long_cta)), 'cta')['ok'] is False


def test_unique():
    ours = ' '.join(t[2] for t in GOOD)
    assert check(hs.score(video(supplier_text=ours)), 'unique')['ok'] is False
    assert check(hs.score(video(supplier_text='')), 'unique')['ok'] is True
    assert check(hs.score(video(supplier_text='')), 'unique')['got'] == 0.0


def test_verdicts_and_losses_order():
    bad = hs.score({'hook': 'Привіт друзі', 'timings': timings([(6.0, 'Привіт друзі')]),
                    'shots': [], 'has_subtitles': False, 'supplier_text': ''})
    assert bad['verdict'] == 'не публікувати'
    weights = [l['weight'] for l in bad['losses']]
    assert weights == sorted(weights, reverse=True)
    assert all('hint' in l and l['hint'] for l in bad['losses'])


def test_empty_timings():
    with pytest.raises(ValueError):
        hs.score(video(timings=[]))


# ── звіт ──────────────────────────────────────────────────────────────

def test_report_with_losses():
    r = hs.score(video(has_subtitles=False))
    lines = hs.report(r).splitlines()
    assert lines[0] == f"🎬 Оцінка ролика: {r['score']}/100 — {r['verdict']}"
    assert lines[1] == 'Втрати:'
    assert lines[2] == '• subtitles (−10): увімкніть субтитри'


def test_report_clean():
    lines = hs.report(hs.score(video())).splitlines()
    assert lines[1] == 'Втрат нема' and len(lines) == 2
