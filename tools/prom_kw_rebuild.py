#!/usr/bin/env python3
"""Переробка ТІЛЬКИ поля keywords_ua у копії фіду.

Навіщо окремий інструмент, коли є prom_content_fix.py: той одним рухом править
назви, описи й ключі. Для експерименту це непридатно — якщо змінити два поля
одразу, ефект буде нероздільним, і ми не дізнаємось, що саме спрацювало
(зауваження консультанта 08.09.2026). Тут змінюється рівно одне поле,
решта рядків фіду не чіпається.

Джерело нових фраз — prom_kw_matrix.build(), шар 3 (біграми з опису).
25.09.2026: шар 3 переведено на справжню морфологію (pymorphy3) — раніше
`_is_adj` за закінченням плутав прикметник з родовим/місцевим відмінком
іменника («лубрикантом водній»); тепер узгодження відмінка/числа/роду.

    python3 tools/prom_kw_rebuild.py --src IN.xml --out OUT.xml
    python3 tools/prom_kw_rebuild.py --src IN.xml --report
"""
import os, re, sys, argparse, collections
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, 'tools'))
import prom_kw_matrix as M

KW_RE = re.compile(r'(<keywords_ua>)(.*?)(</keywords_ua>)', re.S)


def esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out')
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()

    root = ET.parse(a.src).getroot()
    cats = {c.get('id'): (c.text or '') for c in root.findall('.//category')}
    new_by_sku, st = {}, collections.Counter()
    for o in root.iter('offer'):
        sku = o.findtext('vendorCode') or o.get('id')
        prm = {p.get('name'): (p.text or '') for p in o.findall('param')}
        desc = re.sub(r'<[^>]+>', ' ', o.findtext('description_ua') or '')
        new = M.build(o.findtext('name_ua') or '', o.findtext('vendor') or '',
                      cats.get(o.findtext('categoryId'), ''), prm, desc)
        old = [x.strip() for x in (o.findtext('keywords_ua') or '').split(',') if x.strip()]
        new_by_sku[sku] = ', '.join(new)
        st['фраз було'] += len(old); st['фраз стало'] += len(new)
        if len(new) < len(old):
            st['карток скорочено'] += 1
        elif len(new) > len(old):
            st['карток розширено'] += 1
        else:
            st['карток без зміни кількості'] += 1
        if not new:
            st['карток БЕЗ ключів (порожнє поле)'] += 1

    for k, v in st.most_common():
        print(f'  {k}: {v}')

    if not a.out:
        return

    # Замінюємо рядки в СИРОМУ тексті: так решта фіду лишається байт-у-байт.
    raw = open(a.src, encoding='utf-8').read()
    offers = re.split(r'(?=<offer\b)', raw)
    done = 0
    for i, chunk in enumerate(offers):
        m = re.search(r'<vendorCode>(.*?)</vendorCode>', chunk, re.S)
        if not m:
            continue
        sku = m.group(1).strip()
        if sku not in new_by_sku:
            continue
        if KW_RE.search(chunk):
            offers[i] = KW_RE.sub(
                lambda mm: mm.group(1) + esc(new_by_sku[sku]) + mm.group(3),
                chunk, count=1)
            done += 1
    open(a.out, 'w', encoding='utf-8').write(''.join(offers))
    print(f'\nзаписано {a.out}: замінено keywords_ua у {done} офферах')


if __name__ == '__main__':
    main()
