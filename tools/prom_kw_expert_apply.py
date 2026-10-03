#!/usr/bin/env python3
"""Внесення експертних ключів у фід Prom: спершу звільнити, потім заповнити.

Порядок має значення. Слоти вже зайняті, і якщо додавати не звільнивши,
найкращі ключі не вміщаються: у першому прогоні так відхилилось 131 з 165
пропозицій.

ЩО ПРИБИРАЄМО. Лише те, що пройшло ПОДВІЙНИЙ фільтр: модель назвала ключ
зайвим І вимір це підтвердив — ключ стоїть на 50+ наших картках або всі
його слова вже є в назві. Думки моделі самої по собі не досить: правило
merge-not-replace лишається чинним, бо заміна за правилами колись убила
довгий хвіст.

ЩО ДОДАЄМО. Лише те, що пройшло перевірку: мова поля, 2-6 слів, немає на
картці, не стоїть уже на 50+ картках каталогу.

Косметична гілка (лубриканти, збуджуючі засоби, догляд, гігієна) — природна
дослідна група. Решта каталогу лишається контролем.

    STEP_SRC=feed.xml venv/bin/python3 tools/prom_kw_expert_apply.py --write out.xml
"""
import argparse
import glob
import json
import os
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT = 9
PILOT = os.path.join(BASE, 'data', 'prom', 'kw_expert_pilot.json')


def load_all():
    """Усі результати експертних прогонів по категоріях."""
    cards = {}
    for path in glob.glob(os.path.join(BASE, 'exports', 'prom_kw_expert_*.json')):
        d = json.load(open(path, encoding='utf-8'))
        for pid, row in (d.get('cards') or {}).items():
            cards[pid] = row
    return cards


def main(src, out, write):
    cards = load_all()
    print(f'карток із експертними ключами: {len(cards)}')
    tree = ET.parse(src)
    removed = added = touched = 0
    for o in tree.getroot().iter('offer'):
        row = cards.get(o.get('id'))
        if not row:
            continue
        changed = False
        for tag in ('keywords', 'keywords_ua'):
            el = o.find(tag)
            have = [k.strip() for k in ((el.text or '') if el is not None else '').split(',')
                    if k.strip()]
            drop = {d['k'] for d in row['remove'] if d['tag'] == tag}
            kept = [k for k in have if k.lower() not in drop]
            removed += len(have) - len(kept)
            low = {k.lower() for k in kept}
            free = LIMIT - len(kept)
            take = [a['k'] for a in row['add'][tag]
                    if a['k'].lower() not in low][:max(0, free)]
            added += len(take)
            if kept + take != have:
                if el is None:
                    el = ET.SubElement(o, tag)
                el.text = ', '.join(kept + take)
                changed = True
        touched += bool(changed)

    print(f'ПРИБРАНО сміттєвих ключів: {removed}')
    print(f'ДОДАНО експертних:         {added}')
    print(f'карток змінено:            {touched}')
    if not write:
        print('\n--dry: нічого не записано')
        return
    tree.write(out, encoding='utf-8', xml_declaration=True)
    ET.parse(out)
    print(f'\nзаписано {out} ({os.path.getsize(out)} байт), XML валідний')
    os.makedirs(os.path.dirname(PILOT), exist_ok=True)
    json.dump({'started': '2026-10-03', 'група': sorted(cards),
               'removed': removed, 'added': added,
               'контроль': 'решта каталогу, картки поза косметичною гілкою'},
              open(PILOT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('склад групи:', PILOT)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=os.environ.get('STEP_SRC', '/tmp/prom_live.xml'))
    ap.add_argument('--write', metavar='OUT')
    a = ap.parse_args()
    main(a.src, a.write or '/tmp/prom_expert_applied.xml', bool(a.write))
