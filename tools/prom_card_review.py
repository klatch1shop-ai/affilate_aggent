#!/usr/bin/env python3
"""Перевірка ОДНІЄЇ картки Prom — обидві мови, як вона йде у фід.

Навіщо окремо від `prom_card_audit.py`: той перевіряє категоріями, лише
українську сторону, а ключі оцінює, ПЕРЕБУДОВУЮЧИ їх через prom_kw_matrix,
тобто не те, що реально лежить у фіді. Тут — рівно поля фіду, і російська
сторона, на якій 12.09.2026 на першій же картці (SO5178) знайшлося:
російська назва без бренду, російські ключі з шаблонів категорії, помилки
машинного перекладу й невидимі символи в українському описі.

Процес «картка за карткою»: знайдена проблема виправляється в ГЕНЕРАТОРІ
(інакше наступна збірка поверне її), міряється по всьому фіду, і лише текст
конкретної картки (помилки перекладу) правиться через `prom_rewritten_desc`.

    python3 tools/prom_card_review.py SO5178
    python3 tools/prom_card_review.py SO5178 SO5216 --feed /tmp/noire_prom_test_pp.xml
    python3 tools/prom_card_review.py --from docs/chat_cards_20260912.md --summary
"""
import argparse
import collections
import html
import os
import re
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.path.join(BASE, 'data', 'prom', 'noire_prom_server.xml')

ZW = re.compile('[​‌‍⁠﻿]')
RU_ONLY = re.compile(r'[ыэёъ]', re.I)          # у тексті ua — ознака русизму
UA_ONLY = re.compile(r'[іїєґ]', re.I)           # у тексті ru — ознака укр. тексту
TRANSLIT_PAREN = re.compile(r'[A-Za-z][\w\s&\'-]+\(([а-яіїєґ\' -]{3,})\)', re.I)
NO_BRAND = {'без бренда', 'без бренду'}
NAME_MAX = 110
try:
    sys.path.insert(0, os.path.join(BASE, 'tools'))
    from prom_keywords import brand_cyr as _bc
except Exception:
    _bc = None


class _Cyr(dict):
    def get(self, v, d=''):
        if not _bc or not v:
            return d
        out = set()
        for lang in ('ua', 'ru'):
            try:
                x = (_bc(v, lang) or '').lower()
            except Exception:
                x = ''
            if x:
                out.add(x)
        return next(iter(out), d) if len(out) == 1 else ('|'.join(out) or d)


CYR = _Cyr()


def plain(h: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h or ''))).strip()


def phrases(s: str) -> list:
    return [x.strip() for x in (s or '').split(',') if x.strip()]


def review(o, freq_ua, freq_ru) -> list:
    """→ [(поле, проблема)]"""
    out = []
    v = (o.findtext('vendor') or '').strip()
    vl = v.lower()
    has_brand = bool(v) and vl not in NO_BRAND
    nu, nr = o.findtext('name_ua') or '', o.findtext('name') or ''
    du, dr = o.findtext('description_ua') or '', o.findtext('description') or ''
    ku, kr = phrases(o.findtext('keywords_ua')), phrases(o.findtext('keywords'))
    cyr = CYR.get(vl, '')

    for lab, n in (('назва укр.', nu), ('назва рос.', nr)):
        if len(n) > NAME_MAX:
            out.append((lab, f'довша за {NAME_MAX} ({len(n)})'))
        if ZW.search(n):
            out.append((lab, 'невидимі символи'))
        if has_brand and vl not in n.lower():
            out.append((lab, f'немає бренду «{v}»'))
    if RU_ONLY.search(nu):
        out.append(('назва укр.', f'русизм: {", ".join(sorted(set(RU_ONLY.findall(nu))))}'))

    tu, tr = plain(du), plain(dr)
    if ZW.search(du) or ZW.search(dr):
        out.append(('опис', 'невидимі символи'))
    ru_in_ua = [w for w in re.findall(r'\w*[ыэёъ]\w*', tu, re.I)]
    if ru_in_ua:
        out.append(('опис укр.', f'русизми: {", ".join(ru_in_ua[:6])}'))
    if len(UA_ONLY.findall(tr)) > 20:
        out.append(('опис рос.', 'схоже на український текст'))
    m = TRANSLIT_PAREN.search(tu)
    if m:
        out.append(('опис укр.', f'транслітерація в дужках: «{m.group(0)[:50]}»'))
    if len(tu) < 300:
        out.append(('опис укр.', f'короткий ({len(tu)})'))

    for lab, ks, freq in (('ключі укр.', ku, freq_ua), ('ключі рос.', kr, freq_ru)):
        if not ks:
            out.append((lab, 'порожньо'))
            continue
        # Шаблон — фраза БЕЗ бренду, що стоїть у ≥50 картках. Фраза з брендом
        # повторюється, бо брендових карток багато (Art of Sex — десятки),
        # і шаблоном не є — перша версія рахувала її так.
        tmpl = [k for k in ks if freq[k.lower()] >= 50
                and not (has_brand and vl in k.lower())
                and not (cyr and any(c in k.lower() for c in cyr.split('|')))]
        if len(tmpl) > len(ks) / 2:
            out.append((lab, f'шаблонів категорії {len(tmpl)} з {len(ks)}: {", ".join(tmpl[:4])}'))
        if has_brand and not any(vl in k.lower() for k in ks):
            out.append((lab, 'жодної фрази з брендом'))
        junk = [k for k in ks if any(b in k.lower() for b in NO_BRAND)]
        if junk:
            out.append((lab, f'фраза із заглушкою бренду: {junk[0]}'))

    prm = o.findall('param')
    if len(prm) < 3:
        out.append(('характеристики', f'лише {len(prm)}'))
    empty = [p.get('name') for p in prm if not (p.text or '').strip()]
    if empty:
        out.append(('характеристики', f'порожні: {", ".join(empty)}'))
    return out


def show(o):
    print(f"\n{'=' * 78}\n{o.findtext('vendorCode') or o.get('id')} · {o.findtext('vendor')} · "
          f"ціна {o.findtext('price')} · категорія {o.findtext('categoryId')}")
    print(f"  назва укр.: {o.findtext('name_ua')}")
    print(f"  назва рос.: {o.findtext('name')}")
    print(f"  ключі укр.: {o.findtext('keywords_ua')}")
    print(f"  ключі рос.: {o.findtext('keywords')}")
    print(f"  опис укр.:  {plain(o.findtext('description_ua'))[:400]}")
    print('  характеристики: ' + '; '.join(f"{p.get('name')}={p.text}" for p in o.findall('param')))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('skus', nargs='*')
    ap.add_argument('--feed', default=FEED)
    ap.add_argument('--from', dest='src', help='файл, з якого взяти артикули (SO1234, SX…)')
    ap.add_argument('--summary', action='store_true', help='лише зведення, без карток')
    a = ap.parse_args()

    offers = list(ET.parse(a.feed).getroot().iter('offer'))
    by = {(o.findtext('vendorCode') or o.get('id')): o for o in offers}
    freq_ua, freq_ru = collections.Counter(), collections.Counter()
    for o in offers:
        freq_ua.update({k.lower() for k in phrases(o.findtext('keywords_ua'))})
        freq_ru.update({k.lower() for k in phrases(o.findtext('keywords'))})

    skus = list(a.skus)
    if a.src:
        skus += re.findall(r'\b(?:SO|SX|AD|ME|F|BM|HM|PJ)[\w-]*\d+\b', open(a.src, encoding='utf-8').read())
    skus = list(dict.fromkeys(skus))
    tally = collections.Counter()
    for s in skus:
        o = by.get(s)
        if o is None:
            print(f'{s}: немає у фіді')
            continue
        issues = review(o, freq_ua, freq_ru)
        for f, p in issues:
            tally[f'{f}: {re.sub(r"«[^»]*»|: .*", "", p)}'] += 1
        if not a.summary:
            show(o)
            for f, p in issues:
                print(f'   ✗ {f}: {p}')
            if not issues:
                print('   ✓ зауважень немає')
    print(f'\nкарток {len(skus)} · зведення зауважень:')
    for k, n in tally.most_common():
        print(f'  {n:4}  {k}')


if __name__ == '__main__':
    main()
