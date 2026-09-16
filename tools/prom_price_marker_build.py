#!/usr/bin/env python3
"""Відбір карток для цінового тесту порогу видимості Prom.

Протокол: docs/prom_price_threshold_experiment_plan.md.
Питання: чи залежить потрапляння картки у видачу від її ціни. Маркер-експеримент
16.09 дав єдиного кандидата — ціну (дешевша половина 24 %, дорожча 6 %, верхня
цінова чверть 0/25), решта ознак картки ефекту не дала.

Дизайн (заданий до збору даних): 75 пар «дешева + дорога» з ОДНІЄЇ портальної
категорії, різні вигадані маркери на групу, обидва в `keywords_ua`.
Парування за категорією прибирає категорію як пояснення конструктивно.

Цін НЕ змінює: картки лише відбираються за наявною ціною.

    venv/bin/python tools/prom_price_marker_build.py --pairs 75 --write
"""
import argparse
import collections
import csv
import json
import os
import random
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
OUT = os.path.join(BASE, 'data', 'prom', 'price_marker_experiment.json')
CHEAP_MAX, EXP_MIN = 630.0, 2000.0


def used_skus():
    """SKU, які вже брали участь у замірах: не змішувати вибірки."""
    used = set()
    conf = os.path.join(BASE, 'data', 'prom', 'marker_experiment.json')
    if os.path.exists(conf):
        c = json.load(open(conf, encoding='utf-8'))
        used |= {s for g in c['groups'] for s in g['skus']}
    for path, col in (('docs/prom_visibility_20260915.tsv', 'sku'),
                      ('data/prom/browser_tests_20260915.tsv', 'sku'),
                      ('docs/prom_dup_test_20260915.tsv', 'sku'),
                      ('docs/prom_dup_test_auto_20260915.tsv', 'sku')):
        p = os.path.join(BASE, path)
        if not os.path.exists(p):
            continue
        with open(p, encoding='utf-8') as f:
            for r in csv.DictReader(f, delimiter='\t'):
                if r.get(col):
                    used.add(r[col].strip())
    excl = os.path.join(BASE, 'data', 'prom', 'exclude_skus.json')
    if os.path.exists(excl):
        e = json.load(open(excl, encoding='utf-8'))
        used |= set(e if isinstance(e, list) else e.get('skus', []))
    return used


def in_feed(feed):
    """SKU, які реально є в опублікованому фіді (крок шукає за vendorCode)."""
    skus = set()
    for _, o in ET.iterparse(feed, events=('end',)):
        if o.tag == 'offer':
            sku = (o.findtext('vendorCode') or o.get('id') or '').strip()
            if sku:
                skus.add(sku)
            o.clear()
    return skus


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pairs', type=int, default=75)
    ap.add_argument('--cap', type=int, default=8, help='максимум пар з однієї категорії')
    ap.add_argument('--seed', type=int, default=20260916)
    ap.add_argument('--feed', default=os.path.join(BASE, 'output', 'noire_prom.xml'))
    ap.add_argument('--markers', default='мірквалон,тевзаніс')
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()

    from shared.utils.db import get_connection
    cur = get_connection().cursor()
    cur.execute("""select external_id, prom_id, portal_category, price, name
                   from prom_product_state
                   where status = 'on_display' and presence = 'available'
                     and price is not null and coalesce(is_variation, false) = false""")
    rows = cur.fetchall()
    skip = used_skus()
    feed = in_feed(a.feed) if os.path.exists(a.feed) else None
    print(f'на вітрині {len(rows)}, виключено з попередніх замірів {len(skip)}'
          + (f', у фіді {len(feed)}' if feed else ', фіду немає — перевірку пропущено'))

    cheap, exp = collections.defaultdict(list), collections.defaultdict(list)
    for r in rows:
        sku = r['external_id']
        if sku in skip or (feed is not None and sku not in feed):
            continue
        price = float(r['price'])
        rec = {'sku': sku, 'price': price, 'cat': r['portal_category'],
               'name': r['name'], 'prom_id': r['prom_id']}
        if price <= CHEAP_MAX:
            cheap[r['portal_category']].append(rec)
        elif price >= EXP_MIN:
            exp[r['portal_category']].append(rec)

    rng = random.Random(a.seed)
    cats = sorted(set(cheap) & set(exp), key=lambda k: -min(len(cheap[k]), len(exp[k])))
    pairs = []
    for rnd in range(1, a.cap + 1):            # по колу: спершу 1 пара з кожної категорії
        for k in cats:
            if len(pairs) >= a.pairs:
                break
            pool_c = [x for x in cheap[k] if x['sku'] not in {p[0]['sku'] for p in pairs}]
            pool_e = [x for x in exp[k] if x['sku'] not in {p[1]['sku'] for p in pairs}]
            if not pool_c or not pool_e:
                continue
            pairs.append((rng.choice(pool_c), rng.choice(pool_e)))
        if len(pairs) >= a.pairs:
            break
    if len(pairs) < a.pairs:
        sys.exit(f'зібрано лише {len(pairs)} пар із {a.pairs} — послабити --cap або межі цін')

    m1, m2 = a.markers.split(',')
    conf = {
        'active': True,
        'protocol': 'docs/prom_price_threshold_experiment_plan.md',
        'created': '2026-09-16',
        'question': 'чи залежить потрапляння у видачу від ціни картки',
        'design': {'pairs': len(pairs), 'cheap_max': CHEAP_MAX, 'expensive_min': EXP_MIN,
                   'field': 'keywords_ua', 'matched_by': 'portal_category', 'seed': a.seed},
        'groups': [
            {'name': 'cheap', 'lang': 'ua', 'marker': m1, 'skus': [c['sku'] for c, _ in pairs]},
            {'name': 'expensive', 'lang': 'ua', 'marker': m2, 'skus': [e['sku'] for _, e in pairs]},
        ],
        'prom_ids': {x['sku']: x['prom_id'] for pr in pairs for x in pr},
        'pairs': [{'cat': c['cat'], 'cheap': c['sku'], 'cheap_price': c['price'],
                   'expensive': e['sku'], 'expensive_price': e['price']} for c, e in pairs],
    }
    pc = [c['price'] for c, _ in pairs]
    pe = [e['price'] for _, e in pairs]
    print(f'пар: {len(pairs)} у {len({p["cat"] for p in conf["pairs"]})} категоріях')
    print(f'  дешеві:  медіана {sorted(pc)[len(pc)//2]:.0f} грн, від {min(pc):.0f} до {max(pc):.0f}')
    print(f'  дорогі:  медіана {sorted(pe)[len(pe)//2]:.0f} грн, від {min(pe):.0f} до {max(pe):.0f}')
    by_cat = collections.Counter(p['cat'] for p in conf['pairs'])
    print('  категорії:', dict(by_cat.most_common()))
    assert not (set(conf['groups'][0]['skus']) & set(conf['groups'][1]['skus'])), 'SKU у двох групах'
    if a.write:
        json.dump(conf, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'→ {OUT}')
    else:
        print('(пробний прогін, файл не записано — додати --write)')


if __name__ == '__main__':
    main()
