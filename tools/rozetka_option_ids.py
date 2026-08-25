#!/usr/bin/env python3
"""Компактний довідник значень характеристик Rozetka з `paramid`/`valueid`.

Навіщо окремий файл. Повний кеш `data/rozetka_category_options.json` — 91 МБ
(132 категорії × ~1600 рядків), і тягти його в генератор фіду немає сенсу:
з нього потрібні дві-три характеристики. Тут із кеша витягується лише
whitelist назв і зберігається у `data/rozetka_filter_values.json` (кілька КБ),
який уже читає `toptul_filter_extract.py`.

Навіщо взагалі `paramid`/`valueid`. p210 (ред. 12.06.2026): «Ми гарантуємо
зіставлення вказаних вами характеристик, які ТОЧНО збігаються з параметрами в
категорії», а для решти — «постараємося зіставити». З атрибутами
`paramid`/`valueid` здогадки немає взагалі:

    <param name="Розмір посадкового квадрата" paramid="243848"
           valueid="3868053">1/2</param>

Це важливо саме тут, бо значення в довіднику записані БЕЗ одиниці: `1/2`, а
не `1/2"` — одиниця лежить окремим полем `unit` (`"` у «Торцевих головках»,
`дюйм` у трьох інших категоріях). Вгадувати, у якому вигляді майданчик чекає
рядок, не доводиться: беремо `value_name` дослівно й підпираємо `valueid`.

    python3 tools/rozetka_option_ids.py
    python3 tools/rozetka_option_ids.py --name "Матеріал головки"
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, 'data', 'rozetka_category_options.json')
OUT = os.path.join(BASE, 'data', 'rozetka_filter_values.json')

# Характеристики, заради яких файл існує. Зауваження Rozetka #7253098 п.3:
# обидві є фільтрами й обидві в нас порожні.
DEFAULT_NAMES = ('Розмір посадкового квадрата', 'Кількість граней')


def build(cache: dict, names) -> dict:
    """{rz_id: {назва: {paramid, unit, values: {value_name: value_id}}}}"""
    want = set(names)
    out = {}
    for rz_id, items in cache.items():
        if isinstance(items, dict):
            items = items.get('options') or items.get('items') or []
        for x in items:
            if not isinstance(x, dict):
                continue
            nm = str(x.get('name') or '').strip()
            if nm not in want:
                continue
            vn = x.get('value_name')
            if vn is None:
                continue
            slot = out.setdefault(rz_id, {}).setdefault(
                nm, {'paramid': x.get('id'), 'unit': x.get('unit'),
                     'attr_type': x.get('attr_type'), 'values': {}})
            slot['values'][str(vn).strip()] = x.get('value_id')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', action='append', default=None,
                    help='назва характеристики; можна повторювати')
    ap.add_argument('-o', '--output', default=OUT)
    a = ap.parse_args()
    names = a.name or list(DEFAULT_NAMES)

    if not os.path.exists(CACHE):
        sys.exit(f'Немає кеша довідників: {CACHE}\n'
                 f'Зібрати: python3 tools/rozetka_category_options.py '
                 f'--feed output/toptul_rozetka.xml  (токен лише на сервері)')
    cache = json.load(open(CACHE, encoding='utf-8'))
    ref = build(cache, names)

    # Позитивний контроль на боці ЗАПИСУ: порожній довідник записується
    # мовчки й потім дає «0 доданих характеристик», яке читається як «нема
    # чого додавати». Тому кожна замовлена назва мусить знайтись хоча б в
    # одній категорії, інакше — падаємо з переліком, а не пишемо огризок.
    missing = [n for n in names
               if not any(n in v for v in ref.values())]
    if missing:
        sys.exit('У кеші немає жодної категорії з характеристикою: '
                 + ', '.join(repr(m) for m in missing)
                 + f'\nКатегорій у кеші: {len(cache)}')

    json.dump(ref, open(a.output, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, sort_keys=True)
    print(f'категорій у кеші: {len(cache)} → з потрібними назвами: {len(ref)}')
    for rz_id in sorted(ref):
        for nm, slot in sorted(ref[rz_id].items()):
            print(f'  {rz_id}  {nm:30} paramid={slot["paramid"]} '
                  f'unit={slot["unit"]!r} значень={len(slot["values"])}: '
                  f'{sorted(slot["values"])}')
    print(f'→ {a.output} ({os.path.getsize(a.output)} Б)')


if __name__ == '__main__':
    main()
