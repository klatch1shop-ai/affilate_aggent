#!/usr/bin/env python3
"""Крок постобробки фіду Prom: маркер-експеримент «чи шукає Prom за ключами».

Протокол: docs/prom_marker_experiment_20260915.md (дозвіл власника 15.09).
Вигадане слово-маркер, якого немає на Prom (перевірено до старту), дописується
ЛИШЕ в поле ключів вибраних карток: група UA — у `keywords_ua`, група RU — у
`keywords`. У назві й описі маркера немає, тож розділеного збігу бути не може:
запит = одне слово, яке є лише в ключах.

Налаштування — data/prom/marker_experiment.json; "active": false вимикає крок
(фід проходить без змін). Нічого не робить, якщо файла немає.

    STEP_SRC=feed.xml python3 tools/prom_marker_step.py --write out.xml
"""
import argparse
import json
import os
import shutil
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.environ.get('STEP_SRC') or os.path.join(BASE, 'output', 'noire_prom.xml')
CONF = os.path.join(BASE, 'data', 'prom', 'marker_experiment.json')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', required=True)
    a = ap.parse_args()
    conf = json.load(open(CONF, encoding='utf-8')) if os.path.exists(CONF) else {}
    if not conf.get('active'):
        shutil.copy2(FEED, a.write)
        print('маркер-експеримент вимкнено — фід без змін')
        return
    field = {'ua': 'keywords_ua', 'ru': 'keywords'}
    want = {}
    for grp in conf['groups']:
        for sku in grp['skus']:
            want[sku] = (field[grp['lang']], grp['marker'])
    tree = ET.parse(FEED)
    done, missing = {}, set(want)
    for o in tree.getroot().iter('offer'):
        sku = (o.findtext('vendorCode') or o.get('id') or '').strip()
        if sku not in want:
            continue
        tag, marker = want[sku]
        el = o.find(tag)
        if el is None:
            el = ET.SubElement(o, tag)
        cur = [x.strip() for x in (el.text or '').split(',') if x.strip()]
        if marker not in cur:
            cur.append(marker)
        el.text = ', '.join(cur)
        done[tag] = done.get(tag, 0) + 1
        missing.discard(sku)
    tree.write(a.write, encoding='utf-8', xml_declaration=True)
    print(f'маркер додано: {done}' + (f'; у фіді немає: {sorted(missing)}' if missing else ''))


if __name__ == '__main__':
    main()
