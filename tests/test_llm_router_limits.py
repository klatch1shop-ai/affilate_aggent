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
