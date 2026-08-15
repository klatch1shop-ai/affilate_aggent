#!/usr/bin/env python3
"""Аудит фотографій карток: майже однакові кадри та обрізане перше фото.

Два зауваження відділу адаптації Rozetka (лист 10.08.2026):
  п.4 «Немає сенсу в одній картці викладати практично однакові фото»
  п.7 «Товар на перших фото має бути видно повністю»

За URL це не визначається: точних дублів у нас нуль, а кадри постачальника
відрізняються дрібницею — модель спереду й та сама модель у рамці паковання.
Тому порівнюємо самі зображення перцептивним хешем.

Метрики:
  • pHash з відстанню Геммінга ≤ THRESHOLD — практично однакові кадри
  • співвідношення сторін першого фото проти решти — ознака кадру-деталі
    (обрізана нога крупним планом замість товару цілком)

Нічого не змінює у фіді: пише в noire_photo_audit і показує звіт. Рішення,
що саме прибирати, приймається після перегляду результатів.

Запуск:
    python3 tools/noire_photo_audit.py --limit 50      # проба
    python3 tools/noire_photo_audit.py                 # повний прохід
    python3 tools/noire_photo_audit.py --report        # звіт з БД
"""
import argparse
import collections
import io
import os
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import requests
import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

FEED = os.path.join(BASE_DIR, 'output', 'noire_rozetka.xml')
THRESHOLD = 6          # відстань Геммінга, за якої кадри вважаємо однаковими
# Сервер постачальника ріже частоту: 12 потоків дали HTTP 429 на 40% запитів.
# Три потоки з паузою тримаються стабільно; повний прохід ~30 хв.
WORKERS = 6
TIMEOUT = 30
PAUSE = 0.25
RETRIES = 3


def ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS noire_photo_audit (
            url        TEXT PRIMARY KEY,
            sku        TEXT NOT NULL,
            position   INTEGER NOT NULL,
            phash      TEXT,
            width      INTEGER,
            height     INTEGER,
            bytes      INTEGER,
            error      TEXT,
            checked_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute('CREATE INDEX IF NOT EXISTS noire_photo_audit_sku '
                'ON noire_photo_audit (sku)')
    # Другий раунд Ольги (14.08.2026, п.5): «QR-коди на фото». Джерело —
    # скани упаковки постачальника, де QR веде на сайт виробника. Ті самі
    # скани дають і два інші зауваження: на упаковці зображено ВСІ кольори
    # моделі (п.4, асортимент у картці) і той самий скан трапляється двічі
    # під різними URL (п.7, дублікати). Тому позначка «на фото є код» —
    # спільний маркер для трьох пунктів, а не лише для QR.
    for col in ('codes TEXT', 'has_qr BOOLEAN'):
        cur.execute(f'ALTER TABLE noire_photo_audit ADD COLUMN IF NOT EXISTS {col}')


def fetch_one(task):
    sku, pos, url = task
    try:
        from PIL import Image
        import imagehash
        import time as _t
        r = None
        for attempt in range(RETRIES):
            r = requests.get(url, timeout=TIMEOUT)
            if r.status_code != 429:
                break
            _t.sleep(2 ** attempt)          # експоненційна витримка
        _t.sleep(PAUSE)
        if r.status_code != 200:
            # Рівно стільки ж полів, скільки в успішній гілці: додавання
            # codes/has_qr у INSERT зробило коротший кортеж фатальним —
            # execute_values падав з IndexError на першому ж HTTP 404.
            return (url, sku, pos, None, None, None, None,
                    f'HTTP {r.status_code}', None, None)
        img = Image.open(io.BytesIO(r.content))
        w, h = img.size
        rgb = img.convert('RGB')
        ph = str(imagehash.phash(rgb))
        return (url, sku, pos, ph, w, h, len(r.content), None) + scan_codes(rgb)
    except Exception as e:
        return (url, sku, pos, None, None, None, None, type(e).__name__,
                None, None)


def scan_codes(img) -> tuple:
    """Типи кодів на зображенні та ознака QR.

    Дрібний QR на скані упаковки не читається в оригінальному масштабі —
    перевірено на скріншоті Ольги BS064: у повному розмірі обидва коди
    знаходяться, у зменшеній копії того ж кадру жодного. Тому пробуємо
    ще й збільшену версію, перш ніж сказати «кодів немає».
    """
    try:
        from pyzbar.pyzbar import decode
    except Exception:
        return (None, None)
    seen = set()
    for factor in (1, 2):
        im = img if factor == 1 else img.resize((img.width * 2, img.height * 2))
        try:
            for c in decode(im):
                seen.add(c.type)
        except Exception:
            pass
        if seen:
            break
    return (','.join(sorted(seen)) or None, 'QRCODE' in seen)


def cmd_scan(cur, conn, limit):
    root = ET.parse(FEED).getroot()
    tasks, known = [], set()
    # Готовим лише ті, де є і phash, і результат перевірки на коди: 18 819
    # зображень зняті до появи QR-детекції, їх треба пройти ще раз.
    cur.execute('SELECT url FROM noire_photo_audit '
                'WHERE phash IS NOT NULL AND has_qr IS NOT NULL')
    known = {r['url'] for r in cur.fetchall()}
    for o in root.findall('.//offer'):
        for i, pic in enumerate(o.findall('picture')):
            if pic.text and pic.text not in known:
                tasks.append((o.get('id'), i, pic.text))
    if limit:
        tasks = tasks[:limit]
    logger.info(f'До перевірки зображень: {len(tasks)} '
                f'(уже в базі: {len(known)})')
    if not tasks:
        return

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        batch = []
        for res in ex.map(fetch_one, tasks):
            batch.append(res)
            done += 1
            if len(batch) >= 300:
                _save(cur, conn, batch)
                batch = []
                logger.info(f'  {done}/{len(tasks)}')
        if batch:
            _save(cur, conn, batch)
    logger.success(f'Оброблено {done} зображень')


def _save(cur, conn, batch):
    psycopg2.extras.execute_values(cur, """
        INSERT INTO noire_photo_audit
          (url, sku, position, phash, width, height, bytes, error,
           codes, has_qr)
        VALUES %s
        ON CONFLICT (url) DO UPDATE SET phash=EXCLUDED.phash,
          width=EXCLUDED.width, height=EXCLUDED.height,
          bytes=EXCLUDED.bytes, error=EXCLUDED.error, checked_at=NOW(),
          codes=EXCLUDED.codes, has_qr=EXCLUDED.has_qr
    """, batch, page_size=300)
    conn.commit()


def _hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count('1')


def cmd_report(cur):
    cur.execute("""SELECT sku, position, url, phash, width, height, error
                   FROM noire_photo_audit ORDER BY sku, position""")
    by = collections.defaultdict(list)
    for r in cur.fetchall():
        by[r['sku']].append(r)

    dup_cards, dup_pairs, crop_first, errors = [], 0, [], 0
    for sku, rows in by.items():
        good = [r for r in rows if r['phash']]
        errors += sum(1 for r in rows if r['error'])
        pairs = []
        for i in range(len(good)):
            for j in range(i + 1, len(good)):
                d = _hamming(good[i]['phash'], good[j]['phash'])
                if d <= THRESHOLD:
                    pairs.append((good[i]['position'], good[j]['position'], d))
        if pairs:
            dup_cards.append((sku, pairs))
            dup_pairs += len(pairs)

        # перше фото як кадр-деталь: помітно інші пропорції за решту
        if len(good) >= 2 and good[0]['position'] == 0:
            f = good[0]
            rest = good[1:]
            if f['width'] and f['height']:
                fr = f['width'] / f['height']
                others = [r['width'] / r['height'] for r in rest
                          if r['width'] and r['height']]
                if others:
                    med = sorted(others)[len(others) // 2]
                    if med and abs(fr - med) / med > 0.25:
                        crop_first.append((sku, round(fr, 2), round(med, 2)))

    print('══ АУДИТ ФОТОГРАФІЙ ══')
    print(f'   карток перевірено      : {len(by)}')
    print(f'   зображень із помилкою  : {errors}')
    print(f'\n   п.4 картки з майже однаковими кадрами: {len(dup_cards)}'
          f'  (пар: {dup_pairs})')
    for sku, pairs in dup_cards[:10]:
        pp = ', '.join(f'фото {a+1}≈{b+1} (d={d})' for a, b, d in pairs[:3])
        print(f'      {sku:10} {pp}')
    print(f'\n   п.7 перше фото з іншими пропорціями: {len(crop_first)}')
    for sku, fr, med in crop_first[:10]:
        print(f'      {sku:10} перше {fr} проти решти {med}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int)
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure_table(cur)
    conn.commit()
    if a.report:
        cmd_report(cur)
    else:
        cmd_scan(cur, conn, a.limit)
        cmd_report(cur)
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
