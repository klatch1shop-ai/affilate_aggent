#!/usr/bin/env python3
"""Добір атрибутів Єпіцентру ПО ОДНІЙ картці — з повним контекстом товару.

Відмінність від пачкового `epicentr_classify_deepseek.py`: там в один
запит іде 15 назв і одна характеристика, тут — одна картка й УСІ її
прогалини разом, плюс опис товару й наші витягнуті параметри. Пачка
дешевша, одна картка точніша: коли в назві «Спідниця під лак із
прозорою сіткою», рішення часто лежить саме в описі.

Порядок роботи: спершу пачковий прогін забирає очевидне, потім цей
добирає залишок. Так само, як з цінами конкурентів.

МЕЖА ДАНИХ: у запит ідуть лише назва, опис і характеристики товару.
Замовлення й покупці в DeepSeek не потрапляють ніколи.

Модель зобовʼязана відповісти «—», якщо підстави немає. Вигадане
значення гірше за порожнє: порожнє видно в аудиті, вигадане проходить
як факт.

    venv/bin/python tools/epicentr_classify_one.py --скільки 50
    venv/bin/python tools/epicentr_classify_one.py --тільки-порожні --скільки 300
"""
import argparse
import json
import os
import re
import sys
import time

from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.llm_router import call_deepseek, DEEPSEEK_FAST      # noqa: E402
from tools.epicentr_classify_deepseek import options                  # noqa: E402

GAPS = os.path.join(BASE, 'docs', 'epicentr_enrich_gaps.json')
PROD = os.path.join(BASE, 'data', 'epicentr_products.json')
OUT = os.path.join(BASE, 'exports', 'epicentr_deepseek_values.json')


def товарні_дані(skus):
    """{sku: {'опис': ..., 'параметри': {...}}} з нашої бази."""
    from shared.utils.db import get_connection
    cur = get_connection().cursor()
    out = {}
    cur.execute('select sku, name, description_html, vendor, country '
                'from sexopt_products where sku = any(%s)', (list(skus),))
    for r in cur.fetchall():
        опис = re.sub(r'<[^>]+>', ' ', r['description_html'] or '')
        out[r['sku']] = {'опис': re.sub(r'\s+', ' ', опис).strip()[:700],
                         'бренд': r['vendor'], 'країна': r['country'],
                         'параметри': {}}
    cur.execute('select sku, param_name, param_value from sexopt_extracted_params '
                'where sku = any(%s)', (list(skus),))
    for r in cur.fetchall():
        out.setdefault(r['sku'], {'опис': '', 'параметри': {}})
        out[r['sku']].setdefault('параметри', {})[r['param_name']] = r['param_value']
    return out


def спитати(назва_товару, дані, прогалини):
    """{код атрибута: назва значення} — одна відповідь на всю картку."""
    блоки = []
    for код, імʼя, дозволені in прогалини:
        блоки.append(f'{імʼя}: ' + ' | '.join(sorted(дозволені)))
    пар = '; '.join(f'{k}: {v}' for k, v in (дані.get('параметри') or {}).items())
    запит = (
        'Ти заповнюєш характеристики картки товару для маркетплейсу.\n'
        'Для КОЖНОЇ характеристики обери значення СУВОРО з її переліку.\n'
        'Якщо дані товару не дають прямої підстави — постав «—».\n'
        'Вигадане значення гірше за порожнє.\n'
        'Відповідь: по рядку на характеристику, «характеристика = значення».\n\n'
        f'Товар: {назва_товару}\n'
        + (f'Бренд: {дані.get("бренд")}\n' if дані.get('бренд') else '')
        + (f'Країна: {дані.get("країна")}\n' if дані.get('країна') else '')
        + (f'Характеристики постачальника: {пар}\n' if пар else '')
        + (f'Опис: {дані.get("опис")}\n' if дані.get('опис') else '')
        + '\nХарактеристики й дозволені значення:\n' + '\n'.join(блоки))
    txt, _, usage = call_deepseek(запит, model=DEEPSEEK_FAST, thinking=False,
                                  max_tokens=600)
    відп = {}
    for рядок in (txt or '').splitlines():
        m = re.match(r'\s*(.+?)\s*=\s*(.+?)\s*$', рядок)
        if not m:
            continue
        імʼя, значення = m.group(1).strip().lstrip('-').strip(), m.group(2).strip()
        for код, i, дозволені in прогалини:
            if i.lower() == імʼя.lower() and значення in дозволені:
                відп[код] = значення
    return відп, usage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--скільки', type=int, default=50)
    ap.add_argument('--тільки-порожні', action='store_true', dest='порожні',
                    help='лише картки, яким пачковий прогін нічого не дав')
    a = ap.parse_args()

    gaps = json.load(open(GAPS, encoding='utf-8'))
    назви = {str(p['id']): p.get('name') for p in json.load(open(PROD, encoding='utf-8'))}
    готове = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}

    цілі = []
    for g in gaps:
        якщо_є = готове.get(g['sku'], {}).get('значення', {})
        лишилось = [m for m in g['missing'] if m['code'] not in якщо_є]
        if not лишилось:
            continue
        if a.порожні and якщо_є:
            continue
        цілі.append((g, лишилось))
    цілі = цілі[:a.скільки]
    print(f'карток у роботі: {len(цілі)}')

    дані = товарні_дані({g['sku'] for g, _ in цілі})
    кеш_значень, заповнено, витрати = {}, 0, {'вхід': 0, 'вихід': 0}
    for n, (g, лишилось) in enumerate(цілі, 1):
        прогалини = []
        for m in лишилось:
            ключ = (str(g['category']), m['code'])
            if ключ not in кеш_значень:
                кеш_значень[ключ] = options(*ключ)
            if кеш_значень[ключ]:
                прогалини.append((m['code'], m['name'], кеш_значень[ключ]))
        if not прогалини:
            continue
        try:
            відп, usage = спитати(назви.get(str(g['id'])) or g['sku'],
                                   дані.get(g['sku'], {}), прогалини)
        except Exception as e:
            print(f"  {g['sku']}: {e}", file=sys.stderr)
            continue
        витрати['вхід'] += (usage or {}).get('вхід', 0)
        витрати['вихід'] += (usage or {}).get('вихід', 0)
        if відп:
            зап = готове.setdefault(g['sku'], {'id': g['id'],
                                               'набір': str(g['category']),
                                               'значення': {}})
            for код, значення in відп.items():
                імʼя = next(i for c, i, _ in прогалини if c == код)
                зап['значення'][код] = {'назва_атрибута': імʼя, 'значення': значення,
                                        'код_значення': кеш_значень[(str(g['category']), код)][значення]}
            заповнено += len(відп)
        if n % 20 == 0:
            print(f'  {n}/{len(цілі)} · заповнено значень {заповнено}')
            with open(OUT, 'w', encoding='utf-8') as f:
                json.dump(готове, f, ensure_ascii=False, indent=1)
        time.sleep(0.2)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(готове, f, ensure_ascii=False, indent=1)
    print(f'заповнено значень: {заповнено} · токени {витрати} → {OUT}')


if __name__ == '__main__':
    main()
