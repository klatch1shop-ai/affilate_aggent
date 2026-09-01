#!/usr/bin/env python3
"""EasyToys → характеристики та фактура опису для білизни без опису.

Той самий метод, що в noire_country_scraper.py (SKILL-01..08): Camoufox,
пошук за брендом і моделлю, суворий токенний збіг. Відмінність — що саме
знімаємо: тут потрібні не тільки Herkomst, а вся таблиця специфікацій
(Materiaal, Kleur, Maat) і текст картки.

Текст нідерландською в український фід не піде — він зберігається як
ФАКТУРА, з якої опис пишеться вручну. Характеристики ж переносяться
напряму: Materiaal / Kleur / Maat — структуровані поля, а не проза.

Застосовується лише match_type='exact'. Правило з SKILL-04 діє незмінно:
знайдене для однієї моделі бренду не переноситься на інші моделі.

Запуск:
    ./venv/bin/python tools/noire_lingerie_scraper.py --limit 20
    ./venv/bin/python tools/noire_lingerie_scraper.py            # усі
"""
import argparse
import re
import time

import psycopg2
import psycopg2.extras
from camoufox.sync_api import Camoufox

DB = dict(host='192.168.3.28', dbname='agentdb',
          user='agentadmin', password='1')
BASE = 'https://www.easytoys.nl'

# Поля таблиці специфікацій, які нас цікавлять
SPEC_KEYS = ['Materiaal', 'Kleur', 'Maat', 'Herkomst', 'Originele naam',
             'Merk', 'Inhoud', 'Kleding maat', 'Artikelnummer']

STOP = {
    'the', 'and', 'with', 'for', 'set', 'kit', 'pack', 'de', 'van', 'een',
    'met', 'ml', 'cm', 'mm', 'st', 'pcs', 'size', 'maat', 'edition', 'new',
    'lingerie', 'bra', 'panty', 'body', 'string', 'thong', 'stockings',
    'corset', 'dress', 'teddy', 'babydoll', 'chemise', 'bodystocking',
}
COLORS = {
    'black': 'zwart', 'white': 'wit', 'red': 'rood', 'pink': 'roze',
    'blue': 'blauw', 'green': 'groen', 'purple': 'paars', 'nero': 'zwart',
    'gold': 'goud', 'silver': 'zilver', 'grey': 'grijs', 'gray': 'grijs',
    'brown': 'bruin', 'beige': 'beige', 'nude': 'nude', 'ecru': 'ecru',
}


def tokens(s: str) -> list:
    t = re.findall(r'[a-z0-9]{2,}', (s or '').lower())
    return [x for x in t if x not in STOP and not x.isdigit()]


def brand_of(vendor: str) -> str:
    return re.sub(r'\s*\(.*?\)\s*', '', vendor or '').strip()


def classify(our_name: str, their_name: str) -> tuple:
    ours, theirs = tokens(our_name), set(tokens(their_name))
    if not ours:
        return 'none', []
    missing = []
    for tok in ours:
        if tok in theirs or COLORS.get(tok) in theirs:
            continue
        if any(tok in th or th in tok for th in theirs if len(th) > 3):
            continue
        missing.append(tok)
    if not missing:
        return 'exact', []
    if len(missing) <= len(ours) / 2:
        return 'partial', missing
    return 'none', missing


def grab(body: str, key: str):
    m = re.search(rf'^{re.escape(key)}:?\s*\n\s*(.+)$', body, re.M)
    return m.group(1).strip()[:300] if m else None


def specs_of(body: str) -> dict:
    return {k: v for k in SPEC_KEYS if (v := grab(body, k))}


def description_of(page) -> str:
    """Текст картки — сировина для ручного опису, не для прямої вставки."""
    for sel in ['[class*="product-description"]', '[class*="ProductDescription"]',
                'section:has-text("Productinformatie")']:
        try:
            t = page.locator(sel).first.inner_text(timeout=2500)
            if t and len(t) > 80:
                return re.sub(r'\s+', ' ', t)[:2000]
        except Exception:
            continue
    return ''


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


# Код моделі виробника в нашій назві: PS004, F333, 818-TED-1, WW7004.
# Це найнадійніший ключ: слаг EasyToys для білизни описовий
# («netstof-body-met-open-kruisje»), зате в картці є Artikelnummer.
MODEL_CODE = re.compile(
    r'\b([0-9]{3}-[A-Z]{2,4}-[0-9]|[A-Z]{1,3}[0-9]{2,4}(?:-[A-Z0-9]+)*)\b')


def model_code(name: str):
    m = MODEL_CODE.search(name or '')
    return m.group(1) if m else None


def code_matches(code: str, *fields) -> bool:
    """Збіг коду моделі з Artikelnummer / Originele naam.

    Порівнюємо лише літери й цифри: у нас «PS004», у них «S004» або
    «811-TED-1-SML» — розділювачі й розмірний суфікс різняться.
    """
    if not code:
        return False
    c = re.sub(r'[^a-z0-9]', '', code.lower())
    if len(c) < 4:
        return False
    for f in fields:
        f = re.sub(r'[^a-z0-9]', '', (f or '').lower())
        if f and (c in f or (len(c) > 5 and f.startswith(c[:6]))):
            return True
    return False


def search_query(name: str, vendor: str) -> str:
    brand = brand_of(vendor)
    code = model_code(name)
    toks = [t for t in tokens(name) if t not in tokens(brand)][:2]
    parts = [brand.lower()] + ([code.lower()] if code else []) + toks
    return ' '.join(filter(None, parts))[:60]


def ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sexopt_easytoys_specs (
            sku           TEXT PRIMARY KEY,
            source        TEXT NOT NULL DEFAULT 'easytoys',
            matched_url   TEXT,
            original_name TEXT,
            match_type    TEXT,
            missing_tokens TEXT,
            specs         JSONB,
            body_text     TEXT,
            checked_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int)
    ap.add_argument('--skus', default='')
    ap.add_argument('--rz', default='4647534', help='rz-категорія для вибірки')
    args = ap.parse_args()

    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure_table(cur)

    if args.skus:
        cur.execute('SELECT sku, name, vendor FROM sexopt_products WHERE sku = ANY(%s)',
                    (args.skus.split(','),))
    else:
        cur.execute("""
            SELECT p.sku, p.name, p.vendor
            FROM sexopt_products p
            JOIN rozetka_category_mapping m
              ON m.sexopt_category_id = p.category_id
            WHERE m.rozetka_category_id = %s
              AND (p.description_html IS NULL OR TRIM(p.description_html) = '')
              AND p.sku NOT IN (SELECT sku FROM sexopt_easytoys_specs)
            ORDER BY p.vendor, p.sku
        """, (args.rz,))
    rows = cur.fetchall()
    if args.limit:
        rows = rows[:args.limit]
    print(f'До перевірки: {len(rows)} SKU', flush=True)

    t0 = time.time()
    stats = {'exact': 0, 'partial': 0, 'none': 0, 'notfound': 0, 'error': 0}

    with Camoufox(headless=True, humanize=True, geoip=True, locale='nl-NL') as br:
        page = br.new_page()
        page.set_default_timeout(35000)
        page.goto(BASE + '/', wait_until='domcontentloaded')
        page.wait_for_timeout(2500)
        accept_cookies(page)

        for i, row in enumerate(rows, 1):
            sku = row['sku']
            rec = dict(url=None, orig=None, mtype='notfound', missing=[],
                       specs={}, body='')
            try:
                q = search_query(row['name'], row['vendor'])
                page.goto(f'{BASE}/zoeken?zoek=' + q.replace(' ', '+'),
                          wait_until='domcontentloaded')
                page.wait_for_timeout(3500)
                links = page.eval_on_selector_all('a[href]', 'e => e.map(x => x.href)')
                prods = [l for l in dict.fromkeys(links) if re.search(r'-p-\d+/?$', l)]

                brand_toks = tokens(brand_of(row['vendor']))
                model_toks = [t for t in tokens(row['name']) if t not in brand_toks]

                def slug_score(u: str) -> int:
                    s = u.lower()
                    return (sum(2 for t in brand_toks if t in s)
                            + sum(1 for t in model_toks if t in s))

                prods = [u for u in sorted(prods, key=slug_score, reverse=True)
                         if slug_score(u) > 0][:3]

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
                    sp = specs_of(body)
                    orig = sp.get('Originele naam') or page.title()
                    mtype, missing = classify(row['name'], orig)
                    # Код моделі — сильніший доказ, ніж збіг слів у назві:
                    # назви в них описові нідерландською й не збігаються ніколи.
                    if code_matches(model_code(row['name']),
                                    sp.get('Artikelnummer'), orig, url):
                        mtype, missing = 'exact', []
                    cand = dict(url=url, orig=orig, mtype=mtype, missing=missing,
                                specs=sp, body=description_of(page))
                    if mtype == 'exact':
                        best = cand
                        break
                    if best is None or (mtype == 'partial' and best['mtype'] == 'none'):
                        best = cand
                if best:
                    rec.update(best)
            except Exception as e:
                rec['mtype'] = 'error'
                rec['missing'] = [type(e).__name__]

            stats[rec['mtype'] if rec['mtype'] in stats else 'none'] += 1
            cur.execute("""
                INSERT INTO sexopt_easytoys_specs
                  (sku, matched_url, original_name, match_type,
                   missing_tokens, specs, body_text)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (sku) DO UPDATE SET
                  matched_url=EXCLUDED.matched_url,
                  original_name=EXCLUDED.original_name,
                  match_type=EXCLUDED.match_type,
                  missing_tokens=EXCLUDED.missing_tokens,
                  specs=EXCLUDED.specs, body_text=EXCLUDED.body_text,
                  checked_at=NOW()
            """, (sku, rec['url'], rec['orig'], rec['mtype'],
                  ' '.join(rec['missing'] or [])[:300],
                  psycopg2.extras.Json(rec['specs']), rec['body']))

            if rec['mtype'] == 'exact':
                print(f'[{i}/{len(rows)}] {sku} EXACT | {rec["specs"]}', flush=True)
            if i % 25 == 0:
                el = time.time() - t0
                print(f'--- {i}/{len(rows)} | {stats} | {el/60:.0f} хв '
                      f'| ще ~{(len(rows)-i)*el/i/3600:.1f} год ---', flush=True)

    print(f'\nГОТОВО за {(time.time()-t0)/3600:.2f} год. {stats}', flush=True)


if __name__ == '__main__':
    main()
