#!/usr/bin/env python3
"""Аудит фіду dropoffice для Rozetka за зауваженнями менеджера адаптації (15.09.2026).

Зауваження Rozetka (Ольга, #7253098):
  1 опис лише про конкретну одиницю — без асортименту («Розміри в асортименті»)
  2 одиниці виміру в числових параметрах («Товщина: 5», «Висота: 770»)
  3 невідповідність даних: назва / параметри / опис (SW-00000288: 152.4 проти 152,5,
    площа 0.1393 проти 0,138 м²)
  4 фото лише з цим товаром (колаж «КУПУЮТЬ РАЗОМ»)

Кожна перевірка рахується і в нашому фіді, і в джерелі постачальника — щоб бачити,
що успадковано, а що додав генератор. Лише читання.

    python3 tools/dropoffice_rozetka_audit.py --feed output/dropoffice_rozetka.xml --src <джерело.xml>
"""
import argparse
import collections
import re
import xml.etree.ElementTree as ET

ASSORT = re.compile(r'асортимент|ассортимент|різн\w* розмір|разн\w* размер|різн\w* кольор|разн\w* цвет|'
                    r'на вибір|на выбор|розміри\s*:|размеры\s*:', re.I)
NUM_ONLY = re.compile(r'^\s*[\d]+(?:[.,]\d+)?\s*$')
UNIT_IN_NAME = re.compile(r',\s*(мм|см|м|м²|м2|кг|г|л|мл|шт)\s*$|\((мм|см|м|м²|кг|г|л|мл)\)', re.I)
DIMS = re.compile(r'(\d+(?:[.,]\d+)?)\s*[xх×*]\s*(\d+(?:[.,]\d+)?)(?:\s*[xх×*]\s*(\d+(?:[.,]\d+)?))?', re.I)


UNIT_MM = {'мм': 1, 'см': 10, 'м': 1000, 'мкм': 0.001}
VAL_UNIT = re.compile(r'^\s*(\d+(?:[.,]\d+)?)\s*(мм|см|м|мкм)?\s*$')
SPEC_LINE = re.compile(r'(?:розміри|розмір|размеры|размер)\s*:[^.;]{0,60}', re.I)
DIM_PARAMS = ('Товщина', 'Висота', 'Довжина', 'Ширина', 'Ширина рулону', 'Довжина рулону',
              'Товщина покриття', 'Ширина покриття')


def to_mm_val(name, v):
    """«770 мм» → 770; «0.1524 м» → 152.4; голе число — одиниця невідома → None."""
    if name not in DIM_PARAMS:
        return None
    m = VAL_UNIT.match(v or '')
    if not m or not m.group(2):
        return None
    return float(m.group(1).replace(',', '.')) * UNIT_MM[m.group(2)]


def f(x):
    return float(str(x).replace(',', '.'))


def dims(text):
    m = DIMS.search(text or '')
    return tuple(f(x) for x in m.groups() if x) if m else None


import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from dropoffice_rozetka_generator import name_dims_mm as _gen_name_dims  # noqa: E402


def name_dims_mm(name):
    return _gen_name_dims(name)


def plain(html):
    return ' '.join(re.sub(r'<[^>]+>', ' ', html or '').split())


def audit(path, label):
    root = ET.parse(path).getroot()
    offers = list(root.iter('offer'))
    st = collections.Counter()
    ex = collections.defaultdict(list)
    no_unit_params = collections.Counter()
    for o in offers:
        oid = o.get('id')
        name = o.findtext('name_ua') or o.findtext('name') or ''
        desc = plain(o.findtext('description_ua') or '') + ' ' + plain(o.findtext('description') or '')
        pics = o.findall('picture')
        st['фото: офферів з >1 фото'] += len(pics) > 1
        st['фото: усього'] += len(pics)
        # 1. асортимент
        if ASSORT.search(desc):
            st['1 асортимент в описі'] += 1
            ex['1'].append((oid, ASSORT.search(desc).group(0), name[:70]))
        nd = name_dims_mm(name)
        sizes_in_desc = {tuple(sorted(d)) for d in (tuple(f(x) for x in m.groups() if x) for m in DIMS.finditer(desc))}
        if len(sizes_in_desc) >= 2:
            st['1б кілька різних розмірів в описі'] += 1
        # 2. одиниці
        miss = [p.get('name') for p in o.findall('param')
                if NUM_ONLY.match(p.text or '') and not p.get('unit') and not UNIT_IN_NAME.search(p.get('name') or '')
                and p.get('name') not in ('Кількість в упаковці',)]
        if miss:
            st['2 параметри без одиниць'] += 1
            no_unit_params.update(miss)
        # 3. невідповідності розмірів: назва ↔ «Розмір» ↔ числові параметри (з одиницею) ↔ площа ↔ опис
        pv = {p.get('name'): (p.text or '').strip() for p in o.findall('param')}
        bad = []
        if nd:
            sd = sorted(nd)
            r = name_dims_mm(pv.get('Розмір', ''))
            if r and len(r) == len(sd) and any(abs(x - y) > max(0.05, 0.01 * y) for x, y in zip(sorted(r), sd)):
                bad.append(f"Розмір {pv['Розмір']} ≠ назва {'×'.join(map(str, nd))}")
            for k, v in pv.items():
                mm = to_mm_val(k, v)
                if mm is None or k.startswith('Площа') or k.startswith('Кількість'):
                    continue
                if 'Товщина' in k and len(nd) < 3:      # товщини в назві немає — нема з чим звіряти
                    continue
                if all(abs(mm - x) > max(0.05, 0.01 * x) for x in nd):
                    bad.append(f'{k} {v} (= {mm:g} мм) не з назви')
            area = next((pv[k] for k in pv if k.startswith('Площа покриття')), None)
            if area and NUM_ONLY.match(area) and len(nd) >= 2:
                a, b = sorted(nd)[-2:]
                calc = a * b / 1e6
                if calc and abs(f(area) - calc) / calc > 0.03:
                    bad.append(f'площа {area} ≠ {calc:.4f} з назви')
            for m in SPEC_LINE.finditer(desc):
                d = dims(m.group(0))
                if d and sorted(d)[:2] != sd[:2] and all(abs(x - y) > 0.5 for x, y in zip(sorted(d), sd)):
                    bad.append(f'в описі «{m.group(0)[:40]}»')
        if bad:
            st['3 невідповідність розмірів'] += 1
            ex['3'].append((oid, '; '.join(bad)[:120], name[:60]))
    print(f'\n=== {label}: {path} — офферів {len(offers)}')
    for k in sorted(st):
        print(f'  {k:42} {st[k]}')
    if no_unit_params:
        print('  параметри без одиниць (назва → к-сть офферів):', dict(no_unit_params.most_common(15)))
    for k in ('1', '3'):
        for e in ex[k][:6]:
            print(f'   прикл.{k}: {e}')
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--feed', required=True)
    ap.add_argument('--src')
    a = ap.parse_args()
    audit(a.feed, 'НАШ ФІД')
    if a.src:
        audit(a.src, 'ДЖЕРЕЛО ПОСТАЧАЛЬНИКА')


if __name__ == '__main__':
    main()
