"""Канал сповіщень власнику через @NOIRE_helper_Bot, 26.09.2026 — окремий від
запущеного сервісу helper-bot, той самий токен/ADMIN_ID з .env."""
import importlib

import pytest

notify_owner = importlib.import_module('tools.notify_owner')


class FakeResp:
    def __init__(self, status=200, ok=True, message_id=1, ctype='application/json'):
        self.status_code = status
        self.headers = {'content-type': ctype}
        self._body = {'ok': ok, 'result': {'message_id': message_id}}
        self.text = str(self._body)

    def json(self):
        return self._body


def test_notify_sends_to_admin(monkeypatch):
    monkeypatch.setenv('HELPER_BOT_TOKEN', 'tok')
    monkeypatch.setenv('TELEGRAM_ADMIN_ID', '999')
    seen = {}

    def fake_post(url, timeout=None, json=None):
        seen['url'], seen['json'] = url, json
        return FakeResp(message_id=42)

    monkeypatch.setattr(notify_owner.requests, 'post', fake_post)
    mid = notify_owner.notify('привіт')
    assert mid == 42
    assert seen['url'] == 'https://api.telegram.org/bottok/sendMessage'
    assert seen['json']['chat_id'] == 999
    assert seen['json']['text'] == 'привіт'


def test_notify_missing_config_raises(monkeypatch):
    monkeypatch.delenv('HELPER_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_ADMIN_ID', raising=False)
    with pytest.raises(RuntimeError, match='HELPER_BOT_TOKEN'):
        notify_owner.notify('привіт')


def test_notify_telegram_error_raises(monkeypatch):
    monkeypatch.setenv('HELPER_BOT_TOKEN', 'tok')
    monkeypatch.setenv('TELEGRAM_ADMIN_ID', '999')
    monkeypatch.setattr(notify_owner.requests, 'post',
                        lambda *a, **k: FakeResp(status=400, ok=False))
    with pytest.raises(RuntimeError, match='Telegram'):
        notify_owner.notify('привіт')
