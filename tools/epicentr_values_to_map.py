#!/usr/bin/env python3
"""Результат класифікації → формат, який приймає epicentr_attr_fill_multi.

Класифікатор пише {sku: {код: {назва_атрибута, значення, код_значення}}},
а записувач чекає {sku: {«Назва характеристики»: «значення»}} і працює з
ОДНИМ набором за прогін. Тут розкладаємо по наборах.

    venv/bin/python tools/epicentr_values_to_map.py
    → exports/epicentr_map_<набір>.json на кожен набір
"""
import collections
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN = os.path.join(BASE, 'exports', 'epicentr_deepseek_values.json')
OUTDIR = os.path.join(BASE, 'exports')


def main():
    d = json.load(open(IN, encoding='utf-8'))
    по_наборах = collections.defaultdict(dict)
    for sku, зап in d.items():
        м = {v['назва_атрибута']: v['значення'] for v in зап['значення'].values()}
        if м:
            по_наборах[зап['набір']][sku] = м
    for набір, карти in sorted(по_наборах.items(), key=lambda x: -len(x[1])):
        шлях = os.path.join(OUTDIR, f'epicentr_map_{набір}.json')
        with open(шлях, 'w', encoding='utf-8') as f:
            json.dump(карти, f, ensure_ascii=False, indent=1)
        значень = sum(len(v) for v in карти.values())
        print(f'набір {набір}: карток {len(карти)}, значень {значень} → {шлях}')


if __name__ == '__main__':
    main()
