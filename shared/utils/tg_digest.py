"""Щоденне зведення для Telegram замість десятків інформаційних повідомлень.

Навіщо (рішення власника 13.09.2026): синхронізації й публікації слали до
~22 інформаційних повідомлень на добу («наявність Єпіцентру: публікація ok»
кожні 2 години, «NOIRE sync» при кожній зміні ціни, «Watchdog OK» кожні
6 годин) — серед них легко не побачити замовлення.

Правило:
  * тривоги й помилки (❌, 🚨, демпінг, падіння сервісу, замовлення,
    повідомлення клієнтів) — як і раніше, одразу через tg();
  * звичайний перебіг («оновлено», «опубліковано», «OK») — сюди, через
    add(); раз на добу watchdog збирає все в одне повідомлення.

Файл — JSON Lines, по рядку на подію; watchdog після відправки зведення
лишає лише записи, новіші за звіт.
"""
import json
import os
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIGEST_FILE = os.path.join(BASE_DIR, 'data', 'tg_digest.jsonl')


def add(source: str, text: str, **nums):
    """Записати подію для щоденного зведення. Ніколи не падає: зведення —
    допоміжне, воно не сміє зупинити синхронізацію."""
    try:
        os.makedirs(os.path.dirname(DIGEST_FILE), exist_ok=True)
        with open(DIGEST_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': time.time(), 'at': datetime.now().strftime('%d.%m %H:%M'),
                                'source': source, 'text': text, 'nums': nums},
                               ensure_ascii=False) + '\n')
    except Exception:
        pass


def read_since(ts: float) -> list:
    if not os.path.exists(DIGEST_FILE):
        return []
    out = []
    with open(DIGEST_FILE, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get('ts', 0) >= ts:
                out.append(r)
    return out


def trim_before(ts: float):
    """Прибрати записи, вже включені у відправлене зведення."""
    keep = read_since(ts)
    tmp = DIGEST_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.replace(tmp, DIGEST_FILE)


def summary(entries: list) -> str:
    """Зведення по джерелах: скільки подій, суми числових полів, останній текст."""
    if not entries:
        return 'подій не записано'
    by = {}
    for r in entries:
        s = by.setdefault(r['source'], {'n': 0, 'nums': {}, 'last': ''})
        s['n'] += 1
        for k, v in (r.get('nums') or {}).items():
            if isinstance(v, (int, float)):
                s['nums'][k] = s['nums'].get(k, 0) + v
        s['last'] = f"{r.get('at', '')} {r.get('text', '')}".strip()
    lines = []
    for src, s in by.items():
        nums = ', '.join(f'{k} {v:g}' for k, v in s['nums'].items() if v)
        lines.append(f"• <b>{src}</b>: ×{s['n']}" + (f" — {nums}" if nums else '')
                     + (f"\n   остання: {s['last'][:120]}" if s['last'] else ''))
    return '\n'.join(lines)
