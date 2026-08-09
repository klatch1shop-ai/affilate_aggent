#!/usr/bin/env python3
"""Довідник характеристик категорій Prom.ua → prom_category_attributes.

Джерело: кабінет продавця → «Експорт характеристик», окреме посилання на
кожну категорію з токеном доступу. Токен робить URL самодостатнім, тож
логін не потрібен — звичайного requests достатньо.

Навіщо: Prom розрізняє характеристики КАТЕГОРІЇ (потрапляють у фільтри
каталогу) і КОРИСТУВАЦЬКІ (видно лише на картці). Правила оформлення прямо
кажуть, що конверсія товарів з характеристиками втричі вища, а у фільтри
йдуть лише перші. Тобто вільні <param>, як у фіді Віктора, працюють
наполовину — і це та сама пастка, що вже спіймана на Rozetka.

Структура XML:
    <category id="161011" nameUK="Вібратори">
      <attribute id="5" nameUK="Вага" type="real" measureUnitUK="г"
                 min="0" max="500"/>
      <attribute id="…" nameUK="…" type="select">
        <value id="…" nameUK="…"/>
      </attribute>

Типи: select / multiselect / real / int / string / bool.

Запуск:
    python3 tools/prom_attributes_import.py --dry
    python3 tools/prom_attributes_import.py
"""
import argparse
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests
import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

LINKS = os.path.join(BASE_DIR, 'data', 'prom',
                     'prom_attribute_export_links.txt')
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
PAUSE = 0.6


def ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prom_category_attributes (
            prom_category_id TEXT NOT NULL,
            attr_id          TEXT NOT NULL,
            attr_name        TEXT NOT NULL,
            attr_name_ru     TEXT,
            attr_type        TEXT,
            measure_unit     TEXT,
            min_value        TEXT,
            max_value        TEXT,
            is_required      BOOLEAN NOT NULL DEFAULT FALSE,
            allowed_values   JSONB,
            fetched_at       TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (prom_category_id, attr_id)
        )
    """)


def parse(xml_bytes: bytes) -> list:
    root = ET.fromstring(xml_bytes)
    out = []
    for cat in root.iter('category'):
        cid = cat.get('id')
        for a in cat.findall('attribute'):
            # Дочірній тег саме attribute_value, не value. Українська назва
            # подекуди порожня (Prom не переклав) — тоді беремо російську,
            # інакше значення просто зникло б зі словника.
            vals = [(v.get('nameUK') or '').strip() or (v.get('nameRU') or '').strip()
                    for v in a.findall('attribute_value')]
            vals = [v for v in vals if v]
            # Позначки обовʼязковості у вигрузці немає взагалі: на відміну від
            # Єпіцентру з його attribute_set, Prom не має обовʼязкових
            # характеристик — лише рекомендацію заповнювати щонайменше 2-3.
            req = False
            out.append({
                'cid': cid, 'aid': a.get('id'),
                'name': (a.get('nameUK') or '').strip() or (a.get('nameRU') or '').strip(),
                'name_ru': a.get('nameRU'),
                'type': a.get('type'),
                'unit': a.get('measureUnitUK') or a.get('measureUnitRU'),
                'min': a.get('min'), 'max': a.get('max'),
                'req': req, 'values': vals,
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--links', default=LINKS)
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    urls = [u.strip() for u in open(a.links) if u.strip().startswith('http')]
    logger.info(f'Посилань: {len(urls)}')

    s = requests.Session()
    s.headers['User-Agent'] = UA
    rows, stats = [], {'ok': 0, 'fail': 0, 'attrs': 0, 'select': 0, 'req': 0}

    for i, u in enumerate(urls, 1):
        cid = re.search(r'category_id=(\d+)', u)
        cid = cid.group(1) if cid else '?'
        try:
            r = s.get(u, timeout=90)
            if r.status_code != 200:
                logger.warning(f'{cid}: HTTP {r.status_code}')
                stats['fail'] += 1
                continue
            recs = parse(r.content)
            rows.extend(recs)
            stats['ok'] += 1
            stats['attrs'] += len(recs)
            stats['select'] += sum(1 for x in recs if x['values'])
            stats['req'] += sum(1 for x in recs if x['req'])
            print(f"[{i}/{len(urls)}] {cid}: характеристик {len(recs)}, "
                  f"зі списком значень {sum(1 for x in recs if x['values'])}, "
                  f"обовʼязкових {sum(1 for x in recs if x['req'])}")
        except Exception as e:
            logger.warning(f'{cid}: {type(e).__name__}')
            stats['fail'] += 1
        time.sleep(PAUSE)

    logger.info(f"Категорій отримано {stats['ok']}, збоїв {stats['fail']}, "
                f"характеристик {stats['attrs']} "
                f"(зі списком {stats['select']}, обовʼязкових {stats['req']})")
    if a.dry or not rows:
        print('\n(--dry: у базу нічого не записано)' if a.dry else '')
        return

    conn = get_connection()
    cur = conn.cursor()
    ensure_table(cur)
    psycopg2.extras.execute_values(cur, """
        INSERT INTO prom_category_attributes
          (prom_category_id, attr_id, attr_name, attr_name_ru, attr_type,
           measure_unit, min_value, max_value, is_required, allowed_values)
        VALUES %s
        ON CONFLICT (prom_category_id, attr_id) DO UPDATE SET
          attr_name=EXCLUDED.attr_name, attr_type=EXCLUDED.attr_type,
          measure_unit=EXCLUDED.measure_unit, min_value=EXCLUDED.min_value,
          max_value=EXCLUDED.max_value, is_required=EXCLUDED.is_required,
          allowed_values=EXCLUDED.allowed_values, fetched_at=NOW()
    """, [(x['cid'], x['aid'], x['name'], x['name_ru'], x['type'], x['unit'],
           x['min'], x['max'], x['req'], psycopg2.extras.Json(x['values']))
          for x in rows], page_size=500)
    conn.commit()
    logger.success(f'Записано {len(rows)} характеристик')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
