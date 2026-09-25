#!/usr/bin/env python3
"""Локальна копія довідки продавця EVA (sellersupport.eva.ua).

Навіщо. 21.09.2026 власник домовився з EVA про магазин — за зразком уроку з
Rozetka (tools/rozetka_help_crawl.py): правила майданчика беремо з довідки,
а не з чужого робочого фіду чи здогадки.

Технічно сайт — Nuxt SPA на рушії Tawk.to Knowledge Base: у сирому HTML тексту
статей немає, вони довантажуються через JSON API. Перевірено 25.09.2026:
  * `GET /api/categories?propertyId=<kb>&siteId=primary` — список категорій
    (siteId завжди буквально "primary", кабінет один);
  * `GET /api/articles?propertyId=<kb>&siteId=primary&categoryId=<cat>` —
    список статей категорії (id, title, slug, updatedAt), пагінація курсором
    `next`, продовжувати поки `hasNext`;
  * `GET /article/<slug>` — рендерена сторінка; текст статті лежить у
    `__NUXT__` як JS-об'єкт із single-letter substitution для дублікатів
    (як у Rozetka), але самі текстові блоки (`content.text`, HTML-фрагменти)
    завжди повний JSON-рядок — регуляркою й `json.loads` витягуються надійно,
    без потреби рендерити сторінку браузером.

Ключ бази знань (`propertyId`) зашитий у фавікон і в Nuxt SSR-стан головної
сторінки; змінюється разом із самим сайтом EVA — перевіряти константу нижче,
якщо краулер почне повертати порожньо.

    python3 tools/eva_help_crawl.py            # повний обхід
    python3 tools/eva_help_crawl.py --index    # лише перелік статей
"""
import argparse
import html
import json
import os
import re
import time

import requests

BASE = 'https://sellersupport.eva.ua'
KB_ID = '654b86dca84dd54dc489e4b1'
SITE_ID = 'primary'
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE_DIR, 'shared', 'knowledge_base', 'eva', 'sellersupport')
HEADERS = {'User-Agent': 'Mozilla/5.0'}
TEXT_BLOCK = re.compile(r'(?:text|title|heading)\s*:\s*"((?:[^"\\]|\\.)*)"')


def api(path, **params):
    params.setdefault('propertyId', KB_ID)
    params.setdefault('siteId', SITE_ID)
    r = requests.get(f'{BASE}{path}', params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def list_categories():
    return api('/api/categories')['data']['categories']


def list_articles(category_id):
    out, nxt = [], None
    while True:
        p = {'categoryId': category_id, 'limit': 100}
        if nxt:
            p['next'] = nxt
        d = api('/api/articles', **p)['data']
        out += d['articles']
        nxt = d.get('next') if d.get('hasNext') else None
        if not nxt:
            break
    return out


def decode_js_string(raw: str) -> str:
    """`raw` — вміст JS-рядка (у лапках, з \\uXXXX-екрануванням). Тексти статей
    у __NUXT__ кодуються так само, як валідний JSON-рядок, тому json.loads."""
    return json.loads(f'"{raw}"')


def article_text(slug: str) -> str:
    r = requests.get(f'{BASE}/article/{slug}', headers=HEADERS, timeout=30)
    r.raise_for_status()
    i = r.text.find('__NUXT__')
    j = r.text.find('</script>', i)
    chunk = r.text[i:j] if i >= 0 else ''
    parts = [decode_js_string(m.group(1)) for m in TEXT_BLOCK.finditer(chunk)]
    body = '\n\n'.join(parts)
    body = re.sub(r'</(p|li|h[1-6]|tr|div|br)>', '\n', body)
    body = html.unescape(re.sub(r'<[^>]+>', ' ', body))
    body = re.sub(r'[ \t]+', ' ', body)
    return re.sub(r'\n\s*\n+', '\n\n', body).strip()


def slugify(s: str) -> str:
    s = re.sub(r'[^\w\-]+', '-', s.lower()).strip('-')
    return re.sub(r'-+', '-', s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', action='store_true')
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    cats = list_categories()
    plan = []
    for c in cats:
        for art in list_articles(c['categoryId']):
            plan.append((c['name'], art))

    print(f'категорій: {len(cats)} · статей: {len(plan)}')
    if a.index:
        for cat_name, art in plan:
            print(f"  [{cat_name}] {art['title']} — {art['slug']}")
        return

    index = []
    for cat_name, art in plan:
        body = article_text(art['slug'])
        if not body:
            print(f"  ПОРОЖНЬО: {art['slug']}")
            continue
        fname = slugify(art['slug'])[:80] + '.txt'
        with open(os.path.join(OUT, fname), 'w', encoding='utf-8') as f:
            f.write(f"# {BASE}/article/{art['slug']}\n"
                    f"# категорія: {cat_name}\n"
                    f"# оновлено: {art['updatedAt'][:10]}\n\n"
                    f"{art['title']}\n\n{body}\n")
        index.append(f"- [{fname}]({fname}) — {art['title']} · {cat_name} (ред. {art['updatedAt'][:10]})")
        time.sleep(0.3)

    with open(os.path.join(OUT, 'INDEX.md'), 'w', encoding='utf-8') as f:
        f.write('# Довідка продавця EVA (sellersupport.eva.ua) — локальна копія\n\n'
                'Зібрано tools/eva_help_crawl.py. Цитувати звідси з датою редакції, '
                'а не з памʼяті.\n\n' + '\n'.join(index) + '\n')
    print(f'збережено: {len(index)} файлів у {OUT}')


if __name__ == '__main__':
    main()
