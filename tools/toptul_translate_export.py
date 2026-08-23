#!/usr/bin/env python3
"""Вивантаження рядків TOPTUL, які ще не мають перекладу.

Навіщо окремий крок. `toptul_translate.py` ходить у NVIDIA, але ключа
`NVIDIA_API_KEY` на сервері немає (22.08.2026: у `.env` його не існує,
прогін дав 41 відповідь HTTP 401 поспіль і жодного запису). Модель для
перекладу словника не мусить бути саме хмарною: експорт → переклад →
`toptul_translate_load.py` дає той самий результат і той самий захист
від зсуву, бо кожен рядок несе свій оригінал.

Формат виводу — TSV `kind<TAB>uses<TAB>src`, відсортований за спаданням
вживань, щоб найдорожчі рядки перекладались першими.

    python3 tools/toptul_translate_export.py > docs/toptul_todo.tsv
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
from toptul_translate import KINDS, collect, ensure  # noqa: E402


def esc(s: str) -> str:
    """Один рядок TSV. Зворотна операція — `unesc()` у завантажувачі."""
    return (s.replace('\\', '\\\\').replace('\t', '\\t')
             .replace('\r', '').replace('\n', '\\n'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true',
                    help='вивантажити й уже перекладені (для перевірки)')
    ap.add_argument('--kind', action='append', choices=KINDS,
                    help='лише цей вид рядків (можна кілька разів)')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()

    for kind in (a.kind or KINDS):
        src = collect(kind)
        cur.execute('SELECT src FROM toptul_translation WHERE kind=%s', (kind,))
        done = {r['src'] for r in cur.fetchall()}
        todo = [s for s in src if a.all or s not in done]
        logger.info(f'{kind}: різних {len(src)}, вживань {sum(src.values())}, '
                    f'уже в таблиці {len(done)}, на вивантаження {len(todo)}')
        multi = 0
        for s in sorted(todo, key=lambda x: -src[x]):
            # Багаторядкові значення пропускати НЕ можна: перший варіант
            # експорту їх відкидав і мовчки втрачав 155 рядків із 437 —
            # рівно та «чиста» відповідь, від якої застерігає правило
            # позитивного контролю. Тому переноси й табуляції екрануються,
            # а `toptul_translate_load.py` повертає їх назад.
            if '\t' in s or '\n' in s or '\r' in s:
                multi += 1
            print(f'{kind}\t{src[s]}\t{esc(s)}')
        if multi:
            logger.info(f'{kind}: з них багаторядкових (екрановано): {multi}')

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
