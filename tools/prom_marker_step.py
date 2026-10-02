#!/usr/bin/env python3
"""Крок постобробки фіду Prom: маркер-експеримент «чи шукає Prom за ключами».

Протокол: docs/prom_marker_experiment_20260915.md (дозвіл власника 15.09).
Вигадане слово-маркер, якого немає на Prom (перевірено до старту), дописується
ЛИШЕ в поле ключів вибраних карток: група UA — у `keywords_ua`, група RU — у
`keywords`. У назві й описі маркера немає, тож розділеного збігу бути не може:
запит = одне слово, яке є лише в ключах.

Налаштування — два файли, обидва необов'язкові:
  data/prom/marker_experiment.json       — «чи шукає Prom за ключами» (15.09)
  data/prom/price_marker_experiment.json — ціновий поріг видимості (16.09,
                                            docs/prom_price_threshold_experiment_plan.md)
"active": false у файлі вимикає його експеримент. Якщо жодного активного —
фід проходить без змін. Картка не може бути у двох експериментах одночасно:
перетин SKU зупиняє крок.

    STEP_SRC=feed.xml python3 tools/prom_marker_step.py --write out.xml
"""
import argparse
import json
import os
import shutil
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.environ.get('STEP_SRC') or os.path.join(BASE, 'output', 'noire_prom.xml')
CONFS = [os.path.join(BASE, 'data', 'prom', f)
         for f in ('marker_experiment.json', 'marker_experiment_v2.json',
           'price_marker_experiment.json')]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', required=True)
    a = ap.parse_args()
    confs = [json.load(open(c, encoding='utf-8')) for c in CONFS if os.path.exists(c)]
    confs = [c for c in confs if c.get('active')]
    if not confs:
        shutil.copy2(FEED, a.write)
        print('маркер-експерименти вимкнено — фід без змін')
        return
    field = {'ua': 'keywords_ua', 'ru': 'keywords'}
    want = {}
    for conf in confs:
        for grp in conf['groups']:
            for sku in grp['skus']:
                if sku in want:
                    raise SystemExit(f'SKU {sku} у двох експериментах одразу — крок зупинено')
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
    print(f'експериментів активних: {len(confs)}, карток: {len(want)}')
    print(f'маркер додано: {done}' + (f'; у фіді немає: {sorted(missing)}' if missing else ''))


if __name__ == '__main__':
    main()
