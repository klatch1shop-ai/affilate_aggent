#!/usr/bin/env python3
"""Фільтрові характеристики еротичної білизни з назви й опису.

Найбільша категорія фіду — 3176 карток із 4147. Зауваження Ольги (раунд 2
п.1) і чекліст модератора називають причину прямо: «якщо не прописати
параметри, ваш товар не потрапить у відфільтровані покупцем товари».

Метод той самий, що для лубрикантів: значення беремо ТІЛЬКИ з офіційного
довідника категорії 4647534 і тільки якщо слово справді є в тексті цього
товару. Різниця одна, і вона критична — **перевірка близькості**.

Чому вона тут обовʼязкова. Значення «Спереду» і «Ззаду» в довіднику
належать характеристиці «Застібка». Простий пошук слова дав 782 картки, але
вибіркова перевірка показала: «переплітаються спереду», «декор спереду і
ззаду», «вирізи на стегнах спереду» — жодне не про застібку. Тому значення
зараховується, лише якщо в межах 40 символів стоїть слово самої
характеристики («застібка спереду»). Після цього лишилось 443 картки.

Запуск:
    python3 tools/rozetka_lingerie_params.py --dry-run
    python3 tools/rozetka_lingerie_params.py
"""
import argparse
import collections
import html
import os
import re
import sys
import xml.etree.ElementTree as ET

import psycopg2.extras

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402
from rozetka_lube_params import hit  # noqa: E402

FEED = os.path.join(BASE_DIR, 'output', 'noire_rozetka.xml')
RZ = '4647534'
CATEGORY = 'Еротична білизна'
WINDOW = 40

# Характеристики, чиї значення неоднозначні поза контекстом. Ключ — слова,
# які мають стояти поруч, щоб значення зарахувалось.
NEAR = {
    'Застібка': ('застібк', 'застеж', 'блискавк', 'гачк', 'зав\'язк'),
    'Чашка': ('чашк', 'бюстгальтер', 'ліф', 'бра'),
    'Бретелі': ('бретел', 'лямк'),
    'Форма бюстгальтера': ('бюстгальтер', 'ліф', 'бра'),
    'Довжина рукава': ('рукав',),
}
# Решту беремо прямим збігом цілого слова: «Поліамід», «Мереживо», «Push-up»
# однозначні самі по собі.
DIRECT = ('Матеріал', 'Push-up')


def flat(t: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', t or ''))).lower()


def near_hit(text: str, value: str, keys) -> bool:
    for m in re.finditer(re.escape(value.lower()), text):
        a = max(0, m.start() - WINDOW)
        if any(k in text[a:m.end() + WINDOW] for k in keys):
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT param_name, allowed_values FROM rozetka_category_params
                   WHERE rz_category_id=%s""", (RZ,))
    official = {r['param_name']: [v for v in (r['allowed_values'] or [])
                                  if v and v != 'N/D'] for r in cur.fetchall()}

    root = ET.parse(FEED).getroot()
    cats = {x.get('id'): (x.text or '') for x in root.findall('.//category')}
    rows, added, had = [], collections.Counter(), collections.Counter()
    total = 0
    for o in root.findall('.//offer'):
        if cats.get(o.findtext('categoryId')) != CATEGORY:
            continue
        total += 1
        sku = o.get('id')
        prm = {p.get('name'): (p.text or '') for p in o.findall('param')}
        text = flat((o.findtext('name') or '') + ' ' +
                    (o.findtext('description_ua') or ''))
        for name in list(NEAR) + list(DIRECT):
            vals = official.get(name) or []
            if not vals:
                continue
            if prm.get(name):
                had[name] += 1
                continue
            keys = NEAR.get(name)
            found = [v for v in vals
                     if (near_hit(text, v, keys) if keys else hit(text, v.lower()))]
            if not found:
                continue
            added[name] += 1
            for v in found:
                rows.append((sku, name, v, 'name+description'))

    print(f'карток «{CATEGORY}»: {total}\n')
    print(f"{'параметр':22} {'було':>6} {'додаємо':>8}")
    for name in list(NEAR) + list(DIRECT):
        print(f'{name:22} {had[name]:6} {added[name]:8}')
    top = collections.Counter((r[1], r[2]) for r in rows)
    print('\nнайчастіші знайдені значення:')
    for (p, v), n in top.most_common(10):
        print(f'   {p:20} {v[:38]:40} {n}')

    if a.dry_run:
        print('\n--dry-run: у базу не записано')
        return
    psycopg2.extras.execute_values(cur, """
        INSERT INTO rozetka_derived_params (sku, param, value, source)
        VALUES %s ON CONFLICT DO NOTHING""", rows)
    conn.commit()
    print(f'\nзаписано значень: {len(rows)}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
