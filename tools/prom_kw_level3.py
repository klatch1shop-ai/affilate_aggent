#!/usr/bin/env python3
"""Рівень 3: терміни з живих карток конкурентів у каталозі Prom.

Рівні 1-2 працюють із нашими даними. Цей рівень дає те, чого в них немає:
як товар називають інші продавці тієї самої категорії. Для поля keywords
це найточніше джерело — там уже відсіяно те, за чим ніхто не шукає.

Метод той самий, що в listing_pattern_analyzer: беремо видачу, знімаємо
СТРУКТУРУ (частотні n-грами з назв), не копіюємо чужий текст. Фраза
потрапляє в кандидати, якщо трапляється щонайменше у MIN_HITS карток —
один продавець це здогадка, п'ять це вже термінологія ринку.

Prom віддає 403 на звичайний requests, тому Camoufox.

Запуск:
    python3 tools/prom_kw_level3.py --limit 200
    python3 tools/prom_kw_level3.py --report
"""
import argparse
import collections
import json
import os
import re
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(BASE_DIR, 'tools'))
OUT = os.path.join(BASE_DIR, 'docs', 'prom_kw_level3.json')
LEVEL1 = os.path.join(BASE_DIR, 'docs', 'prom_kw_level1_all.json')

MIN_HITS = 3          # у скількох чужих картках має трапитись фраза
MIN_WORDS, MAX_WORDS = 2, 4
PAUSE = 2.0
STOP = {'купити', 'замовити', 'ціна', 'дешево', 'недорого', 'оптом',
        'доставка', 'україні', 'києві', 'інтернет', 'магазин', 'шт'}


def ngrams(title: str):
    t = re.sub(r'[^\w\sʼ\'-]', ' ', title.lower())
    words = [w for w in t.split() if len(w) > 1 and not w.isdigit()]
    for n in range(MIN_WORDS, MAX_WORDS + 1):
        for i in range(len(words) - n + 1):
            g = words[i:i + n]
            if any(x in STOP for x in g):
                continue
            yield ' '.join(g)


def harvest(page, query: str) -> list:
    """Частотні n-грами з назв товарів у видачі Prom за запитом."""
    url = 'https://prom.ua/ua/search?search_term=' + query.replace(' ', '%20')
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_timeout(3500)
    titles = []
    for sel in ('[data-qaid="product_name"]', 'span[data-qaid="product_name"]',
                'a[data-qaid="product_link"]'):
        try:
            titles += [t.strip() for t in page.locator(sel).all_inner_texts()]
        except Exception:
            pass
        if titles:
            break
    freq = collections.Counter()
    for t in dict.fromkeys(titles):
        freq.update(set(ngrams(t)))
    return [(g, c) for g, c in freq.most_common(40) if c >= MIN_HITS], len(titles)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=200)
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()

    if a.report:
        data = json.load(open(OUT))
        ok = [k for k, v in data.items() if v.get('candidates')]
        print(f'запитів оброблено: {len(data)} | з результатом: {len(ok)}')
        for k, v in list(data.items())[:12]:
            print(f"\n  «{k}» — карток у видачі {v.get('titles', 0)}")
            for g, c in v.get('candidates', [])[:6]:
                print(f'      {c:3}× {g}')
        return

    rows = json.load(open(LEVEL1))
    need = [r for r in rows if len(r['level1']) < 3][:a.limit]
    # запит = найінформативніша фраза, яка в нас уже є
    queries = []
    for r in need:
        q = (r['level1'] or [r['category']])[0]
        if q and q not in queries:
            queries.append(q)
    print(f'товарів у роботі: {len(need)} → унікальних запитів: {len(queries)}',
          flush=True)

    done = json.load(open(OUT)) if os.path.exists(OUT) else {}
    from camoufox.sync_api import Camoufox
    with Camoufox(headless=True, humanize=True, geoip=True, locale='uk-UA') as br:
        page = br.new_page()
        page.set_default_timeout(45000)
        for i, q in enumerate(queries, 1):
            if q in done:
                continue
            try:
                cands, n = harvest(page, q)
                done[q] = {'candidates': cands, 'titles': n}
                print(f'  [{i}/{len(queries)}] «{q}» — {n} карток, '
                      f'{len(cands)} кандидатів', flush=True)
            except Exception as e:
                done[q] = {'candidates': [], 'error': type(e).__name__}
                print(f'  [{i}/{len(queries)}] «{q}» — {type(e).__name__}',
                      flush=True)
            if i % 5 == 0:
                json.dump(done, open(OUT, 'w'), ensure_ascii=False, indent=1)
            time.sleep(PAUSE)
    json.dump(done, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(f'готово: {len(done)} запитів → {OUT}')


if __name__ == '__main__':
    main()
