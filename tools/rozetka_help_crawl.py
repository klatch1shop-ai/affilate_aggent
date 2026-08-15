#!/usr/bin/env python3
"""Локальна копія довідки продавця Rozetka (sellerhelp.rozetka.com.ua).

Навіщо. Правила майданчика — джерело істини, і кожен раз, коли ми діяли за
здогадкою чи за чужим робочим фідом, це коштувало раунду листування. Два
приклади з 15.08.2026: тег <description> позначений ОБОВʼЯЗКОВИМ, а ми
віддавали лише <description_ua> «бо у Carvol так»; посилання на зображення
мають бути https, а 698 наших ішли по http. Обидва — прямо в довідці.

Сайт віддає статику звичайним requests, Camoufox не потрібен. Складаємо
текст у shared/knowledge_base/rozetka/sellerhelp/, щоб шукати grep-ом і
цитувати з датою редакції, а не з памʼяті.

Запуск:
    python3 tools/rozetka_help_crawl.py            # повний обхід
    python3 tools/rozetka_help_crawl.py --index    # лише перелік статей
"""
import argparse
import html
import os
import re
import time

import requests

BASE = 'https://sellerhelp.rozetka.com.ua'
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE_DIR, 'shared', 'knowledge_base', 'rozetka', 'sellerhelp')
LINK = re.compile(r'href="(/p\d+-[\w\-]+\.html)"')
UPDATED = re.compile(r'Останнє оновлення:\s*([\d.]+)')


def text_of(raw: str) -> tuple:
    m = re.search(r'<main[^>]*>(.*?)</main>', raw, re.S)
    body = m.group(1) if m else raw
    body = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', body, flags=re.S)
    # переноси на межах блоків, щоб текст лишався читабельним
    body = re.sub(r'</(p|li|h[1-6]|tr|div)>', '\n', body)
    t = html.unescape(re.sub(r'<[^>]+>', ' ', body))
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\n\s*\n+', '\n\n', t).strip()
    d = UPDATED.search(t)
    return t, (d.group(1) if d else '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', action='store_true')
    ap.add_argument('--limit', type=int)
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    seen, queue = set(), ['/']
    pages = []
    # Обхід у ширину: головна довідки лінкує розділи, розділи — статті.
    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        try:
            r = requests.get(BASE + path, timeout=30)
        except Exception as e:
            print(f'   {path}: {type(e).__name__}')
            continue
        if r.status_code != 200:
            continue
        for link in set(LINK.findall(r.text)):
            if link not in seen:
                queue.append(link)
        if re.match(r'/p\d+-', path):
            pages.append((path, r.text))
        time.sleep(0.3)
        if a.limit and len(pages) >= a.limit:
            break

    print(f'знайдено статей: {len(pages)}')
    if a.index:
        for path, _ in sorted(pages):
            print('  ', path)
        return

    index = []
    for path, raw in sorted(pages):
        t, upd = text_of(raw)
        if len(t) < 400:
            continue
        slug = path.strip('/').replace('.html', '')
        with open(os.path.join(OUT, slug + '.txt'), 'w', encoding='utf-8') as f:
            f.write(f'# {BASE}{path}\n# оновлено: {upd}\n\n{t}\n')
        title = t.split('\n')[0][:90]
        index.append(f'- [{slug}]({slug}.txt) — {title} (ред. {upd})')

    with open(os.path.join(OUT, 'INDEX.md'), 'w', encoding='utf-8') as f:
        f.write('# Довідка продавця Rozetka — локальна копія\n\n'
                'Зібрано tools/rozetka_help_crawl.py. Цитувати звідси з датою '
                'редакції, а не з памʼяті.\n\n' + '\n'.join(sorted(index)) + '\n')
    print(f'збережено: {len(index)} файлів у {OUT}')


if __name__ == '__main__':
    main()
