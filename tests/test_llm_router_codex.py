"""Ескалація до Codex, коли Gemini впав (429/PerDay і подібне) — рішення власника 21.09.2026.

Codex НЕ в CHAIN за замовчуванням: платний/обмежений ресурс, ескалація лише свідома
(параметр `escalate_to_codex=True`), щоб фонова автоматика не палила квоту непомітно.
"""
import importlib
import subprocess

import pytest

router = importlib.import_module('shared.utils.llm_router')


class FakeRun:
    def __init__(self, returncode=0, stderr='', write_text=None):
        self.returncode, self.stderr, self._write = returncode, stderr, write_text
        self.calls = []

    def __call__(self, cmd, capture_output=None, text=None, timeout=None):
        self.calls.append(cmd)
        out_idx = cmd.index('-o') + 1
        path = cmd[out_idx]
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self._write or '')
        return subprocess.CompletedProcess(cmd, self.returncode, stdout='', stderr=self.stderr)


def test_call_codex_text_only(monkeypatch):
    fake = FakeRun(write_text='Київ')
    monkeypatch.setattr(router.subprocess, 'run', fake)
    text, model = router.call_codex('яка столиця України?')
    assert text == 'Київ' and model == 'codex-exec'
    cmd = fake.calls[0]
    assert cmd[:2] == ['codex', 'exec'] and 'яка столиця України?' in cmd
    assert '--sandbox' in cmd and 'read-only' in cmd
    assert '--ephemeral' in cmd and '--skip-git-repo-check' in cmd
    assert '-i' not in cmd


def test_call_codex_with_image(monkeypatch):
    fake = FakeRun(write_text='Фіолетовий')
    monkeypatch.setattr(router.subprocess, 'run', fake)
    text, model = router.call_codex('який колір?', image_path='/tmp/x.jpg')
    assert text == 'Фіолетовий'
    cmd = fake.calls[0]
    assert '-i' in cmd and cmd[cmd.index('-i') + 1] == '/tmp/x.jpg'


def test_call_codex_nonzero_exit_raises(monkeypatch):
    fake = FakeRun(returncode=1, stderr='rate limit exceeded', write_text='')
    monkeypatch.setattr(router.subprocess, 'run', fake)
    with pytest.raises(RuntimeError) as e:
        router.call_codex('питання')
    assert 'rate limit' in str(e.value) or '1' in str(e.value)


def test_call_codex_empty_output_raises(monkeypatch):
    fake = FakeRun(write_text='   ')
    monkeypatch.setattr(router.subprocess, 'run', fake)
    with pytest.raises(RuntimeError):
        router.call_codex('питання')


def test_call_codex_timeout_propagates(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd='codex', timeout=180)
    monkeypatch.setattr(router.subprocess, 'run', boom)
    with pytest.raises(subprocess.TimeoutExpired):
        router.call_codex('питання', timeout=180)


# ── ask() ескалує лише коли явно попросили ─────────────────────────────

def test_ask_does_not_escalate_by_default(monkeypatch):
    def fail(*a, **k):
        raise RuntimeError('Gemini HTTP 429')
    monkeypatch.setattr(router, 'call_gemini', fail)
    monkeypatch.setattr(router, 'call_ollama', fail)
    monkeypatch.setattr(router, 'CHAIN', ['gemini', 'ollama'])
    monkeypatch.setattr(router, '_down', {})
    called = []
    monkeypatch.setattr(router, 'call_codex', lambda *a, **k: called.append(1) or ('x', 'codex-exec'))
    with pytest.raises(RuntimeError):
        router.ask('питання', min_len=1)
    assert called == []


def test_ask_escalates_to_codex_when_asked(monkeypatch, tmp_path):
    def fail(*a, **k):
        raise RuntimeError('Gemini HTTP 429 …PerDay…')
    monkeypatch.setattr(router, 'call_gemini', fail)
    monkeypatch.setattr(router, 'CHAIN', ['gemini'])
    monkeypatch.setattr(router, '_down', {})
    monkeypatch.setattr(router, 'LOG', str(tmp_path / 'log.jsonl'))
    monkeypatch.setattr(router, 'call_codex', lambda prompt, **k: ('відповідь codex', 'codex-exec'))
    out = router.ask('питання', min_len=1, escalate_to_codex=True)
    assert out['text'] == 'відповідь codex' and out['channel'] == 'codex'
    assert out['model'] == 'codex-exec'


def test_ask_escalation_passes_image(monkeypatch):
    def fail(*a, **k):
        raise RuntimeError('Gemini HTTP 429')
    monkeypatch.setattr(router, 'call_gemini', fail)
    monkeypatch.setattr(router, 'CHAIN', ['gemini'])
    monkeypatch.setattr(router, '_down', {})
    seen = {}
    def fake_codex(prompt, image_path=None, **k):
        seen['image_path'] = image_path
        return 'ok', 'codex-exec'
    monkeypatch.setattr(router, 'call_codex', fake_codex)
    router.ask('питання', min_len=1, escalate_to_codex=True, image_path='/tmp/photo.jpg')
    assert seen['image_path'] == '/tmp/photo.jpg'


def test_ask_escalation_only_after_chain_exhausted(monkeypatch, tmp_path):
    monkeypatch.setattr(router, 'call_gemini', lambda *a, **k: ('добре', 'gemini-flash-lite-latest', None))
    monkeypatch.setattr(router, 'CHAIN', ['gemini'])
    monkeypatch.setattr(router, '_down', {})
    monkeypatch.setattr(router, 'LOG', str(tmp_path / 'log.jsonl'))
    called = []
    monkeypatch.setattr(router, 'call_codex', lambda *a, **k: called.append(1) or ('x', 'codex-exec'))
    out = router.ask('питання', min_len=1, escalate_to_codex=True)
    assert out['channel'] == 'gemini' and called == []


def test_usage_limit_raises_specific_error(monkeypatch):
    err = 'OpenAI Codex v0.155\nuser\nхай\nERROR: You’ve hit your usage limit. try again at Sep 22nd'
    monkeypatch.setattr(router.subprocess, 'run', FakeRun(returncode=1, stderr=err, write_text=''))
    with pytest.raises(router.CodexLimitError) as e:
        router.call_codex('питання')
    assert 'usage limit' in str(e.value)


def test_other_failure_keeps_stderr_tail_not_banner(monkeypatch):
    err = 'BANNER ' * 100 + '\nсправжня причина збою'
    monkeypatch.setattr(router.subprocess, 'run', FakeRun(returncode=1, stderr=err, write_text=''))
    with pytest.raises(RuntimeError) as e:
        router.call_codex('питання')
    assert 'справжня причина' in str(e.value)


# ── call_gemini підтримує фото (аудит 25.09: пілот хардкодив одну модель) ──

class FakeGeminiResp:
    def __init__(self, status=200, text='', candidates=None, usage=None):
        self.status_code, self.text = status, text
        self._c, self._u = candidates, usage

    def json(self):
        body = {}
        if self._c is not None:
            body['candidates'] = self._c
        if self._u is not None:
            body['usageMetadata'] = self._u
        return body


def test_call_gemini_accepts_image(monkeypatch):
    seen = {}

    def fake_post(url, timeout=None, headers=None, json=None):
        seen['body'] = json
        return FakeGeminiResp(200, candidates=[{'content': {'parts': [{'text': 'чорний'}]}}])

    monkeypatch.setattr(router.requests, 'post', fake_post)
    monkeypatch.setenv('GEMINI_API_KEY', 'test')
    text, model, tokens = router.call_gemini('який колір?', model='gemini-flash-lite-latest',
                                             image_bytes=b'fake-jpeg-bytes', image_mime='image/jpeg')
    assert text == 'чорний'
    parts = seen['body']['contents'][0]['parts']
    assert parts[0] == {'text': 'який колір?'}
    assert parts[1]['inlineData']['mimeType'] == 'image/jpeg'
    import base64
    assert base64.b64decode(parts[1]['inlineData']['data']) == b'fake-jpeg-bytes'


def test_call_gemini_without_image_unchanged(monkeypatch):
    seen = {}

    def fake_post(url, timeout=None, headers=None, json=None):
        seen['body'] = json
        return FakeGeminiResp(200, candidates=[{'content': {'parts': [{'text': 'ok'}]}}])

    monkeypatch.setattr(router.requests, 'post', fake_post)
    monkeypatch.setenv('GEMINI_API_KEY', 'test')
    router.call_gemini('текст', model='gemini-flash-lite-latest')
    assert seen['body']['contents'][0]['parts'] == [{'text': 'текст'}]


def test_call_gemini_falls_through_model_chain_with_image(monkeypatch):
    calls = []

    def fake_post(url, timeout=None, headers=None, json=None):
        calls.append(url)
        if len(calls) == 1:
            return FakeGeminiResp(429, text='…PerDay…')
        return FakeGeminiResp(200, candidates=[{'content': {'parts': [{'text': 'прозорий'}]}}])

    monkeypatch.setattr(router.requests, 'post', fake_post)
    monkeypatch.setenv('GEMINI_API_KEY', 'test')
    monkeypatch.setattr(router, '_gemini_day_out', {})
    text, model, tokens = router.call_gemini('колір?', image_bytes=b'x', image_mime='image/jpeg')
    assert text == 'прозорий' and len(calls) == 2
