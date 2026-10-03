#!/usr/bin/env python3
"""Аудит КОЖНОЇ картки Prom: що саме в ній зламано і чому її не знайдуть.

Перевірки побудовані на офіційних правилах Prom, а не на здогадах:

  * «Облік ключових слів у пошуку та тегах»: якщо слова запиту розкидані по
    ДВОХ І БІЛЬШЕ різних ключових фразах, товар у видачу НЕ потрапляє. Отже
    кожен ключ має бути ЦІЛИМ запитом, а не уламком.
  * «Ранжування на маркетплейсі»: враховується перше входження слів запиту
    в НАЗВУ. Назва важить більше за ключі.
  * keywords (рос.) і keywords_ua — ОКРЕМІ поля, по 9 слотів кожне.

Чому не вердикт моделі: усі перевірки тут відтворювані на тому самому фіді.
Семантику, яку числом не візьмеш, перевіряє окремий крок через Gemini.

ІСТОРІЯ ПОМИЛОК ЦЬОГО ІНСТРУМЕНТА (щоб не повторити):
  * підміна типу: перший варіант рахував синоніми за помилки («дилдо» проти
    «фалоімітатор» — те саме, люди шукають обома). Групи синонімів нижче.
  * підміна статі: перший варіант визначав стать за ФОРМОЮ товару, тож
    «фалоімітатор … Cock» з ключем «для женщин» вважався помилкою, хоча це
    правильний ключ. Стать визначає КОРИСТУВАЧ, не форма.
  * «чужий тип за категорією»: давав 895 спрацювань, з них майже всі хибні —
    ловив ознаки («на батарейках»), а не типи. Прибрано.

    venv/bin/python3 tools/prom_card_audit_v2.py --feed output/noire_prom.xml
"""
import argparse
import collections
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT = 9                       # слотів ключів на поле

TYPES = {
    'мастурбатор': 'мастурбатор', 'вагин': 'вагіна', 'вагін': 'вагіна',
    'вибратор': 'вібратор', 'вібратор': 'вібратор',
    'виброкольц': 'віброкільце', 'віброкільц': 'віброкільце',
    'фаллоимитатор': 'фалоімітатор', 'фалоімітатор': 'фалоімітатор',
    'дилдо': 'дилдо', 'ділдо': 'дилдо', 'пробка': 'пробка', 'пробк': 'пробка',
    'лубрикант': 'лубрикант', 'смазк': 'лубрикант', 'гель': 'гель',
    'свеч': 'свічка', 'свічк': 'свічка', 'наручник': 'наручники',
    'кляп': 'кляп', 'плет': 'плеть', 'флоггер': 'флоггер',
    'помпа': 'помпа', 'помп': 'помпа', 'страпон': 'страпон',
    'стимулятор': 'стимулятор', 'кольц': 'кільце', 'кільц': 'кільце',
    'насадк': 'насадка', 'презерватив': 'презерватив',
    'кульк': 'кульки', 'шарик': 'кульки', 'масло': 'масло',
    'білизн': 'білизна', 'белье': 'білизна',
}
# взаємозамінні назви того самого товару — НЕ помилка, ними реально шукають
SYNONYMS = [
    {'дилдо', 'фалоімітатор'}, {'мастурбатор', 'вагіна'},
    {'лубрикант', 'гель', 'масло'}, {'вібратор', 'віброкільце'},
    {'кільце', 'віброкільце'}, {'стимулятор', 'вібратор'},
]
# стать КОРИСТУВАЧА. Фалоімітатор — жіночий товар попри форму;
# мастурбатор — чоловічий (правило власника 03.10).
MALE = re.compile(
    r'мастурбатор|штучна вагіна|искусственная вагина|гумова вагіна|резиновая вагина|'
    r'для чоловіків|для мужчин|чоловічий|мужской|для пеніса|для пениса|для члена|'
    r'ерекційн|эрекционн|збільшення члена|увеличения члена|простат')
FEMALE = re.compile(
    r'для жінок|для женщин|жіночий|женский|клітор|клитор|'
    r'фалоімітатор|фаллоимитатор|дилдо|ділдо')
# службові слова: ключ, що ними закінчується, — уламок, а не запит
DANGLING = set('для та и в на с із з і по от до под над при о об у'.split())


def types_in(s):
    s = s.lower()
    return {v for root, v in TYPES.items() if root in s}


def allowed_types(found):
    out = set(found)
    for t in found:
        for g in SYNONYMS:
            if t in g:
                out |= g
    return out


def gender(s):
    s = s.lower()
    m, f = bool(MALE.search(s)), bool(FEMALE.search(s))
    if m and f:
        return None                      # неоднозначно — не судимо
    return 'ч' if m else ('ж' if f else None)


def keywords(offer, tag):
    return [k.strip() for k in (offer.findtext(tag) or '').split(',') if k.strip()]


def audit_offer(o, counts):
    """→ список проблем картки. Кожна — (код, деталь)."""
    problems = []
    name = (o.findtext('name') or '').strip()
    nlow = name.lower()
    ntypes = types_in(name)
    ok_types = allowed_types(ntypes)
    ngender = gender(name)

    if not name:
        problems.append(('назва порожня', ''))
    elif len(name) > 100:
        problems.append(('назва довша за 100 символів', f'{len(name)}'))

    for tag, label in (('keywords', 'рос'), ('keywords_ua', 'укр')):
        kws = keywords(o, tag)
        if not kws:
            problems.append((f'ключі {label}: порожньо', ''))
            continue
        if len(kws) < LIMIT:
            problems.append((f'ключі {label}: порожніх слотів', str(LIMIT - len(kws))))
        if len(kws) != len({k.lower() for k in kws}):
            problems.append((f'ключі {label}: повтор у межах картки', ''))
        for k in kws:
            kl = k.lower()
            parts = kl.split()
            if parts and parts[-1] in DANGLING or kl.endswith(('+', '-', '/', ',')):
                problems.append(('уламок, а не запит', k))
            if kl == nlow:
                problems.append(('ключ дослівно дублює назву', k))
            kt = types_in(k)
            if ntypes and kt and not (kt & ok_types):
                problems.append(('ключ називає інший тип товару',
                                 f'{k} → {",".join(sorted(kt))} замість {",".join(sorted(ntypes))}'))
            kg = gender(k)
            if ngender and kg and kg != ngender:
                problems.append(('ключ плутає стать', f'{k} ({kg}) при товарі ({ngender})'))
            counts[tag][kl] += 1
    return problems


def main(feed):
    offers = list(ET.parse(feed).getroot().iter('offer'))
    counts = {'keywords': collections.Counter(), 'keywords_ua': collections.Counter()}
    # перший прохід — зібрати частоти, щоб судити про унікальність
    for o in offers:
        for tag in counts:
            for k in keywords(o, tag):
                counts[tag][k.lower()] += 1
    counts = {'keywords': counts['keywords'], 'keywords_ua': counts['keywords_ua']}

    report, stat = {}, collections.Counter()
    fresh = {'keywords': collections.Counter(), 'keywords_ua': collections.Counter()}
    for o in offers:
        probs = audit_offer(o, fresh)
        # унікальність рахуємо за першим проходом
        for tag, label in (('keywords', 'рос'), ('keywords_ua', 'укр')):
            kws = keywords(o, tag)
            if kws and not any(counts[tag][k.lower()] == 1 for k in kws):
                probs.append((f'ключі {label}: жодного унікального', ''))
        if probs:
            report[o.get('id')] = {'name': (o.findtext('name') or '')[:90],
                                   'problems': probs}
        for code, _ in probs:
            stat[code] += 1

    print(f'офферів: {len(offers)} · із проблемами: {len(report)} '
          f'({len(report)/len(offers)*100:.1f}%)')
    print(f'\n{"проблема":<44}{"разів":>8}')
    for code, n in stat.most_common():
        print(f'{code:<44}{n:>8}')
    out = os.path.join(BASE, 'exports', 'prom_card_audit.json')
    json.dump(report, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n→', out)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--feed', default='/tmp/prom_now.xml')
    main(ap.parse_args().feed)
