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
# ДЕФІС, не крапка: хоста api.seller.rozetka.com.ua не існує взагалі
API = 'https://api-seller.rozetka.com.ua'
CACHE = os.path.join(BASE, 'data', 'rozetka_category_options.json')


def fetch(s, cid):
    for attempt in range(3):
        try:
            r = s.get(f'{API}/market-categories/category-options',
                      params={'category_id': cid}, timeout=45)
            if r.status_code != 200:
                return None
            d = r.json()
            if not d.get('success'):
                return None
            c = d.get('content')
            # content приходить РЯДКОМ із JSON усередині, а не масивом
            return json.loads(c) if isinstance(c, str) else c
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
        # одна характеристика повторюється рядком на кожне своє значення —
        # групуємо за назвою й окремо тримаємо ті, що є ФІЛЬТРАМИ категорії
        allnames, filters = set(), set()
        for x in items:
            if not isinstance(x, dict):
                continue
            nm = str(x.get('name') or '').strip()
            if not nm:
                continue
            allnames.add(nm)
            if str(x.get('filter_type') or '').lower() not in ('disable', 'none', ''):
                filters.add(nm)
        have = set(ours[cid])
        gaps.append({'category_id': rz_id, 'name': rz_name, 'offers': n,
                     'rozetka_options': len(allnames), 'rozetka_filters': len(filters),
                     'ours': len(have),
                     'missing': sorted(allnames - have),
                     'missing_filters': sorted(filters - have)})
    json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
    out = os.path.join(BASE, 'docs', 'rozetka_option_gaps.json')
    json.dump(gaps, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    tot_off = sum(g['offers'] for g in gaps)
    print(f'\nрозібрано категорій: {len(gaps)} ({tot_off} офферів)')
    print(f"{'офферів':>8} {'усього':>7} {'фільтрів':>9} {'у нас':>6} {'бракує фільтрів':>16}  категорія")
    for g in sorted(gaps, key=lambda x: -x['offers'])[:15]:
        print(f"{g['offers']:8} {g['rozetka_options']:7} {g['rozetka_filters']:9} "
              f"{g['ours']:6} {len(g['missing_filters']):16}  {g.get('name','')[:30]}")
    freq = collections.Counter()
    for g in gaps:
        for m in g['missing_filters']:
            freq[m] += g['offers']
    print('\nвідсутні ФІЛЬТРИ (зважено за офферами):')
    for k, v in freq.most_common(20):
        print(f'   {v:6}  {k}')
    print(f'\n→ {out}')


if __name__ == '__main__':
    main()
