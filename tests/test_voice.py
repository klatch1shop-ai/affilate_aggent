"""Приймальні тести TASK-29. Написані замовником ДО виконання; виконавець їх не змінює."""
import importlib
import pytest

voice = importlib.import_module('content.voice')


def test_plan_lines():
    s = {'hook': ' Гачок ', 'points': ['раз', '', 'два'], 'cta': 'Замовляй', 'disclosure': 'x'}
    assert voice.plan_lines(s) == ['Гачок', 'раз', 'два', 'Замовляй']


class Synth:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def __call__(self, text, voice_code, rate, path):
        self.calls.append((text, voice_code, rate, path))
        if text == self.fail_on:
            raise RuntimeError('синтез упав')


def probe(path):
    return 2.0


def test_synthesize_ok():
    s = Synth()
    out = voice.synthesize(['раз', 'два'], s, probe, voice='female', out_dir='/tmp/x')
    assert [o['duration'] for o in out] == [2.0 + voice.PAUSE] * 2
    assert s.calls[0][1] == voice.VOICES['female'] and s.calls[0][2] == '+8%'
    assert out[0]['path'] != out[1]['path'] and out[0]['path'].startswith('/tmp/x')


def test_synthesize_bad_voice_and_empty():
    with pytest.raises(ValueError):
        voice.synthesize(['раз'], Synth(), probe, voice='нема')
    assert voice.synthesize([], Synth(), probe) == []
    assert voice.synthesize(['раз'], Synth(), probe, voice='uk-UA-PolinaNeural')[0]['duration'] > 0


def test_synthesize_survives_one_failure():
    out = voice.synthesize(['раз', 'два'], Synth(fail_on='раз'), probe)
    assert out[0]['path'] is None and out[0]['duration'] == 0.0 and 'RuntimeError' in out[0]['error']
    assert out[1]['duration'] == 2.0 + voice.PAUSE


def test_align_skips_failed():
    segs = [{'text': 'a', 'path': None, 'duration': 0.0}, {'text': 'b', 'path': '/b.mp3', 'duration': 2.0},
            {'text': 'c', 'path': '/c.mp3', 'duration': 3.0}]
    assert voice.align(segs) == [(0.0, 2.0, 'b'), (2.0, 5.0, 'c')]


def test_concat_list_escapes():
    text = voice.concat_list(['/a.mp3', "/it's/b.mp3"])
    assert text.splitlines()[0] == "file '/a.mp3'" and "'\\''" in text.splitlines()[1]
