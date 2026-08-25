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
from toptul_translate_export import esc  # noqa: E402
# Та сама пара функцій, що й у завантажувачі: ознака мови й виняток на
# перенесений артикул. Друге власне визначення «російського» розійшлось би з
# першим, і аудит показував би не те, що приймає `toptul_translate_load.py`.
from toptul_translate_load import carried_codes  # noqa: E402
from uk_lexicon import ru_words  # noqa: E402


def bad_words(src: str, dst: str) -> list:
    """Російські слова перекладу, крім артикулів, перенесених незмінними.

    Без цього виправлення аудит вимагав неможливого: «Набір екстракторів для
    зламаних болтів (4 шт.) (Харків) ЭКСТРХ» — правильний переклад, але
    артикул `ЭКСТРХ` перекладати заборонено, тож пара лишалась би «поганою»
    назавжди. Той самий випадок, що «Бренд: Молния» 23.08.
    """
    carried = carried_codes(src or '', dst or '')
    return [w for w in ru_words(dst or '') if w not in carried]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tsv', action='store_true',
                    help='вивести як TSV kind/src/dst для ручної правки')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('SELECT kind, src, dst, uses FROM toptul_translation')
    rows = cur.fetchall()
    bad = [r for r in rows if bad_words(r['src'], r['dst'])]
    if a.tsv:
        for r in sorted(bad, key=lambda x: -(x['uses'] or 0)):
            print(f"{r['kind']}\t{esc(r['src'])}\t{esc(r['dst'])}")
    else:
        logger.info(f'у таблиці пар: {len(rows)}')
        logger.info(f'переклад лишився російським: {len(bad)} '
                    f'({sum(r["uses"] or 0 for r in bad)} вживань)')
        for r in sorted(bad, key=lambda x: -(x['uses'] or 0)):
            hit = ' '.join(bad_words(r['src'], r['dst']))
            logger.info(f"   {r['uses']:5} {r['kind']:5} {r['src'][:45]!r} → "
                        f"{r['dst'][:45]!r}  ({hit!r})")
    cur.close()
    conn.close()
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
