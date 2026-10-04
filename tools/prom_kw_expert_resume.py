#!/usr/bin/env python3
"""Відновлюваний прогін експертних ключів: переживає вичерпання ліміту.

Навіщо: Codex дає ~22 с на картку при трьох потоках, тож 968 карток це
близько 6 годин — більше за 5-годинний ліміт підписки. Ліміт оновлюється
сам, тому прогін має не падати, а ЧЕКАТИ й продовжувати з того ж місця.

Залишок ліміту ззовні НЕ ВИДНО: у `codex-cli 0.155.1` команди статусу немає
(перевірено 03.10.2026). Тому вичерпання впізнається з тексту помилки, а не
питається наперед.

Черга лежить у репозиторії, не в /tmp: вартовий у /tmp зник при вимкненні
ноутбука — на цьому вже наступали.

Кожна картка фіксується ОДРАЗУ після відповіді. Обрив втрачає одну картку,
а не години роботи.

    venv/bin/python3 tools/prom_kw_expert_resume.py --category "БДСМ-игрушки" --vendor codex
    # повторний запуск продовжує з місця зупинки
"""
import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from tools.prom_kw_expert import ask, validate, is_exhausted  # noqa: E402

QUEUE_DIR = os.path.join(BASE, 'data', 'kw_queue')
WAIT_MINUTES = 20
# Картка, що впала стільки разів, вибуває назавжди. Без цього прогін
# крутився по колу на тих самих 48 картках, бо `todo` рахувався лише за
# зробленими, а невдалі лишались у черзі вічно.
MAX_RETRIES = 2


def qpath(category):
    os.makedirs(QUEUE_DIR, exist_ok=True)
    safe = category.replace(' ', '_').replace('/', '_')
    return os.path.join(QUEUE_DIR, f'{safe}.json')


def load_queue(category):
    p = qpath(category)
    if os.path.exists(p):
        return json.load(open(p, encoding='utf-8'))
    return {'category': category, 'cards': {}, 'failed': {}}


def save_queue(category, q):
    tmp = qpath(category) + '.tmp'
    json.dump(q, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, qpath(category))      # атомарно: обрив не псує файл


def main(category, vendor, workers, feed):
    import collections
    offers = list(ET.parse(feed).getroot().iter('offer'))
    cats = json.load(open('/tmp/prom_cats.json', encoding='utf-8'))
    freq = {t: collections.Counter(
        k.strip().lower() for o in offers
        for k in (o.findtext(t) or '').split(',') if k.strip())
        for t in ('keywords', 'keywords_ua')}

    q = load_queue(category)
    q.setdefault('tries', {})

    def pending():
        return [o for o in offers
                if cats.get(o.get('id')) == category
                and o.get('id') not in q['cards']
                and q['tries'].get(o.get('id'), 0) < MAX_RETRIES]

    todo = pending()
    print(f'категорія «{category}»: зроблено {len(q["cards"])}, лишилось {len(todo)}',
          flush=True)
    if not todo:
        print('усе зроблено')
        return

    stop = {'exhausted': False}

    def one(o):
        if stop['exhausted']:
            return o.get('id'), None, None
        try:
            data = ask(o, category, vendor)
        except Exception as exc:
            if is_exhausted(exc):
                stop['exhausted'] = True
                print(f'  ЛІМІТ ВИЧЕРПАНО: {str(exc)[:100]}', flush=True)
                return o.get('id'), None, None
            return o.get('id'), None, str(exc)[:120]
        if not data:
            return o.get('id'), None, 'модель не повернула JSON'
        good, bad, drop = validate(o, data, freq)
        return o.get('id'), {'name': (o.findtext('name') or '')[:80],
                             'add': good, 'remove': drop,
                             'remove_suggested': data.get('remove') or [],
                             'from_photo': data.get('from_photo') or '',
                             'beyond': data.get('beyond_keywords') or '',
                             'vendor': vendor}, None

    done_now = 0
    while todo:
        stop['exhausted'] = False
        chunk = todo[:workers * 8]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for pid, row, err in pool.map(one, chunk):
                if row:
                    q['cards'][pid] = row
                    done_now += 1
                elif err:
                    q['failed'][pid] = err
                    q['tries'][pid] = q['tries'].get(pid, 0) + 1
        save_queue(category, q)          # фіксуємо ОДРАЗУ після пачки
        todo = pending()
        print(f'  зроблено {len(q["cards"])}, лишилось {len(todo)}', flush=True)
        if stop['exhausted'] and todo:
            print(f'  чекаю {WAIT_MINUTES} хв на оновлення ліміту…', flush=True)
            time.sleep(WAIT_MINUTES * 60)

    added = sum(len(v['add'][t]) for v in q['cards'].values()
                for t in ('keywords', 'keywords_ua'))
    print(f'\nготово: {len(q["cards"])} карток, ключів {added}, '
          f'збоїв {len(q["failed"])}')
    out = os.path.join(BASE, 'exports',
                       f'prom_kw_expert_{category.replace(" ", "_")}.json')
    json.dump({'category': category, 'cards': q['cards'], 'rejected': []},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('→', out)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--category', required=True)
    ap.add_argument('--vendor', choices=['gemini', 'codex'], default='codex')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--feed', default='/tmp/prom_live.xml')
    a = ap.parse_args()
    main(a.category, a.vendor, a.workers, a.feed)
