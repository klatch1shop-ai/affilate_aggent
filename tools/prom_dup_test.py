#!/usr/bin/env python3
"""Склеювання чи ранг: скільки карток ОДНОГО товару показує Prom за точною назвою кожної.

Порада чату 15.09 перед листом у підтримку. Для кожного товару:
  1) перепис: широкий запит «бренд + модель» (5 сторінок) → картки того самого
     товару й варіанта (усі токени `must` у назві) — «група»;
  2) для кожної картки групи (до 8, наша — завжди): запит = її точна назва, 2 прогони →
     які картки групи у видачі (2 сторінки).
Читання результату:
  * у відповідь на назву будь-якої картки групи у видачі завжди рівно 1 картка групи →
    склеювання (показують одну з однакових);
  * кілька карток групи, але не наша → ранг (наш магазин програє серед однакових).
Окремо — підгрупи з дослівно однаковою назвою.

HTML-пошук (основний блок; частковий блок 15.09 був порожній у 34/34 браузерних запитах).

    venv/bin/python tools/prom_dup_test.py --out docs/prom_dup_test_20260915.tsv
"""
import argparse
import collections
import os
import re
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
import prom_search as PS  # noqa: E402

# (наш sku, наш prom_id, запит перепису, токени, які мусять бути в назві картки групи)
PRODUCTS = [
    ('SX1722', None, 'Leg Avenue Faux Pearl', ['leg avenue', 'faux pearl']),
    ('SO6083', None, 'Satisfyer Deep Diver', ['satisfyer', 'deep diver', 'grey']),
    ('SX1201', None, 'Rocks Off Chaiamo G', ['chaiamo', 'black']),
    ('SO4519', None, 'Strap-On-Me Soft Realistic Dildo', ['strap-on-me', 'realistic', 'violet']),
    ('SO6140', None, 'Fleshlight Pink Lady Mini-Lotus', ['fleshlight', 'mini-lotus']),
    ('SX1209', None, 'Satisfyer Mermaid Vibes', ['mermaid vibes', 'mint']),
    ('SO8701', None, 'Pussy Pump Premium Fun', ['pussy pump', 'premium fun']),
    ('SO8779', None, 'Satisfyer G-Force', ['g-force', 'violet']),
    ('SO5178', '3152112459', 'Батіг Art of Sex рукоять 120 см', ['art of sex', 'батіг', '120']),
    ('SO6310', None, 'Alive Fluffy Twist', ['alive', 'fluffy twist']),
]


def norm(s):
    return re.sub(r'\s+', ' ', (s or '').lower().replace('ʼ', "'")).strip()


def prom_ids():
    import json
    p = PS.IDS
    return {str(r['external_id']): str(r['prom_id']) for r in json.load(open(p, encoding='utf-8'))} if os.path.exists(p) else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--cap', type=int, default=8)
    a = ap.parse_args()
    PS.ensure_feed()
    ids = prom_ids()
    ctl = PS.control()
    print(f'контроль SO5178: {ctl}-та позиція', flush=True)
    out = []
    summary = []
    for sku, pid, census_q, must in PRODUCTS:
        pid = pid or ids.get(sku)
        cen = PS.search(census_q, pages=5)
        group = {r['pid']: r for r in cen if all(t in norm(r['name']) for t in must)}
        ours_in_census = pid in group
        if pid and not ours_in_census:              # нашу додаємо з назвою з фіду
            import xml.etree.ElementTree as ET
            nm = next(((o.findtext('name_ua') or '').strip() for o in ET.parse(PS.FEED).getroot().iter('offer')
                       if (o.findtext('vendorCode') or o.get('id')) == sku), '')
            group[pid] = {'pid': pid, 'company_id': PS.OUR_COMPANY, 'company': 'NOIRE (наш)', 'name': nm}
        members = [group[pid]] if pid in group else []
        members += [r for k, r in group.items() if k != pid][:a.cap - len(members)]
        same_title = collections.Counter(norm(r['name']) for r in group.values())
        print(f'\n== {sku}: у переписі {len(cen)}, група {len(group)} (наша в переписі: {ours_in_census}), '
              f'перевіряємо {len(members)}; однакових назв: {sum(c for c in same_title.values() if c > 1)}', flush=True)
        for m in members:
            shown_runs = []
            for run in (1, 2):
                res = PS.search(m['name'], pages=2)
                shown_runs.append({r['pid'] for r in res if r['pid'] in group})
                time.sleep(PS.PAUSE)
            shown = shown_runs[0] | shown_runs[1]
            rec = {'product': sku, 'query_owner': m['company'][:30], 'query_is_ours': int(m['pid'] == pid),
                   'title_dup': same_title[norm(m['name'])], 'group': len(group),
                   'shown_run1': len(shown_runs[0]), 'shown_run2': len(shown_runs[1]),
                   'owner_shown': int(m['pid'] in shown), 'ours_shown': int(bool(pid) and pid in shown),
                   'shown_companies': ';'.join(sorted(group[x]['company'][:20] for x in shown)), 'query': m['name'][:120]}
            out.append(rec)
            print(f"  {'НАШ ' if rec['query_is_ours'] else '    '}{rec['query_owner'][:22]:22} дубль×{rec['title_dup']} "
                  f"→ групи у видачі {rec['shown_run1']}/{rec['shown_run2']} · власник показаний {rec['owner_shown']} · "
                  f"наш {rec['ours_shown']}", flush=True)
        ex = [r for r in out if r['product'] == sku]
        summary.append((sku, len(group), sum(1 for r in ex if max(r['shown_run1'], r['shown_run2']) == 1),
                        len(ex), sum(r['ours_shown'] for r in ex)))
    print(f"\nконтроль після: {PS.control()}-та позиція")
    print('\nтовар   група  запитів «показано рівно 1 з групи»/усього  наш показаний (разів)')
    for s in summary:
        print(f'  {s[0]:8} {s[1]:4}   {s[2]}/{s[3]}   {s[4]}')
    with open(a.out, 'w', encoding='utf-8') as f:
        cols = list(out[0].keys())
        f.write('\t'.join(cols) + '\n')
        for r in out:
            f.write('\t'.join(str(r[c]) for c in cols) + '\n')
    print(f'→ {a.out}')


if __name__ == '__main__':
    main()
