#!/usr/bin/env python3
"""Аудит `toptul_translation`: чи не лишився сам ПЕРЕКЛАД російським.

Навіщо окремо від завантажувача. `toptul_translate_load.py` перевіряє `dst`
лише в тому, що записує зараз. Але в таблиці вже лежать 424 назви й 240
значень від прогону NVIDIA 21.08, і серед них є напівперекладені —
«Матеріал изделия», «Довжина лезвия», «Потужність лампы». Модель переклала
перше слово й лишила друге; стара, звужена ознака `RU` цього не бачила, бо
`изделия`/`лезвия` не мали жодної «однозначної основи» з її переліку.

Тобто рядок у таблиці є, покриття виглядає повним — а у фіді російське
слово лишається. Саме той випадок, коли нуль є фактом про інструмент.

    python3 tools/toptul_translate_audit.py            # перелік
    python3 tools/toptul_translate_audit.py --tsv      # заготовка на правку
"""
import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.append(os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2.extras  # noqa: E402
from loguru import logger  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402
from toptul_translate import RU  # noqa: E402
from toptul_translate_export import esc  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tsv', action='store_true',
                    help='вивести як TSV kind/src/dst для ручної правки')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('SELECT kind, src, dst, uses FROM toptul_translation')
    rows = cur.fetchall()
    bad = [r for r in rows if RU.search(r['dst'] or '')]
    if a.tsv:
        for r in sorted(bad, key=lambda x: -(x['uses'] or 0)):
            print(f"{r['kind']}\t{esc(r['src'])}\t{esc(r['dst'])}")
    else:
        logger.info(f'у таблиці пар: {len(rows)}')
        logger.info(f'переклад лишився російським: {len(bad)} '
                    f'({sum(r["uses"] or 0 for r in bad)} вживань)')
        for r in sorted(bad, key=lambda x: -(x['uses'] or 0)):
            hit = RU.search(r['dst']).group(0)
            logger.info(f"   {r['uses']:5} {r['kind']:5} {r['src'][:45]!r} → "
                        f"{r['dst'][:45]!r}  ({hit!r})")
    cur.close()
    conn.close()
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
