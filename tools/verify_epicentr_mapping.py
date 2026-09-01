#!/usr/bin/env python3
"""
Верифікація epicentr_category_mapping через пошук товарів на epicentrk.ua/apteka.

Для кожного з 32 унікальних epicentr_category_code:
  1. Береться 1-2 реальні назви товарів із sexopt_products цієї категорії
  2. Ці назви шукаються на epicentrk.ua
  3. З dataLayer(categoryName) порівнюється з epicentr_intimate_categories.name_ua
  4. Якщо збігається — SET verified=true + competitor_example_url
  5. Якщо ні — залишається verified=false, виводиться у список для перегляду

Usage:
  python3 tools/verify_epicentr_mapping.py [--dry-run]
"""

import re, json, time, sys, argparse
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, '/home/tekken/agent-system')
from shared.utils.db import get_connection

HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/124.0.0.0 Safari/537.36'),
    'Accept-Language': 'uk-UA,uk;q=0.9',
}
SEARCH_URL = 'https://epicentrk.ua/ua/search/?q={}'
DELAY = 2.0  # секунди між запитами

# ── Утиліти ────────────────────────────────────────────────────────────────────

def normalize(s: str) -> str:
    return re.sub(r'\s+', ' ', s.lower().strip())

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()

def keyword_overlap(expected: str, found: str) -> bool:
    stopwords = {'та', 'і', 'для', 'на', 'з', 'із', 'до', 'у', 'в', 'або', 'а', 'та/або'}
    exp_words = {w for w in normalize(expected).split() if w not in stopwords and len(w) > 2}
    fnd_words = {w for w in normalize(found).split() if w not in stopwords and len(w) > 2}
    overlap = exp_words & fnd_words
    return len(overlap) >= 2 or (len(exp_words) == 1 and exp_words <= fnd_words)

def is_match(expected_name: str, found_name: str) -> bool:
    if similarity(expected_name, found_name) >= 0.50:
        return True
    if keyword_overlap(expected_name, found_name):
        return True
    return False

def clean_brand(vendor: str) -> str:
    """'Fleshlight (США)' → 'Fleshlight'"""
    return re.split(r'\s*[\(\[,]', vendor)[0].strip()

def get_page(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        return BeautifulSoup(r.text, 'html.parser')
    except Exception:
        return None

def extract_datalayer(html_text: str) -> dict:
    """Витягує categoryId/categoryName з dataLayer.push({...}) (re.DOTALL)."""
    for s in re.findall(r'dataLayer\.push\((\{.*?\})\)', html_text, re.DOTALL):
        try:
            d = json.loads(s)
            if d.get('categoryId') or d.get('categoryName'):
                return d
        except Exception:
            continue
    return {}

def apteka_cards_for_brand(brand: str, limit: int = 5) -> list[str]:
    """Шукає brand на epicentrk.ua і повертає URL з apteka.epicentrk.ua/ua/shop/mplc."""
    from urllib.parse import quote
    url = SEARCH_URL.format(quote(brand))
    soup = get_page(url)
    if not soup:
        return []
    seen, result = set(), []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if 'apteka.epicentrk.ua/ua/shop/mplc' in href and href not in seen:
            seen.add(href)
            result.append(href)
            if len(result) >= limit:
                break
    return result

def verify_one(code: str, expected_name_ua: str, vendor: str, product_name: str) -> dict:
    """
    Повертає dict з полями: status, found_category, example_url, detail.
    status: 'verified' | 'mismatch' | 'not_found'
    """
    brand = clean_brand(vendor) if vendor else ''
    queries_tried = []

    # ── Стратегія 1: пошук за брендом → фільтр apteka-URL ──
    for query in ([brand] if brand else []) + [product_name[:40]]:
        queries_tried.append(query)
        card_urls = apteka_cards_for_brand(query, limit=6)
        time.sleep(DELAY)
        if not card_urls:
            continue

        for card_url in card_urls[:3]:
            soup = get_page(card_url)
            if not soup:
                continue
            time.sleep(1.0)

            dl = extract_datalayer(str(soup))
            found_cat_name = dl.get('categoryName', '')
            found_cat_id   = dl.get('categoryId', '')
            found_title    = dl.get('productName', card_url.split('/')[-1])

            if not found_cat_name:
                continue

            if is_match(expected_name_ua, found_cat_name):
                return {
                    'status': 'verified',
                    'found_category': f"{found_cat_name} (id={found_cat_id})",
                    'example_url': card_url,
                    'detail': (f'brand="{query}" → "{found_title[:50]}" '
                               f'→ cat="{found_cat_name}" ≈ "{expected_name_ua}"'),
                }
            else:
                # Знайшли товар на apteka, але категорія не збігається
                return {
                    'status': 'mismatch',
                    'found_category': f"{found_cat_name} (id={found_cat_id})",
                    'example_url': card_url,
                    'detail': (f'brand="{query}" → cat="{found_cat_name}" '
                               f'≠ очікувано "{expected_name_ua}"'),
                }

    return {
        'status': 'not_found',
        'found_category': None,
        'example_url': None,
        'detail': f'Не знайдено apteka-товарів для: {queries_tried}',
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Не писати в БД')
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    # Завантажуємо 32 унікальні категорії з vendor та назвою товару
    cur.execute('''
        SELECT DISTINCT ON (m.epicentr_category_code)
            m.epicentr_category_code AS code,
            m.sexopt_category_id,
            m.sexopt_category_name,
            e.name_ua AS epicentr_name_ua,
            p.name  AS product_name,
            p.vendor
        FROM epicentr_category_mapping m
        JOIN epicentr_intimate_categories e ON e.code = m.epicentr_category_code
        LEFT JOIN LATERAL (
            SELECT name, vendor FROM sexopt_products
            WHERE category_id = m.sexopt_category_id
              AND vendor IS NOT NULL AND vendor != \'\'
            ORDER BY sku LIMIT 1
        ) p ON true
        ORDER BY m.epicentr_category_code
    ''')
    categories = cur.fetchall()
    total = len(categories)
    print(f"\n{'='*70}")
    print(f"  Верифікація epicentr_category_mapping: {total} унікальних кодів")
    print(f"  dry-run: {args.dry_run}")
    print(f"{'='*70}\n")

    verified_list = []
    mismatch_list = []
    not_found_list = []

    for i, cat in enumerate(categories, 1):
        code       = cat['code']
        name_ua    = cat['epicentr_name_ua']
        vendor     = cat['vendor'] or ''
        prod_name  = cat['product_name'] or cat['sexopt_category_name']

        print(f"[{i:02d}/{total}] code={code} | очікувано: «{name_ua}»")
        print(f"        sexopt: «{cat['sexopt_category_name']}» | бренд: {vendor.split('(')[0].strip()}")
        print(f"        товар:  {prod_name[:70]}")

        result = verify_one(code, name_ua, vendor, prod_name)
        status = result['status']

        print(f"        → {status.upper()} | {result['detail']}")
        print()

        if status == 'verified':
            verified_list.append((code, name_ua, result))
            if not args.dry_run:
                cur.execute('''
                    UPDATE epicentr_category_mapping
                    SET verified = true,
                        competitor_example_url = %s
                    WHERE epicentr_category_code = %s
                ''', (result['example_url'], code))
                conn.commit()
        elif status == 'mismatch':
            mismatch_list.append((code, name_ua, result))
        else:
            not_found_list.append((code, name_ua, result))

    # ── Підсумок ──────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  ПІДСУМОК: {len(verified_list)}/{total} верифіковано ✅")
    print(f"{'='*70}\n")

    if verified_list:
        print(f"✅ ВЕРИФІКОВАНО ({len(verified_list)}):")
        for code, name_ua, r in verified_list:
            print(f"   [{code}] {name_ua}")
            print(f"         Epicentr cat: {r['found_category']}")
            print(f"         URL: {r['example_url']}")
        print()

    need_review = mismatch_list + not_found_list
    if need_review:
        print(f"❌ ПОТРЕБУЄ ПЕРЕГЛЯДУ ({len(need_review)}):")
        for code, name_ua, r in mismatch_list:
            print(f"   [{code}] {name_ua} — РОЗБІЖНІСТЬ")
            print(f"         {r['detail']}")
        for code, name_ua, r in not_found_list:
            print(f"   [{code}] {name_ua} — НЕ ЗНАЙДЕНО")
            print(f"         {r['detail']}")

    conn.close()

if __name__ == '__main__':
    main()
