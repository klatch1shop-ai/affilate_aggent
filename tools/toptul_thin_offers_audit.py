#!/usr/bin/env python3
"""Чому 1035 офферів TOPTUL відсіялось на «менше 3 характеристик».

Питання з черги: це справді бідні картки постачальника — чи характеристики
є, але під іменами, яких `collect_params()` не бачить?

Відповідати на це «схоже, все добре» не можна (правило позитивного контролю).
Тому інструмент:

  1. **перелічує реальні теги** офферів, а не вірить у `<param>`. Якщо
     характеристики лежать у `<attribute>`, `<feature>` чи в атрибутах
     оффера — це видно з переліку, а не з припущення;
  2. **повторює конвеєр генератора в тому самому порядку** (id → дубль →
     категорія → ціна → фото → характеристики), бо 1035 — це число ПІСЛЯ
     попередніх фільтрів, і рахувати його на всьому фіді означало б міряти
     інше;
  3. **друкує 10 відсіяних SKU дослівно** — усі їхні `<param>`, опис,
     категорію, — щоб поріг `MIN_PARAMS` мінявся після погляду на дані, а не
     до нього;
  4. **міряє контрольну групу** — офферів, що пройшли, — тими самими мірками.
     Якщо в бідних і в нормальних карток однакова частка описів зі списком
     характеристик, то справа не в бідності постачальника;
  5. **рахує втрату `unit`** — `collect_params()` бере лише текст `<param>`,
     а одиниця виміру лежить в атрибуті `unit`. «12» без «мм» — це не менше
     характеристик, але гірша характеристика.

Запуск (на сервері, де лежить /tmp/toptul.xml і є база):
    python3 tools/toptul_thin_offers_audit.py
    python3 tools/toptul_thin_offers_audit.py --samples 20 --json out.json
"""
import argparse
import collections
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2.extras  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402

import toptul_rozetka_generator as G  # noqa: E402

FEED = os.getenv('TOPTUL_FEED_FILE', '/tmp/toptul.xml')

# Рядок «назва: значення» в описі — ознака того, що характеристики в картці є,
# просто не винесені в теги. Двокрапка й тире, бо TOPTUL уживає обидва.
_DESC_PAIR = re.compile(r'^\s*[-–•* ]*\s*([^:\n<]{2,40})\s*[:—-]\s*(\S[^\n<]{0,80})\s*$',
                        re.M)
_LI = re.compile(r'<li[^>]*>(.*?)</li>', re.I | re.S)


def desc_pairs(desc: str) -> list:
    """Пари «характеристика — значення», що лежать у тілі опису."""
    if not desc:
        return []
    items = [G.plain(x) for x in _LI.findall(desc)] or []
    body = desc if not items else '\n'.join(items)
    body = re.sub(r'<br\s*/?>', '\n', body, flags=re.I)
    body = G._TAGS.sub('\n', body)
    out = []
    for k, v in _DESC_PAIR.findall(body):
        k, v = k.strip(), v.strip()
        if k and v and len(k) >= 2:
            out.append((k, v))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--feed', default=FEED)
    ap.add_argument('--samples', type=int, default=10,
                    help='скільки відсіяних SKU показати дослівно')
    ap.add_argument('--json', help='куди скласти повний перелік відсіяних')
    args = ap.parse_args()

    if not os.path.exists(args.feed):
        sys.exit(f'Фід не знайдено: {args.feed}')

    root = ET.parse(args.feed).getroot()
    offers = root.find('shop').find('offers').findall('offer')
    print(f'Офферів у фіді: {len(offers)}')

    # ── 1. Які теги взагалі є. Крок 1 правила позитивного контролю ──────────
    tags = collections.Counter()
    for o in offers:
        for ch in o:
            tags[ch.tag] += 1
    print('\n--- дочірні теги оффера (вживань) ---')
    for t, c in tags.most_common():
        print(f'{c:9d}  {t}')
    other = [t for t in tags
             if t not in ('param', 'picture') and
             re.search(r'attr|feature|charact|prop|specif|option', t, re.I)]
    print('Теги, схожі на характеристики поза <param>: '
          + (', '.join(other) if other else 'НЕМАЄ'))

    fields = G.resolve_fields(offers)

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cats = G.load_categories(cur)
    tr = G.load_translations(cur)
    cur.close()
    conn.close()

    # ── 2. Той самий конвеєр, той самий порядок ────────────────────────────
    stats = collections.Counter()
    seen_ids = set()
    thin, passed = [], []
    for o in offers:
        sku = (o.get('id') or '').strip()
        cid = G._txt(o, fields['cat'])
        if not sku:
            stats['без id'] += 1
            continue
        if sku in seen_ids:
            stats['дубль id'] += 1
            continue
        seen_ids.add(sku)
        if cid not in cats:
            stats['категорія без rz_id'] += 1
            continue
        try:
            price = float((G._txt(o, fields['price']) or '0').replace(',', '.'))
        except ValueError:
            price = 0.0
        if price <= 0:
            stats['без ціни'] += 1
            continue
        if not G.pictures(o, collections.Counter()):
            stats['без фото'] += 1
            continue

        vendor = G._txt(o, fields['vendor']) or 'TOPTUL'
        prm = G.collect_params(o, tr)
        if vendor and not any(k.lower() in ('бренд', 'виробник', 'торгова марка')
                              for k in prm):
            prm['Бренд'] = [vendor]

        rec = {
            'sku': sku,
            'cat': cid,
            'rz': cats[cid][0],
            'rz_name': cats[cid][1],
            'name': G._txt(o, fields['name']),
            'n_param_tags': len(o.findall('param')),
            'n_params': len(prm),
            'params': {k: v for k, v in prm.items()},
            'units': [p.get('unit') for p in o.findall('param') if p.get('unit')],
            'desc_len': len(G.plain(G._txt(o, fields['desc']))),
            'desc_pairs': desc_pairs(G._txt(o, fields['desc'])),
        }
        if len(prm) < G.MIN_PARAMS:
            stats['менше 3 характеристик'] += 1
            thin.append(rec)
        else:
            passed.append(rec)

    print('\n--- конвеєр (у порядку генератора) ---')
    for k, v in stats.most_common():
        print(f'{v:9d}  {k}')
    print(f'{len(passed):9d}  ПРОЙШЛО до наступних перевірок')

    # ── 3. Позитивний контроль самого лічильника ───────────────────────────
    # Нуль або «все добре» читається як факт про дані лише тоді, коли та сама
    # перевірка на завідомо різних випадках дає різні числа.
    if thin and passed:
        print(f'\nКонтроль лічильника: бідна картка {thin[0]["sku"]} — '
              f'{thin[0]["n_params"]} характеристик, '
              f'нормальна {passed[0]["sku"]} — {passed[0]["n_params"]}. '
              f'Числа різні, отже лічильник рахує.')
    else:
        print('\nУВАГА: одна з груп порожня — лічильник не доведено, '
              'решту чисел читати не можна.')

    # ── 4. Скільки саме характеристик у відсіяних ──────────────────────────
    dist = collections.Counter(r['n_params'] for r in thin)
    print('\n--- відсіяні: скільки в них характеристик ---')
    for n in sorted(dist):
        print(f'   {n} характеристик — {dist[n]} офферів')
    zero_tags = sum(1 for r in thin if r['n_param_tags'] == 0)
    lost = sum(1 for r in thin if r['n_param_tags'] > r['n_params'])
    print(f'   із них БЕЗ ЖОДНОГО тега <param> у фіді: {zero_tags}')
    print(f'   тегів більше, ніж характеристик (дублі імен/порожні '
          f'значення/нульова гарантія): {lost}')

    print('\n--- назви характеристик, які у відсіяних усе ж є ---')
    names = collections.Counter(k for r in thin for k in r['params'])
    for n, c in names.most_common(25):
        print(f'{c:7d}  {n}')

    print('\n--- категорії відсіяних (топ-15) ---')
    bycat = collections.Counter(f'{r["rz"]} {r["rz_name"]}' for r in thin)
    for n, c in bycat.most_common(15):
        share = c / max(1, sum(1 for r in thin + passed
                              if f'{r["rz"]} {r["rz_name"]}' == n))
        print(f'{c:7d}  {n}   ({share:.0%} категорії)')

    # ── 5. Контрольна група тими самими мірками ────────────────────────────
    def avg(rs, key):
        return sum(r[key] for r in rs) / len(rs) if rs else 0

    thin_with_pairs = sum(1 for r in thin if len(r['desc_pairs']) >= 3)
    pass_with_pairs = sum(1 for r in passed if len(r['desc_pairs']) >= 3)
    print('\n--- відсіяні проти тих, що пройшли ---')
    print(f'   опис, середня довжина:  бідні {avg(thin, "desc_len"):.0f} · '
          f'нормальні {avg(passed, "desc_len"):.0f}')
    print(f'   ≥3 пари «назва: значення» в описі: '
          f'бідні {thin_with_pairs}/{len(thin)} '
          f'({thin_with_pairs / max(1, len(thin)):.0%}) · '
          f'нормальні {pass_with_pairs}/{len(passed)} '
          f'({pass_with_pairs / max(1, len(passed)):.0%})')

    # ── 6. Втрата одиниць виміру ───────────────────────────────────────────
    tot_units = sum(len(r['units']) for r in thin + passed)
    off_units = sum(1 for r in thin + passed if r['units'])
    print(f'\n--- атрибут unit ---\n   параметрів з unit: {tot_units} '
          f'у {off_units} офферах; collect_params() бере лише текст тега, '
          f'тобто одиниця втрачається')

    # ── 7. Дослівно, очима ─────────────────────────────────────────────────
    print(f'\n--- {min(args.samples, len(thin))} відсіяних SKU дослівно ---')
    idx = {o.get('id'): o for o in offers}
    for r in thin[:args.samples]:
        o = idx.get(r['sku'])
        print(f'\nSKU {r["sku"]} · категорія {r["cat"]} → rz {r["rz"]} '
              f'{r["rz_name"]}')
        print(f'  назва: {r["name"][:110]}')
        raw = o.findall('param') if o is not None else []
        print(f'  тегів <param>: {len(raw)}')
        for p in raw:
            print(f'    [{p.get("name")}] unit={p.get("unit")!r} '
                  f'-> {(p.text or "").strip()[:70]!r}')
        print(f'  після collect_params: {list(r["params"])}')
        print(f'  опис: {r["desc_len"]} символів, '
              f'пар у описі: {len(r["desc_pairs"])} '
              f'{r["desc_pairs"][:4]}')

    # ── 8. Що дав би інший поріг ───────────────────────────────────────────
    print('\n--- контрфакт: скільки повернулось би ---')
    for th in (1, 2, 3):
        back = sum(1 for r in thin if r['n_params'] >= th)
        print(f'   MIN_PARAMS={th}: повертається {back} офферів')
    gain = sum(1 for r in thin
               if r['n_params'] + len(r['desc_pairs']) >= G.MIN_PARAMS
               and len(r['desc_pairs']) > 0)
    print(f'   якби характеристики добувались з опису: {gain} офферів '
          f'дотягли б до {G.MIN_PARAMS}')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(thin, f, ensure_ascii=False, indent=1)
        print(f'\nПовний перелік відсіяних: {args.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
