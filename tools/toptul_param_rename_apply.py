#!/usr/bin/env python3
"""
tools/toptul_param_rename_apply.py
==================================
Застосовує ПІДТВЕРДЖЕНІ перейменування назв характеристик TOPTUL —
правкою `dst` у `toptul_translation`, звідки їх бере
`toptul_rozetka_generator.collect_params()`.

Перейменовуються лише пари з `toptul_param_rename_check.PAIRS`, і лише ті,
які той скрипт визнав ПІДТВЕРДЖЕНИМИ на поточному фіді: цільова назва є серед
характеристик Rozetka в категоріях наших офферів, а поточна — ні. Перелік
складався нечітким зіставленням і містив завідомо хибні пари, тому вирок
виносить звірка з майданчиком, а не цей файл.

    python3 tools/toptul_param_rename_apply.py            # показати, не міняти
    python3 tools/toptul_param_rename_apply.py --apply
    python3 tools/toptul_param_rename_apply.py --revert

Щит: `toptul_translation_bak_<дата>` створюється перед першою правкою.
"""
import os, sys, argparse, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from toptul_param_rename_check import PAIRS, load_cache, cat_names, feed_usage

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAK = 'toptul_translation_bak_' + datetime.date.today().strftime('%Y%m%d')


def db():
    # той самий помічник, що й у решти інструментів TOPTUL — власне
    # з'єднання розійшлося б із їхніми обліковими даними
    sys.path.insert(0, BASE)
    from shared.utils.db import get_connection
    return get_connection()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--feed', default=os.path.join(BASE, 'output', 'toptul_rozetka.xml'))
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--revert', action='store_true')
    a = ap.parse_args()

    conn = db()
    cur = conn.cursor()

    if a.revert:
        cur.execute("SELECT to_regclass(%s) AS t", (BAK,))
        if not cur.fetchone()['t']:
            sys.exit(f'щита {BAK} немає — відкочувати нічого')
        cur.execute(f'UPDATE toptul_translation t SET dst = b.dst '
                    f'FROM {BAK} b WHERE t.kind=b.kind AND t.src=b.src AND t.dst<>b.dst')
        print(f'повернуто рядків: {cur.rowcount}')
        conn.commit()
        return 0

    cache = load_cache()
    total, where, rz_names = feed_usage(a.feed)

    plan = []
    for old, new in PAIRS:
        if not total.get(old):
            print(f'  пропуск: {old!r} — у фіді немає'); continue
        ok = bad = 0
        for rz_id in where[old]:
            names = cat_names(cache, rz_id)
            if names is None:
                continue
            ok += new in names
            bad += old in names
        if not ok or bad:
            print(f'  ВІДМОВА: {old!r} → {new!r} — не підтверджено звіркою '
                  f'(ціль у {ok} кат., поточна у {bad})')
            continue
        # `dst` правиться лише там, де він зараз ДОРІВНЮЄ старій назві: якщо
        # хтось уже переклав рядок інакше, мовчки перезаписувати його не можна.
        # get_connection() віддає RealDictCursor — рядки тут словники
        cur.execute("SELECT kind, src FROM toptul_translation WHERE kind='name' AND dst=%s",
                    (old,))
        rows = [(r['kind'], r['src']) for r in cur.fetchall()]
        if not rows:
            print(f'  ВІДМОВА: {old!r} — немає жодного рядка з таким dst')
            continue
        plan.append((old, new, rows))
        srcs = ', '.join(r[1] for r in rows)
        print(f'  {old!r} → {new!r}: {total[old]} офферів, рядків у таблиці '
              f'{len(rows)} ({srcs})')

    if not plan:
        print('\nнічого застосовувати')
        return 1
    if not a.apply:
        print('\nпробний прогін. Застосувати: --apply')
        return 0

    cur.execute("SELECT to_regclass(%s) AS t", (BAK,))
    if not cur.fetchone()['t']:
        cur.execute(f'CREATE TABLE {BAK} AS SELECT * FROM toptul_translation')
        print(f'щит {BAK} створено')
    n = 0
    for old, new, rows in plan:
        for kind, src in rows:
            cur.execute('UPDATE toptul_translation SET dst=%s '
                        'WHERE kind=%s AND src=%s AND dst=%s', (new, kind, src, old))
            n += cur.rowcount
    conn.commit()
    print(f'\nоновлено рядків: {n}')
    print('далі: перезібрати фід генератором і переміряти '
          'tools/toptul_param_rename_check.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())
