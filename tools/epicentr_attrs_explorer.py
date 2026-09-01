"""
tools/epicentr_attrs_explorer.py
=================================
Отримує всі обов'язкові атрибути для 7 категорій Єпіцентру через PIM API.

Запуск на сервері:
  cd /home/tek/agent-system && source venv/bin/activate
  EPICENTR_TOKEN=$(grep EPICENTR_TOKEN .env | cut -d= -f2) python3 tools/epicentr_attrs_explorer.py

Що робить:
  1. Сканує /v2/pim/attribute-sets (паралельно) — знаходить наші 6 atsets
  2. Для кожного required select/multiselect — бере всі options
  3. Зберігає в epicentr_required_attrs
  4. Виводить звіт + valuecodes для 'Універсальна' в car_brand
"""

import os, sys, json, time, threading
import requests
import psycopg2
from psycopg2.extras import execute_batch, Json

BASE    = 'https://merchant-api.epicentrm.com.ua'
TOKEN   = os.environ.get('EPICENTR_TOKEN', '')
HEADERS = {'Authorization': f'Bearer {TOKEN}'}
DB_DSN  = 'host=localhost port=5432 dbname=agentdb user=agentadmin password=1'

OUR_CATS = {
    '8743': 'Перехідні рамки для автомагнітол',
    '2866': 'Автомагнітоли',
    '3729': 'Камери заднього огляду',
    '2821': 'Кабелі та перехідники',
    '2848': 'Аксесуари для автосигналізацій',
    # 4907 (Магнітоли) — deleted=False в API але замінено на 2866 в pipeline
    # 2883 (LED-світло) — deleted=True в API, замінено на 2848 через postprocess
}

# ── API ──────────────────────────────────────────────────────────────────────

def _get(path, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(BASE + path, headers=HEADERS, params=params, timeout=20)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            time.sleep(1)


def _scan_pages_parallel(path, params=None, workers=20):
    """Сканує всі сторінки паралельно, повертає всі items."""
    params = dict(params or {})
    params['limit'] = 100
    first = _get(path, {**params, 'page': 1})
    total = first.get('pages', 1)
    all_items = list(first.get('items', []))

    results = {1: all_items}
    lock = threading.Lock()

    def fetch(pg):
        try:
            data = _get(path, {**params, 'page': pg})
            with lock:
                results[pg] = data.get('items', [])
        except Exception as e:
            with lock:
                results[pg] = []

    for i in range(2, total + 1, workers):
        batch = range(i, min(i + workers, total + 1))
        threads = [threading.Thread(target=fetch, args=(pg,)) for pg in batch]
        for t in threads: t.start()
        for t in threads: t.join()

    ordered = []
    for pg in sorted(results):
        ordered.extend(results[pg])
    return ordered, total


def get_options(atset_code, attr_code, workers=30):
    """Повертає всі options для атрибута: [{code, name_ua}]."""
    # brand має 54370 опцій — беремо з кешу щоб не сканувати 544 сторінки
    if attr_code == 'brand':
        return get_brand_options_from_cache(atset_code)

    path = f'/v2/pim/attribute-sets/{atset_code}/attributes/{attr_code}/options'
    items, pages = _scan_pages_parallel(path, workers=workers)
    result = []
    for item in items:
        name_ua = next(
            (t['value'] for t in item.get('translations', []) if t['languageCode'] == 'ua'),
            item.get('code', ''))
        result.append({'code': item['code'], 'name_ua': name_ua})
    return result


def get_brand_options_from_cache(atset_code):
    """
    Бренди вже кешовані в epicentr_brand_cache (54370 брендів).
    Якщо кеш порожній — сканує API і кешує.
    """
    try:
        with psycopg2.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM epicentr_brand_cache')
                cnt = cur.fetchone()[0]
        if cnt > 1000:
            print(f' (з кешу DB: {cnt} брендів)', end='', flush=True)
            with psycopg2.connect(DB_DSN) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT valuecode, value_ua FROM epicentr_brand_cache LIMIT 200')
                    rows = cur.fetchall()
            # Повертаємо тільки перші 200 для звіту (54k не потрібно в JSON)
            return [{'code': r[0], 'name_ua': r[1]} for r in rows]
    except Exception:
        pass

    print(f' сканую brand (544 сторінки, ~60с)', end='', flush=True)
    path = f'/v2/pim/attribute-sets/{atset_code}/attributes/brand/options'
    items, _ = _scan_pages_parallel(path, workers=50)
    result = []
    for item in items:
        name_ua = next(
            (t['value'] for t in item.get('translations', []) if t['languageCode'] == 'ua'),
            item.get('code', ''))
        result.append({'code': item['code'], 'name_ua': name_ua})

    # Кешуємо в DB
    try:
        with psycopg2.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                execute_batch(cur,
                    'INSERT INTO epicentr_brand_cache (valuecode, value_ua) VALUES (%s,%s) ON CONFLICT DO NOTHING',
                    [(b['code'], b['name_ua']) for b in result])
            conn.commit()
    except Exception as e:
        print(f'  [warn] brand cache: {e}')

    return result[:200]


# ── SCAN ATSETS ──────────────────────────────────────────────────────────────

def scan_atsets_for_our_cats():
    """
    Сканує /v2/pim/attribute-sets паралельно, зупиняється коли знайшла всі 6.
    Повертає {cat_code: [{code, name_ua, type, is_required}]}.
    """
    remaining = set(OUR_CATS.keys())
    found = {}
    lock = threading.Lock()
    stop_event = threading.Event()

    def parse_items(items):
        for item in items:
            code = str(item.get('code', ''))
            if code in remaining:
                attrs = []
                for a in item.get('attributes', []):
                    name_ua = next(
                        (t['title'] for t in a.get('translations', []) if t['languageCode'] == 'ua'),
                        a.get('code', ''))
                    attrs.append({
                        'code':        a.get('code'),
                        'name_ua':     name_ua,
                        'type':        a.get('type'),
                        'is_required': bool(a.get('isRequired', False)),
                    })
                with lock:
                    found[code] = attrs
                    remaining.discard(code)
                    if not remaining:
                        stop_event.set()

    print('Сканую /v2/pim/attribute-sets щоб знайти наші 6 категорій...')
    first = _get('/v2/pim/attribute-sets', {'limit': 100, 'page': 1})
    total_pages = first.get('pages', 1)
    parse_items(first.get('items', []))
    print(f'  Всього сторінок: {total_pages}')
    if stop_event.is_set():
        print(f'  Знайдено всі 6 за першу сторінку!')
        return found

    WORKERS = 30
    results_buf = {}
    buf_lock = threading.Lock()

    def fetch(pg):
        if stop_event.is_set():
            return
        try:
            data = _get('/v2/pim/attribute-sets', {'limit': 100, 'page': pg})
            items = data.get('items', [])
            parse_items(items)
            with buf_lock:
                results_buf[pg] = len(items)
        except Exception as e:
            pass

    for i in range(2, total_pages + 1, WORKERS):
        if stop_event.is_set():
            break
        batch = range(i, min(i + WORKERS, total_pages + 1))
        threads = [threading.Thread(target=fetch, args=(pg,)) for pg in batch]
        for t in threads: t.start()
        for t in threads: t.join()
        done = len(found)
        print(f'  Сторінки {i}-{min(i+WORKERS-1, total_pages)}: знайдено {done}/6  (залишилось: {remaining})')
        if stop_event.is_set():
            break

    print(f'\nЗнайдено {len(found)}/6 категорій')
    if remaining:
        print(f'  НЕ знайдено: {remaining}')
    return found


# ── DB ───────────────────────────────────────────────────────────────────────

def init_db():
    with psycopg2.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS epicentr_required_attrs (
                    category_code  TEXT,
                    attr_code      TEXT,
                    attr_name_ua   TEXT,
                    attr_type      TEXT,
                    is_required    BOOLEAN,
                    options        JSONB,
                    PRIMARY KEY (category_code, attr_code)
                );
            """)
        conn.commit()
    print('DB: таблиця epicentr_required_attrs готова')


def save_attrs(cat_code, attrs, options_map):
    rows = []
    for a in attrs:
        opts = options_map.get(a['code'])
        rows.append((
            cat_code, a['code'], a['name_ua'], a['type'],
            a['is_required'],
            Json(opts) if opts is not None else None,
        ))
    with psycopg2.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            execute_batch(cur, """
                INSERT INTO epicentr_required_attrs
                    (category_code, attr_code, attr_name_ua, attr_type, is_required, options)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (category_code, attr_code) DO UPDATE
                    SET attr_name_ua=EXCLUDED.attr_name_ua,
                        attr_type=EXCLUDED.attr_type,
                        is_required=EXCLUDED.is_required,
                        options=EXCLUDED.options
            """, rows)
        conn.commit()
    print(f'  DB: збережено {len(rows)} атрибутів для кат. {cat_code}')


# ── REPORT ───────────────────────────────────────────────────────────────────

def print_report(cat_code, cat_name, attrs, options_map):
    required = [a for a in attrs if a['is_required']]
    optional = [a for a in attrs if not a['is_required']]

    print(f'\n{"="*60}')
    print(f'=== {cat_code}  {cat_name} ===')
    print(f'{"="*60}')
    print(f'Всього атрибутів: {len(attrs)}  |  Обов\'язкових: {len(required)}  |  Опціональних: {len(optional)}')

    if required:
        print('\n[ОБОВ\'ЯЗКОВІ]:')
        for a in required:
            opts = options_map.get(a['code'])
            if opts:
                # Шукаємо 'universal' або 'Універсальна'
                universal = [o for o in opts if
                             'universal' in o['code'].lower() or
                             'універс' in o['name_ua'].lower()]
                print(f'  {a["code"]} ({a["type"]}): {a["name_ua"]} — {len(opts)} options', end='')
                if universal:
                    for u in universal:
                        print(f'\n    ★ UNIVERSAL: code={u["code"]!r}  ua={u["name_ua"]!r}', end='')
                print()
            else:
                print(f'  {a["code"]} ({a["type"]}): {a["name_ua"]}')

    if optional:
        codes = [a['code'] for a in optional]
        print(f'\n[ОПЦІОНАЛЬНІ ({len(optional)})]: {", ".join(codes[:20])}', end='')
        if len(optional) > 20:
            print(f' … ще {len(optional)-20}', end='')
        print()


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    if not TOKEN:
        sys.exit('EPICENTR_TOKEN не встановлено')

    init_db()

    # КРОК 1: знайти атрибути для всіх 6 категорій
    cat_attrs = scan_atsets_for_our_cats()

    if not cat_attrs:
        print('Нічого не знайдено. Перевір TOKEN і доступ до API.')
        return

    # КРОК 2 + 3 + 4: для кожної категорії — options + DB + звіт
    all_universal = {}  # {cat_code: {attr_code: [universal options]}}

    for cat_code, cat_name in OUR_CATS.items():
        attrs = cat_attrs.get(cat_code)
        if attrs is None:
            print(f'\n⚠️  {cat_code} {cat_name}: не знайдено в API')
            continue

        print(f'\n--- {cat_code} {cat_name}: отримую options для select/multiselect ---')

        options_map = {}
        select_attrs = [a for a in attrs if a['type'] in ('select', 'multiselect')]

        for a in select_attrs:
            is_req = '★' if a['is_required'] else ' '
            print(f'  {is_req} {a["code"]} ({a["type"]}) ...', end='', flush=True)
            try:
                opts = get_options(cat_code, a['code'])
                options_map[a['code']] = opts
                print(f' {len(opts)} options')
            except Exception as e:
                print(f' ПОМИЛКА: {e}')
                options_map[a['code']] = []

        save_attrs(cat_code, attrs, options_map)
        print_report(cat_code, cat_name, attrs, options_map)

        # Збираємо universal для підсумку
        universal_in_cat = {}
        for attr_code, opts in options_map.items():
            univ = [o for o in opts if
                    'universal' in o['code'].lower() or
                    'універс' in o['name_ua'].lower()]
            if univ:
                universal_in_cat[attr_code] = univ
        if universal_in_cat:
            all_universal[cat_code] = universal_in_cat

    # КРОК 5: Зведений звіт по 'universal' / 'Універсальна'
    print(f'\n{"="*60}')
    print('=== ЗВІТ: valuecode "Універсальна" по категоріях ===')
    print(f'{"="*60}')
    if all_universal:
        for cat_code, attrs in all_universal.items():
            print(f'\n  Категорія {cat_code} ({OUR_CATS.get(cat_code, "")}):')
            for attr_code, opts in attrs.items():
                for o in opts:
                    print(f'    {attr_code}: code={o["code"]!r}  ua={o["name_ua"]!r}')
    else:
        print('  Не знайдено жодного "universal" значення в обов\'язкових select-атрибутах.')

    # Підсумок по required атрибутах
    print(f'\n{"="*60}')
    print('=== ПІДСУМОК required атрибутів ===')
    print(f'{"="*60}')
    for cat_code, cat_name in OUR_CATS.items():
        attrs = cat_attrs.get(cat_code)
        if not attrs:
            print(f'  {cat_code}: N/A')
            continue
        req = [a for a in attrs if a['is_required']]
        print(f'  {cat_code} {cat_name}: {len(req)} обов\'язкових — {[a["code"] for a in req]}')


if __name__ == '__main__':
    main()
