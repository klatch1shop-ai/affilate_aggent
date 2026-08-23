#!/usr/bin/env python3
"""Кандидати з ОФІЦІЙНОГО каталогу Rozetka для категорій TOPTUL без мапінгу.

Чим відрізняється від `toptul_rozetka_map.py`. Той шукає у
`docs/rozetka_seller_categories.json` — 289 категоріях із каталогу конкурента
`ttul`. Для 96 категорій TOPTUL (602 товари) відповідника там не знайшлось, і
частина «немає відповідника» була фактом про перелік конкурента: газоаналізатори,
тепловізори чи повербанки він просто не возить, хоча в Rozetka такі категорії є.
Цей скрипт шукає в `docs/rozetka_categories_all.json` — 4762 категорії з
`market-categories/search`.

Скрипт НЕ вирішує. Він друкує кандидатів із повним шляхом від кореня, а
рішення записується руками у `docs/toptul_rozetka_manual.json`: за SKILL-04
хибна категорія гірша за порожню — товар лягає туди, де його не шукають.
Саме тому 27 записів рівня `review` лишились невикористаними: «Інструмент для
пайки → Набори інструментів» і «Тестери герметичності → Тестери кабельні» —
це не відповідники, а найкраще, що змогла дати схожість рядків.

    python3 tools/toptul_rozetka_suggest.py > docs/toptul_rozetka_suggest.txt
"""
import argparse
import difflib
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.append(os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2.extras  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402
from toptul_rozetka_map import TERMS, STOP, norm_tokens  # noqa: E402
from rozetka_category_find import load, path  # noqa: E402


def ua(name: str) -> list:
    """Токени назви TOPTUL, переведені в українські терміни, де вони відомі."""
    out = []
    for t in norm_tokens(name):
        if t in STOP:
            continue
        out.append(TERMS.get(t, t))
    return out


def stem(t: str) -> str:
    return t[:5]


def sim(src_tokens: list, dst: str) -> float:
    """Схожість за основами слів, а не за рядком цілком.

    «Головки торцевые» і «Торцеві головки» як рядки різні (інший порядок і
    закінчення), як набори основ — майже однакові. Порядок слів у назвах
    категорій двох майданчиків не збігається систематично, тож рядкова
    схожість тут дає хибний нуль.
    """
    d = [x for x in norm_tokens(dst) if x not in STOP]
    if not src_tokens or not d:
        return 0.0
    hit = 0.0
    for s in src_tokens:
        best = max((difflib.SequenceMatcher(None, stem(s), stem(x)).ratio()
                    for x in d), default=0.0)
        hit += best
    return hit / len(src_tokens)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=8)
    ap.add_argument('--tier', action='append', default=None)
    a = ap.parse_args()
    tiers = tuple(a.tier or ('none', 'review'))

    rows, by_id, parents = load()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT toptul_id, toptul_name, goods, tier
                     FROM toptul_rozetka_category_map
                    WHERE tier = ANY(%s) ORDER BY goods DESC NULLS LAST""",
                (list(tiers),))
    todo = cur.fetchall()
    print(f'# категорій без мапінгу: {len(todo)}, '
          f'товарів: {sum(r["goods"] or 0 for r in todo)}')
    print(f'# каталог Rozetka: {len(rows)} категорій, листкових {len(rows) - len(parents)}')

    for r in todo:
        toks = ua(r['toptul_name'])
        scored = sorted(((sim(toks, c['rz_name'] or ''), c) for c in rows),
                        key=lambda x: -x[0])[:a.top]
        print(f"\n## {r['toptul_id']}  {r['toptul_name']}  "
              f"[{r['tier']}, товарів {r['goods'] or 0}]  ← {' '.join(toks)}")
        for s, c in scored:
            leaf = ' ' if c['rz_id'] not in parents else '*'
            print(f"   {s:.2f}{leaf}{c['rz_id']:>9}  {path(by_id, c['rz_id'])}")

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
