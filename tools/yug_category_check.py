#!/usr/bin/env python3
"""Звірка категорій фіду з тим, де ці самі товари лежать на Rozetka.

Гейт №2 зі SKILL-36: категорія має бути та, де лежать ТІ САМІ товари
конкурентів, а не та, яку ми вважаємо правильною. Постачальник дає
`rozetka_code`, але він може бути застарілим або з іншої гілки.

Метод — публічні ендпойнти Rozetka (SKILL-30): пошук за артикулом,
картка товару, `category_id` з неї. Конкурентом вважається лише картка
з ТИМ САМИМ артикулом.

    venv/bin/python tools/yug_category_check.py --на-категорію 3
"""
import argparse
import collections
import csv
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'tools'))
import rozetka_competitors as RC   # noqa: E402

ВІДБІР = os.path.join(BASE, 'exports', 'yug_відбір.csv')
НАЗВИ = os.path.join(BASE, 'data', 'rozetka_category_names.json')
OUT = os.path.join(BASE, 'exports', 'yug_категорії_звірка.csv')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--на-категорію', type=int, default=3, dest='на_категорію')
    ap.add_argument('--категорій', type=int, default=0)
    a = ap.parse_args()
    рядки = list(csv.DictReader(open(ВІДБІР, encoding='utf-8')))
    назви = json.load(open(НАЗВИ, encoding='utf-8')) if os.path.exists(НАЗВИ) else {}
    по_кат = collections.defaultdict(list)
    for r in рядки:
        по_кат[r['категорія_rz']].append(r)
    категорії = sorted(по_кат, key=lambda c: -len(по_кат[c]))
    if a.категорій:
        категорії = категорії[:a.категорій]
    print(f'категорій до звірки: {len(категорії)}')

    http = RC.Http(os.path.join(BASE, 'data', 'rz_cat_check_cache.json'), 72)
    sellers, звіт = {}, []
    for i, cid in enumerate(категорії, 1):
        проба = по_кат[cid][:a.на_категорію]
        чужі = collections.Counter()
        знайдено = 0
        for r in проба:
            try:
                картки, _ = RC.find(http, r['артикул'], sellers)
            except Exception as e:
                print(f"  {r['артикул']}: {type(e).__name__}", file=sys.stderr)
                continue
            for c in (картки or []):
                if c.get('category_id'):
                    чужі[int(c['category_id'])] += 1
            знайдено += len(картки or [])
            time.sleep(0.3)
        наша = int(cid)
        збіг = чужі.get(наша, 0)
        найчастіша = чужі.most_common(1)[0] if чужі else (None, 0)
        стан = ('немає конкурентів' if not чужі
                else 'збіг' if найчастіша[0] == наша
                else 'РОЗБІЖНІСТЬ')
        звіт.append({'категорія_наша': наша, 'назва_наша': назви.get(str(наша), ''),
                     'товарів_у_фіді': len(по_кат[cid]),
                     'перевірено_артикулів': len(проба),
                     'карток_конкурентів': знайдено,
                     'у_нашій_категорії': збіг,
                     'найчастіша_чужа': найчастіша[0] or '',
                     'назва_чужої': назви.get(str(найчастіша[0]), ''),
                     'скільки_там': найчастіша[1], 'стан': стан})
        print(f"{i:3}/{len(категорії)} {наша:>9} {назви.get(str(наша),'')[:28]:28} "
              f"×{len(по_кат[cid]):<4} {стан}")
        http.save()
    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(звіт[0])); w.writeheader(); w.writerows(звіт)
    c = collections.Counter(x['стан'] for x in звіт)
    print(f'\nпідсумок: {dict(c)}')
    print(f'→ {OUT}')


if __name__ == '__main__':
    main()
