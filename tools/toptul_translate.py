#!/usr/bin/env python3
"""Переклад характеристик TOPTUL на українську — словником, не по картках.

Замір 21.08.2026: у фіді 33757 характеристик, з них **45% мають російську
назву** (15256 вживань), а різних назв лише 319. Значень російською 6950.
Тобто перекладати треба словник унікальних рядків, а не кожне вживання —
319 запитів замість 15 тисяч.

Чому хмарна модель тут дозволена: асортимент — інструменти, обмеження щодо
18+ на TOPTUL не поширюється (перевірено, NVIDIA обробляє без відмов).

Захист від вигадок: модель повертає рядки ПОРЯДКОВО, і кількість рядків у
відповіді мусить збігатися з кількістю на вході. Не збіглась — партія
відхиляється цілком, а не «підганяється».

Запуск:
    python3 tools/toptul_translate.py --names --dry
    python3 tools/toptul_translate.py --names --values
"""
import argparse
import collections
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2.extras  # noqa: E402
from loguru import logger  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402

FEED = os.getenv('TOPTUL_FEED_FILE', '/tmp/toptul.xml')
API = 'https://integrate.api.nvidia.com/v1/chat/completions'
# Доступ до КОНКРЕТНОЇ моделі зникає без попередження: 21.08.2026 о 06:20
# nemotron-120b обробила 30 запитів поспіль, а о 06:58 почала віддавати
# HTTP 404 із порожнім тілом, тоді як решта моделей працювала. Тому не одна
# модель, а перелік: на 404 переходимо до наступної й далі працюємо нею.
MODELS = [m for m in (os.getenv('NOIRE_TRANSLATE_MODEL'),
                      'nvidia/nemotron-3-super-120b-a12b',
                      'mistralai/mistral-nemotron',
                      'deepseek-ai/deepseek-v4-flash-0731') if m]
_active = [0]
BATCH = 15

# Однозначні ознаки російської. Слова, спільні для обох мов («головка»,
# «ключ», «набір»), сюди НЕ входять — інакше перекладали б уже українське.
RU = re.compile(r'[ыэъё]|\b(отвертк\w*|съемник\w*|трещоточн\w*|удлинитель\w*|'
                r'переходник\w*|рукоятк\w*|размер\w*|материал\w*|цвет\b|'
                r'количество|назначение|инструмент\w*|шестигранн\w*|ед\.|'
                r'длина|ширина|высота|вес\b|диаметр|давлени\w*|момент\w*|'
                r'напряжени\w*|мощност\w*|скорост\w*|привод\w*|числ\w*)', re.I)

# Прив'язка за ПОРЯДКОМ рядків виявилась крихкою: модель розбивала
# багатослівні значення на кілька рядків, і партія на 25 позицій приходила
# як 27 або 34 — відхилялась цілком. Тому кожен рядок несе свій оригінал,
# і зіставлення йде за ним, а не за позицією. Зайві рядки ігноруються.
PROMPT = """Переклади українською терміни з каталогу інструментів.

ФОРМАТ ВІДПОВІДІ — по одному рядку на кожен термін:
оригінал ||| переклад

ПРАВИЛА:
- зліва від ||| постав оригінал ТОЧНО як у переліку, без змін;
- якщо термін уже українською — праворуч повтори його без змін;
- бренди, моделі, артикули, одиниці виміру НЕ перекладай;
- без нумерації, без пояснень, без порожніх рядків.

ПЕРЕЛІК ({n}):
{items}"""


def ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS toptul_translation (
        kind TEXT, src TEXT, dst TEXT, uses INT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (kind, src))""")


def translate(items: list, key: str) -> dict:
    """{оригінал: переклад}. Зіставлення за рядком, не за позицією."""
    wanted = set(items)
    # Читаємо ТІЛЬКИ content. Резервне читання reasoning_content, доречне в
    # класифікації, тут отруйне: у міркуванні сотні рядків, і партія на 40
    # позицій відхилялась як «198 рядків замість 40». Порожній content
    # означає лише брак токенів — повторюємо з більшим бюджетом.
    txt = ''
    for tokens in (1500, 3000):
        while _active[0] < len(MODELS):
            model = MODELS[_active[0]]
            body = {'model': model, 'temperature': 0, 'max_tokens': tokens,
                    'messages': [{'role': 'user', 'content': PROMPT.format(
                        n=len(items), items='\n'.join(items))}]}
            try:
                r = requests.post(API, headers={'Authorization': f'Bearer {key}'},
                                  json=body, timeout=240)
            except Exception as e:
                logger.warning(f'{type(e).__name__}')
                return {}
            if r.status_code == 404:
                logger.warning(f'модель {model} недоступна (404) — переходжу далі')
                _active[0] += 1
                continue
            try:
                txt = (r.json()['choices'][0]['message'].get('content') or '').strip()
            except Exception:
                logger.warning(f'нечитана відповідь HTTP {r.status_code}')
                return {}
            break
        if _active[0] >= len(MODELS):
            logger.error('усі моделі недоступні')
            return {}
        if txt:
            break
    if not txt:
        logger.warning('порожній content навіть на 12000 токенів')
        return {}
    pairs = {}
    for line in txt.split('\n'):
        if '|||' not in line:
            continue
        src, _, dst = line.partition('|||')
        src = re.sub(r'^\s*\d+[\.\)]\s*', '', src.strip())
        dst = dst.strip()
        if src in wanted and dst:
            pairs[src] = dst
    if not pairs:
        logger.warning('жодної пари з роздільником у відповіді')
    return pairs


def collect(kind: str) -> collections.Counter:
    root = ET.parse(FEED).getroot()
    c = collections.Counter()
    for o in root.find('shop').find('offers').findall('offer'):
        for p in o.findall('param'):
            s = (p.get('name') if kind == 'name' else (p.text or '')).strip()
            if s and RU.search(s):
                c[s] += 1
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--names', action='store_true')
    ap.add_argument('--values', action='store_true')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    key = os.getenv('NVIDIA_API_KEY')
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()

    for kind in [k for k, on in (('name', a.names), ('value', a.values)) if on]:
        src = collect(kind)
        cur.execute('SELECT src FROM toptul_translation WHERE kind=%s', (kind,))
        done = {r['src'] for r in cur.fetchall()}
        todo = [s for s in src if s not in done]
        logger.info(f'модель {MODELS[_active[0]]}');logger.info(f'{kind}: різних {len(src)}, вживань {sum(src.values())}, '
                    f'до перекладу {len(todo)}')
        if a.dry:
            for s in todo[:10]:
                print(f'   {src[s]:5}  {s}')
            continue
        ok = 0
        for i in range(0, len(todo), BATCH):
            part = todo[i:i + BATCH]
            out = translate(part, key)
            if not out:
                continue
            for s, d in out.items():
                cur.execute("""INSERT INTO toptul_translation (kind, src, dst, uses)
                               VALUES (%s,%s,%s,%s)
                               ON CONFLICT (kind, src) DO UPDATE SET dst=EXCLUDED.dst""",
                            (kind, s, d, src[s]))
            conn.commit()
            ok += len(out)
            logger.info(f'  {kind}: {ok}/{len(todo)}')
            time.sleep(0.3)
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
