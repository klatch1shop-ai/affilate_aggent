#!/usr/bin/env python3
"""SERP-бенчмаркінг Prom: де насправді стоять наші картки за нашими ж keywords.

Розширення SKILL-09. Різниця з listing_pattern_analyzer: там ми дивилися
випадкові картки категорії, тут — цілений пошук за конкретними фразами, які
ми самі призначили товарам на Рівнях 1-2. Тобто перевіряємо не «як прийнято
оформлювати», а «чи працює те, що ми зробили».

Два типи діагнозу, і їх не можна змішувати:
  • «відсутній у видачі»       — технічна прогалина: слова немає ні в назві,
                                 ні в keywords, або товар не в тій категорії;
  • «присутній, низька позиція» — питання конкурентоспроможності (ціна,
                                 рейтинг, продажі), текст тут ні до чого.

Перше лікується генератором, друге — ні. Плутати їх означає переписувати
тексти там, де проблема в ціні.

Prom віддає рівно 10 товарів на сторінку (SKILL-14.3), тому топ-20 — це дві
сторінки. Чужі описи не копіюємо: знімаємо частотні терміни, не текст.

Запуск:
    python3 tools/prom_serp_baseline.py --pilot          # 18 запитів
    python3 tools/prom_serp_baseline.py --coverage 100   # вибірка з пулу
    python3 tools/prom_serp_baseline.py --report
"""
import argparse
import collections
import json
import os
import random
import re
import sys
import time
from datetime import date

import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

FEED = os.path.join(BASE_DIR, 'output', 'noire_prom.xml')
KEYWORDS = os.path.join(BASE_DIR, 'docs', 'prom_kw_level1_all.json')
PAGES = 2                 # 10 товарів на сторінку → топ-20
PAUSE = 2.5
OUR_SELLER = ('klatch', 'noire')
# Термін вважаємо нормою видачі, якщо він є у 60% карток топ-20 — той самий
# поріг, що в listing_pattern_analyzer: один продавець це здогадка, більшість
# це вже мова ринку.
REQUIRED_SHARE = 0.6

PILOT = [
    'мастурбатор tenga', 'онахол kokos', 'реалістичний мастурбатор',
    'мастурбатор з вібрацією',
    'анальна пробка з хвостом', 'металева анальна пробка',
    'силіконова анальна пробка', 'анальна пробка dorcel',
    'вібратор для клітора', 'вібратор lelo', 'смарт вібратор',
    'вібратор для пар',
    'реалістичний фалоімітатор', 'фалоімітатор з мошонкою',
    'бдсм набір', 'манжети для підвісу',
    'лубрикант на водній основі', 'анальний лубрикант',
]

STOP = {'см', 'мм', 'кг', 'мл', 'шт', 'грн', 'для', 'зі', 'із', 'над', 'під',
        'від', 'при', 'без', 'або', 'та', 'і', 'з', 'на', 'у', 'в', 'до'}


def ensure_tables(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS serp_baseline (
            run_date   DATE NOT NULL,
            run_label  TEXT NOT NULL,
            query      TEXT NOT NULL,
            position   INTEGER NOT NULL,
            title      TEXT,
            price      NUMERIC,
            seller     TEXT,
            is_ours    BOOLEAN DEFAULT FALSE,
            match_level TEXT,
            PRIMARY KEY (run_date, run_label, query, position)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS serp_summary (
            run_date     DATE NOT NULL,
            run_label    TEXT NOT NULL,
            query        TEXT NOT NULL,
            our_position INTEGER,
            diagnosis    TEXT,
            in_name      BOOLEAN,
            in_keywords  BOOLEAN,
            results      INTEGER,
            price_min    NUMERIC,
            price_median NUMERIC,
            exact_n      INTEGER,
            exact_median NUMERIC,
            brand_n      INTEGER,
            generic_n    INTEGER,
            price_verdict TEXT,
            missing      JSONB,
            PRIMARY KEY (run_date, run_label, query)
        )
    """)
    for ddl in (
        "ALTER TABLE serp_baseline ADD COLUMN IF NOT EXISTS match_level TEXT",
        "ALTER TABLE serp_summary ADD COLUMN IF NOT EXISTS exact_n INTEGER",
        "ALTER TABLE serp_summary ADD COLUMN IF NOT EXISTS exact_median NUMERIC",
        "ALTER TABLE serp_summary ADD COLUMN IF NOT EXISTS brand_n INTEGER",
        "ALTER TABLE serp_summary ADD COLUMN IF NOT EXISTS generic_n INTEGER",
        "ALTER TABLE serp_summary ADD COLUMN IF NOT EXISTS price_verdict TEXT",
    ):
        cur.execute(ddl)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS serp_coverage (
            run_date   DATE NOT NULL,
            run_label  TEXT NOT NULL,
            sampled    INTEGER,
            present    INTEGER,
            coverage   NUMERIC,
            margin     NUMERIC,
            pool_size  INTEGER,
            PRIMARY KEY (run_date, run_label)
        )
    """)


def load_our_data():
    """Наші назви й keywords — щоб відрізнити свою картку й поставити діагноз."""
    import xml.etree.ElementTree as ET
    names, kw, vendors = {}, {}, set()
    root = ET.parse(FEED).getroot()
    for o in root.findall('.//offer'):
        sku = o.findtext('vendorCode')
        names[sku] = (o.findtext('name') or '').lower()
        kw[sku] = (o.findtext('keywords') or '').lower()
        v = (o.findtext('vendor') or '').strip()
        if v:
            vendors.add(v)
    return names, kw, sorted(vendors, key=len, reverse=True)


def price_of(text: str):
    """Ціна товару, а не платіж у розстрочку.

    Блок ціни містить і «від 50 \u20b4/міс» — щомісячний платіж. Наївний перший
    збіг давав 15-20 \u20b4 за преміальні вібратори LELO і робив медіану ринку
    беззмістовною. Тому: відкидаємо все з «/міс», з решти беремо найбільше
    (варіанти «за штуку / за набір»).
    """
    if not text:
        return None
    vals = []
    for m in re.finditer(r'([\d][\d\s\u00a0]*)\s*\u20b4\s*(/\s*\w+)?', text):
        tail = (m.group(2) or '').lower()
        if 'міс' in tail or 'мес' in tail:
            continue
        try:
            v = float(re.sub(r'[\s\u00a0]', '', m.group(1)))
        except ValueError:
            continue
        if v >= 10:
            vals.append(v)
    return max(vals) if vals else None


# ── точний збіг моделі, а не збіг за широким словом ────────────────────────
_LAT = re.compile(r'\b[A-Za-z][A-Za-z0-9\-]{1,}\b')
_MODEL_STOP = {'the', 'and', 'for', 'with', 'edition', 'design', 'new', 'set',
               'pro', 'plus', 'max', 'mini', 'size', 'cm', 'ua', 'ki'}


def model_tokens(title: str, vendor: str) -> set:
    """Латинські токени назви без бренду — це і є модель."""
    vt = {w.lower() for w in (vendor or '').split()}
    out = set()
    for w in _LAT.findall(title or ''):
        lw = w.lower()
        if lw in vt or lw in _MODEL_STOP or len(lw) < 2:
            continue
        out.add(lw)
    m = re.search(r'(?<![\d.,])(\d)(?![\d.,])', title or '')
    if m:
        out.add(m.group(1))
    return out


def match_level(comp_title: str, vendor: str, our_model: set) -> str:
    """exact  — той самий бренд і та сама модель (єдине чесне порівняння цін);
    brand  — бренд той самий, модель інша;
    generic — бренду немає, це інший ринковий сегмент (ноунейм)."""
    low = (comp_title or '').lower()
    if not vendor or vendor.lower() not in low:
        return 'generic'
    if not our_model:
        return 'brand'
    return 'exact' if our_model <= model_tokens(comp_title, vendor) else 'brand'


def scrape(page, query: str) -> list:
    out = []
    for pg in range(1, PAGES + 1):
        url = ('https://prom.ua/ua/search?search_term='
               + query.replace(' ', '%20') + (f'&page={pg}' if pg > 1 else ''))
        page.goto(url, wait_until='domcontentloaded')
        page.wait_for_timeout(4000)
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1500)
        blocks = page.locator('[data-qaid="product_block"]')
        for i in range(blocks.count()):
            b = blocks.nth(i)
            try:
                nm = b.locator('[data-qaid="product_name"]')
                title = nm.first.inner_text().strip() if nm.count() else ''
                pr = b.locator('[data-qaid="product_price"]')
                price = (price_of(' '.join(pr.all_inner_texts()))
                         if pr.count() else None)
                cm = b.locator('[data-qaid="company_name"]')
                seller = cm.first.inner_text().strip() if cm.count() else ''
            except Exception:
                continue
            if title:
                out.append({'position': len(out) + 1, 'title': title,
                            'price': price, 'seller': seller})
        time.sleep(PAUSE)
    return out


def terms(title: str):
    t = re.sub(r'[^\w\sʼ\'-]', ' ', (title or '').lower())
    return {w for w in t.split() if len(w) > 2 and w not in STOP
            and not w.isdigit()}


def analyse(query, rows, names, kw, vendors=None):
    """Позиція нашої картки, тип діагнозу і терміни, яких нам бракує."""
    ours = next((r for r in rows
                 if any(s in (r['seller'] or '').lower() for s in OUR_SELLER)),
                None)
    if ours is not None and vendors:
        # бренд нашої картки — з фіду, за найкращим збігом назви
        t = ours['title'].lower()
        ours['vendor'] = next((v for v in vendors if v and v.lower() in t), '')
    q = query.lower()
    in_name = any(q in n for n in names.values())
    in_kw = any(q in k for k in kw.values())

    if ours:
        diagnosis = ('у топ-10' if ours['position'] <= 10
                     else 'присутній, низька позиція')
    elif not rows:
        diagnosis = 'видача порожня'
    elif in_name or in_kw:
        diagnosis = 'відсутній у видачі (фраза є в картці)'
    else:
        diagnosis = 'відсутній у видачі (фрази немає в картці)'

    freq = collections.Counter()
    for r in rows:
        freq.update(terms(r['title']))
    need = max(int(len(rows) * REQUIRED_SHARE), 1)
    common = {w for w, c in freq.items() if c >= need}
    ours_terms = terms(ours['title']) if ours else set()
    # чого немає в нашій картці взагалі — ні в назві, ні в keywords
    corpus = ' '.join(names.values()) + ' ' + ' '.join(kw.values())
    missing = sorted(w for w in common - ours_terms if w not in corpus)

    # ── ціна: порівнюємо тільки з тим самим брендом і моделлю ──────────────
    # Медіана по всій видачі беззмістовна: за словом «вібратор» у топ-20
    # потрапляють і ноунейм-товари за 500 грн, і преміум за 10 000. Це різні
    # ринкові сегменти, і усереднювати їх — те саме, що рівняти ціну авто до
    # медіани «всього, що має колеса».
    vendor = ours.get('vendor', '') if ours else ''
    our_model = model_tokens(ours['title'], vendor) if ours else set()
    for r in rows:
        r['match_level'] = (match_level(r['title'], vendor, our_model)
                            if vendor else 'generic')
        if r is ours:
            r['match_level'] = 'ours'

    exact = [r['price'] for r in rows
             if r['match_level'] == 'exact' and r['price']]
    # Частина продавців ставить у картку символічні 15-64 грн (дропшип-
    # заглушка або «ціна за запитом»). Для преміальної моделі це не ціна,
    # а шум: медіана з ними падає у сто разів. Відкидаємо все, що менше 5%
    # від найдорожчої точної пропозиції.
    if exact:
        floor = max(exact) * 0.05
        dropped = [p for p in exact if p < floor]
        exact = [p for p in exact if p >= floor]
        if dropped:
            logger.info(f'  відкинуто символічних цін: {len(dropped)}')
    brand = [r for r in rows if r['match_level'] == 'brand']
    generic = [r for r in rows if r['match_level'] == 'generic']
    exact.sort()
    exact_median = exact[len(exact) // 2] if exact else None

    verdict = 'немає точних конкурентів у топ-20'
    if ours and exact_median:
        our_price = ours.get('price')
        if our_price:
            d = (our_price - exact_median) / exact_median * 100
            verdict = (f'наша {our_price:.0f}\u20b4 проти {exact_median:.0f}\u20b4 '
                       f'по {len(exact)} точних ({d:+.0f}%)')
    elif not ours:
        verdict = 'нашої картки у видачі немає'

    prices = sorted(r['price'] for r in rows if r['price'])
    return {
        'our_position': ours['position'] if ours else None,
        'diagnosis': diagnosis, 'in_name': in_name, 'in_keywords': in_kw,
        'results': len(rows),
        'price_min': prices[0] if prices else None,
        'price_median': prices[len(prices) // 2] if prices else None,
        'exact_n': len(exact), 'exact_median': exact_median,
        'brand_n': len(brand), 'generic_n': len(generic),
        'price_verdict': verdict,
        'missing': missing[:12],
    }


def save_gaps(cur, gaps: dict):
    """Прогалини термінів — одразу в category_ideal_template, не лише у звіт."""
    if not gaps:
        return 0
    rows = [('prom', q, 'serp_missing_terms',
             'терміни, що є у ≥60% топ-20 за цим запитом, але відсутні '
             'в нашій картці: ' + ', '.join(t),
             'джерело: SERP-бенчмаркінг', 'prom_serp_baseline.py',
             'зафіксовано ' + str(date.today()), 'спостереження видачі')
            for q, t in gaps.items() if t]
    psycopg2.extras.execute_values(cur, """
        INSERT INTO category_ideal_template
          (marketplace, category, field, rule, hard_limit, source,
           our_state, verified)
        VALUES %s
        ON CONFLICT (marketplace, category, field) DO UPDATE SET
          rule=EXCLUDED.rule, our_state=EXCLUDED.our_state, updated_at=NOW()
    """, rows)
    return len(rows)


def run(queries, label, coverage_pool=None):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure_tables(cur)
    conn.commit()
    names, kw, vendors = load_our_data()
    today = date.today()

    from camoufox.sync_api import Camoufox
    gaps, present, done = {}, 0, 0
    with Camoufox(headless=True, humanize=True, geoip=True, locale='uk-UA') as br:
        page = br.new_page()
        page.set_default_timeout(60000)
        for i, q in enumerate(queries, 1):
            try:
                rows = scrape(page, q)
            except Exception as e:
                logger.warning(f'{q}: {type(e).__name__}')
                continue
            res = analyse(q, rows, names, kw, vendors)
            done += 1
            if res['our_position']:
                present += 1
            if not coverage_pool:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO serp_baseline
                      (run_date, run_label, query, position, title, price,
                       seller, is_ours, match_level)
                    VALUES %s ON CONFLICT DO NOTHING
                """, [(today, label, q, r['position'], r['title'], r['price'],
                       r['seller'],
                       any(s in (r['seller'] or '').lower() for s in OUR_SELLER),
                       r.get('match_level'))
                      for r in rows])
                cur.execute("""
                    INSERT INTO serp_summary
                      (run_date, run_label, query, our_position, diagnosis,
                       in_name, in_keywords, results, price_min, price_median,
                       exact_n, exact_median, brand_n, generic_n,
                       price_verdict, missing)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (run_date, run_label, query) DO UPDATE SET
                      our_position=EXCLUDED.our_position,
                      diagnosis=EXCLUDED.diagnosis, missing=EXCLUDED.missing
                """, (today, label, q, res['our_position'], res['diagnosis'],
                      res['in_name'], res['in_keywords'], res['results'],
                      res['price_min'], res['price_median'],
                      res['exact_n'], res['exact_median'], res['brand_n'],
                      res['generic_n'], res['price_verdict'],
                      psycopg2.extras.Json(res['missing'])))
                gaps[q] = res['missing']
                conn.commit()
            logger.info(f"[{i}/{len(queries)}] «{q}» — {res['results']} карток, "
                        f"наша: {res['our_position'] or '—'} · {res['diagnosis']}")

    if coverage_pool:
        cov = present / done * 100 if done else 0
        margin = 196 * (cov / 100 * (1 - cov / 100) / done) ** 0.5 if done else 0
        cur.execute("""
            INSERT INTO serp_coverage
              (run_date, run_label, sampled, present, coverage, margin, pool_size)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (run_date, run_label) DO UPDATE SET
              sampled=EXCLUDED.sampled, present=EXCLUDED.present,
              coverage=EXCLUDED.coverage, margin=EXCLUDED.margin
        """, (today, label, done, present, round(cov, 1), round(margin, 1),
              coverage_pool))
        conn.commit()
        print(f'\n══ ПОКРИТТЯ ══\nвибірка {done} запитів із пулу {coverage_pool}')
        print(f'наша картка в топ-20: {present} ({cov:.1f}% ±{margin:.1f})')
    else:
        n = save_gaps(cur, gaps)
        conn.commit()
        print(f'\nпрогалин термінів записано в category_ideal_template: {n}')
    cur.close()
    conn.close()


def cmd_report():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT * FROM serp_summary ORDER BY run_date, run_label,
                   our_position NULLS LAST""")
    rows = cur.fetchall()
    cur.execute('SELECT * FROM serp_coverage ORDER BY run_date')
    cov = cur.fetchall()
    by = collections.defaultdict(list)
    for r in rows:
        by[(r['run_date'], r['run_label'])].append(r)
    for (d, lbl), rs in by.items():
        print(f'\n══ {d} · {lbl} ══')
        d_cnt = collections.Counter(r['diagnosis'] for r in rs)
        for k, v in d_cnt.most_common():
            print(f'   {k}: {v}')
        for r in rs:
            pos = r['our_position'] or '—'
            print(f"   {str(pos):>3}  {r['query'][:32]:34} "
                  f"медіана ринку {r['price_median'] or '—'}₴  "
                  f"бракує: {', '.join(r['missing'][:5]) or '—'}")
    for c in cov:
        print(f"\nПОКРИТТЯ {c['run_date']} · {c['run_label']}: "
              f"{c['coverage']}% ±{c['margin']} "
              f"(вибірка {c['sampled']} з пулу {c['pool_size']})")
    cur.close()
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pilot', action='store_true')
    ap.add_argument('--coverage', type=int)
    ap.add_argument('--label', default='before')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--queries', nargs='+', help='довільний список запитів')
    a = ap.parse_args()

    if a.report:
        cmd_report()
    elif a.coverage:
        pool = sorted({p for r in json.load(open(KEYWORDS))
                       for p in (r.get('final') or [])})
        random.seed(2026)
        run(random.sample(pool, min(a.coverage, len(pool))),
            a.label + '-coverage', coverage_pool=len(pool))
    elif a.queries:
        run(a.queries, a.label)
    elif a.pilot:
        run(PILOT, a.label)
    else:
        ap.error('потрібен --pilot, --coverage N або --report')


if __name__ == '__main__':
    main()
