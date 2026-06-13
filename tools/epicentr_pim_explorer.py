"""
Epicentr PIM API explorer — categories, attributes, brands, countries.

Key facts:
- atset_code == category_code for all categories
- Brand options: 544 pages x100 = ~54400 brands, shared across atsets
- No search filter exists — scan all pages, cache in DB
- Country options: 50 pages x20 = ~1000 countries

DB: agentadmin/1/agentdb (docker exec agent_postgres psql -U agentadmin agentdb)
"""

import os, sys, time, threading
import requests
import psycopg2
from psycopg2.extras import execute_batch

BASE = 'https://merchant-api.epicentrm.com.ua'
TOKEN = os.environ.get('EPICENTR_TOKEN', '')
HEADERS = {'Authorization': 'Bearer ' + TOKEN}

DB_DSN = 'host=localhost port=5432 dbname=agentdb user=agentadmin password=1'

# Our target categories
OUR_CATS = {
    '8743': 'Перехідні рамки для автомагнітол',
    '4907': 'Магнітоли',
    '3729': 'Камери заднього огляду',
    '2821': 'Кабелі та перехідники',
    '2848': 'Аксесуари для автосигналізацій',
    '2883': 'LED-світло для автомобіля',
    '2866': 'Автомагнітоли',
}

OUR_BRANDS = ['QIV', 'Carav', 'Teyes', 'Pioneer', 'Alpine', 'Sony', 'Toyota']

# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DB_DSN)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS epicentr_brand_map (
                    brand_name  TEXT NOT NULL,
                    atset_code  TEXT NOT NULL,
                    valuecode   TEXT NOT NULL,
                    value_ua    TEXT,
                    verified_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (brand_name, atset_code)
                );
                CREATE TABLE IF NOT EXISTS epicentr_brand_cache (
                    valuecode  TEXT PRIMARY KEY,
                    value_ua   TEXT,
                    cached_at  TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS epicentr_country_cache (
                    valuecode  TEXT PRIMARY KEY,
                    value_ua   TEXT,
                    cached_at  TIMESTAMP DEFAULT NOW()
                );
            """)
        conn.commit()
    print('DB tables ready.')


# ── API helpers ────────────────────────────────────────────────────────────────

def _get(path, params=None, timeout=15):
    r = requests.get(BASE + path, headers=HEADERS, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _scan_pages(path, params=None, max_workers=20, verbose=False):
    """Scan all pages concurrently (limit=100 is max that works)."""
    params = dict(params or {})
    params['limit'] = 100
    first = _get(path, {**params, 'page': 1})
    total_pages = first.get('pages', 1)
    all_items = list(first.get('items', []))

    if verbose:
        print(f'  Total pages: {total_pages}')

    results = {1: all_items}
    lock = threading.Lock()

    def fetch(pg):
        try:
            data = _get(path, {**params, 'page': pg})
            with lock:
                results[pg] = data.get('items', [])
        except Exception as e:
            if verbose:
                print(f'  Page {pg} error: {e}')

    pages_left = list(range(2, total_pages + 1))
    batch_size = max_workers
    for i in range(0, len(pages_left), batch_size):
        batch = pages_left[i:i + batch_size]
        threads = [threading.Thread(target=fetch, args=(pg,)) for pg in batch]
        for t in threads: t.start()
        for t in threads: t.join()
        if verbose and (i // batch_size) % 10 == 0:
            print(f'  Progress: {min(i + batch_size, len(pages_left))}/{len(pages_left)} batches')

    ordered = []
    for pg in sorted(results):
        ordered.extend(results[pg])
    return ordered


# ── Core functions ─────────────────────────────────────────────────────────────

def get_category_atset(cat_code: str) -> str:
    """
    For Epicentr PIM, atset_code == category_code always.
    Returns immediately without API call.
    """
    return cat_code


def get_atset_attributes(atset_code: str) -> dict:
    """
    Scan attribute-sets pages to find attributes for given atset.
    Returns {attr_code: {name_ua, type, required}}.

    SLOW (1824 pages). Use only when needed.
    """
    path = '/v2/pim/attribute-sets'
    target = {}
    params = {'limit': 100}
    first = _get(path, {**params, 'page': 1})
    total_pages = first.get('pages', 1)

    def check_items(items):
        for item in items:
            if item['code'] == atset_code:
                for a in item.get('attributes', []):
                    title_ua = next(
                        (t['title'] for t in a.get('translations', []) if t['languageCode'] == 'ua'), a['code'])
                    target[a['code']] = {
                        'name_ua': title_ua,
                        'type': a.get('type'),
                        'required': a.get('isRequired', False),
                    }
                return True
        return False

    if check_items(first.get('items', [])):
        return target

    found = threading.Event()
    lock = threading.Lock()

    def fetch(pg):
        if found.is_set():
            return
        try:
            data = _get(path, {**params, 'page': pg})
            if check_items(data.get('items', [])):
                found.set()
        except Exception:
            pass

    for i in range(2, total_pages + 1, 20):
        if found.is_set():
            break
        batch = range(i, min(i + 20, total_pages + 1))
        threads = [threading.Thread(target=fetch, args=(pg,)) for pg in batch]
        for t in threads: t.start()
        for t in threads: t.join()

    return target


def get_attribute_options(atset_code: str, attr_code: str, verbose=False) -> list:
    """
    Get all options for an attribute. Returns [{code, name_ua}].
    Scans all pages concurrently (limit=100, up to 544 pages for brand).
    """
    path = f'/v2/pim/attribute-sets/{atset_code}/attributes/{attr_code}/options'
    items = _scan_pages(path, verbose=verbose)
    result = []
    for item in items:
        name_ua = next(
            (t['value'] for t in item.get('translations', []) if t['languageCode'] == 'ua'),
            item.get('code', ''))
        result.append({'code': item['code'], 'name_ua': name_ua})
    return result


def _cache_brands(atset_code='8743', verbose=True) -> list:
    """
    Fetch and cache all brands in DB. Uses atset 8743 (brands are shared).
    Returns list of {code, name_ua}.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM epicentr_brand_cache')
            cnt = cur.fetchone()[0]
    if cnt > 1000:
        if verbose:
            print(f'Using cached {cnt} brands from DB.')
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT valuecode, value_ua FROM epicentr_brand_cache')
                return [{'code': r[0], 'name_ua': r[1]} for r in cur.fetchall()]

    print(f'Caching all brands from API (544 pages × 100)...')
    brands = get_attribute_options(atset_code, 'brand', verbose=verbose)
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_batch(cur,
                'INSERT INTO epicentr_brand_cache (valuecode, value_ua) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                [(b['code'], b['name_ua']) for b in brands])
        conn.commit()
    print(f'Cached {len(brands)} brands.')
    return brands


def _match_brand(query: str, brands: list) -> tuple | None:
    """
    Exact and fuzzy brand matching.
    Returns (code, name_ua) or None.
    Priority: exact → startswith → word-contains
    """
    q = query.lower().strip()
    exact, starts, contains = None, None, None
    for b in brands:
        name = b['name_ua'].lower().strip()
        if name == q:
            exact = (b['code'], b['name_ua'])
            break
        if name.startswith(q) or q.startswith(name):
            if starts is None:
                starts = (b['code'], b['name_ua'])
        elif q in name.split() or any(w == q for w in name.split()):
            if contains is None:
                contains = (b['code'], b['name_ua'])
    return exact or starts or contains


def find_brand(brand_name: str, atset_code: str = '8743') -> tuple | None:
    """Find brand in Epicentr options. Returns (code, name_ua) or None."""
    brands = _cache_brands(atset_code, verbose=False)
    return _match_brand(brand_name, brands)


def get_country_code(country_name: str, atset_code: str = '8743') -> tuple | None:
    """Find country code. Returns (code, name_ua) or None."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM epicentr_country_cache')
            cnt = cur.fetchone()[0]

    if cnt < 50:
        path = f'/v2/pim/attribute-sets/{atset_code}/attributes/country_of_origin/options'
        countries = _scan_pages(path)
        with get_conn() as conn:
            with conn.cursor() as cur:
                execute_batch(cur,
                    'INSERT INTO epicentr_country_cache (valuecode, value_ua) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                    [(c['code'], next((t['value'] for t in c.get('translations', []) if t['languageCode'] == 'ua'), c['code']))
                     for c in countries])
            conn.commit()
        print(f'Cached {len(countries)} countries.')

    with get_conn() as conn:
        with conn.cursor() as cur:
            q = country_name.lower()
            cur.execute('SELECT valuecode, value_ua FROM epicentr_country_cache WHERE LOWER(value_ua) = %s', (q,))
            row = cur.fetchone()
            if row:
                return row[0], row[1]
            cur.execute("SELECT valuecode, value_ua FROM epicentr_country_cache WHERE LOWER(value_ua) LIKE %s LIMIT 1", (q + '%',))
            row = cur.fetchone()
            return (row[0], row[1]) if row else None


def explore_category(cat_code: str) -> dict:
    """Full category report: atset, attributes, brand options count, our brand search."""
    atset = get_category_atset(cat_code)
    title = OUR_CATS.get(cat_code, cat_code)
    print(f'\n{"="*60}')
    print(f'Category {cat_code}: {title}')
    print(f'AtSet code: {atset}')
    print(f'{"="*60}')

    # Get attributes (fast path — skip full scan, just check known system attrs)
    known_attrs = ['measure', 'ratio', 'brand', 'country_of_origin', 'weight', 'width', 'height', 'length']
    print('\nChecking known system attributes...')
    attr_status = {}
    for attr in known_attrs:
        try:
            r = requests.get(BASE + f'/v2/pim/attribute-sets/{atset}/attributes/{attr}/options',
                             headers=HEADERS, params={'limit': 1}, timeout=10)
            if r.status_code == 200:
                pages = r.json().get('pages', 0)
                attr_status[attr] = pages
                print(f'  {attr}: OK (pages={pages})')
            else:
                print(f'  {attr}: {r.status_code}')
        except Exception as e:
            print(f'  {attr}: error {e}')

    # Search our brands
    print('\nSearching our brands...')
    brands_all = _cache_brands(verbose=False)
    brand_results = {}
    for brand in OUR_BRANDS:
        match = _match_brand(brand, brands_all)
        brand_results[brand] = match
        status = f'✅ code={match[0]} name={match[1]}' if match else '❌ NOT FOUND'
        print(f'  {brand}: {status}')

    # Country check
    print('\nCountry "Китай":')
    cn = get_country_code('Китай', atset)
    print(f'  {"✅ code=" + cn[0] if cn else "❌ NOT FOUND"}')

    return {
        'cat_code': cat_code,
        'atset': atset,
        'title': title,
        'brands': brand_results,
        'china_code': cn[0] if cn else None,
    }


def build_brand_map(cat_codes: list = None) -> dict:
    """
    Build brand→valuecode mapping for all our categories.
    Saves to epicentr_brand_map table.
    """
    if cat_codes is None:
        cat_codes = list(OUR_CATS.keys())

    brands_all = _cache_brands(verbose=True)
    mapping = {}

    with get_conn() as conn:
        rows = []
        for cat_code in cat_codes:
            atset = get_category_atset(cat_code)
            for brand in OUR_BRANDS:
                match = _match_brand(brand, brands_all)
                if match:
                    code, name_ua = match
                    mapping[brand] = {'code': code, 'name_ua': name_ua}
                    rows.append((brand, atset, code, name_ua))

        with conn.cursor() as cur:
            execute_batch(cur, """
                INSERT INTO epicentr_brand_map (brand_name, atset_code, valuecode, value_ua)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (brand_name, atset_code) DO UPDATE
                  SET valuecode=EXCLUDED.valuecode, value_ua=EXCLUDED.value_ua, verified_at=NOW()
            """, rows)
        conn.commit()

    print(f'\nSaved {len(rows)} brand mappings to DB.')
    return mapping


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if not TOKEN:
        sys.exit('EPICENTR_TOKEN not set in environment')

    init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'explore'

    if cmd == 'explore':
        cat = sys.argv[2] if len(sys.argv) > 2 else '8743'
        explore_category(cat)

    elif cmd == 'explore-all':
        for cat_code in OUR_CATS:
            explore_category(cat_code)

    elif cmd == 'build-brand-map':
        print('\nBuilding brand map for all categories...')
        mapping = build_brand_map()
        print('\n=== Brand Map ===')
        for brand, info in mapping.items():
            print(f'  {brand} → {info["code"]} ({info["name_ua"]})')

    elif cmd == 'find-brand':
        brand = sys.argv[2] if len(sys.argv) > 2 else 'Pioneer'
        result = find_brand(brand)
        if result:
            print(f'Found: code={result[0]} name={result[1]}')
        else:
            print(f'Brand "{brand}" NOT FOUND in Epicentr')

    elif cmd == 'country':
        name = sys.argv[2] if len(sys.argv) > 2 else 'Китай'
        result = get_country_code(name)
        print(result if result else 'NOT FOUND')

    elif cmd == 'cache-brands':
        brands = _cache_brands(verbose=True)
        print(f'Total brands cached: {len(brands)}')

    else:
        print('Usage: python3 epicentr_pim_explorer.py [explore [cat_code] | explore-all | build-brand-map | find-brand NAME | country NAME | cache-brands]')
