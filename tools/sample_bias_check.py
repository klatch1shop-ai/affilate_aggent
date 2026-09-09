#!/usr/bin/env python3
"""Позитивний контроль на зміщення вибірки за віком товару.

НАВІЩО. 09.09.2026 з'ясувалось, що вибірка перших 600 товарів через
`/products/list` дала 34.7 % карток із датою 09-05 замість справжніх 9.3 %.
Причина: метод віддає товари за зростанням `id`, тож перші сторінки — це
найдавніше створені позиції. Медіанний перцентиль віку такої вибірки — 5.4 %
замість очікуваних 50 %.

Помилка мовчазна: вибірка виглядає нормальною, числа правдоподібні, і хибний
висновок живе доти, доки хтось випадково не звірить його з повним обходом.

Цей скрипт робить перевірку явною і дешевою — один запит до БД.

МЕТОД. `prom_id` у Prom зростає з часом створення товару. Для випадкової
вибірки медіанний перцентиль `prom_id` у каталозі має лягти біля 50 %.
Систематичне відхилення означає, що відбір іде за віком, а не навмання.

Очікуваний розкид медіани для рівномірної вибірки ≈ 100/(2·√n) відсоткових
пунктів: n=12 → ±14.4, n=40 → ±7.9, n=150 → ±4.1. Порогом беремо 2σ.

    python3 tools/sample_bias_check.py --skus SO1234,SX5678
    python3 tools/sample_bias_check.py --mode name_fixed --date 2026-09-08
    python3 tools/sample_bias_check.py --file skus.txt
"""
import argparse
import bisect
import os
import statistics as st
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402


def catalogue_ids(cur):
    """Живі товари з останнього денного знімка, а не всі рядки таблиці.

    prom_product_state накопичувальна: 09.09 в ній було 5570 рядків при 5540
    живих товарах. Рахувати перцентиль по залишкових рядках означало б міряти
    відносно каталогу, якого вже немає.
    """
    cur.execute("""
        SELECT p.prom_id
        FROM prom_state_history h
        JOIN prom_product_state p USING (external_id)
        WHERE h.snapshot_at = (SELECT max(snapshot_at) FROM prom_state_history)
          AND p.prom_id IS NOT NULL
    """)
    ids = sorted(r['prom_id'] for r in cur.fetchall())
    if not ids:                      # історії ще немає — відкат на поточний стан
        cur.execute('SELECT prom_id FROM prom_product_state '
                    'WHERE prom_id IS NOT NULL')
        ids = sorted(r['prom_id'] for r in cur.fetchall())
    return ids


def load_skus(a, cur):
    if a.skus:
        return [s.strip() for s in a.skus.split(',') if s.strip()]
    if a.file:
        return [l.split()[0].strip() for l in open(a.file, encoding='utf-8')
                if l.strip()]
    cur.execute("""SELECT DISTINCT sku FROM prom_visibility
                   WHERE mode = %s AND checked_at::date = %s""",
                (a.mode, a.date))
    return [r['sku'] for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skus', help='список артикулів через кому')
    ap.add_argument('--file', help='файл: артикул у першій колонці')
    ap.add_argument('--mode', help='режим із prom_visibility')
    ap.add_argument('--date', default='2026-09-08')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()
    ids = catalogue_ids(cur)
    skus = load_skus(a, cur)
    if not skus:
        print('Вибірка порожня — нічого перевіряти.')
        return 2

    cur.execute('SELECT external_id, prom_id FROM prom_product_state '
                'WHERE external_id = ANY(%s)', (skus,))
    have = {r['external_id']: r['prom_id'] for r in cur.fetchall()
            if r['prom_id'] is not None}
    missing = [s for s in skus if s not in have]

    pct = [100 * bisect.bisect_left(ids, v) / len(ids) for v in have.values()]
    n = len(pct)
    med = st.median(pct)
    sigma = 100 / (2 * n ** 0.5)

    print(f'каталог: {len(ids)} живих товарів')
    print(f'вибірка: {n} з {len(skus)}'
          + (f' (немає prom_id у {len(missing)}: {missing[:5]})' if missing else ''))
    print(f'\nмедіанний перцентиль віку : {med:.1f} %   (норма 50 %)')
    print(f'очікуваний розкид         : ±{sigma:.1f} в.п. (1σ), '
          f'±{2 * sigma:.1f} (2σ)')
    print(f'відхилення                : {abs(med - 50) / sigma:.1f}σ')

    if abs(med - 50) > 2 * sigma:
        print('\n✗ ЗМІЩЕННЯ. Вибірка систематично зсунута до '
              + ('давніх' if med < 50 else 'новіших')
              + ' товарів. Перевірте метод відбору: послідовний зріз через '
                '/products/list іде за id і дає саме такий результат.')
        return 1
    print('\n✓ зміщення не виявлено — вибірку можна використовувати')
    return 0


if __name__ == '__main__':
    sys.exit(main())
