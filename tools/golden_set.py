#!/usr/bin/env python3
"""Золотий набір: чи збігається наш автоматичний суддя з людиною.

Навіщо (власник, 03.10.2026): зараз ми знаємо лише, що перевірник
узгоджується САМ ІЗ СОБОЮ — два вендори кажуть «так». Це не те саме, що
«він правий». Практика 2026: взяти 20-50 задач зі СПРАВЖНІХ збоїв, де є
вердикт людини, і порахувати згоду.

Матеріал у нас є, але не той, про який думалось спочатку:
  * ФОТО — 122 картки Єпіцентру з письмовими коментарями модератора. Це
    справжня людська розмітка: «замініть головне фото», «товар має бути в
    єдиному екземплярі». Нею калібрується photo_pick_main.
  * КЛЮЧІ — людської розмітки НЕМАЄ. Є лише наші власні виміри. Тому
    ключовий набір наповнюється випадками, де істину встановлено ОКРЕМО
    від судді: підміна типу, перевірена очима, і частота ключа в каталозі.

Згода міряється каппою Коена, а не часткою збігів: при перекосі класів
«90 % збігу» може означати, що суддя просто завжди каже «ні».

    venv/bin/python3 tools/golden_set.py --build photo
    venv/bin/python3 tools/golden_set.py --score photo
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
SETS = os.path.join(BASE, 'data', 'golden')


def kappa(pairs):
    """Каппа Коена для двох бінарних суддів. pairs: [(людина, машина)]."""
    n = len(pairs)
    if not n:
        return None
    agree = sum(1 for h, m in pairs if h == m) / n
    ph = sum(1 for h, _ in pairs if h) / n
    pm = sum(1 for _, m in pairs if m) / n
    chance = ph * pm + (1 - ph) * (1 - pm)
    if chance >= 1:
        return None
    return (agree - chance) / (1 - chance)


def build_photo():
    """Людська розмітка: що саме модератор Єпіцентру написав про фото."""
    com = json.load(open(os.path.join(BASE, 'exports',
                                      'epicentr_ban_comments.json'), encoding='utf-8'))
    rows = []
    for c in com:
        t = (c.get('text') or '').lower()
        if 'фото' not in t:
            continue
        if 'єдиному екземплярі' in t or 'єдиному ракурсі' in t:
            reason = 'кілька екземплярів або ракурсів'
        elif 'без написів' in t:
            reason = 'написи або зайві елементи'
        else:
            reason = 'інше про фото'
        rows.append({'sku': c['sku'], 'людина': 'погане', 'причина': reason,
                     'джерело': f"модератор {c.get('author','')} {c.get('at','')[:10]}"})
    # ПОЗИТИВНІ приклади: картки зі статусом «published». Це теж вердикт
    # модератора — він їх ПРИЙНЯВ. Без них набір має 126 поганих і 2 добрі,
    # і каппа на такому перекосі нічого не показує.
    #
    # Вибірка СТРАТИФІКОВАНА за набором атрибутів: беремо прийняті картки з
    # тих самих груп товарів, що й відхилені. Інакше порівнюватимемо
    # косметику з іграшками — на цьому вже спіткнулись 30.09.
    import random
    prods = json.load(open(os.path.join(BASE, 'data', 'epicentr_products.json'),
                           encoding='utf-8'))
    bad_sets = {p.get('attributeSetCode') for p in prods
                if p['sku'] in {r['sku'] for r in rows}}
    good = [p for p in prods if p['status'] == 'published'
            and p.get('attributeSetCode') in bad_sets]
    random.Random(20261003).shuffle(good)
    for p in good[:len(rows)]:
        rows.append({'sku': p['sku'], 'людина': 'добре',
                     'причина': 'пройшла модерацію Єпіцентру',
                     'джерело': f'status=published, набір {p.get("attributeSetCode")}'})
    rows += [
        {'sku': 'конкурент-пеньюар', 'людина': 'добре', 'причина': 'прийнято Єпіцентром',
         'url': 'https://cdn.27.ua/sc--media--prod/default/6d/86/6e/'
                '6d866e51-854b-49d2-be5b-34344eebb01b.jpg'},
        {'sku': 'конкурент-бодістокінг', 'людина': 'добре', 'причина': 'прийнято Єпіцентром',
         'url': 'https://cdn.27.ua/sc--media--prod/default/68/79/9b/'
                '68799bc9-5913-4012-9006-3280c46d5b5f.jpg'},
    ]
    os.makedirs(SETS, exist_ok=True)
    path = os.path.join(SETS, 'photo.json')
    json.dump(rows, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    bad = sum(1 for r in rows if r['людина'] == 'погане')
    print(f'золотий набір «фото»: {len(rows)} випадків '
          f'({bad} поганих, {len(rows)-bad} добрих) → {path}')
    if bad and len(rows) - bad < bad * 0.5:
        print('УВАГА: класи перекошені, каппа буде нестабільна')


def score_photo(limit):
    """Чи згоден наш детермінований відбір фото з модератором."""
    import psycopg2
    from tools.photo_pick_main import rate
    rows = json.load(open(os.path.join(SETS, 'photo.json'), encoding='utf-8'))
    conn = psycopg2.connect(host='192.168.3.28', dbname='agentdb',
                            user='agentadmin', password='1')
    cur = conn.cursor()
    pairs, detail = [], []
    for r in rows[:limit] if limit else rows:
        if r.get('url'):
            urls = [r['url']]
        else:
            cur.execute('select pictures from sexopt_products where sku=%s', (r['sku'],))
            got = cur.fetchone()
            urls = (got[0] or [])[:1] if got else []
        if not urls:
            continue
        try:
            sc = rate(urls[0], use_ocr=False)['score']
        except Exception:
            continue
        machine = 'добре' if sc >= 3.9 else 'погане'
        pairs.append((r['людина'] == 'погане', machine == 'погане'))
        detail.append((r['sku'], r['людина'], machine, round(sc, 2)))
    k = kappa(pairs)
    agree = sum(1 for h, m in pairs if h == m) / max(len(pairs), 1)
    print(f'порівняно: {len(pairs)} випадків')
    print(f'проста згода: {agree*100:.1f}%')
    print(f'каппа Коена: {k:.3f}' if k is not None else 'каппа: не рахується')
    print('\nрозбіжності:')
    for sku, h, m, sc in detail:
        if h != m:
            print(f'   {sku:<22} людина={h:<7} машина={m:<7} бал={sc}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', choices=['photo'])
    ap.add_argument('--score', choices=['photo'])
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    if a.build == 'photo':
        build_photo()
    elif a.score == 'photo':
        score_photo(a.limit)
    else:
        ap.print_help()
