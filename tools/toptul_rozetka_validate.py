#!/usr/bin/env python3
"""Валідація спірних відповідностей TOPTUL → Rozetka великою моделлю.

Місце в конвеєрі: **останній крок**. Рядковий матчер (`toptul_rozetka_map.py`)
закриває очевидне, ручний файл — найдорожче, а сюди йде хвіст, де автоматика
не дала однозначної відповіді.

Чому хмарна модель тут дозволена, хоч для SexOpt була ні. Заборона виникла
через асортимент 18+, який хостингові моделі відмовлялись обробляти. TOPTUL —
інструменти, підстав для відмови немає, тож обмеження не поширюється.

Чому саме NVIDIA NIM: ключ Anthropic у проєкті — заглушка, тож валідація
через Claude неможлива, доки його не додадуть. Модель за замовчуванням —
`nemotron-super-49b`, вона з міркуванням: відповідь іде після довгого
`reasoning`, тому `max_tokens` мусить бути з великим запасом, інакше `content`
повертається порожнім (на 64 токенах саме так і сталось).

Калібрувальна проба: 3 із 3 на випадках, де матчер помилявся змістовно —
компресори → компресометри, пневмошланги → поливні, розпилювачі фарби →
товщиноміри фарби.

Захист від вигадок той самий, що й скрізь: відповідь приймається лише як id
зі списку 198 листових категорій. Будь-що інше відкидається.

Впевненість = **згода двох незалежних методів**. Модель і рядковий матчер
вказали те саме — зараховуємо. Розійшлись — на ручний перегляд, з обома
варіантами поруч.

Запуск:
    python3 tools/toptul_rozetka_validate.py --limit 5     # проба
    python3 tools/toptul_rozetka_validate.py --save
"""
import argparse
import collections
import json
import os
import re
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
OUT = os.path.join(BASE_DIR, 'docs', 'toptul_rozetka_validated.json')
API = 'https://integrate.api.nvidia.com/v1/chat/completions'
MODEL = os.getenv('NOIRE_VALIDATE_MODEL',
                  'nvidia/llama-3.3-nemotron-super-49b-v1.5')

PROMPT = """Ти класифікуєш товари постачальника в каталозі Rozetka.

Категорія постачальника: «{name}»
Приклади товарів із неї:
{samples}

Обери ОДНУ категорію Rozetka зі списку нижче, до якої належать ці товари.
Орієнтуйся на приклади товарів, а не лише на назву категорії.

СПИСОК КАТЕГОРІЙ (id — назва):
{cats}

Останнім рядком виведи лише JSON:
{{"rz_id": <число зі списку, або 0 якщо жодна не підходить>, "confidence": "high" або "low"}}"""


def samples_by_category(limit: int = 4) -> dict:
    root = ET.parse(FEED).getroot()
    out = collections.defaultdict(list)
    for o in root.find('shop').find('offers').findall('offer'):
        cid = o.findtext('categoryId')
        if cid and len(out[cid]) < limit:
            nm = (o.findtext('name_ua') or o.findtext('name') or '').strip()
            if nm:
                out[cid].append(nm[:90])
    return out


def _one_call(name: str, samples: list, cats: str, key: str, tokens: int):
    body = {'model': MODEL, 'temperature': 0, 'max_tokens': tokens,
            'messages': [{'role': 'user', 'content': PROMPT.format(
                name=name, cats=cats,
                samples='\n'.join(f'- {s}' for s in samples) or '(немає)')}]}
    r = requests.post(API, headers={'Authorization': f'Bearer {key}'},
                      json=body, timeout=300)
    msg = r.json()['choices'][0]['message']
    # Модель із міркуванням: за короткого ліміту відповідь лишається в
    # reasoning_content, а content порожній — читаємо обидва.
    return (msg.get('content') or '') or (msg.get('reasoning_content') or '')


def ask(name: str, samples: list, cats: str, valid: set, key: str):
    """(rz_id | None, впевненість або причина, секунди).

    Порожня відповідь тут майже завжди означала не відмову, а обрив на
    токенах: міркування з'їдало ліміт, і JSON не встигав початись. На пробі
    так «мовчали» дві категорії з п'яти, хоча відповідь для обох очевидна.
    Тому ліміт із запасом, і одна повторна спроба з подвоєним бюджетом.
    """
    t0 = time.time()
    for tokens in (3000, 6000):
        try:
            txt = _one_call(name, samples, cats, key, tokens)
        except Exception as e:
            return None, type(e).__name__, time.time() - t0
        hits = re.findall(r'\{[^{}]*"rz_id"\s*:\s*(\d+)[^{}]*\}', txt)
        if hits:
            conf = ('high' if '"confidence": "high"' in txt.replace("'", '"')
                    else 'low')
            rid = int(hits[-1])
            # Єдиний, але достатній захист: id мусить бути зі списку.
            return (rid if rid in valid else None), conf, time.time() - t0
    return None, 'без JSON', time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--save', action='store_true')
    a = ap.parse_args()

    key = os.getenv('NVIDIA_API_KEY')
    if not key:
        logger.error('NVIDIA_API_KEY не задано')
        sys.exit(1)

    targets = load_targets()
    valid = {t['rz_id'] for t in targets}
    by_id = {t['rz_id']: t for t in targets}
    cats = '\n'.join(f"{t['rz_id']} — {t['rz_name']}" for t in targets)

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT toptul_id, toptul_name, goods, rz_id, rz_name, tier
                   FROM toptul_rozetka_category_map
                   WHERE tier IN ('review','none') AND NOT verified
                   ORDER BY goods DESC""")
    todo = cur.fetchall()
    if a.limit:
        todo = todo[:a.limit]
    logger.info(f'До валідації: {len(todo)} категорій, модель {MODEL}')

    samples = samples_by_category()
    rows, agree, solo, empty = [], 0, 0, 0
    for i, t in enumerate(todo, 1):
        rid, conf, sec = ask(t['toptul_name'], samples.get(t['toptul_id'], []),
                             cats, valid, key)
        best = max(targets, key=lambda x: score(t['toptul_name'], x['rz_name']))
        if rid is None:
            empty += 1
            # Модель мовчить — це збій ДРУГОГО методу, а не доказ, що
            # відповіді немає. Пропозиція матчера лишається на перегляд:
            # на пробі саме так ледь не втратились «Балонні ключі» і
            # «Зубило, керн, пробійник», обидва очевидно правильні.
            verdict = 'model-silent'
        elif rid == best['rz_id']:
            agree += 1
            verdict = 'agree'          # два незалежні методи зійшлись
        else:
            solo += 1
            verdict = 'model-only'     # на ручний перегляд
        rows.append({'toptul_id': t['toptul_id'], 'toptul_name': t['toptul_name'],
                     'goods': t['goods'], 'model_id': rid,
                     'model_name': by_id[rid]['rz_name'] if rid else None,
                     'matcher_id': best['rz_id'], 'matcher_name': best['rz_name'],
                     'model_confidence': conf, 'verdict': verdict})
        logger.info(f"[{i}/{len(todo)}] {t['goods']:4} {t['toptul_name'][:32]:34} "
                    f"→ {(by_id[rid]['rz_name'] if rid else '—')[:24]:26} "
                    f"{verdict:10} {conf:4} {sec:.0f}с")
        json.dump(rows, open(OUT, 'w'), ensure_ascii=False, indent=1)

    print(f'\nзгода з матчером : {agree}')
    print(f'лише модель      : {solo}')
    print(f'без відповіді    : {empty}')
    logger.success(f'Збережено: {OUT}')

    if a.save:
        n = 0
        for r in rows:
            if r['verdict'] != 'agree':
                continue
            cur.execute("""UPDATE toptul_rozetka_category_map
                           SET rz_id=%s, rz_name=%s, tier='validated',
                               score=NULL, updated_at=NOW()
                           WHERE toptul_id=%s AND NOT verified""",
                        (r['model_id'], r['model_name'], r['toptul_id']))
            n += cur.rowcount
        conn.commit()
        logger.success(f'Записано узгоджених: {n}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
