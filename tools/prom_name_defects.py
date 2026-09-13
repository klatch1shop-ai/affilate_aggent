#!/usr/bin/env python3
"""Дефекти УКРАЇНСЬКИХ назв постачальника — список, а не поштучні правки.

Навіщо список (порада чату 13.09.2026): поштучна правка без правила не
відтворюється і не показує, чи є за поодинокими випадками спільна причина.
Список, зібраний інструментом, показує: якщо назбирується клас (наприклад,
«українська назва написана російською»), це вже сигнал про етап конвеєра
постачальника, і виправлення має бути правилом, а не ручною заміною.

Класи:
  ru      — у назві є слова, які словник (`uk_lexicon`) визначає російськими:
            «размер», «цвет», «Массажер простаты», «Мыло в форме…»;
  typo    — рідкісне слово поза словником, що на одну правку (вставка,
            пропуск, заміна, перестановка) відрізняється від словникової
            форми або частого слова каталогу: «Подадрунковий» → «подарунковий»;
  mixed   — латиниця всередині кириличного слова, яку не зняв `dehomo()`;
  cut     — назва рівно 100 символів і обривається посеред слова («вібропуля
            в подарун») — обрізання в базі постачальника.

Контролі йдуть перед заміром (правило 11.5/11.6): відомі дефекти мусять
знайтися, часті слова каталогу («мастурбатор», «віброкуля») — ні.

    python3 tools/prom_name_defects.py --feed output/noire_prom.xml
    python3 tools/prom_name_defects.py --out docs/prom_name_defects.tsv
"""
import argparse
import collections
import os
import re
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'tools'))
import uk_lexicon as LEX  # noqa: E402
from homoglyph import is_mixed, TOKEN  # noqa: E402

FEED = os.path.join(BASE, 'output', 'noire_prom.xml')
ALPHA = 'абвгґдеєжзиіїйклмнопрстуфхцчшщьюяʼ'
# Назви творів у лапках не мова назви: «Эродит» (RU) — назва видання гри.
QUOTED = re.compile(r'«[^»]*»|"[^"]*"|“[^”]*”')

# Контролі — самі рядки назв постачальника, а не артикули: після виправлення
# у фіді дефекту вже немає, і контроль «за артикулом» ламався від успіху.
POSITIVE = [
    ('Подадрунковий набір Lovehoney Discover Romance, силікон, алюміній', 'typo'),
    ('Мыло в форме пениса Чистый Кайф Violet size L, крафтове мило-член', 'ru'),
    ('Нашийник с флогером Rosy Gold - Collar with Flogger - Black', 'ru'),
    ('Кольоровий фалоімітатор ADDICTION - LEONARDO - 7 "- 3 COLOURS, 17,8 см, силікон, вібропуля в подарун', 'cut'),
]
NEGATIVE_WORDS = ['мастурбатор', 'лубрикант', 'віброкуля', 'страпон',
                  'вібромасажер', 'мастурбатор-вагіна', 'пульсатор']


def edits1(w):
    splits = [(w[:i], w[i:]) for i in range(len(w) + 1)]
    out = set()
    for a, b in splits:
        if b:
            out.add(a + b[1:])                                  # пропуск
            for c in ALPHA:
                out.add(a + c + b[1:])                          # заміна
        if len(b) > 1:
            out.add(a + b[1] + b[0] + b[2:])                    # перестановка
        for c in ALPHA:
            out.add(a + c + b)                                  # вставка
    out.discard(w)
    return out


def build_vocab(offers):
    freq = collections.Counter()
    for o in offers:
        for f in ('name_ua', 'description_ua'):
            freq.update(LEX.tokens(re.sub(r'<[^>]+>', ' ', o.findtext(f) or '')))
    return freq


def classify_name(name, freq, uk):
    """→ [(клас, слово, підказка)]"""
    out = []
    text = QUOTED.sub(' ', name)
    for w in LEX.ru_words(text):
        out.append(('ru', w, ''))
    # однолітерні рос. прийменник і сполучник — словник слова <3 літер не
    # класифікує («Нашийник с флогером», «з ротацією и анальним»)
    for w in re.findall(r"(?<![\wʼ’'-])[си](?![\wʼ’'-])", text):
        out.append(('ru', w, ''))
    # постачальник обрізає назву на 100-му символі посеред слова
    if len(name) == 100:
        last = LEX.norm((re.findall(r"[\w’'ʼ-]+$", name) or [''])[0])
        if last and not re.search(r'[a-z0-9]', last) and last not in uk and freq[last] < 5:
            comp = [w for w in freq if w.startswith(last) and w != last and freq[w] >= 3]
            out.append(('cut', last, max(comp, key=lambda w: freq[w]) if comp else ''))
    for tok in TOKEN.findall(name):
        if is_mixed(tok):
            out.append(('mixed', tok, ''))
    for w in LEX.unknown_words(text):
        # рідкісність відносна: одруківка повторюється в описі тієї самої
        # картки («Подадрунковий» — 4 вживання), тож поріг «≤2» її пропускав
        if len(w) < 6 or not re.fullmatch(r"[а-яіїєґʼ-]+", w) or freq[w] > 8:
            continue
        near = [c for c in edits1(w)
                if (c in uk and freq[c] >= freq[w]) or freq[c] >= max(10, 5 * freq[w])]
        if near:
            best = max(near, key=lambda c: (freq[c], c in uk))
            out.append(('typo', w, best))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--feed', default=FEED)
    ap.add_argument('--out', help='TSV зі списком (артикул, клас, слово, підказка, назва)')
    a = ap.parse_args()
    offers = list(ET.parse(a.feed).getroot().iter('offer'))
    LEX._load()
    uk = LEX._uk
    freq = build_vocab(offers)

    ok = True
    for name, cls in POSITIVE:
        got = {c for c, _, _ in classify_name(name, freq, uk)}
        if cls not in got:
            print(f'  ✗ позитивний контроль: «{name[:40]}…» мав дати «{cls}», дав {got or "нічого"}')
            ok = False
    for w in NEGATIVE_WORDS:
        if classify_name(w, freq, uk):
            print(f'  ✗ негативний контроль позначено: «{w}»')
            ok = False
    print('контролі: ' + ('пройдено' if ok else 'НЕ ПРОЙДЕНО, списку немає'))
    if not ok:
        sys.exit(1)

    rows = []
    for o in offers:
        name = o.findtext('name_ua') or ''
        for cls, w, hint in classify_name(name, freq, uk):
            rows.append((o.findtext('vendorCode') or o.get('id'), cls, w, hint, name))
    cnt = collections.Counter(r[1] for r in rows)
    words = collections.Counter((r[1], r[2]) for r in rows)
    print(f'назв з дефектами: {len({r[0] for r in rows})} · ' +
          ', '.join(f'{k} {v}' for k, v in cnt.most_common()))
    for (cls, w), n in words.most_common(40):
        hint = next((r[3] for r in rows if r[1] == cls and r[2] == w), '')
        print(f'  {n:3}  {cls:5} {w}' + (f' → {hint}' if hint else ''))
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write('артикул\tклас\tслово\tпідказка\tназва\tрішення\n')
            for r in rows:
                f.write('\t'.join(r) + '\t\n')
        print(f'записано: {a.out}')


if __name__ == '__main__':
    main()
