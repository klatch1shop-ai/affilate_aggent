#!/usr/bin/env python3
"""Довідник характеристик Prom із експорту кабінету.

Кабінет: Товари та послуги → Категорії → «Експорт характеристик». Дає XML
на категорію з повним переліком атрибутів І ДОЗВОЛЕНИХ ЗНАЧЕНЬ двома
мовами — те, чого не було в нашій таблиці: там лежали самі назви атрибутів,
та й то лише для 20 категорій.

Навіщо: без переліку значень ми не можемо перевірити, чи прийме Prom те,
що витягнули з даних постачальника. «Матеріал: Силікон/ABS-пластик» треба
розкласти на два дозволені значення, а не віддати рядком.

Посилання живуть із токеном компанії й не потребують входу — власник
експортує їх із кабінету одним кліком на категорію.

Запуск:
    python3 tools/prom_attrs_import.py /tmp/promattrs/*.bin
    python3 tools/prom_attrs_import.py --report
"""
import argparse
import glob
import os
import sys
import xml.etree.ElementTree as ET

import psycopg2.extras

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
from shared.utils.db import get_connection  # noqa: E402


def ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS prom_attribute_values (
        prom_category_id TEXT NOT NULL,
        attr_id          TEXT NOT NULL,
        attr_name        TEXT NOT NULL,
        value_id         TEXT NOT NULL,
        value_ua         TEXT NOT NULL,
        value_ru         TEXT,
        PRIMARY KEY (prom_category_id, attr_id, value_id))""")
    cur.execute('CREATE INDEX IF NOT EXISTS prom_attr_values_cat '
                'ON prom_attribute_values (prom_category_id, attr_name)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='*')
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()

    if a.report or not a.files:
        cur.execute("""SELECT prom_category_id c, count(DISTINCT attr_name) a,
                              count(*) v FROM prom_attribute_values
                       GROUP BY 1 ORDER BY a DESC""")
        for r in cur.fetchall():
            print(f"   {r['c']:10} атрибутів {r['a']:3}, значень {r['v']:5}")
        return

    attrs, values = [], []
    for path in a.files:
        for cat in ET.parse(path).getroot().findall('.//category'):
            cid = cat.get('id')
            for at in cat.findall('attribute'):
                name = at.get('nameUK') or at.get('nameRU')
                attrs.append((cid, at.get('id'), name, at.get('nameRU'),
                              at.get('type')))
                for v in at.findall('attribute_value'):
                    values.append((cid, at.get('id'), name, v.get('id'),
                                   v.get('nameUK') or v.get('nameRU'),
                                   v.get('nameRU')))
    print(f'файлів: {len(a.files)} | атрибутів: {len(attrs)} | '
          f'значень: {len(values)}')

    psycopg2.extras.execute_values(cur, """
        INSERT INTO prom_category_attributes
          (prom_category_id, attr_id, attr_name, attr_name_ru, attr_type)
        VALUES %s ON CONFLICT (prom_category_id, attr_id) DO UPDATE
          SET attr_name=EXCLUDED.attr_name,
              attr_name_ru=EXCLUDED.attr_name_ru,
              attr_type=EXCLUDED.attr_type""", attrs)
    psycopg2.extras.execute_values(cur, """
        INSERT INTO prom_attribute_values
          (prom_category_id, attr_id, attr_name, value_id, value_ua, value_ru)
        VALUES %s ON CONFLICT DO NOTHING""", values)
    conn.commit()
    print('записано')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
