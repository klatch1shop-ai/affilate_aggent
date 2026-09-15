#!/usr/bin/env python3
"""Пошук Prom справжнім браузером: обидва блоки видачі — основний і «частковий збіг».

Навіщо (15.09.2026): `prom_search.search()` читає HTML, де контейнер
`partial_match_products` порожній — його заповнює браузер окремим запитом.
За документацією Prom товари, знайдені за ключовими словами, показуються
саме в другій частині видачі. Тож «0 знайдено» від HTML-інструмента означає
лише «немає в основному блоці». Цей інструмент бачить обидва блоки.

Лише читання. Потрібен Camoufox (є у venv ноутбука).

    venv/bin/python tools/prom_search_browser.py --query "..."            # обидва блоки, ← НАШ
    venv/bin/python tools/prom_search_browser.py --tests tests.tsv --out res.tsv
        # tests.tsv: test<TAB>sku<TAB>prom_id<TAB>query  (кожен запит — 2 прогони)

Позитивний контроль: SO5178 за поточною назвою має бути в основному блоці.
"""
import argparse
import csv
import os
import sys
import time
import urllib.parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
import prom_search as PS  # noqa: E402

JS = """() => {
  const out = [];
  for (const b of document.querySelectorAll('[data-qaid="product_block"]')) {
    const part = !!b.closest('[data-qaid="partial_match_products"], [class*="partial"], [data-qaid*="partial"]');
    out.push({pid: b.getAttribute('data-product-id') || '', cid: b.getAttribute('data-company-id') || '',
              block: part ? 'partial' : 'main'});
  }
  const pc = document.querySelector('[data-qaid="partial_match_products"]');
  return {items: out, partial_container: !!pc, partial_len: pc ? pc.querySelectorAll('[data-qaid="product_block"]').length : -1};
}"""


def search_both(page, q):
    """→ {'main': [(pos, pid, cid)], 'partial': [...], 'partial_container': bool}"""
    page.goto('https://prom.ua/ua/search?search_term=' + urllib.parse.quote(q), wait_until='domcontentloaded')
    page.wait_for_timeout(3500)
    for _ in range(8):                       # гортаємо — частковий блок довантажується внизу
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(900)
    page.wait_for_timeout(2500)
    r = page.evaluate(JS)
    res = {'main': [], 'partial': [], 'partial_container': r['partial_container']}
    seen = set()
    for it in r['items']:
        if it['pid'] in seen:
            continue
        seen.add(it['pid'])
        lst = res[it['block']]
        lst.append((len(lst) + 1, it['pid'], it['cid']))
    return res


def where(res, prom_id):
    for blk in ('main', 'partial'):
        for pos, pid, _ in res[blk]:
            if pid == str(prom_id):
                return f'{blk}:{pos}'
    return ''


def ours(res):
    return [f'{b}:{p}:{pid}' for b in ('main', 'partial') for p, pid, cid in res[b] if cid == PS.OUR_COMPANY]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--query')
    ap.add_argument('--tests')
    ap.add_argument('--out')
    a = ap.parse_args()
    from camoufox.sync_api import Camoufox
    with Camoufox(headless=True, humanize=True, geoip=True, locale='uk-UA') as br:
        page = br.new_page()
        page.set_default_timeout(45000)
        ctl = search_both(page, PS.control_name())
        w = where(ctl, PS.CONTROL[1])
        print(f'контроль {PS.CONTROL[0]}: {w or "НЕ ЗНАЙДЕНО"} · основний {len(ctl["main"])}, '
              f'частковий {len(ctl["partial"])} (контейнер {ctl["partial_container"]})', flush=True)
        if not w.startswith('main'):
            sys.exit('КОНТРОЛЬ НЕ ПРОЙДЕНО — результати не будуються')
        if a.query:
            r = search_both(page, a.query)
            for blk in ('main', 'partial'):
                print(f'— {blk}: {len(r[blk])}')
                for pos, pid, cid in r[blk][:60]:
                    print(f'   {pos:3} {pid:>11} {cid:>8}' + ('  ← НАШ' if cid == PS.OUR_COMPANY else ''))
            return
        rows = list(csv.reader(open(a.tests, encoding='utf-8'), delimiter='\t'))
        out = []
        for i, (test, sku, prom_id, q) in enumerate(rows, 1):
            runs = []
            for _ in range(2):
                r = search_both(page, q)
                runs.append((where(r, prom_id), len(r['main']), len(r['partial']), r['partial_container'], ours(r)))
                time.sleep(2)
            rec = {'test': test, 'sku': sku, 'prom_id': prom_id, 'query': q,
                   'run1': runs[0][0], 'run2': runs[1][0], 'main_n': runs[0][1], 'partial_n': runs[0][2],
                   'partial_container': runs[0][3], 'ours_on_page': ';'.join(runs[0][4])[:200]}
            out.append(rec)
            print(f"[{i}/{len(rows)}] {test:12} {sku:8} {rec['run1'] or '—':12} {rec['run2'] or '—':12} "
                  f"осн {rec['main_n']:3} част {rec['partial_n']:3} | {q[:60]}", flush=True)
        ctl2 = where(search_both(page, PS.control_name()), PS.CONTROL[1])
        print(f'контроль після: {ctl2 or "НЕ ЗНАЙДЕНО"}')
        if a.out:
            with open(a.out, 'w', encoding='utf-8') as f:
                cols = list(out[0].keys())
                f.write('\t'.join(cols) + '\n')
                for r in out:
                    f.write('\t'.join(str(r[c]) for c in cols) + '\n')
            print(f'→ {a.out}')


if __name__ == '__main__':
    main()
