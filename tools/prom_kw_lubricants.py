#!/usr/bin/env python3
"""Ключові фрази для категорії «Лубриканти» Prom — двома мовами.

Побудовано на доказах із самого фіду, а не на здогадах:

* **бренд** береться з тега `<vendor>` (заповнений у 308 з 308), а не
  витягується з назви. Наївне витягування з назви давало «Doc», «Anal»,
  «Swiss», «Love», «PREMIUM» — тобто хибні бренди;
* **транслітерація** взята з фраз, які вже є в живому фіді (`джо`, `пьюр`,
  `оржі`/`оржи`), і вона **різна для мов** — тому словник двомовний;
* **основа** визначається суворою формулою «на X основі». Водно-силіконові
  гібриди (5 карток) вона чесно лишає невизначеними замість здогаду — саме
  на цьому ризику наполягав Gemini в обговоренні;
* **константи не беруться**: «Стать: унісекс» у 93 з 93, «Сумісність з
  презервативами: Так» у 106 з 106 — вони не розрізняють товар;
* **заперечення не беруться**: «Без смаку» (36 карток), «без аромату» (29).

Слотів приблизно 9 на мову, поля `keywords_ua` і `keywords` — ОКРЕМІ.
"""
import json
import re

MAX_SLOTS = 9

TYPE = {'ua': ('лубрикант', 'змазка'), 'ru': ('лубрикант', 'смазка')}

# лише форми, які вже зустрічаються в живому фіді
TRANSLIT = {
    'JO': {'ua': 'джо', 'ru': 'джо'},
    'Pjur': {'ua': 'пьюр', 'ru': 'пьюр'},
    'Orgie': {'ua': 'оржі', 'ru': 'оржи'},
    'Doc Johnson': {'ua': 'док джонсон', 'ru': 'док джонсон'},
    'Sensuva': {'ua': 'сенсува', 'ru': 'сенсува'},
    'Shunga': {'ua': 'шунга', 'ru': 'шунга'},
    'Tenga': {'ua': 'тенга', 'ru': 'тенга'},
}

BASE_RE = re.compile(r'на (водн\w+|силіконов\w+|олійн\w+|гібридн\w+) основі', re.I)
# прикметник ПЕРЕД словом «лубрикант/змазка/гель» — теж надійна ознака
# («Силіконовий лубрикант pjur Light»), на відміну від будь-якої згадки
# силікону в тексті, яка може стосуватись сумісності з іграшками
BASE_ADJ_RE = re.compile(r'\b(водн\w+|силіконов\w+|олійн\w+|гібридн\w+)\s+'
                         r'(лубрикант|змазк\w+|гель)', re.I)
HYBRID_RE = re.compile(r'водно[- ]силіконов', re.I)
BASE_WORD = {
    'водн': {'ua': 'на водній основі', 'ru': 'на водной основе'},
    'силік': {'ua': 'на силіконовій основі', 'ru': 'на силиконовой основе'},
    'олійн': {'ua': 'на олійній основі', 'ru': 'на масляной основе'},
    'гібри': {'ua': 'гібридний', 'ru': 'гибридный'},
}

EFFECT = {
    'Зігріваючий': {'ua': 'розігрівальний', 'ru': 'разогревающий'},
    'Охолоджуючий': {'ua': 'охолоджувальний', 'ru': 'охлаждающий'},
    'Збуджуючий': {'ua': 'збуджувальний', 'ru': 'возбуждающий'},
    'Зволожуючий': {'ua': 'зволожувальний', 'ru': 'увлажняющий'},
}

NEGATIVE = {'без смаку', 'без аромату', 'ні', 'немає', 'нейтральний'}

# слова латиницею, які трапляються в назвах, але моделлю не є
NOT_MODEL = {'ml', 'мл', 'g', 'pro', 'new', 'premium', 'anal', 'toy', 'lube',
             'gel', 'sex', 'love', 'hot', 'cool', 'silicone', 'water'}


def model_of(name, brand):
    """Назва моделі — латинські слова після бренду.

    Саме модель дає довгий хвіст: без неї генератор видає 95 унікальних фраз
    на 308 карток, тобто шаблонність, у якій ми дорікали старим російським
    ключам. Бренд вирізаємо, службові слова відкидаємо.
    """
    tail = name
    if brand:
        pos = name.lower().find(brand.lower())
        if pos >= 0:
            tail = name[pos + len(brand):]
    # беремо ПІДРЯД ідучі латинські слова, а не вибірково: відкидання слова
    # з середини давало покалічене «slow finger» замість «Slow Sex Finger play»
    # цифри в моделі дозволені: без них «JO H2O» давало модель «H» і фразу «jo h»
    run = re.match(r'\s*((?:[A-Za-z][A-Za-z0-9\-]*\s+){0,2}[A-Za-z][A-Za-z0-9\-]*)', tail)
    if not run:
        return None
    words = run.group(1).split()
    words = [w for w in words if len(w) > 1]            # одинокі літери моделлю не є
    if not words or all(w.lower() in NOT_MODEL for w in words):
        return None
    return ' '.join(words[:3])


def base_of(name):
    if HYBRID_RE.search(name):
        return 'гібри'
    m = BASE_RE.search(name) or BASE_ADJ_RE.search(name)
    if not m:
        return None
    w = m.group(1).lower()
    for key in BASE_WORD:
        if w.startswith(key[:4]):
            return key
    return None


def volume(params):
    for k, v in params.items():
        if k.startswith('Об') and 'є' in k:
            v = (v or '').strip()
            return v if v else None
    return None


def build(card, lang):
    """→ список фраз для однієї мови. Порядок = пріоритет слотів."""
    t, syn = TYPE[lang]
    name = card['name_ua']
    brand = card.get('vendor') or ''
    brand = '' if brand in ('', 'Без бренда') else brand
    params = card.get('params') or {}
    out = []

    def add(p):
        p = re.sub(r'\s+', ' ', p).strip().lower()
        if p and p not in out and len(out) < MAX_SLOTS:
            out.append(p)

    if brand:
        add(f'{t} {brand}')                                   # 1 бренд латиницею
        tr = TRANSLIT.get(brand, {}).get(lang)
        if tr:
            add(f'{t} {tr}')                                  # 2 бренд кирилицею

    model = model_of(name, brand)
    if brand and model:
        add(f'{brand} {model}')                               # 3 бренд + модель
        add(f'{t} {brand} {model}')                           # 4 тип + бренд + модель

    b = base_of(name)
    if b:
        add(f'{t} {BASE_WORD[b][lang]}')                      # 5 основа

    for flag, words in EFFECT.items():                        # 4 ефект
        if str(params.get(flag, '')).strip().lower() in ('так', 'да', 'yes'):
            add(f'{words[lang]} {t}')
    eff = str(params.get('Додатковий ефект', '')).strip().lower()
    for flag, words in EFFECT.items():
        if eff and flag.lower()[:5] in eff:
            add(f'{words[lang]} {t}')

    for f in ('Смак', 'Аромат'):                              # 5 смак/аромат
        v = str(params.get(f, '')).strip()
        if v and v.lower() not in NEGATIVE:
            add(f'{t} {v.lower()}')

    if b:
        add(f'{syn} {BASE_WORD[b][lang]}')                    # 6 синонім + основа

    vol = volume(params)
    if vol:
        add(f'{t} {vol} мл' if lang == 'ua' else f'{t} {vol} мл')   # 7 обʼєм

    add(f'{t} для сексу' if lang == 'ua' else f'{t} для секса')     # 8 категорійна
    add(f'інтимна {syn}' if lang == 'ua' else f'интимная {syn}')    # 9 синонім
    return out


if __name__ == '__main__':
    import sys
    cards = json.load(open(sys.argv[1], encoding='utf-8'))
    for c in cards[:5]:
        print('\n', c['name_ua'][:88])
        print('  ua:', ', '.join(build(c, 'ua')))
        print('  ru:', ', '.join(build(c, 'ru')))


def merge(existing, generated, limit=MAX_SLOTS):
    """Доповнення, а не заміна.

    Наявний генератор дає фрази, яких правила не бачать: «лубрикант золотий»,
    «олія для орального сексу» — вони приходять з описової частини назви.
    Тому наявні фрази йдуть першими, згенеровані лише добивають порожні
    слоти. Так картка не може стати гіршою за нинішню.
    """
    out = []
    for p in list(existing) + list(generated):
        p = re.sub(r'\s+', ' ', (p or '')).strip().lower()
        if p and p not in out and len(out) < limit:
            out.append(p)
    return out
