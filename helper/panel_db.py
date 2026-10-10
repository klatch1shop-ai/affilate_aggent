"""Сховище живої панелі: дошка, чат, журнал команд. SQLite, одна тека.

ЧОМУ SQLITE. Один користувач, один процес-писар, десятки записів на день.
Postgres тут уже є для замовлень, але тягнути туди дошку означало б
прив'язати панель до того, щоб сервер був доступний — а панель має
працювати й тоді, коли ноутбук сам по собі.

ЧОМУ НЕ ДУБЛЮЄМО ДАНІ СИСТЕМИ. Тут лежить ЛИШЕ те, що народжується в
панелі: завдання, ідеї, повідомлення, журнал запусків. Замовлення, картки
й фіди лишаються там, де були, і панель читає їх живими викликами. Інакше
вийшло б два джерела правди — рівно та помилка, через яку зріз карток на
сервері розійшовся з ноутбуком на 6410 записів.

Шлях: PANEL_DB у .env, або data/panel.db поруч із рештою.
"""
import json
import os
import sqlite3
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.getenv('PANEL_DB') or os.path.join(BASE, 'data', 'panel.db')

SCHEMA = """
create table if not exists board (
  id integer primary key autoincrement,
  kind text not null,                 -- 'завдання' | 'ідея' | 'рішення'
  title text not null,
  body text default '',
  status text not null default 'нове', -- нове|в роботі|чекає рішення|зроблено|відкинуто
  напрям text default '',             -- зв'язок із docs/напрями/
  author text not null,               -- 'власник' | 'claude'
  created real not null,
  updated real not null,
  обговорено integer default 0        -- Claude уже забрав на обговорення
);
create index if not exists board_status on board(status);

create table if not exists chat (
  id integer primary key autoincrement,
  role text not null,                 -- 'власник' | 'claude'
  text text not null,
  created real not null,
  прочитано integer default 0         -- інша сторона вже побачила
);
create index if not exists chat_unread on chat(прочитано);

create table if not exists runs (
  id integer primary key autoincrement,
  command text not null,
  params text default '{}',
  risk text default 'R0',
  state text not null,                -- запропоновано|виконано|відмова|збій
  result text default '',
  created real not null,
  by text default 'панель'
);
create index if not exists runs_created on runs(created desc);
"""


def conn():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    # WAL: читач не блокує писаря. Панель читає часто, пише рідко.
    c.execute('pragma journal_mode=WAL')
    c.executescript(SCHEMA)
    return c


def now():
    return time.time()


# ── дошка ────────────────────────────────────────────────────────
def board_add(kind, title, body='', author='власник', напрям='', status='нове'):
    with conn() as c:
        cur = c.execute(
            'insert into board(kind,title,body,status,напрям,author,created,updated)'
            ' values(?,?,?,?,?,?,?,?)',
            (kind, title, body, status, напрям, author, now(), now()))
        return cur.lastrowid


def board_list(status=None, kind=None, limit=200):
    q = 'select * from board'
    w, p = [], []
    if status:
        w.append('status=?'); p.append(status)
    if kind:
        w.append('kind=?'); p.append(kind)
    if w:
        q += ' where ' + ' and '.join(w)
    q += ' order by updated desc limit ?'
    p.append(limit)
    with conn() as c:
        return [dict(r) for r in c.execute(q, p)]


def board_update(id_, **fields):
    allowed = {'title', 'body', 'status', 'напрям', 'kind', 'обговорено'}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return 0
    sets['updated'] = now()
    q = 'update board set ' + ','.join(f'{k}=?' for k in sets) + ' where id=?'
    with conn() as c:
        return c.execute(q, list(sets.values()) + [id_]).rowcount


def board_new_for_claude():
    """Ідеї власника, яких Claude ще не забирав на обговорення."""
    with conn() as c:
        return [dict(r) for r in c.execute(
            "select * from board where author='власник' and обговорено=0"
            " order by created")]


# ── чат ──────────────────────────────────────────────────────────
def chat_add(role, text):
    with conn() as c:
        cur = c.execute('insert into chat(role,text,created) values(?,?,?)',
                        (role, text, now()))
        return cur.lastrowid


def chat_tail(limit=50, after_id=None):
    if after_id:
        q, p = 'select * from chat where id>? order by id limit ?', (after_id, limit)
    else:
        q, p = ('select * from (select * from chat order by id desc limit ?)'
                ' order by id', (limit,))
    with conn() as c:
        return [dict(r) for r in c.execute(q, p)]


def chat_unread(role='власник'):
    """Повідомлення ВІД вказаної сторони, яких інша ще не бачила."""
    with conn() as c:
        return [dict(r) for r in c.execute(
            'select * from chat where role=? and прочитано=0 order by id', (role,))]


def chat_mark_read(ids):
    if not ids:
        return 0
    with conn() as c:
        return c.execute(
            'update chat set прочитано=1 where id in (%s)'
            % ','.join('?' * len(ids)), list(ids)).rowcount


# ── журнал команд ────────────────────────────────────────────────
def run_add(command, params, risk, state, result='', by='панель'):
    with conn() as c:
        cur = c.execute(
            'insert into runs(command,params,risk,state,result,created,by)'
            ' values(?,?,?,?,?,?,?)',
            (command, json.dumps(params, ensure_ascii=False), risk, state,
             str(result)[:4000], now(), by))
        return cur.lastrowid


def run_set(id_, state, result=''):
    with conn() as c:
        return c.execute('update runs set state=?, result=? where id=?',
                         (state, str(result)[:4000], id_)).rowcount


def runs_tail(limit=50):
    with conn() as c:
        return [dict(r) for r in c.execute(
            'select * from runs order by id desc limit ?', (limit,))]
