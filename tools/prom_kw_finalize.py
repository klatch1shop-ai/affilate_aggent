#!/usr/bin/env python3
"""Фінальний відбір keywords: фільтр чужих брендів + збереження диференціації.

Два правила, знайдені на пробному пулі 30:

1. КРОСБРЕНДОВЕ ЗАБРУДНЕННЯ. Фраза не повинна містити назву бренду,
   відмінного від `<vendor>` самого товару. У фіді 125 позицій, у назві
   яких стоїть чужий бренд (Pjur із «we-vibe», Rocks Off із «blush»),
   і кожна така назва тягне бренд у ключі.

2. ВТРАЧЕНА ДИФЕРЕНЦІАЦІЯ. Кольорові варіанти отримували ідентичне поле:
   у SX3178 (White) і SX3179 (Black) колір визначався правильно, але
   вилітав з топ-5, витіснений загальними фразами. Тепер фраза, унікальна
   в межах групи варіантів, має пріоритет над спільною для всієї групи —
   інакше варіанти конкурують між собою за той самий запит.

Словник брендів — 116 значень `<vendor>` з фіду плюс EXTRA_BRANDS: бренди,
які трапляються лише в назвах. Авто-детект тут не працює: він дає 772
кандидати, бо не відрізняє бренд від назви моделі.

Запуск:
    python3 tools/prom_kw_finalize.py --batch docs/prom_kw_batch01.json
    python3 tools/prom_kw_finalize.py --all
"""
import argparse
import collections
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(BASE_DIR, 'tools'))
from prom_keywords import natural, validate, MAX_PHRASES  # noqa: E402

FEED = os.path.join(BASE_DIR, 'output', 'noire_prom.xml')

# Бренди, присутні в назвах, але відсутні серед <vendor>. Список ведеться
# руками свідомо: автоматика на цьому місці дає 772 хибні спрацювання.
EXTRA_BRANDS = {'jes-extender', 'jes extender'}
NOT_A_BRAND = {'без бренда', 'без бренду', 'no brand', 'noname', ''}

COLOR = (r'чорн|біл|червон|рожев|син|зелен|фіолетов|бежев|тілесн|прозор|'
         r'золот|срібн|коричнев|мʼятн|мятн|салатов|бузков|темн|'
         r'black|white|pink|red|blue|green|purple|plum|rose|aqua|vanilla|'
         r'chocolate|gold|silver|violet|mint|melon|petrol|turquoise|coral')
# «Deep Rose» проти «Plum»: без зняття модифікатора основи не збігаються
# і пара не розпізнається як варіанти одного товару.
MODIFIER = (r'deep|dark|light|hot|neon|pastel|midnight|wine|royal|baby|'
            r'rich|soft|bright|pale|темно|світло|яскраво')
VARIANT = re.compile(r'\b(?:' + COLOR + r'|' + MODIFIER + r')\w*\b', re.I)
SIZE = re.compile(r'\b(?:XS|S|M|L|XL|XXL|[2-7]XL|\d+\s?in|\d+\s?inch)\b', re.I)


def brand_vocab(root) -> set:
    v = set()
    for o in root.findall('.//offer'):
        name = (o.findtext('vendor') or '').strip().lower()
        if name and name not in NOT_A_BRAND:
            v.add(name)
    return v | EXTRA_BRANDS


def foreign_brand(phrase: str, vendor: str, vocab: set):
    """Назва якого чужого бренду сидить у фразі (або None)."""
    p = ' ' + re.sub(r'[-]', ' ', phrase.lower()) + ' '
    own = re.sub(r'[-]', ' ', (vendor or '').lower())
    for b in vocab:
        bn = re.sub(r'[-]', ' ', b)
        if bn == own or len(bn) < 4:
            continue
        if re.search(r'(?<!\w)' + re.escape(bn) + r'(?!\w)', p):
            # власний бренд може містити чужий як підрядок — це не забруднення
            if bn in own:
                continue
            return b
    return None


def sibling_key(name: str, vendor: str, category: str) -> tuple:
    """Ключ групи варіантів: назва без кольору й розміру."""
    t = VARIANT.sub(' ', name)
    t = SIZE.sub(' ', t)
    t = re.sub(r'[^\w\sʼ]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip().lower()
    return (vendor, category, t)


def finalize(rows: list, vocab: set) -> dict:
    """Проставляє row['final'] з урахуванням обох правил."""
    groups = collections.defaultdict(list)
    for r in rows:
        r['_key'] = sibling_key(r['name'], r.get('vendor', ''),
                                r.get('cat', r.get('category', '')))
        groups[r['_key']].append(r)

    stat = collections.Counter()
    for r in rows:
        vendor = r.get('vendor', '')
        pool, rejected = [], []
        seen = set()
        norm = lambda x: re.sub(r'[-\s]+', ' ', x).strip()
        for p in r['level1'] + r.get('level2', []):
            # Фраза має виглядати як реальний пошуковий запит, а не як
            # склейка полів: «портупея/збруя bijoux pour toi», «силіконовий
            # лубрикант 100мл pjur». Перевірка спільна з Рівнем 1.
            if not natural(p):
                stat['неприродна фраза'] += 1
                continue
            b = foreign_brand(p, vendor, vocab)
            if b:
                rejected.append((p, b))
                continue
            if norm(p) in seen:
                continue
            seen.add(norm(p))
            pool.append(p)

        # частота фрази всередині групи варіантів
        sibs = groups[r['_key']]
        shared = collections.Counter()
        for s in sibs:
            for p in set(s['level1'] + s.get('level2', [])):
                shared[norm(p)] += 1
        uniq = {p for p in pool if shared[norm(p)] == 1} if len(sibs) > 1 else set()

        # найспецифічніша фраза лишається першою, далі — унікальні,
        # і лише потім спільні для всієї групи
        head = pool[:1]
        rest = [p for p in pool[1:] if p in uniq] + \
               [p for p in pool[1:] if p not in uniq]
        r['final'] = (head + rest)[:MAX_PHRASES]
        r['keywords'] = ', '.join(r['final'])
        r['rejected'] = rejected
        r['siblings'] = len(sibs)
        stat['фраз відкинуто'] += len(rejected)
        stat['товарів із відкинутими'] += 1 if rejected else 0
        stat['товарів у групах варіантів'] += 1 if len(sibs) > 1 else 0
        r.pop('_key', None)
    return stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--show', nargs='*')
    a = ap.parse_args()

    root = ET.parse(FEED).getroot()
    vocab = brand_vocab(root)
    print(f'словник брендів: {len(vocab)} назв')

    if a.all:
        path = os.path.join(BASE_DIR, 'docs', 'prom_kw_level1_all.json')
        rows = json.load(open(path))
        cats = {c.get('id'): (c.text or '') for c in root.findall('.//category')}
        meta = {o.findtext('vendorCode'): ((o.findtext('vendor') or '').strip(),
                                           cats.get(o.findtext('categoryId'), ''))
                for o in root.findall('.//offer')}
        for r in rows:
            r['vendor'], r['cat'] = meta.get(r['sku'], ('', ''))
    else:
        path = a.batch
        rows = json.load(open(path))

    stat = finalize(rows, vocab)
    bad = [(r['sku'], p, w) for r in rows for p, w in validate(r['final'])]
    json.dump(rows, open(path, 'w'), ensure_ascii=False, indent=1)

    n = len(rows)
    print(f'товарів: {n}')
    for k, v in stat.items():
        print(f'   {k}: {v}')
    print(f'   порушень валідації: {len(bad)}')
    print(f'   з ≥3 фразами: {sum(1 for r in rows if len(r["final"]) >= 3)}')
    print(f'→ {path}')

    for sku in (a.show or []):
        r = next((x for x in rows if x['sku'] == sku), None)
        if not r:
            continue
        print(f"\n{sku}  {r['name'][:70]}")
        print(f"   vendor: {r.get('vendor')} | варіантів у групі: {r['siblings']}")
        if r['rejected']:
            print(f"   ВІДКИНУТО: " +
                  '; '.join(f'«{p}» (бренд {b})' for p, b in r['rejected']))
        print(f"   ПОЛЕ: {r['keywords']}")


if __name__ == '__main__':
    main()
