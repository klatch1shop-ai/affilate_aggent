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


def test_image_url_goes_as_openai_content_list(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    seen = {}

    def fake_post(url, timeout=None, headers=None, json=None):
        seen['body'] = json
        return FakeResp(content='чашки, 2 шт')

    monkeypatch.setattr(router.requests, 'post', fake_post)
    router.call_openrouter('що на фото?', image_url='https://cdn/x.jpeg')
    content = seen['body']['messages'][0]['content']
    assert content[0] == {'type': 'text', 'text': 'що на фото?'}
    assert content[1]['image_url']['url'] == 'https://cdn/x.jpeg'


def test_image_bytes_become_data_uri(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    seen = {}

    def fake_post(url, timeout=None, headers=None, json=None):
        seen['body'] = json
        return FakeResp(content='ok')

    monkeypatch.setattr(router.requests, 'post', fake_post)
    router.call_openrouter('колір?', image_bytes=b'jpeg-bytes', image_mime='image/jpeg')
    url = seen['body']['messages'][0]['content'][1]['image_url']['url']
    assert url.startswith('data:image/jpeg;base64,')
    import base64
    assert base64.b64decode(url.split(',', 1)[1]) == b'jpeg-bytes'


def test_url_wins_over_bytes_to_avoid_needless_base64(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    seen = {}
    monkeypatch.setattr(router.requests, 'post',
                        lambda url, timeout=None, headers=None, json=None:
                        (seen.update(body=json), FakeResp(content='ok'))[1])
    router.call_openrouter('?', image_url='https://cdn/x.jpeg', image_bytes=b'ignored')
    assert seen['body']['messages'][0]['content'][1]['image_url']['url'] == 'https://cdn/x.jpeg'


def test_no_image_keeps_plain_string_content(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    seen = {}
    monkeypatch.setattr(router.requests, 'post',
                        lambda url, timeout=None, headers=None, json=None:
                        (seen.update(body=json), FakeResp(content='ok'))[1])
    router.call_groq('звичайний текст')
    assert seen['body']['messages'][0]['content'] == 'звичайний текст'


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


def test_photo_request_switches_to_vision_model(monkeypatch):
    """26.09: живий прогін дав HTTP 404 «No endpoints found» — текстова модель
    за замовчуванням просто не приймає зображень. Модель має залежати від того,
    чи є фото, інакше збій виглядає як проблема ключа."""
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    seen = {}
    monkeypatch.setattr(router.requests, 'post',
                        lambda url, timeout=None, headers=None, json=None:
                        (seen.update(body=json), FakeResp(content='ok'))[1])

    router.call_openrouter('що на фото?', image_url='https://cdn/x.jpeg')
    assert seen['body']['model'] == router.OPENROUTER_VISION_MODEL

    router.call_openrouter('звичайний текст')
    assert seen['body']['model'] == router.OPENROUTER_MODEL


def test_explicit_model_still_wins_over_vision_default(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    seen = {}
    monkeypatch.setattr(router.requests, 'post',
                        lambda url, timeout=None, headers=None, json=None:
                        (seen.update(body=json), FakeResp(content='ok'))[1])
    router.call_openrouter('?', image_url='https://cdn/x.jpeg', model='my/model:free')
    assert seen['body']['model'] == 'my/model:free'


def test_kimi_uses_moonshot_endpoint_and_supports_photos(monkeypatch):
    """Kimi платний, але без добової стелі — заради цього його й додано."""
    monkeypatch.setenv('KIMI_API_KEY', 'test-key')
    seen = {}
    monkeypatch.setattr(router.requests, 'post',
                        lambda url, timeout=None, headers=None, json=None:
                        (seen.update(url=url, body=json, headers=headers), FakeResp(content='ок'))[1])

    text, _ = router.call_kimi('що на фото?', image_url='https://cdn/x.jpeg')
    assert text == 'ок'
    assert seen['url'] == 'https://api.moonshot.ai/v1/chat/completions'
    assert seen['headers']['Authorization'] == 'Bearer test-key'
    assert seen['body']['model'] == router.KIMI_MODEL
    assert seen['body']['messages'][0]['content'][1]['image_url']['url'] == 'https://cdn/x.jpeg'


def test_kimi_missing_key_raises(monkeypatch):
    monkeypatch.delenv('KIMI_API_KEY', raising=False)
    with pytest.raises(RuntimeError, match='KIMI_API_KEY'):
        router.call_kimi('питання')


def test_kimi_not_in_default_chain():
    assert 'kimi' not in router.CHAIN
