#!/usr/bin/env python3
"""Внесення перевірених ключів і видалення доведених помилок у фід Prom.

Дві РІЗНІ дії, свідомо розділені:

  * ВИДАЛЕННЯ доведених помилок — на всіх картках. Ключ, що називає інший
    тип товару або плутає стать, це дефект, а не гіпотеза; тримати його
    заради чистоти експерименту немає сенсу.
  * ДОДАВАННЯ нових ключів — ПІЛОТОМ з контрольною групою. Користь не
    доведена, і без контролю ми не дізнаємось, чи працює. Так вирішили
    обидва учасники обговорення 03.10 (docs/research/PROM_CARD_REWORK_PROTOCOL.md).

Додаються лише ключі, які ПІДТВЕРДИЛИ ДВА РІЗНІ вендори (groq і cerebras).

Правила Prom, за якими це безпечно (довідка, підтверджена власником 03.10):
  * збіг шукається В МЕЖАХ ОДНОГО ключового слова, не по всьому переліку;
  * часткова відповідність у назві + часткова в ключах = товару у видачі
    НЕМАЄ, тому кожен ключ має сам покривати запит;
  * між релевантними словами в межах фрази — до 5 слів, довгі фрази Prom
    радить дробити (наші всі ≤6 слів, перевірено);
  * «купити», «замовити», назва регіону в ключах не потрібні (у нас їх 0).

Наявні ключі НІКОЛИ не замінюються — лише доповнюються. Перевірено на
лубрикантах: merge дав 259 → 480 унікальних без жодної погіршеної картки,
а заміна за правилами вбивала довгий хвіст.

    STEP_SRC=feed.xml venv/bin/python3 tools/prom_kw_apply.py --write out.xml
"""
import argparse
import json
import os
import random
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT = 9
VERIFIED = os.path.join(BASE, 'exports', 'prom_kw_verified.json')
TYPE_ERR = os.path.join(BASE, 'exports', 'prom_kw_type_errors.json')
GENDER_ERR = os.path.join(BASE, 'exports', 'prom_kw_gender_errors.json')
PILOT = os.path.join(BASE, 'data', 'prom', 'kw_pilot.json')


def load_errors():
    """Ключі, які треба прибрати: {external_id: {ключ у нижньому регістрі}}."""
    bad = {}
    for path in (TYPE_ERR, GENDER_ERR):
        if not os.path.exists(path):
            continue
        for row in json.load(open(path, encoding='utf-8')):
            pid, key = row[0], row[2]
            bad.setdefault(pid, set()).add(key.strip().lower())
    return bad


def pilot_split(ids, size, seed=20261003):
    """Половина в дослід, половина в контроль — із того самого списку.

    Контроль беремо з ТІЄЇ Ж сукупності, інакше порівнювати нема з чим:
    саме на цьому 30.09 завалилось калібрування фото Єпіцентру.
    """
    pool = sorted(ids)
    random.Random(seed).shuffle(pool)
    return set(pool[:size]), set(pool[size:size * 2])


def main(src, out, pilot_size, write):
    verified = json.load(open(VERIFIED, encoding='utf-8'))['kept']
    bad = load_errors()
    test, control = pilot_split(verified, pilot_size)

    tree = ET.parse(src)
    removed = added = 0
    touched_rm = touched_add = 0
    for o in tree.getroot().iter('offer'):
        pid = o.get('id')

        # 1. видалення помилок — на ВСІХ картках
        drop = bad.get(pid)
        if drop:
            before = 0
            for tag in ('keywords', 'keywords_ua'):
                el = o.find(tag)
                if el is None or not el.text:
                    continue
                keys = [k.strip() for k in el.text.split(',') if k.strip()]
                before += len(keys)
                keep = [k for k in keys if k.strip().lower() not in drop]
                if len(keep) != len(keys):
                    el.text = ', '.join(keep)
                    removed += len(keys) - len(keep)
            if before:
                touched_rm += 1

        # 2. додавання — лише дослідній групі
        if pid in test and pid in verified:
            for tag, keys in verified[pid]['add'].items():
                el = o.find(tag)
                have = [k.strip() for k in (el.text or '').split(',') if k.strip()] if el is not None else []
                low = {k.lower() for k in have}
                free = LIMIT - len(have)
                take = [k for k in keys if k.lower() not in low][:max(0, free)]
                if not take:
                    continue
                if el is None:
                    el = ET.SubElement(o, tag)
                    el.text = ''
                el.text = ', '.join(have + take)
                added += len(take)
            touched_add += 1

    print(f'ВИДАЛЕНО помилкових ключів: {removed} на {touched_rm} картках (усі картки)')
    print(f'ДОДАНО перевірених ключів:  {added} на {touched_add} картках (дослідна група)')
    print(f'контрольна група (не чіпаємо): {len(control)} карток')

    if not write:
        print('\n--dry: нічого не записано')
        return
    tree.write(out, encoding='utf-8', xml_declaration=True)
    ET.parse(out)
    print(f'\nзаписано {out} ({os.path.getsize(out)} байт), XML валідний')
    os.makedirs(os.path.dirname(PILOT), exist_ok=True)
    json.dump({'started': '2026-10-03', 'test': sorted(test),
               'control': sorted(control), 'added': added, 'removed': removed},
              open(PILOT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('склад пілота:', PILOT)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=os.environ.get('STEP_SRC', '/tmp/prom_now.xml'))
    ap.add_argument('--write', metavar='OUT')
    ap.add_argument('--pilot', type=int, default=600)
    a = ap.parse_args()
    main(a.src, a.write or '/tmp/prom_applied.xml', a.pilot, bool(a.write))
