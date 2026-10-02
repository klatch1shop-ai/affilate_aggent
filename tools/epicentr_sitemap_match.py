#!/usr/bin/env python3
"""Скільки наших товарів реально є на вітрині epicentrk.ua.

Вимірювання, а не оцінка: качаємо ВЕСЬ офіційний sitemap товарів
маркетплейсу (`products_mp/products_merchant_ua.xml`, 91 частина) і звіряємо
з нашими картками у статусі `published` + «В наявності».

Чому саме так, а не перебором адрес: 7 186 запитів до сайту — це навантаження
на чужий сервіс заради того, що статичні файли дають одним проходом. Sitemap
оголошений у robots.txt, тобто опублікований для машин.

Артикул шукається в slug як `-<sku>-` або `-<sku>.html`: саме так slug
будується (перевірено на живих прикладах).

    python3 tools/epicentr_sitemap_match.py
"""
import json
import os
import re
import time

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = 'https://epicentrk.ua/upload/sitemap/new/products_mp/products_merchant_ua.xml'
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/140.0 Safari/537.36')
OUT = os.path.join(BASE, 'exports', 'epicentr_on_site.json')


def main():
    s = requests.Session()
    s.headers.update({'User-Agent': UA, 'Accept-Language': 'uk-UA'})
    parts = re.findall(r'<loc>(.*?)</loc>', s.get(INDEX, timeout=60).text)
    print(f'частин sitemap: {len(parts)}', flush=True)

    prods = json.load(open(os.path.join(BASE, 'data', 'epicentr_products.json'),
                           encoding='utf-8'))
    live = [x for x in prods
            if x.get('status') == 'published' and str(x.get('availability')) == '100']
    want = {str(x['sku']).lower(): x for x in live}
    print(f'наших живих карток: {len(want)}', flush=True)

    found, total_urls = set(), 0
    for n, url in enumerate(parts, 1):
        try:
            text = s.get(url, timeout=120).text.lower()
        except Exception as exc:
            print(f'  частина {n}: збій {exc}', flush=True)
            continue
        # Розбираємо адреси ОДИН раз і працюємо множинами. Первісний варіант
        # шукав кожен із 7 186 артикулів по всьому 9-мегабайтному тексту —
        # це мільярди порівнянь на частину, прогін не завершувався.
        locs = re.findall(r'<loc>([^<]+)</loc>', text)
        total_urls += len(locs)
        for u in locs:
            slug = u.rsplit('/', 1)[-1].removesuffix('.html')
            for tok in slug.split('-'):
                if tok in want:
                    found.add(tok)
        if n % 10 == 0:
            print(f'  {n}/{len(parts)} частин · адрес {total_urls} · наших знайдено {len(found)}',
                  flush=True)
        time.sleep(0.4)

    print(f'\nАДРЕС У SITEMAP МАРКЕТПЛЕЙСУ: {total_urls}')
    print(f'НАШИХ ЖИВИХ КАРТОК: {len(want)}')
    print(f'З НИХ Є НА ВІТРИНІ: {len(found)}  ({len(found) / len(want):.1%})')
    print(f'НЕМАЄ НА ВІТРИНІ: {len(want) - len(found)}')
    json.dump({'checked': len(want), 'on_site': sorted(found),
               'missing': sorted(set(want) - found)},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('записано:', OUT)


if __name__ == '__main__':
    main()
