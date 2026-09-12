#!/usr/bin/env python3
"""Чи індексує пошук Prom поле `keywords_ua` — перевірка з двома контролями.

Питання, від якого залежить уся робота над ключовими словами: якщо Prom
шукає лише за назвою (і, можливо, описом), то поле `keywords_ua` на
видимість не впливає і вкладатися в нього марно.

На кожну картку, яка за власною назвою ЗНАХОДИТЬСЯ (інакше тест безглуздий),
три запити:

    A  «ядро»            повна назва картки            — має знаходитись
    K  ядро + слово K    слово є ЛИШЕ в keywords_ua    — ?
    N  ядро + слово N    слова немає в картці ніде     — негативний контроль

Читання:
    A так, K так, N ні   → keywords_ua індексується
    A так, K ні,  N ні   → не індексується (пошук строгий, а слово не бачить)
    A так, N так         → пошук «м'який» (OR/нечіткий) — картка тест не розрізняє
    A ні                 → ядро невдале, картка вибуває

«Лише в keywords» перевіряється за основою слова (перші 5 літер) у назві,
описі, характеристиках — інакше збіг через опис видавався б за збіг ключа.

    python3 tools/prom_keywords_probe.py --from docs/prom_visibility_20260912.tsv
"""
import argparse
import collections
import csv
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from prom_search import search, locate, FEED, PAUSE  # noqa: E402

# Слова для негативного контролю: наш каталог їх не містить ніде (перевіряється).
NEG = ('тракторний', 'бетономішалка', 'акваріумний', 'шпаклівка', 'велосипедний')
WORD = re.compile(r"[а-яіїєґa-z0-9']+", re.I)
STOP = {'для', 'та', 'і', 'з', 'із', 'на', 'в', 'у', 'від', 'до', 'без', 'по'}


def stems(text: str) -> set:
    return {w[:5].lower() for w in WORD.findall(text or '') if len(w) >= 3}


def core(name: str) -> str:
    """Бренд/модель: латиниця й цифри з назви (їх мало в чужих картках)."""
    toks = re.findall(r"[A-Za-z][A-Za-z0-9\-']+|\d+[A-Za-z]*", name.split(',')[0])
    return ' '.join(toks[:4])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='src', required=True)
    ap.add_argument('--limit', type=int, default=40)
    a = ap.parse_args()

    found = [r for r in csv.DictReader(open(a.src, encoding='utf-8'), delimiter='\t')
             if r['found_pos'] not in ('', '0')]
    offers = {(o.findtext('vendorCode') or o.get('id')): o
              for o in ET.parse(FEED).getroot().iter('offer')}
    catalogue_stems = set()
    for o in offers.values():
        catalogue_stems |= stems((o.findtext('name_ua') or '') + ' '
                                 + (o.findtext('description_ua') or ''))
    neg = [w for w in NEG if w[:5] not in catalogue_stems]
    print(f'знайдених карток у вихідному заміру: {len(found)} · негативні слова: {neg}')

    tally = collections.Counter()
    rows = []
    for r in found[:a.limit]:
        o = offers.get(r['sku'])
        if o is None:
            continue
        name = o.findtext('name_ua') or ''
        body = name + ' ' + (o.findtext('description_ua') or '') + ' ' + ' '.join(
            (p.text or '') + ' ' + (p.get('name') or '') for p in o.findall('param'))
        seen_stems = stems(body)
        kws = [k.strip() for k in (o.findtext('keywords_ua') or '').split(',') if k.strip()]
        only_kw = [w for k in kws for w in WORD.findall(k)
                   if len(w) >= 4 and w.lower() not in STOP and w[:5].lower() not in seen_stems]
        # Ядро — ПОВНА назва. Перша версія брала «бренд + модель», і 14 з 14
        # карток за таким запитом не знаходились узагалі (у топ-20 інші
        # продавці того самого бренду) — позитивний контроль не працював.
        c = name
        if len(c) < 4 or not only_kw:
            tally['пропущено: немає ядра або слова лише-в-ключах'] += 1
            continue
        kword = only_kw[0]
        res = {}
        for tag, q in (('A', c), ('K', f'{c} {kword}'), ('N', f'{c} {neg[0]}')):
            try:
                mine, _ = locate(search(q, pages=2), r['prom_id'])
            except RuntimeError:
                mine = None
            res[tag] = mine
            time.sleep(PAUSE)
        A, K, N = (bool(res[t]) for t in 'AKN')
        verdict = ('ядро не знаходить' if not A else
                   "пошук м'який" if N else
                   'ключ ІНДЕКСУЄТЬСЯ' if K else 'ключ НЕ індексується')
        tally[verdict] += 1
        rows.append((r['sku'], c, kword, res['A'], res['K'], res['N'], verdict))
        print(f"{r['sku']:8} A={res['A']} K+«{kword}»={res['K']} N+«{neg[0]}»={res['N']} → {verdict}", flush=True)

    print('\nпідсумок:')
    for k, v in tally.most_common():
        print(f'  {v:3}  {k}')


if __name__ == '__main__':
    main()
