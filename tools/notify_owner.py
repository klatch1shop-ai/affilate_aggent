"""Надіслати повідомлення власнику через @NOIRE_helper_Bot з командного рядка.

Канал зв'язку 26.09.2026: власник керує з VSCode, а підсумки/сповіщення
отримує в Telegram, не чекаючи біля екрана. Незалежний від запущеного
сервісу helper-bot — той самий токен і ADMIN_ID з .env, окремий HTTP-виклик.

    venv/bin/python tools/notify_owner.py "текст повідомлення"
    from tools.notify_owner import notify
    notify('Prom-реєстр готовий: 21/21 команд згенеровано')
"""
import os
import sys

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))


def notify(text: str, timeout: int = 15) -> int:
    """Повертає message_id. Кидає RuntimeError, якщо Telegram відмовив."""
    token = os.getenv('HELPER_BOT_TOKEN', '')
    admin_id = os.getenv('TELEGRAM_ADMIN_ID', '')
    if not token or not admin_id:
        raise RuntimeError('HELPER_BOT_TOKEN або TELEGRAM_ADMIN_ID не задано в .env')
    r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage', timeout=timeout,
                      json={'chat_id': int(admin_id), 'text': text, 'parse_mode': 'HTML',
                            'disable_web_page_preview': True})
    body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
    if r.status_code != 200 or not body.get('ok'):
        raise RuntimeError(f'Telegram {r.status_code}: {body or r.text[:200]}')
    return body['result']['message_id']


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    mid = notify(sys.argv[1])
    print(f'надіслано, message_id={mid}')
