#!/usr/bin/env python3
"""Обговорення рішення кількома моделями в раундах, із збереженням стенограми.

Задум власника (28.09): не разове питання, а **постійне обговорення** —
подивитись, до чого моделі дійдуть, коли побачать заперечення одна одної.

Порядок раундів навмисно такий:

1. **Незалежний** — кожен відповідає, не бачачи інших. Це зберігає дві
   справді окремі думки (правило скіла `asking-experts`: показати відповідь
   одного іншому означає втратити другу думку).
2. **Перехресний** — кожному показують чужі відповіді знеособлено («учасник
   А», «учасник Б») і просять знайти помилку та змінити свою позицію, якщо
   аргумент сильніший. Знеособлено, щоб не спрацювала повага до бренду.
3. **Зведення** — кожен формулює остаточну позицію одним абзацом.

Стенограма пишеться повністю: цінне не лише рішення, а й те, ЧИ і ЧОМУ
учасник змінив думку.

    python3 tools/deliberate.py --question q.txt --vendors gemini,codex
"""
import argparse
import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from shared.utils import vendor_pool  # noqa: E402

OUT_DIR = os.path.join(BASE, 'docs', 'research', 'deliberations')

R0 = """Це НУЛЬОВИЙ раунд. Рішень не пропонувати — їх відкинуть.

Твоє єдине завдання: знайти хибну передумову в самому питанні.

1. Випиши ВСІ фактичні твердження, на яких тримається питання, окремим списком.
2. Для кожного познач: чим воно підтверджене — «джерело в питанні», «загальновідоме»
   або «НЕ ПЕРЕВІРЕНО».
2а. ОКРЕМО для кожного ЧИСЛА: чим його виміряно і що сталося б, якби сам
   вимірювач був зламаний? Назви, яке хибне число дав би зіпсований
   інструмент і чим воно відрізнялось би від наведеного. Числа в питанні —
   найчастіше джерело хибних висновків: 02-03.10 шість чисел поспіль
   виявились артефактами інструментів, і обговорення цього не спіймало,
   бо числа приходять ззовні й виглядають як вимір.
3. Для кожного «НЕ ПЕРЕВІРЕНО» скажи, яка перевірка його підтвердила б або спростувала.
4. Назви одну передумову, яка найімовірніше хибна, і поясни, що тоді розсиплеться.
5. Окремо дай відповідь на питання: «а чи там ми взагалі дивимось?» — чи не може
   предмет перевірки перебувати в іншому середовищі, ніж те, про яке йдеться.

Якщо хибних передумов не бачиш — так і напиши, але спершу пройди всі пʼять пунктів.

ПИТАННЯ:
{question}"""

R2 = """Нижче — відповіді інших учасників на те саме питання. Вони знеособлені навмисно.

{others}

--- ТВОЯ ПОПЕРЕДНЯ ВІДПОВІДЬ ---
{mine}

Завдання:
1. Назви конкретну помилку або пропущений ризик у кожній чужій відповіді. Якщо помилки немає — так і скажи, не вигадуй.
2. Назви найсильніший чужий аргумент, якого не було в тебе.
3. Скажи прямо, чи змінюєш свою позицію і в чому саме. «Не змінюю» — теж відповідь, але з обґрунтуванням.

Питання, на яке всі відповідали:
{question}"""

R3 = """Це завершальний раунд. Сформулюй остаточну позицію.

Вимоги: одна рекомендація, а не перелік варіантів; що саме робити першим; одне число-критерій, за яким буде видно, що рішення хибне; і чесно — де воно зламається.

Не більше 200 слів. Без вступів.

Питання: {question}"""


def ask(vendor, prompt, timeout, max_tokens):
    try:
        text = vendor_pool.call(vendor, prompt, timeout=timeout, max_tokens=max_tokens)
        return text or '(порожня відповідь)'
    except Exception as exc:
        return f'(збій: {type(exc).__name__}: {str(exc)[:200]})'


def _save(log):
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M')
    path = os.path.join(OUT_DIR, f'{stamp}.json')
    json.dump(log, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('стенограма:', path)


def warn_unmeasured(question):
    """Числа без опису методу — головне джерело хибних колових висновків.

    03.10 учасники двічі побудували впевнені висновки на моєму «13 % видимих
    карток», яке виявилось артефактом скрейпера, що читав одну сторінку.
    Тому питання має казати, ЯК виміряно кожне число.
    """
    import re as _re
    numbers = _re.findall(r'\b\d[\d\s.,]*\s*%|\b\d{2,}\b', question)
    hints = ('виміряно', 'замір', 'заміряно', 'джерело', 'перевірено',
             'з API', 'з бази', 'вручну', 'інструмент')
    if numbers and not any(h in question for h in hints):
        print('УВАГА: у питанні є числа, але не сказано, ЯК вони виміряні.\n'
              '       Учасники міркуватимуть на них як на фактах. Додай до\n'
              '       кожного числа джерело й метод — див. скіл\n'
              '       measuring-before-reporting.\n', flush=True)


def run(question, vendors, timeout=600, max_tokens=2500):
    warn_unmeasured(question)
    log = {'question': question, 'started': datetime.datetime.now().isoformat(timespec='seconds'),
           'vendors': vendors, 'rounds': []}

    # Нульовий раунд: атака на передумови. Додано 29.09.2026 після випадку,
    # коли трьом моделям дали хибний висновок і попросили оцінити лист — усі
    # троє обговорювали формулювання, жоден не спитав, чи правда те, що в
    # основі. Усі три незалежно порадили саме цей раунд як виправлення.
    r0 = {v: ask(v, R0.format(question=question), timeout, max_tokens) for v in vendors}
    log['rounds'].append({'name': 'атака на передумови', 'answers': r0})
    doubts = sum(1 for a in r0.values()
                 if 'НЕ ПЕРЕВІРЕНО' in a or 'хибн' in a.lower())
    log['premise_doubts'] = doubts
    print(f'раунд 0: сумнівів у передумовах висловили {doubts} з {len(vendors)}', flush=True)
    if doubts == 0:
        print('УВАГА: жоден не засумнівався в передумовах — імовірно, вони просто '
              'погодились із питанням. Ставитись до підсумку з обережністю.', flush=True)

    r1 = {v: ask(v, question, timeout, max_tokens) for v in vendors}
    log['rounds'].append({'name': 'незалежний', 'answers': r1})

    # Учасник, який не відповів, вибуває: інакше в перехресному раунді решта
    # критикуватиме повідомлення про збій і видаватиме це за другу думку.
    alive = [v for v in vendors if not r1[v].startswith('(збій')]
    log['failed'] = [v for v in vendors if v not in alive]
    print(f'раунд 1: відповіли {alive}, вибули {log["failed"]}', flush=True)
    if len(alive) < 2:
        log['verdict'] = ('ОБГОВОРЕННЯ НЕ ВІДБУЛОСЬ: лишився один учасник, '
                          'це одна думка, а не збіг двох')
        print(log['verdict'], flush=True)
        _save(log)
        return log
    vendors = alive

    r2 = {}
    for v in vendors:
        others = '\n\n'.join(
            f'--- УЧАСНИК {chr(65 + n)} ---\n{r1[o]}'
            for n, o in enumerate(x for x in vendors if x != v))
        r2[v] = ask(v, R2.format(others=others, mine=r1[v], question=question), timeout, max_tokens)
    log['rounds'].append({'name': 'перехресний', 'answers': r2})
    print('раунд 2 готовий', flush=True)

    r3 = {v: ask(v, R3.format(question=question) + '\n\nТвоя позиція після обговорення:\n' + r2[v],
                 timeout, 900) for v in vendors}
    log['rounds'].append({'name': 'зведення', 'answers': r3})
    print('раунд 3 готовий', flush=True)

    _save(log)
    return log


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--question', required=True, help='файл із питанням')
    ap.add_argument('--vendors', default='gemini,codex')
    ap.add_argument('--timeout', type=int, default=600)
    args = ap.parse_args()
    run(open(args.question, encoding='utf-8').read(), args.vendors.split(','), args.timeout)
