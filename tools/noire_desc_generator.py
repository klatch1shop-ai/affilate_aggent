#!/usr/bin/env python3
"""
Генерація описів українською для товарів SexOpt без description_html.
Локальна модель: Ollama qwen2.5:7b на 100.126.131.55 (той самий підхід,
що в agents/scraper/category_classifier.py).

Результат → таблиця sexopt_generated_descriptions (не чіпає description_html).

Використання:
    python3 noire_desc_generator.py --test 20
    python3 noire_desc_generator.py --all
"""
import argparse
import html
import logging
import random
import re
import sys
import time

import psycopg2
import psycopg2.extras
import requests

OLLAMA = 'http://100.126.131.55:11434'
MODEL = 'qwen2.5:7b'   # перевизначається --model

DB = dict(host='192.168.3.28', dbname='agentdb',
          user='agentadmin', password='1')

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S')
logger = logging.getLogger('desc_gen')

MIN_LEN, MAX_LEN = 400, 800
import os
SKIP_SAVE = bool(os.environ.get('SKIP_SAVE'))
VERBOSE = bool(os.environ.get('VERBOSE', '1') != '0')

# ---------------------------------------------------------------- helpers


def strip_html(s: str) -> str:
    """HTML-опис постачальника → чистий текст для прикладу в промпті."""
    s = re.sub(r'<br\s*/?>', ' ', s or '')
    s = re.sub(r'</p>', ' ', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def dedupe_mention(t: str, needle: str) -> str:
    """Залишити тільки перше входження needle, наступні — прибрати.

    Видалення (а не заміна) дає граматично коректний текст:
    'від відомого іспанського бренду Adrien Lastic пропонує'
      → 'від відомого іспанського бренду пропонує'
    """
    if not needle or len(needle) < 3:
        return t
    pat = re.compile(r'(?<!\w)' + re.escape(needle) + r'(?!\w)', re.I)
    if len(pat.findall(t)) < 2:
        return t

    sentences = re.split(r'(?<=[.?…])\s+', t)
    out, seen = [], False
    for s in sentences:
        if not pat.search(s):
            out.append(s)
            continue
        if not seen:            # перша згадка — залишаємо як є
            seen = True
            out.append(s)
            continue
        # повторна згадка: прибрати і полагодити речення
        r = pat.sub('', s)
        r = re.sub(r'\s{2,}', ' ', r)
        r = re.sub(r'\s+([,.;:])', r'\1', r)
        r = re.sub(r'([,–—-])\s*[,–—-]+', r'\1', r)
        r = re.sub(r'^[\s,;:–—-]+', '', r).strip()
        if len(r.split()) < 5:  # огризок — краще прибрати речення повністю
            continue
        out.append(r[0].upper() + r[1:])
    return ' '.join(x for x in out if x).strip()


def clean_output(text: str, product_name: str, vendor: str = '') -> str:
    """Прибрати службові артефакти, знаки оклику, зайві згадки назви/бренду."""
    t = strip_html(text)

    # прибрати преамбули моделі
    t = re.sub(r'^(ось|опис|текст|варіант)[^:]{0,40}:\s*', '', t, flags=re.I)
    # markdown
    t = re.sub(r'[*_`#]+', '', t)
    # лапки на початку/кінці
    t = t.strip().strip('"“”«»').strip()
    # знаки оклику заборонені Epicentr
    t = t.replace('!', '.')
    # подвійні крапки після заміни
    t = re.sub(r'\.{2,}', '.', t)
    t = re.sub(r'\s+([.,;:])', r'\1', t)
    t = re.sub(r'\s+', ' ', t).strip()

    # назва товару / бренд — не більше 1 разу
    t = dedupe_mention(t, product_name)
    brand = brand_of(vendor)
    if brand:
        t = dedupe_mention(t, brand)
    return t


# --- автоматична перевірка якості -----------------------------------------

# корені слів, що позначають фізичні характеристики (матеріал/колір/крій/фурнітура)
SPEC_ROOTS = [
    # матеріали
    'силікон', 'шкір', 'латекс', 'тканин', 'мереж', 'атлас', 'сатин', 'оксамит',
    'велюр', 'бавовн', 'поліестер', 'еластан', 'нейлон', 'пластик', 'метал',
    'сталев', 'сталі', 'скло', 'склян', 'кристал', 'дерев', 'керамі',
    'поліуретан', 'полівінілхлорид',
    # колір
    'чорн', 'біл', 'червон', 'рожев', 'син', 'блакитн', 'зелен', 'фіолетов',
    'бузков', 'прозор', 'золот', 'срібл', 'бежев', 'коричнев', 'жовт',
    'помаранчев', 'бірюзов',
    # крій / фурнітура / деталі
    'застібк', 'блискавк', 'ремінц', 'ремінь', 'шнурівк', 'гачк', 'кнопк',
    'спідниц', 'декольте', 'бретел', 'панчох', 'сітк', 'сіточк', 'вирізом',
    'вставк', 'стрази', 'мережив', 'рюш', 'завʼязк', 'присоск',
]

# англ. слово в назві → український корінь, який після цього дозволено
EN_HINTS = {
    'silicone': 'силікон', 'leather': 'шкір', 'latex': 'латекс',
    'lace': 'мереж', 'satin': 'сатин', 'velvet': 'оксамит',
    'glass': 'скл', 'crystal': 'кристал', 'steel': 'стал',
    'stainless': 'метал', 'metal': 'метал', 'wood': 'дерев',
    'mesh': 'сітк', 'fishnet': 'сітк', 'net': 'сітк',
    'cotton': 'бавовн', 'nylon': 'нейлон', 'pvc': 'полівінілхлорид',
    'black': 'чорн', 'white': 'біл', 'red': 'червон', 'pink': 'рожев',
    'blue': 'син', 'green': 'зелен', 'purple': 'фіолетов',
    'violet': 'фіолетов', 'gold': 'золот', 'golden': 'золот',
    'silver': 'срібл', 'beige': 'бежев', 'brown': 'коричнев',
    'yellow': 'жовт', 'transparent': 'прозор', 'clear': 'прозор',
    'nero': 'чорн', 'zipper': 'блискавк', 'strap': 'ремінц',
    'suction': 'присоск', 'cup': 'присоск',
}


def brand_of(vendor: str) -> str:
    """'Adrien Lastic (Іспанія)' → 'Adrien Lastic'"""
    return re.sub(r'\s*\(.*?\)\s*', '', vendor or '').strip()


def norm(s: str) -> str:
    return re.sub(r'[^\w\s]', '', (s or '').lower())


def count_occurrences(text: str, needle: str) -> int:
    if not needle or len(needle) < 3:
        return 0
    t, n = norm(text), norm(needle)
    if not n:
        return 0
    return len(re.findall(r'(?<!\w)' + re.escape(n) + r'(?!\w)', t))


def allowed_roots(name: str) -> set:
    """Корені ТТХ, які дозволені, бо присутні (прямо чи через англ.) у назві."""
    ok = set()
    nl = name.lower()
    for root in SPEC_ROOTS:
        if root in nl:
            ok.add(root)
    for en, root in EN_HINTS.items():
        if re.search(r'(?<![a-z])' + en + r'(?![a-z])', nl):
            ok.update(r for r in SPEC_ROOTS if r.startswith(root) or root.startswith(r))
            ok.add(root)
    return ok


def check_text(text: str, name: str, vendor: str) -> list:
    """→ список порушень (порожній = пройшов)."""
    issues = []
    tl = text.lower()

    if not (MIN_LEN <= len(text) <= MAX_LEN):
        issues.append(f'довжина {len(text)} поза 400-800')

    if '!' in text:
        issues.append('знак оклику')

    # латиниця всередині кириличного слова
    mixed = re.findall(r'\b\w*(?:[а-яїієґё][a-z]|[a-z][а-яїієґё])\w*\b', text,
                       flags=re.I)
    if mixed:
        issues.append('змішана латиниця/кирилиця: ' + ', '.join(set(mixed))[:80])

    # згадки бренду / назви
    brand = brand_of(vendor)
    nb = count_occurrences(text, brand)
    if nb > 1:
        issues.append(f'бренд "{brand}" згадано {nb} разів')
    if count_occurrences(text, name) > 1:
        issues.append('повна назва згадана більше 1 разу')

    # цифри, яких немає в назві
    name_nums = set(re.findall(r'\d+', name))
    for num in set(re.findall(r'\d+', text)):
        if num not in name_nums:
            issues.append(f'вигадане число: {num}')

    # ТТХ, яких немає в назві
    ok_roots = allowed_roots(name)
    for root in SPEC_ROOTS:
        if root in tl and not any(root.startswith(a) or a.startswith(root)
                                  for a in ok_roots):
            issues.append(f'вигадана ТТХ: "{root}"')

    return issues


def trim_to_sentence(t: str, limit: int) -> str:
    """Обрізати по межі речення, щоб влізти в limit символів."""
    if len(t) <= limit:
        return t
    cut = t[:limit]
    pos = max(cut.rfind('. '), cut.rfind('.'))
    if pos > MIN_LEN:
        return cut[:pos + 1].strip()
    return cut.rsplit(' ', 1)[0].strip() + '.'


def build_prompt(name, vendor, cat_name, examples=None) -> str:
    """Промпт без прикладів-описів — вони були джерелом вигаданих ТТХ."""
    return f"""Ти — досвідчений копірайтер українського інтернет-магазину товарів для дорослих.

Напиши опис товару українською мовою.

ТОВАР: {name}
БРЕНД: {vendor or 'не вказано'}
КАТЕГОРІЯ: {cat_name}

ЖОРСТКІ ПРАВИЛА:
1. Обсяг: від 450 до 750 символів. Це 3-5 речень.
2. Тільки українська мова, без орфографічних і граматичних помилок.
   Не вставляй латинських літер усередину українських слів.
3. ЗАБОРОНЕНО знак оклику.
4. Назву товару або бренд згадуй рівно один раз за весь текст, не більше.
5. НЕ згадуй конкретний матеріал, колір, крій, застібки, тип тканини чи
   будь-які фізичні характеристики, яких немає дослівно в назві товару.
   Жодних цифр розмірів, ваги, обʼєму. Не описуй, з чого зроблений товар,
   як він виглядає, які в нього деталі, ремінці, вставки чи форма — ти цього
   не знаєш. Якщо сумніваєшся, чи є характеристика в назві — не згадуй її.
6. Пиши тільки загальний маркетинговий текст: призначення товару, для кого
   він, яку емоцію і настрій створює, чим буде корисний. Наприкінці —
   стриманий заклик до дії.
7. Без заголовків, без списків, без markdown, без HTML. Тільки суцільний текст.
8. Не пиши службових фраз на кшталт "ось опис" — одразу текст опису.

Опис:"""


def call_ollama(prompt: str, temperature: float = 0.7) -> str:
    resp = requests.post(f'{OLLAMA}/api/generate', json={
        'model': MODEL,
        'prompt': prompt,
        'stream': False,
        'options': {
            'num_predict': 700,
            'temperature': temperature,
            'top_p': 0.9,
            'repeat_penalty': 1.15,
        }
    }, timeout=300)
    resp.raise_for_status()
    return resp.json()['response']


# ---------------------------------------------------------------- data


def fetch_targets(cur, limit=None, spread=False):
    """Товари без реального опису (порожні + template_fallback заглушки)."""
    q = """
        SELECT p.sku, p.name, p.vendor, p.category_id,
               COALESCE(m.epicentr_category_code, '') AS ep_code
        FROM sexopt_products p
        LEFT JOIN epicentr_category_mapping m
               ON m.sexopt_category_id = p.category_id
        WHERE (p.description_source IS NULL
               OR p.description_source = 'template_fallback')
          AND (p.description_html IS NULL
               OR TRIM(p.description_html) = ''
               OR p.description_source = 'template_fallback')
          AND NOT EXISTS (SELECT 1 FROM sexopt_generated_descriptions g
                          WHERE g.sku = p.sku)
        ORDER BY {}
    """.format('p.category_id, p.sku' if not spread else 'p.sku')
    if limit and spread:
        # по одному товару з кожної категорії — щоб тест покрив різні категорії
        q = """
            SELECT sku, name, vendor, category_id, ep_code FROM (
              SELECT p.sku, p.name, p.vendor, p.category_id,
                     COALESCE(m.epicentr_category_code,'') AS ep_code,
                     ROW_NUMBER() OVER (PARTITION BY p.category_id
                                        ORDER BY p.sku) rn
              FROM sexopt_products p
              LEFT JOIN epicentr_category_mapping m
                     ON m.sexopt_category_id = p.category_id
              WHERE (p.description_source IS NULL
                     OR p.description_source = 'template_fallback')
                AND NOT EXISTS (SELECT 1 FROM sexopt_generated_descriptions g
                                WHERE g.sku = p.sku)
            ) t WHERE rn = 1 ORDER BY category_id LIMIT %s
        """
        cur.execute(q, (limit,))
    elif limit:
        cur.execute(q + ' LIMIT %s', (limit,))
    else:
        cur.execute(q)
    return cur.fetchall()


_ex_cache: dict = {}
_cat_cache: dict = {}


def get_examples(cur, category_id: str, ep_code: str = '') -> list:
    key = category_id
    if key in _ex_cache:
        return _ex_cache[key]
    cur.execute("""
        SELECT description_html FROM sexopt_products
        WHERE category_id = %s
          AND description_source = 'original'
          AND description_html IS NOT NULL
          AND length(description_html) BETWEEN 400 AND 2500
        ORDER BY random() LIMIT 3
    """, (category_id,))
    rows = cur.fetchall()
    # fallback: приклади з тієї ж Epicentr-категорії (сусідні SexOpt-категорії)
    if not rows and ep_code:
        cur.execute("""
            SELECT p.description_html FROM sexopt_products p
            JOIN epicentr_category_mapping m
              ON m.sexopt_category_id = p.category_id
            WHERE m.epicentr_category_code = %s
              AND p.description_source = 'original'
              AND p.description_html IS NOT NULL
              AND length(p.description_html) BETWEEN 400 AND 2500
            ORDER BY random() LIMIT 3
        """, (ep_code,))
        rows = cur.fetchall()
    ex = [trim_to_sentence(strip_html(r['description_html']), 700)
          for r in rows]
    _ex_cache[key] = ex
    return ex


def get_cat_name(cur, category_id: str, ep_code: str) -> str:
    key = (category_id, ep_code)
    if key in _cat_cache:
        return _cat_cache[key]
    cur.execute("SELECT sexopt_category_name FROM epicentr_category_mapping "
                "WHERE sexopt_category_id=%s LIMIT 1", (category_id,))
    row = cur.fetchone()
    name = (row or {}).get('sexopt_category_name') or 'Товари для дорослих'
    _cat_cache[key] = name
    return name


# ---------------------------------------------------------------- main


def generate_one(cur, row) -> tuple:
    """→ (text, seconds, attempts, issues)"""
    cat_name = get_cat_name(cur, row['category_id'], row['ep_code'])
    prompt = build_prompt(row['name'], row['vendor'], cat_name)

    t0 = time.time()
    best, best_issues = None, ['не згенеровано']
    for attempt in range(3):
        try:
            raw = call_ollama(prompt, temperature=0.6 + 0.1 * attempt)
        except Exception as e:
            logger.error(f'{row["sku"]}: ollama error {e}')
            continue
        txt = clean_output(raw, row['name'], row['vendor'])
        if len(txt) > MAX_LEN:
            txt = trim_to_sentence(txt, MAX_LEN)
        issues = check_text(txt, row['name'], row['vendor'])
        if not issues:
            return txt, time.time() - t0, attempt + 1, []
        if best is None or len(issues) < len(best_issues):
            best, best_issues = txt, issues
    return best, time.time() - t0, 3, best_issues


def save(cur, sku, text, secs, issues):
    cur.execute("""
        INSERT INTO sexopt_generated_descriptions
              (sku, description_text, source, model, char_len, gen_seconds,
               issues)
        VALUES (%s, %s, 'ai_generated_local', %s, %s, %s, %s)
        ON CONFLICT (sku) DO UPDATE SET
            description_text = EXCLUDED.description_text,
            model = EXCLUDED.model,
            char_len = EXCLUDED.char_len,
            gen_seconds = EXCLUDED.gen_seconds,
            issues = EXCLUDED.issues,
            generated_at = NOW()
    """, (sku, text, MODEL, len(text), round(secs, 2),
          '; '.join(issues) if issues else None))


def main():
    global MODEL
    ap = argparse.ArgumentParser()
    ap.add_argument('--test', type=int, default=0)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--model', default=MODEL)
    ap.add_argument('--skus', default='')
    args = ap.parse_args()
    MODEL = args.model

    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if args.skus:
        cur.execute("""SELECT p.sku,p.name,p.vendor,p.category_id,
                       COALESCE(m.epicentr_category_code,'') ep_code
                       FROM sexopt_products p LEFT JOIN epicentr_category_mapping m
                       ON m.sexopt_category_id=p.category_id
                       WHERE p.sku = ANY(%s)""", (args.skus.split(','),))
        rows = cur.fetchall()
    elif args.test:
        rows = fetch_targets(cur, limit=args.test, spread=True)
    else:
        rows = fetch_targets(cur)

    cur.execute("""SELECT count(*) c FROM sexopt_products p
                   WHERE (p.description_source IS NULL
                          OR p.description_source='template_fallback')""")
    total_pool = cur.fetchone()['c']

    logger.info(f'До генерації: {len(rows)} товарів (весь пул: {total_pool})')

    t_start = time.time()
    ok = fail = clean = 0
    results = []
    bad_len = []
    for i, row in enumerate(rows, 1):
        text, secs, attempts, issues = generate_one(cur, row)
        if not text:
            fail += 1
            logger.warning(f'[{i}/{len(rows)}] {row["sku"]} FAIL')
            continue
        if not SKIP_SAVE:
            save(cur, row['sku'], text, secs, issues)
        ok += 1
        if not issues:
            clean += 1
        if any('довжина' in x for x in issues):
            bad_len.append((row['sku'], len(text)))
        results.append((row, text, secs, attempts, issues))
        mark = 'OK' if not issues else 'FLAG: ' + '; '.join(issues)[:90]
        logger.info(f'[{i}/{len(rows)}] {row["sku"]} '
                    f'{len(text)} симв. {secs:.1f}s (сп.{attempts}) {mark}')
        if i % 100 == 0:
            el = time.time() - t_start
            eta = (len(rows) - i) * el / i / 3600
            logger.info(f'--- ЧЕКПОЙНТ {i}/{len(rows)}: чисто {clean}, '
                        f'з зауваженнями {ok - clean}, {el/60:.0f} хв, '
                        f'залишилось ~{eta:.1f} год ---')

    elapsed = time.time() - t_start

    if VERBOSE:
        print('\n' + '=' * 78)
        for row, text, secs, attempts, issues in results:
            print(f'\nSKU: {row["sku"]}  |  cat {row["category_id"]}'
                  f'  |  Epicentr {row["ep_code"] or "-"}'
                  f'  |  {len(text)} симв.  |  {secs:.1f}s')
            print(f'НАЗВА: {row["name"]}')
            print(f'БРЕНД: {row["vendor"]}')
            if issues:
                print(f'ЗАУВАЖЕННЯ: {"; ".join(issues)}')
            print('-' * 78)
            print(text)
            print('-' * 78)

    print('\n' + '=' * 78)
    print(f'Згенеровано: {ok},  без зауважень: {clean},  '
          f'з зауваженнями: {ok - clean},  помилок: {fail}')
    if bad_len:
        print(f'Не влучили в 400-800 симв. за 3 спроби ({len(bad_len)}): '
              + ', '.join(f'{s}({n})' for s, n in bad_len))
    print(f'Загальний час: {elapsed:.1f}s ({elapsed/60:.1f} хв)')
    if ok:
        avg = elapsed / ok
        print(f'Середній час на товар: {avg:.1f}s')
        print(f'ОЦІНКА на весь пул ({total_pool} товарів): '
              f'{total_pool * avg / 3600:.1f} год '
              f'({total_pool * avg / 60:.0f} хв)')


if __name__ == '__main__':
    main()
