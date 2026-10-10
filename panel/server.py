#!/usr/bin/env python3
"""Жива панель: команди, дошка, чат. FastAPI, слухає в мережі Tailscale.

ДЕ ЖИВЕ. За замовчуванням на ноутбуці, на адресі Tailscale. Трафік у
tailnet уже шифрований WireGuard, тому HTTPS і `tailscale serve` не
обов'язкові — а `serve` ще й потребує одноразового sudo. Назовні панель
НЕ видно: перевірено, запит із публічної адреси не доходить.

ЧОМУ НЕ FUNNEL. Панель уміє створювати накладні, тобто витрачати гроші.
`tailscale funnel` виставив би її в інтернет. Лише `serve`/tailnet.

БЕЗПЕКА. Один спільний секрет `PANEL_TOKEN` у заголовку або cookie. Це не
захист від зловмисника в tailnet, це захист від випадкового відкриття
сусіднім пристроєм. Справжня межа — tailnet.

ПІДТВЕРДЖЕННЯ. R0 виконується одразу. R2 і R3 спершу повертають
«пропозицію» з показаними параметрами; виконання — окремим запитом із
тим самим id. Той самий порядок, що в Telegram, щоб не було двох різних
правил для однієї дії.

    venv/bin/python panel/server.py
    PANEL_HOST=0.0.0.0 PANEL_PORT=8600 venv/bin/python panel/server.py
"""
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from dotenv import load_dotenv                                      # noqa: E402
load_dotenv(os.path.join(BASE, '.env'))

from fastapi import FastAPI, HTTPException, Request                 # noqa: E402
from fastapi.responses import JSONResponse, FileResponse            # noqa: E402
from fastapi.staticfiles import StaticFiles                         # noqa: E402
from pydantic import BaseModel                                      # noqa: E402

from helper import panel_db as DB                                   # noqa: E402
from helper import supervisor as S                                  # noqa: E402

HOST = os.getenv('PANEL_HOST', '100.126.131.55')   # адреса Tailscale ноутбука
PORT = int(os.getenv('PANEL_PORT', '8600'))
TOKEN = os.getenv('PANEL_TOKEN', '')
WEB = os.path.join(BASE, 'web')

app = FastAPI(title='Операційна панель')


def tg(text):
    """Дублювання в Telegram. Мовчазний збій не має ламати відповідь веб-у."""
    try:
        from tools.notify_owner import notify
        return bool(notify(text))
    except Exception:
        return False


@app.middleware('http')
async def guard(request: Request, call_next):
    if TOKEN and request.url.path.startswith('/api/'):
        given = (request.headers.get('x-panel-token')
                 or request.query_params.get('token')
                 or request.cookies.get('panel_token'))
        if given != TOKEN:
            return JSONResponse(
                {'error': 'потрібен PANEL_TOKEN — відкрийте / у браузері, '
                          'щоб отримати cookie'}, status_code=401)
        # Запит із чужого походження відхиляємо навіть із правильною cookie.
        origin = request.headers.get('origin')
        if origin and request.url.hostname not in origin:
            return JSONResponse({'error': 'чуже походження запиту'},
                                status_code=403)
    return await call_next(request)


# ── команди ──────────────────────────────────────────────────────
class RunIn(BaseModel):
    command: str
    params: dict = {}


@app.get('/api/commands')
def commands():
    path = os.path.join(WEB, 'commands.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)


@app.post('/api/parse')
def parse(body: dict):
    """Фраза власника → команда. Той самий розбір, що в Telegram."""
    return S.parse(body.get('text') or '') or {'command': None}


@app.post('/api/run')
def run(body: RunIn):
    """R0 виконуємо тут. R2 і R3 — НІ.

    Рішення після розбору 10.10: панель має право ПРОПОНУВАТИ і не має
    права ПІДТВЕРДЖУВАТИ. Причини дві, обидві перевірені.

    1) `confirm.db` живе на сервері (`helper_bot/main.py:73,434`). Якби
       панель на ноутбуці вела свій журнал підтверджень, вийшло б дві
       бази — а захист від подвійної накладної (унікальний індекс по
       intent+content_key і `_claim()`) діє В МЕЖАХ ОДНІЄЇ бази. Дві
       бази = дубль ТТН = реальні гроші.
    2) Сенс підтвердження в тому, що пропозиція і згода йдуть РІЗНИМИ
       каналами. Якщо та сама вкладка і пропонує, і підтверджує, TTL на
       5 хвилин не захищає ні від чого.

    Тому ризикована команда з панелі йде в Telegram як прохання, і
    власник підтверджує там, де це вже працює.
    """
    spec = S.COMMANDS.get(body.command)
    if not spec:
        raise HTTPException(404, f'немає команди {body.command}')
    risk = spec['risk']
    if risk == 'R0':
        return _execute(body.command, body.params, risk)

    rid = DB.run_add(body.command, body.params, risk, 'передано в Telegram')
    пар = ', '.join(f'{k}={v}' for k, v in body.params.items()) or 'без параметрів'
    ok = tg(f'🔐 <b>Панель просить підтвердити</b>\n'
            f'Команда: <code>{body.command}</code> ({risk})\n'
            f'{spec["about"]}\nПараметри: {пар}\n\n'
            f'Підтвердьте тут, у боті — панель сама цього зробити не може.')
    if not ok:
        DB.run_set(rid, 'збій', 'Telegram не прийняв прохання')
        return {'збій': 'не вдалось надіслати прохання в Telegram'}
    return {'передано_в_telegram': True, 'id': rid, 'ризик': risk,
            'команда': body.command, 'параметри': body.params,
            'що': spec['about'],
            'пояснення': 'Ризикована дія підтверджується лише в боті — '
                         'там один журнал і захист від подвійної накладної.'}


def _execute(command, params, risk, rid=None):
    spec = S.COMMANDS[command]
    rid = rid or DB.run_add(command, params, risk, 'виконується')
    try:
        res = spec['fn'](**params)
    except Exception as e:
        msg = f'{type(e).__name__}: {e}'
        DB.run_set(rid, 'збій', msg)
        tg(f'❌ Панель · {command}\n{msg[:300]}')
        return {'id': rid, 'збій': msg}
    short = json.dumps(res, ensure_ascii=False, default=str)[:1200]
    DB.run_set(rid, 'виконано', short)
    # Дублюємо в Telegram — власник просив бачити те саме, що й у боті.
    tg(f'🖥 Панель · <b>{command}</b>\n<code>{short[:900]}</code>')
    return {'id': rid, 'результат': res}


@app.get('/api/runs')
def runs(limit: int = 30):
    return DB.runs_tail(limit)


# ── дошка ────────────────────────────────────────────────────────
@app.get('/api/board')
def board(status: str = None, kind: str = None):
    return DB.board_list(status=status, kind=kind)


@app.post('/api/board')
def board_add(body: dict):
    if not (body.get('title') or '').strip():
        raise HTTPException(400, 'порожній заголовок')
    i = DB.board_add(kind=body.get('kind', 'ідея'),
                     title=body['title'].strip(),
                     body=body.get('body', ''),
                     author=body.get('author', 'власник'),
                     напрям=body.get('напрям', ''))
    tg(f'📝 Нова {body.get("kind", "ідея")} на дошці: <b>{body["title"][:120]}</b>')
    return {'id': i}


@app.patch('/api/board/{id_}')
def board_patch(id_: int, body: dict):
    n = DB.board_update(id_, **body)
    if not n:
        raise HTTPException(404, 'не знайдено або нічого міняти')
    return {'оновлено': n}


# ── чат ──────────────────────────────────────────────────────────
@app.get('/api/chat')
def chat(after: int = 0, limit: int = 60):
    return DB.chat_tail(limit=limit, after_id=after or None)


@app.post('/api/chat')
def chat_send(body: dict):
    text = (body.get('text') or '').strip()
    if not text:
        raise HTTPException(400, 'порожнє повідомлення')
    i = DB.chat_add('власник', text)
    # Те саме повідомлення йде в Telegram — щоб воно знайшло мене там,
    # де я його точно побачу, а не лише в базі.
    tg(f'💬 Через панель: {text[:900]}')
    return {'id': i}


# ── стан ─────────────────────────────────────────────────────────
@app.get('/api/status')
def status():
    unread = len(DB.chat_unread('claude'))
    return {
        'команд': len(S.COMMANDS),
        'дошка': {'усього': len(DB.board_list()),
                  'нових_ідей': len(DB.board_new_for_claude())},
        'непрочитаних_від_claude': unread,
        'останній_запуск': (DB.runs_tail(1) or [{}])[0].get('created'),
        'час': time.time(),
    }


# ── статика ──────────────────────────────────────────────────────
@app.get('/')
def index():
    """Віддаємо сторінку й кладемо секрет у cookie SameSite=Strict.

    Навіщо саме так. Tailscale засвідчує ПРИСТРІЙ, а не людину, тому
    сам по собі tailnet не захищає від запиту, який зробить чужа
    вкладка у браузері на цій же машині (DNS-rebinding). Cookie зі
    SameSite=Strict така вкладка ні прочитати, ні надіслати не може —
    саме від цього тут захист. Від зловмисника всередині tailnet
    захищає не це, а склад самого tailnet: звідти треба прибрати
    пристрої, якими вже не користуються.
    """
    r = FileResponse(os.path.join(WEB, 'index.html'))
    if TOKEN:
        r.set_cookie('panel_token', TOKEN, httponly=True, samesite='strict',
                     max_age=60 * 60 * 24 * 30, path='/')
    return r


app.mount('/', StaticFiles(directory=WEB), name='web')


if __name__ == '__main__':
    import uvicorn
    print(f'панель: http://{HOST}:{PORT}  (лише мережа Tailscale)')
    if not TOKEN:
        print('УВАГА: PANEL_TOKEN не задано — доступ без секрету')
    uvicorn.run(app, host=HOST, port=PORT, log_level='warning')
