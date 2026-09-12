#!/usr/bin/env python3
"""Пошук Prom без браузера: чи знаходиться КОНКРЕТНА наша картка і на якій позиції.

Сторінка `prom.ua/ua/search?search_term=…&page=N` віддає звичайний HTML
(перевірено 12.09.2026), і в кожному блоці товару вже є все потрібне:

    data-product-id="3152112459"   ← prom_id картки
    data-company-id="4053918"      ← магазин (наш — 4053918, як cs4053918.prom.ua)
    data-qaid="product_name" / "company_name" / "product_price"

Звідси головна різниця з попередніми замірами (`prom_visibility_check.py`,
ручний `walk()` від 08.09): **картка звіряється за prom_id, а не за іменем
продавця й не за схожістю назви.** Обидва старі способи вже давали хибні
«знайдено» — у видачі траплялась ІНША наша картка (SX4628, SO5943).

Що з'ясовано про розмітку, щоб не наступити вдруге:
  * `&page=N` працює (друга сторінка без спільних товарів із першою);
    `&p=N` — ігнорується й повертає першу сторінку;
  * `data-qa-advtoken` стоїть на КОЖНОМУ блоці — це не ознака реклами;
  * `data-position-qaid` починається з 1 на кожній сторінці — позицію
    рахуємо самі, наскрізно;
  * та сама картка буває у видачі двічі (SO5178: 1-ша і 11-та позиція) —
    рахується перше входження.

Позитивний контроль вбудовано: SO5178 за своєю точною назвою має бути в
перших 10. Не знайшов — прогін зупиняється, а не звітує нулі.

    python3 tools/prom_search.py --query "вібратор lelo"
    python3 tools/prom_search.py --sample 150 --out docs/prom_visibility_20260912.tsv
    python3 tools/prom_search.py --skus SO5178,SO5463
"""
import argparse
import collections
import html
import json
import math
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED_URL = 'https://raw.githubusercontent.com/klatch1shop-ai/noire-feed/main/noire_prom.xml'
FEED = os.path.join(BASE_DIR, 'data', 'prom', 'noire_prom_published.xml')
IDS = os.path.join(BASE_DIR, 'data', 'prom', 'prom_ids.json')
OUR_COMPANY = '4053918'
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/128.0 Safari/537.36')
PAUSE = float(os.getenv('PROM_PAUSE', '2.0'))
CONTROL = ('SO5178', '3152112459',
           'Батіг Art of Sex з рукояттю, натуральна шкіра, колір чорний, довжина - 120 см')

_BLOCK = re.compile(r'<[^>]*data-qaid="product_block"[^>]*>')


def search(q: str, pages: int = 3) -> list:
    """→ [{pos, pid, company_id, company, name, price}] без повторів pid."""
    out, seen, pos = [], set(), 0
    for pg in range(1, pages + 1):
        u = ('https://prom.ua/ua/search?search_term=' + urllib.parse.quote(q)
             + (f'&page={pg}' if pg > 1 else ''))
        req = urllib.request.Request(u, headers={
            'User-Agent': UA, 'Accept-Language': 'uk-UA,uk;q=0.9'})
        t = None
        for attempt in range(3):
            try:
                t = urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'ignore')
                break
            except Exception:
                time.sleep(5 * (attempt + 1))
        if t is None:
            raise RuntimeError(f'сторінка {pg} не відповіла: {q[:40]}')
        tags = [(m.start(), m.group(0)) for m in _BLOCK.finditer(t)]
        if not tags:
            break
        for i, (s, tag) in enumerate(tags):
            body = t[s:tags[i + 1][0] if i + 1 < len(tags) else s + 20000]
            pid = re.search(r'data-product-id="(\d+)"', tag)
            cid = re.search(r'data-company-id="(\d+)"', tag)
            nm = re.search(r'data-qaid="product_name"[^>]*>([^<]+)<', body)
            co = re.search(r'data-qaid="company_name"[^>]*>([^<]{1,300})<', body)
            pr = re.search(r'data-qaid="product_price"[^>]*data-qaprice="([\d.]+)"', body)
            pos += 1
            p = pid.group(1) if pid else ''
            if p and p in seen:
                continue
            seen.add(p)
            out.append({'pos': pos, 'pid': p, 'company_id': cid.group(1) if cid else '',
                        'company': html.unescape(co.group(1)).strip() if co else '',
                        'name': html.unescape(nm.group(1)).strip() if nm else '',
                        'price': pr.group(1) if pr else ''})
        if len(tags) < 10:
            break
        time.sleep(PAUSE)
    return out


def locate(results: list, prom_id: str) -> tuple:
    """(позиція нашої картки або 0, позиція будь-якої ІНШОЇ нашої картки або 0)."""
    mine = next((r['pos'] for r in results if r['pid'] == str(prom_id)), 0)
    other = next((r['pos'] for r in results
                  if r['company_id'] == OUR_COMPANY and r['pid'] != str(prom_id)), 0)
    return mine, other


def control():
    res = search(CONTROL[2], pages=1)
    mine, _ = locate(res, CONTROL[1])
    if not mine:
        sys.exit(f'КОНТРОЛЬ НЕ ПРОЙДЕНО: {CONTROL[0]} не знайдено за власною назвою '
                 f'(блоків {len(res)}). Звіт не будується.')
    return mine


def load_catalogue() -> list:
    """Опублікований фід Prom + prom_id з бази (знімок у data/prom/prom_ids.json)."""
    if not os.path.exists(FEED) or time.time() - os.path.getmtime(FEED) > 12 * 3600:
        os.makedirs(os.path.dirname(FEED), exist_ok=True)
        urllib.request.urlretrieve(FEED_URL, FEED + '.tmp')
        os.replace(FEED + '.tmp', FEED)
    with open(IDS, encoding='utf-8') as f:
        ids = {str(r['external_id']): r for r in json.load(f)}
    out = []
    for o in ET.parse(FEED).getroot().iter('offer'):
        sku = (o.findtext('vendorCode') or o.get('id') or '').strip()
        r = ids.get(sku)
        if not r:
            continue
        kw = [x.strip() for x in (o.findtext('keywords_ua') or '').split(',') if x.strip()]
        desc = re.sub(r'<[^>]+>', ' ', o.findtext('description_ua') or '')
        out.append({'sku': sku, 'prom_id': str(r['prom_id']),
                    'name': (o.findtext('name_ua') or '').strip(),
                    'category': r.get('portal_category') or '',
                    'cat_id': str(r.get('portal_category_id') or ''),
                    'price': r.get('price'), 'presence': r.get('presence'),
                    'keywords': kw, 'desc_len': len(re.sub(r'\s+', ' ', desc).strip()),
                    'params': len(o.findall('param')), 'pics': len(o.findall('picture'))})
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    if not n:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--query')
    ap.add_argument('--skus')
    ap.add_argument('--sample', type=int, default=0)
    ap.add_argument('--seed', type=int, default=20260912)
    ap.add_argument('--pages', type=int, default=3)
    ap.add_argument('--out')
    a = ap.parse_args()

    if a.query:
        for r in search(a.query, a.pages):
            mark = ' ← НАШ' if r['company_id'] == OUR_COMPANY else ''
            print(f"{r['pos']:3} {r['pid']:>11} {r['company'][:22]:22} {r['price']:>7}  {r['name'][:70]}{mark}")
        return

    pos = control()
    print(f'контроль: {CONTROL[0]} на {pos}-й позиції за власною назвою')
    cat = load_catalogue()
    if a.skus:
        want = set(a.skus.split(','))
        items = [c for c in cat if c['sku'] in want]
    else:
        # Випадкова вибірка з УСЬОГО каталогу, а не з порядку /products/list:
        # той упорядкований за id і дав 34.7 % замість 9.3 % 05.09 (вік картки).
        items = random.Random(a.seed).sample(cat, min(a.sample or 40, len(cat)))
    print(f'карток: {len(items)} · запит = точна назва_ua · сторінок {a.pages}')

    rows = []
    for i, it in enumerate(items, 1):
        try:
            res = search(it['name'], a.pages)
        except RuntimeError as e:
            print('  ', e)
            continue
        mine, other = locate(res, it['prom_id'])
        rows.append({**it, 'found_pos': mine, 'other_ours_pos': other, 'seen': len(res)})
        if i % 10 == 0:
            k = sum(1 for r in rows if r['found_pos'])
            print(f'  {i}/{len(items)} · знайдено {k}', flush=True)
        time.sleep(PAUSE)

    pos2 = control()
    k = sum(1 for r in rows if r['found_pos'])
    lo, hi = wilson(k, len(rows))
    print(f'\nконтроль після прогону: {CONTROL[0]} на {pos2}-й позиції')
    print(f'знайдено за точною назвою: {k}/{len(rows)} = {k / max(1, len(rows)):.1%} '
          f'(95 % інтервал {lo:.1%}–{hi:.1%})')
    print(f'з них на 1-й сторінці: {sum(1 for r in rows if 0 < r["found_pos"] <= 10)}')
    print(f'не знайдено, але у видачі була ІНША наша картка: '
          f'{sum(1 for r in rows if not r["found_pos"] and r["other_ours_pos"])}')
    if a.out:
        cols = ['sku', 'prom_id', 'found_pos', 'other_ours_pos', 'seen', 'cat_id', 'category',
                'price', 'presence', 'params', 'pics', 'desc_len', 'name']
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write('\t'.join(cols + ['name_len', 'kw_count', 'keywords']) + '\n')
            for r in rows:
                f.write('\t'.join(str(r.get(c, '')) for c in cols)
                        + f"\t{len(r['name'])}\t{len(r['keywords'])}\t{', '.join(r['keywords'])}\n")
        print(f'→ {a.out}')


if __name__ == '__main__':
    main()
