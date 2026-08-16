#!/usr/bin/env python3
"""Фільтрові характеристики з тексту — для решти категорій Rozetka.

Узагальнення методу, відпрацьованого на лубрикантах і білизні
(`rozetka_lube_params.py`, `rozetka_lingerie_params.py`): значення беремо
лише з офіційного довідника категорії й лише якщо слово справді є в назві
чи описі саме цього товару.

Дві перевірки, без яких метод дає сміття, — обидві куплені досвідом:
  • **ціле слово, а не підрядок.** «мед» знаходився в «медичний»,
    «медицині», «камедь» — 40 хибних ароматів;
  • **близькість до назви характеристики** для неоднозначних значень.
    «Спереду» в довіднику належить «Застібці», але в описі це частіше
    «переплітаються спереду» — 339 хибних збігів на білизні.

Категорії тут — ті, до яких ще не дійшли руки: презервативи, олія для
тіла, чоловіча білизна.

Запуск:
    python3 tools/rozetka_cat_params.py --dry-run
    python3 tools/rozetka_cat_params.py
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
from rozetka_lingerie_params import near_hit  # noqa: E402

FEED = os.path.join(BASE_DIR, 'output', 'noire_rozetka.xml')

# rz_id → (назва категорії у фіді, {характеристика: слова-контексти або None})
# None означає прямий збіг цілого слова: значення однозначне саме по собі.
CATS = {
    '4629824': ('Презервативи', {
        'Аромат': None,
        'Текстура': ('текстур', 'поверхн', 'рельєф', 'ребр', 'точк'),
        'Тип': None,
        'Для кого': ('для чоловіків', 'для жінок', 'для пар'),
        'Властивості гелю/мастила': ('мастил', 'змазк', 'гель'),
        'Основа мастила': ('мастил', 'змазк', 'основ'),
    }),
    '4657502': ('Олія для тіла', {
        'Вид': None,
        'Призначення': ('призначен', 'для масажу', 'для тіла', 'застосу'),
        'Клас косметики': None,
        'Домішки': ('містить', 'до складу', 'екстракт', 'олія'),
        'Спосіб застосування': ('нанес', 'застосу', 'масаж'),
    }),
    '4649418': ('Еротична білизна для чоловіків', {
        'Вид': None,
        'Матеріал': None,
        'Декор': ('декор', 'оздобл', 'прикраш'),
        'Особливості': ('особлив', 'з отвор', 'відкрит'),
    }),
}


def flat(t: str) -> str:
    return re.sub(r'\s+', ' ',
                  html.unescape(re.sub('<[^>]+>', ' ', t or ''))).lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    root = ET.parse(FEED).getroot()
    cats = {x.get('id'): (x.text or '') for x in root.findall('.//category')}

    rows = []
    for rz, (cat_name, wanted) in CATS.items():
        cur.execute("""SELECT param_name, allowed_values
                       FROM rozetka_category_params WHERE rz_category_id=%s""",
                    (rz,))
        official = {r['param_name']: [v for v in (r['allowed_values'] or [])
                                      if v and v != 'N/D'] for r in cur.fetchall()}
        offers = [o for o in root.findall('.//offer')
                  if cats.get(o.findtext('categoryId')) == cat_name]
        had, added = collections.Counter(), collections.Counter()
        for o in offers:
            sku = o.get('id')
            prm = {p.get('name'): (p.text or '') for p in o.findall('param')}
            text = flat((o.findtext('name') or '') + ' ' +
                        (o.findtext('description_ua') or ''))
            for name, keys in wanted.items():
                vals = official.get(name) or []
                if not vals:
                    continue
                if prm.get(name):
                    had[name] += 1
                    continue
                found = [v for v in vals
                         if (near_hit(text, v, keys) if keys
                             else hit(text, v.lower()))]
                if not found:
                    continue
                added[name] += 1
                for v in found:
                    rows.append((sku, name, v, 'name+description'))
        print(f'\n══ {cat_name}: {len(offers)} карток')
        for name in wanted:
            if had[name] or added[name]:
                print(f'   {name:26} було {had[name]:5} → додаємо {added[name]:5}')

    if a.dry_run:
        print(f'\n--dry-run: знайдено {len(rows)} значень, у базу не записано')
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
