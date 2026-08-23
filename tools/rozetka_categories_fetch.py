#!/usr/bin/env python3
"""Повний офіційний каталог категорій Rozetka → `docs/rozetka_categories_all.json`.

Навіщо. Досі джерелом істини для мапінгу TOPTUL був
`docs/rozetka_seller_categories.json` — **289 категорій, зібраних із каталогу
конкурента `ttul`**. Для 96 категорій TOPTUL (602 товари) відповідника в
ньому не знайшлось, і це очікувано: конкурент просто не возить газоаналізатори,
тепловізори чи повербанки. Нуль там був фактом про перелік конкурента, а не
про Rozetka — рівно та підміна, від якої застерігає правило позитивного
контролю.

Офіційний перелік дає `market-categories/search`: `category_id`, `name`,
`parent_id`, сторінками. Токен є ЛИШЕ на сервері (`ROZETKA_API_TOKEN` у
`.env`); на ноутбуці його немає, тому скрипт запускається на сервері.

Запуск:
    venv/bin/python3 tools/rozetka_categories_fetch.py
"""
import json
import os
import sys

import requests
import urllib3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
from loguru import logger  # noqa: E402

# Старий сервер із протухлим сертом — verify=False обовʼязково (CLAUDE.md).
urllib3.disable_warnings()

# З дефісом. Без дефіса домен не резолвиться взагалі (перевірено 23.08.2026).
API = 'https://api-seller.rozetka.com.ua/market-categories/search'
OUT = os.path.join(BASE_DIR, 'docs', 'rozetka_categories_all.json')


def fetch() -> list:
    tok = os.getenv('ROZETKA_API_TOKEN')
    if not tok:
        sys.exit('ROZETKA_API_TOKEN відсутній — запускати на сервері')
    head = {'Authorization': f'Bearer {tok}', 'Content-Language': 'uk'}
    rows, page, seen = [], 1, set()
    while True:
        r = requests.get(API, params={'page': page}, headers=head,
                         verify=False, timeout=60)
        try:
            body = r.json()
        except Exception:
            sys.exit(f'нечитана відповідь HTTP {r.status_code} на сторінці {page}')
        if not body.get('success'):
            sys.exit(f'API: {body.get("errors")}')
        part = body['content'].get('marketCategorys') or []
        if not part:
            break
        new = 0
        for c in part:
            cid = c.get('category_id')
            if cid in seen:
                continue
            seen.add(cid)
            rows.append({'rz_id': cid, 'rz_name': c.get('name'),
                         'parent_id': c.get('parent_id')})
            new += 1
        logger.info(f'сторінка {page}: {len(part)} записів, нових {new}, '
                    f'усього {len(rows)}')
        # Порожня сторінка — не єдиний спосіб закінчитись: якщо пагінація
        # зациклиться, повторна сторінка не дасть жодного нового id, і без
        # цієї умови цикл крутився б вічно.
        if new == 0:
            logger.warning(f'сторінка {page} без нових id — зупинка')
            break
        page += 1
        if page > 500:
            logger.warning('понад 500 сторінок — запобіжник')
            break
    return rows


def main():
    rows = fetch()
    if len(rows) < 1000:
        # Позитивний контроль розміру: каталог Rozetka — тисячі категорій.
        # Кілька сотень означали б обрізану пагінацію, а не малий каталог,
        # і мапінг мовчки будувався б на огризку — саме те, що сталось із
        # переліком конкурента на 289 позицій.
        sys.exit(f'ПІДОЗРА: лише {len(rows)} категорій — пагінація обірвалась')
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    leaf = {r['rz_id'] for r in rows} - {r['parent_id'] for r in rows}
    logger.success(f'{len(rows)} категорій → {OUT} (листків {len(leaf)})')


if __name__ == '__main__':
    main()
