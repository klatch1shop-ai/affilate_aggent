#!/usr/bin/env python3
"""Передача задачі безкоштовній моделі з автоматичним прийманням за тестами.

Ідея власника (16.09.2026): великі, добре описані задачі віддавати
безкоштовному каналу (`shared/utils/llm_router.py`), а основна модель
приймає роботу. Тут це зроблено так, щоб приймання **не залежало від
вражень**: суддя — тести, написані замовником наперед.

Цикл:
  1. надіслати каналу завдання (маркдаун) і вимогу віддати один файл коду;
  2. витягти код з відповіді, записати у цільовий файл;
  3. ворота: синтаксис (`ast.parse`) → тести (`pytest`);
  4. якщо червоно — повернути моделі ПОМИЛКИ (не переказ, а вивід) і
     повторити, поки є спроби;
  5. написати звіт і зупинитись — далі перевіряє основна модель.

Навмисні обмеження:
  * пише **лише** у файл, названий у `--target`, і не перезаписує наявний
    без `--allow-overwrite` (правило AGENT_RULES про чужий код);
  * тести не редагуються ніколи — ні моделлю, ні цим скриптом;
  * увесь обмін пишеться в `logs/llm_delegate/<задача>/`, щоб було видно,
    що саме модель відповідала, а не лише підсумок.

    venv/bin/python tools/llm_delegate.py \\
        --task docs/tasks/TASK-01-voice-intents.md \\
        --target tg_dispatcher/ai_brain/intents.py \\
        --tests tests/test_voice_intents.py --rounds 4
"""
import argparse
import ast
import datetime
import os
import re
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from shared.utils.llm_router import ask  # noqa: E402
import shared.utils.llm_router as _router  # noqa: E402

CODE_BLOCK = re.compile(r'```(?:python|py)?\s*\n(.*?)```', re.S)

FIRST = """Ти пишеш промисловий код на Python 3.13 для робочої системи.

Нижче — технічне завдання. Виконай його ПОВНІСТЮ і поверни ОДИН файл коду.

Правила відповіді:
1. Поверни лише один блок ```python з повним вмістом файлу — без пояснень до і після.
2. Жодних заглушок, TODO чи прикладів використання поза файлом.
3. Лише стандартна бібліотека.
4. Коментарі й docstring українською.

=== ТЕХНІЧНЕ ЗАВДАННЯ ===
{task}
=== КІНЕЦЬ ЗАВДАННЯ ===

Файл: {target}
"""

RETRY = """Твій код не пройшов приймальні тести. Виправ і поверни ПОВНИЙ файл заново.

Тести змінювати не можна — вони умова приймання.

=== ЩО НЕ ТАК ===
{errors}
=== КІНЕЦЬ ===

Нагадування завдання:
{task_short}

Поверни лише один блок ```python з повним вмістом файлу {target}.
"""


def extract_code(text):
    blocks = CODE_BLOCK.findall(text or '')
    if blocks:
        return max(blocks, key=len).strip()
    # модель могла віддати код без огорожі — беремо, якщо це взагалі Python
    t = (text or '').strip()
    try:
        ast.parse(t)
        return t
    except SyntaxError:
        return None


def run_tests(tests, timeout=180):
    r = subprocess.run([os.path.join(BASE, 'venv', 'bin', 'python'), '-m', 'pytest', tests,
                        '-q', '--no-header', '-x' if False else '--tb=short'],
                       cwd=BASE, capture_output=True, text=True, timeout=timeout)
    return r.returncode == 0, (r.stdout + r.stderr)[-4000:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task', required=True)
    ap.add_argument('--target', required=True)
    ap.add_argument('--tests', required=True)
    ap.add_argument('--rounds', type=int, default=4)
    ap.add_argument('--channel', default='omniroute')
    ap.add_argument('--timeout', type=int, default=900)
    ap.add_argument('--allow-overwrite', action='store_true')
    a = ap.parse_args()

    task_path = os.path.join(BASE, a.task)
    target = os.path.join(BASE, a.target)
    task = open(task_path, encoding='utf-8').read()
    name = os.path.splitext(os.path.basename(task_path))[0]
    logdir = os.path.join(BASE, 'logs', 'llm_delegate', name)
    os.makedirs(logdir, exist_ok=True)

    if os.path.exists(target) and not a.allow_overwrite:
        sys.exit(f'{a.target} вже існує — потрібен --allow-overwrite і резервна копія')

    prompt = FIRST.format(task=task, target=a.target)
    best = {'passed': -1, 'code': None, 'round': None, 'tail': ''}
    history = []
    t_start = time.time()
    for rnd in range(1, a.rounds + 1):
        print(f'\n=== коло {rnd}/{a.rounds} · канал {a.channel}', flush=True)
        _router._down.clear()      # пауза після збою не має з'їдати наступні кола
        t0 = time.time()
        out = None
        for attempt in range(1, 4):          # мережевий збій не має ховати коло:
            try:                              # безкоштовні провайдери часто відмовляють
                _router._down.clear()         # пауза стосується запиту, а не спроби
                out = ask(prompt, task='code', chain=[a.channel], timeout=a.timeout, min_len=200)
                break
            except Exception as e:
                print(f'  спроба {attempt}/3 не вдалась: {type(e).__name__}: {str(e)[:90]}',
                      flush=True)
                last = e
                time.sleep(30 * attempt)
        if out is None:
            history.append({'round': rnd, 'error': str(last)[:200]})
            continue
        secs = round(time.time() - t0)
        open(os.path.join(logdir, f'round{rnd}_answer.md'), 'w', encoding='utf-8').write(out['text'])
        code = extract_code(out['text'])
        if not code:
            errors = 'У відповіді немає блоку коду ```python з повним файлом.'
            print(f'  {secs} с · {out["model"]} · коду немає')
        else:
            try:
                ast.parse(code)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                open(target, 'w', encoding='utf-8').write(code.rstrip() + '\n')
                ok, log = run_tests(os.path.join(BASE, a.tests))
                tail = log.strip().splitlines()[-1] if log.strip() else ''
                m = re.search(r'(\d+) passed', tail)
                passed = int(m.group(1)) if m else 0
                if passed >= best['passed']:
                    best.update(passed=passed, code=code, round=rnd, tail=tail)
                else:                          # відкат: не віддаємо гірший файл
                    open(target, 'w', encoding='utf-8').write(best['code'].rstrip() + '\n')
                    print(f'  коло {rnd} гірше ({passed} проти {best["passed"]}) — лишаю краще')
                print(f'  {secs} с · {out["model"]} · {len(code)} символів · тести: {tail}')
                history.append({'round': rnd, 'model': out['model'], 'secs': secs,
                                'chars': len(code), 'passed': ok, 'tail': tail})
                if ok:
                    report(logdir, name, a, history, True, time.time() - t_start, log)
                    print('\n✅ тести зелені. Передаю основній моделі на перевірку.')
                    return 0
                errors = log
            except SyntaxError as e:
                errors = f'Файл не парситься: {e}'
                print(f'  {secs} с · синтаксична помилка: {e}')
                history.append({'round': rnd, 'model': out['model'], 'secs': secs,
                                'passed': False, 'tail': f'SyntaxError: {e}'})
        open(os.path.join(logdir, f'round{rnd}_errors.txt'), 'w', encoding='utf-8').write(str(errors))
        fails = '\n'.join(l for l in str(errors).splitlines()
                           if 'AssertionError' in l or l.startswith('FAILED'))[-1200:]
        prompt = RETRY.format(errors=fails or str(errors)[-1200:], target=a.target,
                              task_short=task[:1500])
    report(logdir, name, a, history, False, time.time() - t_start,
           'останнє коло не пройшло тести')
    print('\n⚠️ тести не зелені після всіх кіл. Передаю основній моделі на перевірку.')
    return 1


def report(logdir, name, a, history, ok, secs, log):
    lines = [f'# Звіт делегування: {name}', '',
             f'- **Завдання:** `{a.task}`', f'- **Цільовий файл:** `{a.target}`',
             f'- **Тести:** `{a.tests}` (замовника, не редагувались)',
             f'- **Канал:** {a.channel}', f'- **Кіл:** {len(history)} з {a.rounds}',
             f'- **Загальний час:** {secs / 60:.1f} хв',
             f'- **Підсумок:** {"✅ тести зелені" if ok else "⚠️ тести не зелені"}',
             '', '| коло | модель | с | символів | тести |', '|---|---|---|---|---|']
    for h in history:
        lines.append(f"| {h.get('round')} | {h.get('model', '—')} | {h.get('secs', '—')} | "
                     f"{h.get('chars', '—')} | {h.get('tail', h.get('error', '—'))[:70]} |")
    lines += ['', '## Останній вивід тестів', '', '```', str(log)[-2500:], '```', '',
              '## Що робить основна модель далі', '',
              '1. Читає код очима: межі, регулярні вирази, чи не підігнано під тести.',
              '2. Перевіряє фрази, яких у тестах немає.',
              '3. Вирішує, чи вбудовувати в бот, і робить це сама.']
    path = os.path.join(os.path.dirname(os.path.join(BASE, a.task)), f'{name}-REPORT.md')
    open(path, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print(f'звіт: {os.path.relpath(path, BASE)} · обмін: {os.path.relpath(logdir, BASE)}')


if __name__ == '__main__':
    sys.exit(main())
