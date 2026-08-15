#!/usr/bin/env python3
"""Реєстр зауважень модераторів майданчиків: жодне не закривається без доказу.

Навіщо. 10.08.2026 відділ адаптації Rozetka надіслав 7 зауважень. По двох із
них — «практично однакові фото» і «в товарах не повинно бути асортименту» —
було зроблено аналіз (146 пар майже однакових кадрів, поріг, список
межових випадків) і написано «нічого не змінював, чекаю рішення». Рішення
не надійшло, до теми ніхто не повернувся, і 14.08.2026 ті самі два пункти
прийшли вдруге. Місяць роботи менеджера й наш простій — через те, що
«проаналізовано» ніде не відрізнялось від «виправлено».

Реєстр робить цю різницю явною. Статуси:
    new         — зауваження отримано, нічого не зроблено
    analysed    — причину знайдено, зміни НЕ внесені (найнебезпечніший стан)
    fixed       — зміни в коді є, але не опубліковані
    published   — опубліковано, є хеш опублікованого фіду
    confirmed   — модератор підтвердив, що питання закрите
    rejected    — вирішили не виправляти, з поясненням

Правило: доповідати власнику можна лише про `published` і `confirmed`.
`analysed` у звіті завжди називається окремо — це борг, а не результат.

Запуск:
    python3 tools/moderator_findings.py --list
    python3 tools/moderator_findings.py --list --stale
    python3 tools/moderator_findings.py --add rozetka 2 4 "текст зауваження"
    python3 tools/moderator_findings.py --status 12 published --note "sha1 ..."
"""
import argparse
import os
import sys

import psycopg2.extras

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

STATUSES = ('new', 'analysed', 'fixed', 'published', 'confirmed', 'rejected')
# Стани, які виглядають як робота, але нічого не змінили у фіді. Саме вони
# мають потрапляти в кожну доповідь окремим рядком.
DEBT = ('new', 'analysed', 'fixed')


def ensure(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS moderator_findings (
            id          SERIAL PRIMARY KEY,
            marketplace TEXT NOT NULL,       -- rozetka | prom | epicentr
            round       INTEGER NOT NULL,    -- номер листа
            point       TEXT NOT NULL,       -- номер пункту в листі
            summary     TEXT NOT NULL,
            evidence    TEXT,                -- посилання на скріншот/SKU
            status      TEXT NOT NULL DEFAULT 'new',
            note        TEXT,                -- доказ: хеш, SKU, дата
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            updated_at  TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (marketplace, round, point)
        )
    """)


def cmd_list(cur, only_stale: bool, mp: str):
    q = 'SELECT * FROM moderator_findings'
    cond, args = [], []
    if mp:
        cond.append('marketplace = %s')
        args.append(mp)
    if only_stale:
        cond.append('status = ANY(%s)')
        args.append(list(DEBT))
    if cond:
        q += ' WHERE ' + ' AND '.join(cond)
    cur.execute(q + ' ORDER BY marketplace, round, point', args)
    rows = cur.fetchall()
    if not rows:
        print('порожньо')
        return
    cur_mp = None
    for r in rows:
        head = f"{r['marketplace']} раунд {r['round']}"
        if head != cur_mp:
            print(f'\n══ {head} ══')
            cur_mp = head
        flag = '  ⚠ БОРГ' if r['status'] in DEBT else ''
        print(f"  #{r['id']:<3} п.{r['point']:<3} [{r['status']:<9}]"
              f" {r['summary'][:64]}{flag}")
        if r['note']:
            print(f"        {r['note'][:88]}")
    debt = [r for r in rows if r['status'] in DEBT]
    print(f'\nвсього: {len(rows)}, з них борг (не опубліковано): {len(debt)}')
    if debt:
        print('Борг називати в кожній доповіді окремо — «проаналізовано» '
              'це не «виправлено».')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--stale', action='store_true', help='лише борг')
    ap.add_argument('--marketplace')
    ap.add_argument('--add', nargs=4,
                    metavar=('MP', 'ROUND', 'POINT', 'SUMMARY'))
    ap.add_argument('--evidence')
    ap.add_argument('--status', nargs=2, metavar=('ID', 'STATUS'))
    ap.add_argument('--note')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()

    if a.add:
        mp, rnd, point, summary = a.add
        cur.execute("""INSERT INTO moderator_findings
            (marketplace, round, point, summary, evidence)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (marketplace, round, point) DO UPDATE
              SET summary=EXCLUDED.summary, evidence=EXCLUDED.evidence,
                  updated_at=NOW()
            RETURNING id""", (mp, int(rnd), point, summary, a.evidence))
        print('записано #', cur.fetchone()['id'])
        conn.commit()
    elif a.status:
        fid, st = a.status
        if st not in STATUSES:
            sys.exit(f'статус має бути одним із: {", ".join(STATUSES)}')
        if st in ('published', 'confirmed') and not a.note:
            sys.exit('для published/confirmed потрібен --note із доказом '
                     '(хеш опублікованого фіду або цитата модератора)')
        cur.execute("""UPDATE moderator_findings
                       SET status=%s, note=COALESCE(%s, note), updated_at=NOW()
                       WHERE id=%s RETURNING marketplace, point""",
                    (st, a.note, int(fid)))
        r = cur.fetchone()
        conn.commit()
        print(f"#{fid} {r['marketplace']} п.{r['point']} → {st}" if r
              else 'не знайдено')
    else:
        cmd_list(cur, a.stale, a.marketplace)

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
