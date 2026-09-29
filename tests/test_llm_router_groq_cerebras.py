"""Groq/Cerebras/OpenRouter — паралельний до Gemini канал, тест 26.09.2026:
живий прогін показав, що безкоштовний Gemini дає лише ~20 запитів/добу
на модель, а gpt-oss/nemotron на цих провайдерах — reasoning-моделі, де
`reasoning`-токени зʼїдають малий max_tokens раніше за відповідь.

НЕ в CHAIN за замовчуванням — той самий принцип, що й Codex.
"""
import importlib

import pytest

router = importlib.import_module('shared.utils.llm_router')


class FakeResp:
    def __init__(self, status=200, content='', model='m', text=''):
        self.status_code, self.text = status, text or content
        self._content, self._model = content, model

    def json(self):
        return {'choices': [{'message': {'content': self._content}}], 'model': self._model}


@pytest.mark.parametrize('fn,key_env,url_part', [
    (router.call_groq, 'GROQ_API_KEY', 'groq.com'),
    (router.call_cerebras, 'CEREBRAS_API_KEY', 'cerebras.ai'),
    (router.call_openrouter, 'OPENROUTER_API_KEY', 'openrouter.ai'),
])
def test_call_ok(monkeypatch, fn, key_env, url_part):
    monkeypatch.setenv(key_env, 'test-key')
    seen = {}

    def fake_post(url, timeout=None, headers=None, json=None):
        seen['url'], seen['headers'], seen['body'] = url, headers, json
        return FakeResp(content='чотири', model='oss-120b')

    monkeypatch.setattr(router.requests, 'post', fake_post)
    text, model = fn('скільки буде 2+2?')
    assert text == 'чотири' and model == 'oss-120b'
    assert url_part in seen['url']
    assert seen['headers']['Authorization'] == 'Bearer test-key'


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    with pytest.raises(RuntimeError, match='GROQ_API_KEY'):
        router.call_groq('питання')


def test_small_max_tokens_bumped_to_minimum(monkeypatch):
    """Знайдено 26.09: reasoning зʼїдає max_tokens=30 цілком, content порожній."""
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    seen = {}

    def fake_post(url, timeout=None, headers=None, json=None):
        seen['body'] = json
        return FakeResp(content='чотири')

    monkeypatch.setattr(router.requests, 'post', fake_post)
    router.call_groq('питання', max_tokens=30)
    assert seen['body']['max_tokens'] == 200


def test_empty_content_raises(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    monkeypatch.setattr(router.requests, 'post',
                        lambda *a, **k: FakeResp(content=''))
    with pytest.raises(RuntimeError, match='порожня відповідь'):
        router.call_groq('питання')


def test_http_error_raises(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    monkeypatch.setattr(router.requests, 'post',
                        lambda *a, **k: FakeResp(status=429, text='rate limited'))
    with pytest.raises(RuntimeError, match='HTTP 429'):
        router.call_groq('питання')


def test_ask_routes_to_groq_when_in_chain(monkeypatch, tmp_path):
    monkeypatch.setattr(router, 'call_groq', lambda *a, **k: ('відповідь groq', 'oss-120b'))
    monkeypatch.setattr(router, '_down', {})
    monkeypatch.setattr(router, 'LOG', str(tmp_path / 'log.jsonl'))
    out = router.ask('питання', chain=['groq'], min_len=1)
    assert out['channel'] == 'groq' and out['text'] == 'відповідь groq'


def test_ask_not_in_default_chain():
    assert 'groq' not in router.CHAIN
    assert 'cerebras' not in router.CHAIN
    assert 'openrouter' not in router.CHAIN
