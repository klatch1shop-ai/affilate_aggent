#!/usr/bin/env python3
"""
tools/prom_competitor_scan.py
==============================
Скільки в нас конкурентів — за категоріями й брендами, на Prom.

ЧОМУ НОВИЙ ІНСТРУМЕНТ. `prom_dup_check.py` робить те саме, але через
Camoufox (браузер із антидетектом). 07.09.2026 він завис на старті:
15 хвилин роботи, 2 секунди процесорного часу, жодного рядка виводу.
Перевірка показала, що видача Prom **віддається звичайним HTTP** — 10
карток на сторінку з розміткою `data-qaid`. Браузер не потрібен.

Що рахує:
  • скільки різних продавців пропонують той самий товар;
  • хто з них трапляється найчастіше (прямі конкуренти);
  • розподіл за нашими категоріями й брендами.

Свої картки відсіюються за назвою магазину — інакше порівняємо себе з
собою (SKILL-18).

Тільки читання. Нічого не публікує й не змінює.

    python3 tools/prom_competitor_scan.py --n 120
    python3 tools/prom_competitor_scan.py --n 40 --brand "Art of Sex"
"""
import os, re, sys, json, time, random, argparse, collections
import xml.etree.ElementTree as ET
import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.path.join(BASE, 'output', 'noire_prom.xml')
OUT  = os.path.join(BASE, 'docs', 'prom_competitor_scan.json')

# Назви нашого магазину в різних написаннях — щоб не порахувати себе.
OURS = {'noire', 'noire intime', 'klatch1', 'klatch1 shop', 'cs4053918'}

HDR = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                     '(KHTML, like Gecko) Chrome/120 Safari/537.36',
       'Accept-Language': 'uk-UA,uk;q=0.9'}

SELLER = re.compile(r'data-qaid="company_name"[^>]*>([^<]{1,60})<')
PNAME  = re.compile(r'data-qaid="product_name"[^>]*>([^<]{1,200})<')


def load_offers():
    """sku → (назва, категорія, бренд) з нашого фіду Prom."""
    root = ET.parse(FEED).getroot()
    cats = {c.get('id'): (c.text or '') for c in root.iter('category')}
    out = []
    for o in root.iter('offer'):
        name = (o.findtext('name') or '').strip()
        if not name:
            continue
        out.append({
            'sku': o.get('id'),
            'name': name,
            'cat': cats.get(o.findtext('categoryId'), '?'),
            'brand': (o.findtext('vendor') or '').strip(),
        })
    return out


def query_for(item):
    """Пошуковий запит: бренд + модель без нашого артикула в дужках.

    Артикул у дужках — наш власний, у конкурентів його немає, і запит із
    ним знайшов би тільки нас.
    """
    n = re.sub(r'\s*\([^)]*\)\s*$', '', item['name'])
    return n[:90]


def search(sess, q):
    """Продавці, що пропонують схожий товар. Порожній список — не помилка."""
    url = 'https://prom.ua/ua/search'
    r = sess.get(url, params={'search_term': q}, timeout=30)
    if r.status_code != 200:
        return None
    html = r.text
    sellers = [s.strip() for s in SELLER.findall(html)]
    return [s for s in sellers if s.lower() not in OURS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=100)
    ap.add_argument('--brand')
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args()

    items = load_offers()
    if a.brand:
        items = [x for x in items if a.brand.lower() in x['brand'].lower()]
    random.seed(20260907)
    items = random.sample(items, min(a.n, len(items)))
    print(f'перевіряємо {len(items)} позицій\n')

    sess = requests.Session(); sess.headers.update(HDR)
    rows, fails = [], 0
    for i, it in enumerate(items, 1):
        q = query_for(it)
        try:
            sellers = search(sess, q)
        except Exception as e:
            sellers = None
        if sellers is None:
            fails += 1
        else:
            rows.append({**it, 'query': q,
                         'sellers': sorted(set(sellers)),
                         'n_sellers': len(set(sellers))})
        if i % 10 == 0:
            print(f'  {i}/{len(items)}')
        time.sleep(random.uniform(1.2, 2.4))

    json.dump(rows, open(a.out, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    if not rows:
        print('\nЖОДНОГО результату. Перевірка не зарахована (SKILL-21): '
              'спершу довести, що сканер уміє повертати ненуль.')
        sys.exit(1)

    print(f'\nзібрано: {len(rows)} позицій, помилок запиту {fails}')
    ns = [r['n_sellers'] for r in rows]
    print(f'продавців на позицію: сер {sum(ns)/len(ns):.1f}, '
          f'мін {min(ns)}, макс {max(ns)}')
    zero = sum(1 for n in ns if n == 0)
    print(f'позицій, де конкурентів не знайдено: {zero}')

    freq = collections.Counter()
    for r in rows:
        freq.update(r['sellers'])
    print(f'\nрізних продавців усього: {len(freq)}')
    print('топ-20 за кількістю наших позицій:')
    for s, c in freq.most_common(20):
        print(f'  {c:4}  {s}')

    bycat = collections.defaultdict(list)
    for r in rows:
        bycat[r['cat']].append(r['n_sellers'])
    print('\nза категоріями (позицій | сер. продавців):')
    for c, v in sorted(bycat.items(), key=lambda kv: -len(kv[1]))[:15]:
        print(f'  {len(v):4} | {sum(v)/len(v):5.1f}  {c[:50]}')

    bybr = collections.defaultdict(list)
    for r in rows:
        bybr[r['brand'] or '(без бренду)'].append(r['n_sellers'])
    print('\nза брендами (позицій | сер. продавців):')
    for b, v in sorted(bybr.items(), key=lambda kv: -len(kv[1]))[:15]:
        print(f'  {len(v):4} | {sum(v)/len(v):5.1f}  {b[:40]}')
    print(f'\n→ {a.out}')


if __name__ == '__main__':
    main()
