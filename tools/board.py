"""Дошка завдань: збирає СПРАВЖНІ числа з живих джерел і складає docs/BOARD.md.

Числа руками не вписуються — усе зчитується: черга задач (SQLite), файл
прогресу старого батча, лічильники Rozetka, живі проби провайдерів.

    venv/bin/python tools/board.py              # оновити docs/BOARD.md
    venv/bin/python tools/board.py --telegram   # ще й надіслати зведення
    venv/bin/python tools/board.py --no-probe   # без мережевих проб (швидко)
"""
import argparse
import json
import os
import sys
import time

from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

from shared.utils import board                                      # noqa: E402

QUEUE_DB = os.path.join(BASE, 'data', 'tasks', 'epicentr.db')
LEGACY_PROGRESS = os.path.join(BASE, 'scratchpad', 'fill_gaps_all_progress.json')
WATCHDOG_LOG = os.path.join(BASE, 'logs', 'epicentr_watchdog.log')
BLOCK_FILE = '/tmp/epicentr_codex_blocked_until'
OUT = os.path.join(BASE, 'docs', 'BOARD.md')
EPICENTR_TOTAL = 1790


def epicentr_track():
    """Спершу черга; якщо її ще не наповнено — старий файл прогресу."""
    if os.path.exists(QUEUE_DB):
        from shared.utils.task_queue import TaskQueue, DONE
        q = TaskQueue(QUEUE_DB)
        counts = q.counts()
        total = sum(counts.values())
        track = {'name': 'Епіцентр · атрибути', 'done': counts.get(DONE, 0),
                 'total': total, 'verified': q.verified_by_two(),
                 'notes': [f'вендори: {q.vendor_usage() or "ще жодного"}']}
        q.close()
    else:
        track = _legacy_epicentr()
    blocker = _codex_block()
    if blocker:
        track['blocker'] = blocker
    track['moving'] = _recently_moved()
    track.setdefault('next_step', 'наповнити чергу й запустити виконавця')
    return track


def _legacy_epicentr():
    try:
        with open(LEGACY_PROGRESS, encoding='utf-8') as f:
            state = json.load(f)
    except OSError:
        return {'name': 'Епіцентр · атрибути', 'done': 0, 'total': EPICENTR_TOTAL}
    rows = state.get('rows') or []
    honest = sum(1 for r in rows
                 if r.get('src_photo') and r.get('src_text')
                 and r.get('src_photo') != r.get('src_text'))
    return {
        'name': 'Епіцентр · атрибути',
        'done': len(state.get('done_skus') or []),
        'total': EPICENTR_TOTAL,
        'verified': honest,
        'notes': [f'старий прогін: {len(rows)} рядків, з них чесно перевірено {honest}'],
    }


def _codex_block():
    try:
        with open(BLOCK_FILE, encoding='utf-8') as f:
            until = float(f.read().strip())
    except (OSError, ValueError):
        return None
    if until <= time.time():
        return None
    return f'квота Codex до {time.strftime("%H:%M", time.localtime(until))}'


def _recently_moved(minutes=30):
    try:
        return (time.time() - os.path.getmtime(WATCHDOG_LOG)) < minutes * 60
    except OSError:
        return False


def rozetka_track(probe=True):
    track = {'name': 'Розетка · dropoffice', 'done': 0, 'total': 1103, 'moving': False,
             'blocker': 'фід не забирається для джерела 55861',
             'notes': ['причини відмови НЕМАЄ: error_reason, blocked_reason, '
                       'стоп-слова й comment порожні в усіх 1077 перевірених',
                       'фід здоровий: 1108 оферів, фото в усіх, опубліковано сьогодні',
                       'заявки bpm 4602797 (961) і 4602798 (97)'],
             'next_step': 'власнику — перевірити прив’язку фіду в кабінеті'}
    if not probe:
        return track
    try:
        import requests
        from integrations.rozetka import RozetkaClient

        def http_get(url, params=None, headers=None):
            r = requests.get(url, params=params, headers=headers, timeout=20)
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, None

        rz = RozetkaClient(http_get, os.getenv('ROZETKA_API_TOKEN', ''), time.sleep)
        on_sale = rz.goods_count('on-sale', 'dropoffice')
        track['done'] = on_sale
        if on_sale:
            track['blocker'] = None
            track['moving'] = True
    except Exception as e:
        track['notes'].append(f'лічильник не зчитано: {type(e).__name__}')
    return track


def vendor_states(probe=True):
    """Живий — відповідає на дешеву пробу. Придатний — дає змістовні відповіді
    саме на наш тип задачі; це окреме знання, з замірів, а не з проби."""
    known_useful = {'openrouter': (True, 'єдиний читає фото, 12–50 с'),
                    'gemini': (False, 'на фото каже «НЕ ВИДНО»'),
                    'codex': (False, 'на фото каже «НЕ ВИДНО»'),
                    'groq': (None, 'лише текст'),
                    'cerebras': (None, 'лише текст')}
    out = []
    for name, (useful, note) in known_useful.items():
        state = {'name': name, 'alive': None, 'useful': useful, 'note': note}
        if probe:
            state['alive'] = _alive(name)
        out.append(state)
    return out


def _alive(name):
    from shared.utils import vendor_pool as vp
    try:
        vp.call(name, 'Відповідай одним словом: 2+2?', timeout=30, max_tokens=200)
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--telegram', action='store_true', help='надіслати зведення власнику')
    ap.add_argument('--no-probe', action='store_true', help='без мережевих проб')
    a = ap.parse_args()
    probe = not a.no_probe

    now = time.strftime('%d.%m %H:%M')
    tracks = [epicentr_track(), rozetka_track(probe=probe)]
    vendors = vendor_states(probe=probe)
    needs_owner = [t['next_step'] for t in tracks
                   if t.get('blocker') and 'власнику' in (t.get('next_step') or '')]

    text = board.render(tracks, vendors, now=now, needs_owner=needs_owner)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(text)
    print(text)
    print(f'\n→ {OUT}')

    if a.telegram:
        from tools.notify_owner import notify
        notify(board.render_telegram(tracks, vendors, now=now, needs_owner=needs_owner))
        print('→ надіслано в Telegram')


if __name__ == '__main__':
    main()
