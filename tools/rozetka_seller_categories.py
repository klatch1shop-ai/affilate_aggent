#!/usr/bin/env python3
"""Дерево категорій Rozetka, у яких реально лежить асортимент конкурента.

Навіщо. Для мапінгу TOPTUL → Rozetka потрібна не наша здогадка, у яку
категорію товар «мав би» піти, а факт: де ті самі позиції **вже лежать** в
іншого продавця. Конкурент `ttul` возить той самий TOPTUL, тож його дерево —
готова відповідь, уже пройдена модерацією майданчика.

Межа застосування (SKILL-14.8): з чужої видачі беремо **структуру** — назву
й id категорії. Значення характеристик не беремо ніколи.

Як влаштована сторінка продавця (з'ясовано 17.08.2026):
  * requests і будь-який API дають Cloudflare «Just a moment…» → лише Camoufox;
  * каталог живе не на `/seller/<alias>/`, а на `/seller/<alias>/goods/`;
  * категорії — не посилання виду `/c<id>/`, а фільтр `?section_id=<id>`;
  * перший рівень дає 12 розділів, справжні категорії — усередині, тому обхід
    рекурсивний.

Запуск:
    python3 tools/rozetka_seller_categories.py --seller ttul --depth 3 --save
"""
import argparse
import json
import os
import re
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
from loguru import logger  # noqa: E402

OUT = os.path.join(BASE_DIR, 'docs', 'rozetka_seller_categories.json')
SEC_RE = re.compile(r'section_id=(\d+)')
CNT_RE = re.compile(r'\((\d[\d\s ]*)\)\s*$')


def parse_links(page) -> list:
    """(section_id, назва, кількість) з фільтра поточної сторінки."""
    out = []
    for a in page.locator('a[href*="section_id="]').all():
        try:
            href = a.get_attribute('href') or ''
            text = (a.inner_text() or '').strip().replace('\n', ' ')
        except Exception:
            continue
        m = SEC_RE.search(href)
        if not m or not text:
            continue
        cnt, name = None, text
        mc = CNT_RE.search(text)
        if mc:
            cnt = int(re.sub(r'\D', '', mc.group(1)))
            name = text[:mc.start()].strip()
        if name and len(name) <= 90:
            out.append((m.group(1), name, cnt))
    return out


def crawl(seller: str, max_depth: int = 3, pause: float = 2.5) -> dict:
    from camoufox.sync_api import Camoufox
    base = f'https://rozetka.com.ua/ua/seller/{seller}/goods/'
    found = {}          # section_id → запис
    queue = [(None, 0)]  # (section_id, глибина); None = корінь
    seen = set()

    with Camoufox(headless=True, humanize=True, geoip=True,
                  locale='uk-UA') as br:
        page = br.new_page()
        page.set_default_timeout(90000)
        while queue:
            sid, depth = queue.pop(0)
            if sid in seen:
                continue
            seen.add(sid)
            url = base if sid is None else f'{base}?section_id={sid}'
            try:
                page.goto(url, wait_until='domcontentloaded')
            except Exception as e:
                logger.warning(f'{url}: {type(e).__name__}')
                continue
            page.wait_for_timeout(int(pause * 1000))
            if 'Just a moment' in page.title():
                logger.error('Cloudflare заблокував — зупиняюсь')
                break
            page.mouse.wheel(0, 6000)
            page.wait_for_timeout(900)

            kids = parse_links(page)
            new = 0
            for cid, name, cnt in kids:
                if cid == sid:
                    continue
                rec = found.get(cid)
                if rec is None:
                    found[cid] = {'rz_id': int(cid), 'rz_name': name,
                                  'count': cnt, 'depth': depth,
                                  'parent': int(sid) if sid else None}
                    new += 1
                elif rec.get('count') is None and cnt is not None:
                    rec['count'] = cnt
                if depth + 1 < max_depth and cid not in seen:
                    queue.append((cid, depth + 1))
            logger.info(f'глибина {depth} | {url.split("goods/")[-1] or "корінь"} '
                        f'→ {len(kids)} пунктів, нових {new} '
                        f'| всього {len(found)}, у черзі {len(queue)}')
            time.sleep(0.4)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seller', default='ttul')
    ap.add_argument('--depth', type=int, default=3)
    ap.add_argument('--save', action='store_true')
    a = ap.parse_args()

    found = crawl(a.seller, a.depth)
    if not found:
        logger.error('Категорій не знайдено')
        sys.exit(1)

    rows = sorted(found.values(), key=lambda r: (r['depth'], -(r['count'] or 0)))
    leaf = [r for r in rows if r['depth'] >= 1]
    logger.success(f'Категорій: {len(rows)} (з них не верхнього рівня: {len(leaf)})')
    for r in rows[:60]:
        c = r['count'] if r['count'] is not None else '—'
        print(f"  d{r['depth']} {r['rz_id']:<10} {r['rz_name'][:52]:54} {c}")

    if a.save:
        json.dump(rows, open(OUT, 'w'), ensure_ascii=False, indent=1)
        logger.success(f'Збережено: {OUT} ({len(rows)} записів)')


if __name__ == '__main__':
    main()
