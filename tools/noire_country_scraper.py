#!/usr/bin/env python3
"""EasyToys → країна виробництва (Herkomst) для SKU без country.

Camoufox (антидетект + повний рендеринг JS) → пошук за назвою моделі →
розгортання блоку специфікацій → витяг поля Herkomst.

Критерій застосування СТРОГИЙ: усі значущі латинські токени нашої назви
мають бути присутні в назві картки EasyToys. Частковий збіг ("той самий
бренд, інша модель" або "той самий гель, інший смак") позначається
match_type='partial' і НЕ використовується для проставляння країни.

Результат → sexopt_country_lookup. Прогрес зберігається щоразу, тому
скрипт можна перервати і запустити знову — уже перевірені SKU пропускаються.
"""
import argparse
import re
import sys
import time

import psycopg2
import psycopg2.extras
from camoufox.sync_api import Camoufox

DB = dict(host='192.168.3.28', dbname='agentdb',
          user='agentadmin', password='1')
BASE = 'https://www.easytoys.nl'

# токени, які нічого не кажуть про конкретну модель
STOP = {
    'the', 'and', 'with', 'for', 'set', 'kit', 'pack', 'plus', 'pro', 'de',
    'van', 'een', 'met', 'ml', 'cm', 'mm', 'gr', 'gram', 'st', 'pcs', 'size',
    'edition', 'version', 'new', 'vibrator', 'dildo', 'plug', 'massager',
    'masturbator', 'lubricant', 'gel', 'toy', 'toys', 'sex', 'anal', 'silicone',
}

# колір: наш латинський варіант → нідерландський на картці
COLORS = {
    'black': 'zwart', 'white': 'wit', 'red': 'rood', 'pink': 'roze',
    'blue': 'blauw', 'green': 'groen', 'purple': 'paars', 'violet': 'paars',
    'gold': 'goud', 'golden': 'goud', 'silver': 'zilver', 'grey': 'grijs',
    'gray': 'grijs', 'brown': 'bruin', 'yellow': 'geel', 'orange': 'oranje',
    'transparent': 'transparant', 'clear': 'transparant', 'nude': 'nude',
}


def tokens(s: str) -> list:
    """Значущі латинські токени назви (кирилиця відкидається)."""
    t = re.findall(r'[a-z0-9]{2,}', (s or '').lower())
    return [x for x in t if x not in STOP and not x.isdigit()]


def brand_of(vendor: str) -> str:
    return re.sub(r'\s*\(.*?\)\s*', '', vendor or '').strip()


def classify(our_name: str, their_name: str) -> tuple:
    """→ (match_type, missing_tokens)"""
    ours, theirs = tokens(our_name), set(tokens(their_name))
    if not ours:
        return 'none', []
    missing = []
    for tok in ours:
        if tok in theirs:
            continue
        if COLORS.get(tok) in theirs:      # black ↔ zwart
            continue
        if any(tok in th or th in tok for th in theirs if len(th) > 3):
            continue                        # air-tech ↔ airtech
        missing.append(tok)
    if not missing:
        return 'exact', []
    if len(missing) <= len(ours) / 2:
        return 'partial', missing
    return 'none', missing


def grab(body: str, key: str):
    m = re.search(rf'{key}:\s*\n\s*(.+)', body)
    return m.group(1).strip() if m else None


def accept_cookies(page):
    for sel in ['button:has-text("Accepteren")', '#onetrust-accept-btn-handler',
                'button:has-text("Akkoord")']:
        try:
            if page.locator(sel).first.is_visible(timeout=2000):
                page.locator(sel).first.click()
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass


def search_query(name: str, vendor: str) -> str:
    """Бренд + перші латинські токени моделі."""
    brand = brand_of(vendor)
    toks = [t for t in tokens(name) if t not in tokens(brand)][:3]
    return ' '.join(filter(None, [brand.lower()] + toks))[:60]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int)
    ap.add_argument('--skus', default='')
    args = ap.parse_args()

    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if args.skus:
        target = args.skus.split(',')
    else:
        target = open('/home/tekken/agent-system/output/'
                      'phase1_no_country_skus.txt').read().split()
    cur.execute('SELECT sku FROM sexopt_country_lookup')
    done = {r['sku'] for r in cur.fetchall()}
    target = [s for s in target if s not in done]
    if args.limit:
        target = target[:args.limit]

    cur.execute('SELECT sku, name, vendor FROM sexopt_products WHERE sku = ANY(%s)',
                (target,))
    rows = {r['sku']: r for r in cur.fetchall()}
    print(f'До перевірки: {len(target)} SKU (вже перевірено раніше: {len(done)})',
          flush=True)

    t0 = time.time()
    stats = {'exact': 0, 'partial': 0, 'none': 0, 'notfound': 0, 'error': 0}

    with Camoufox(headless=True, humanize=True, geoip=True, locale='nl-NL') as br:
        page = br.new_page()
        page.set_default_timeout(35000)
        page.goto(BASE + '/', wait_until='domcontentloaded')
        page.wait_for_timeout(2500)
        accept_cookies(page)

        for i, sku in enumerate(target, 1):
            row = rows.get(sku)
            if not row:
                continue
            rec = dict(sku=sku, url=None, title=None, orig=None,
                       herkomst=None, mtype='notfound', missing=None)
            try:
                q = search_query(row['name'], row['vendor'])
                page.goto(f'{BASE}/zoeken?zoek=' + q.replace(' ', '+'),
                          wait_until='domcontentloaded')
                page.wait_for_timeout(3500)
                links = page.eval_on_selector_all('a[href]', 'e => e.map(x => x.href)')
                prods = [l for l in dict.fromkeys(links) if re.search(r'-p-\d+/?$', l)]

                # Попередній відсів по URL-слагу: відкриваємо лише картки,
                # де в адресі є токени бренду і моделі. Це головна економія
                # часу — інакше 6 переходів на кожен SKU.
                brand_toks = tokens(brand_of(row['vendor']))
                model_toks = [t for t in tokens(row['name'])
                              if t not in brand_toks]

                def slug_score(u: str) -> int:
                    s = u.lower()
                    return (sum(2 for t in brand_toks if t in s)
                            + sum(1 for t in model_toks if t in s))

                prods = sorted(prods, key=slug_score, reverse=True)
                prods = [u for u in prods if slug_score(u) > 0][:3]

                best = None
                for url in prods:
                    page.goto(url, wait_until='domcontentloaded')
                    page.wait_for_timeout(2500)
                    try:
                        loc = page.get_by_text('Maten & specificaties',
                                               exact=False).first
                        loc.scroll_into_view_if_needed()
                        loc.click(timeout=3000)
                        page.wait_for_timeout(1800)
                    except Exception:
                        pass
                    body = page.inner_text('body')
                    orig = grab(body, 'Originele naam') or page.title()
                    mtype, missing = classify(row['name'], orig)
                    cand = dict(url=url, title=page.title().replace(' - EasyToys', ''),
                                orig=orig, herkomst=grab(body, 'Herkomst'),
                                mtype=mtype, missing=missing)
                    if mtype == 'exact':
                        best = cand
                        break
                    if best is None or (mtype == 'partial' and best['mtype'] == 'none'):
                        best = cand
                if best:
                    rec.update(best)
            except Exception as e:
                rec['mtype'] = 'error'
                rec['missing'] = [f'{type(e).__name__}']

            key = rec['mtype'] if rec['mtype'] in stats else 'none'
            stats[key] = stats.get(key, 0) + 1
            cur.execute("""
                INSERT INTO sexopt_country_lookup
                  (sku, source, matched_url, matched_title, original_name,
                   herkomst, match_type, our_tokens, missing_tokens)
                VALUES (%s,'easytoys',%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (sku) DO UPDATE SET
                  matched_url=EXCLUDED.matched_url,
                  matched_title=EXCLUDED.matched_title,
                  original_name=EXCLUDED.original_name,
                  herkomst=EXCLUDED.herkomst, match_type=EXCLUDED.match_type,
                  our_tokens=EXCLUDED.our_tokens,
                  missing_tokens=EXCLUDED.missing_tokens, checked_at=NOW()
            """, (sku, rec['url'], rec['title'], rec['orig'], rec['herkomst'],
                  rec['mtype'], ' '.join(tokens(row['name']))[:500],
                  ' '.join(rec['missing'] or [])[:300]))

            if rec['mtype'] == 'exact':
                print(f'[{i}/{len(target)}] {sku} EXACT → {rec["herkomst"]} '
                      f'| {(rec["orig"] or "")[:60]}', flush=True)
            if i % 25 == 0:
                el = time.time() - t0
                eta = (len(target) - i) * el / i / 3600
                print(f'--- {i}/{len(target)} | {stats} | {el/60:.0f} хв '
                      f'| ще ~{eta:.1f} год ---', flush=True)

    el = time.time() - t0
    print(f'\nГОТОВО за {el/3600:.2f} год. {stats}', flush=True)


if __name__ == '__main__':
    main()
