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
    """Одна задача = одне фото. Дрібні задачі переживають обрив краще за великі."""
    tasks = []
    for card in load_cards():
        for index, url in enumerate(card['pictures']):
            tasks.append({'key': f"{card['article']}#{index}", 'kind': 'photo',
                          'payload': {'article': card['article'], 'index': index,
                                      'url': url, 'name': card['name']}})
    return queue.add_many(tasks)


def run_one(task, retries=2):
    """Одне фото через пул. Другого джерела тут НЕ беремо: фото вміє читати
    лише openrouter (заміри 26.09), тож чесніше записати одне джерело, ніж
    вдавати перевірку другим, який на фото каже «НЕ ВИДНО».

    Повтор саме на порожню відповідь: у прогоні 26.09 це 8 із 11 збоїв, і
    вона минуща — те саме фото з другої спроби читається нормально.
    """
    payload = task['payload']
    for attempt in range(retries + 1):
        text, vendor, errors = vp.first_ok(
            ['openrouter'], QUESTION, image_url=payload['url'], timeout=120, max_tokens=400)
        if text or not any('порожня' in e for e in errors):
            break
        time.sleep(2 * (attempt + 1))
    if not text:
        return task['key'], {'error': '; '.join(errors)[:200]}
    answer = parse_answer(text)
    if answer is None:
        return task['key'], {'error': f'нерозбірлива відповідь: {text[:120]}',
                             'vendor_a': vendor}
    return task['key'], {'vendor_a': vendor, 'answer_a': json.dumps(answer, ensure_ascii=False),
                         'verdict': 'придатне' if is_good_first_photo(answer) else 'непридатне'}


def run(queue, limit, workers=4, chunk=None):
    """Бере задачі ПОРЦІЯМИ, а не всі одразу.

    26.09: `take(600)` позначив «в роботі» всі 600, і обрив процесу лишив 584
    завислими. Черга їх повертає за строком, але правильніше не створювати
    такого боргу: порція = кілька робітників, тож обрив коштує одиниць роботи.
    """
    chunk = chunk or max(workers * 2, 4)
    done = 0
    while done < limit:
        tasks = queue.take(min(chunk, limit - done), kind='photo')
        if not tasks:
            break
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for key, result in pool.map(run_one, tasks):
                queue.finish(key, **result)
                done += 1
                mark = '✗' if result.get('error') else ('✅' if result.get('verdict') == 'придатне' else '⬜')
                print(f'  {mark} {key}', flush=True)
    if not done:
        print('нових задач немає')
    return done


def report(queue):
    rows = queue._conn.execute(
        'SELECT key, payload, verdict, answer_a, error FROM tasks WHERE state = ?',
        (DONE,)).fetchall()
    by_card = {}
    for row in rows:
        payload = json.loads(row['payload'])
        card = by_card.setdefault(payload['article'], {'name': payload['name'], 'photos': {}})
        card['photos'][payload['index']] = {'verdict': row['verdict'], 'url': payload['url'],
                                            'answer': row['answer_a']}
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['article', 'name', 'перше_фото_придатне', 'пропонований_індекс',
                         'пропоноване_фото', 'усього_фото', 'опис_поточного'])
        for article, card in sorted(by_card.items()):
            photos = card['photos']
            first = photos.get(0) or {}
            good = [i for i in sorted(photos) if photos[i]['verdict'] == 'придатне']
            suggest = next((i for i in good if i != 0), None)
            writer.writerow([article, card['name'],
                             'так' if first.get('verdict') == 'придатне' else 'ні',
                             '' if first.get('verdict') == 'придатне' else (suggest if suggest is not None else 'НЕМАЄ ПРИДАТНОГО'),
                             '' if first.get('verdict') == 'придатне' or suggest is None else photos[suggest]['url'],
                             len(photos), (first.get('answer') or '')[:200]])
    print(f'карток у звіті: {len(by_card)} → {REPORT}')


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
