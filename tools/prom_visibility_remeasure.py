#!/usr/bin/env python3
"""Парний повторний замір видимості Prom: ті самі картки, що в базовому замірі 12.09.

Скіл: .claude/skills/prom/SKILL-31-prom-search.md (методика, пастки розмітки).

Для кожної картки з базового файлу:
  Q1  точна ПОТОЧНА назва_ua, /ua/search, 2 прогони (видача «мигає»)
  Q2  точна назва_ua від 12.09 — лише якщо назва відтоді змінилась (1 прогін):
      відділяє ефект зміни назви від зміни індексу
  Q3  реалістичний запит «тип + бренд» з наших keywords_ua, 2 прогони, + total видачі
  Q4  точна назва рос. у рос. пошуку (prom.ua/search), 1 прогін
Живий стан картки — з API (/products/list): status, presence. Картки не на
вітрині / не в наявності окремо: Prom їх може не показувати взагалі, це не
«пошук не знайшов».

Контроль: SO5178 за власною назвою до і після; без нього звіт не будується.

    python3 tools/prom_visibility_remeasure.py --base docs/prom_visibility_20260912.tsv \
        --out docs/prom_visibility_20260915.tsv [--limit 5]
"""
import argparse
import csv
import html
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
import prom_search as PS  # noqa: E402
from prom_api import call  # noqa: E402

_BLOCK = PS._BLOCK


def search(q, pages=3, lang='ua'):
    """Як prom_search.search, але з вибором мови пошуку і total видачі. → (results, total)."""
    out, seen, pos, total = [], set(), 0, None
    root = 'https://prom.ua/ua/search' if lang == 'ua' else 'https://prom.ua/search'
    al = 'uk-UA,uk;q=0.9' if lang == 'ua' else 'ru-RU,ru;q=0.9'
    for pg in range(1, pages + 1):
        u = root + '?search_term=' + urllib.parse.quote(q) + (f'&page={pg}' if pg > 1 else '')
        req = urllib.request.Request(u, headers={'User-Agent': PS.UA, 'Accept-Language': al})
        t = None
        for attempt in range(3):
            try:
                t = urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'ignore')
                break
            except Exception:
                time.sleep(5 * (attempt + 1))
        if t is None:
            raise RuntimeError(f'сторінка {pg} не відповіла: {q[:40]}')
        if total is None:
            i = t.find('ListingPage')
            m = re.search(r'"total"\s*:\s*(\d+)', t[i:i + 20000]) if i >= 0 else None
            total = int(m.group(1)) if m else -1
        tags = [(m.start(), m.group(0)) for m in _BLOCK.finditer(t)]
        if not tags:
            break
        for i, (s, tag) in enumerate(tags):
            pid = re.search(r'data-product-id="(\d+)"', tag)
            cid = re.search(r'data-company-id="(\d+)"', tag)
            pos += 1
            p = pid.group(1) if pid else ''
            if p and p in seen:
                continue
            seen.add(p)
            out.append({'pos': pos, 'pid': p, 'company_id': cid.group(1) if cid else ''})
        if len(tags) < 10:
            break
        time.sleep(PS.PAUSE)
    return out, total


def api_state():
    out, last = {}, None
    while True:
        params = {'limit': 1000}
        if last:
            params['last_id'] = last
        r = call('GET', '/products/list', None, params=params)
        if r.status_code != 200:
            sys.exit(f'API HTTP {r.status_code}: {r.text[:120]}')
        ps = r.json().get('products') or []
        if not ps:
            break
        for p in ps:
            out[str(p.get('id'))] = {'status': p.get('status'), 'presence': p.get('presence'),
                                     'date_modified': p.get('date_modified')}
        last = ps[-1]['id']
        time.sleep(0.5)
    return out


def medium_query(kws, brand, name):
    """Реалістичний запит «тип + бренд»: перший ключ, що містить бренд і має 2–4 слова."""
    b = (brand or '').lower().split()[0] if brand else ''
    for k in kws:
        w = k.split()
        if b and b in k.lower() and 2 <= len(w) <= 4:
            return k
    first = next((k for k in kws if len(k.split()) <= 2), kws[0] if kws else name.split()[0])
    return f'{first} {brand}'.strip() if brand else first


def mcnemar(b, c):
    """Точний двобічний тест МакНемара (біном, p=0.5) для незбіжних пар b, c."""
    n = b + c
    if not n:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    pos = PS.control()
    print(f'контроль до: {PS.CONTROL[0]} на {pos}-й позиції', flush=True)
    base = list(csv.DictReader(open(a.base, encoding='utf-8'), delimiter='\t'))
    if a.limit:
        base = base[:a.limit]
    if not os.path.exists(PS.FEED) or time.time() - os.path.getmtime(PS.FEED) > 12 * 3600:
        urllib.request.urlretrieve(PS.FEED_URL, PS.FEED + '.tmp')   # опублікований фід (кеш 12 год)
        os.replace(PS.FEED + '.tmp', PS.FEED)
    offers = {(o.findtext('vendorCode') or o.get('id') or '').strip(): o
              for o in ET.parse(PS.FEED).getroot().iter('offer')}
    live = api_state()
    print(f'карток у базі: {len(base)} · у фіді: {len(offers)} · у API: {len(live)}', flush=True)

    rows = []
    for i, b in enumerate(base, 1):
        o = offers.get(b['sku'])
        st = live.get(str(b['prom_id']), {})
        r = {'sku': b['sku'], 'prom_id': b['prom_id'], 'base_found': int(b['found_pos'] or 0),
             'base_presence': b.get('presence'), 'status': st.get('status'), 'presence': st.get('presence'),
             'in_feed': int(o is not None)}
        if o is None:
            rows.append(r)
            continue
        name_ua = (o.findtext('name_ua') or '').strip()
        name_ru = (o.findtext('name') or '').strip()
        kws = [x.strip() for x in (o.findtext('keywords_ua') or '').split(',') if x.strip()]
        brand = (o.findtext('vendor') or '').strip()
        r.update(name_ua=name_ua, base_name=b['name'], name_changed=int(nn(name_ua) != nn(b['name'])))
        try:
            p1 = [PS.locate(search(name_ua)[0], b['prom_id'])[0] for _ in range(2)]
            r.update(q1_a=p1[0], q1_b=p1[1], q1_found=int(any(p1)))
            if r['name_changed']:
                r['q2_old_name'] = PS.locate(search(b['name'])[0], b['prom_id'])[0]
            mq = medium_query(kws, brand, name_ua)
            res3 = [search(mq) for _ in range(2)]
            p3 = [PS.locate(x[0], b['prom_id'])[0] for x in res3]
            r.update(q3_query=mq, q3_a=p3[0], q3_b=p3[1], q3_found=int(any(p3)), q3_total=res3[0][1],
                     q3_ours_any=int(any(x['company_id'] == PS.OUR_COMPANY for x in res3[0][0] + res3[1][0])))
            r['q4_ru'] = PS.locate(search(name_ru, lang='ru')[0], b['prom_id'])[0] if name_ru else ''
        except RuntimeError as e:
            r['error'] = str(e)
        rows.append(r)
        if i % 10 == 0:
            k = sum(1 for x in rows if x.get('q1_found'))
            print(f'  {i}/{len(base)} · точна назва: знайдено {k}', flush=True)
        time.sleep(PS.PAUSE)

    pos2 = PS.control()
    cols = ['sku', 'prom_id', 'status', 'presence', 'base_presence', 'in_feed', 'base_found', 'q1_a', 'q1_b',
            'q1_found', 'name_changed', 'q2_old_name', 'q3_query', 'q3_a', 'q3_b', 'q3_found', 'q3_total',
            'q3_ours_any', 'q4_ru', 'error', 'name_ua', 'base_name']
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write('\t'.join(cols) + '\n')
        for r in rows:
            f.write('\t'.join(str(r.get(c, '')) for c in cols) + '\n')

    ok = [r for r in rows if 'q1_found' in r]
    shown = [r for r in ok if r['status'] == 'on_display' and r['presence'] == 'available']
    print(f'\nконтроль після: {PS.CONTROL[0]} на {pos2}-й позиції')
    for title, grp in (('усі виміряні', ok), ('на вітрині й у наявності зараз', shown)):
        k0 = sum(1 for r in grp if r['base_found']); k1 = sum(1 for r in grp if r['q1_found'])
        bb = sum(1 for r in grp if r['base_found'] and not r['q1_found'])
        cc = sum(1 for r in grp if not r['base_found'] and r['q1_found'])
        lo, hi = PS.wilson(k1, len(grp))
        print(f'[{title}] n={len(grp)} · 12.09: {k0} → зараз: {k1} ({k1 / max(1, len(grp)):.1%}, 95 % {lo:.1%}–{hi:.1%}) '
              f'· стали видимі {cc}, зникли {bb} · МакНемар p={mcnemar(bb, cc):.3f}')
    ch = [r for r in ok if r['name_changed']]
    print(f'назва змінилась з 12.09: {len(ch)} · з них знайдено за новою {sum(r["q1_found"] for r in ch)}, '
          f'за старою {sum(1 for r in ch if r.get("q2_old_name"))}')
    print(f'Q1 обидва прогони збіглися: {sum(1 for r in ok if bool(r["q1_a"]) == bool(r["q1_b"]))}/{len(ok)}')
    k3 = sum(r.get('q3_found', 0) for r in ok)
    print(f'Q3 «тип + бренд»: картку знайдено {k3}/{len(ok)} · будь-яка наша картка у видачі: '
          f'{sum(r.get("q3_ours_any", 0) for r in ok)}/{len(ok)}')
    k4 = sum(1 for r in ok if r.get('q4_ru'))
    print(f'Q4 рос. назва в рос. пошуку: {k4}/{len(ok)}')
    print(f'не в фіді: {sum(1 for r in rows if not r["in_feed"])} · помилки мережі: {sum(1 for r in rows if r.get("error"))}')
    print(f'→ {a.out}')


def nn(s):
    return ' '.join((s or '').lower().split())


if __name__ == '__main__':
    main()
