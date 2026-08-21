#!/usr/bin/env python3
"""
NOIRE / SexOpt → XML прайс-лист для Prom.ua
============================================
Формат YML за офіційним описом support.prom.ua/hc/uk/articles/360004963538.

Чим відрізняється від Єпіцентру та Rozetka — і чому саме так:

  • Категорія береться через ДВА шари: sexopt → epicentr (готовий, двічі
    аудитований мапінг) → prom. Це 33 відповідності замість 170+.
  • Без type="vendor.model". У фіді Віктора цей атрибут стоїть без
    <typePrefix>, і Prom ігнорує готову назву, склеюючи власну з vendor+model:
    «Шланг системи охолодження Polestar 2 2023» перетворюється на
    «Polestar 32257944». Пишемо <name> напряму.
  • selling_type — АТРИБУТ офера зі значенням r/w/u/s, а не дочірній тег.
    У Віктора він дочірній зі значенням "retail", тобто мовчки ігнорується.
  • Ціна = РРЦ постачальника напряму (MARKUP 1.0, без gross-up на комісію).
    Комісію майданчика несе бізнес, не покупець — рішення власника 11.08.2026.
  • Розміри білизни та інших виробів обʼєднуються в різновиди через group_id:
    три розміри одного товару — одна позиція, а не три.
  • Фото максимум 10 (у Rozetka 15), опис обовʼязковий і лише в CDATA.
  • name_ua і description_ua заповнюються ЗАВЖДИ парою: без опису українською
    українська назва не застосується, і навпаки.

Запуск:
    python3 tools/noire_prom_generator.py -o output/noire_prom.xml
    python3 tools/noire_prom_generator.py --limit 50
"""
import argparse
import collections
import hashlib
import html
import json
import math
import os
import re
import sys
from datetime import datetime

import psycopg2
import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

OUT = os.path.join(BASE_DIR, 'output', 'noire_prom.xml')

SHOP_NAME = 'klatch1 shop'
SHOP_COMPANY = '3721108'
SHOP_URL = 'https://cs4053918.prom.ua/'

MARKUP = float(os.getenv('NOIRE_MARKUP_PROM', '1.0'))
DEFAULT_COMMISSION = float(os.getenv('NOIRE_PROM_COMMISSION', '18.88'))

MAX_PICTURES = 10        # офіційний ліміт Prom (у Rozetka 15)
IN_STOCK = os.getenv('NOIRE_PROM_IN_STOCK', '0') == '1'
BROKEN_PICS = set()
ACTUAL_CAT = {}
SUPPLIER_PARAMS = {}
MAX_NAME = 110           # правила оформлення карток

# Скорочення назв для видимої зони — рахується окремо
# (tools/prom_name_shorten.py) і лежить у docs/, щоб зміну можна було
# переглянути очима, а не шукати в коді.
try:
    with open(os.path.join(BASE_DIR, 'docs', 'prom_name_shorten.json'),
              encoding='utf-8') as _f:
        NAME_SHORTEN = json.load(_f)
except (OSError, ValueError):
    NAME_SHORTEN = {}
MAX_PARAMS = 100
MAX_ARTICLE = 25
MIN_PARAMS = 2           # Prom радить «мінімум 2-3 основні характеристики»
# Було 3: правило писалося тоді, коли поле лишалось ПОРОЖНІМ, і дві
# найзагальніші фрази справді не давали користі. Тепер поле добирається
# широкими фразами з тегових сторінок, тож викидати одну-дві ПРАВДИВІ
# фрази — чиста втрата: «кріплення для душу» краще за нічого.
MIN_KEYWORDS = 1
KEYWORD_TARGET = 9
MAX_KEYWORDS = 1000      # офіційний ліміт не задокументований, тримаємось нижче

# Порогів «відкритого словника», як у Rozetka, тут немає: найбільший список
# Prom — 33 значення (Тип інтимної іграшки), тобто всі вони закриті переліки.
# Значення поза списком у фільтри не потрапить, тому звіряємо суворо.


def esc(t) -> str:
    return html.escape(str(t) if t is not None else '', quote=True)


def cdata(t: str) -> str:
    """Опис може містити HTML — тоді він обовʼязково в CDATA (вимога Prom)."""
    return '<![CDATA[' + (t or '').replace(']]>', ']]&gt;') + ']]>'


# Prom забороняє в описі посилання на сторонні сайти — **крім YouTube**, який
# дозволений для відеооглядів. Опис приходить від постачальника, і в ньому
# трапляються домени сумісних сервісів (feelme.com, lovense.com) та згадки
# самого постачальника. Порушення виключає товар із каталогу ProSale.
ALLOWED_DOMAINS = ('youtu.be', 'youtube.com', 'www.youtube.com')
SUPPLIER_WORDS = ('sexopt', 'смтм', 'smtm')

_A_TAG = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                    re.I | re.S)
_BARE_URL = re.compile(r'https?://[^\s<>"\']+|\bwww\.[^\s<>"\']+', re.I)
_BARE_DOMAIN = re.compile(
    r'(?<![\w./@-])((?:[a-z0-9][a-z0-9\-]*\.)+(?:com\.ua|com|ua|net|org|io))'
    r'(?![\w-])', re.I)


def _allowed(url: str) -> bool:
    host = re.sub(r'^https?://', '', url).split('/')[0].lower()
    return any(host == d or host.endswith('.' + d) for d in ALLOWED_DOMAINS)


def strip_links(text: str, stats=None):
    """Прибрати сторонні посилання й згадки постачальника, лишити YouTube.

    Голі домени в тексті («сумісний з feelme.com») вирізаються разом із
    доменом, але речення лишається читабельним — саме тому тут не regex на
    весь абзац, а точкове видалення.
    """
    if not text:
        return text
    out = text

    def _a(m):
        if _allowed(m.group(1)):
            return m.group(0)
        if stats is not None:
            stats['посилань <a> прибрано'] += 1
        return m.group(2)          # лишаємо видимий текст, знімаємо посилання

    out = _A_TAG.sub(_a, out)

    def _u(m):
        if _allowed(m.group(0)):
            return m.group(0)
        if stats is not None:
            stats['голих URL прибрано'] += 1
        return ''

    out = _BARE_URL.sub(_u, out)

    def _d(m):
        if _allowed(m.group(1)):
            return m.group(1)
        if stats is not None:
            stats['доменів прибрано'] += 1
        return ''

    out = _BARE_DOMAIN.sub(_d, out)

    for w in SUPPLIER_WORDS:
        if re.search(w, out, re.I):
            out = re.sub(r'(?i)\b%s\b[.,]?\s*' % re.escape(w), '', out)
            if stats is not None:
                stats['згадок постачальника прибрано'] += 1

    # Після видалення домену лишаються обірвані хвости («на офіційному сайті .»,
    # «заходь на ()»). Prom вважає незвʼязний текст порушенням, тому
    # прибираємо повислі прийменники й порожні дужки.
    out = re.sub(r'\(\s*\)|\[\s*\]', '', out)
    out = re.sub(r'\s+([.,;:!?])', r'\1', out)
    out = re.sub(r'(?i)\b(на|у|в|до|за|з|із|зі)\s*([.,;:!?])', r'\2', out)
    out = re.sub(r'(?i)\b(заходь|перейди|дивись|переходь)\s+на\s*(?=[(<]|$)', '', out)
    out = re.sub(r'[ \t]{2,}', ' ', out)
    out = re.sub(r'([.,;:])\1+', r'\1', out)
    return out.strip()


_PACK_RE = re.compile(r'(\d{1,4})\s*шт', re.I)


def pack_scale(name: str) -> float:
    """Множник габаритів для наборів «N шт».

    Категорійний дефолт описує звичайну пачку. Набір презервативів на 100
    штук фізично більший у рази, і занижені габарити дали б неправильну
    вартість доставки на позиції до 20 000 грн. Масштабуємо за коренем
    кубічним від кількості: обʼєм росте лінійно, лінійний розмір — як корінь.
    """
    m = _PACK_RE.search(name or '')
    if not m:
        return 1.0
    n = int(m.group(1))
    if n < 24:
        return 1.0
    return min((n / 12) ** (1 / 3), 3.0)


_CAPS_OK = {'BDSM', 'БДСМ', 'XL', 'XXL', 'USB', 'LED', 'ABS', 'TPE', 'TPR',
            'PVC', 'ПВХ', 'IPX', '3D', '2D', 'DVD', 'CD', 'UV', 'SM'}


def fix_caps(name: str, vendor: str) -> str:
    """Прибрати надлишковий капс, лишивши фірмове написання бренду.

    Визначення капсу тут ТЕ САМЕ, що у валідаторі (`prom_validator._is_all_caps`):
    слово з великою літерою й без жодної малої, включно з дволітерними («JO»)
    та з цифрами («H2O»). Перша версія рахувала інакше — лише алфавітні слова
    довші за 2 символи — і через це 92 назви лишились із помилкою.

    Нормалізуємо не все підряд: слова бренду лишаються як є, решта переходить
    у Title Case, і рівно стільки, щоб капсових лишилось не більше трьох.
    """
    words = name.split()
    if len(words) <= 3:
        return name

    def is_caps(w):
        return bool(re.search(r'[А-ЯЁІЇЄA-Z]', w)) and not re.search(r'[а-яёіїєa-z]', w)

    caps = [w for w in words if is_caps(w)]
    if len(caps) <= 3:
        return name

    vt = {x.upper() for x in (vendor or '').split()}
    # спершу знижуємо ті, що не належать бренду й не є короткими абревіатурами
    order = sorted(range(len(words)),
                   key=lambda k: (words[k].upper() in vt,
                                  words[k].upper() in _CAPS_OK,
                                  len(words[k]) <= 3))
    need = len(caps) - 3
    out = list(words)
    for k in order:
        if need <= 0:
            break
        if is_caps(out[k]) and out[k].isalpha():
            out[k] = out[k].capitalize()
            need -= 1
    return ' '.join(out)


# Російські відповідники категорій. Написані руками свідомо: gemma3:4b на
# коротких рядках не перекладає, а повертає вхід незміненим — перевірено на
# всіх 30 записах. Тридцять рядків надійніше вивірити очима, ніж промпт.
_RU_CAT = {}
_RU_MATERIAL = {
    'Силікон': ('силиконовый', 'силиконовая', 'силиконовое', 'силиконовые'),
    'Метал': ('металлический', 'металлическая', 'металлическое', 'металлические'),
    'Латекс': ('латексный', 'латексная', 'латексное', 'латексные'),
    'Скло': ('стеклянный', 'стеклянная', 'стеклянное', 'стеклянные'),
    'ПВХ': ('виниловый', 'виниловая', 'виниловое', 'виниловые'),
    'ABS-пластик': ('пластиковый', 'пластиковая', 'пластиковое', 'пластиковые'),
    'Нержавіюча сталь': ('стальной', 'стальная', 'стальное', 'стальные'),
}
_RU_GENDER = {'m': 0, 'f': 1, 'n': 2, 'p': 3}


def _load_ru_cat():
    import json
    path = os.path.join(BASE_DIR, 'docs', 'prom_category_ru.json')
    if _RU_CAT or not os.path.exists(path):
        return _RU_CAT
    with open(path, encoding='utf-8') as f:
        _RU_CAT.update(json.load(f))
    return _RU_CAT


def ru_keywords(kw_ua: str, ru_row: dict, vendor: str, category: str = '',
                prm: dict = None) -> str:
    """Пошукові запити для РОСІЙСЬКОГО поля — тими самими шаблонами, що й укр.

    Раніше тут була лише голова російської назви плюс бренд: 1.8 фрази проти
    3.6 українських. Тепер працює той самий набір шаблонів, бо зʼявився
    російський довідник категорій; прикметник матеріалу узгоджується за родом
    російського типу, а не українського.
    """
    prm = prm or {}
    name_ru = (ru_row or {}).get('name_ru') or ''
    if not name_ru or not (ru_row or {}).get('is_ru'):
        return ''
    cat = _load_ru_cat().get((category or '').strip())
    single, gender, purpose = cat if cat else ('', 'm', '')

    t = name_ru.split(vendor)[0] if vendor and vendor in name_ru else name_ru
    t = re.split(r'[,(]', t)[0]
    words = [w for w in t.split()
             if w and not w.isdigit() and not re.fullmatch(r'[A-Za-z0-9\-.]+', w)]
    while words and words[-1].lower() in ('с', 'из', 'для', 'на', 'в', 'к', 'и'):
        words.pop()
    head = ' '.join(words[:3]).strip()
    material = (prm.get('Матеріал') or '').split('|')[0].split(',')[0].strip()

    # бренд кирилицею — та сама таблиця, що для української, але російська
    # форма: «сатисфайер», не «сатисфаєр». Без цього російська сторона
    # відставала б від української рівно на цей шаблон.
    try:
        from prom_keywords import brand_cyr as _bcyr
        cyr = _bcyr(vendor, 'ru')
    except Exception:
        cyr = ''

    cand = []
    if head and vendor:
        cand.append(f'{head} {vendor}')
    if single and cyr:
        cand.append(f'{single} {cyr}')
    if head and cyr:
        cand.append(f'{head} {cyr}')
    if single and vendor:
        cand.append(f'{single} {vendor}')
    if material in _RU_MATERIAL and single:
        cand.append(f'{_RU_MATERIAL[material][_RU_GENDER[gender]]} {single}')
    if single and purpose:
        cand.append(f'{single} {purpose}')
    m = re.search(re.escape(vendor) + r'\s+([A-Za-z][A-Za-z0-9\-]+)', name_ru) \
        if vendor else None
    if m:
        cand.append(f'{vendor} {m.group(1)}')
    if head:
        cand.append(head)

    seen, res, total = set(), [], 0
    for x in cand:
        x = re.sub(r'\s+', ' ', x).strip().lower()
        if not (2 <= len(x.split()) <= 4) or x in seen:
            continue
        if total + len(x) + 2 > MAX_KEYWORDS:
            break
        seen.add(x)
        res.append(x)
        total += len(x) + 2
    return ', '.join(res[:8])   # та сама стеля 8, що й для української


def calc_price(retail: float, commission: float) -> int:
    """Ціна продажу = РРЦ постачальника напряму, без gross-up на комісію.

    Рішення власника 11.08.2026: комісію маркетплейсу несе бізнес, а не
    покупець. Раніше тут був gross-up ÷(1−комісія), який на Prom додавав
    +23.3% до РРЦ і робив нас дорожчими за ринок на тій самій моделі
    (перевірено на Lelo Ina Wave 2: наші 16 000 грн проти 11 799 медіани
    серед семи точних конкурентів).

    Аргумент `commission` лишено у сигнатурі: він більше не впливає на
    ціну, але потрібен викликам і майбутньому розрахунку маржі.
    """
    return math.ceil(retail * MARKUP)


# ── Наші назви характеристик → назви з довідника Prom ───────────────────────
# Збігаються лише «Матеріал», «Колір», «Розмір», «Призначення». Решту треба
# перекладати, інакше характеристика не потрапить у фільтри каталогу.
PARAM_ALIAS = {
    # ── тип товару: у Prom він названий по-різному в кожній категорії ──
    'Тип товару': ('Тип', 'Тип інтимної іграшки', 'Тип вібратора',
                   'Тип мастурбатора', 'Тип фалоімітатора', 'Тип засобу',
                   'Тип гри', 'Вид секс-ляльки'),
    'Тип': ('Тип', 'Тип інтимної іграшки', 'Тип вібратора',
            'Тип мастурбатора', 'Тип фалоімітатора'),
    'Вид': ('Тип мастурбатора', 'Тип фалоімітатора', 'Тип вібратора',
            'Тип інтимної іграшки', 'Вид секс-ляльки', 'Тип'),
    'Тип приладу': ('Тип вібратора', 'Тип інтимної іграшки', 'Тип'),
    'Тип помпи': ('Тип',),
    'Тип аксесуара': ('Тип',),
    'Тип засобу': ('Тип засобу', 'Тип'),
    'Тип фалоімітатора': ('Тип фалоімітатора', 'Тип'),
    'Тип мастурбатора': ('Тип мастурбатора', 'Тип'),

    # ── розміри: наші значення в мм, у довіднику Prom одиниця залежить від
    # категорії («Довжина» буває і мм, і см) — перерахунок робить fit_params
    'Довжина (мм)': ('Довжина', 'Довжина робочої частини'),
    'Довжина': ('Довжина', 'Довжина робочої частини'),
    'Діаметр (мм)': ('Діаметр',),
    'Діаметр': ('Діаметр',),
    'Ширина (мм)': ('Ширина',),
    'Висота (мм)': ('Висота',),
    'Товщина (мм)': ('Товщина',),
    'Вага (г)': ('Вага',),
    'Вага': ('Вага',),

    # ── живлення й керування ──
    'Тип живлення': ('Живлення',),
    'Живлення': ('Живлення',),
    'Керування через застосунок': ('Тип управління', 'Управління'),
    'Управління': ('Управління', 'Тип управління'),
    'Пульт ДК': ('Управління', 'Тип управління'),

    # ── вібрація й режими ──
    'Вібрація': ('Функція вібрації', 'Вібрація'),
    'Віброефект': ('Функція вібрації', 'Вібрація'),
    'Кількість режимів': ('Кількість режимів вібрації',
                          'Кількість режимів роботи'),
    'Кількість режимів роботи': ('Кількість режимів роботи',
                                 'Кількість режимів вібрації'),
    'Кількість режимів вібрації': ('Кількість режимів вібрації',
                                   'Кількість режимів роботи'),

    # ── аудиторія, форма, комплектація ──
    'Для кого': ('Для кого', 'Стать'),
    'Стать': ('Стать', 'Для кого'),
    'Форма': ('Форма', 'Форма випуску'),
    'Форма випуску': ('Форма випуску', 'Форма'),
    'Конструкція': ('Форма', 'Особливості'),
    'Кілька насадок': ('Комплектація', 'Набір'),
    'Комплектація': ('Комплектація', 'Кількість в комплекті', 'Набір'),
    'Кількість в упаковці': ('Кількість в упаковці', 'Кількість в наборі'),

    # ── склад і матеріали ──
    # ВАЖЛИВО: у довіднику Prom «Обʼєм» пишеться через ЗВОРОТНИЙ АПОСТРОФ
    # (Об`єм), а не через звичайний. Без цього варіанта характеристика
    # мовчки не знаходилась у жодній категорії.
    'Обʼєм': ('Об`єм', "Об'єм"),
    "Об'єм": ('Об`єм', "Об'єм"),
    'Об`єм': ('Об`єм',),
    'Основа засобу': ('Основа',),
    'Основа мастила': ('Основа',),
    'Основа': ('Основа',),
    'Матеріал колби': ('Матеріал колби', 'Матеріал'),
    'Смак': ('Смак',),
    'Текстура': ('Текстура',),
    'Рівень підготовки': ('Рівень підготовки',),
    'Термін придатності': ('Термін придатності',),
}

# Булеві характеристики → значення multiselect «Особливості»
FEATURE_MAP = {
    'Водонепроникний': 'Водонепроникні',
    'Підігрів': 'З підігрівом',
    'На присосці': 'На присосках',
    'Безшумний': 'Безшумні',
    'Віброефект': 'З вібрацією',
    'Вібрація': 'З вібрацією',
    'Надувний': 'Надувні',
    'Телескопічний': 'Телескопічні',
    'Реалістичний': 'Реалістичні',
    'Двосторонній': 'Двосторонні',
    'Кишеньковий': 'Кишенькові',
    'Автоматичний': 'Автоматичні',
    'Гіпоалергенний': 'Гіпоалергенні',
    'Ароматизований': 'Ароматизовані',
    'Без спирту': 'Без спирту',
    'Антибактеріальний': 'Антибактеріальні',
    'Для силікону': 'Для силікону',
    'Для латексу': 'Для латексу',
}

# Булеві характеристики, що лягають у «Додатковий ефект», а не «Особливості»:
# це різні переліки Prom, і значення одного в іншому не приймається.
EFFECT_MAP = {
    'Зігріваючий': 'Розігріваючий',
    'Розігріваючий': 'Розігріваючий',
    'Охолоджуючий': 'Охолоджуючий',
    'Збуджуючий': 'Збудливий',
    'Пролонгатор': 'Пролонгуючий ефект',
    'Зволожуючий': 'Зволоження',
    'Знеболюючий': 'Знеболюючий',
}

# Наші значення → значення довідника Prom (коли формулювання різне)
VALUE_ALIAS = {
    'силікон': 'Силікон', 'медичний силікон': 'Медичний силікон',
    'латекс': 'Латекс', 'метал': 'Метал', 'скло': 'Скло', 'гума': 'Гума',
    'пвх': 'ПВХ', 'пластик': 'Пластик', 'абс-пластик': 'ABS-пластик',
    'тпе': 'ТПЕ (термопластичний еластомер)',
    'кібершкіра': 'Кібершкіра', 'нержавіюча сталь': 'Нержавіюча сталь',
    'акумулятор': 'Акумулятор', 'батарейки': 'Батарейки', 'мережа': 'Мережа',
    'унісекс': 'Унісекс', 'для жінок': 'Для жінок',
    'для чоловіків': 'Для чоловіків', 'для пар': 'Для пар',
    # Наші написання проти переліку Prom. Додаємо лише однозначні
    # відповідники: «Шкіра» без уточнення не мапимо — вона може бути і
    # натуральною, і штучною, а вгадувати склад товару не можна.
    'еко-шкіра': 'Штучна шкіра', 'екошкіра': 'Штучна шкіра',
    'штучна шкіра': 'Штучна шкіра', 'натуральна шкіра': 'Натуральна шкіра',
    'поліестер': 'Синтетичний', 'поліуретан': 'Поліуретан',
    'нейлон': 'Нейлон', 'неопрен': 'Неопрен', 'каучук': 'Каучук',
    'вініл': 'Вініл', 'акрил': 'Акрил', 'джут': 'Джут', 'віск': 'Віск',
    'дерево': 'Дерево', 'сталь': 'Сталь', 'срібло': 'Срібло',
}

# Розмірні позначки, за якими товар визнається різновидом того самого виробу
SIZE_TOKEN = re.compile(
    r'\b(?:XS|S|M|L|XL|XXL|2XL|3XL|XXXL)\s*/\s*(?:S|M|L|XL|XXL|2XL|3XL|XXXL)\b'
    r'|\b(?:XS|S|M|L|XL|XXL|2XL|3XL|XXXL)\b|\bone\s?size\b|\bT[1-4]\b'
    r'|\b[1-4]/[2-4]\b', re.I)


def variant_key(vendor: str, name: str) -> str:
    """Ключ різновиду: назва без розмірної позначки."""
    return re.sub(r'\s+', ' ', SIZE_TOKEN.sub(' ', name or '')).strip(' ,.-').lower()


# Кольори, якими розрізняються різновиди, коли розміру в назві немає
COLOR_TOKEN = [
    (r'\bчорн\w*|\bblack\b', 'Чорний'), (r'\bбіл\w*|\bwhite\b', 'Білий'),
    (r'\bчервон\w*|\bred\b', 'Червоний'), (r'\bрожев\w*|\bpink\b', 'Рожевий'),
    (r'\bсин\w*|\bblue\b', 'Синій'), (r'\bзелен\w*|\bgreen\b', 'Зелений'),
    (r'\bфіолетов\w*|\bpurple\b|\bviolet\b', 'Фіолетовий'),
    (r'\bзолот\w*|\bgold\b', 'Золотистий'), (r'\bсрібн\w*|\bsilver\b', 'Сріблястий'),
    (r'\bбежев\w*|\bbeige\b', 'Бежевий'), (r'\bпрозор\w*|\btransparent\b', 'Прозорий'),
]


def variant_mark(name: str) -> tuple:
    """Чим саме цей різновид відрізняється від інших у групі.

    Prom відхиляє різновид, у якого немає жодного значення, відмінного від
    решти групи: «Різновид не буде імпортований». Артикул не рахується.
    А в наших даних відмінність — розмір або колір — живе ЛИШЕ в назві:
    у 134 зі 135 груп набори характеристик виявились ідентичними.
    Тому витягуємо ознаку з назви й віддаємо окремим <param>.

    «Розміру» немає в довідниках цих категорій, тож він стане
    користувацькою характеристикою: у фільтри каталогу не піде, зате
    зробить різновид валідним, а покупцеві буде видно на картці.
    """
    m = SIZE_TOKEN.search(name or '')
    if m:
        return 'Розмір', re.sub(r'\s*/\s*', '/', m.group(0)).upper()
    for rx, val in COLOR_TOKEN:
        if re.search(rx, name or '', re.I):
            return 'Колір', val
    return None, None


def stable_group_id(key) -> int:
    """Незмінний номер групи різновидів у діапазоні Prom (1..999999999)."""
    digest = hashlib.sha1(repr(key).encode('utf-8')).hexdigest()
    return int(digest[:12], 16) % 999_999_000 + 1


def load_mapping(cur) -> dict:
    """epicentr_code → [(prom_id, name_rule, excluded)], правила спершу."""
    cur.execute("""SELECT epicentr_code, prom_category_id, name_rule, excluded
                   FROM prom_category_mapping WHERE source='noire'
                   ORDER BY (name_rule IS NULL), id""")
    out = collections.defaultdict(list)
    for r in cur.fetchall():
        out[r['epicentr_code']].append(
            (r['prom_category_id'], r['name_rule'], r['excluded']))
    return out


def resolve_category(mapping: dict, ec: str, name: str):
    """Категорія Prom за кодом Єпіцентру, з урахуванням правил по назві."""
    for pid, rule, excluded in mapping.get(ec, []):
        if rule and not re.search(rule, name, re.I):
            continue
        return pid, excluded
    return None, False


def load_rates(cur) -> dict:
    cur.execute("""SELECT category_id, cpa_rate FROM prom_cpa_rates
                   WHERE source='noire'""")
    return {r['category_id']: float(r['cpa_rate']) for r in cur.fetchall()}


def load_attributes(cur) -> dict:
    """prom_id → {назва: (тип, одиниця, {значення}, min, max)}"""
    cur.execute("""SELECT prom_category_id, attr_name, attr_type,
                          measure_unit, allowed_values, min_value, max_value
                   FROM prom_category_attributes""")
    out = collections.defaultdict(dict)
    for r in cur.fetchall():
        vals = {str(v).strip().lower(): str(v).strip()
                for v in (r['allowed_values'] or [])}
        def _f(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None
        out[r['prom_category_id']][r['attr_name']] = (
            r['attr_type'], r['measure_unit'], vals,
            _f(r['min_value']), _f(r['max_value']))
    return out


def load_categories(cur) -> dict:
    cur.execute('SELECT category_id, name FROM prom_categories')
    return {str(r['category_id']): r['name'] for r in cur.fetchall()}


def _number(value: str):
    m = re.search(r'(\d+(?:[.,]\d+)?)', str(value))
    return float(m.group(1).replace(',', '.')) if m else None


_OUT_OF_RANGE = []
_sku_ctx = ['']
st_composite = []
# Характеристики, які не варто дублювати в «Користувацьких»: вони вже є
# окремими тегами оффера, і повтор виглядав би сміттям у картці.
# «Бренд» дублює тег <vendor>, тому не потрібен. А от країну виробництва
# фід Prom окремим тегом не передає — там вона доречна як характеристика.
CUSTOM_SKIP = {'Бренд', 'Виробник'}


def fit_params(raw: dict, pid: str, attrs: dict, sku: str = '',
               boost: dict = None) -> dict:
    """Наші характеристики → характеристики довідника Prom.

    Все, чого немає в довіднику категорії, відкидаємо: такі значення
    показуються лише на картці й не працюють у фільтрах каталогу, а
    фільтри — головна причина, чому характеристики взагалі заповнюють.
    """
    _sku_ctx[0] = sku
    spec = attrs.get(pid, {})
    out, features, effects, unplaced = {}, [], [], []
    if not spec:
        # Категорія без довідника атрибутів — у Prom такі є, наприклад
        # «Секс-машини» (перевірено в кабінеті вручну 21.08.2026).
        # Доти повертали порожньо, і 8-14 характеристик зникали на 33
        # картках: у фіді вони мали НУЛЬ характеристик. Портальних полів
        # тут не існує, але КОРИСТУВАЦЬКІ існують — вони видно на картці
        # й саме їх радить заповнювати підтримка Prom.
        for name, value in list(raw.items()) + list((boost or {}).items()):
            v = str(value).strip()
            if v and name not in CUSTOM_SKIP:
                out.setdefault(name, v[:500])
        return out

    for name, value in raw.items():
        v = str(value).strip()
        if not v:
            continue

        if name in FEATURE_MAP and v.lower() in ('так', 'yes', 'true'):
            features.append(FEATURE_MAP[name])
            unplaced.append((name, 'Так'))
            continue

        if name in EFFECT_MAP and v.lower() in ('так', 'yes', 'true'):
            effects.append(EFFECT_MAP[name])
            unplaced.append((name, 'Так'))
            continue

        targets = PARAM_ALIAS.get(name, (name,))
        hit = next((t for t in targets if t in spec), None)
        if not hit:
            continue
        atype, unit, allowed, vmin, vmax = spec[hit]

        if atype in ('real', 'int'):
            num = _number(v)
            if num is None:
                continue
            # У довіднику одиниця своя: наша «Довжина (мм)» у категорії
            # вібраторів має бути в см, у БДСМ — у мм.
            if unit == 'см' and 'мм' in name:
                num /= 10
            elif unit == 'мм' and 'см' in name:
                num *= 10
            # Межі довідника — це заявлений Promом правдоподібний діапазон.
            # Вихід за них означає помилку в даних постачальника (реальний
            # приклад: «Діаметр (мм) = 320» на вібраторі, тобто 32 см).
            # Публікувати такий факт не можна — характеристику відкидаємо.
            if (vmin is not None and num < vmin) or \
               (vmax is not None and num > vmax):
                _OUT_OF_RANGE.append((_sku_ctx[0], hit, f'{num:g}', unit, vmax))
                # у портальне поле не лягає (межі категорії), але сам факт
                # цінний — віддаємо користувацькою характеристикою з одиницею
                unplaced.append((f'{hit}, {unit}' if unit else hit, f'{num:g}'))
                continue
            out[hit] = f'{num:g}'
        elif allowed:
            key = VALUE_ALIAS.get(v.lower(), v).lower()
            if key in allowed:
                out[hit] = allowed[key]
            else:
                # «TPE, Поліпропілен» — постачальник дає склад через кому,
                # у переліку Prom такого значення немає, і раніше воно
                # відкидалось цілком. Розбиваємо й віддаємо ВСІ складові,
                # що є в довіднику, через «|»: товар потрапляє у фільтр за
                # кожним матеріалом окремо (SKILL-13.4).
                parts = []
                for part in re.split(r'[,;/]| та | і ', v):
                    pk = VALUE_ALIAS.get(part.strip().lower(),
                                         part.strip()).lower()
                    if pk in allowed and allowed[pk] not in parts:
                        parts.append(allowed[pk])
                if parts:
                    out[hit] = ' | '.join(parts)
                    st_composite.append(name)
        else:
            out[hit] = v[:500]

    if effects and 'Додатковий ефект' in spec:
        allowed = spec['Додатковий ефект'][2]
        ok = [e for e in effects if e.lower() in allowed]
        if ok:
            out['Додатковий ефект'] = ' | '.join(sorted(set(ok)))

    # Усе, що не лягло в портальні поля, віддаємо як користувацькі
    # характеристики: у фільтри вони не потраплять, але заповнюють картку
    # й підвищують показник якості. Раніше ці 29 831 значення просто
    # зникали.
    for name, value in list(raw.items()) + list((boost or {}).items()):
        v = str(value).strip()
        if not v or name in CUSTOM_SKIP or name in FEATURE_MAP \
                or name in EFFECT_MAP:
            continue
        targets = PARAM_ALIAS.get(name, (name,))
        if any(t in out for t in targets) or name in out:
            continue
        out.setdefault(name, v[:500])

    # булеві та числові, що не знайшли місця в портальних переліках
    for nm, val in unplaced:
        out.setdefault(nm, val)

    if features and 'Особливості' in spec:
        allowed = spec['Особливості'][2]
        ok = [f for f in features if f.lower() in allowed]
        if ok:
            out['Особливості'] = ' | '.join(sorted(set(ok)))
    return out


def load_products(cur):
    cur.execute("""
        SELECT p.sku, p.name, p.description_html, p.price_retail, p.vendor,
               p.pictures, p.country, p.quantity, p.available,
               m.epicentr_category_code AS ec,
               sc.name AS cat_name
        FROM sexopt_products p
        LEFT JOIN sexopt_categories sc ON sc.id = p.category_id
        JOIN epicentr_category_mapping m
          ON m.sexopt_category_id = p.category_id
         AND COALESCE(m.confidence, 1) > 0
        WHERE p.available IS TRUE AND p.quantity > 1
          AND NOT p.damaged_stock AND p.price_retail > 0
        ORDER BY p.sku
    """)
    return cur.fetchall()


def load_params(cur) -> dict:
    """Наші характеристики; окремо — ті, що робились під вільні пари Rozetka.

    `rozetka_boost` не можна пускати в ПОРТАЛЬНІ поля Prom: значення там
    підбирались під вільний формат Rozetka й у закриті переліки не лягають.
    Але «Користувацькі характеристики» Prom — теж вільні пари, і там ці
    значення доречні: вони заповнюють картку, хоч і не працюють у фільтрах.
    """
    cur.execute("""SELECT sku, param_name, param_value, source
                   FROM sexopt_extracted_params
                   WHERE param_value IS NOT NULL AND TRIM(param_value) <> ''""")
    out, boost = collections.defaultdict(dict), collections.defaultdict(dict)
    for r in cur.fetchall():
        tgt = boost if r['source'] == 'rozetka_boost' else out
        tgt[r['sku']][r['param_name']] = r['param_value']
    logger.info(f'Характеристик: портальних {len(out)} товарів, '
                f'лише-користувацьких {len(boost)}')
    return out, boost


def load_unknown_vendors(cur) -> set:
    """Бренди, яких немає в базі виробників Prom.

    Prom імпортує виробника лише якщо він є в базі маркетплейсу, інакше
    у звіті зʼявляється «Невідомий виробник». Перевірити це програмно
    неможливо — публічної вигрузки бази виробників немає, а API-токен
    акаунта віддає 401. Тому список наповнюється зі звіту про імпорт:
    tools/prom_unknown_vendors_load.py --from-report.

    Поки таблиця порожня, підміни не відбувається: це не блокує імпорт,
    бо невідомий виробник — попередження, а не помилка.
    """
    try:
        cur.execute('SELECT vendor FROM prom_unknown_vendors')
        return {(r['vendor'] or '').strip().lower() for r in cur.fetchall()}
    except psycopg2.Error:
        cur.connection.rollback()
        return set()


def load_overrides(cur) -> dict:
    try:
        cur.execute("""SELECT sku, price_manual FROM sexopt_price_override
                       WHERE until IS NULL OR until >= CURRENT_DATE""")
        return {r['sku']: int(r['price_manual']) for r in cur.fetchall()}
    except psycopg2.Error:
        cur.connection.rollback()
        return {}


def load_ru(cur) -> dict:
    """Російський контент постачальника (окремий фід import-retail-2.xml).

    У Prom `<name>`/`<description>` — це РОСІЙСЬКІ поля, а `_ua` — українські.
    Доти сюди клався той самий український текст, і картка мала два однакові
    описи. Дослідження прямо називає це причиною блокування в Google Merchant
    Center, а Prom вважає дублюванням контенту.

    Fallback свідомий: якщо російського тексту немає (703 позиції) або він
    насправді український (`is_ru = false`), лишаємо українську версію —
    порожнє поле гірше за дубль, бо без пари `description`/`description_ua`
    Prom не застосує ані українську назву, ані опис.
    """
    try:
        cur.execute("""SELECT sku, name_ru, description_ru, is_ru
                       FROM sexopt_products_ru""")
    except psycopg2.Error:
        cur.connection.rollback()
        logger.warning('sexopt_products_ru недоступна — рос. текст = укр.')
        return {}
    out = {r['sku']: dict(r) for r in cur.fetchall()}
    # Постачальник дає російський опис не на весь асортимент. Для решти
    # беремо власний машинний переклад — але ЛИШЕ той, що пройшов валідатор
    # (status='ok'). Позиції зі status='manual' лишаються з українським
    # описом: краще дубль, ніж напівперекладений текст у картці.
    try:
        cur.execute("""SELECT sku, result FROM noire_ru_translation
                       WHERE status = 'ok' AND COALESCE(result, '') <> ''""")
        n = 0
        for r in cur.fetchall():
            row = out.setdefault(r['sku'], {'name_ru': '', 'is_ru': False})
            if not (row.get('description_ru') or '').strip():
                row['description_ru'] = r['result']
                n += 1
        logger.info(f'Машинних перекладів підставлено: {n}')
    except psycopg2.Error:
        cur.connection.rollback()
        logger.warning('noire_ru_translation недоступна')
    logger.info(f'Російських карток завантажено: {len(out)}')
    return out


def load_tags(cur) -> dict:
    """(категорія, мова) → широкі фрази з тегових сторінок Prom.

    Шаблони дають переважно «точний» шар семантичного ядра: тип + бренд +
    модель. Широкий шар — «гумова вагіна», «анальний гак», «вібратор мова» —
    вони не породжують у принципі, бо цієї лексики немає в наших даних.
    Тегові сторінки Prom дають її прямо: це фрази, під які майданчик завів
    окремі сторінки, тобто вважає вартими індексації.

    Одна фраза застосовна до ВСІХ товарів категорії, тому 62 нові фрази
    закривають дефіцит у тисяч позицій.
    """
    try:
        cur.execute("""SELECT category, phrase, COALESCE(lang, 'ua') lang
                       FROM prom_category_tags""")
    except psycopg2.Error:
        cur.connection.rollback()
        return {}
    out = collections.defaultdict(list)
    for r in cur.fetchall():
        out[(r['category'], r['lang'])].append(r['phrase'])
    logger.info(f'Тегових фраз завантажено: {sum(len(v) for v in out.values())}')
    return out


def load_dimensions(cur) -> dict:
    """epicentr_code → (вага_г, ширина_мм, висота_мм, довжина_мм).

    Габарити потрібні Promу для розрахунку доставки; порожні поля змушують
    систему брати середні по категорії, і це може заблокувати відправку
    поштоматом через штучне перевищення розмірів (SKILL-14.2).

    Джерело — та сама таблиця, що вже працює для Єпіцентру. Значення
    оцінкові (`source='estimated'`) і описують ПАКОВАННЯ, тому беруться
    комплектом: змішувати реальну довжину товару з оцінковою шириною
    паковання означало б отримати неузгоджений набір.
    """
    try:
        cur.execute("""SELECT epicentr_category_code ec, weight_g, width_mm,
                              height_mm, length_mm
                       FROM epicentr_default_dimensions""")
    except psycopg2.Error:
        cur.connection.rollback()
        logger.warning('epicentr_default_dimensions недоступна — габарити порожні')
        return {}
    out = {r['ec']: (r['weight_g'], r['width_mm'], r['height_mm'], r['length_mm'])
           for r in cur.fetchall()}
    logger.info(f'Категорійних габаритів завантажено: {len(out)}')
    return out


def load_actual_categories(cur) -> dict:
    """sku → категорія, яку Prom присвоїв товару насправді."""
    try:
        cur.execute('SELECT sku, category_id FROM prom_actual_category')
        return {r['sku']: r['category_id'] for r in cur.fetchall()}
    except psycopg2.Error:
        cur.connection.rollback()
        return {}


def load_supplier_params(cur) -> dict:
    """sku → {атрибут Prom: значення} з таблиці постачальника."""
    try:
        cur.execute('SELECT sku, param, value FROM prom_derived_params')
        out = {}
        for r in cur.fetchall():
            out.setdefault(r['sku'], {})[r['param']] = r['value']
        return out
    except psycopg2.Error:
        cur.connection.rollback()
        return {}


def load_param_overrides(cur) -> dict:
    """sku → {характеристика: значення} — виправлення поверх даних постачальника.

    `SUPPLIER_PARAMS` лише заповнює порожнє (`if not raw.get(k)`), тому хибне
    значення ним не перебити. А хибні значення бувають: постачальник ставив
    `Тип = Анальний душ` усім 33 позиціям категорії «Анальні пробки», зокрема
    вібропробкам Satisfyer і We-Vibe. Опис і назва казали одне, характеристика
    на тій самій сторінці — інше; це рівно та «розбіжність даних», за яку
    знімає з публікації модерація Rozetka.

    Порожнє значення = прибрати характеристику зовсім (краще, ніж хибна).
    Значення береться з довідника категорії Prom, а не вигадується:
    `prom_attribute_values`.
    """
    try:
        cur.execute("""SELECT sku, param, value FROM prom_param_override""")
        out = {}
        for r in cur.fetchall():
            out.setdefault(r['sku'], {})[r['param']] = (r['value'] or '').strip()
        return out
    except psycopg2.Error:
        cur.connection.rollback()
        logger.warning('prom_param_override недоступна')
        return {}


def load_rewritten(cur) -> dict:
    """Унікальні описи замість тексту постачальника.

    Опис від SexOpt дослівно збігається з картками інших дропшиперів того
    самого постачальника — замір `prom_dup_check.py` дав середні 90%, девʼять
    позицій із вісімнадцяти збіглись слово в слово. Тут підставляється текст,
    складений із фактів (`prom_desc_rewrite.py`).

    Беремо ЛИШЕ `status = 'ok'`. Позиція, що не пройшла валідатор, лишається
    з оригінальним описом: дубль гірший за унікальність, але вигадана
    характеристика гірша за дубль.
    """
    try:
        cur.execute("""SELECT sku, rewritten, rewritten_ru
                       FROM prom_rewritten_desc
                       WHERE status = 'ok' AND COALESCE(rewritten, '') <> ''""")
        return {r['sku']: dict(r) for r in cur.fetchall()}
    except psycopg2.Error:
        cur.connection.rollback()
        logger.warning('prom_rewritten_desc недоступна — описи від постачальника')
        return {}


def load_broken_pics(cur) -> set:
    """Посилання на фото, які постачальник віддає з помилкою."""
    try:
        cur.execute("""SELECT url FROM noire_photo_audit
                       WHERE error IS NOT NULL""")
        return {re.sub(r'^https?://', '', r['url']) for r in cur.fetchall()}
    except psycopg2.Error:
        cur.connection.rollback()
        return set()


def load_keywords() -> dict:
    """Пошукові запити з Рівня 1 (tools/prom_keywords.py + prom_kw_finalize).

    Беремо лише позиції, де набралось MIN_KEYWORDS фраз. Решта чекає на
    Рівень 2: порожнє поле чесніше за поле з двох найзагальніших фраз, які
    дають «порожні» покази й тягнуть рейтинг ProSale вниз (SKILL-13.6).

    Пишемо тільки в <keywords>. Окремого тега для української версії в
    документації Prom немає, а невідомий тег може відхилити імпорт цілком —
    тому до перевірки на пілотній партії другу мову не чіпаємо.
    """
    import json
    path = os.path.join(BASE_DIR, 'docs', 'prom_kw_level1_all.json')
    if not os.path.exists(path):
        logger.warning('prom_kw_level1_all.json не знайдено — '
                       'поле пошукових запитів лишається порожнім')
        return {}
    out, cats = {}, {}
    with open(path, encoding='utf-8') as f:
        for r in json.load(f):
            # категорія верхнього рівня — та сама, з якої будувались
            # українські фрази. sexopt_categories.name дає ЛИСТОВУ
            # («Попки», «Вібратори-кролики»), і словник по ній не працює.
            if r.get('category'):
                cats[r['sku']] = r['category']
            phrases = r.get('final') or []
            if len(phrases) >= MIN_KEYWORDS:
                kw = ', '.join(phrases)[:MAX_KEYWORDS]
                if kw:
                    out[r['sku']] = kw
    logger.info(f'Пошукових запитів завантажено: {len(out)}, '
                f'категорій верхнього рівня: {len(cats)}')
    return out, cats


def generate(out_file=OUT, limit=None):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    mapping = load_mapping(cur)
    rates = load_rates(cur)
    attrs = load_attributes(cur)
    cat_names = load_categories(cur)
    products = load_products(cur)
    params, params_boost = load_params(cur)
    overrides = load_overrides(cur)
    unknown_vendors = load_unknown_vendors(cur)
    keywords, kw_cats = load_keywords()
    dims = load_dimensions(cur)
    tags = load_tags(cur)
    global BROKEN_PICS
    BROKEN_PICS = load_broken_pics(cur)
    global ACTUAL_CAT
    ACTUAL_CAT = load_actual_categories(cur)
    global SUPPLIER_PARAMS
    SUPPLIER_PARAMS = load_supplier_params(cur)
    ru = load_ru(cur)
    param_over = load_param_overrides(cur)
    logger.info(f'Позицій із виправленими характеристиками: {len(param_over)}')
    rewritten = load_rewritten(cur)
    logger.info(f'Унікальних описів підставлено: {len(rewritten)}')
    conn.close()
    logger.info(f'Товарів у вибірці: {len(products)}')

    # ── різновиди: групуємо за брендом і назвою без розміру ─────────────────
    groups = collections.defaultdict(list)
    for p in products:
        groups[(p['vendor'], variant_key(p['vendor'], p['name']))].append(p)
    logger.info(f'Груп після обʼєднання розмірів: {len(groups)}')

    st = collections.Counter()
    used_cats, offers = {}, []

    for key, items in groups.items():
        head = items[0]
        pid, excluded = resolve_category(mapping, head['ec'], head['name'] or '')
        # Якщо Prom уже перекласифікував цей товар — беремо його рішення.
        # Звіт імпорту 16.08.2026: 949 позицій із автовизначеною категорією,
        # 337 із них лягли не туди, куди ми відправляли. Для каталогу
        # ProSale правильна категорія — основний критерій видачі, а наш
        # мапінг іде через два шари (sexopt → epicentr → prom) і на межових
        # товарах помиляється. Наполягати на своєму означає щоразу давати
        # системі привід переносити товар.
        actual = ACTUAL_CAT.get(head['sku'])
        if actual and actual != pid:
            pid = actual
            st['категорію взято з Prom'] += len(items)
        if not pid:
            st['без мапінгу'] += len(items)
            continue
        if excluded:
            st['виключено (Фаза 2)'] += len(items)
            continue
        # ворота якості: опис і фото — вимоги Prom, не наші побажання
        if not any((x['description_html'] or '').strip() for x in items):
            st['без опису'] += len(items)
            continue
        if not any(len(x['pictures'] or []) >= 2 for x in items):
            st['менше 2 фото'] += len(items)
            continue

        # Групуємо лише тоді, коли різновиди справді різні. Ознака береться
        # з назви (розмір або колір); якщо в двох позицій вона однакова —
        # це не різновиди, а дублі товару під різними артикулами. Вигадувати
        # їм відмінність не можна, тому такі йдуть окремими позиціями.
        marks = [variant_mark(x['name'] or '')[1] for x in items]
        distinct = len(items) > 1 and all(marks) and len(set(marks)) == len(marks)
        # Prom відхиляє різновид, у якого є характеристика, відсутня в
        # основного товару: «знайдені характеристики, яких немає в основного
        # товару». Тому в межах групи лишаємо лише СПІЛЬНІ ключі — перетин,
        # а не обʼєднання. Відмітна ознака додається всім, тож набір ключів
        # виходить однаковий, а значення різні.
        common_keys = None
        if distinct:
            for x in items:
                r = dict(params.get(x['sku'], {}))
                if x['country']:
                    r.setdefault('Країна-виробник',
                                 x['country'].split('(')[0].strip())
                keys = set(fit_params(r, pid, attrs))
                common_keys = keys if common_keys is None else (common_keys & keys)
        # group_id рахуємо ДЕТЕРМІНОВАНО з ключа групи, а не наскрізним
        # лічильником: зникнення одного товару зсувало нумерацію всім групам
        # після нього (147 з 359 офферів змінили group_id між двома збірками),
        # і Prom щоразу перебудовував би звʼязки різновидів заново.
        group_id = stable_group_id(key) if distinct else None
        if group_id:
            st['груп із різновидами'] += 1
        elif len(items) > 1:
            st['дублі — розгруповано'] += len(items)
        used_cats[pid] = cat_names.get(pid, pid)
        rate = rates.get(pid, DEFAULT_COMMISSION)

        for p in items:
            sku = p['sku']
            name = (p['name'] or '').strip()
            # У назві не повинно бути посилань і контактів. Єдиний випадок —
            # серія Doc Johnson «Girls of Social Media», де модель названа
            # нікнеймом (@viking.barbie). Знімаємо лише «@»: сам токен — це
            # ідентифікатор моделі, без нього товар не відрізнити від сусіднього.
            vend_clean = re.sub(r'\s*\(.*?\)', '', p['vendor'] or '').strip()
            # Prom вимагає, щоб виробник у назві збігався зі значенням
            # <vendor>. У 476 позицій бренд є в теґу, але не в назві —
            # додаємо його після типу товару, тобто після першого слова:
            # так зберігається і формула назви, і «правило трьох слів»
            # для URL (перші три слова лишаються осмисленими).
            if (vend_clean and vend_clean.lower() not in name.lower()
                    and vend_clean.lower() not in ('без бренда', 'без бренду')):
                w = name.split()
                cand = ' '.join(w[:1] + [vend_clean] + w[1:]) if w else name
                if len(cand) <= MAX_NAME:
                    name = cand
                    st['бренд додано в назву'] += 1
                else:
                    st['бренд не вміщується в назву'] += 1
            fixed = fix_caps(name, (p['vendor'] or '').strip())
            if fixed != name:
                name = fixed
                st['капс у назві нормалізовано'] += 1
            if '@' in name:
                name = re.sub(r'@(?=\w)', '', name)
                st['«@» прибрано з назви'] += 1
            # Видима зона Prom — перші ~70 символів. Якщо початок назви
            # збігається з іншою карткою, у видачі вони не відрізняються
            # (докладно — tools/prom_name_shorten.py).
            if sku in NAME_SHORTEN:
                name = NAME_SHORTEN[sku]
                st['назву скорочено для видимої зони'] += 1
            if len(name) > MAX_NAME:
                name = name[:MAX_NAME].rsplit(' ', 1)[0].rstrip(' ,.-')
                st['назву вкорочено'] += 1
            # Биті посилання Prom не просто пропускає — він рахує їх як
            # помилки імпорту («3 не можуть бути завантажені» у звіті
            # 16.08.2026). Ті, про які ми вже знаємо з фотоаудиту (HTTP 404
            # у постачальника), відсіюємо заздалегідь.
            pics = [u for u in (p['pictures'] or []) if u
                    and re.sub(r'^https?://', '', u) not in BROKEN_PICS]
            if len(pics) > MAX_PICTURES:
                st['фото обрізано'] += 1
            pics = pics[:MAX_PICTURES]
            if not pics:
                st['без фото'] += 1
                continue

            desc = (p['description_html'] or '').strip()
            if not desc:
                # У межах групи опис може бути лише в одного розміру —
                # беремо його, інакше українська назва не застосується.
                desc = next(((x['description_html'] or '').strip()
                             for x in items
                             if (x['description_html'] or '').strip()), '')
                st['опис узято з різновиду'] += 1
            desc = strip_links(desc, st)
            # Унікальний опис має пріоритет над текстом постачальника.
            rw = rewritten.get(sku) or {}
            if rw.get('rewritten'):
                desc = rw['rewritten']
                st['опис унікальний (переписаний)'] += 1

            raw = dict(params.get(sku, {}))
            if p['country']:
                raw.setdefault('Країна-виробник',
                               p['country'].split('(')[0].strip())
            # Характеристики з кабінету постачальника (tools/sexopt_prices.py
            # → tools/prom_supplier_params.py): матеріал, довжина, діаметр,
            # маса, вібрація. Це структурована таблиця з картки товару, а не
            # витяг регулярками з опису, тому точніша за все, що ми мали.
            # Ставимо лише туди, де порожньо: пряме поле фіду надійніше.
            for k, v in SUPPLIER_PARAMS.get(sku, {}).items():
                if not raw.get(k):
                    raw[k] = v
                    st['характеристики від постачальника'] += 1
            # Виправлення застосовуються ОСТАННІМИ — вони мають перебивати і
            # постачальника, і наші похідні значення.
            for k, v in (param_over.get(sku) or {}).items():
                if v:
                    raw[k] = v
                    st['характеристику виправлено'] += 1
                else:
                    raw.pop(k, None)
                    st['характеристику прибрано'] += 1
            prm = fit_params(raw, pid, attrs, sku,
                             params_boost.get(sku) or {})
            if group_id:
                dropped = len(prm)
                prm = {k: v for k, v in prm.items() if k in (common_keys or set())}
                if dropped != len(prm):
                    st['характеристик прибрано з різновидів'] += dropped - len(prm)
                # Різновид без жодного відмінного значення Prom не імпортує
                mk, mv = variant_mark(p['name'] or '')
                prm[mk] = mv
                st['ознаку різновиду додано'] += 1
            st[f'характеристик {min(len(prm), 5)}'] += 1
            if len(prm) < MIN_PARAMS:
                st['менше 2 характеристик'] += 1

            price = overrides.get(sku) or calc_price(
                float(p['price_retail']), rate)
            # in_stock="true" — «Готово до відправки». Атрибут офіційний,
            # підтверджений специфікацією YML (support.prom.ua, стаття
            # 360004963538): <offer id available in_stock type selling_type>.
            # Такі товари мають пріоритет у видачі («Як формується видача на
            # маркетплейсі»). Але це ЗАЯВА покупцеві, що товар відправлять
            # одразу, а ми возимо від постачальника — тому за замовчуванням
            # вимкнено, вмикається свідомо через NOIRE_PROM_IN_STOCK=1.
            ready = ' in_stock="true"' if IN_STOCK else ''
            attr = (f'      <offer id="{esc(sku)}" available="true" '
                    f'selling_type="r"{ready}'
                    + (f' group_id="{group_id}"' if group_id else '') + '>')
            if IN_STOCK:
                st['позначено «Готово до відправки»'] += 1
            # <name>/<description> — російські поля Prom, `_ua` — українські
            rr = ru.get(sku) or {}
            name_ru = (rr.get('name_ru') or '').strip() if rr.get('is_ru') else ''
            # Ліміт 110 символів діє на обидві мови, а російська назва
            # довша за українську на префіксах на кшталт «Мастурбатор-яйцо».
            name_ru = fix_caps(name_ru, (p['vendor'] or '').strip())
            if len(name_ru) > MAX_NAME:
                name_ru = name_ru[:MAX_NAME].rsplit(' ', 1)[0].rstrip(' ,.-')
                st['назву рос. вкорочено'] += 1
            if name_ru:
                st['назва рос. з окремого фіду'] += 1
            else:
                st['назва рос. = укр. (немає перекладу)'] += 1
            o = [attr,
                 f'        <name>{esc(name_ru or name)}</name>',
                 f'        <name_ua>{esc(name)}</name_ua>']
            o += [f'        <picture>{esc(u)}</picture>' for u in pics]
            o += [f'        <price>{price}</price>',
                  '        <currencyId>UAH</currencyId>',
                  f'        <categoryId>{esc(pid)}</categoryId>',
                  f'        <portal_category_id>{esc(pid)}</portal_category_id>']
            vendor = re.sub(r'\s*\(.*?\)', '', p['vendor'] or '').strip()
            if vendor.lower() in unknown_vendors:
                vendor = 'Без бренда'
                st['бренд замінено на «Без бренда»'] += 1
            if vendor:
                o.append(f'        <vendor>{esc(vendor)}</vendor>')
            o.append(f'        <vendorCode>{esc(sku[:MAX_ARTICLE])}</vendorCode>')
            o.append(f'        <quantity_in_stock>{int(p["quantity"] or 0)}'
                     f'</quantity_in_stock>')
            # description і description_ua ЗАВЖДИ разом: без пари Prom не
            # застосує ані український опис, ані українську назву.
            desc_ru = strip_links((rr.get('description_ru') or '').strip(), st)
            # Російське поле теж має бути унікальним: інакше картка лишається
            # дублем для тих, хто дивиться її російською.
            if rw.get('rewritten_ru'):
                desc_ru = rw['rewritten_ru']
            if desc_ru:
                st['опис рос. з окремого фіду'] += 1
            else:
                st['опис рос. = укр. (немає перекладу)'] += 1
            o.append(f'        <description>{cdata(desc_ru or desc)}</description>')
            o.append(f'        <description_ua>{cdata(desc)}</description_ua>')
            # <keywords> — РОСІЙСЬКЕ поле кабінету, <keywords_ua> —
            # українське. Обидва задокументовані в специфікації YML. Доти
            # українські фрази йшли в російське поле, і українська пошукова
            # аудиторія не бачила жодного нашого ключа.
            kw = keywords.get(sku, '')
            cat_ua = kw_cats.get(sku, '')
            # добираємо широкими фразами категорії до цілі у 8 (лист
            # підтримки Prom 14.08.2026), не дублюючи вже наявні
            def _fill(base, lang):
                cur_ph = [x.strip() for x in base.split(',') if x.strip()]
                seen = {x.lower() for x in cur_ph}
                # Ціль 9, а не 8. Дев'ятий слот раніше займав артикул —
                # рішення власника 16.08.2026 прибрати його: внутрішній код
                # постачальника покупець ніде не бачить і в пошук не вводить.
                # Слот віддаємо ще одній фразі з семантичного ядра, яка має
                # шанс збігтися з реальним запитом.
                for t in tags.get((cat_ua, lang), []):
                    if len(cur_ph) >= KEYWORD_TARGET:
                        break
                    if t.lower() not in seen:
                        seen.add(t.lower())
                        cur_ph.append(t)
                return ', '.join(cur_ph)[:MAX_KEYWORDS]

            kw = _fill(kw, 'ua')
            if kw:
                st['фраз добрано тегами'] += 1
            if kw:
                o.append(f'        <keywords_ua>{esc(kw)}</keywords_ua>')
                st['пошукові запити укр.'] += 1
                kw_ru = _fill(ru_keywords(kw, rr, vendor, cat_ua, raw), 'ru')
                if kw_ru:
                    o.append(f'        <keywords>{esc(kw_ru)}</keywords>')
                    st['пошукові запити рос.'] += 1
            else:
                st['без пошукових запитів'] += 1

            if dim := dims.get(p['ec']):
                w_g, wd, ht, ln = dim
                k = pack_scale(name)
                if k > 1:
                    w_g = int(w_g * k ** 3) if w_g else w_g
                    wd = int(wd * k) if wd else wd
                    ht = int(ht * k) if ht else ht
                    ln = int(ln * k) if ln else ln
                    st['габарити масштабовано під набір'] += 1
                # реальна довжина товару може перевищувати оцінку паковання —
                # тоді паковання не може бути коротшим
                real = _number((params.get(sku) or {}).get('Довжина (мм)', ''))
                if real and real > (ln or 0):
                    ln = real
                o.append('        <dimensions>')
                if w_g:
                    o.append(f'          <weight unit="kg">{w_g / 1000:g}</weight>')
                for tag, mm in (('width', wd), ('height', ht), ('length', ln)):
                    if mm:
                        o.append(f'          <{tag} unit="cm">{mm / 10:g}</{tag}>')
                o.append('        </dimensions>')
                st['габарити проставлено'] += 1
            else:
                st['габаритів немає (категорія не в довіднику)'] += 1
            for k, v in list(prm.items())[:MAX_PARAMS]:
                o.append(f'        <param name="{esc(k)}">{esc(v)}</param>')
            o.append('      </offer>')
            offers.append('\n'.join(o))
            st['офферів'] += 1

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<yml_catalog date="{datetime.now():%Y-%m-%d %H:%M}">',
             '  <shop>',
             f'    <name>{esc(SHOP_NAME)}</name>',
             f'    <company>{esc(SHOP_COMPANY)}</company>',
             f'    <url>{esc(SHOP_URL)}</url>',
             '    <currencies><currency id="UAH" rate="1" /></currencies>',
             '    <categories>']
    for pid, nm in sorted(used_cats.items(), key=lambda x: x[1]):
        lines.append(f'      <category id="{esc(pid)}" portal_id="{esc(pid)}">'
                     f'{esc(nm)}</category>')
    lines += ['    </categories>', '    <offers>']
    lines += offers[:limit] if limit else offers
    lines += ['    </offers>', '  </shop>', '</yml_catalog>', '']

    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    logger.success(f"Згенеровано офферів: {st['офферів']} → {out_file}")
    logger.info(f"  категорій             : {len(used_cats)}")
    logger.info(f"  груп із різновидами   : {st['груп із різновидами']}")
    for k in ('виключено (Фаза 2)', 'без опису', 'менше 2 фото', 'без мапінгу',
              'фото обрізано', 'назву вкорочено', 'менше 2 характеристик',
              'опис узято з різновиду', 'ознаку різновиду додано',
              'дублі — розгруповано', 'бренд замінено на «Без бренда»',
              'характеристик прибрано з різновидів'):
        if st[k]:
            logger.info(f'  {k:22}: {st[k]}')
    return st['офферів']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--output', default=OUT)
    ap.add_argument('--limit', type=int)
    a = ap.parse_args()
    sys.exit(0 if generate(a.output, a.limit) else 1)


if __name__ == '__main__':
    main()
