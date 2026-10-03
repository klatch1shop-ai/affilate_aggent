#!/usr/bin/env python3
"""Побудова ключових слів Prom: кожен ключ — ЦІЛИЙ пошуковий запит.

Правила взяті з офіційної довідки Prom, не з інтуїції:

  * «Облік ключових слів у пошуку та тегах»: якщо слова запиту розкидані по
    ДВОХ І БІЛЬШЕ ключових фразах, товар у видачу НЕ потрапляє. Звідси
    головне правило цього генератора: ключ — самодостатня фраза, якою
    людина реально шукає, а не набір ознак.
  * «Ранжування»: враховується перше входження слів запиту в НАЗВУ, тож
    ключі не дублюють назву дослівно — вони додають інші формулювання.
  * keywords (рос.) і keywords_ua — ОКРЕМІ поля по 9 слотів.

Зворотний звʼязок менеджера Prom (власник переказав): ключі мають бути
такими, «як я б шукав свій товар». Ознака товару стає ключем лише тоді,
коли вона сама є приводом для пошуку.

Доповнюємо, а не заміняємо: перевірено на лубрикантах — merge дав
259 → 480 унікальних ключів без жодної погіршеної картки, а заміна за
правилами вбивала довгий хвіст. Наявні ключі тут ніколи не видаляються,
окрім доведених помилок із prom_card_audit_v2.

    venv/bin/python3 tools/prom_kw_build.py --feed /tmp/prom_now.xml --sample 20
"""
import argparse
import collections
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
LIMIT = 9
LATIN = re.compile(r'[A-Za-z]')

# Призначення → природні запити, ОКРЕМО для кожної мови: поля keywords і
# keywords_ua різні, і змішувати мови в одному полі не можна (03.10 перша
# версія клала «мастурбатор для чоловіків» у російське поле).
USE_CASES = {
    'ru': {
        'мастурбатор': ['мастурбатор для мужчин', 'искусственная вагина'],
        'вибратор': ['вибратор для женщин'],
        'фаллоимитатор': ['фаллоимитатор на присоске'],
        'дилдо': ['реалистичное дилдо'],
        'пробка': ['анальная пробка'],
        'лубрикант': ['интимная смазка'],
        'свеч': ['массажная свеча'],
        'наручники': ['наручники для ролевых игр'],
        'помпа': ['вакуумная помпа'],
        'страпон': ['страпон с креплением'],
    },
    'ua': {
        'мастурбатор': ['мастурбатор для чоловіків', 'штучна вагіна'],
        'вібратор': ['вібратор для жінок'],
        'фалоімітатор': ['фалоімітатор на присосці'],
        'дилдо': ['реалістичне дилдо'],
        'пробка': ['анальна пробка'],
        'лубрикант': ['інтимне мастило'],
        'свічк': ['масажна свічка'],
        'наручники': ['наручники для рольових ігор'],
        'помпа': ['вакуумна помпа'],
        'страпон': ['страпон з кріпленням'],
        'кульк': ['вагінальні кульки'],
    },
}
# Поле фіду → мова. name/keywords — російські, name_ua/keywords_ua — українські.
FIELD = {'keywords': ('name', 'ru'), 'keywords_ua': ('name_ua', 'ua')}

# ХАРАКТЕРИСТИКИ, ЯКІ СТАЮТЬ ЗАПИТАМИ.
# Правило від менеджера Prom (переказав власник): ознака стає ключем лише
# тоді, коли вона сама є приводом для пошуку. «Матеріал: силікон» — так,
# люди шукають «силіконовий вібратор». «Довжина: 580» — ні, за міліметрами
# не шукають. Тому перелік явний, а не «усі param підряд».
#
# Значення → прикметник, окремо для кожної мови.
ATTR_WORDS = {
    'Матеріал': {
        'силікон':      {'ru': 'силиконовый',      'ua': 'силіконовий'},
        'скло':         {'ru': 'стеклянный',       'ua': 'скляний'},
        'метал':        {'ru': 'металлический',    'ua': 'металевий'},
        'нержавіюча сталь': {'ru': 'металлический', 'ua': 'металевий'},
        'латекс':       {'ru': 'латексный',        'ua': 'латексний'},
        'тпе':          {'ru': 'реалистичный',     'ua': 'реалістичний'},
        'кіберкожа':    {'ru': 'реалистичный',     'ua': 'реалістичний'},
        'шкіра':        {'ru': 'кожаный',          'ua': 'шкіряний'},
        'екошкіра':     {'ru': 'из экокожи',       'ua': 'з екошкіри'},
        'дерево':       {'ru': 'деревянный',       'ua': 'дерев\'яний'},
    },
    'Призначення': {
        'анальні':      {'ru': 'анальный',         'ua': 'анальний'},
        'вагінальні':   {'ru': 'вагинальный',      'ua': 'вагінальний'},
        'кліторальні':  {'ru': 'для клитора',      'ua': 'для клітора'},
        'для пар':      {'ru': 'для пар',          'ua': 'для пар'},
    },
    'Тип живлення': {
        'акумулятор':   {'ru': 'перезаряжаемый',   'ua': 'акумуляторний'},
        'батарейки':    {'ru': 'на батарейках',    'ua': 'на батарейках'},
        'usb':          {'ru': 'с usb зарядкой',   'ua': 'із зарядкою usb'},
    },
    'Водонепроникний': {
        'так':          {'ru': 'водонепроницаемый', 'ua': 'водонепроникний'},
    },
    'Конструкція': {
        'двосторонні':  {'ru': 'двусторонний',     'ua': 'двосторонній'},
        'безремінні':   {'ru': 'безремневой',      'ua': 'безремінний'},
        'на присосці':  {'ru': 'на присоске',      'ua': 'на присосці'},
    },
}
# Колір — окремо. Значень лише 17, тож перекладаємо всі: значення
# характеристик у фіді українські, і без перекладу російське поле втрачало
# цілий вимір («багато людей користуються російською» — власник 03.10).
COLOR_PARAM = 'Колір'
COLORS = {
    'чорний': 'черный', 'рожевий': 'розовый', 'червоний': 'красный',
    'фіолетовий': 'фиолетовый', 'синій': 'синий', 'білий': 'белый',
    'зелений': 'зеленый', 'золотий': 'золотой', 'тілесний': 'телесный',
    'коричневий': 'коричневый', 'прозорий': 'прозрачный', 'сірий': 'серый',
    'оранжевий': 'оранжевый', 'срібний': 'серебряный', 'бірюзовий': 'бирюзовый',
    'бежевий': 'бежевый', 'жовтий': 'желтый',
}
# Довші за це фрази запитами не бувають: «лубрикант на водной основе orgie
# lube tube» ніхто не вводить.
MAX_WORDS = 4


def product_type(name, brand):
    """Тип товару — кирилична частина назви до бренду, стисла до суті.

    Бренд беремо з тега `vendor` фіду (заповнений у всіх 5409 карток,
    117 значень), а не вгадуємо з назви: 03.10 частотний довідник розбивав
    «Art of Sex» на бренд «Art of» і модель «Sex».
    """
    if not name:
        return None
    head = name
    if brand and brand.lower() in name.lower():
        head = name[:name.lower().index(brand.lower())]
    else:
        m = LATIN.search(name)
        if m:
            head = name[:m.start()]
    typ = head.strip(' ,-–—')
    # «Лубрикант на водной основе» → «Лубрикант»: запитом є саме тип
    typ = re.split(r'\s+(?:на|для|з|из|с|із)\s+', typ)[0].strip()
    return typ or None


# Службові слова: модель на них не закінчується. 03.10 без цього виходили
# ключі «adrien lastic trigger с» і «adrien lastic amuse big» — обрізані
# посеред назви, їх відхиляла семантична перевірка.
TAIL_STOP = set('с со з із и і та and with для на от до в у the of in on for to a an'.split())


def model_of(name, brand):
    """Модель — слова після бренду до першого розділювача або службового слова.

    Беремо лише суцільний «хвіст моделі»: латиницю, цифри й дефіси. Щойно
    трапилось кириличне службове слово або кома — зупиняємось, бо далі йде
    опис, а не назва моделі.
    """
    if not brand:
        return None
    i = name.lower().find(brand.lower())
    if i < 0:
        return None
    tail = name[i + len(brand):]
    tail = re.split(r'[,;(–—]', tail)[0]
    out = []
    for w in tail.split():
        wl = w.strip(' .-').lower()
        if not wl or wl in TAIL_STOP:
            break
        if not re.match(r'^[\w\-\.]+$', w):
            break
        out.append(w.strip(' .,-'))
        if len(out) == 2:
            break
    model = ' '.join(out).strip()
    # однобуквений чи порожній хвіст моделлю не є
    return model if len(model) >= 3 else None


# Стать користувача: мастурбатор — чоловічий товар, фалоімітатор і вібратор
# для клітора — жіночі (правило власника). Ознака, що суперечить статі типу,
# ключем стати не може: 03.10 генератор видав «вагинальный мастурбатор».
GENDER_OF_TYPE = {'мастурбатор': 'ч', 'вагина': 'ч', 'вагіна': 'ч',
                  'фаллоимитатор': 'ж', 'фалоімітатор': 'ж',
                  'дилдо': 'ж', 'ділдо': 'ж'}
GENDER_OF_ADJ = {'вагинальный': 'ж', 'вагінальний': 'ж',
                 'для клитора': 'ж', 'для клітора': 'ж'}


_MORPH = {}


def agree(adj, noun, lang):
    """Узгодити прикметник з іменником за родом і числом.

    Без цього виходило «кожаный маска» і «шкіряний наручники» — склеювання
    рядків замість мови. pymorphy3 лежав під рукою весь день: його ставили
    вранці 03.10, щоб полагодити постобробку фіду.
    """
    code = 'uk' if lang == 'ua' else 'ru'
    if code not in _MORPH:
        try:
            import pymorphy3
            _MORPH[code] = pymorphy3.MorphAnalyzer(lang=code)
        except Exception:
            _MORPH[code] = None
    m = _MORPH[code]
    if m is None or len(adj.split()) > 1:
        return adj
    try:
        # Іменник: беремо розбір саме як NOUN
        npar = next((x for x in m.parse(noun.split()[0]) if 'NOUN' in x.tag),
                    m.parse(noun.split()[0])[0])
        gram = {npar.tag.gender, npar.tag.number} - {None}
        # Прикметник: беремо розбір саме як ADJF. Перший розбір бреше —
        # pymorphy вважає «білий» ПРІЗВИЩЕМ (NOUN,Surn), і узгодження не
        # спрацьовує: виходило «білий портупея», «чорний простирадло».
        apar = next((x for x in m.parse(adj) if 'ADJF' in x.tag), None)
        if apar is None:
            return adj
        a = apar.inflect(gram)
        if a is None and npar.tag.number:        # множина без роду
            a = apar.inflect({npar.tag.number})
        word = a.word if a else adj
        # pymorphy віддає «чёрный», а шукають «черный»: у пошукових запитах
        # «ё» майже не вводять.
        return word.replace('ё', 'е') if code == 'ru' else word
    except Exception:
        return adj


def _gender_conflict(adj, typ):
    tg = next((g for r, g in GENDER_OF_TYPE.items() if r in (typ or '').lower()), None)
    ag = GENDER_OF_ADJ.get(adj)
    return bool(tg and ag and tg != ag)


def attr_adjectives(offer, lang):
    """Прикметники з характеристик, якими реально шукають."""
    out = []
    for p in offer.findall('param'):
        name = (p.get('name') or '').strip()
        val = (p.text or '').strip().lower()
        if not val:
            continue
        if name in ATTR_WORDS:
            for key, words in ATTR_WORDS[name].items():
                if key in val:
                    out.append(words[lang])
                    break
        elif name == COLOR_PARAM:
            word = val if lang == 'ua' else COLORS.get(val)
            if word and len(word.split()) == 1 and len(word) > 3:
                out.append(word)
    # без повторів, зберігаючи порядок
    seen, res = set(), []
    for a in out:
        if a not in seen:
            seen.add(a)
            res.append(a)
    return res


def candidates(typ, brand, model, lang, adjectives=()):
    """Кандидати в ключі однією мовою. Кожен — самодостатня фраза-запит."""
    out = []
    t = (typ or '').lower()
    b = (brand or '').lower()
    if b in ('без бренда', 'без бренду'):
        b = ''
    if t:
        if b:
            out.append(f'{t} {b}')                      # «мастурбатор doc johnson»
            if model:
                out.append(f'{t} {b} {model.lower()}')
        for key, phrases in USE_CASES[lang].items():
            if key in t:
                out += phrases
                if b:
                    out.append(f'{phrases[0]} {b}')
    if b and model:
        out.append(f'{b} {model.lower()}')              # «doc johnson stella barey»
    # ознака + тип: «силіконовий вібратор», «анальна пробка на присосці».
    # Саме такі фрази роблять ключ УНІКАЛЬНИМ для картки, а не спільним на
    # тисячу: 03.10 перша версія генератора давала лише тип+бренд, і 38 %
    # карток пілота лишились без жодного власного ключа.
    # Прикметник чіпляємо ЛИШЕ до однослівного типу. 03.10 без цієї умови
    # виходило «силиконовый металлическая анальная пробка» — прикметник на
    # прикметник. І лише перед типом: «с usb зарядкой мастурбатор» — не фраза.
    if t and len(t.split()) == 1:
        for a in adjectives[:4]:
            if len(a.split()) > 1:        # «на батарейках», «з екошкіри» — після типу
                out.append(f'{t} {a}')
            else:
                a2 = agree(a, t, lang)
                out.append(f'{a2} {t}')
                if b:
                    out.append(f'{a2} {t} {b}')
    seen, res = set(), []
    for c in out:
        c = re.sub(r'\s+', ' ', c).strip(' ,-–—+/')
        if not (2 <= len(c.split()) <= MAX_WORDS) or c in seen:
            continue
        seen.add(c)
        res.append(c)
    return res


def build(feed, brands_path, sample=0):
    brands = set(json.load(open(brands_path, encoding='utf-8')))
    offers = list(ET.parse(feed).getroot().iter('offer'))

    def kws(o, tag):
        return [k.strip() for k in (o.findtext(tag) or '').split(',') if k.strip()]

    # частоти наявних ключів — щоб не додавати те, що й так на тисячі карток
    freq = collections.Counter()
    for o in offers:
        for tag in ('keywords', 'keywords_ua'):
            for k in kws(o, tag):
                freq[k.lower()] += 1

    plan, added = {}, collections.Counter()
    for o in offers:
        brand = (o.findtext('vendor') or '').strip()
        row = {}
        for tag in ('keywords', 'keywords_ua'):
            name_tag, lang = FIELD[tag]
            name = (o.findtext(name_tag) or '').strip()
            typ = product_type(name, brand)
            model = model_of(name, brand)
            have = kws(o, tag)
            have_low = {k.lower() for k in have}
            free = LIMIT - len(have)
            if free <= 0:
                continue
            adjs = [a for a in attr_adjectives(o, lang)
                    if not _gender_conflict(a, typ)]
            cand = [c for c in candidates(typ, brand, model, lang, adjs)
                    if c not in have_low and freq[c] < 50]
            # спершу найрідкісніші — вони дають картці власний запит
            cand.sort(key=lambda c: freq[c])
            take = cand[:free]
            if take:
                row[tag] = take
                added[tag] += len(take)
        if row:
            plan[o.get('id')] = {'name': (o.findtext('name') or '')[:80],
                                 'brand': brand, 'add': row}

    print(f'офферів: {len(offers)} · карток із пропозиціями: {len(plan)}')
    print(f'буде додано ключів: рос {added["keywords"]}, укр {added["keywords_ua"]}')
    out = os.path.join(BASE, 'exports', 'prom_kw_plan.json')
    json.dump(plan, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('→', out)

    if sample:
        import random
        random.seed(3)
        print('\nВИБІРКА:')
        for pid in random.sample(list(plan), min(sample, len(plan))):
            p = plan[pid]
            print(f'\n  {p["name"]}')
            print(f'    бренд={p["brand"]!r}')
            for tag, ks in p['add'].items():
                print(f'    +{tag}: {ks}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--feed', default='/tmp/prom_now.xml')
    ap.add_argument('--brands', default='/tmp/prom_brands.json')
    ap.add_argument('--sample', type=int, default=0)
    a = ap.parse_args()
    build(a.feed, a.brands, a.sample)
