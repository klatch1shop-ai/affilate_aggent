"""Тести самоперевірки та інструкції для ручного тесту."""
import importlib

sc = importlib.import_module('helper.selfcheck')
tp = importlib.import_module('helper.testplan')


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.25
        return self.t


def test_run_checks_survives_failure():
    checks = [('перша', lambda: 'усе добре'),
              ('друга', lambda: (_ for _ in ()).throw(ValueError('зламалось'))),
              ('третя', lambda: 42)]
    out = sc.run_checks(checks, clock=Clock())
    assert [r['name'] for r in out] == ['перша', 'друга', 'третя']
    assert [r['ok'] for r in out] == [True, False, True]
    assert out[1]['detail'] == 'ValueError: зламалось'
    assert out[2]['detail'] == '42' and out[0]['ms'] == 250


def test_render_counts_and_masks():
    out = sc.run_checks([('чат', lambda: 'покупець 0671234567'),
                         ('збій', lambda: 1 / 0)], clock=Clock())
    text = sc.render(out)
    assert text.splitlines()[0] == '🔬 Самоперевірка: 1/2 пройшло'
    assert '0671234567' not in text and '[телефон приховано]' in text
    assert text.splitlines()[-1] == 'Не пройшли: збій'


def test_render_truncates_and_flattens():
    out = sc.run_checks([('довга', lambda: 'я' * 500 + '\nдругий рядок')], clock=Clock())
    text = sc.render(out, limit=50)
    assert 'я' * 50 + '…' in text and '\n' not in text.split('· ', 2)[2]
    assert sc.render([]) == 'Нема перевірок'


def test_render_all_ok_has_no_failed_line():
    text = sc.render(sc.run_checks([('одна', lambda: 'ok')], clock=Clock()))
    assert 'Не пройшли' not in text and text.splitlines()[0].endswith('1/1 пройшло')


def test_test_text_lists_every_step():
    text = tp.test_text()
    for i, (what, expect) in enumerate(tp.STEPS, 1):
        assert f'{i}. `{what}`' in text and expect in text
    assert len({w for w, _ in tp.STEPS}) == len(tp.STEPS)
    for note in tp.NOTES:
        assert note in text
