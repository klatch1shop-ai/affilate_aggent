"""Перевірка фото повернутих карток Rozetka через пул провайдерів.

Задача (26.09.2026): 756 карток повернуто з вимогою «перше фото — вид товару в
живу в повному розмірі спереду, зірочки заборонені». У фіді на картку 2–9 фото,
тож здебільшого це **перестановка**, а не пошук нових фото: треба знайти серед
наявних те, що вимогам відповідає.

Нічого не змінює. Складає список пропозицій на перевірку власником — картки
йдуть на повторну модерацію, а туди не можна з вигаданими значеннями.

    venv/bin/python tools/rozetka_photo_check.py --fill        # наповнити чергу
    venv/bin/python tools/rozetka_photo_check.py --run 50      # обробити 50
    venv/bin/python tools/rozetka_photo_check.py --report      # вивести CSV
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

from shared.utils import vendor_pool as vp                         # noqa: E402
from shared.utils.task_queue import TaskQueue, DONE                # noqa: E402

QUEUE_DB = os.path.join(BASE, 'data', 'tasks', 'rozetka_photo.db')
FEED = os.path.join(BASE, 'output', 'noire_rozetka.xml')
HIDDEN = os.path.join(BASE, 'exports', 'rz_hidden.json')
REPORT = os.path.join(BASE, 'exports', 'rozetka_photo_check.csv')

QUESTION = (
    'Це фото товару для інтернет-магазину. Відповідь СТРОГО у форматі JSON, без пояснень:\n'
    '{"товар_видно_повністю": true/false, "вид_спереду": true/false, '
    '"є_цензурні_зірочки_або_заклейки": true/false, "це_таблиця_або_схема": true/false, '
    '"що_на_фото": "коротко українською"}\n'
    'Зірочки/заклейки — графічні наліпки, що закривають частину тіла.'
)


def parse_answer(text):
    """JSON із відповіді моделі. Модель любить обгортати його в ```json."""
    if not text:
        return None
    cleaned = re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except ValueError:
        return None


def is_good_first_photo(answer):
    """Чи годиться це фото головним — за вимогами модератора."""
    if not answer:
        return False
    return bool(answer.get('товар_видно_повністю')) and bool(answer.get('вид_спереду')) \
        and not answer.get('є_цензурні_зірочки_або_заклейки') \
        and not answer.get('це_таблиця_або_схема')


def load_cards():
    """Повернуті картки з вимогою по фото + їхні фото з фіду."""
    with open(HIDDEN, encoding='utf-8') as f:
        hidden = json.load(f)
    need = {i['article']: (i.get('comment') or '') for i in hidden
            if i.get('article') and 'фото' in (i.get('comment') or '').lower()}
    with open(FEED, encoding='utf-8', errors='replace') as f:
        feed = f.read()
    cards = []
    for m in re.finditer(r'<offer\b[^>]*>(.*?)</offer>', feed, re.DOTALL):
        offer = m.group(1)
        art = re.search(r'<article>(.*?)</article>', offer)
        if not art or art.group(1) not in need:
            continue
        pics = [p.strip() for p in re.findall(r'<picture>(.*?)</picture>', offer)]
        name = re.search(r'<name_ua>(.*?)</name_ua>', offer, re.DOTALL)
        if pics:
            cards.append({'article': art.group(1), 'name': name.group(1).strip() if name else '',
                          'pictures': pics, 'comment': need[art.group(1)]})
    return cards


def fill(queue):
    """Одна задача = одна КАРТКА з усіма її фото.

    Спершу було по задачі на фото — це перевіряло всі 3955 фото наосліп.
    Але питання стоїть інакше: «чи придатне перше фото, а якщо ні — яке з
    решти його замінить». Отже фото перевіряються по черзі й перевірка
    спиняється на першому придатному. Заміряно: придатних ~24%, у картці
    в середньому 5.2 фото, тож рання зупинка знімає близько третини запитів.
    """
    tasks = [{'key': card['article'], 'kind': 'card',
              'payload': {'article': card['article'], 'name': card['name'],
                          'pictures': card['pictures']}}
             for card in load_cards()]
    return queue.add_many(tasks)


VENDORS = [v.strip() for v in os.getenv('PHOTO_VENDORS', 'gemini').split(',') if v.strip()]


def ask_photo(url, retries=2):
    """Одне фото. Повтор саме на порожню відповідь: у прогоні 26.09 це 8 із 11
    збоїв, і вона минуща — те саме фото з другої спроби читається нормально."""
    for attempt in range(retries + 1):
        text, vendor, errors = vp.first_ok(
            VENDORS, QUESTION, image_url=url, timeout=120, max_tokens=400)
        if text or not any('порожня' in e for e in errors):
            break
        time.sleep(2 * (attempt + 1))
    if not text:
        return None, None, '; '.join(errors)[:200]
    return parse_answer(text), vendor, None


def run_one(task):
    """Картка: перевіряємо фото по черзі й СПИНЯЄМОСЬ на першому придатному.

    Обсяг тягне gemini: після оплати (26.09) він відповідає за ~1.5 с без
    добової стелі, тоді як безкоштовний openrouter дає 50 запитів на добу.
    Тому openrouter тут НЕ другим джерелом на кожен рядок — його мало, —
    а окремою вибіркою для контролю якості. Вдавати, що кожен рядок
    перевірено двома, коли другого вистачає на 1%, було б тією самою
    брехнею, проти якої написано vendor_pool.
    """
    payload = task['payload']
    seen, vendor_used, first_error = {}, None, None
    good_index = None
    for index, url in enumerate(payload['pictures']):
        answer, vendor, error = ask_photo(url)
        if error:
            first_error = first_error or error
            continue
        vendor_used = vendor_used or vendor
        seen[index] = answer
        if is_good_first_photo(answer):
            good_index = index
            break                      # далі не питаємо — заміну вже знайдено
    if not seen:
        return task['key'], {'error': first_error or 'жодне фото не прочитано'}
    result = {'article': payload['article'], 'name': payload['name'],
              'перевірено_фото': len(seen), 'усього_фото': len(payload['pictures']),
              'придатний_індекс': good_index,
              'фото': {str(i): a for i, a in seen.items()}}
    if good_index == 0:
        verdict = 'перше фото придатне'
    elif good_index is not None:
        verdict = f'замінити першим фото №{good_index}'
        result['пропоноване_фото'] = payload['pictures'][good_index]
    else:
        verdict = 'немає придатного фото'
    return task['key'], {'vendor_a': vendor_used, 'verdict': verdict,
                         'answer_a': json.dumps(result, ensure_ascii=False)}


def run(queue, limit, workers=4, chunk=None):
    """Бере задачі ПОРЦІЯМИ, а не всі одразу.

    26.09: `take(600)` позначив «в роботі» всі 600, і обрив процесу лишив 584
    завислими. Черга їх повертає за строком, але правильніше не створювати
    такого боргу: порція = кілька робітників, тож обрив коштує одиниць роботи.
    """
    chunk = chunk or max(workers * 2, 4)
    done = 0
    while done < limit:
        tasks = queue.take(min(chunk, limit - done), kind='card')
        if not tasks:
            break
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for key, result in pool.map(run_one, tasks):
                queue.finish(key, **result)
                done += 1
                mark = '✗' if result.get('error') else ('✅' if result.get('verdict') == 'перше фото придатне' else '⬜')
                print(f'  {mark} {key}', flush=True)
    if not done:
        print('нових задач немає')
    return done


def report(queue):
    """CSV на перевірку власником: що з фото не так і чим його замінити."""
    rows = queue._conn.execute(
        "SELECT key, verdict, answer_a, error FROM tasks WHERE state IN ('готова','збій')").fetchall()
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    counts = {}
    with open(REPORT, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['article', 'name', 'вердикт', 'замінити_на_фото', 'посилання',
                         'перевірено_фото', 'усього_фото', 'що_на_першому_фото'])
        for row in sorted(rows, key=lambda r: r['key']):
            if row['error']:
                writer.writerow([row['key'], '', 'ПОМИЛКА', '', '', '', '', row['error'][:150]])
                counts['ПОМИЛКА'] = counts.get('ПОМИЛКА', 0) + 1
                continue
            data = json.loads(row['answer_a'])
            first = (data.get('фото') or {}).get('0') or {}
            counts[row['verdict']] = counts.get(row['verdict'], 0) + 1
            writer.writerow([
                data.get('article'), data.get('name'), row['verdict'],
                data.get('придатний_індекс') if data.get('придатний_індекс') else '',
                data.get('пропоноване_фото', ''),
                data.get('перевірено_фото'), data.get('усього_фото'),
                first.get('що_на_фото', ''),
            ])
    for verdict, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f'  {n:>4}  {verdict}')
    print(f'→ {REPORT}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fill', action='store_true')
    ap.add_argument('--run', type=int, metavar='N')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--chunk', type=int, default=None)
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()

    queue = TaskQueue(QUEUE_DB)
    queue.requeue_stale()
    if a.fill:
        print(f'додано задач: {fill(queue)}')
    if a.run:
        print(f'оброблено: {run(queue, a.run, a.workers, a.chunk)}')
    if a.report:
        report(queue)
    print('стан черги:', queue.counts())


if __name__ == '__main__':
    main()
