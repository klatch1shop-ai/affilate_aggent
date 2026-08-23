#!/usr/bin/env python3
"""Добір категорій Rozetka локальною моделлю — для хвоста, який не бере матчер.

Чому тут модель доречна, а в описах була ні. Простір відповідей **закритий**:
198 листових категорій із дерева конкурента. Модель не може вигадати
категорію — може лише назвати id, і будь-який id поза списком відкидається.
Порівняй із переписуванням описів, де простір відкритий і вигадка проходила
у текст непоміченою.

Головний важіль точності — не промпт, а **контекст**: сама назва категорії
часто нічого не каже («Цанговые соединения»), тому в запит ідуть ще й назви
кількох реальних товарів із цієї категорії.

Впевненість визначається згодою двох незалежних методів: якщо модель і
рядковий матчер (`toptul_rozetka_map.py`) вказали ту саму категорію — беремо
автоматично. Розійшлись — на ручний перегляд, з обома варіантами.

Запуск:
    python3 tools/toptul_rozetka_llm.py --limit 5      # проба
    python3 tools/toptul_rozetka_llm.py --save
"""
import argparse
import collections
import json
import os
import sys
import time
import xml.etree.ElementTree as ET

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2.extras  # noqa: E402
from loguru import logger  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402
from toptul_rozetka_map import load_targets, score  # noqa: E402

FEED = os.getenv('TOPTUL_FEED_FILE', '/tmp/toptul.xml')
OUT = os.path.join(BASE_DIR, 'docs', 'toptul_rozetka_llm.json')
OLLAMA = (os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')
          + '/api/generate')
MODEL = os.getenv('NOIRE_MAP_MODEL', 'aya-expanse:8b')

PROMPT = """Ти працюєш із каталогом інструментів.

Категорія постачальника (російською): «{name}»
Приклади товарів із неї:
{samples}

Обери ОДНУ категорію Rozetka зі списку, до якої належать ці товари.

СПИСОК КАТЕГОРІЙ (id — назва):
{cats}

Правила:
- відповідь — лише число id зі списку;
- якщо жодна не підходить, відповідь 0;
- не пояснюй, не пиши нічого крім числа.

Відповідь:"""


def samples_by_category(limit: int = 5) -> dict:
    root = ET.parse(FEED).getroot()
    shop = root.find('shop')
    out = collections.defaultdict(list)
    for o in shop.find('offers').findall('offer'):
        cid = o.findtext('categoryId')
        if cid and len(out[cid]) < limit:
            nm = (o.findtext('name_ua') or o.findtext('name') or '').strip()
            if nm:
                out[cid].append(nm[:90])
    return out


def ask(name: str, samples: list, cats_txt: str, valid: set):
    """Повертає (rz_id | None, сирий текст, секунди)."""
    t0 = time.time()
    body = {'model': MODEL,
            'prompt': PROMPT.format(name=name, cats=cats_txt,
                                    samples='\n'.join(f'- {s}' for s in samples)),
            'stream': False,
            'options': {'temperature': 0.1, 'num_predict': 12}}
    try:
        r = requests.post(OLLAMA, json=body, timeout=300)
        raw = (r.json().get('response') or '').strip()
    except Exception as e:
        return None, f'{type(e).__name__}', time.time() - t0
    digits = ''.join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None, raw[:40], time.time() - t0
    rid = int(digits[:9])
    # Єдиний, але достатній захист: id мусить бути зі списку.
    return (rid if rid in valid else None), raw[:40], time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--save', action='store_true')
    a = ap.parse_args()

    targets = load_targets()
    valid = {t['rz_id'] for t in targets}
    by_id = {t['rz_id']: t for t in targets}
    cats_txt = '\n'.join(f"{t['rz_id']} — {t['rz_name']}" for t in targets)

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT toptul_id, toptul_name, goods, rz_id, rz_name, tier
                   FROM toptul_rozetka_category_map
                   WHERE tier IN ('review','none')
                   ORDER BY goods DESC""")
    todo = cur.fetchall()
    if a.limit:
        todo = todo[:a.limit]
    logger.info(f'До розбору: {len(todo)} категорій, модель {MODEL}')

    samples = samples_by_category()
    rows, agree, solo, empty = [], 0, 0, 0
    for i, t in enumerate(todo, 1):
        rid, raw, sec = ask(t['toptul_name'], samples.get(t['toptul_id'], []),
                            cats_txt, valid)
        # Другий метод: найкращий варіант рядкового матчера.
        best = max(targets, key=lambda x: score(t['toptul_name'], x['rz_name']))
        best_sc = score(t['toptul_name'], best['rz_name'])
        if rid is None:
            empty += 1
            tier = 'none'
        elif rid == best['rz_id']:
            agree += 1
            tier = 'llm+matcher'
        else:
            solo += 1
            tier = 'llm-only'
        rows.append({'toptul_id': t['toptul_id'], 'toptul_name': t['toptul_name'],
                     'goods': t['goods'], 'llm_id': rid,
                     'llm_name': by_id[rid]['rz_name'] if rid else None,
                     'matcher_id': best['rz_id'], 'matcher_name': best['rz_name'],
                     'matcher_score': best_sc, 'tier': tier, 'raw': raw})
        logger.info(f"[{i}/{len(todo)}] {t['goods']:4} {t['toptul_name'][:34]:36} "
                    f"→ {(by_id[rid]['rz_name'] if rid else '—')[:26]:28} "
                    f"{tier:12} {sec:.0f}с")

    print(f'\nзгода з матчером : {agree}')
    print(f'лише модель      : {solo}')
    print(f'без відповіді    : {empty}')
    json.dump(rows, open(OUT, 'w'), ensure_ascii=False, indent=1)
    logger.success(f'Збережено: {OUT}')

    if a.save:
        n = 0
        for r in rows:
            if r['tier'] != 'llm+matcher':
                continue
            cur.execute("""UPDATE toptul_rozetka_category_map
                           SET rz_id=%s, rz_name=%s, tier='llm', score=NULL,
                               updated_at=NOW()
                           WHERE toptul_id=%s AND NOT verified""",
                        (r['llm_id'], r['llm_name'], r['toptul_id']))
            n += cur.rowcount
        conn.commit()
        logger.success(f'Записано узгоджених відповідностей: {n}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
