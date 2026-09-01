#!/usr/bin/env python3
"""Наскільки наші описи збігаються з описами інших продавців SexOpt.

Ми возимо той самий фід, що й десятки продавців. Світова практика називає
дослівний опис постачальника головною причиною, чому дропшипінгові картки
не ранжуються: майданчик групує однакові тексти й показує ОДИН.

Інструмент міряє це не на око: знаходить у пошуку Prom картки того самого
товару в інших продавців, забирає їхні описи й рахує збіг.

Метрика — частка спільних 5-слівних шинглів. Обрана свідомо: вона не
реагує на дрібні правки (додану кому, змінений порядок речень), але падає,
щойно текст переписаний по-справжньому. Для дослівної копії дає ~100%.

Запуск:
    python3 tools/prom_dup_check.py --n 15
    python3 tools/prom_dup_check.py --sku SO1446,EGG-001L
"""
import argparse
import difflib
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)

FEED = os.path.join(BASE_DIR, 'output', 'noire_prom.xml')
OUT = os.path.join(BASE_DIR, 'docs', 'prom_duplicate_report.json')
OURS = ('klatch', 'noire')
SHINGLE = 5


def flat(t: str) -> str:
    t = re.sub(r'<[^>]+>', ' ', html.unescape(t or ''))
    return re.sub(r'\s+', ' ', t).strip().lower()


def shingles(text: str, n=SHINGLE) -> set:
    w = re.findall(r'[а-яіїєґa-z0-9]+', text.lower())
    return {' '.join(w[i:i + n]) for i in range(max(len(w) - n + 1, 0))}


def similarity(a: str, b: str) -> float:
    """Посимвольна схожість текстів.

    Потрібна поряд із шингловою: конкуренти правлять дрібниці («у жіночій»
    → «в жіночій»), і пʼятислівний збіг падає вдвічі, хоча текст той самий.
    Ця метрика показує саме «це один і той же текст», а шинглова — «скільки
    ми копіюємо дослівно».
    """
    return difflib.SequenceMatcher(None, a[:4000], b[:4000]).ratio() * 100


def overlap(a: str, b: str) -> float:
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    # частка НАШОГО тексту, що дослівно є в чужому — саме це показує,
    # скільки ми копіюємо, а не наскільки тексти схожі загалом
    return len(sa & sb) / len(sa) * 100


def sample(n, only):
    root = ET.parse(FEED).getroot()
    cats = {c.get('id'): (c.text or '') for c in root.findall('.//category')}
    offers = root.findall('.//offer')
    picked, seen_cat = [], {}
    for o in offers:
        sku = o.findtext('vendorCode')
        if only and sku not in only:
            continue
        cat = cats.get(o.findtext('categoryId'), '')
        desc = flat(o.findtext('description_ua') or '')
        if len(desc) < 300:
            continue
        # по дві позиції з категорії — щоб вибірка була репрезентативною,
        # а не з однієї полиці
        if not only and seen_cat.get(cat, 0) >= 2:
            continue
        seen_cat[cat] = seen_cat.get(cat, 0) + 1
        picked.append({'sku': sku, 'name': o.findtext('name_ua') or '',
                       'cat': cat, 'desc': desc})
        if not only and len(picked) >= n:
            break
    return picked


def competitor_descriptions(page, name: str, limit=3) -> list:
    """Описи карток того самого товару в інших продавців."""
    page.goto('https://prom.ua/ua/search?search_term=' + name[:70].replace(' ', '%20'),
              wait_until='domcontentloaded')
    page.wait_for_timeout(4500)
    page.mouse.wheel(0, 6000)
    page.wait_for_timeout(1500)
    blocks = page.locator('[data-qaid="product_block"]')
    links = []
    for i in range(min(blocks.count(), 8)):
        b = blocks.nth(i)
        comp = b.locator('[data-qaid="company_name"]')
        cname = (comp.first.inner_text() if comp.count() else '').lower()
        if any(o in cname for o in OURS):
            continue
        a = b.locator('a[data-qaid="product_link"]')
        href = a.first.get_attribute('href') if a.count() else None
        if href:
            links.append((cname.strip()[:28],
                          href if href.startswith('http') else 'https://prom.ua' + href))
        if len(links) >= limit:
            break
    out = []
    for seller, url in links:
        try:
            page.goto(url, wait_until='domcontentloaded')
            page.wait_for_timeout(3500)
            c = page.content()
            m = re.search(r'data-qaid="product_description"(.*?)</div>\s*</div>',
                          c, re.S)
            text = flat(m.group(1)) if m else ''
            if len(text) < 200:
                # запасний варіант: найбільший текстовий блок сторінки
                cand = re.findall(r'<p[^>]*>(.{80,2000}?)</p>', c, re.S)
                text = flat(' '.join(cand[:12]))
            if len(text) > 200:
                out.append({'seller': seller, 'url': url, 'desc': text})
        except Exception:
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=15)
    ap.add_argument('--sku')
    a = ap.parse_args()

    only = set(a.sku.split(',')) if a.sku else None
    items = sample(a.n, only)
    print(f'перевіряємо {len(items)} позицій\n')

    from camoufox.sync_api import Camoufox
    report = []
    with Camoufox(headless=True, humanize=True, geoip=True, locale='uk-UA') as br:
        page = br.new_page()
        page.set_default_timeout(45000)
        for it in items:
            try:
                comps = competitor_descriptions(page, it['name'])
            except Exception as e:
                print(f"   {it['sku']}: {type(e).__name__}")
                continue
            best = max([overlap(it['desc'], c['desc']) for c in comps],
                       default=0.0)
            best_sim = max([similarity(it['desc'], c['desc']) for c in comps],
                           default=0.0)
            report.append({'sku': it['sku'], 'cat': it['cat'],
                           'name': it['name'], 'our_desc': it['desc'],
                           'competitors': [
                               {'seller': c['seller'], 'url': c['url'],
                                'overlap': round(overlap(it['desc'], c['desc']), 1),
                                'similarity': round(similarity(it['desc'], c['desc']), 1),
                                'desc': c['desc']} for c in comps],
                           'max_overlap': round(best, 1),
                           'max_similarity': round(best_sim, 1)})
            print(f"   {it['sku']:10} {it['cat'][:18]:20} дослівно {best:5.1f}% | "
                  f"схожість {best_sim:5.1f}%  ({len(comps)} конкурентів)")
            time.sleep(2)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    hits = [r['max_overlap'] for r in report if r['competitors']]
    sims = [r['max_similarity'] for r in report if r['competitors']]
    if hits:
        print(f'\nсередній дослівний збіг: {sum(hits)/len(hits):.1f}%')
        print(f'середня схожість тексту : {sum(sims)/len(sims):.1f}%')
        print(f'позицій зі схожістю понад 80%: {sum(1 for h in sims if h > 80)}'
              f' із {len(sims)}')
    print(f'звіт: {OUT}')


if __name__ == '__main__':
    main()
