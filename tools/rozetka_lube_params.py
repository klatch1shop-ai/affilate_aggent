#!/usr/bin/env python3
"""Заповнення фільтрових характеристик лубрикантів із назви й опису.

Зауваження Ольги (раунд 1 п.3, раунд 2 п.1): «додати більше параметрів,
особливо тих, що потрапляють у фільтр». Звіт по категорії 4675911 показує,
що з 25 параметрів у фільтрах лише шість: Аромат, Ефекти, Обʼєм, Основа,
Призначення, Форма випуску. Решта — службові поля, яких покупець у фільтрі
не бачить, і заповнювати їх заради цього зауваження сенсу немає.

Обʼєм і Основа вже заповнені з даних постачальника. Цей інструмент бере
чотири інші **тільки з тексту, який постачальник сам написав** про цей
товар — назви й опису, — і тільки якщо знайдене слово є в офіційному
списку дозволених значень Rozetka. Ніякого домислювання: якщо в тексті
нічого немає, характеристика лишається порожньою.

Правило SKILL-14.8 діє: структуру беремо з довідника майданчика, значення —
виключно зі своїх даних.

Запуск:
    python3 tools/rozetka_lube_params.py --dry-run
    python3 tools/rozetka_lube_params.py
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
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

FEED = os.path.join(BASE_DIR, 'output', 'noire_rozetka.xml')
RZ = '4675911'
LUBE_CATEGORY = 'Лубриканти'

# Форма випуску: у довіднику лише три значення. Слова шукаємо в називному
# й непрямих відмінках, тому корені без закінчень.
FORM = {
    'Гель': ('гель', 'гел'),
    'Крем': ('крем',),
    'Спрей': ('спрей', 'спрея'),
}
# Призначення: формулювання довідника довгі, тому тримаємо окремо тригери.
PURPOSE = {
    'Для анального сексу': ('анальн',),
    'Для вагінального сексу': ('вагінальн', 'вагинальн'),
    'Для іграшок (сумісний із секс-іграшками)':
        ('іграшк', 'игрушк', 'сумісн', 'совмест'),
    'Для масажу': ('масаж',),
    'Для мастурбації': ('мастурбац',),
    'Для орального сексу (їстівний лубрикант)':
        ('оральн', 'їстівн', 'съедобн', 'смак', 'вкус'),
    'Для чутливої шкіри': ('чутлив', 'чувствит'),
}
EFFECT = {
    'Збуджуючі': ('збуджу', 'возбужда'),
    'Зігріваючі': ('зігріва', 'согрева', 'розігрів', 'разогрев'),
    'Охолоджуючі': ('охолод', 'охлажда', 'холодн'),
    'Пролонгуючі': ('пролонг', 'подовж', 'продлева'),
    'Регенеруючі': ('регенер', 'відновл', 'восстанавл'),
}


def flat(t: str) -> str:
    return re.sub(r'\s+', ' ', re.sub('<[^>]+>', ' ', html.unescape(t or ''))).lower()


def aroma_map(cur) -> dict:
    """Дозволений аромат → тригери пошуку. Кількасотенний список беремо
    з довідника, а не вигадуємо: збіг шукаємо за коренем слова."""
    cur.execute("""SELECT allowed_values FROM rozetka_category_params
                   WHERE rz_category_id=%s AND param_name='Аромат'""", (RZ,))
    row = cur.fetchone()
    out = {}
    for v in (row['allowed_values'] or []):
        if not v or v == 'N/D':
            continue
        # «Ваніль та груша» → шукаємо цілу фразу, інакше отримаємо ваніль
        # там, де насправді складений аромат
        base = v.lower()
        root = base[:-1] if len(base) > 5 and base[-1] in 'аяиіїоеь' else base
        out[v] = root
    return out


# Збіг лише як ціле слово з коротким закінченням. Пошук підрядком дав
# «Аромат: Мед» у 40 картках, де насправді стояло «медичний», «медицині»,
# «камедь» — жодного меду. Тому корінь + до трьох літер закінчення + межа
# слова: «медом» проходить, «медичних» ні.
def _rx(trigger: str) -> re.Pattern:
    # Довжина допустимого закінчення залежить від кореня. Короткий корінь
    # («мед») мусить лишатись суворим, інакше ловить «медичний». Довгий
    # («охолод») майже завжди дієприкметник і потребує шести літер:
    # «охолоджуючий». Межа в пʼять символів розділяє ці два випадки.
    tail = 6 if len(trigger) >= 5 else 3
    return re.compile(r'\b' + re.escape(trigger) + r'[а-яіїєґ\']{0,%d}\b' % tail)


_rx_cache = {}


def hit(text: str, trigger: str) -> bool:
    if ' ' in trigger:            # складені значення шукаємо як є
        return trigger in text
    rx = _rx_cache.get(trigger)
    if rx is None:
        rx = _rx_cache[trigger] = _rx(trigger)
    return bool(rx.search(text))


def pick(text: str, table: dict) -> list:
    return [name for name, trigs in table.items()
            if any(hit(text, t) for t in trigs)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    aromas = aroma_map(cur)

    cur.execute("""CREATE TABLE IF NOT EXISTS rozetka_derived_params (
        sku TEXT NOT NULL, param TEXT NOT NULL, value TEXT NOT NULL,
        source TEXT, found_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (sku, param, value))""")
    conn.commit()

    root = ET.parse(FEED).getroot()
    cats = {c.get('id'): (c.text or '') for c in root.findall('.//category')}
    rows, stats = [], collections.Counter()
    had = collections.Counter()
    total = 0
    for o in root.findall('.//offer'):
        if cats.get(o.findtext('categoryId')) != LUBE_CATEGORY:
            continue
        total += 1
        sku = o.get('id')
        prm = {p.get('name'): (p.text or '') for p in o.findall('param')}
        text = flat((o.findtext('name') or '') + ' ' +
                    (o.findtext('description_ua') or ''))
        for param, table in (('Форма випуску', FORM), ('Призначення', PURPOSE),
                             ('Ефекти', EFFECT)):
            if prm.get(param):
                had[param] += 1
                continue
            for v in pick(text, table):
                rows.append((sku, param, v, 'name+description'))
                stats[param] += 1
        if prm.get('Аромат'):
            had['Аромат'] += 1
        else:
            hits = [v for v, root_ in aromas.items() if hit(text, root_)]
            # складений аромат («Ваніль та груша») має пріоритет над простим
            if hits:
                best = max(hits, key=len)
                rows.append((sku, 'Аромат', best, 'name+description'))
                stats['Аромат'] += 1

    print(f'карток у категорії {LUBE_CATEGORY}: {total}\n')
    print(f"{'параметр':16} {'було':>6} {'додаємо':>8}")
    for p in ('Аромат', 'Ефекти', 'Призначення', 'Форма випуску'):
        print(f'{p:16} {had[p]:6} {stats[p]:8}')
    seen = collections.Counter((r[1], r[2]) for r in rows)
    print('\nнайчастіші знайдені значення:')
    for (p, v), n in seen.most_common(12):
        print(f'   {p:14} {v[:44]:46} {n}')

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
