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
