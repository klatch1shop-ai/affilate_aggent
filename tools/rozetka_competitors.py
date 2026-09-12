#!/usr/bin/env python3
"""Конкуренти на Rozetka за артикулом: хто продає той самий товар і за скільки.

Метод описано в `.claude/skills/rozetka/SKILL-30-rozetka-search.md`. Коротко —
чотири публічні ендпоінти, без токена й без браузера (перевірено 12.09.2026):

    search.rozetka.com.ua/ua/search/api/v6/?text=<артикул>  → id товарів
    product-api.rozetka.com.ua/v4/goods/get-main?goodsId=<id> → назва, артикул,
                                          seller_id, категорія, ціна (ОДИН id)
    common-api.rozetka.com.ua/v2/goods/get-price/?ids=<id,id> → ціни пачкою
    product-api.rozetka.com.ua/v4/sellers/get?id=<seller_id>  → назва продавця

`xl-catalog-api …/getDetails` цін НЕ віддає (лише відгуки й docket), а
`rozetka.com.ua` сторінки закриті Cloudflare — не витрачати на них час.

Головне правило (SKILL-04): конкурент — лише картка з ТИМ САМИМ артикулом.
Пошук Rozetka повертає й схожі товари (19 результатів на один артикул), тож
кожен id звіряється за полем `article` картки, а якщо воно порожнє — за
артикулом цілим словом у назві. Решта рахується окремо як «відкинуто».

Позитивний контроль вбудовано: SW-00000350 має знайти Bravion Store за 135.
Якщо контроль не проходить — прогін зупиняється, а не звітує нулі (так
12.09 уже було з пробою Prom: «0 конкурентів із 30» через хибну регулярку).

    python3 tools/rozetka_competitors.py --feed output/dropoffice_rozetka.xml --sample 100
    python3 tools/rozetka_competitors.py --feed output/dropoffice_rozetka.xml --all
    python3 tools/rozetka_competitors.py --articles SW-00000350 SW-00001669
"""
import argparse
import collections
import json
import os
import random
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE_DIR, 'data', 'rozetka_search_cache.json')
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/128.0 Safari/537.36')
HEADERS = {'User-Agent': UA, 'Accept': 'application/json',
           'Referer': 'https://rozetka.com.ua/'}
SEARCH = ('https://search.rozetka.com.ua/ua/search/api/v6/'
          '?front-type=xl&country=UA&lang=ua&text={q}')
MAIN = ('https://product-api.rozetka.com.ua/v4/goods/get-main'
        '?front-type=xl&country=UA&lang=ua&goodsId={id}')
SELLER = ('https://product-api.rozetka.com.ua/v4/sellers/get'
          '?front-type=xl&country=UA&lang=ua&id={id}')
PAUSE = float(os.getenv('ROZETKA_PAUSE', '0.35'))   # ввічливо: ~3 запити/с
# Стеля 25 id (перша версія) обрізала видачу у 56 зі 105 артикулів 12.09 —
# серед невидимих міг бути найдешевший. Тепер уся видача, до двох сторінок.
MAX_PAGES = 2
CONTROL = ('SW-00000350', 'Bravion Store')


class Http:
    """GET із кешем на диску: перерваний прогін продовжується з місця зупинки."""

    def __init__(self, cache_path: str, ttl_h: float):
        self.path, self.ttl = cache_path, ttl_h * 3600
        self.stats = collections.Counter()
        try:
            with open(cache_path, encoding='utf-8') as f:
                self.cache = json.load(f)
        except (OSError, ValueError):
            self.cache = {}

    def get(self, url: str):
        hit = self.cache.get(url)
        if hit and time.time() - hit['t'] < self.ttl:
            self.stats['з кешу'] += 1
            return hit['v']
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                body = urllib.request.urlopen(req, timeout=30).read()
                v = json.loads(body)
                self.cache[url] = {'t': time.time(), 'v': v}
                self.stats['запитів'] += 1
                time.sleep(PAUSE)
                return v
            except Exception as e:           # мережа, 429, не-JSON (Cloudflare)
                self.stats[f'помилка: {type(e).__name__}'] += 1
                time.sleep(2 * (attempt + 1))
        return None

    def save(self):
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, ensure_ascii=False)
        os.replace(tmp, self.path)


def norm_art(a: str) -> str:
    return re.sub(r'[\s\-]+$', '', str(a or '').strip()).upper()


def same_article(card: dict, art: str) -> bool:
    """Та сама позиція: поле `article` картки, інакше артикул цілим словом у назві."""
    a = norm_art(art)
    if norm_art(card.get('article')) == a:
        return True
    title = str(card.get('title') or '').upper()
    return bool(re.search(rf'(?<![\w-]){re.escape(a)}(?![\w])', title))


# Кома чи крапка блокують лише ПІСЛЯ ЦИФРИ (десятковий дріб «1,5 шт»), а не
# після літери: «срібло,11шт» — набір з 11. Перша версія блокувала будь-яку
# кому, і конкурентам із «,11шт» ціну множило на 11 («наклейки 4.25×РРЦ»).
_PACK = re.compile(r'(?<!\d[.,])(?<![\dхx×*])(\d{1,3})\s*(?:шт\.?|штук\w*|pcs)(?![\w])', re.I)


def pack_size(title: str) -> int:
    """«… 10 шт. 700х770х2мм» → 10; «1 шт.», без позначки → 1."""
    m = _PACK.search(str(title or ''))
    n = int(m.group(1)) if m else 1
    return n if 2 <= n <= 200 else 1


def find(http: Http, art: str, sellers: dict) -> tuple:
    """→ (картки з тим самим артикулом, скільки id відкинуто як інший товар)."""
    ids = []
    for page in range(1, MAX_PAGES + 1):
        s = http.get(SEARCH.format(q=urllib.parse.quote(art)) + (f'&page={page}' if page > 1 else ''))
        if not s:
            if page == 1:
                return None, 0
            break
        d = s.get('data') or {}
        ids += [g['id'] for g in d.get('goods') or [] if g['id'] not in ids]
        if not (d.get('pagination') or {}).get('show_next'):
            break
    found, rejected = [], 0
    for gid in ids:
        m = http.get(MAIN.format(id=gid))
        card = (m or {}).get('data') if isinstance(m, dict) else None
        if not card:
            continue
        if not same_article(card, art):
            rejected += 1
            continue
        sid = card.get('seller_id')
        if sid and sid not in sellers:
            sv = http.get(SELLER.format(id=sid))
            sellers[sid] = ((sv or {}).get('data') or {}).get('title') or f'seller {sid}'
        found.append({
            'id': gid, 'price': card.get('price'), 'pack': pack_size(card.get('title')),
            'price_raw': card.get('price'),
            'old_price': card.get('old_price'),
            'status': card.get('sell_status'), 'seller_id': sid,
            'seller': sellers.get(sid, ''), 'category_id': card.get('category_id'),
            'title': card.get('title'), 'href': card.get('href')})
    return found, rejected


def load_feed(path: str) -> list:
    root = ET.parse(path).getroot()
    cats = {c.get('id'): (c.get('rz_id'), c.text) for c in root.iter('category')}
    out = []
    for o in root.iter('offer'):
        art = (o.findtext('article') or '').strip()
        if not art:
            continue
        rz, cname = cats.get(o.findtext('categoryId'), ('', ''))
        out.append({'article': art, 'price': float(o.findtext('price') or 0),
                    'available': o.get('available') == 'true',
                    'name': o.findtext('name_ua') or o.findtext('name') or '',
                    'rz_id': rz, 'category': cname})
    return out


def stratified(items: list, n: int, seed: int = 20260912) -> list:
    """Пропорційно категоріям, але хоча б одна позиція з кожної."""
    by = collections.defaultdict(list)
    for it in items:
        by[it['category']].append(it)
    rnd = random.Random(seed)
    pick = []
    for cat, lst in by.items():
        k = max(1, round(n * len(lst) / len(items)))
        pick += rnd.sample(lst, min(k, len(lst)))
    return pick


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--feed', help='наш XML для Rozetka')
    src.add_argument('--articles', nargs='+')
    ap.add_argument('--sample', type=int, default=0)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--ttl-hours', type=float, default=24.0,
                    help='вік кешу; ціни змінюються, тож не більше доби')
    ap.add_argument('--out', default=None, help='префікс файлів звіту')
    a = ap.parse_args()

    http = Http(CACHE, a.ttl_hours)
    sellers = {}

    # ── позитивний контроль ────────────────────────────────────────────────
    ctrl, _ = find(http, CONTROL[0], sellers)
    if not ctrl or not any(c['seller'] == CONTROL[1] for c in ctrl):
        http.save()
        sys.exit(f'КОНТРОЛЬ НЕ ПРОЙДЕНО: {CONTROL[0]} не знайшов {CONTROL[1]} '
                 f'(знайдено: {[c["seller"] for c in ctrl or []]}). Звіт не будується.')
    print(f'контроль: {CONTROL[0]} → {len(ctrl)} карток, {CONTROL[1]} є')

    if a.articles:
        items = [{'article': x, 'price': 0.0, 'available': True, 'name': '',
                  'rz_id': '', 'category': ''} for x in a.articles]
    else:
        items = load_feed(a.feed)
        if not a.all:
            items = stratified(items, a.sample or 100)
    print(f'артикулів до перевірки: {len(items)}')

    rows, detail = [], []
    t0 = time.time()
    for i, it in enumerate(items, 1):
        found, rejected = find(http, it['article'], sellers)
        if found is None:
            rows.append({**it, 'err': 'пошук не відповів'})
            continue
        # Набір під тим самим артикулом («3Д панель на стіну 10 шт.», FOUKS —
        # ціна вдесятеро): зводимо до НАШОЇ одиниці продажу, а не до штуки —
        # наш товар теж буває набором («наклейки, 20шт»).
        # Запобіжник: перераховуємо лише коли сирі ціни справді різняться
        # приблизно в стільки разів, скільки штук у наборі (у межах ×2). Інакше
        # розбір назви помилився — лишаємо сиру ціну й позначаємо картку.
        ours = pack_size(it['name'])
        for c in found:
            if not c['price_raw'] or c['pack'] == ours or not it['price']:
                continue
            want, got = c['pack'] / ours, c['price_raw'] / it['price']
            if 0.5 <= got / want <= 2:
                c['price'] = round(c['price_raw'] / want, 2)
            else:
                c['pack'] = f"{c['pack']}?"     # набір не підтверджено ціною
        live = [c for c in found if c['status'] == 'available' and c['price']]
        prices = sorted(c['price'] for c in live)
        cheapest = min(live, key=lambda c: c['price']) if live else None
        rows.append({
            **it, 'err': '', 'cards': len(found), 'rejected': rejected,
            'sellers': len({c['seller_id'] for c in live}),
            'min': prices[0] if prices else None,
            'median': statistics.median(prices) if prices else None,
            'max': prices[-1] if prices else None,
            'cheaper': sum(p < it['price'] for p in prices),
            'cheapest_seller': cheapest['seller'] if cheapest else '',
            'rz_cats': ','.join(sorted({str(c['category_id']) for c in found})),
        })
        for c in found:
            detail.append({'article': it['article'], **c})
        if i % 20 == 0:
            http.save()
            el = time.time() - t0
            print(f'  {i}/{len(items)} · {el / 60:.1f} хв · {dict(http.stats)}', flush=True)
    http.save()

    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    prefix = a.out or os.path.join(BASE_DIR, 'docs', f'rozetka_competitors_{stamp}')
    cols = ['article', 'category', 'price', 'available', 'cards', 'rejected', 'sellers',
            'min', 'median', 'max', 'cheaper', 'cheapest_seller', 'rz_cats', 'name', 'err']
    with open(prefix + '.tsv', 'w', encoding='utf-8') as f:
        f.write('\t'.join(cols) + '\n')
        for r in rows:
            f.write('\t'.join(str(r.get(c, '') if r.get(c) is not None else '') for c in cols) + '\n')
    dcols = ['article', 'seller', 'seller_id', 'price', 'pack', 'price_raw', 'old_price', 'status',
             'category_id', 'id', 'href', 'title']
    with open(prefix + '_detail.tsv', 'w', encoding='utf-8') as f:
        f.write('\t'.join(dcols) + '\n')
        for r in detail:
            f.write('\t'.join(str(r.get(c, '')) for c in dcols) + '\n')

    # ── зведення ───────────────────────────────────────────────────────────
    ok = [r for r in rows if not r['err']]
    with_c = [r for r in ok if r['sellers']]
    print(f'\nперевірено {len(ok)} артикулів (помилок {len(rows) - len(ok)}) · '
          f'конкуренти в наявності є у {len(with_c)} ({len(with_c) / max(1, len(ok)):.0%})')
    if with_c and any(r['price'] for r in with_c):
        rel_min = sorted(r['price'] / r['min'] for r in with_c if r['price'] and r['min'])
        rel_med = sorted(r['price'] / r['median'] for r in with_c if r['price'] and r['median'])
        print(f'продавців на артикул: медіана {statistics.median(r["sellers"] for r in with_c)}, '
              f'макс {max(r["sellers"] for r in with_c)}')
        print(f'наша / найдешевша: медіана {statistics.median(rel_min):.2f} '
              f'(ми дорожчі за найдешевшого у {sum(x > 1.0001 for x in rel_min)}, '
              f'рівні {sum(abs(x - 1) < 1e-4 for x in rel_min)}, дешевші {sum(x < 0.9999 for x in rel_min)})')
        print(f'наша / медіанна: медіана {statistics.median(rel_med):.2f}')
    sc = collections.Counter()
    for r in detail:
        if r['status'] == 'available':
            sc[r['seller']] += 1
    print('\nпродавці, що найчастіше трапляються (у наявності):')
    for s, n in sc.most_common(12):
        print(f'  {n:5}  {s}')
    print(f'\nкарток відкинуто як інший товар: {sum(r.get("rejected", 0) for r in ok)} · '
          f'запитів {http.stats["запитів"]}, з кешу {http.stats["з кешу"]}')
    print(f'→ {prefix}.tsv\n→ {prefix}_detail.tsv')


if __name__ == '__main__':
    main()
