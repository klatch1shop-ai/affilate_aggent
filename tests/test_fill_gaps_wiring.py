"""Регресія 21.09 і 25.09.2026 навколо scratchpad/fill_gaps_all.py.

21.09: ask_photo/ask_text викликали gemini() без escalation_prompt — при падінні
Gemini повертали 'HTTP429' замість реальної ескалації на Codex.

25.09: gemini() хардкодив ОДНУ модель Gemini напряму замість повного ланцюжка
`call_gemini` (4 моделі, 4 окремі добові квоти) — вичерпував квоту вчетверо
швидше й ішов в ескалацію на Codex там, де досить було наступної моделі.
Перевірено: прогін на 1790 картках упирався в переривник щоразу, коли одна
модель і бюджет ескалацій вичерпувались одночасно.

Тест перевіряє САМЕ ці зʼєднання, а не самі call_gemini/call_codex
(вони в test_llm_router_codex.py).
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
    """Модуль із call_gemini, що завжди падає — щоб перевірити шлях ескалації."""
    m = _load_module()

    def fail(*a, **k):
        raise RuntimeError('Gemini: усі моделі вичерпано')

    monkeypatch.setattr(m, 'call_gemini', fail)
    return m


def test_gemini_tries_full_chain_before_codex(monkeypatch):
    """call_gemini (ланцюжок 4 моделей), а не одна модель напряму."""
    m = _load_module()
    seen = {}

    def fake_call_gemini(prompt, **k):
        seen['called'] = True
        seen['image_bytes'] = k.get('image_bytes')
        return 'чорний', 'gemini-3-flash-preview', {'total': 10}

    monkeypatch.setattr(m, 'call_gemini', fake_call_gemini)
    (text, tokens, src), q = m.ask_photo(b'fake', 'image/jpeg', 'Колір')
    assert seen['called'] is True and seen['image_bytes'] == b'fake'
    assert src == 'gemini' and text == 'чорний'


def test_ask_photo_escalates_when_whole_chain_down(mod, monkeypatch):
    monkeypatch.setattr(mod, 'call_codex', lambda prompt, **k: ('чорний', 'codex-exec'))
    (text, tokens, src), q = mod.ask_photo(b'fake-bytes', 'image/jpeg', 'Колір')
    assert src == 'codex' and text == 'чорний'
    assert 'Колір' in q


def test_ask_text_escalates_when_whole_chain_down(mod, monkeypatch):
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
