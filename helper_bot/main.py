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
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
load_dotenv(BASE / '.env')

from helper.access import is_allowed, parse_ids                     # noqa: E402
from helper.digest import build_digest, due                         # noqa: E402
from helper.keyboards import MENU, to_query                         # noqa: E402
from tg_dispatcher.ai_brain import commands                         # noqa: E402
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


def services_now():
    out = {}
    for name in SERVICES:
        r = subprocess.run(['systemctl', '--user', 'is-active', name],
                           capture_output=True, text=True, timeout=10)
        out[name] = r.stdout.strip() or 'невідомо'
    return out


def system_now():
    lines = []
    for name in SERVICES:
        r = subprocess.run(['systemctl', '--user', 'is-active', name],
                           capture_output=True, text=True, timeout=10)
        state = r.stdout.strip() or 'невідомо'
        lines.append(f"{'✅' if state == 'active' else '❌'} {name}: {state}")
    return '\n'.join(lines)


def unanswered_now():
    # Окреме з'єднання: команди виконуються в іншому потоці, ніж цикл чатів (SQLite).
    st = InboxStore(str(DATA / 'inbox.db'))
    return st.unanswered(datetime.now(timezone.utc), 30, max_age_min=REMIND_MAX_MIN)


def backup_now():
    files = sorted((Path.home() / 'backups' / 'pg').glob('pg_*.dump'), key=lambda p: p.stat().st_mtime)
    if not files:
        return {'last': None, 'size_mb': None, 'age_h': None, 'ok': False}
    last = files[-1]
    age_h = (time.time() - last.stat().st_mtime) / 3600
    return {'last': datetime.fromtimestamp(last.stat().st_mtime).strftime('%Y-%m-%d %H:%M'),
            'size_mb': round(last.stat().st_size / 1024 / 1024, 1), 'age_h': round(age_h, 1),
            'ok': age_h < 26}


def orders_without_ttn_now(rz):
    active = {o['id']: o for o in rz.orders(4) + rz.orders(2)}.values()
    return [{'id': o['id'], 'created': o.get('created'), 'source': 'rozetka'}
            for o in active if not str(o.get('ttn') or '').strip()]


def make_fetchers():
    rz = RozetkaClient(http_get, os.getenv('ROZETKA_API_TOKEN', ''), time.sleep)
    np_key = os.getenv('NP_API_KEY', '')
    np = NovaPoshtaClient(http_post, np_key, time.sleep) if np_key else None
    return rz, build_fetchers(rozetka=rz, novaposhta=np, stock_lookup=stock_lookup,
                              feeds_status=feeds_now, system_status=system_now,
                              unanswered=unanswered_now, backup_status=backup_now,
                              orders_without_ttn=lambda: orders_without_ttn_now(rz))


# ── Telegram ──────────────────────────────────────────────────────────

dp = Dispatcher()
KEYBOARD = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in row] for row in MENU],
                               resize_keyboard=True, is_persistent=True)


def help_text():
    """Лише підключені команди, згруповано за каталогом (TASK-09)."""
    from tg_dispatcher.ai_brain.catalog import help_text as catalog_help
    available = {i for i, c in commands.ALL_COMMANDS.items() if c['fetcher'] in FETCHERS}
    return catalog_help(available)
RZ, FETCHERS = make_fetchers()
DATA.mkdir(parents=True, exist_ok=True)
REMIND_MAX_MIN = int(os.getenv('HELPER_REMIND_MAX_H', '48')) * 60
# SQLite дозволяє з'єднання лише в потоці, де його створено. Тому вся робота з
# базами чату — в ОДНОМУ окремому потоці, і бази відкриваються саме в ньому
# (19.09: перший запуск упав з ProgrammingError, коли цикл пішов через to_thread).
DB_EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix='helper-db')
STATE = {}


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


class RozetkaChats:
    """Чати Rozetka лише ПОШУКОМ — без відкриття.

    19.09 за офіційною документацією (api-seller.rozetka.com.ua/apidoc):
    * `GET /messages/{id}` («Відкрити чат») ПОЗНАЧАЄ ЧАТ ПРОЧИТАНИМ — власник втратив би
      позначку «нове» в кабінеті. Тому тут його немає взагалі.
    * `/messages/search` без `msgType` віддає лише чати по товарах; питання по
      замовленнях (повернення, «де посилка») — лише з `msgType=orders`.
    * Пошук з `expand=messages` віддає всю розмову (перевірено: 16/16) і не читає її.
    Обидва типи зливаються в одну «сторінку» для collect_rozetka; курсор спільний
    (обходяться всі сторінки обох типів, тож це безпечно).
    """
    TYPES = ('items', 'orders')

    def __init__(self, rz):
        self.rz, self.cache = rz, {}

    def list_page(self, page):
        chats, pages = [], 0
        for t in self.TYPES:
            c = self.rz._request('/messages/search', {'msgType': t, 'page': page,
                                                      'expand': 'messages', 'sort': '-updated'})
            pages = max(pages, int((c.get('_meta') or {}).get('pageCount') or 0))
            for ch in c.get('chats') or []:
                self.cache[ch['id']] = ch
                chats.append(ch)
        return {'chats': chats, '_meta': {'pageCount': pages}}

    def get_chat(self, chat_id):
        if chat_id in self.cache:
            return self.cache[chat_id]
        for t in self.TYPES:
            c = self.rz._request('/messages/search', {'msgType': t, 'id': chat_id, 'expand': 'messages'})
            for ch in c.get('chats') or []:
                if ch['id'] == chat_id:
                    return ch
        raise LookupError(f'чат {chat_id} не знайдено')


def _init_db():
    STATE['store'] = InboxStore(str(DATA / 'inbox.db'))
    STATE['queue'] = DeliveryQueue(str(DATA / 'queue.db'))
    src = RozetkaChats(RZ)
    STATE['cycle'] = InboxCycle(RecentStore(STATE['store']), STATE['queue'], src.list_page,
                                src.get_chat, tg_send, lambda: datetime.now(timezone.utc))


async def in_db(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(DB_EXEC, fn, *args)


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
    await message.answer('Я помічник NOIRE. Кнопки внизу або звичайний текст, наприклад:\n\n'
                         + help_text()
                         + f'\n\nНові повідомлення покупців Rozetka приходять сюди карткою.'
                         f'\nВідповіді покупцям: режим «{REPLY_MODE}».'
                         '\nЩоранку о 9:00 — короткий звіт.', reply_markup=KEYBOARD)


@dp.message(F.reply_to_message, F.text)
async def on_reply(message: Message):
    if not allowed(message):
        return
    plan = await in_db(lambda: plan_reply(message.reply_to_message.message_id,
                                          message.text, STATE['store'], REPLY_MODE))
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
    query = to_query(message.text)
    if intents_help(query):
        text = help_text()
    else:
        text = await asyncio.to_thread(answer, query, FETCHERS)
    await message.answer(text[:4000], parse_mode=None, reply_markup=KEYBOARD)


def intents_help(query):
    from tg_dispatcher.ai_brain.intents import parse
    p = parse(query)
    return p['intent'] == 'help' or p['intent'] == 'unknown' or p['confidence'] < 0.5


DIGEST_STATE = DATA / 'digest_last.txt'


def _digest_last():
    try:
        return datetime.strptime(DIGEST_STATE.read_text().strip(), '%Y-%m-%d').date()
    except (OSError, ValueError):
        return None


def _safe_call(fn):
    try:
        return fn()
    except Exception:
        log.exception('ранковий звіт: джерело недоступне')
        return None


def digest_if_due():
    now = datetime.now(timezone.utc)
    if not due(now, _digest_last()):
        return None
    un = _safe_call(lambda: STATE['store'].unanswered(now, 30, max_age_min=REMIND_MAX_MIN))
    text = build_digest(now, _safe_call(RZ.active_orders), un, _safe_call(feeds_now),
                        _safe_call(services_now))
    tg_send(text)
    from helper.digest import KYIV
    DIGEST_STATE.write_text(now.astimezone(KYIV).strftime('%Y-%m-%d'))
    return text


async def inbox_loop():
    while True:
        try:
            res = await in_db(lambda: STATE['cycle'].poll())
            await in_db(lambda: STATE['cycle'].remind())
            try:
                await in_db(digest_if_due)
            except Exception:
                log.exception('ранковий звіт')
            log.info('чат покупців: нових %s, доставлено %s, у черзі %s, помилок %s',
                     res['new'], res['delivered'], res['queued'], len(res['errors']))
        except Exception:
            log.exception('цикл чату покупців')
        await asyncio.sleep(POLL_SEC)


async def main():
    if not TOKEN or not ADMIN_ID or not ALLOWED:
        raise SystemExit('Потрібні HELPER_BOT_TOKEN і TELEGRAM_ADMIN_ID у .env')
    bot = Bot(TOKEN)
    await in_db(_init_db)
    asyncio.create_task(inbox_loop())
    log.info('старт: доступ %s користувачам, режим відповідей %s', len(ALLOWED), REPLY_MODE)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
