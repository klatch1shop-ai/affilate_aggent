#!/usr/bin/env python3
"""Друга незалежна модель для хвоста TOPTUL → Rozetka.

Навіщо окремий прохід. Найсильніший доказ у цій задачі дала не найкраща
модель, а **дві різні моделі, що зійшлись незалежно**. 18.08.2026 таких
збігів було 21, і всі вони виправляли грубі помилки рядкового матчера:
лебідки він відніс до щіток і скребків, пускозарядні пристрої — до скринь
для інструменту, лежаки автомайстра — до автосканерів. Жодна з цих помилок
не виглядає підозріло за оцінкою схожості — саме тому одного методу мало.

Згода моделі з матчером слабша за згоду двох моделей: матчер орієнтується на
написання назви, і модель може зачепитись за те саме слово. Так сталося зі
шлангами — і матчер, і 120b звели «шланги для пневмоінструменту» до поливних.
Помилки корельовані, тож збіг нічого не доводить.

Порядок: `toptul_rozetka_validate.py` записує відповідь першої моделі у
`docs/toptul_rozetka_validated.json`; цей інструмент питає другу модель і
підвищує до `validated-2models` лише там, де обидві назвали ту саму категорію.

Запуск:
    NOIRE_SECOND_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1.5 \
      python3 tools/toptul_rozetka_second.py --save
"""
import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2.extras  # noqa: E402
from loguru import logger  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402
import toptul_rozetka_validate as V  # noqa: E402
from toptul_rozetka_map import load_targets  # noqa: E402

FIRST = os.path.join(BASE_DIR, 'docs', 'toptul_rozetka_validated.json')
OUT = os.path.join(BASE_DIR, 'docs', 'toptul_rozetka_second.json')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--save', action='store_true')
    a = ap.parse_args()

    key = os.getenv('NVIDIA_API_KEY')
    if not key:
        logger.error('NVIDIA_API_KEY не задано')
        sys.exit(1)
    # Друга модель ОБОВʼЯЗКОВО інша: та сама модель двічі — не два методи,
    # а одна думка, повторена двічі, і згода з собою нічого не доводить.
    second = os.getenv('NOIRE_SECOND_MODEL')
    if not second or second == V.MODEL:
        logger.error(f'NOIRE_SECOND_MODEL має бути іншою за {V.MODEL}')
        sys.exit(1)
    V.MODEL = second

    targets = load_targets()
    valid = {t['rz_id'] for t in targets}
    by_id = {t['rz_id']: t for t in targets}
    cats = '\n'.join(f"{t['rz_id']} — {t['rz_name']}" for t in targets)

    first = {r['toptul_id']: r for r in json.load(open(FIRST))
             if r.get('model_id')}

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT toptul_id, toptul_name, goods
                   FROM toptul_rozetka_category_map
                   WHERE tier IN ('review','none') AND NOT verified
                   ORDER BY goods DESC""")
    todo = [t for t in cur.fetchall() if t['toptul_id'] in first]
    if a.limit:
        todo = todo[:a.limit]
    logger.info(f'Друга думка для {len(todo)} категорій, модель {second}')

    samples = V.samples_by_category()
    rows, agree = [], 0
    for i, t in enumerate(todo, 1):
        rid, conf, sec = V.ask(t['toptul_name'], samples.get(t['toptul_id'], []),
                               cats, valid, key)
        prev = first[t['toptul_id']]['model_id']
        match = rid is not None and rid == prev
        agree += match
        rows.append({'toptul_id': t['toptul_id'], 'toptul_name': t['toptul_name'],
                     'goods': t['goods'], 'first_id': prev,
                     'first_name': first[t['toptul_id']]['model_name'],
                     'second_id': rid,
                     'second_name': by_id[rid]['rz_name'] if rid else None,
                     'agree': match})
        logger.info(f"[{i}/{len(todo)}] {t['goods']:4} {t['toptul_name'][:30]:32} "
                    f"перша: {(first[t['toptul_id']]['model_name'] or '—')[:22]:24} "
                    f"друга: {(by_id[rid]['rz_name'] if rid else '—')[:22]:24} "
                    f"{'ЗБІГ' if match else 'різні'} {sec:.0f}с")
        json.dump(rows, open(OUT, 'w'), ensure_ascii=False, indent=1)
        # Запис одразу: прогін триває годинами, збереження лише наприкінці
        # означало б втрату всього при обриві.
        if a.save and match:
            cur.execute("""UPDATE toptul_rozetka_category_map
                           SET rz_id=%s, rz_name=%s, tier='validated-2models',
                               score=NULL, updated_at=NOW()
                           WHERE toptul_id=%s AND NOT verified""",
                        (rid, by_id[rid]['rz_name'], t['toptul_id']))
            conn.commit()

    logger.success(f'Збігів двох моделей: {agree} із {len(todo)}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
