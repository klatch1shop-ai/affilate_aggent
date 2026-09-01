#!/usr/bin/env python3
"""Характеристики Prom із структурованих даних постачальника.

Донедавна ми витягали характеристики регулярками з опису — ненадійно й
дорого. Збирач `sexopt_prices.py` тепер знімає зі сторінки товару **готову
таблицю характеристик**: матеріал, довжина, діаметр, маса, вібрація,
водостійкість. Це те саме джерело, з якого постачальник формує свій сайт,
тобто найточніше з доступних.

Головна пастка — **одиниці різні в різних категоріях Prom**. Атрибут
«Довжина» в одних категоріях у міліметрах (діапазон 0-2000), в інших у
сантиметрах (0-25, 0-30, 0-60). Постачальник дає міліметри завжди. Без
перерахунку 197 мм стають 197 см, і Prom або відкине значення, або
покаже вібратор завдовжки два метри.

Тому кожне числове значення: переводимо в одиницю ЦІЄЇ категорії й
перевіряємо на діапазон min/max із довідника. Не влізло — не пишемо.

Запуск:
    python3 tools/prom_supplier_params.py --dry-run
    python3 tools/prom_supplier_params.py
"""
import argparse
import collections
import os
import re
import sys

import psycopg2.extras

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
from shared.utils.db import get_connection  # noqa: E402

# Ключ постачальника → (атрибут Prom, одиниця постачальника)
# Одиниця потрібна для перерахунку; None = текстове значення.
MAP = {
    'Материал': ('Матеріал', None),
    'Общая длина (мм)': ('Довжина', 'мм'),
    'Вводимая длина (мм)': ('Довжина робочої частини', 'мм'),
    'Диаметр: максимальный (мм)': ('Діаметр', 'мм'),
    'Ширина (мм)': ('Ширина', 'мм'),
    'Высота (мм)': ('Висота', 'мм'),
    'Масса (кг)': ('Вага', 'кг'),
    'Объем (мл)': ("Об'єм", 'мл'),
    'Вибрация': ('Функція вібрації', None),
    'Белье: размер': ('Розмір', None),
    'Питание': ('Тип живлення', None),
    'Водостойкость': ('Водонепроникність', None),
}
# Текстові значення постачальника → те, що чекає Prom
VALUE_MAP = {
    'Функція вібрації': {'да': 'Є', 'нет': 'Немає', 'так': 'Є', 'ні': 'Немає'},
    'Водонепроникність': {'водостойкая': 'Водонепроникний',
                          'водонепроницаемая': 'Водонепроникний',
                          'брызгозащищенная': 'Бризкозахищений'},
}
CONV = {('мм', 'мм'): 1, ('мм', 'см'): 0.1, ('см', 'мм'): 10, ('см', 'см'): 1,
        ('кг', 'г'): 1000, ('кг', 'кг'): 1, ('мл', 'мл'): 1}


def ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS prom_derived_params (
        sku TEXT NOT NULL, param TEXT NOT NULL, value TEXT NOT NULL,
        source TEXT, found_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (sku, param))""")


def norm(name: str) -> str:
    """Назви атрибутів Prom плутають апострофи: «Об`єм» у Лубрикантах
    записаний ЗВОРОТНИМ апострофом, а не звичайним. Порівнюємо нормалізовано,
    інакше 144 значення обʼєму мовчки не доходили."""
    return re.sub(r"['`’ʼ]", "'", (name or '')).strip().lower()


def num(s):
    s = re.sub(r'[^\d.,]', '', str(s or '')).replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()

    # довідник атрибутів: категорія → назва → (одиниця, min, max)
    cur.execute("""SELECT prom_category_id, attr_name, measure_unit,
                          min_value, max_value FROM prom_category_attributes""")
    spec = collections.defaultdict(dict)
    for r in cur.fetchall():
        spec[r['prom_category_id']][norm(r['attr_name'])] = (
            r['measure_unit'], num(r['min_value']), num(r['max_value']))

    cur.execute("""SELECT prom_category_id, attr_name, value_ua, value_ru
                   FROM prom_attribute_values""")
    vals_of = collections.defaultdict(dict)
    for r in cur.fetchall():
        key = (r['prom_category_id'], norm(r['attr_name']))
        vals_of[key][r['value_ua'].lower()] = r['value_ua']
        if r['value_ru']:
            # Постачальник пише характеристики російською («Силикон»), а
            # довідник ми читали лише в українській формі — 121 матеріал
            # відкидався як невідомий. Ключуємо обома.
            vals_of[key][r['value_ru'].lower()] = r['value_ua']

    cur.execute("""SELECT d.sku, d.features, c.category_id
                   FROM sexopt_dropship_price d
                   LEFT JOIN prom_actual_category c ON c.sku = d.sku
                   WHERE d.features IS NOT NULL""")
    rows, stat, skipped = [], collections.Counter(), collections.Counter()
    for r in cur.fetchall():
        cat = r['category_id']
        attrs = spec.get(cat or '', {})
        if not attrs:
            skipped['категорії немає в довіднику'] += 1
            continue
        for key, val in (r['features'] or {}).items():
            target = MAP.get(key)
            if not target:
                continue
            name, unit = target
            if norm(name) not in attrs:
                skipped[f'{name} немає в категорії {cat}'] += 1
                continue
            want_unit, lo, hi = attrs[norm(name)]
            if unit:
                v = num(val)
                k = CONV.get((unit, want_unit))
                if v is None or k is None:
                    skipped[f'{name}: не переводиться {unit}→{want_unit}'] += 1
                    continue
                v = round(v * k, 2)
                if (lo is not None and v < lo) or (hi is not None and v > hi):
                    skipped[f'{name}: поза діапазоном'] += 1
                    continue
                out = f'{v:g}'
            else:
                out = VALUE_MAP.get(name, {}).get(str(val).strip().lower(),
                                                  str(val).strip())
                if not out:
                    continue
                # Значення звіряємо з довідником категорії (експорт кабінету,
                # 4558 дозволених значень). Постачальник дає складені
                # значення — «Силікон/ABS-пластик» — тому розкладаємо на
                # складові й лишаємо ті, які Prom справді знає. Невідоме
                # значення у фільтр не потрапить, тобто користі не дасть.
                allowed = vals_of.get((cat, norm(name)))
                if allowed:
                    parts = [x.strip() for x in re.split(r'[/,;|]', out) if x.strip()]
                    hit = [allowed[x.lower()] for x in parts if x.lower() in allowed]
                    if not hit:
                        skipped[f'{name}: значення поза довідником'] += 1
                        continue
                    out = ' | '.join(dict.fromkeys(hit))
            rows.append((r['sku'], name, out, 'supplier'))
            stat[name] += 1

    print(f'значень зібрано: {len(rows)}')
    for k, v in stat.most_common(12):
        print(f'   {k:26} {v}')
    print('\nпропущено:')
    for k, v in skipped.most_common(6):
        print(f'   {k[:52]:54} {v}')

    if a.dry_run:
        print('\n--dry-run: у базу не записано')
        return
    psycopg2.extras.execute_values(cur, """
        INSERT INTO prom_derived_params (sku, param, value, source)
        VALUES %s ON CONFLICT (sku, param) DO UPDATE
          SET value=EXCLUDED.value, found_at=NOW()""", rows)
    conn.commit()
    print(f'\nзаписано: {len(rows)}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
