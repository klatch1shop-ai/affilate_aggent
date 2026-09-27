"""Друга думка для рядків Епіцентру, де «перевірка» була самопідтвердженням.

Причина (26.09.2026): прогін заповнення атрибутів дав 3357 рядків, але в 2233
з них обидві «незалежні» відповіді дала ОДНА модель — коли Gemini вичерпував
добову квоту, обидва запити падали на Codex, і навпаки. Чесно перевірених
лише 141.

Тепер, коли Gemini оплачений (без добової стелі, ~1.5 с на запит), друга
думка коштує копійки: ~1220 токенів на рядок із фото.

Правило добору: питаємо вендора, ЯКОГО В ЦЬОМУ РЯДКУ ЩЕ НЕ БУЛО. Інакше
повторимо ту саму помилку, лише дорожче.

    venv/bin/python tools/epicentr_reverify.py --fill
    venv/bin/python tools/epicentr_reverify.py --run 200
    venv/bin/python tools/epicentr_reverify.py --report
"""
import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

from shared.utils import vendor_pool as vp                          # noqa: E402
from shared.utils.task_queue import TaskQueue, DONE                 # noqa: E402

QUEUE_DB = os.path.join(BASE, 'data', 'tasks', 'epicentr_reverify.db')
PROGRESS = os.path.join(BASE, 'scratchpad', 'fill_gaps_all_progress.json')
REPORT = os.path.join(BASE, 'exports', 'epicentr_reverify.csv')

# Кого питати другим, якщо перший був таким.
# 27.09: власник лишив із платних лише Gemini. Безкоштовні відпадають —
# OpenRouter дає 50/добу, Codex не відповідає за 90 с. Тому для рядків, де
# першим уже був Gemini, беремо ІНШУ МОДЕЛЬ Gemini: це слабша перевірка
# (спільний тренувальний матеріал = спільні помилки), і вона отримує окрему
# назву вердикту, щоб ніколи не злитись із перевіркою двома вендорами.
SECOND = {'codex': ['gemini'], None: ['gemini']}
GEMINI_SECOND_MODEL = os.getenv('GEMINI_SECOND_MODEL', 'gemini-flash-latest')


def question(attr, name):
    return (f'Товар: {name}\n\nНа фото цей товар. Визнач характеристику «{attr}» САМОГО ВИРОБУ '
            f'(не упаковки, не фону). Відповідай коротко, українською, ЛИШЕ значення. '
            f'Якщо визначити неможливо — НЕ ВИДНО.')


def load_rows():
    with open(PROGRESS, encoding='utf-8') as f:
        state = json.load(f)
    out = []
    for row in state.get('rows') or []:
        if row.get('verdict') == 'помилка запиту':
            continue                            # там немає що перевіряти
        src_photo, src_text = row.get('src_photo'), row.get('src_text')
        if src_photo and src_text and src_photo != src_text:
            continue                            # уже чесно перевірено
        if not row.get('url'):
            continue                            # без фото друга думка неможлива
        out.append(row)
    return out


def fill(queue):
    tasks = []
    for row in load_rows():
        used = row.get('src_photo') or row.get('src_text')
        tasks.append({'key': f"{row.get('sku')}|{row.get('attr')}", 'kind': 'attr',
                      'payload': {'sku': row.get('sku'), 'attr': row.get('attr'),
                                  'url': row.get('url'), 'used': used,
                                  'photo': row.get('photo'), 'text': row.get('text')}})
    return queue.add_many(tasks)


def run_one(task):
    payload = task['payload']
    candidates = SECOND.get(payload.get('used'), ['gemini'])
    answer, vendor, errors = vp.first_ok(
        candidates, question(payload['attr'], payload.get('sku') or ''),
        image_url=payload['url'], timeout=120, max_tokens=300)
    if not answer:
        # НЕ обрізаємо до першої помилки: 26.09 обрізання до 200 символів
        # сховало, що другий кандидат теж упав, і виглядало, ніби його не питали
        return task['key'], {'error': ' | '.join(e[:90] for e in errors)[:400]}
    first = (payload.get('photo') or payload.get('text') or '').strip()
    return task['key'], {
        'vendor_a': payload.get('used'), 'vendor_b': vendor,
        'answer_a': first, 'answer_b': answer.strip(),
        'verdict': vp.verdict(first, answer.strip(), payload.get('used'), vendor),
    }


def run(queue, limit, workers=4):
    chunk = max(workers * 2, 4)
    done = 0
    while done < limit:
        tasks = queue.take(min(chunk, limit - done), kind='attr')
        if not tasks:
            break
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for key, result in pool.map(run_one, tasks):
                queue.finish(key, **result)
                done += 1
                mark = '✗' if result.get('error') else ('✅' if result.get('verdict') == vp.AGREE else '⬜')
                print(f'  {mark} {key} {result.get("verdict", "")}', flush=True)
    return done


def report(queue):
    rows = queue._conn.execute(
        'SELECT key, vendor_a, vendor_b, answer_a, answer_b, verdict, error'
        ' FROM tasks WHERE state IN (?, ?)', (DONE, 'збій')).fetchall()
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    counts = {}
    with open(REPORT, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['sku', 'характеристика', 'перше_джерело', 'перша_відповідь',
                         'друге_джерело', 'друга_відповідь', 'вердикт'])
        for row in rows:
            sku, _, attr = (row['key'] or '').partition('|')
            verdict = row['verdict'] or 'ПОМИЛКА'
            counts[verdict] = counts.get(verdict, 0) + 1
            writer.writerow([sku, attr, row['vendor_a'], row['answer_a'],
                             row['vendor_b'], row['answer_b'], verdict])
    for verdict, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f'  {n:>5}  {verdict}')
    print(f'→ {REPORT}')


def export_map(queue, out_path, min_verdict='ЗБІГ'):
    """Значення, ГОТОВІ до відправки, у форматі epicentr_attr_fill_multi.

    Беремо лише `ЗБІГ` — це два РІЗНІ вендори, що сказали те саме. Решта
    свідомо не йде: `РОЗБІЖНІСТЬ` потребує людини, `лише одне джерело` не
    перевірено, `обидва не знають` — порожньо. Відправляти неперевірене на
    модерацію ми вже пробували 21.09 і отримали по руках.
    """
    rows = queue._conn.execute(
        'SELECT key, answer_b, verdict FROM tasks WHERE state = ? AND verdict = ?',
        (DONE, min_verdict)).fetchall()
    out = {}
    skipped = 0
    for row in rows:
        sku, _, attr = (row['key'] or '').partition('|')
        value = (row['answer_b'] or '').strip()
        if not sku or not attr or not value or vp.is_unknown(value):
            skipped += 1
            continue
        out.setdefault(sku, {})[attr] = value
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    values = sum(len(v) for v in out.values())
    print(f'готових до відправки: {values} значень у {len(out)} картках'
          f' (пропущено порожніх/невідомих: {skipped})')
    print(f'→ {out_path}')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fill', action='store_true')
    ap.add_argument('--run', type=int)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--export', metavar='FILE', help='мапа {sku: {атрибут: значення}} лише зі ЗБІГів')
    a = ap.parse_args()
    queue = TaskQueue(QUEUE_DB)
    queue.requeue_stale()
    if a.fill:
        print(f'додано задач: {fill(queue)}')
    if a.run:
        print(f'оброблено: {run(queue, a.run, a.workers)}')
    if a.report:
        report(queue)
    if a.export:
        export_map(queue, a.export)
    print('стан черги:', queue.counts())


if __name__ == '__main__':
    main()
