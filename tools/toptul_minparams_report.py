#!/usr/bin/env python3
"""Розбір товарів TOPTUL, відсіяних за `MIN_PARAMS` («менше 3 характеристик»).

Вхід — TSV, який пише САМ генератор (`toptul_rozetka_generator.py --drops`), і
довідник фільтрів Rozetka (`data/rozetka_filter_values.json`). Другого набору
правил тут немає свідомо: перелік відсіяних і причина відсіву беруться з
генератора, а цей інструмент лише пояснює, ЧОГО кожному бракує до трьох.

Питання, на яке відповідає звіт, — «що саме нам потрібно, щоб ці товари
повернулись у фід», у трьох рівнях:

  A. категорії немає в довіднику фільтрів Rozetka — фільтри допомогти не
     можуть за побудовою, потрібні характеристики від постачальника;
  B. категорія в довіднику є, потрібної характеристики бракує, і в
     `toptul_filter_extract.RULES` для неї НЕМАЄ правила — тобто впирається в
     нашу роботу, а не в дані;
  C. правило є, джерело перевірено, значення немає — впирається в дані.

Проба «значення довідника стоїть у назві» рахується лише для текстових
характеристик («Вид», «Тип», «Особливості», «Кількість граней», «Розмір
посадкового квадрата»). «Робочий розмір» з назви НЕ пробується: рішення
01.09.2026 — джерелом для нього є лише числові характеристики постачальника,
бо число в назві буває довжиною, а не робочим розміром (див. докстрінг
`toptul_filter_extract.py`).

    python3 tools/toptul_minparams_report.py --drops /tmp/drops.tsv \
        --out docs/toptul_minparams_drops.md --before 1179
    python3 tools/toptul_minparams_report.py --selftest
"""
import argparse
import collections
import csv
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))

from toptul_filter_extract import (  # noqa: E402
    FACES, FEATURES, KIND, RULES, SQUARE, VIEW, WORKSIZE, load_reference)

# Характеристики, значення яких МОЖНА шукати в назві. «Робочий розмір» сюди не
# входить — див. докстрінг.
TEXT_ATTRS = (VIEW, KIND, FEATURES, FACES, SQUARE)
# Характеристики, які беруться з правил на категорію. Для решти правило
# спільне для всіх категорій, тому «правила немає» до них не застосовне.
RULED_ATTRS = (VIEW, KIND)
# Характеристики постачальника, з яких береться «Робочий розмір»
# (`toptul_filter_extract.SIZE_PARAMS`), — але тут потрібні лише НАЗВИ, бо
# значень у TSV відсіяних немає.
SIZE_PARAM_NAMES = ('Розмір min', 'Розмір max', 'Розмір')

# Значення коротші за це в назві не шукаються: `1`, `2`, `Ключ` проти `Ключі`
# — надто дешеві збіги, а ціна хибного «можна заповнити» тут та сама, що й у
# вигаданого значення (правило 5 черги).
MIN_VALUE_LEN = 4


def _word_re(value: str) -> re.Pattern:
    """Точне слово, а не входження: `Ключ` не мусить ловитись у `Ключів`.

    Межа задана явним переліком літер, бо `\\b` у Python рахує кириличні
    літери словесними, але `і`, `ї`, `є`, `ґ` в інших локалях поводяться
    інакше — на цьому вже спіткнувся пошук мішаного написання 01.09.
    """
    letter = r'[0-9A-Za-zА-Яа-яІіЇїЄєҐґ]'
    return re.compile(rf'(?<!{letter}){re.escape(value)}(?!{letter})', re.I)


def values_in_name(name: str, slot: dict) -> list:
    """Значення довідника, які стоять у назві дослівно."""
    return [v for v in slot['values']
            if len(v) >= MIN_VALUE_LEN and _word_re(v).search(name or '')]


def classify(row: dict, ref: dict) -> dict:
    """Чого бракує одному відсіяному товару. Без здогадів про значення."""
    rz = row['rz_id']
    have = {p.strip() for p in (row['характеристики'] or '').split('|')}
    name = row['назва']
    cat = ref.get(rz) or {}
    missing = [a for a in cat if a not in have]

    ruled, unruled, in_name = [], [], {}
    for attr in missing:
        if attr in RULED_ATTRS:
            (ruled if RULES.get((rz, attr)) else unruled).append(attr)
        elif attr == WORKSIZE:
            # Джерело — структурні характеристики; якщо їх немає, правило
            # відпрацювало чесно й порожньо.
            (ruled if any(p in have for p in SIZE_PARAM_NAMES)
             else unruled).append(attr)
        else:
            ruled.append(attr)
        if attr in TEXT_ATTRS:
            hits = values_in_name(name, cat[attr])
            if hits:
                in_name[attr] = hits

    if not cat:
        group = 'A: категорії немає в довіднику фільтрів'
    elif in_name:
        group = 'B: значення довідника стоїть у назві, правила немає'
    elif unruled:
        group = 'B: характеристика довідника без правила для категорії'
    else:
        group = 'C: правило є, значення в даних немає'
    return {'group': group, 'missing': missing, 'unruled': unruled,
            'in_name': in_name, 'need': max(0, 3 - int(row['характеристик після фільтрів']))}


def read_drops(path: str) -> list:
    with open(path, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f, delimiter='\t')
                if r.get('причина') == 'менше 3 характеристик']
    if not rows:
        sys.exit(f'{path}: жодного рядка з причиною «менше 3 характеристик» — '
                 f'перевір, чи це файл із --drops')
    return rows


def build(rows: list, ref: dict, before: int) -> str:
    per_cat = collections.defaultdict(lambda: collections.Counter())
    groups = collections.Counter()
    reasons = collections.Counter()
    attr_upside = collections.Counter()
    examples = collections.defaultdict(list)
    cat_name = {}

    for r in rows:
        c = classify(r, ref)
        groups[c['group']] += 1
        n_sup, n_after = (int(r['характеристик постачальника']),
                          int(r['характеристик після фільтрів']))
        if n_after > n_sup:
            reasons['фільтр додано, але характеристик усе одно менше 3'] += 1
        elif n_sup <= 1:
            reasons['постачальник не дав жодної характеристики (лише «Бренд»)'] += 1
        else:
            reasons['постачальник дав одну характеристику (+ «Бренд»)'] += 1

        rz = r['rz_id']
        cat_name[rz] = r['категорія']
        per_cat[rz]['товарів'] += 1
        per_cat[rz]['у довіднику'] = int(bool(ref.get(rz)))
        for attr, hits in c['in_name'].items():
            per_cat[rz][f'назва дає {attr}'] += 1
            attr_upside[attr] += 1
            if len(examples[(rz, attr)]) < 3:
                examples[(rz, attr)].append((r['назва'], hits))

    # Скільки карток дійшли б до трьох, якби знайдені в назві значення
    # проставились. Рахується по товару, а не по характеристиці: дві знайдені
    # характеристики закривають картку, у якої бракує двох.
    #
    # Два числа, а не одне. `closable` — стеля по всіх текстових
    # характеристиках; `ruled` — лише «Вид» і «Тип», тобто те, що досяжне
    # додаванням запису в `RULES` і НІЧОГО більше. Друге число перевірено
    # прогоном самого генератора з тимчасово підставленими правилами
    # (02.09.2026: 916 → 829 відсіяних, 5783 → 5870 офферів), і саме тому
    # воно тут окремо: прогноз, який ніхто не звірив із генератором, — це
    # здогад про власну пробу, а не про фід.
    closable = ruled_closable = 0
    candidates = []
    for r in rows:
        c = classify(r, ref)
        if c['in_name'] and len(c['in_name']) >= c['need']:
            closable += 1
        vk = {a: v for a, v in c['in_name'].items() if a in RULED_ATTRS}
        if vk and len(vk) >= c['need']:
            ruled_closable += 1
            candidates.append((r['sku'], r['rz_id'], r['категорія'],
                               '; '.join(f'{a} = {"/".join(v)}'
                                         for a, v in sorted(vk.items())),
                               r['назва']))

    out = [
        '# TOPTUL → Rozetka: товари, які не потрапляють у фід через '
        '«менше 3 характеристик»',
        '',
        f'Замір {ARGS.date}, фід `output/toptul_rozetka.xml`. Було **{before}** '
        f'відсіяних, лишилось **{len(rows)}**.',
        '',
        'Значення НЕ вигадувались (правило 5 черги). Повний перелік із SKU — '
        '`docs/toptul_minparams_drops.tsv`.',
        '',
        '## Причини браку характеристик',
        '',
        '| причина | товарів |',
        '|---|---:|',
    ]
    for k, v in reasons.most_common():
        out.append(f'| {k} | {v} |')

    out += ['', '## Чого бракує до трьох — за рівнями', '',
            '| рівень | товарів |', '|---|---:|']
    for k, v in groups.most_common():
        out.append(f'| {k} | {v} |')
    out += ['',
            f'**Карток, які закрилися б самими лише значеннями з назви: '
            f'{closable}**; з них **{ruled_closable}** — самим лише записом у '
            '`toptul_filter_extract.RULES` («Вид» і «Тип»), без нового коду.',
            '',
            f'Друге число не прогноз проби, а замір генератора: з тимчасово '
            f'підставленими правилами він дав **916 → 829** відсіяних і '
            f'**5783 → 5870** офферів, тобто рівно ці {ruled_closable}. '
            'Перелік — `docs/toptul_minparams_candidates.tsv`.',
            '',
            '**Але мовчки такого правила не додають.** Серед збігів є хибні '
            'за суттю: `Утримувач рулону паперу для інструментальної візки` '
            '→ «Тип: Візки» — тримач ДЛЯ візка, а не візок. Це та сама пастка, '
            'через яку 25.08 виникли хибні пари «Кількість граней» ← '
            '«Кількість предметів», тому правило потрібне на кожну категорію '
            'окремо й з переглядом очима, як зроблено для п’яти наявних.',
            '']

    if attr_upside:
        out += ['## Характеристики, значення яких уже стоять у назві', '',
                '| характеристика | товарів |', '|---|---:|']
        for k, v in attr_upside.most_common():
            out.append(f'| {k} | {v} |')
        out.append('')

    out += ['## Розподіл за категоріями', '',
            '| rz_id | категорія | товарів | у довіднику | назва дає значення |',
            '|---|---|---:|---|---:|']
    for rz, c in sorted(per_cat.items(), key=lambda x: -x[1]['товарів']):
        gives = sum(v for k, v in c.items() if k.startswith('назва дає'))
        out.append(f'| {rz} | {cat_name[rz]} | {c["товарів"]} | '
                   f'{"так" if c["у довіднику"] else "ні"} | {gives} |')

    if examples:
        out += ['', '## Приклади збігів «значення довідника в назві»', '']
        seen = 0
        for (rz, attr), ex in sorted(
                examples.items(),
                key=lambda x: -per_cat[x[0][0]]['товарів']):
            out.append(f'**[{rz}] {cat_name[rz]} · {attr}**')
            for name, hits in ex:
                out.append(f'* `{name}` → {", ".join(hits)}')
            out.append('')
            seen += 1
            if seen >= 8:
                break
    return '\n'.join(out) + '\n', candidates


# ── позитивний контроль: проба мусить уміти і знаходити, і НЕ знаходити ─────
_REF_T = {
    '4668955': {KIND: {'paramid': 1, 'attr_type': 'ComboBox',
                       'values': {'Знімач': 1, 'Ключ': 2, 'Набір': 3}},
                WORKSIZE: {'paramid': 2, 'attr_type': 'ListValues',
                           'values': {'75': 4, '100': 5}}},
    '154981': {VIEW: {'paramid': 3, 'attr_type': 'ComboBox',
                      'values': {'Електричні': 6, 'Пневматичні': 7}}},
}
_CASES = [
    # (назва, слот, очікувані збіги, чому)
    ('Знімач підшипників тризахопний 75 мм Без бренда (SP303ST)',
     _REF_T['4668955'][KIND], ['Знімач'], 'значення стоїть у назві дослівно'),
    ('Знімачі підшипників набір Toptul', _REF_T['4668955'][KIND], ['Набір'],
     '`Знімачі` — інше слово, ніж `Знімач`: збіг лише за точним словом'),
    ('Ключі свічкові 16 мм', _REF_T['4668955'][KIND], [],
     '`Ключі` не мусить ловитись як `Ключ` — інакше стеля була б вигаданою'),
    ('Пристрій для заміни гальмівної рідини 1000мл', _REF_T['4668955'][KIND],
     [], 'жодного значення довідника в назві — правильна відповідь порожня'),
    ('Знімач 75 мм', _REF_T['4668955'][WORKSIZE], [],
     'числові значення коротші за поріг і в назві не шукаються'),
    ('Фарбопульт електричний 650 Вт', _REF_T['154981'][VIEW], [],
     'у назві прикметник `електричний`, а в довіднику `Електричні` — '
     'проба навмисно не здогадується про форму слова'),
    ('Фарбопульти пневматичні HVLP', _REF_T['154981'][VIEW], ['Пневматичні'],
     'а тут форма збігається дослівно'),
]


def selftest() -> int:
    bad = 0
    for name, slot, exp, why in _CASES:
        got = values_in_name(name, slot)
        ok = got == exp
        bad += not ok
        print(f'{"OK  " if ok else "ЗБІЙ"} {name[:52]:54} {got}'
              + ('' if ok else f'  ОЧІКУВАНО {exp}'))
        if not ok:
            print(f'       ← {why}')
    empties = sum(1 for c in _CASES if not c[2])
    print(f'\nвипадків: {len(_CASES)} (з порожнім очікуванням: {empties}), '
          f'збоїв: {bad}')
    return 1 if bad or empties < 3 else 0


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument('--drops')
    ap.add_argument('--out')
    ap.add_argument('--before', type=int, default=0)
    ap.add_argument('--candidates', metavar='TSV',
                    help='перелік карток, які закриваються записом у RULES')
    ap.add_argument('--date', default='')
    ap.add_argument('--selftest', action='store_true')
    ARGS = ap.parse_args()
    if ARGS.selftest:
        sys.exit(selftest())
    if not ARGS.drops:
        ap.error('потрібен --drops або --selftest')
    text, candidates = build(read_drops(ARGS.drops), load_reference(),
                             ARGS.before)
    if ARGS.out:
        open(ARGS.out, 'w', encoding='utf-8').write(text)
        print(f'записано: {ARGS.out}')
    else:
        print(text)
    if ARGS.candidates:
        with open(ARGS.candidates, 'w', encoding='utf-8') as f:
            w = csv.writer(f, delimiter='\t', lineterminator='\n')
            w.writerow(['sku', 'rz_id', 'категорія',
                        'що дає назва', 'назва'])
            w.writerows(candidates)
        print(f'записано: {ARGS.candidates} ({len(candidates)} рядків)')


if __name__ == '__main__':
    main()
