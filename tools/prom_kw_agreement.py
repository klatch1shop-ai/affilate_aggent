#!/usr/bin/env python3
"""Неузгоджені пари «прикметник + тип» у ключах Prom (укр.).

Навіщо окремий інструмент. Перша, одноразова версія (12.09.2026) дала 506
«неузгоджених» пар, а ручна перевірка 30 випадкових показала лише 4 справжні
(13 %). Хибні — іменник першим словом («змазка джо», «мастурбатор-вагіна
кокос», «насадка страп он мі» — іменник + бренд кирилицею) і множина
іменника («віброкулі для клітора»). Правило 11.6 AGENT_RULES: детектор, який
не перевірено на прикладі «все гаразд», перебільшує. Тому контролі вбудовані
й ідуть перед кожним заміром; якщо хоч один не проходить — заміру немає.

    python3 tools/prom_kw_agreement.py                      # фід сервера
    python3 tools/prom_kw_agreement.py --feed /tmp/x.xml --sample 20
"""
import argparse
import collections
import os
import random
import re
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'tools'))
from prom_keywords import word_gender, _head_word, _GENDER_PREFIX  # noqa: E402
from prom_kw_matrix import _TAIL_STOP, selftest_name_type, NAME_TYPE_CASES  # noqa: E402

FEED = os.path.join(BASE, 'output', 'noire_prom.xml')
_CYR = re.compile(r"^[а-яіїєґ'’-]{3,}$")
# Прикметник визначаємо не закінченням (-а/-е/-і мають і іменники: «змазка»,
# «маска»), а словником чоловічих форм -ий/-ій, зібраним із самого фіду:
# «рожева» — прикметник, бо у фіді є «рожевий»; «змазка» — ні, «змазкий»
# немає. Перша версія брала закінчення й основу з DESC_NOUNS — і відкидала
# «вагінальний» (починається на «вагін»), а «змазку» вважала прикметником.
MASC = set()


def is_adj(w: str) -> bool:
    w = w.split('-')[-1]
    if re.search(r'(?:ий|ій)$', w):
        return True
    m = re.match(r"^([а-яіїєґ'’]{3,}?)(?:а|я|е|є|і|ї)$", w)
    return bool(m) and (m.group(1) + 'ий' in MASC or m.group(1) + 'ій' in MASC)


def load_masc(offers):
    for o in offers:
        for f in ('name_ua', 'keywords_ua', 'description_ua'):
            MASC.update(re.findall(r"[а-яіїєґ'’]{3,}(?:ий|ій)\b", (o.findtext(f) or '').lower()))

POSITIVE = [   # мусять бути позначені — справжні помилки з фіду
    'подвійна кільце', 'гіпоалергенний затискачі', 'гіпоалергенний кільце',
    'чорна вібратор для клітора', 'вагінальний віброяйця',
    'безшумний вагінальні кульки', 'рожева мастурбатор-вагіна',
    'зелений змазка водній', 'чорний анальна пробка',
    'густа анальна джо', 'розслаблювальна анальна pjur',
]
NEGATIVE = [   # мусять пройти — правильні фрази, на яких детектор уже помилявся
    'змазка джо', 'віброкулі для клітора', 'насадка страп он мі',
    'мастурбатор-вагіна кокос', 'маска серце', 'чорні віброкулі',
    'подвійне кільце', 'рожева віброкуля', 'гіпоалергенні затискачі',
    'рожевий мастурбатор-вагіна', 'силіконове ділдо', 'анальна пробка',
    'смарт-вібратор у трусики', 'вагінальні кульки', 'пінлива сіль',
    'силіконова смарт секс-машина', 'чорні бдсм наручники',
    'анальна міні секс-машина', 'золоте колесо вартенберга',
]


def adj_gender(a: str):
    a = a.split('-')[-1]
    if a.endswith(('ий', 'ій')):
        return 'm'
    if a.endswith(('і', 'ї')):
        return 'p'
    if a.endswith(('а', 'я')):
        return 'f'
    if a.endswith(('е', 'є')):
        return 'n'
    return None


def mismatch(phrase: str):
    """→ (прикметник, іменник) якщо неузгоджено, інакше None."""
    w = phrase.lower().split()
    if len(w) < 2:
        return None
    a = w[0]
    if not is_adj(a):
        return None
    # означень може бути кілька: «чорний анальна пробка», і приставки
    # («смарт секс-машина», «бдсм наручники») — іменник шукаємо так само, як
    # генератор (`_head_word`); інакше «силіконова смарт» — хибне (12.09).
    i = 1
    while i < len(w) and (is_adj(w[i]) or w[i] in _GENDER_PREFIX):
        i += 1
    if i >= len(w) or not _CYR.match(w[i]):
        # за означеннями одразу бренд або кінець — у фразі немає іменника
        return (a, '∅ немає іменника') if i < len(w) or len(w) > 1 else None
    n = _head_word(' '.join(w[i:]))
    if n in _TAIL_STOP or n in ('ділдо', 'дилдо'):
        return None
    ga, gn = adj_gender(a), word_gender(n)
    if ga and gn and ga != gn:
        return a, n
    return None


def selftest() -> bool:
    ok = True
    for p in POSITIVE:
        if not mismatch(p):
            print(f'  ✗ позитивний контроль не спрацював: «{p}»')
            ok = False
    for p in NEGATIVE:
        if mismatch(p):
            print(f'  ✗ негативний контроль позначено: «{p}» → {mismatch(p)}')
            ok = False
    # тип із назви — джерело іменника для самого детектора; зламане правило
    # типу зсунуло б і те, що детектор вважає «правильним»
    ok = selftest_name_type(verbose=False) and ok
    print(f'контролі: позитивних {len(POSITIVE)}, негативних {len(NEGATIVE)}, '
          f'типів із назви {len(NAME_TYPE_CASES)} — '
          + ('пройдено' if ok else 'НЕ ПРОЙДЕНО, заміру немає'))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--feed', default=FEED)
    ap.add_argument('--sample', type=int, default=20, help='випадкова вибірка для ручної перевірки')
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--skus-out', help='файл з артикулами вибірки (для sample_bias_check.py)')
    a = ap.parse_args()
    offers = list(ET.parse(a.feed).getroot().iter('offer'))
    load_masc(offers)
    if not selftest():
        sys.exit(1)
    hits, pairs = [], collections.Counter()
    for o in offers:
        for ph in (o.findtext('keywords_ua') or '').split(', '):
            m = mismatch(ph)
            if m:
                hits.append((o.findtext('vendorCode'), ph, (o.findtext('name_ua') or '')[:75]))
                pairs[' '.join(m)] += 1
    print(f'позначено фраз: {len(hits)} у {len({h[0] for h in hits})} картках')
    for p, c in pairs.most_common(15):
        print(f'  {c:4}  {p}')
    rnd = random.Random(a.seed)
    smp = rnd.sample(hits, min(a.sample, len(hits)))
    print(f'\nвипадкова вибірка {len(smp)} (не верх списку) — відкрити вручну:')
    for h in smp:
        print('  ' + ' | '.join(h))
    if a.skus_out:
        with open(a.skus_out, 'w') as f:
            f.write('\n'.join(dict.fromkeys(h[0] for h in smp)))


if __name__ == '__main__':
    main()
