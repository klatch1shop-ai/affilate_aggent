#!/usr/bin/env python3
"""Каталог Юг-Контракт через API порталу → data/yug_catalog.json.

Ендпойнти знайдено 17.10 спостереженням за самим порталом:
    /api/catalog/tree                       — 9 розділів верхнього рівня
    /api/catalog/nested-cats?id={id}        — підкатегорії
    /api/catalog/list/{id}?page&rowsPerPage — товари категорії
    /api/catalog/filters-list/{id}          — фільтри = характеристики товарів

Токен портал тримає в localStorage (`authToken`), сесія — у
data/yug_session.json (tools/yug_portal.py --вхід, один раз із SMS).

Тільки читання. Нічого не замовляє.

    venv/bin/python tools/yug_catalog_dump.py --дерево
    venv/bin/python tools/yug_catalog_dump.py --категорія 1307 --сторінок 3
"""
import argparse
import json
import os
import sys

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
СЕСІЯ = os.path.join(BASE, 'data', 'yug_session.json')
OUT = os.path.join(BASE, 'data', 'yug_catalog.json')
ПОРТАЛ = 'https://b2b.yugcontract.ua'

JS = """async ({шлях}) => {
    const t = JSON.parse(localStorage.getItem('authToken') || '""');
    const res = await fetch(шлях, {headers: {'Accept':'application/json',
                                             'Authorization':'Bearer ' + t}});
    try { return {ok: res.ok, status: res.status, j: await res.json()}; }
    catch (e) { return {ok: false, status: res.status, j: null}; }
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--дерево', action='store_true', dest='дерево')
    ap.add_argument('--категорія', dest='категорія')
    ap.add_argument('--сторінок', type=int, default=2, dest='сторінок')
    ap.add_argument('--на-сторінці', type=int, default=100, dest='на_сторінці')
    a = ap.parse_args()
    if not os.path.exists(СЕСІЯ):
        sys.exit('немає сесії — спершу tools/yug_portal.py --вхід')

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(locale='uk-UA', storage_state=СЕСІЯ)
        page = ctx.new_page()
        page.goto(f'{ПОРТАЛ}/', wait_until='networkidle', timeout=60000)
        page.wait_for_timeout(3000)

        def взяти(шлях):
            r = page.evaluate(JS, {'шлях': шлях})
            if not r.get('ok'):
                print(f'  {шлях}: HTTP {r.get("status")}', file=sys.stderr)
                return None
            return r['j']

        дані = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}

        if a.дерево:
            t = (взяти('/api/catalog/tree') or {}).get('data') or {}
            корені = t.get('menuItems') or []
            дерево = {}
            for корінь in корені:
                cid = корінь['link']
                під = взяти(f'/api/catalog/nested-cats?id={cid}')
                гілки = ((під or {}).get('data')
                         or (під or {}).get('content') or [])
                дерево[str(cid)] = {'назва': корінь['text'], 'підкатегорії': гілки}
                n = len(гілки) if isinstance(гілки, list) else '?'
                print(f"{cid:>6}  {корінь['text']:<34} підкатегорій: {n}")
            дані['дерево'] = дерево
            дані['підрозділи'] = t.get('menuSubItems')

        if a.категорія:
            cid = a.категорія
            ф = взяти(f'/api/catalog/filters-list/{cid}?typhoonId=-1&actionId=-1&page=1&rowsPerPage=20')
            дані.setdefault('фільтри', {})[cid] = ф
            товари = []
            for стор in range(1, a.сторінок + 1):
                j = взяти(f'/api/catalog/list/{cid}?typhoonId=-1&actionId=-1'
                          f'&page={стор}&rowsPerPage={a.на_сторінці}')
                порція = (((j or {}).get('content') or {}).get('data')) or []
                товари += порція
                print(f'  категорія {cid}, сторінка {стор}: {len(порція)} товарів')
                if len(порція) < a.на_сторінці:
                    break
            дані.setdefault('товари', {})[cid] = товари

        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(дані, f, ensure_ascii=False)
        print('→', OUT)
        b.close()


if __name__ == '__main__':
    main()
