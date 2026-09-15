#!/usr/bin/env python3
"""Набір браузерних тестів пошуку Prom (для tools/prom_search_browser.py --tests).

Порада чату 15.09 — до листа в підтримку переробити докази правильним методом:
  order_*   порядок слів: 5+ карток, знайдених за точною назвою, з різних категорій;
            orig (позитивний контроль), first_last (перше слово першої частини — в кінець
            цієї частини), seg_swap (друга й третя частини через кому місцями)
  kw        фраза лише з keywords_ua (3+ слова), ЖОДНЕ слово якої не входить у назву —
            без розділеного збігу; n ≥ 10
  notfound  картки, не знайдені HTML-заміром за точною назвою: чи лежать у частковому блоці

    python3 tools/prom_browser_tests_build.py --remeasure docs/prom_visibility_20260915.tsv \
        --out data/prom/browser_tests.tsv
"""
import argparse
import csv
import os
import random
import re
import sys
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
import prom_search as PS  # noqa: E402

WORD = re.compile(r"[\w'’-]+", re.U)


def words(s):
    return {w.lower() for w in WORD.findall(s or '') if len(w) > 2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--remeasure', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--seed', type=int, default=20260915)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    PS.ensure_feed()
    offers = {(o.findtext('vendorCode') or o.get('id') or '').strip(): o for o in ET.parse(PS.FEED).getroot().iter('offer')}
    rows = list(csv.DictReader(open(a.remeasure, encoding='utf-8'), delimiter='\t'))
    tests = []

    # 1. порядок слів — знайдені зараз, різні категорії
    found = [r for r in rows if r.get('q1_found') == '1' and r['sku'] in offers]
    by_cat = {}
    for r in found:
        by_cat.setdefault(offers[r['sku']].findtext('portal_category_id'), r)
    picks = list(by_cat.values())[:5] or found[:5]
    for r in picks:
        name = (offers[r['sku']].findtext('name_ua') or '').strip()
        parts = [p.strip() for p in name.split(',')]
        w = parts[0].split()
        tests.append(('order_orig', r['sku'], r['prom_id'], name))
        if len(w) >= 3:
            tests.append(('order_first_last', r['sku'], r['prom_id'], ', '.join([' '.join(w[1:] + w[:1])] + parts[1:])))
        if len(parts) >= 3:
            tests.append(('order_seg_swap', r['sku'], r['prom_id'], ', '.join([parts[0], parts[2], parts[1]] + parts[3:])))

    # 2. фраза лише з ключів, без жодного слова назви (без розділеного збігу) і з рідкісним
    #    словом (≤3 товари каталогу мають його в ключах) — інакше тисячі результатів і тест
    #    нічого не розрізняє (15.09: перша версія дала «іграшки для чоловіків»)
    ids = {}
    if os.path.exists(PS.IDS):
        import json
        ids = {str(r['external_id']): str(r['prom_id']) for r in json.load(open(PS.IDS, encoding='utf-8'))}
    ids.update({r['sku']: r['prom_id'] for r in rows})
    kwmap = {sku: [x.strip() for x in (o.findtext('keywords_ua') or '').split(',') if x.strip()] for sku, o in offers.items()}
    df = {}
    for ks in kwmap.values():
        for w in set().union(*[words(k) for k in ks]) if ks else set():
            df[w] = df.get(w, 0) + 1
    cand = []
    for sku, o in offers.items():
        nw = words(o.findtext('name_ua'))
        for k in kwmap[sku]:
            kw = words(k)
            if len(k.split()) >= 2 and kw and not (kw & nw) and min(df.get(w, 99) for w in kw) <= 3:
                cand.append((sku, ids.get(sku), k))
                break
    known = [c for c in cand if c[1]]
    rnd.shuffle(known)
    for sku, pid, k in known[:12]:
        tests.append(('kw', sku, pid, k))

    # 3. не знайдені за точною назвою — чи в частковому блоці
    nf = [r for r in rows if r.get('q1_found') == '0' and r.get('status') == 'on_display'
          and r.get('presence') == 'available' and r['sku'] in offers]
    rnd.shuffle(nf)
    for r in nf[:12]:
        tests.append(('notfound', r['sku'], r['prom_id'], (offers[r['sku']].findtext('name_ua') or '').strip()))

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as f:
        for t in tests:
            f.write('\t'.join(t) + '\n')
    c = {}
    for t in tests:
        c[t[0]] = c.get(t[0], 0) + 1
    print(f'тестів: {len(tests)} · {c} · кандидатів «лише ключі» з відомим prom_id: {len(known)} (усього {len(cand)})')
    print(f'→ {a.out}')


if __name__ == '__main__':
    main()
