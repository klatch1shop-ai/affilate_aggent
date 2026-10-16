#!/usr/bin/env python3
"""Добір значень обовʼязкових атрибутів Єпіцентру через DeepSeek.

ЩО РОБИТЬ. Для карток у статусі enrich бере перелік того, чого бракує
(`docs/epicentr_enrich_gaps.json`), витягує ПОВНИЙ перелік дозволених
значень з merchant-api і просить DeepSeek обрати значення за назвою
товару. Нічого не записує: результат лягає у файл для перевірки очима.

МЕЖА ДАНИХ. У запит ідуть лише назви товарів і довідник значень — це
публічні дані картки. Замовлення, покупці, телефони в DeepSeek не
потрапляють ніколи.

ЧОМУ НЕ РЕГУЛЯРКИ. Своїми витягнутими параметрами ми закриваємо 12 %
прогалин. Дві найбільші — «Тип товару» (304) і «Стать» (213) — живуть у
назві товару словами, які регуляркою не перелічити: бодістокінг,
пеньюар, портупея, бюстьє.

ЧОМУ ДОЗВОЛЕНО НЕ ЗНАТИ. Модель зобовʼязана відповісти «—», якщо назва
не дає підстави. Вигадане значення гірше за порожнє: порожнє видно в
аудиті, а вигадане проходить як факт.

    venv/bin/python tools/epicentr_classify_deepseek.py --набір 7216 --скільки 40
    venv/bin/python tools/epicentr_classify_deepseek.py --усі --скільки 600
"""
import argparse
import collections
import json
import os
import re
import sys
import time

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.llm_router import call_deepseek, DEEPSEEK_FAST  # noqa: E402

MAPI = 'https://merchant-api.epicentrm.com.ua'
GAPS = os.path.join(BASE, 'docs', 'epicentr_enrich_gaps.json')
PROD = os.path.join(BASE, 'data', 'epicentr_products.json')
OUT = os.path.join(BASE, 'exports', 'epicentr_deepseek_values.json')
ПАЧКА = 15


def ua(o):
    for t in (o or {}).get('translations', []):
        if t.get('languageCode') in ('ua', 'uk'):
            return t.get('value') or t.get('title')
    return None


def options(набір, код):
    """{назва: код} — повний перелік дозволених значень атрибута."""
    h = {'Authorization': f"Bearer {os.getenv('EPICENTR_TOKEN')}",
         'Accept': 'application/json'}
    out, page = {}, 1
    while True:
        r = requests.get(f'{MAPI}/v2/pim/attribute-sets/{набір}/attributes/{код}/options',
                         headers=h, params={'limit': 80, 'page': page}, timeout=40)
        if r.status_code != 200:
            return out
        j = r.json()
        for o in j.get('items', []):
            назва = ua(o)
            if назва and not o.get('deleted'):
                out[назва] = o['code']
        if page >= (j.get('pages') or 1):
            break
        page += 1
        time.sleep(0.1)
    return out


def обрати(атрибут, дозволені, товари):
    """[(sku, назва значення або '—')] — одна відповідь на пачку товарів."""
    перелік = '\n'.join(f'- {n}' for n in sorted(дозволені))
    голова = (
        'Ти заповнюєш характеристики карток товарів для маркетплейсу.\n'
        'Обери значення характеристики для кожного товару СУВОРО з переліку.\n'
        'Якщо назва товару не дає прямої підстави — відповідай «—».\n'
        'Вигадане значення гірше за порожнє.\n'
        'Відповідь: рядки виду «артикул = значення», без пояснень.\n\n'
        f'Характеристика: {атрибут}\n'
        f'Дозволені значення:\n{перелік}\n\n'
        'Товари:\n')
    тіло = '\n'.join(f"{s} = {n}" for s, n in товари)
    txt, модель, usage = call_deepseek(голова + тіло, model=DEEPSEEK_FAST,
                                       thinking=False, max_tokens=1200)
    пари = []
    for рядок in (txt or '').splitlines():
        m = re.match(r'\s*([A-Za-zА-Яа-я0-9][\w./-]*)\s*=\s*(.+?)\s*$', рядок)
        if m:
            пари.append((m.group(1), m.group(2).strip()))
    return пари, usage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--набір', help='код набору атрибутів')
    ap.add_argument('--усі', action='store_true')
    ap.add_argument('--скільки', type=int, default=40)
    a = ap.parse_args()

    gaps = json.load(open(GAPS, encoding='utf-8'))
    назви = {str(p['id']): p.get('name') for p in json.load(open(PROD, encoding='utf-8'))}
    якщо = (lambda g: True) if a.усі else (lambda g: str(g['category']) == str(a.набір))
    цілі = [g for g in gaps if g['missing'] and якщо(g)][:a.скільки]
    print(f'карток у роботі: {len(цілі)}')

    # групуємо за (набір, атрибут): довідник значень тягнемо раз на групу
    групи = collections.defaultdict(list)
    for g in цілі:
        for m in g['missing']:
            групи[(str(g['category']), m['code'], m['name'])].append(
                (g['sku'], назви.get(str(g['id'])) or g['sku'], str(g['id'])))

    готове = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    витрати = collections.Counter()
    for (набір, код, імʼя), товари in sorted(групи.items(), key=lambda x: -len(x[1])):
        дозволені = options(набір, код)
        if not дозволені:
            print(f'{імʼя} ({код}) у наборі {набір}: переліку значень немає — пропускаю')
            continue
        обрано = 0
        for i in range(0, len(товари), ПАЧКА):
            пачка = [(s, n) for s, n, _ in товари[i:i + ПАЧКА]]
            try:
                пари, usage = обрати(імʼя, дозволені, пачка)
            except Exception as e:
                print(f'  DeepSeek: {e}', file=sys.stderr)
                continue
            витрати['вхід'] += (usage or {}).get('prompt_tokens', 0)
            витрати['вихід'] += (usage or {}).get('completion_tokens', 0)
            айді = {s: pid for s, _, pid in товари[i:i + ПАЧКА]}
            for sku, значення in пари:
                if значення in ('—', '-', '') or значення not in дозволені:
                    continue
                зап = готове.setdefault(sku, {'id': айді.get(sku), 'набір': набір,
                                              'значення': {}})
                зап['значення'][код] = {'назва_атрибута': імʼя,
                                        'значення': значення,
                                        'код_значення': дозволені[значення]}
                обрано += 1
            time.sleep(0.3)
        print(f'{імʼя} ({код}), набір {набір}: товарів {len(товари)}, обрано {обрано}')
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(готове, f, ensure_ascii=False, indent=1)
    print(f'\nтокени: вхід {витрати["вхід"]}, вихід {витрати["вихід"]} → {OUT}')


if __name__ == '__main__':
    main()
