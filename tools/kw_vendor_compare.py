#!/usr/bin/env python3
"""Порівняння вендорів на ОДНАКОВИХ картках: чи є різниця по суті.

Навіщо (власник, 03.10.2026): «будем порівнювати чи є різниця». Косметику
вже пройшов Gemini; ті самі картки проганяємо Codex і дивимось не на
красу, а на вимірюване:

  * скільки ключів пройшло детерміновану перевірку;
  * скільки з них ЗБІГЛИСЬ у двох вендорів — збіг означає, що фраза не
    вигадка одного, а висновок із даних картки;
  * чи знайшов вендор на ФОТО те, чого немає в тексті (головна цінність);
  * скільки видалень підтвердив вимір.

Порівнюємо на тих самих картках, інакше різниця буде різницею вибірок.

    venv/bin/python3 tools/kw_vendor_compare.py --limit 20
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

A = os.path.join(BASE, 'exports', 'prom_kw_expert_Лубриканты.json')
B = os.path.join(BASE, 'exports', 'prom_kw_expert_codex.json')


def norm(s):
    import re
    return re.sub(r'\s+', ' ', (s or '').strip().lower())


def main(limit):
    a = json.load(open(A, encoding='utf-8'))['cards']
    if not os.path.exists(B):
        print(f'немає {B} — спершу прогнати Codex по тих самих картках')
        return
    b = json.load(open(B, encoding='utf-8'))['cards']
    common = [p for p in a if p in b][:limit] if limit else [p for p in a if p in b]
    print(f'спільних карток: {len(common)}')
    if not common:
        return

    stat = {'gemini': 0, 'codex': 0, 'обидва': 0, 'фото_gemini': 0, 'фото_codex': 0}
    examples = []
    for pid in common:
        ka = {norm(x['k']) for t in ('keywords', 'keywords_ua') for x in a[pid]['add'][t]}
        kb = {norm(x['k']) for t in ('keywords', 'keywords_ua') for x in b[pid]['add'][t]}
        stat['gemini'] += len(ka)
        stat['codex'] += len(kb)
        stat['обидва'] += len(ka & kb)
        stat['фото_gemini'] += bool(a[pid].get('from_photo'))
        stat['фото_codex'] += bool(b[pid].get('from_photo'))
        if len(examples) < 3 and (ka - kb) and (kb - ka):
            examples.append((a[pid]['name'][:60], sorted(ka - kb)[:3], sorted(kb - ka)[:3]))

    n = len(common)
    print(f'\n{"":<12}{"ключів":>9}{"на картку":>11}{"фото дало нове":>17}')
    for v, key in (('gemini', 'gemini'), ('codex', 'codex')):
        print(f'{v:<12}{stat[key]:>9}{stat[key]/n:>11.1f}'
              f'{stat["фото_"+key]:>13}/{n}')
    both = stat['обидва']
    print(f'\nЗБІГЛИСЬ дослівно: {both} '
          f'({both/max(min(stat["gemini"], stat["codex"]), 1)*100:.0f}% від меншого)')
    print('\nде розійшлись:')
    for name, only_a, only_b in examples:
        print(f'  {name}')
        print(f'    лише gemini: {only_a}')
        print(f'    лише codex:  {only_b}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    main(ap.parse_args().limit)
