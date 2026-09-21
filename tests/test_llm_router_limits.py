"""Ліміт виходу має доходити до Ollama, а не мовчки зникати.

Знайдено аудитом TASK-36: `call_ollama` приймав `max_tokens` і не передавав його
в API — параметр був порожньою обіцянкою.
"""
import importlib
import sys
import types

router = importlib.import_module('shared.utils.llm_router')


class FakePost:
    def __init__(self, text='відповідь'):
        self.calls, self.text = [], text

    def __call__(self, url, json=None, timeout=None):
        self.calls.append({'url': url, 'json': json, 'timeout': timeout})
        return types.SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {'response': self.text},
            status_code=200, text='')


def test_max_tokens_reaches_ollama(monkeypatch):
    fake = FakePost()
    monkeypatch.setattr(router.requests, 'post', fake)
    router.call_ollama('питання', model='llama3.2:3b', max_tokens=256)
    body = fake.calls[0]['json']
    assert body['options']['num_predict'] == 256
    assert body['model'] == 'llama3.2:3b' and body['stream'] is False


def test_without_max_tokens_no_options(monkeypatch):
    fake = FakePost()
    monkeypatch.setattr(router.requests, 'post', fake)
    router.call_ollama('питання', model='llama3.2:3b')
    assert 'options' not in fake.calls[0]['json']


def test_empty_answer_still_raises(monkeypatch):
    fake = FakePost(text='   ')
    monkeypatch.setattr(router.requests, 'post', fake)
    try:
        router.call_ollama('питання', model='llama3.2:3b', max_tokens=10)
    except RuntimeError as e:
        assert 'порожня' in str(e)
    else:
        raise AssertionError('мала бути RuntimeError')


# ── облік справжніх токенів (аудит TASK-36, п. 2) ─────────────────────

class FakeGemini:
    """Відповідь Gemini з usageMetadata, як її віддає API."""

    def __init__(self, usage=None, status=200):
        self.status_code, self._usage, self.text = status, usage, ''

    def json(self):
        body = {'candidates': [{'content': {'parts': [{'text': 'готово'}]}}]}
        if self._usage is not None:
            body['usageMetadata'] = self._usage
        return body


def test_gemini_returns_usage(monkeypatch):
    usage = {'promptTokenCount': 120, 'candidatesTokenCount': 45, 'totalTokenCount': 165}
    monkeypatch.setattr(router.requests, 'post', lambda *a, **k: FakeGemini(usage))
    monkeypatch.setenv('GEMINI_API_KEY', 'test')
    text, model, got = router.call_gemini('питання', model='gemini-flash-lite-latest')
    assert text == 'готово' and model == 'gemini-flash-lite-latest'
    assert got == {'in': 120, 'out': 45, 'total': 165}


def test_gemini_without_usage_gives_none(monkeypatch):
    monkeypatch.setattr(router.requests, 'post', lambda *a, **k: FakeGemini(None))
    monkeypatch.setenv('GEMINI_API_KEY', 'test')
    assert router.call_gemini('питання', model='gemini-flash-lite-latest')[2] is None


def test_ask_writes_usage_to_log(monkeypatch, tmp_path):
    usage = {'promptTokenCount': 10, 'candidatesTokenCount': 3, 'totalTokenCount': 13}
    monkeypatch.setattr(router.requests, 'post', lambda *a, **k: FakeGemini(usage))
    monkeypatch.setenv('GEMINI_API_KEY', 'test')
    monkeypatch.setattr(router, 'LOG', str(tmp_path / 'log.jsonl'))
    monkeypatch.setattr(router, 'CHAIN', ['gemini'])
    monkeypatch.setattr(router, '_down', {})
    out = router.ask('питання', min_len=1)
    assert out['text'] == 'готово' and out['tokens'] == {'in': 10, 'out': 3, 'total': 13}
    import json as _json
    rec = _json.loads((tmp_path / 'log.jsonl').read_text(encoding='utf-8').splitlines()[-1])
    assert rec['tokens_in'] == 10 and rec['tokens_out'] == 3 and rec['tokens_total'] == 13
