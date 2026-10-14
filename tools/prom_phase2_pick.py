#!/usr/bin/env python3
"""Відбір позицій Фази 2 для випуску у фід Prom, у межах ліміту магазину.

Фаза 2 — еротична білизна й одяг (2869 позицій). Випустити всі не можна:
ліміт магазину 6000, а у фіді вже 5410.

ЯК ВІДБИРАЄМО. Беремо не свою реконструкцію, а СПРАВЖНІЙ повний фід,
зібраний генератором без позначки «Фаза 2» (`--повний`). У ньому вже
застосовані всі ворота якості: опис, мінімум 2 фото, характеристики,
обʼєднання розмірів у різновиди.

ЧИМ МІРЯЄМО «найкращу картку». Про продажі цих позицій даних немає, тому
не вгадуємо попит, а міряємо повноту картки — саме вона вирішує, чи
пройде товар модерацію і чи знайдуть його у фільтрах каталогу:
фото → характеристики → довжина опису.

ГРУПИ НЕ РОЗРИВАЄМО: розміри одного товару обʼєднані через group_id.
Випустити три розміри з пʼяти означало б показати неповний розмірний ряд.

    venv/bin/python tools/prom_phase2_pick.py --повний /tmp/probe_full.xml
    venv/bin/python tools/prom_phase2_pick.py --повний /tmp/probe_full.xml --записати
"""
import argparse
import json
import os
import re
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ВИХІД = os.path.join(BASE, 'data', 'prom_phase2_release.json')
ФІД = os.path.join(BASE, 'output', 'noire_prom.xml')


def офери(шлях):
    with open(шлях, encoding='utf-8') as f:
        t = f.read()
    cats = dict(re.findall(r'<category id="(\d+)"[^>]*>([^<]+)</category>', t))
    out = []
    for b in re.findall(r'<offer .*?</offer>', t, re.S):
        i = re.search(r'\bid="([^"]+)"', b)
        g = re.search(r'group_id="(\d+)"', b)
        c = re.search(r'<categoryId>(\d+)</categoryId>', b)
        out.append({
            'id': i.group(1) if i else '',
            'група': g.group(1) if g else None,
            'категорія': cats.get(c.group(1), '?') if c else '?',
            'фото': b.count('<picture>'),
            'характеристик': b.count('<param '),
            'опис': len(re.search(r'<description>(.*?)</description>', b, re.S).group(1))
                    if '<description>' in b else 0,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--повний', required=True,
                    help='фід, зібраний БЕЗ позначки «Фаза 2»')
    ap.add_argument('--ліміт', type=int, default=6000)
    ap.add_argument('--записати', action='store_true')
    a = ap.parse_args()

    є = {o['id'] for o in офери(ФІД)} if os.path.exists(ФІД) else set()
    усі = офери(a.повний)
    нові = [o for o in усі if o['id'] not in є]
    місце = a.ліміт - len(є)
    print(f'у фіді зараз: {len(є)} · ліміт: {a.ліміт} · місця: {місце}')
    print(f'кандидатів Фази 2: {len(нові)}')
    if місце <= 0:
        print('місця немає')
        return

    # Групуємо: різновиди одного товару йдуть разом або не йдуть зовсім.
    групи = defaultdict(list)
    for o in нові:
        групи[o['група'] or o['id']].append(o)

    def вага(g):
        # Середня повнота картки в групі: фото важливіші за характеристики,
        # характеристики — за довжину опису.
        return (sum(x['фото'] for x in g) / len(g),
                sum(x['характеристик'] for x in g) / len(g),
                sum(x['опис'] for x in g) / len(g))

    впорядковані = sorted(групи.values(), key=вага, reverse=True)
    відібрані, разом = [], 0
    for g in впорядковані:
        if разом + len(g) > місце:
            continue          # не розриваємо групу — шукаємо наступну меншу
        відібрані.extend(g)
        разом += len(g)
        if разом == місце:
            break

    from collections import Counter
    print(f'\nвідібрано: {разом} позицій у {len(set(o["група"] or o["id"] for o in відібрані))} групах')
    print(f'фід стане: {len(є) + разом} із {a.ліміт}')
    print('за категоріями:')
    for k, v in Counter(o['категорія'] for o in відібрані).most_common():
        print(f'   {v:5}  {k}')
    сер = (sum(o['фото'] for o in відібрані) / max(len(відібрані), 1),
           sum(o['характеристик'] for o in відібрані) / max(len(відібрані), 1))
    print(f'середньо на картку: {сер[0]:.1f} фото, {сер[1]:.1f} характеристик')
    решта = [o for o in нові if o not in відібрані]
    if решта:
        с2 = (sum(o['фото'] for o in решта) / len(решта),
              sum(o['характеристик'] for o in решта) / len(решта))
        print(f'у невідібраних   : {с2[0]:.1f} фото, {с2[1]:.1f} характеристик')

    if a.записати:
        os.makedirs(os.path.dirname(ВИХІД), exist_ok=True)
        with open(ВИХІД, 'w', encoding='utf-8') as f:
            json.dump({'ліміт': a.ліміт, 'позицій': разом,
                       'skus': sorted(o['id'] for o in відібрані)},
                      f, ensure_ascii=False, indent=1)
        print(f'\nзаписано {ВИХІД}')
    else:
        print('\n(нічого не записано — додайте --записати)')


if __name__ == '__main__':
    main()
