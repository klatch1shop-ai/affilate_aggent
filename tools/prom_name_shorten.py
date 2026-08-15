#!/usr/bin/env python3
"""Розрізняльна ознака у видимій зоні назви (перші 70 символів).

Prom показує у видачі перші ~70 символів назви. Якщо два наші товари
відрізняються тільки кольором чи розміром, а ця частина стоїть у кінці
довгої назви, у видачі вони виглядають ОДНАКОВО — покупець не бачить
різниці й не може обрати.

Виміряно на фіді: 121 однаковий початок, 314 карток (5%). Приклад — девʼять
насадок Strap-On-Me, де в зоні видно «Вібронасадка для страпону з вакуумною
стимуляцією Strap-On-Me Multi Orgasm Dildo», а «M Black» / «S Purple»
обрізано.

Що робимо: ріжемо ЛИШЕ прийменникову вставку між іменною групою й брендом
(«на водній основі», «з вакуумною стимуляцією»). Бренд, модель і хвіст із
розрізняльною ознакою лишаються недоторканими.

Чому саме так, а не «різати з кінця»: перша версія прибирала слова з кінця
вступу й видаляла сам іменник — виходило «Стимулювальний pjur» замість
«Стимулювальний лубрикант pjur». Іменна група недоторканна.

Втрати немає: слова з вирізаної вставки лишаються в keywords («маска на
очі» для SO3415), а Prom шукає і в назві, і в пошукових запитах.

Запуск:
    python3 tools/prom_name_shorten.py --dry-run
    python3 tools/prom_name_shorten.py            # запис у docs/
"""
import argparse
import collections
import json
import os
import re
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.path.join(BASE_DIR, 'output', 'noire_prom.xml')
OUT = os.path.join(BASE_DIR, 'docs', 'prom_name_shorten.json')

ZONE = 70
_INSERT = re.compile(r'\s+(на|з|із|зі|для|під|та|і)\s')


def shorten_head(name: str, vendor: str) -> str:
    if not vendor or len(name) <= ZONE:
        return name
    i = name.lower().find(vendor.lower())
    if i <= 0:
        return name
    lead, rest = name[:i].rstrip(), name[i:]
    m = _INSERT.search(' ' + lead)
    if not m:
        return name
    cut = lead[:m.start()].strip()
    if not cut:
        return name
    out = (cut + ' ' + rest).strip()
    return out if len(out) < len(name) else name


def collisions(names: dict) -> dict:
    h = collections.defaultdict(list)
    for sku, nm in names.items():
        h[nm[:ZONE].rstrip().lower()].append(sku)
    return {k: v for k, v in h.items() if len(v) > 1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    offers = ET.parse(FEED).getroot().findall('.//offer')
    names = {o.get('id'): (o.findtext('name_ua') or '') for o in offers}
    vend = {o.get('id'): (o.findtext('vendor') or '') for o in offers}

    before = collisions(names)
    affected = {s for g in before.values() for s in g}
    fixed = {s: shorten_head(names[s], vend[s]) for s in affected}
    fixed = {s: v for s, v in fixed.items() if v != names[s]}

    after = collisions({**names, **fixed})
    print(f'однакових початків: {len(before)} → {len(after)}')
    print(f'карток у колізіях : {sum(len(v) for v in before.values())} → '
          f'{sum(len(v) for v in after.values())}')
    print(f'назв скорочено    : {len(fixed)}')
    for s, v in list(fixed.items())[:5]:
        print(f'\n  {s}\n    було : {names[s]}\n    стало: {v}')
    if a.dry_run:
        print('\n--dry-run: файл не записано')
        return
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(fixed, f, ensure_ascii=False, indent=1)
    print(f'\nзаписано: {OUT} ({len(fixed)} назв)')


if __name__ == '__main__':
    main()
