#!/usr/bin/env python3
"""
tools/rozetka_category_options.py
==================================
Збирає перелік характеристик (фільтрів) категорій Rozetka і звіряє з тим,
що ми віддаємо у фіді.

Навіщо: зауваження менеджера Rozetka (#7253098, 24.08.2026) — «важливо, як
мінімум, прописати всі параметри, які є фільтрами у категорії». Без них товар
не потрапляє у відфільтровану вибірку покупця й лишається невидимим.

    GET /market-categories/category-options?category_id={id}

Токен ROZETKA_API_TOKEN є ТІЛЬКИ на сервері — запускати там.

    python3 tools/rozetka_category_options.py --feed output/toptul_rozetka.xml
"""
import os, sys, json, time, argparse, collections
import xml.etree.ElementTree as ET
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
API = 'https://api.seller.rozetka.com.ua'
CACHE = os.path.join(BASE, 'data', 'rozetka_category_options.json')


def fetch(s, cid):
    for attempt in range(3):
        try:
            r = s.get(f'{API}/market-categories/category-options',
                      params={'category_id': cid}, timeout=45)
            if r.status_code != 200:
                return None
            d = r.json()
            return d.get('content') or d.get('data') or d
        except Exception:
            if attempt == 2:
                return None
            time.sleep(2 * (attempt + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--feed', required=True)
    a = ap.parse_args()

    root = ET.parse(a.feed).getroot()
    # У фіді <offer><categoryId> несе НАШ внутрішній номер, а справжній
    # ідентифікатор Rozetka лежить у <category id="N" rz_id="...">.
    # Перший прогін пішов із внутрішніми номерами й дав «не отримано» на всіх.
    rz = {}
    for c in root.findall('.//categories/category'):
        if c.get('id') and c.get('rz_id'):
            rz[c.get('id')] = (c.get('rz_id'), (c.text or '').strip())
    print(f'категорій з rz_id: {len(rz)}')
    cats = collections.Counter()
    ours = collections.defaultdict(collections.Counter)
    for o in root.findall('.//offer'):
        cid = (o.findtext('categoryId') or '').strip()
        if not cid:
            continue
        cats[cid] += 1
        for p in o.findall('param'):
            nm = (p.get('name') or '').strip()
            if nm:
                ours[cid][nm] += 1
    print(f'категорій у фіді: {len(cats)} | офферів: {sum(cats.values())}')

    s = requests.Session()
    s.headers.update({'Authorization': f"Bearer {os.getenv('ROZETKA_API_TOKEN')}",
                      'Content-Language': 'uk', 'Accept': 'application/json'})
    cache = json.load(open(CACHE, encoding='utf-8')) if os.path.exists(CACHE) else {}
    gaps = []
    for i, (cid, n) in enumerate(cats.most_common(), 1):
        rz_id, rz_name = rz.get(cid, (None, ''))
        if not rz_id:
            continue
        if rz_id not in cache:
            d = fetch(s, rz_id)
            if d is None:
                print(f'  {rz_id} {rz_name}: не отримано', file=sys.stderr)
                continue
            cache[rz_id] = d
            time.sleep(0.4)
            if i % 20 == 0:
                json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
                print(f'  {i}/{len(cats)}', file=sys.stderr)
        items = cache[rz_id]
        if isinstance(items, dict):
            items = items.get('options') or items.get('items') or []
        names = {str(x.get('name') or x.get('title') or '').strip()
                 for x in items if isinstance(x, dict)}
        names.discard('')
        have = set(ours[cid])
        miss = sorted(names - have)
        gaps.append({'category_id': rz_id, 'name': rz_name, 'offers': n, 'rozetka_options': len(names),
                     'ours': len(have), 'missing': miss})
    json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
    out = os.path.join(BASE, 'docs', 'rozetka_option_gaps.json')
    json.dump(gaps, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    tot_off = sum(g['offers'] for g in gaps)
    print(f'\nрозібрано категорій: {len(gaps)} ({tot_off} офферів)')
    print(f"{'офферів':>8} {'у Rozetka':>10} {'у нас':>6}  категорія")
    for g in sorted(gaps, key=lambda x: -x['offers'])[:15]:
        print(f"{g['offers']:8} {g['rozetka_options']:10} {g['ours']:6}  {g.get('name','')[:34]}")
    freq = collections.Counter()
    for g in gaps:
        for m in g['missing']:
            freq[m] += g['offers']
    print('\nнайчастіші відсутні характеристики (зважено за офферами):')
    for k, v in freq.most_common(20):
        print(f'   {v:6}  {k}')
    print(f'\n→ {out}')


if __name__ == '__main__':
    main()
