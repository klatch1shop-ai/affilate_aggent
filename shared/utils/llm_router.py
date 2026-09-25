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
import subprocess
import tempfile
import time

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(BASE, '.env'))

OMNIROUTE_URL = os.getenv('OMNIROUTE_URL', 'http://localhost:20128')
OMNIROUTE_MODEL = os.getenv('OMNIROUTE_MODEL', 'auto')       # 'auto' = шлюз обирає сам
OLLAMA_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models'
GEMINI_MODELS = [m.strip() for m in os.getenv(
    'GEMINI_MODELS', 'gemini-flash-lite-latest,gemini-3.1-flash-lite,gemini-3-flash-preview,gemini-flash-latest'
).split(',') if m.strip()]
_gemini_day_out = {}                 # модель → дата, коли вичерпано добовий ліміт
# 19.09.2026: OmniRoute видалено, безкоштовний канал — Gemini (AI Studio, ключ власника).
CHAIN = [c.strip() for c in os.getenv('LLM_CHAIN', 'gemini,ollama').split(',') if c.strip()]
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


def _usage(data):
    """Справжні токени з відповіді провайдера, якщо він їх віддав (аудит TASK-36).

    Досі ми рахували символи й через це не могли перевірити жодну обіцянку економії.
    Немає `usageMetadata` — повертаємо None, а не нулі: «не знаємо» і «нуль» різні речі.
    """
    u = (data or {}).get('usageMetadata') or {}
    if not u:
        return None
    return {'in': u.get('promptTokenCount'), 'out': u.get('candidatesTokenCount'),
            'total': u.get('totalTokenCount')}


def call_gemini(prompt, timeout=120, model=None, max_tokens=None, image_bytes=None, image_mime=None):
    """Gemini через REST AI Studio (безкоштовний тариф). Ключ — лише в заголовку.

    Повертає (текст, модель, токени|None).

    Безкоштовні ліміти — ДОБОВІ й окремі для кожної моделі (19.09: gemini-flash-latest —
    лише 20 запитів/добу). Тому ланцюжок моделей GEMINI_MODELS: вичерпано добу
    (429 …PerDay…) — одразу наступна модель; хвилинний ліміт чи 503 — пауза й повтор.
    Каталогу не віримо: gemini-2.5-* є в списку, але «недоступні новим користувачам».

    `image_bytes`/`image_mime` — аналіз фото (аудит 25.09: пілот заповнення атрибутів
    хардкодив ОДНУ модель напряму в обхід цього ланцюжка й тому вичерпував добовий
    ліміт учетверо швидше, ніж треба, — зайві ескалації на Codex).
    """
    key = os.getenv('GEMINI_API_KEY', '')
    if not key:
        raise RuntimeError('GEMINI_API_KEY не задано')
    cfg = {'temperature': 0.3}
    if max_tokens:
        cfg['maxOutputTokens'] = max_tokens
    parts = [{'text': prompt}]
    if image_bytes:
        import base64
        parts.append({'inlineData': {'mimeType': image_mime or 'image/jpeg',
                                     'data': base64.b64encode(image_bytes).decode()}})
    body = {'contents': [{'parts': parts}], 'generationConfig': cfg}
    last = 'нема моделей'
    for m in ([model] if model else GEMINI_MODELS):
        if _gemini_day_out.get(m) == time.strftime('%Y-%m-%d'):
            continue
        for attempt in range(3):
            r = requests.post(f'{GEMINI_URL}/{m}:generateContent', timeout=timeout,
                              headers={'x-goog-api-key': key}, json=body)
            if r.status_code == 429 and 'PerDay' in r.text:
                _gemini_day_out[m] = time.strftime('%Y-%m-%d')
                break
            if r.status_code not in (429, 503):
                break
            time.sleep(5 * (attempt + 1))
        if r.status_code != 200:
            last = f'{m}: HTTP {r.status_code}'
            continue
        data = r.json()
        parts = (((data.get('candidates') or [{}])[0].get('content') or {}).get('parts') or [])
        text = ''.join(p.get('text', '') for p in parts if not p.get('thought')).strip()
        if text:
            return text, m, _usage(data)
        last = f'{m}: порожня відповідь'
    raise RuntimeError(f'Gemini: {last}')


def call_ollama(prompt, timeout=120, model=None, task='default', max_tokens=None):
    m = model or _ollama_model(task)
    body = {'model': m, 'prompt': prompt, 'stream': False}
    if max_tokens:                      # інакше параметр був порожньою обіцянкою (аудит TASK-36)
        body['options'] = {'num_predict': int(max_tokens)}
    r = requests.post(f'{OLLAMA_URL}/api/generate', json=body, timeout=timeout)
    r.raise_for_status()
    text = (r.json().get('response') or '').strip()
    if not text:
        raise RuntimeError('порожня відповідь Ollama')
    return text, m


class CodexLimitError(RuntimeError):
    """Вичерпано ліміт використання Codex (ChatGPT). Повторювати марно до вказаного часу."""


def call_codex(prompt, image_path=None, timeout=180, model=None):
    """Ескалація до Codex CLI, коли Gemini впав — рішення власника 21.09.2026.

    НЕ в CHAIN за замовчуванням і не викликається автоматично з `ask()`, доки не
    попросили `escalate_to_codex=True`: Codex — обмежений ресурс під нашим власним
    добовим запобіжником (`codex_task.py`), а не безкоштовний запасний канал для
    фонової автоматики. Використовувати свідомо, в інтерактивних/пілотних скриптах.

    `codex exec` уміє те саме, що й `call_gemini`, — текст і аналіз фото (`-i`),
    але моделі й ліміти OpenAI зазвичай більші за безкоштовний тариф Gemini.
    Перевірено вручну 21.09: та сама фотографія дала той самий колір, що й Gemini.
    """
    cmd = ['codex', 'exec', prompt, '--skip-git-repo-check', '--sandbox', 'read-only',
          '--ephemeral']
    if model:
        cmd += ['-m', model]
    if image_path:
        cmd += ['-i', image_path]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        out_path = f.name
    cmd += ['-o', out_path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            err = (r.stderr or '')
            if 'usage limit' in err.lower():
                # 21.09: 268 ескалацій вичерпали ліміт, а помилку ховав банер на початку stderr
                raise CodexLimitError(err.strip().splitlines()[-1][:300])
            raise RuntimeError(f'codex exec: код {r.returncode}: {err.strip()[-300:]}')
        text = open(out_path, encoding='utf-8').read().strip()
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass
    if not text:
        raise RuntimeError('codex exec: порожня відповідь')
    return text, model or 'codex-exec'


def ask(prompt, task='default', timeout=120, chain=None, max_tokens=None, min_len=1,
       escalate_to_codex=False, image_path=None):
    """Питає канали по черзі. Повертає {text, channel, model, ms, tried, tokens}.

    `min_len` — мінімальна довжина осмисленої відповіді: коротший рядок
    вважається збоєм каналу, а не результатом (у NIM саме так виглядали
    напівживі моделі).

    `escalate_to_codex=True` — коли весь звичайний ланцюжок вичерпано (усі
    канали впали чи на паузі), останньою спробою питає `call_codex`
    (з `image_path`, якщо задано). За замовчуванням вимкнено — ескалація лише
    свідома, не для фонової автоматики.
    """
    tried = []
    for ch in (chain or CHAIN):
        if _down.get(ch, 0) > time.time():
            tried.append(f'{ch}:пауза')
            continue
        t0 = time.time()
        try:
            tokens = None
            if ch == 'gemini':
                text, model, tokens = call_gemini(prompt, timeout, max_tokens=max_tokens)
            elif ch == 'omniroute':
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
            if tokens:
                rec.update({'tokens_in': tokens.get('in'), 'tokens_out': tokens.get('out'),
                            'tokens_total': tokens.get('total')})
            _log(rec)
            return {'text': text, 'channel': ch, 'model': model, 'ms': ms, 'tried': tried,
                    'tokens': tokens}
        except Exception as e:                                  # канал впав — наступний
            tried.append(f'{ch}:{type(e).__name__}')
            _down[ch] = time.time() + COOLDOWN
            _log({'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'channel': ch, 'error': str(e)[:200],
                  'task': task})

    if escalate_to_codex:
        t0 = time.time()
        try:
            text, model = call_codex(prompt, image_path=image_path, timeout=max(timeout, 180))
            if len(text) < min_len:
                raise RuntimeError(f'відповідь коротша за {min_len} символів')
            ms = int((time.time() - t0) * 1000)
            rec = {'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'channel': 'codex', 'model': model,
                  'ms': ms, 'prompt_len': len(prompt), 'text_len': len(text),
                  'task': task, 'tried': tried}
            _log(rec)
            return {'text': text, 'channel': 'codex', 'model': model, 'ms': ms,
                    'tried': tried, 'tokens': None}
        except Exception as e:
            tried.append(f'codex:{type(e).__name__}')
            _log({'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'channel': 'codex',
                  'error': str(e)[:200], 'task': task})

    raise RuntimeError(f'усі канали недоступні: {tried}')


def selftest(prompt=None):
    """Справжній запит у кожен канал окремо. Каталогам не віримо."""
    prompt = prompt or 'Відповідай українською одним коротким реченням: що таке гель-лубрикант?'
    out = []
    for ch in CHAIN:
        t0 = time.time()
        try:
            text, model = (call_gemini(prompt, 90) if ch == 'gemini'
                           else call_omniroute(prompt, 90) if ch == 'omniroute'
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
