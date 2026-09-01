#!/usr/bin/env python3
"""Переклад описів українською → російською для позицій без російського тексту.

Постачальник дає російський фід не на весь асортимент: 718 позицій мають
лише український опис, і в фіді Prom вони йдуть дублем (рос = укр). Prom
вважає це дублюванням контенту, а дослідження називає причиною блокування
в Google Merchant Center.

Чому саме ця задача віддана моделі, а keywords — ні: тут вихідний текст уже
існує, модель його **перекладає**, а не вигадує. Ризик галюцинації менший
за конструкцією. Але «менший» ≠ «нульовий», тому кожен переклад проходить
валідатор, і все, що не пройшло, лишається в черзі на ручний розгляд —
не публікується мовчки й не відкидається мовчки.

Стан зберігається в БД, тому прогін відновлюваний: падіння Ollama чи
перезавантаження ноутбука не втрачають зробленого.

Запуск:
    python3 tools/noire_ru_translate.py --limit 10        # проба
    python3 tools/noire_ru_translate.py --all             # нічний прогін
    python3 tools/noire_ru_translate.py --report          # зведення
"""
import argparse
import html
import os
import re
import sys
import time

import psycopg2.extras
import requests
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

# У .env лежать обидва варіанти: OLLAMA_BASE_URL без шляху й OLLAMA_URL
# уже зі шляхом. Беремо базовий і дописуємо шлях самі, інакше виходить
# «…/api/generate/api/generate» і глухий 404.
OLLAMA = (os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')
          + '/api/generate')
# gemma3:4b, а не aya-expanse:8b. Заміряно на однакових описах: 4.3 с проти
# 14.6 с при тій самій якості (5/5 валідних в обох). Причина фізична —
# 3.3 ГБ вміщуються в 6 ГБ VRAM цілком, тоді як aya (7.0 ГБ) рахує чверть
# на CPU. Aya лишається для української генерації, де багатомовність
# Cohere може дати перевагу; для перекладу вона програє без виграшу.
MODEL = os.getenv('NOIRE_TRANSLATE_MODEL', 'gemma3:4b')

# Довші описи ріжемо на частини: модель на 8B стабільно тримає ~1200 символів,
# далі починає скорочувати текст замість перекладу.
CHUNK = 1200
# Переклад не має суттєво міняти обсяг. Російська трохи компактніша за
# українську, тож допускаємо 0.6-1.4 від оригіналу; вихід за межі означає,
# що модель або скоротила, або дописала від себе.
LEN_MIN, LEN_MAX = 0.6, 1.4

PROMPT = ("Переклади текст з української на російську. "
          "Збережи всі HTML-теги без змін. Не додавай нічого від себе, "
          "не скорочуй, не коментуй. Виведи лише переклад.\n\n{t}")

UA_ONLY = re.compile(r'[іїєґІЇЄҐ]')
RU_ONLY = re.compile(r'[ыъэёЫЪЭЁ]')
# Слова, що пишуться однаково літерами, які є в обох абетках, тому UA_ONLY
# їх не ловить. Трапляються в хвості шаблонного речення «Придбати X з
# доставкою по Україні», яке модель часто лишає як є.
UA_WORDS = re.compile(
    r'\b(придбати|доставкою|набір|ланцюжок|кольорі|вагіна|іграшк\w*)\b', re.I)


def ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS noire_ru_translation (
            sku        TEXT PRIMARY KEY,
            source_len INTEGER,
            result     TEXT,
            result_len INTEGER,
            status     TEXT,          -- ok | manual | failed
            reason     TEXT,
            model      TEXT,
            seconds    NUMERIC,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def pending(cur, limit=None):
    """SKU з описом лише українською і без готового перекладу."""
    cur.execute("""
        SELECT p.sku, p.description_html d
        FROM sexopt_products p
        LEFT JOIN sexopt_products_ru r ON r.sku = p.sku
        LEFT JOIN noire_ru_translation t ON t.sku = p.sku
        WHERE p.available IS TRUE
          AND COALESCE(p.description_html, '') <> ''
          AND COALESCE(r.description_ru, '') = ''
          AND t.sku IS NULL
        ORDER BY p.sku
    """ + (f' LIMIT {int(limit)}' if limit else ''))
    return cur.fetchall()


def split_chunks(text: str) -> list:
    """Ділимо по межах тегів/речень, щоб не розірвати розмітку."""
    parts, buf = [], ''
    for piece in re.split(r'(</p>|</li>|<br\s*/?>)', text):
        buf += piece
        if len(buf) >= CHUNK:
            parts.append(buf)
            buf = ''
    if buf.strip():
        parts.append(buf)
    return parts or [text]


def translate(text: str) -> tuple:
    out, t0 = [], time.time()
    for chunk in split_chunks(text):
        r = requests.post(OLLAMA, json={
            'model': MODEL, 'prompt': PROMPT.format(t=chunk), 'stream': False,
            'options': {'temperature': 0.1, 'num_predict': 1400}}, timeout=600)
        out.append((r.json().get('response') or '').strip())
    return '\n'.join(out), time.time() - t0


def validate(src: str, res: str) -> str:
    """Порожній рядок = придатний переклад; інакше — причина."""
    if not res:
        return 'порожня відповідь'
    if len(res) < len(src) * LEN_MIN:
        return f'скорочено до {len(res) * 100 // max(len(src), 1)}% оригіналу'
    if len(res) > len(src) * LEN_MAX:
        return f'роздуто до {len(res) * 100 // max(len(src), 1)}% оригіналу'
    # Текст має стати російським: жодної української літери, а не «до трьох».
    # Допуск у три літери пропустив 81 переклад із залишками української —
    # разом із маркерною лексикою і розміткою це 16% від усіх прийнятих.
    ua = len(UA_ONLY.findall(res))
    if ua:
        return f'лишились українські літери ({ua})'
    if UA_WORDS.search(res):
        return 'лишились українські слова'
    if '```' in res:
        return 'модель віддала розмітку markdown'
    if not RU_ONLY.search(res) and len(res) > 200:
        return 'немає ознак російської — ймовірно текст не перекладено'
    # розмітка має вціліти
    for tag in ('<p', '<li', '<ul', '<strong', '<br'):
        if src.count(tag) and abs(src.count(tag) - res.count(tag)) > 1:
            return f'втрачено розмітку {tag}'
    if re.search(r'(?i)\b(переклад|перевод|вот перевод|итак)\b', res[:80]):
        return 'модель додала коментар'
    return ''


def cmd_report(cur):
    cur.execute("""SELECT status, count(*) c, round(avg(seconds)::numeric, 1) s
                   FROM noire_ru_translation GROUP BY status ORDER BY c DESC""")
    rows = cur.fetchall()
    total = sum(r['c'] for r in rows)
    print(f'══ ПЕРЕКЛАД ОПИСІВ ══\nоброблено: {total}')
    for r in rows:
        print(f"   {r['status']:8} {r['c']:5}  середньо {r['s']} с")
    cur.execute("""SELECT reason, count(*) c FROM noire_ru_translation
                   WHERE status <> 'ok' GROUP BY reason ORDER BY c DESC LIMIT 8""")
    bad = cur.fetchall()
    if bad:
        print('\nпричини відхилення:')
        for r in bad:
            print(f"   {r['c']:5}  {r['reason']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure_table(cur)
    conn.commit()

    if a.report:
        cmd_report(cur)
        return

    items = pending(cur, None if a.all else (a.limit or 10))
    logger.info(f'До перекладу: {len(items)}')
    ok = manual = failed = 0
    for i, r in enumerate(items, 1):
        src = r['d']
        try:
            res, sec = translate(src)
        except Exception as e:
            res, sec = '', 0
            logger.warning(f"{r['sku']}: {type(e).__name__}")
        why = validate(src, res) if res else 'помилка виклику моделі'
        status = 'ok' if not why else ('manual' if res else 'failed')
        ok += status == 'ok'
        manual += status == 'manual'
        failed += status == 'failed'
        cur.execute("""INSERT INTO noire_ru_translation
            (sku, source_len, result, result_len, status, reason, model, seconds)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (sku) DO UPDATE SET result=EXCLUDED.result,
              status=EXCLUDED.status, reason=EXCLUDED.reason,
              result_len=EXCLUDED.result_len, seconds=EXCLUDED.seconds""",
                    (r['sku'], len(src), res, len(res), status, why or None,
                     MODEL, round(sec, 1)))
        conn.commit()
        if i % 10 == 0 or i == len(items):
            logger.info(f'{i}/{len(items)}  ok={ok} manual={manual} failed={failed}')
    print(f'\nготово: ok={ok} manual={manual} failed={failed}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
