#!/usr/bin/env python3
"""Клієнт NVIDIA NIM (build.nvidia.com) — альтернативний бекенд для LLM-задач.

Навіщо: локальна gemma3:4b дає 1.9 с на опис і прийнятну якість, але на
великих одноразових задачах (переклад усього каталогу, генерація словників)
хостингові моделі на 30-500B дають помітно кращий текст за ті самі хвилини.
Безкоштовний рівень NVIDIA: ~1000 кредитів, 40 запитів/хв, без картки.

Чому НЕ автологін через сайт: ключ статичний, він не змінюється від сесії
до сесії. Автоматизувати вхід логіном-паролем заради значення, яке
достатньо один раз покласти в .env, означає додати крихку ланку (OAuth,
можлива капча, зміни верстки) без жодного виграшу. Пароль у коді не
зберігається принципово.

Ключ: build.nvidia.com → «Generate API Key» → у .env як NVIDIA_API_KEY.

Запуск:
    python3 tools/nvidia_nim.py --list                 # доступні моделі
    python3 tools/nvidia_nim.py --test                 # проба перекладу
    python3 tools/nvidia_nim.py --compare              # NVIDIA проти локальної
"""
import argparse
import os
import re
import sys
import time

import psycopg2.extras
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402
from noire_ru_translate import PROMPT, validate  # noqa: E402

API = 'https://integrate.api.nvidia.com/v1'
KEY = os.getenv('NVIDIA_API_KEY', '')

# Моделі, придатні для наших задач, у порядку переваги. Перевіряються
# наявністю у /v1/models — перелік на безкоштовному рівні змінюється.
PREFERRED = [
    'meta/llama-3.3-70b-instruct',
    'meta/llama-3.1-70b-instruct',
    'nvidia/llama-3.3-nemotron-super-49b-v1',
    'mistralai/mistral-large-2-instruct',
    'meta/llama-3.1-8b-instruct',
]
# Ліміт безкоштовного рівня — 40 запитів/хв. Тримаємо 1.6 с між викликами:
# запас на випадок, якщо ліміт рахується жорсткіше за ковзне вікно.
PAUSE = 1.6


def headers():
    if not KEY:
        sys.exit('NVIDIA_API_KEY не заданий у .env — згенеруйте ключ на '
                 'build.nvidia.com («Generate API Key») і додайте рядок:\n'
                 'NVIDIA_API_KEY=nvapi-...')
    return {'Authorization': f'Bearer {KEY}', 'Accept': 'application/json'}


def list_models() -> list:
    r = requests.get(f'{API}/models', headers=headers(), timeout=60)
    if r.status_code != 200:
        sys.exit(f'HTTP {r.status_code}: {r.text[:200]}')
    return [m['id'] for m in r.json().get('data', [])]


def pick_model(available: list) -> str:
    """Найкраща з доступних за нашим порядком переваги."""
    for m in PREFERRED:
        if m in available:
            return m
    # запасний варіант: будь-яка instruct-модель середнього розміру
    for m in available:
        if 'instruct' in m and not any(x in m for x in ('vision', 'embed', 'rerank')):
            return m
    return available[0] if available else ''


def ask(model: str, prompt: str, max_tokens=1400) -> tuple:
    """Відповідь моделі й час. Порожній рядок, якщо запит відхилено."""
    t0 = time.time()
    r = requests.post(f'{API}/chat/completions', headers=headers(), json={
        'model': model,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.1, 'top_p': 0.9, 'max_tokens': max_tokens,
        'stream': False,
    }, timeout=180)
    dt = time.time() - t0
    if r.status_code != 200:
        return f'__HTTP_{r.status_code}__ {r.text[:160]}', dt
    try:
        return r.json()['choices'][0]['message']['content'].strip(), dt
    except (KeyError, IndexError):
        return '__EMPTY__', dt


def sample_descriptions(n=5) -> list:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT p.sku, p.description_html d FROM sexopt_products p
                   WHERE p.available AND length(p.description_html) BETWEEN 300 AND 900
                   ORDER BY md5(p.sku) LIMIT %s""", (n,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--test', action='store_true')
    ap.add_argument('--compare', action='store_true')
    ap.add_argument('--model')
    ap.add_argument('--n', type=int, default=5)
    a = ap.parse_args()

    if a.list:
        models = list_models()
        print(f'доступно моделей: {len(models)}\n')
        chosen = pick_model(models)
        for m in sorted(models):
            mark = ' ← обрана' if m == chosen else ''
            if any(k in m for k in ('llama', 'nemotron', 'mistral', 'qwen', 'gemma')):
                print(f'   {m}{mark}')
        print(f'\nбуде використана: {chosen}')
        return

    model = a.model or pick_model(list_models())
    rows = sample_descriptions(a.n)
    print(f'модель: {model}\nописів: {len(rows)}\n')

    ok = refused = 0
    t_all = 0.0
    for r in rows:
        res, dt = ask(model, PROMPT.format(t=r['d']))
        t_all += dt
        if res.startswith('__HTTP_') or res == '__EMPTY__':
            refused += 1
            print(f"   {r['sku']:10} ВІДМОВА  {res[:110]}")
            continue
        why = validate(r['d'], res)
        ok += not why
        flat = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', res))[:100]
        print(f"   {r['sku']:10} {dt:5.1f}с  {'✓' if not why else '✗ ' + why}")
        print(f'      {flat}')
        time.sleep(PAUSE)

    print(f'\nпройшли валідатор: {ok}/{len(rows)} | відмов: {refused} | '
          f'середньо {t_all / max(len(rows), 1):.1f} с/опис')
    if refused:
        print('\nВідмови на цьому контенті очікувані: товари 18+, і хостингові '
              'моделі мають фільтри безпеки. Якщо відмов багато — задачу треба '
              'лишати локальній моделі.')


if __name__ == '__main__':
    main()
