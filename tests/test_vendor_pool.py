"""Пул вендорів, 26.09.2026. Головне, що стережуть ці тести: один вендор НЕ
може підтвердити сам себе. Саме ця дірка знецінила 94% попереднього прогону
атрибутів Епіцентру (196 із 218 «ЗБІГів» — модель погодилась сама з собою).
"""
import os

import pytest

from shared.utils import vendor_pool as vp


# ── вердикт ───────────────────────────────────────────────────────────

def test_same_vendor_never_counts_as_agreement():
    """Навіть при однакових відповідях: той самий вендор — не перевірка."""
    assert vp.verdict('Гель', 'Гель', 'codex', 'codex') == vp.UNVERIFIED
    assert vp.verdict('Гель', 'Гель', 'gemini', 'gemini') == vp.UNVERIFIED


def test_different_vendors_agreeing_is_real_agreement():
    assert vp.verdict('Гель', 'Гель', 'openrouter', 'codex') == vp.AGREE
    # регістр і пробіли не мають робити з збігу розбіжність
    assert vp.verdict(' гель ', 'Гель', 'openrouter', 'gemini') == vp.AGREE


def test_different_vendors_disagreeing():
    assert vp.verdict('Гель', 'Крем', 'openrouter', 'codex') == vp.DISAGREE


def test_both_unknown_is_its_own_verdict():
    assert vp.verdict('НЕ ВИДНО', 'НЕ ВКАЗАНО', 'openrouter', 'codex') == vp.BOTH_UNKNOWN
    # і навіть у того самого вендора — це радше «не знає», ніж «не перевірено»
    assert vp.verdict('НЕ ВИДНО', 'НЕ ВИДНО', 'codex', 'codex') == vp.BOTH_UNKNOWN


def test_missing_answer_is_failure():
    assert vp.verdict(None, 'Гель', 'openrouter', 'codex') == vp.FAILED
    assert vp.verdict('Гель', '', 'openrouter', 'codex') == vp.FAILED


# ── добір двох різних ─────────────────────────────────────────────────

def test_pick_two_returns_different_vendors():
    first, second = vp.pick_two(['openrouter', 'codex', 'groq'])
    assert first != second and first is not None and second is not None


def test_pick_two_first_must_see_photos():
    first, _ = vp.pick_two(['groq', 'cerebras', 'openrouter'])
    assert first in vp.VISION


def test_pick_two_single_vendor_admits_it_honestly():
    """Один живий вендор — чесне (вендор, None), а не вигаданий другий голос."""
    assert vp.pick_two(['codex']) == ('codex', None)


def test_pick_two_no_vision_vendor_alive():
    assert vp.pick_two(['groq', 'cerebras']) == (None, None)


# ── виклик ────────────────────────────────────────────────────────────

def fake_callers(**behaviour):
    def make(name):
        def fn(prompt, image_url=None, image_bytes=None, image_mime=None,
               timeout=180, max_tokens=300):
            result = behaviour.get(name, f'відповідь {name}')
            if isinstance(result, Exception):
                raise result
            return result
        return fn
    return {n: make(n) for n in ('openrouter', 'gemini', 'codex', 'groq', 'cerebras')}


def test_call_rejects_photo_for_text_only_vendor():
    with pytest.raises(ValueError, match='фото'):
        vp.call('groq', 'що на фото?', image_url='https://x/y.jpg',
                callers=fake_callers())


def test_call_unknown_vendor():
    with pytest.raises(ValueError, match='невідомий вендор'):
        vp.call('вигаданий', 'привіт', callers=fake_callers())


def test_first_ok_skips_broken_and_reports_why():
    callers = fake_callers(openrouter=RuntimeError('429'), gemini='Гель')
    stats = vp.Stats()
    text, vendor, errors = vp.first_ok(['openrouter', 'gemini'], 'питання',
                                       stats=stats, callers=callers)
    assert text == 'Гель' and vendor == 'gemini'
    # не лише тип: «RuntimeError» однаково виглядає для вичерпаної квоти
    # й порожньої відповіді, тому причина має бути в тексті
    assert errors[0].startswith('openrouter:RuntimeError')
    assert '429' in errors[0]
    assert stats.summary()['openrouter']['збоїв'] == 1
    assert stats.summary()['gemini']['відповів'] == 1


def test_first_ok_all_down_returns_nothing_not_garbage():
    callers = fake_callers(openrouter=RuntimeError('429'), gemini=RuntimeError('429'))
    text, vendor, errors = vp.first_ok(['openrouter', 'gemini'], 'питання', callers=callers)
    assert text is None and vendor is None
    assert len(errors) == 2


def test_stats_summary_counts_and_median():
    stats = vp.Stats()
    stats.record('openrouter', True, 100)
    stats.record('openrouter', True, 300)
    stats.record('openrouter', False)
    summary = stats.summary()['openrouter']
    assert summary['відповів'] == 2 and summary['збоїв'] == 1
    assert summary['медіана_мс'] == 300


def test_one_side_unknown_is_not_disagreement():
    """26.09 живий тест: OpenRouter читає фото («2»), а Gemini і Codex кажуть
    НЕ ВИДНО. Це не суперечність — це одне джерело знає, друге ні."""
    assert vp.verdict('2', 'НЕ ВКАЗАНО', 'openrouter', 'gemini') == vp.ONLY_ONE_KNOWS
    assert vp.verdict('НЕ ВИДНО', 'Гель', 'openrouter', 'codex') == vp.ONLY_ONE_KNOWS


def test_one_side_unknown_same_vendor_still_only_one_knows():
    assert vp.verdict('2', 'НЕ ВКАЗАНО', 'codex', 'codex') == vp.ONLY_ONE_KNOWS


def test_vendors_that_need_bytes_actually_receive_the_image(monkeypatch):
    """ЗНАЙДЕНО 26.09: gemini приймає лише image_bytes, codex — лише файл, і
    обидва мовчки ігнорували image_url. Вони відповідали «НЕ ВИДНО» на фото,
    якого не бачили, а я записав це в їхню непридатність.

    Підміна саме атрибута пакета: `from shared.utils import llm_router` бере
    атрибут з `shared.utils`, а не з `sys.modules`, тож підміна в sys.modules
    не діяла — і тест ходив у справжню мережу.
    """
    import shared.utils as pkg

    monkeypatch.setattr(vp, '_fetch', lambda url, **k: (b'jpeg-bytes', 'image/jpeg'))
    seen = {}

    class FakeRouter:
        @staticmethod
        def call_gemini(prompt, timeout=None, max_tokens=None, image_bytes=None, image_mime=None):
            seen['gemini_bytes'] = image_bytes
            return 'ok', 'model', None

        @staticmethod
        def call_codex(prompt, image_path=None, timeout=None):
            seen['codex_path'] = image_path
            seen['codex_file_existed'] = bool(image_path) and os.path.exists(image_path)
            return 'ok', 'codex-exec'

        @staticmethod
        def call_openrouter(prompt, **kw):
            return 'ok', 'm'

        call_groq = call_cerebras = call_openrouter

    monkeypatch.setattr(pkg, 'llm_router', FakeRouter, raising=False)

    vp.call('gemini', 'що на фото?', image_url='https://cdn/x.jpg')
    assert seen['gemini_bytes'] == b'jpeg-bytes'

    vp.call('codex', 'що на фото?', image_url='https://cdn/x.jpg')
    assert seen['codex_path'].endswith('.jpg')
    assert seen['codex_file_existed']                     # файл існував НА МОМЕНТ виклику
    assert not os.path.exists(seen['codex_path'])         # і прибрано після
