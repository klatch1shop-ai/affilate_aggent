#!/usr/bin/env python3
"""Черга пошуку конкурентів по товарах KATRAN. Одна позиція — один запис.

Завдання власника 12.10.2026: «по кожному товару по черзі провести пошук
конкурентів та зафіксувати ціни, по яких продаються, аби розуміти, як ми
можемо продавати».

Пошук РОБИТЬ ЛЮДИНА АБО CLAUDE — тут лише черга й сховище результатів.
Автоматичний скрейпінг агрегаторів не роблю свідомо: Rozetka закрила
/search у robots, а Hotline та Comfy віддають ціни лише в браузері.
Замість вигадувати числа, записуємо те, що справді знайдено, з джерелом.

    venv/bin/python tools/katran_competitors.py черга            # що далі
    venv/bin/python tools/katran_competitors.py внести SO123 \
        --ціни "8377 hotline; 8999 foxtrot" --висновок "ми дорожчі на 24%"
    venv/bin/python tools/katran_competitors.py звіт
"""
import argparse
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
# Фід лежить локально: на сервері це ~/noire-feed, на ноутбуці — копія в
# репозиторії, щоб інструмент працював на обох вузлах без налаштування.
ФІД = next((p for p in (
    os.getenv('KATRAN_FEED') or '',
    os.path.expanduser('~/noire-feed/katran_rozetka_pobutova.xml'),
    os.path.join(BASE, 'data', 'katran', 'katran_rozetka_pobutova.xml'),
) if p and os.path.exists(p)), '')
СХОВИЩЕ = os.path.join(BASE, 'data', 'katran_competitors.json')
# Стоп-категорії Rozetka: туди не можна, тому й шукати нема сенсу.
СТОП = {'Пральні машини', 'Блендери', 'Мультиварки', 'Тримери'}


def товари():
    with open(ФІД, encoding='utf-8') as f:
        t = f.read()
    cats = dict(re.findall(r'<category id="(\d+)"[^>]*>([^<]+)</category>', t))
    out = []
    for b in re.findall(r'<offer .*?</offer>', t, re.S):
        g = lambda k: (re.search(rf'<{k}>([^<]*)</{k}>', b) or [None, None])[1]
        cat = cats.get(g('categoryId'), '')
        if cat in СТОП:
            continue
        out.append({'article': g('vendorCode') or g('article'),
                    'name': g('name_ua') or g('name'), 'vendor': g('vendor'),
                    'price': float(g('price') or 0), 'cat': cat})
    return out


def сховище():
    if os.path.exists(СХОВИЩЕ):
        with open(СХОВИЩЕ, encoding='utf-8') as f:
            return json.load(f)
    return {}


def зберегти(d):
    os.makedirs(os.path.dirname(СХОВИЩЕ), exist_ok=True)
    tmp = СХОВИЩЕ + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, СХОВИЩЕ)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    q = sub.add_parser('черга'); q.add_argument('--скільки', type=int, default=10)
    q.add_argument('--категорія')
    v = sub.add_parser('внести'); v.add_argument('article')
    v.add_argument('--ціни', required=True,
                   help='"8377 hotline; 8999 foxtrot" — ціна і джерело через ;')
    v.add_argument('--висновок', default='')
    sub.add_parser('звіт')
    a = ap.parse_args()
    t, d = товари(), сховище()

    if a.cmd == 'черга':
        лишилось = [x for x in t if x['article'] not in d]
        if a.категорія:
            лишилось = [x for x in лишилось if x['cat'] == a.категорія]
        print(f'досліджено {len(d)} з {len(t)} · у черзі {len(лишилось)}')
        for x in лишилось[:a.скільки]:
            print(f"  {x['article'][:18]:18} {x['price']:8.0f}  "
                  f"{x['vendor'][:12]:12} {x['cat'][:18]:18} {(x['name'] or '')[:44]}")

    elif a.cmd == 'внести':
        наш = next((x for x in t if x['article'] == a.article), None)
        if not наш:
            sys.exit(f'{a.article} немає у фіді (або це стоп-категорія)')
        ціни = []
        for шм in a.ціни.split(';'):
            m = re.match(r'\s*([\d\s]+)\s*(.*)', шм)
            if m:
                ціни.append({'ціна': int(re.sub(r'\s', '', m.group(1))),
                             'джерело': m.group(2).strip()})
        if not ціни:
            sys.exit('не розібрав жодної ціни')
        мін = min(c['ціна'] for c in ціни)
        d[a.article] = {'наша': наш['price'], 'назва': наш['name'],
                        'категорія': наш['cat'], 'конкуренти': ціни,
                        'мін_конкурент': мін,
                        'різниця_%': round((наш['price'] - мін) / мін * 100, 1),
                        'висновок': a.висновок, 'коли': time.strftime('%Y-%m-%d')}
        зберегти(d)
        print(f"{a.article}: наша {наш['price']:.0f} · мін конкурент {мін} · "
              f"ми {'дорожчі' if наш['price'] > мін else 'дешевші'} на "
              f"{abs(d[a.article]['різниця_%'])}%")

    elif a.cmd == 'звіт':
        if not d:
            sys.exit('ще нічого не досліджено')
        дорожчі = [v for v in d.values() if v['різниця_%'] > 0]
        print(f'досліджено: {len(d)} з {len(t)}')
        print(f'ми ДОРОЖЧІ за найдешевшого конкурента: {len(дорожчі)} '
              f'({len(дорожчі) / len(d) * 100:.0f}%)')
        if дорожчі:
            сер = sum(v['різниця_%'] for v in дорожчі) / len(дорожчі)
            print(f'  у середньому на {сер:.0f}%')
        print()
        for k, v in sorted(d.items(), key=lambda x: -x[1]['різниця_%']):
            знак = '+' if v['різниця_%'] > 0 else ''
            print(f"  {k[:18]:18} наша {v['наша']:8.0f} · конкурент {v['мін_конкурент']:8} "
                  f"· {знак}{v['різниця_%']:6.1f}%  {v['категорія'][:16]}")


if __name__ == '__main__':
    main()
