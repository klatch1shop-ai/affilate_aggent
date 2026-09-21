"""Регресія 21.09.2026: ask_photo/ask_text у scratchpad/fill_gaps_all.py викликали
gemini() без escalation_prompt — при падінні Gemini повертали 'HTTP429' замість
реальної ескалації на Codex, і батч-прогін зупинявся переривником одразу
(перевірено: 39 підряд «помилок запиту» після вичерпання добового ліміту Gemini).

Тест перевіряє САМЕ це зʼєднання — що ask_photo/ask_text передають escalation_prompt
у gemini(), а не повторює тести самого call_codex (вони в test_llm_router_codex.py).
"""
import importlib.util
import os
import sys

import pytest

BASE = os.path.expanduser('~/agent-system')
sys.path.insert(0, BASE)


def _load_module():
    """Завантажити scratchpad/fill_gaps_all.py без запуску його головного циклу
    (той одразу читає gaps_enrich.json і починає мережеві виклики)."""
    path = os.path.join(BASE, 'scratchpad', 'fill_gaps_all.py')
    src = open(path, encoding='utf-8').read()
    cut = src.index('gaps = json.load')
    src = src[:cut]
    src = src.replace('SP = os.path.dirname(os.path.abspath(__file__))', "SP = 'scratchpad'")
    mod = importlib.util.module_from_spec(
        importlib.util.spec_from_loader('fill_gaps_all_head', loader=None))
    mod.__file__ = path
    exec(compile(src, path, 'exec'), mod.__dict__)
    return mod


@pytest.fixture
def mod(monkeypatch):
    m = _load_module()

    class Fake429:
        status_code = 429
        text = 'PerDay quota exceeded'

    monkeypatch.setattr(m.requests, 'post', lambda *a, **k: Fake429())
    return m


def test_ask_photo_escalates_when_gemini_down(mod, monkeypatch):
    monkeypatch.setattr(mod, 'call_codex', lambda prompt, **k: ('чорний', 'codex-exec'))
    (text, tokens, src), q = mod.ask_photo(b'fake-bytes', 'image/jpeg', 'Колір')
    assert src == 'codex' and text == 'чорний'
    assert 'Колір' in q


def test_ask_text_escalates_when_gemini_down(mod, monkeypatch):
    monkeypatch.setattr(mod, 'call_codex', lambda prompt, **k: ('силікон', 'codex-exec'))
    (text, tokens, src), q = mod.ask_text('опис товару', 'назва товару', 'Матеріал')
    assert src == 'codex' and text == 'силікон'


def test_ask_photo_passes_image_bytes_to_codex(mod, monkeypatch):
    seen = {}

    def fake_codex(prompt, image_path=None, **k):
        seen['has_image'] = image_path is not None
        return 'ok', 'codex-exec'

    monkeypatch.setattr(mod, 'call_codex', fake_codex)
    mod.ask_photo(b'fake-bytes', 'image/jpeg', 'Колір')
    assert seen['has_image'] is True


def test_ask_photo_and_text_still_return_gemini_result_when_it_works(monkeypatch):
    m = _load_module()

    class FakeOK:
        status_code = 200

        def json(self):
            return {'candidates': [{'content': {'parts': [{'text': 'білий'}]}}],
                    'usageMetadata': {'totalTokenCount': 12}}

    monkeypatch.setattr(m.requests, 'post', lambda *a, **k: FakeOK())
    (text, tokens, src), q = m.ask_photo(b'fake', 'image/jpeg', 'Колір')
    assert src == 'gemini' and text == 'білий' and tokens == 12
