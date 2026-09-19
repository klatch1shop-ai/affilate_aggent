#!/usr/bin/env python3
"""Бот-помічник @NOIRE_helper_Bot: чат покупців і текстові команди.

Окремий від робочого бота замовлень (tg_dispatcher/main.py) — рішення власника
19.09.2026: помилка тут не має зачепити замовлення. Уся логіка — у `helper/`,
`tg_dispatcher/inbox/`, `integrations/` (TASK-02…06, перевірені тестами); цей
файл лише з'єднує їх із Telegram і справжньою мережею.

Етап 1 — ЛИШЕ ЧИТАННЯ: у майданчики бот нічого не пише. Відповіді покупцям —
режим HELPER_REPLY_MODE (за замовчуванням `draft`: бот показує, що надіслав би).

.env: HELPER_BOT_TOKEN, TELEGRAM_ADMIN_ID (кому слати картки),
      HELPER_ALLOWED_IDS (хто може писати боту; за замовчуванням — лише адмін),
      ROZETKA_API_TOKEN, NP_API_KEY, HELPER_REPLY_MODE, HELPER_POLL_SEC.
"""
import asyncio
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
load_dotenv(BASE / '.env')

from helper.access import is_allowed, parse_ids                     # noqa: E402
from helper.feeds import feeds_status                               # noqa: E402
from helper.inbox_cycle import DeliveryQueue, InboxCycle            # noqa: E402
from helper.services import answer, build_fetchers                  # noqa: E402
from integrations.novaposhta import NovaPoshtaClient                # noqa: E402
from integrations.rozetka import RozetkaClient                      # noqa: E402
from tg_dispatcher.inbox.reply import plan_reply                    # noqa: E402
from tg_dispatcher.inbox.store import InboxStore                    # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('helper_bot')

TOKEN = os.getenv('HELPER_BOT_TOKEN', '')
ADMIN_ID = int(os.getenv('TELEGRAM_ADMIN_ID', '0') or 0)
ALLOWED = parse_ids(os.getenv('HELPER_ALLOWED_IDS') or str(ADMIN_ID or ''))
REPLY_MODE = os.getenv('HELPER_REPLY_MODE', 'draft')
POLL_SEC = int(os.getenv('HELPER_POLL_SEC', '300'))
# Бази — поза репозиторієм: data/ у git не ігнорується, а тут дані покупців.
DATA = Path(os.getenv('HELPER_DATA_DIR', str(Path.home() / 'helper_data')))
FEEDS = {                                    # лише фіди, що оновлюються щодня
    'rozetka': BASE / 'output' / 'noire_rozetka.xml',
    'prom': BASE / 'output' / 'noire_prom.xml',
    'epicentr': BASE / 'output' / 'noire_epicentr_stock.xml',
}
SERVICES = ('tg-dispatcher', 'rozetka-order-agent', 'epicentr-order-agent',
            'noire-notifier', 'feed-server')
TG_API = f'https://api.telegram.org/bot{TOKEN}'


# ── справжній транспорт для адаптерів ─────────────────────────────────

def _call(method, url, **kw):
    """HTTP з відображенням мережевих збоїв у ConnectionError/TimeoutError адаптерів."""
    try:
        r = requests.request(method, url, timeout=30, **kw)
    except requests.Timeout as e:
        raise TimeoutError(type(e).__name__) from None
    except requests.RequestException as e:
        raise ConnectionError(type(e).__name__) from None
    try:
        body = r.json()
    except ValueError:
        body = None
    return r.status_code, body


def http_get(url, params=None, headers=None):
    return _call('GET', url, params=params, headers=headers)


def http_post(url, json=None, headers=None):
    return _call('POST', url, json=json, headers=headers)


def tg_send(text):
    """Синхронне надсилання власнику (для InboxCycle, що працює в потоці)."""
    status, body = _call('POST', f'{TG_API}/sendMessage', json={
        'chat_id': ADMIN_ID, 'text': text, 'parse_mode': 'HTML',
        'disable_web_page_preview': True})
    if status != 200 or not (body or {}).get('ok'):
        raise ConnectionError(f'Telegram {status}')
    return body['result']['message_id']


# ── залежності команд ─────────────────────────────────────────────────

def stock_lookup(sku):
    from shared.utils.db import get_connection
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute('SELECT sku, name, available, quantity, price_retail FROM sexopt_products '
                    'WHERE upper(sku) = upper(%s) LIMIT 1', (sku,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def feeds_now():
    return feeds_status({k: str(v) for k, v in FEEDS.items()}, time.time())


def system_now():
    lines = []
    for name in SERVICES:
        r = subprocess.run(['systemctl', '--user', 'is-active', name],
                           capture_output=True, text=True, timeout=10)
        state = r.stdout.strip() or 'невідомо'
        lines.append(f"{'✅' if state == 'active' else '❌'} {name}: {state}")
    return '\n'.join(lines)


def make_fetchers():
    rz = RozetkaClient(http_get, os.getenv('ROZETKA_API_TOKEN', ''), time.sleep)
    np_key = os.getenv('NP_API_KEY', '')
    np = NovaPoshtaClient(http_post, np_key, time.sleep) if np_key else None
    return rz, build_fetchers(rozetka=rz, novaposhta=np, stock_lookup=stock_lookup,
                              feeds_status=feeds_now, system_status=system_now)


# ── Telegram ──────────────────────────────────────────────────────────

dp = Dispatcher()
RZ, FETCHERS = make_fetchers()
DATA.mkdir(parents=True, exist_ok=True)
STORE = InboxStore(str(DATA / 'inbox.db'))
QUEUE = DeliveryQueue(str(DATA / 'queue.db'))
REMIND_MAX_MIN = int(os.getenv('HELPER_REMIND_MAX_H', '48')) * 60


class RecentStore:
    """Нагадувати лише про свіжі чати. На першому запуску в базу потрапляють усі
    старі розмови, і там, де останнім писав покупець («дякую» тижневої давнини),
    unanswered() вважав би їх такими, що чекають. Межа — HELPER_REMIND_MAX_H."""

    def __init__(self, store):
        self._store = store

    def __getattr__(self, name):
        return getattr(self._store, name)

    def unanswered(self, now, older_than_min):
        return [x for x in self._store.unanswered(now, older_than_min)
                if x['waiting_min'] <= REMIND_MAX_MIN]


CYCLE = InboxCycle(RecentStore(STORE), QUEUE, RZ.chats_page, RZ.chat, tg_send,
                   lambda: datetime.now(timezone.utc))
LOCK = asyncio.Lock()                   # SQLite і цикл — з одного потоку за раз


def allowed(message: Message) -> bool:
    ok = message.from_user is not None and is_allowed(message.from_user.id, ALLOWED)
    if not ok:
        log.warning('відмовлено у доступі: user %s', message.from_user.id if message.from_user else '?')
    return ok


@dp.message(CommandStart())
@dp.message(Command('help'))
async def on_start(message: Message):
    if not allowed(message):
        return
    await message.answer('Я помічник NOIRE. Пишіть звичайним текстом, наприклад:\n\n'
                         + answer('', FETCHERS)
                         + f'\n\nНові повідомлення покупців Rozetka приходять сюди карткою.'
                         f'\nВідповіді покупцям: режим «{REPLY_MODE}».')


@dp.message(F.reply_to_message, F.text)
async def on_reply(message: Message):
    if not allowed(message):
        return
    async with LOCK:
        plan = await asyncio.to_thread(plan_reply, message.reply_to_message.message_id,
                                       message.text, STORE, REPLY_MODE)
    if plan['action'] == 'send':
        # Надсилання в Rozetka ще не перевірене на живому чаті — лише з дозволу власника.
        await message.answer('⚠️ Надсилання покупцю ще не підключене. Текст не надіслано.')
        return
    tail = f"\n\n{plan['body']}" if plan['ok'] and plan['body'] else ''
    await message.answer(f"{plan['message']}{tail}")


@dp.message(F.text)
async def on_text(message: Message):
    if not allowed(message):
        return
    text = await asyncio.to_thread(answer, message.text, FETCHERS)
    await message.answer(text[:4000], parse_mode=None)


async def inbox_loop():
    while True:
        try:
            async with LOCK:
                res = await asyncio.to_thread(CYCLE.poll)
                await asyncio.to_thread(CYCLE.remind)
            log.info('чат покупців: нових %s, доставлено %s, у черзі %s, помилок %s',
                     res['new'], res['delivered'], res['queued'], len(res['errors']))
        except Exception:
            log.exception('цикл чату покупців')
        await asyncio.sleep(POLL_SEC)


async def main():
    if not TOKEN or not ADMIN_ID or not ALLOWED:
        raise SystemExit('Потрібні HELPER_BOT_TOKEN і TELEGRAM_ADMIN_ID у .env')
    bot = Bot(TOKEN)
    asyncio.create_task(inbox_loop())
    log.info('старт: доступ %s користувачам, режим відповідей %s', len(ALLOWED), REPLY_MODE)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
