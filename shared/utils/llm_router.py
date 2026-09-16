#!/usr/bin/env python3
"""Єдина точка запиту до LLM з перемиканням між безкоштовним шлюзом і локальною моделлю.

Навіщо. До 16.09.2026 наші скрипти зверталися прямо до Ollama на ноутбуці.
Ollama пише грамотно, але **вигадує характеристики товару** (пам'ять
`ollama-ukrainian-models`), а платний Anthropic витрачає тижневий ліміт власника.
OmniRoute (docker, localhost:20128) дає безкоштовні хмарні моделі без ключа.

Ланцюжок за замовчуванням: **omniroute → ollama**. Перший, хто відповів
осмислено, і дає відповідь. Anthropic сюди НЕ включений: платний канал
лишається рішенням власника, а не запасним варіантом за замовчуванням.

Урок NVIDIA NIM (пам'ять `nvidia-nim-usage`): каталог провайдера бреше —
з 82 моделей працювала одна. Тому:
  * `selftest()` перевіряє канали справжнім запитом, а не наявністю в каталозі;
  * канал, який впав, вимикається на COOLDOWN секунд (запобіжник), і цього не
    треба помічати вручну;
  * кожна відповідь пишеться в журнал: хто відповів, скільки секунд, скільки
    символів — щоб потім рахувати, а не згадувати.

    python3 shared/utils/llm_router.py --selftest        # які канали живі
    python3 shared/utils/llm_router.py --ask "текст"     # один запит
    python3 shared/utils/llm_router.py --stats           # звідки йшли відповіді

    from shared.utils.llm_router import ask
    r = ask('Переклади українською: ...', task='text')
    r['text'], r['channel'], r['model'], r['ms']
"""
import argparse
import json
import os
import time

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(BASE, '.env'))

OMNIROUTE_URL = os.getenv('OMNIROUTE_URL', 'http://localhost:20128')
OMNIROUTE_MODEL = os.getenv('OMNIROUTE_MODEL', 'auto')       # 'auto' = шлюз обирає сам
OLLAMA_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
CHAIN = [c.strip() for c in os.getenv('LLM_CHAIN', 'omniroute,ollama').split(',') if c.strip()]
LOG = os.path.join(BASE, 'logs', 'llm_router.jsonl')
COOLDOWN = int(os.getenv('LLM_COOLDOWN', '300'))             # скільки тримати впалий канал вимкненим
_down = {}                                                   # канал → час, до якого не чіпаємо


def _ollama_model(task):
    from shared.utils.model_selector import get_model
    return get_model(task)


def _log(rec):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except OSError:
        pass


def call_omniroute(prompt, timeout=120, model=None, max_tokens=None):
    """Шлюз OmniRoute, API сумісне з OpenAI. Без ключа працює безкоштовний канал."""
    body = {'model': model or OMNIROUTE_MODEL,
            'messages': [{'role': 'user', 'content': prompt}]}
    if max_tokens:
        body['max_tokens'] = max_tokens
    r = requests.post(f'{OMNIROUTE_URL}/v1/chat/completions', json=body, timeout=timeout)
    r.raise_for_status()
    d = r.json()
    msg = (d.get('choices') or [{}])[0].get('message') or {}
    # reasoning_content — «думки» моделі, у відповідь не йдуть
    text = (msg.get('content') or '').strip()
    if not text:
        raise RuntimeError('порожня відповідь шлюзу')
    return text, d.get('model') or body['model']


def call_ollama(prompt, timeout=120, model=None, task='default', max_tokens=None):
    m = model or _ollama_model(task)
    r = requests.post(f'{OLLAMA_URL}/api/generate',
                      json={'model': m, 'prompt': prompt, 'stream': False}, timeout=timeout)
    r.raise_for_status()
    text = (r.json().get('response') or '').strip()
    if not text:
        raise RuntimeError('порожня відповідь Ollama')
    return text, m


def ask(prompt, task='default', timeout=120, chain=None, max_tokens=None, min_len=1):
    """Питає канали по черзі. Повертає {text, channel, model, ms, tried}.

    `min_len` — мінімальна довжина осмисленої відповіді: коротший рядок
    вважається збоєм каналу, а не результатом (у NIM саме так виглядали
    напівживі моделі).
    """
    tried = []
    for ch in (chain or CHAIN):
        if _down.get(ch, 0) > time.time():
            tried.append(f'{ch}:пауза')
            continue
        t0 = time.time()
        try:
            if ch == 'omniroute':
                text, model = call_omniroute(prompt, timeout, max_tokens=max_tokens)
            elif ch == 'ollama':
                text, model = call_ollama(prompt, timeout, task=task, max_tokens=max_tokens)
            else:
                tried.append(f'{ch}:невідомий канал')
                continue
            if len(text) < min_len:
                raise RuntimeError(f'відповідь коротша за {min_len} символів')
            ms = int((time.time() - t0) * 1000)
            rec = {'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'channel': ch, 'model': model,
                   'ms': ms, 'prompt_len': len(prompt), 'text_len': len(text),
                   'task': task, 'tried': tried}
            _log(rec)
            return {'text': text, 'channel': ch, 'model': model, 'ms': ms, 'tried': tried}
        except Exception as e:                                  # канал впав — наступний
            tried.append(f'{ch}:{type(e).__name__}')
            _down[ch] = time.time() + COOLDOWN
            _log({'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'channel': ch, 'error': str(e)[:200],
                  'task': task})
    raise RuntimeError(f'усі канали недоступні: {tried}')


def selftest(prompt=None):
    """Справжній запит у кожен канал окремо. Каталогам не віримо."""
    prompt = prompt or 'Відповідай українською одним коротким реченням: що таке гель-лубрикант?'
    out = []
    for ch in CHAIN:
        t0 = time.time()
        try:
            text, model = (call_omniroute(prompt, 90) if ch == 'omniroute'
                           else call_ollama(prompt, 90, task='text'))
            out.append({'channel': ch, 'ok': True, 'model': model,
                        'ms': int((time.time() - t0) * 1000), 'sample': text[:120]})
        except Exception as e:
            out.append({'channel': ch, 'ok': False, 'error': f'{type(e).__name__}: {str(e)[:120]}',
                        'ms': int((time.time() - t0) * 1000)})
    return out


def stats():
    """Звідки насправді йшли відповіді — з журналу, а не з наміру."""
    import collections
    ok, err, ms = collections.Counter(), collections.Counter(), collections.defaultdict(list)
    if not os.path.exists(LOG):
        return {}
    for line in open(LOG, encoding='utf-8'):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get('error'):
            err[r['channel']] += 1
        else:
            ok[r['channel']] += 1
            ms[r['channel']].append(r.get('ms') or 0)
    return {ch: {'відповідей': ok[ch], 'збоїв': err[ch],
                 'медіана_мс': sorted(ms[ch])[len(ms[ch]) // 2] if ms[ch] else None}
            for ch in set(ok) | set(err)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--ask')
    ap.add_argument('--task', default='default')
    ap.add_argument('--stats', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        for r in selftest():
            mark = '✅' if r['ok'] else '❌'
            print(f"{mark} {r['channel']:10} {r['ms']:6} мс  {r.get('model') or r.get('error')}")
            if r.get('sample'):
                print(f"     {r['sample']}")
    elif a.ask:
        r = ask(a.ask, task=a.task)
        print(f"[{r['channel']} · {r['model']} · {r['ms']} мс]\n{r['text']}")
    elif a.stats:
        for ch, s in stats().items():
            print(f'{ch:10} {s}')
    else:
        print(__doc__)


if __name__ == '__main__':
    import sys
    sys.path.insert(0, BASE)
    main()
