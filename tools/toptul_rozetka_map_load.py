#!/usr/bin/env python3
"""Запис ручних відповідностей категорій TOPTUL → Rozetka в `toptul_rozetka_category_map`.

Чому окремий інструмент, а не правка `toptul_rozetka_map.py`. Той перевіряє
`rz_id` по `docs/rozetka_seller_categories.json` — дереву конкурента `ttul`
на 289 категорій — і відкидає все, чого там немає. Саме там немає
газоаналізаторів, тепловізорів, пірометрів і повербанків, тобто нових
відповідностей він не прийняв би жодної. Перекроювати його зіставлення заради
цього означало б чіпати всі 338 категорій, зокрема вже підтверджені.

Перевірки перед записом — усі три обов'язкові, бо кожна ловить свій дефект:
  1. `toptul_id` існує в таблиці. Друкарська помилка в id інакше дала б запис,
     який ніколи не спрацює, а таблиця виглядала б повнішою.
  2. `rz_id` існує в ОФІЦІЙНОМУ каталозі. Вигаданий чи застарілий id — це
     оффер, який Rozetka відкине при імпорті, і дізнаємось про це з листа.
  3. Категорія не має дітей. Rozetka приймає товар лише в листову категорію;
     вузол із дітьми — гарантована помилка модерації.

Не перевіряється й не може бути перевірене автоматично те, ЧИ ТА це категорія
по суті. Тому в JSON поруч із кожним id лежить причина, і рішення ухвалює
людина або агент, а не схожість рядків.

    python3 tools/toptul_rozetka_map_load.py --dry
    python3 tools/toptul_rozetka_map_load.py
"""
import argparse
import json
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
from rozetka_category_find import load, path  # noqa: E402

SRC = os.path.join(BASE_DIR, 'docs', 'toptul_rozetka_manual_official.json')
TIER = 'manual'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', default=SRC)
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    with open(a.file, encoding='utf-8') as f:
        raw = json.load(f)
    dec = {k: v for k, v in raw.items() if not k.startswith('_')}

    rows, by_id, parents = load()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('SELECT toptul_id, toptul_name, goods, tier, rz_id '
                'FROM toptul_rozetka_category_map')
    have = {r['toptul_id']: r for r in cur.fetchall()}

    ok = bad = 0
    goods = 0
    for tid, (rid, why) in dec.items():
        cur_row = have.get(tid)
        if not cur_row:
            logger.error(f'{tid}: такої категорії немає в toptul_rozetka_category_map')
            bad += 1
            continue
        if rid not in by_id:
            logger.error(f'{tid} «{cur_row["toptul_name"]}»: rz_id {rid} '
                         f'немає в офіційному каталозі')
            bad += 1
            continue
        if rid in parents:
            logger.error(f'{tid} «{cur_row["toptul_name"]}»: rz_id {rid} '
                         f'({by_id[rid]["rz_name"]}) має дітей — не листова')
            bad += 1
            continue
        ok += 1
        goods += cur_row['goods'] or 0
        logger.info(f'{tid:>10} {cur_row["goods"] or 0:>4} тов.  '
                    f'{cur_row["toptul_name"][:42]:42} → {path(by_id, rid)}')
        if not a.dry:
            cur.execute("""UPDATE toptul_rozetka_category_map
                              SET rz_id=%s, rz_name=%s, tier=%s, verified=TRUE,
                                  updated_at=NOW()
                            WHERE toptul_id=%s""",
                        (rid, by_id[rid]['rz_name'], TIER, tid))
    if not a.dry:
        conn.commit()

    # Нуль записів — це помилка, а не тиша: файл рішень не буває порожнім.
    if bad or not ok:
        logger.error(f'прийнято {ok}, відхилено {bad} із {len(dec)}')
    else:
        logger.success(f'{"перевірено" if a.dry else "записано"} {ok} із {len(dec)}, '
                       f'товарів {goods}, відхилень немає')

    cur.execute("SELECT tier, count(*) n, sum(goods) g FROM toptul_rozetka_category_map "
                "GROUP BY tier ORDER BY 3 DESC NULLS LAST")
    for r in cur.fetchall():
        logger.info(f'  {r["tier"]:18} категорій {r["n"]:>3}, товарів {r["g"] or 0:>5}')
    cur.close()
    conn.close()
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
