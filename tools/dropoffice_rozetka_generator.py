#!/usr/bin/env python3
"""dropoffice → XML прайс-лист для Rozetka Маркетплейс.

Окремий генератор і окремий файл `output/dropoffice_rozetka.xml`. Фіди NOIRE
і TOPTUL цей інструмент не має права торкнутись: `_safe_output()` відмовляє
писати у файл із префіксом `noire` чи `toptul` (TOPTUL зараз на перевірці в
Rozetka, і будь-яка зміна під нею зіб'є перевірку — правило 12).

Джерело — фід постачальника (кабінет dropoffice), 1207 офферів будівельних і
оздоблювальних матеріалів, переважно Sticker Wall. На вході він кращий за
TOPTUL: українські назва й опис уже є (`name_ua`, `description_ua`),
характеристики готові. Що довелося робити — і чому (докази в
`docs/dropoffice_feed_assessment.md`):

  * **категорії** — `docs/dropoffice_rozetka_map.tsv`. Кожна категорія
    постачальника звірена з тим, куди ці самі артикули вже поставили
    конкуренти на Rozetka (блок `categories` пошукового API, по 3 артикули).
    До фіду йдуть рівні `confirmed`, `manual` і `owner` (вибір власника 11.09
    для 5 спірних груп); `review` — ні: хибна
    категорія гірша за відсутню (SKILL-04, «нижче порогу — не вгадуємо»);
  * **характеристики** — у кожної категорії Rozetka СВОЇ назви й одиниці для
    тих самих розмірів: у «Самоклейних плівках» ширина рулону в см, довжина
    в м, товщина в мікронах; у «ПВХ покритті» ширина в м. Постачальник дає
    усе в мм. Тому розміри перераховуються під категорію, а текстові значення
    фільтрів виводяться лише тоді, коли вони ДОСЛІВНО є в довіднику категорії
    (`data/dropoffice_category_options.json`, `rozetka_options_fetch.py`);
  * **розмір у назві проти характеристики** — 16 карток мають розмір,
    що суперечить повному розміру в назві («710х690х3мм», а товщина 5). Протиріччя
    назви й характеристик модератор помічає першим, тож таку характеристику
    не виводимо взагалі — вгадувати, яке з двох чисел правильне, не можна;
  * **фото** — постачальник кладе інфографіку (шари матеріалу, розмірні
    лінії, панелі іконок) на позиції 2–4 і «КУПУЮТЬ РАЗОМ» наприкінці. Саме
    за це Rozetka відхилила TOPTUL. Автоматично відрізнити інфографіку не
    вдалося (gemma3:4b пропустила 19 із 25 на ручній розмітці), тож за
    замовчуванням ідемо лише з першим фото: воно чисте в 39 із 40 перевірених;
  * **уцінка** — 20 товарів «Уцінка/Розпродаж» мають плашку з причиною уцінки
    прямо на фото; їхнє місце — розділ «Знижені в ціні», не звичайна категорія;
  * **без бренду** — 79 карток без `<vendor>`. Rozetka його вимагає, а бренд
    вигадувати не можна — на рішення власника;
  * **ціна** — `<price>` постачальника є РРЦ: 30 із 30 перевірених артикулів
    продаються на Prom рівно за нею. Множник — з `data/price_rules.json`
    (`tools/price_rules.py`): ×1.10 типово, ×1.00 там, де комісія 5–11 %.

Запуск:
    python3 tools/dropoffice_rozetka_generator.py --fetch      # свіжий фід
    python3 tools/dropoffice_rozetka_generator.py              # з кешу
    python3 tools/dropoffice_rozetka_generator.py --photos all # усі фото
"""
import argparse
import collections
import csv
import html
import json
import math
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCE_URL = os.getenv(
    'DROPOFFICE_FEED_URL',
    'https://kabinet.dropoffice.com.ua/data/7584005b2498aebb572fa6a91bfda027.xml')
CACHE = os.path.join(BASE_DIR, 'data', 'dropoffice', 'source.xml')
OUT = os.path.join(BASE_DIR, 'output', 'dropoffice_rozetka.xml')
MAP = os.path.join(BASE_DIR, 'docs', 'dropoffice_rozetka_map.tsv')
OPTIONS = os.path.join(BASE_DIR, 'data', 'dropoffice_category_options.json')
DROPS = os.path.join(BASE_DIR, 'docs', 'dropoffice_rozetka_dropped.tsv')

SHOP_NAME = 'klatch1 shop'
SHOP_COMPANY = '3721108'
SHOP_URL = 'https://cs4053918.prom.ua/'

# Ціна = РРЦ постачальника × множник із правил `data/price_rules.json`
# (фід «dropoffice»), які змінює лише `tools/price_rules.py` — з історією й
# відкатом. Рішення власника 12.09.2026 за заміром конкурентів (SKILL-30 §9):
#   * типово ×1.10 — 27 % конкурентів стоять РІВНО на РРЦ, тож будь-яка
#     надбавка ставить нас позаду цього кластера (топ-3 за ціною 82/95 на ×1.00
#     → 18/95 на ×1.05), а далі позиція падає повільно (×1.10 — 6 дешевших із
#     14, ×1.05 — 5). Якщо піднімати, то одразу до медіани ринку;
#   * ×1.00 для категорій із комісією 5–11 % (ПВХ і гумові покриття, плитка,
#     мозаїка, плінтуси): там надбавка ставить нас позаду 11–13 продавців.
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
import price_rules  # noqa: E402
PRICE_FEED = 'dropoffice'


def markup_for(rz: str, article: str = '', _cache={}) -> float:
    if 'rules' not in _cache:
        _cache['rules'] = price_rules.load_rules()
    return price_rules.markup_for(PRICE_FEED, rz, article, _cache['rules'])


ALLOWED_TIERS = ('confirmed', 'manual', 'owner')
MIN_PARAMS = 3
MAX_NAME = 150
MAX_PICTURES = 15
CYRILLIC = re.compile(r'[а-яА-ЯіІєЄїЇґҐёЁ]')

# Картки, де інфографіка стоїть ПЕРШИМ фото (знайдено вручну на контактних
# аркушах 11.09.2026). З режимом «лише перше фото» чистого фото в них немає.
BAD_FIRST_PHOTO = {'SW-00000579'}

# Rozetka #7253098 п.4 (15.09.2026): «на фото лише товар». Переглянуто всі 1108
# перших фото: колажі «КУПУЮТЬ РАЗОМ», інтер'єри з меблями, текст на фото.
# Для них — інше фото постачальника лише з товаром (за точною адресою), або
# картку виключено, якщо чистого фото немає.
PHOTO_FILE = os.path.join(BASE_DIR, 'data', 'dropoffice_photo_override.json')
_PH = json.load(open(PHOTO_FILE, encoding='utf-8')) if os.path.exists(PHOTO_FILE) else {}
PHOTO_OVERRIDE = {k: v['url'] for k, v in (_PH.get('override') or {}).items()}
PHOTO_EXCLUDE = dict(_PH.get('exclude') or {})

# rz_id категорій, на які посилаються правила нижче
DP, PL, PVC, KOV = '4629548', '4648788', '4641184', '4625988'


def esc(t) -> str:
    return html.escape(str(t) if t is not None else '', quote=True)


def cdata(t: str) -> str:
    return '<![CDATA[' + (t or '').replace(']]>', ']]&gt;') + ']]>'


def _safe_output(path: str) -> str:
    full = os.path.abspath(path)
    base = os.path.basename(full).lower()
    if base.startswith(('noire', 'toptul')):
        sys.exit(f'ВІДМОВА: {full} — чужий фід, писати в нього заборонено')
    return full


# ── Джерело ────────────────────────────────────────────────────────────────
def fetch_source() -> None:
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    req = urllib.request.Request(SOURCE_URL, headers={'User-Agent': 'Mozilla/5.0'})
    body = urllib.request.urlopen(req, timeout=120).read()
    # Відповідь без офферів (сторінка входу, помилка) не має затерти кеш.
    root = ET.fromstring(body)
    n = len(root.findall('.//offer'))
    if n < 100:
        sys.exit(f'у свіжому фіді лише {n} офферів — кеш не оновлено')
    with open(CACHE + '.tmp', 'wb') as f:
        f.write(body)
    os.replace(CACHE + '.tmp', CACHE)
    print(f'джерело оновлено: {n} офферів, {len(body) // 1024} КБ')


def load_map() -> tuple:
    good, bad = {}, {}
    with open(MAP, encoding='utf-8') as f:
        for r in csv.DictReader(f, delimiter='\t'):
            if r['rz_id'] and r['tier'] in ALLOWED_TIERS:
                good[r['supplier_cat_id']] = (r['rz_id'], r['rz_name'])
            else:
                bad[r['supplier_cat_id']] = (r['tier'], r['supplier_cat'], r['note'])
    return good, bad


def load_options() -> dict:
    """rz_id → {назва характеристики: (тип, одиниця, множина значень)}."""
    with open(OPTIONS, encoding='utf-8') as f:
        raw = json.load(f)
    out = {}
    for cid, items in raw.items():
        cat = {}
        for x in items:
            nm = (x.get('name') or '').strip()
            if not nm:
                continue
            t, u, vals = cat.get(nm, (x.get('attr_type'), x.get('unit'), set()))
            if x.get('value_name'):
                vals.add(str(x['value_name']).strip())
            cat[nm] = (t, u, vals)
        out[cid] = cat
    return out


# ── Числа й розміри ────────────────────────────────────────────────────────
_NUM_UNIT = re.compile(r'^\s*(\d+(?:[.,]\d+)?)\s*(мм|mm|см|cm|cм|м|m)?\s*$', re.I)


def to_mm(v):
    """«600» → 600.0 (голе число в цьому фіді — мм), «147см» → 1470.0."""
    m = _NUM_UNIT.match(str(v or ''))
    if not m:
        return None
    x = float(m.group(1).replace(',', '.'))
    u = (m.group(2) or 'мм').lower()
    return x * {'мм': 1, 'mm': 1, 'см': 10, 'cm': 10, 'cм': 10, 'м': 1000, 'm': 1000}[u]


_TRIPLE = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*[хxХX*×]\s*(\d+(?:[.,]\d+)?)\s*[хxХX*×]\s*'
    r'(\d+(?:[.,]\d+)?)\s*(мм|mm)', re.I)


def name_triple(name: str):
    """Повний розмір А×Б×В мм із назви або None."""
    m = _TRIPLE.search(name or '')
    if not m:
        return None
    return {float(m.group(i).replace(',', '.')) for i in (1, 2, 3)}


_NAME_DIMS = re.compile(r'(\d+(?:[.,]\d+)?)\s*(?:мм|mm|см|cm|м|m)?\s*[хxХX*×]\s*(\d+(?:[.,]\d+)?)\s*(?:мм|mm|см|cm|м|m)?'
                        r'(?:\s*[хxХX*×]\s*(\d+(?:[.,]\d+)?)\s*(?:мм|mm|см|cm|м|m)?)?(?![\w])', re.I)
_UNIT_K = {'мм': 1, 'mm': 1, 'см': 10, 'cm': 10, 'м': 1000, 'm': 1000}


def name_dims_mm(name: str):
    """Розмір із назви в мм з урахуванням одиниць (Rozetka #7253098 п.3):
    «200х150х0.8см» → (2000, 1500, 8); «0.40х10м» → (400, 10000);
    «60*60cm*2cm» → (600, 600, 20). Число без одиниці бере одиницю наступного
    («0.45х10м х 0.07мм»: 0.45 м); якщо одиниці немає ніде — мм."""
    m = _NAME_DIMS.search(name or '')
    if not m:
        return None
    parts = re.findall(r'(\d+(?:[.,]\d+)?)\s*(мм|mm|см|cm|м|m)?(?=\s*[хxХX*×]|\s|$|[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ])',
                       m.group(0), re.I)
    res, carry = [], 'мм'
    for num, u in reversed(parts):
        carry = (u or carry).lower()
        res.append(float(num.replace(',', '.')) * _UNIT_K[carry])
    return tuple(reversed(res))


def fmt(x: float) -> str:
    """0.45 → «0.45», 600.0 → «600». Крапка, як у довідниках Rozetka."""
    s = f'{x:.4f}'.rstrip('0').rstrip('.')
    return s or '0'


# ── Назва ──────────────────────────────────────────────────────────────────
_PRICE_UNIT = re.compile(r',?\s*(?:ціна|цена)\s+за\s+1\s*шт\.?', re.I)
_MARKERS = re.compile(r'\((?:D|S)\)')
_PUNCT = re.compile(r'[,;:«»„“”‚`´!?…"]+')   # ’ — український апостроф, не пунктуація
_MULTISPACE = re.compile(r'\s+')


# Російські вставки в УКРАЇНСЬКИХ полях постачальника — знайдені заміром
# `uk_lexicon.ru_words` 11.09.2026 (28 назв, 3 описи). Цілими фразами, щоб
# відмінок узгоджувався: «Под коричневую кожу с бронзой» пословно не
# перекладеш. Застосовується лише до `name_ua` і `description_ua`.
UA_FIXES = [
    ('Под коричневую кожу с бронзой', 'Під коричневу шкіру з бронзою'),
    ('Рейка декоративная', 'Рейка декоративна'),
    ('Декоративная ПВХ плита', 'Декоративна ПВХ плита'),
    ('Складной стілець', 'Складаний стілець'),
    ('Самоклеющаяся 3D панель белая мраморная плитка',
     'Самоклеюча 3D панель біла мармурова плитка'),
    ('вініловая', 'вінілова'), ('Вініловая', 'Вінілова'),
    ('Былий', 'Білий'), ('Белый', 'Білий'), ('Кубы', 'Куби'),
    ('нагадуэ', 'нагадує'),
]


def fix_ua(t: str) -> str:
    for a, b in UA_FIXES:
        t = t.replace(a, b)
    return t


# Перший розмір у назві: «700х700х5мм», «60см», «1.22м». «3D» сюди не
# потрапляє — після цифри там літера D, а не «х» чи одиниця.
_FIRST_DIM = re.compile(r'\d+(?:\.\d+)?\s*(?:[хxХX*×]\s*\d|(?:мм|см|м|mm|cm|m)\s*[хxХX*×]|мм\b|см\b|м\b|mm\b|cm\b)')
# «1.45мх 3м» (15.09): одиниця, одразу за нею «х» — без цього бренд вставав посеред розміру
def build_name(raw: str, vendor: str, article: str, kind: str) -> str:
    """Тип → Бренд → Модель/Розмір → Колір → (Артикул) — чекліст модератора, п.7.

    Тип — текст до першого розміру.

    Колір із характеристики постачальника в назву НЕ дописується, хоча 222
    картки мають назви, що відрізняються лише артикулом. Спроба 11.09.2026
    показала, що поле «Колір» ненадійне: російське («Темный дуб», «Жемчужный
    серый») і таке, що суперечить назві («Венге … Темный дуб»). p185
    забороняє лише АБСОЛЮТНО однакові назви, а артикул у дужках їх розрізняє.
    """
    s = _PRICE_UNIT.sub(' ', raw or '')
    s = _MARKERS.sub(' ', s)
    # «4,5мм» → «4.5мм»: кома між цифрами — десятковий знак, і без цього
    # рядка її прибирала пунктуаційна чистка нижче, лишаючи «4 5мм».
    s = re.sub(r'(?<=\d),(?=\d)', '.', s)
    if article:
        s = re.sub(rf'(?<![\w-]){re.escape(article)}(?![\w])', ' ', s)
    if vendor:
        s = re.sub(rf'\b{re.escape(vendor)}\b', ' ', s, flags=re.I)
    s = _PUNCT.sub(' ', s).replace('(', ' ').replace(')', ' ')
    # «світло - фіолетова» → «світло-фіолетова»: тире в назві заборонене
    # чеклістом, а тут це складений колір, розірваний пробілами
    s = re.sub(r'(?<=[а-яіїєґА-ЯІЇЄҐ])\s+[-–—]\s+(?=[а-яіїєґА-ЯІЇЄҐ])', '-', s)
    s = re.sub(r'\s+[–—]\s+', ' ', s)
    s = _MULTISPACE.sub(' ', s).strip(' .-')
    # «3D панель самоклеюча …» → «Панель 3D самоклеюча …»: інакше назва
    # починається з цифри, а префікс типу дав би «Декоративна панель 3D панель».
    s = re.sub(r'^3D\s+(\w)(\w*)', lambda m: f'{m.group(1).upper()}{m.group(2)} 3D', s)
    m = _FIRST_DIM.search(s)
    head, rest = (s[:m.start()].strip(), s[m.start():].strip()) if m else (s, '')
    # Назва з цифри — попередження валідатора («3D панель …», «600х300 …»).
    if not head or head[:1].isdigit():
        head = f'{kind} {head}'.strip()
    name = _MULTISPACE.sub(' ', f'{head} {vendor} {rest}'.strip())
    tail = f' ({article})' if article else ''
    if len(name) + len(tail) > MAX_NAME:
        name = name[:MAX_NAME - len(tail)].rsplit(' ', 1)[0].strip(' -')
    return name + tail


# ── Опис ───────────────────────────────────────────────────────────────────
# Rozetka (#7253098): опис без посилань, реклами, пропозицій інших товарів,
# цін, інформації про компанію, умов оплати й доставки, емодзі.
#
# Шаблон свідомо ВУЖЧИЙ за TOPTUL-овий: тут «доставка» трапляється в 64
# описах у значенні «плиту легко доставити у важкодоступні місця завдяки її
# легкості» — про товар, а не про послугу. Шаблон TOPTUL вирізав би їх усі.
# «Ціна за 1 шт.» — одиниця продажу, її переписуємо, а не видаляємо.
_BANNED_SENT = re.compile(
    r'https?://|www\.|\.com\b|\.ua\b'
    r'|\+?38\s*\(?0\d{2}\)?[\s-]?\d{3}'
    r'|наш(?:ому|ій|ого|а|ий|ем|ем)?\s+(?:інтернет-)?(?:магазин|компані|сайт|склад)'
    r'|\bми\s+використовуємо\b|\bмы\s+используем\b'
    r'|відвантаж|отгрузк'
    r'|\b\d[\d\s]*\s*(?:грн|₴|uah)\b'
    r'|\bцін[аиеою]\w*\b|\bцен[аыуойе]\w*\b|\bвартіст|\bстоимост'
    r'|нова\s+пошта|новая\s+почта|укрпошт|укрпочт|самовивіз|самовывоз'
    r'|післяплат|наложенн\w*\s+платеж|накладен\w+\s+платіж'
    r'|\bоплат\w*|безкоштовн\w+\s+доставк|бесплатн\w+\s+доставк'
    r'|доставк\w*\s+по\s+(?:україні|украине|всій|всей)|термін\w*\s+доставк|срок\w*\s+доставк'
    r'|купують\s+разом|покупают\s+вместе'
    # гарантія як умова продажу, але НЕ дієслово: «що гарантує довгий термін
    # служби» (243 речення) — властивість товару, не обіцянка продавця
    r'|\bгаранті[яїюйе]\b|\bгарантійн|\bгаранти[яийюе]\b|\bгарантийн',
    re.I)
# Емодзі. «‼️» (U+203C + U+FE0F) стоїть у 33 описах перед «Якщо поверхня…».
# Стрілка «→» — НЕ емодзі: вона в розрахунках («= 49,77 → округлюємо»), тому
# її замінюємо тире, а не видаляємо (без неї арифметика читається як обрив).
_EMOJI = re.compile(r'[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF'
                    r'\u203C\u2049\uFE0F]')
_ALLOWED_TAGS = {'p', 'strong', 'b', 'em', 'i', 'ul', 'ol', 'li', 'br', 'h3', 'sup'}
_TAG = re.compile(r'<\s*(/?)\s*([a-zA-Z0-9]+)[^>]*?(/?)\s*>')
_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+')


def clean_description(raw: str, stats: collections.Counter) -> str:
    s = html.unescape(raw or '')
    # вміст службових блоків — геть разом із тегами
    s = re.sub(r'<(style|script|head)\b.*?</\1\s*>', ' ', s, flags=re.I | re.S)
    s = _PRICE_UNIT.sub(', 1 шт.', s)
    s = s.replace('→', '–')
    # Речення про ЛЕГКІСТЬ плити (56) і про рулон, що «зменшує ризик
    # пошкодження під час доставки» (14) — про товар, не про послугу,
    # але містить слово «доставка», на яке реагує модерація. Переформульовуємо
    # точково, зміст той самий.
    s = re.sub(r'Можливість доставки плити у важкодоступні місця',
               'Плиту легко занести у важкодоступні місця', s)
    s = re.sub(r'Возможность доставки плиты в тяжело доступные места',
               'Плиту легко занести в труднодоступные места', s)
    s = s.replace('під час доставки', 'під час перевезення')
    s = s.replace('во время доставки', 'при перевозке')
    # ДПК (13): «формати 30×30 … спрощують доставку порівняно з довгою дошкою»
    s = s.replace('спрощує доставку', 'спрощує перевезення')
    s = s.replace('упрощает доставку', 'упрощает перевозку')
    if _EMOJI.search(s):
        s = _EMOJI.sub('', s)
        stats['опис: прибрано емодзі'] += 1
    out, pos = [], 0
    for m in _TAG.finditer(s):
        out.append(('text', s[pos:m.start()]))
        close, tag = m.group(1), m.group(2).lower()
        if tag in ('h1', 'h2'):
            tag = 'h3'
        if tag in _ALLOWED_TAGS:
            out.append(('tag', '<br>' if tag == 'br' else f'<{close}{tag}>'))
        else:
            out.append(('text', ' '))
        pos = m.end()
    out.append(('text', s[pos:]))
    parts = []
    for kind, val in out:
        if kind == 'tag':
            parts.append(val)
            continue
        keep = []
        for sent in _SENT_SPLIT.split(val):
            if _BANNED_SENT.search(sent):
                stats['опис: прибрано речення'] += 1
                continue
            keep.append(sent)
        parts.append(esc_text(_balance_parens(' '.join(keep))))
    res = ''.join(parts)
    # порожні елементи, що лишились після вирізання речень
    for _ in range(3):
        res = re.sub(r'<(p|strong|b|em|i|li|h3|sup)>\s*(?:<br>\s*)*</\1>', '', res)
        res = re.sub(r'<(ul|ol)>\s*</\1>', '', res)
    res = re.sub(r'(?:<br>\s*){3,}', '<br><br>', res)
    return _MULTISPACE.sub(' ', res).strip()


# Rozetka #7253098 п.1 (15.09.2026): «в описах лише інформація про конкретну
# одиницю товару; в товарах не повинно бути асортименту». І п.3 — невідповідність:
# технічні рядки опису постачальник округлює («152 x 914» при назві 152.4х914.4,
# площа 0,138 проти 0.1393). Розміри й площа є в характеристиках, де рахуються з
# назви, тож у описі ці рядки прибираємо — джерело розбіжностей зникає.
_SPEC = (r'(?:габаритні\s+|габаритные\s+)?(?:розміри(?:\s+в\s+асортименті)?|розмір|размеры(?:\s+в\s+ассортименте)?|размер)'
         r'|вага(?:\s+рулонів)?|вес(?:\s+рулонов)?|площа\s+покриття|площадь\s+покрытия'
         r'|кольори\s+в\s+асортименті|цвета\s+в\s+ассортименте')
_SPEC_LIST = re.compile(rf'<p>\s*(?:<(?:strong|b)>)?\s*(?:{_SPEC})\s*:\s*(?:</(?:strong|b)>)?\s*</p>\s*<(ul|ol)>.*?</\1>',
                        re.I | re.S)
_SPEC_BLOCK = re.compile(rf'<(p|li)>\s*(?:<(?:strong|b)>)?\s*(?:{_SPEC})\s*:.*?</\1>', re.I | re.S)
_ASSORT_CLAUSE = [
    (re.compile(r'\s+у\s+широкому\s+різноманітті\s+кольорів', re.I), ''),
    (re.compile(r'\s+в\s+широком\s+разнообразии\s+цветов', re.I), ''),
    (re.compile(r'\s+(?:і|та)\s+різноманіт\w*\s+кольор\w*(?:\s+(?:та|і)\s+(?:дизайн|візерунк)\w*)?', re.I), ''),
    (re.compile(r'\s+и\s+разнообрази\w*\s+цвет\w*(?:\s+и\s+(?:дизайн|узор)\w*)?', re.I), ''),
]
_ASSORT_SENT = re.compile(
    r'асортимент|ассортимент'
    r'|(?:доступн|представлен|пропону|бува|предлага|быва)\w*\b[^.;]{0,60}?\b(?:різн|різноманітн|разн|различн|разнообразн)\w*\s+'
    r'(?:кольор|розмір|дизайн|варіац|цвет|размер|вариац)'
    r'|комбінувати\s+різні\s+кольори|комбинировать\s+разные\s+цвета'
    r'|різноманітн\w*\s+(?:кольор|дизайн)|разнообрази\w*\s+(?:цвет|дизайн)',
    re.I)


def unit_only_description(desc: str, stats: collections.Counter) -> str:
    """Опис лише про цю одиницю товару: без асортименту й без технічних рядків розміру."""
    n0 = plain_len(desc)
    s = _SPEC_LIST.sub('', desc)
    s = _SPEC_BLOCK.sub('', s)
    if plain_len(s) != n0:
        stats['опис: прибрано рядки розміру/ваги/площі/асортименту'] += 1
    for rx, rep in _ASSORT_CLAUSE:
        s = rx.sub(rep, s)
    out, pos = [], 0
    for m in re.finditer(r'<[^>]+>', s):
        out.append(('text', s[pos:m.start()]))
        out.append(('tag', m.group(0)))
        pos = m.end()
    out.append(('text', s[pos:]))
    parts, cut = [], 0
    for kind, val in out:
        if kind == 'tag':
            parts.append(val)
            continue
        keep = []
        for sent in _SENT_SPLIT.split(val):
            if _ASSORT_SENT.search(sent):
                cut += 1
                continue
            keep.append(sent)
        parts.append(' '.join(keep))
    if cut:
        stats['опис: прибрано речення про асортимент'] += 1
    res = ''.join(parts)
    res = re.sub(r'<li>\s*\d+\.?\s*</li>', '', res)          # «<li>6.</li>» — порожній пункт постачальника
    for _ in range(3):
        res = re.sub(r'<(p|strong|b|em|i|li|h3|sup)>\s*(?:<br>\s*)*</\1>', '', res)
        res = re.sub(r'<(ul|ol)>\s*</\1>', '', res)
    return _MULTISPACE.sub(' ', res).strip()


_DESC_DIM = re.compile(r'\d+(?:[.,]\d+)?\s*(?:мм|mm|см|cm|м|m)?\s*[хxХX*×]\s*\d+(?:[.,]\d+)?'
                       r'(?:\s*(?:мм|mm|см|cm|м|m)?\s*[хxХX*×]\s*\d+(?:[.,]\d+)?)?\s*(?:мм|mm|см|cm|м|m)(?![а-яa-z])', re.I)
_DESC_SKIP = re.compile(r'пакуван|упаков|коробк|площ|розрахун|=|кімнат|квадрат|\bм\d|гвинт|болт|приклад', re.I)


def align_desc_sizes(desc: str, raw_name: str, stats: collections.Counter) -> str:
    """Rozetka #7253098 п.3: розмір у реченні опису («700х700х8мм») має збігатися з
    назвою («700х700х5мм»). Назва — джерело правди: з неї ж рахуються характеристики.
    Лише розміри з явною одиницею (без неї «1,5х2,0» — метри, вгадувати не можна);
    речення про пакування й розрахунки не чіпаємо."""
    nd = name_dims_mm(raw_name)
    if not nd or len(nd) < 2:
        return desc

    def fix_sentence(sent):
        if _DESC_SKIP.search(re.sub(r'<[^>]+>', ' ', sent)):
            return sent

        def rep(m):
            got = name_dims_mm(m.group(0))
            if not got or len(got) < 2 or all(any(abs(x - y) <= max(0.6, 0.02 * y) for y in nd) for x in got):
                return m.group(0)
            if len(got) == 3 and len(nd) == 3:
                new = nd
            else:
                new = [x for x in nd if x in sorted(nd)[-2:]][:2]
            stats['опис: розмір приведено до назви'] += 1
            return 'х'.join(fmt(x) for x in new) + ' мм'
        return _DESC_DIM.sub(rep, sent)
    # межі: кінець речення І кінець абзацу/пункту — заголовок без крапки не злипається з наступним
    return ''.join(fix_sentence(p) for p in re.split(r'((?<=[.!?])\s+|</p>|</li>|<br>)', desc))


def _balance_parens(t: str) -> str:
    """Прибирає «)» без пари: «Декоративна плита ПВХ )» — так у постачальника."""
    depth, out = 0, []
    for ch in t:
        if ch == '(':
            depth += 1
        elif ch == ')':
            if depth == 0:
                continue
            depth -= 1
        out.append(ch)
    return re.sub(r'\s+([.,;:])', r'\1', ''.join(out)).rstrip() + (' ' if t.endswith(' ') else '')


def esc_text(t: str) -> str:
    return t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def plain_len(desc: str) -> int:
    return len(_MULTISPACE.sub(' ', re.sub(r'<[^>]+>', ' ', desc)).strip())


# ── Характеристики ─────────────────────────────────────────────────────────
class Params:
    """Збирач характеристик картки з перевіркою за довідником категорії."""

    def __init__(self, opts: dict, stats: collections.Counter):
        self.opts, self.stats, self.out = opts, stats, collections.OrderedDict()

    def has(self, name: str) -> bool:
        return name in self.opts

    def put(self, name: str, value, numeric: bool = False) -> None:
        if value is None or value == '' or name in self.out:
            return
        value = str(value).strip()
        if name in self.opts and not numeric:
            _, _, vals = self.opts[name]
            if vals and value not in vals:
                self.stats[f'поза довідником: {name}'] += 1
                return
        self.out[name] = [value]

    def put_many(self, name: str, values: list) -> None:
        vals = self.opts.get(name, (None, None, set()))[2]
        ok = [v for v in values if not vals or v in vals]
        for v in values:
            if v not in ok:
                self.stats[f'поза довідником: {name}'] += 1
        if ok and name not in self.out:
            self.out[name] = list(dict.fromkeys(ok))

    def extra(self, name: str, value) -> None:
        """Характеристика поза довідником категорії — для покупця, не фільтр."""
        if value and name not in self.out:
            self.out[name] = [str(value).strip()]


def first_match(text: str, rules: list, ambiguous_skip: bool = True):
    hits = [v for pat, v in rules if re.search(pat, text, re.I)]
    hits = list(dict.fromkeys(hits))
    if not hits or (ambiguous_skip and len(hits) > 1):
        return None
    return hits[0]


COLOR_PARAMS = ('Колір', 'Основний колір', 'Колір рами', 'Колір каркаса',
                'Колір стільниці')

# Колір постачальника → значення довідника. Спершу дослівно без регістру й
# з однаковим апострофом, далі синоніми — і лише ті, що є в довіднику САМЕ
# цієї категорії: «Різнобарвний» є в панелях, але немає в плівках.
COLOR_SYNONYMS = {
    'різні кольори': ('Різнобарвний',), 'різнокольоровий': ('Різнобарвний',),
    'мармуровий': ('Мармур',), 'графіт': ('Графіт', 'Графітовий'),
    'срібний': ('Сріблястий',), 'золотий': ('Золотистий', 'Золотий'),
    'темный дуб': ('Темний дуб',), 'шоколад': ('Шоколадний', 'Шоколад'),
    'кава': ('Кавовий',),
}


def _ckey(v: str) -> str:
    return str(v or '').strip().lower().replace('’', "'")


def color_value(raw, allowed: set):
    if not raw or not allowed:
        return None
    low = {_ckey(v): v for v in allowed}
    if _ckey(raw) in low:
        return low[_ckey(raw)]
    for cand in COLOR_SYNONYMS.get(_ckey(raw), ()):
        if _ckey(cand) in low:
            return low[_ckey(cand)]
    return None


# назва матеріалу постачальника → значення довідника «Декоративних панелей»
DP_MATERIAL = {
    'спінений поліпропілен': 'Поліпропілен', 'пінополіпропілен': 'Поліпропілен',
    'поліпропілен': 'Поліпропілен', 'пвх': 'ПВХ', 'пвх плівка': 'ПВХ',
    'поліуретан': 'Поліуретан',
}

TEXTURE = [(r'цегл|кладк|клінкер', 'Під цеглу'), (r'камін|камен', 'Під камінь'),
           (r'дерев|бамбук|\bдуб|сосн|ясен|горіх|венге|\bтик\b', 'Під дерево'),
           (r'шкір', 'Під шкіру')]

KIND = {DP: 'Декоративна панель', PL: 'Плівка самоклейна', PVC: 'ПВХ покриття',
        KOV: 'Ковролін'}


# Категорії постачальника, яким у спільній категорії Rozetka потрібне інше
# значення «Типу», ніж решті: екошкіра — не плівка, вініловий молдинг 10 см —
# бордюр. Номери з `docs/dropoffice_rozetka_map.tsv`.
SUP_ECO_LEATHER, SUP_VINYL_MOLDING = '95118338', '95118348'


def build_params(cat: str, opts: dict, sp: dict, name: str, raw_name: str,
                 stats: collections.Counter, scid: str = '') -> collections.OrderedDict:
    P = Params(opts, stats)
    n = name.lower()
    P.put('Країна-виробник товару', sp.get('Країна виробник'))

    col = sp.get('Колір')
    for cn in COLOR_PARAMS:
        if P.has(cn):
            P.put(cn, color_value(col, P.opts[cn][2]) or col)
            break

    # розміри: відкидаємо ті, що суперечать повному розміру в назві
    tri = name_triple(raw_name)
    nd = name_dims_mm(raw_name)
    dims = {}
    for k in ('Товщина', 'Ширина', 'Довжина', 'Висота'):
        v = to_mm(sp.get(k))
        if v is None:
            if sp.get(k):
                stats[f'розмір не розібрано: {k}'] += 1
            continue
        if tri and not any(abs(v - t) < 1e-6 for t in tri):
            stats[f'розмір суперечить назві — не виведено: {k}'] += 1
            continue
        # назва з одиницями см/м («0.40х10м», «60*60cm*2cm»): звіряємо теж; товщину —
        # лише коли в назві 3 розміри (у «67см х 10м» товщини немає — не суперечність)
        if not tri and nd and (len(nd) == 3 or k != 'Товщина') \
                and not any(abs(v - t) <= max(0.05, 0.01 * t) for t in nd):
            stats[f'розмір суперечить назві — не виведено: {k}'] += 1
            continue
        dims[k] = v
    T, W, L, H = (dims.get(k) for k in ('Товщина', 'Ширина', 'Довжина', 'Висота'))
    roll = 'рулон' in n

    def num(pname, val, factor=1.0):
        if val is not None and P.has(pname):
            P.put(pname, fmt(val * factor), numeric=True)

    if cat == DP:
        num('Товщина', T); num('Висота', H); num('Довжина', L)
        m = (sp.get('Матеріал') or '').strip().lower()
        m = re.sub(r'\s+', ' ', m)
        mat = DP_MATERIAL.get(m) or first_match(n, [
            (r'\bwpc\b|\bдпк\b', 'ДПК'), (r'алюміні', 'Метал'),
            (r'\bпвх\b', 'ПВХ'), (r'поліуретан', 'Поліуретан')])
        P.put('Матеріал', mat)
        P.put('Вид панелі', first_match(n, [(r'рейк', 'Рейкові')])
              or first_match(n, [(r"м['’]як|велюр", 'М’які')])
              or first_match(n, [(r'мозаїк', 'Мозаїчні')])
              or first_match(n, [(r'3d\s+панел|панел\w*\s+3d', "Об'ємні 3D-панелі")]))
        if re.search(r'самокле', n):
            P.put_many('Особливості', ['Самоклейні'])
        place = [v for pat, v in [(r'стінов|для стін|настінн|на стіну', 'Для стін'),
                                  (r'стел', 'Для стелі')] if re.search(pat, n)]
        if place:
            P.put_many('Місце монтажу', place)
        P.put('Текстура', first_match(n, TEXTURE))
        P.put('Покриття', sp.get('Покриття'))
        num('Кількість в упаковці', to_mm(sp.get('Кількість в упаковці')))

    elif cat == PL:
        num('Ширина рулону', W, 0.1); num('Довжина рулону', L, 0.001)
        num('Товщина', T, 1000)
        if scid == SUP_VINYL_MOLDING:
            P.put('Тип', 'Бордюр')
        elif scid != SUP_ECO_LEATHER:
            P.put('Тип', 'Плівка')
        P.put('Поверхня', first_match(n, [(r'глянц', 'Глянцеві'),
                                          (r'\bмат\b|матов', 'Матові'),
                                          (r'дзеркал', 'Дзеркальні')]))

    elif cat == PVC:
        num('Ширина покриття', W, 0.001); num('Товщина покриття', T)
        if re.search(r'самокле', n):
            P.put('Основа', 'Клейова')
        P.put('Призначення', 'Для підлоги')   # сюди мапляться лише підлогові
        P.put('Малюнок', first_match(n, [(r'дерев|\bдуб|сосн|ясен|горіх|ламінат', 'Під дерево'),
                                         (r'мармур', 'Під мармур'), (r'бетон', 'Під бетон')]))
        if not roll and W and L:
            P.put('Форма нарізання', 'Квадрат' if abs(W - L) < 1e-6 else 'Прямокутник')
        if _PRICE_UNIT.search(raw_name):
            P.put('Одиниця продажу', '1 шт')
        num('Кількість в упаковці', to_mm(sp.get('Кількість в упаковці')))

    elif cat == KOV:
        P.put('Вид', 'Рулон' if roll else 'Плитка')
        P.put('Тип', 'Ковролін')
        num('Товщина покриття', T); num('Ширина покриття', W, 0.001)

    elif cat == '4646656':          # Гумові покриття — підлога-пазл
        num('Товщина покриття', T); num('Ширина покриття', W, 0.001)
        P.put('Форма', 'Рулон' if roll else 'Плитка')
        # EVA лише там, де його назвав постачальник: плюшеві пазли — не EVA
        if (sp.get('Матеріал') or '').strip().upper() == 'EVA':
            P.put_many('Матеріал', ['EVA'])

    elif cat == '4640984':          # Комплектуючі для оздоблення — молдинги
        # «Вид» тут — профілі для гіпсокартону (CD/CW/UD), молдингу не пасує;
        # розміри категорія не має, тож лише для покупця
        for label, val in (('Довжина, мм', L), ('Ширина, мм', W), ('Товщина, мм', T)):
            if val:
                P.extra(label, fmt(val))

    elif cat == '4659010':          # Плитка для вулиці — терасна плитка ДПК
        num('Товщина', T); num('Довжина', L); num('Ширина', W)
        if W and L:
            P.put('Форма плитки', 'Квадратна' if abs(W - L) < 1e-6 else 'Прямокутна')

    elif cat == '4660237':          # Плитка мозаїка — «Мозаїка з декоративного скла»
        P.put('Матеріал', 'Скло')

    elif cat == '4647678':          # Плівки на вікна
        num('Ширина', W); num('Товщина', T, 1000)
        # у віконних плівках постачальник пише ТИП у поле «Колір»: «Матовий»
        if (sp.get('Колір') or '').strip().lower() == 'матовий':
            P.put_many('Тип плівки', ['Матові'])

    elif cat == '4640952':          # Плінтуси
        num('Довжина', L, 0.001)
        P.put_many('Особливості', [v for pat, v in [(r'гнучк', 'Гнучкий'),
                                                    (r'самокле', 'Клейкий')]
                                   if re.search(pat, n)])

    elif cat == '4657848':          # Вінілові шпалери (самоклейні на XPE)
        num('Ширина рулону', W, 0.1); num('Довжина рулону', L, 0.001)
        feats = []
        if re.search(r'самокле', n):
            feats.append('Самоклейні')
        if 'xpe' in (sp.get('Основа шпалер') or '').lower():
            feats.append('Спінені')
        P.put_many('Особливість', feats)

    elif cat == '142254':           # Килими — вологопоглинаючі килимки
        if re.search(r'вологопоглин', n):
            P.put('Вид', 'Килимки для ванної')
        feats = {'вологопоглинаючий': 'Вологовсмоктуючі',
                 'безворсовий': 'Безворсові'}
        f = feats.get((sp.get('Вид килима') or '').strip().lower())
        if f:
            P.put_many('Особливості', [f])
        P.put('Форма', first_match(n, [(r'оваль', 'Овальна'), (r'кругл', 'Кругла')]))
        for pname, val in (('Ширина', W), ('Довжина', L)):
            if val is None:
                continue
            b = rug_bucket(pname, val / 1000)
            if b:
                P.put(pname, b)

    elif cat == '4630668':          # Дзеркала — акрилові самоклейні
        P.put('Тип', 'Настінні')
        P.put_many('Особливості', ['Без рами/багета'])
        num('Ширина', W, 0.1); num('Висота', H or L, 0.1)

    elif cat == '4640928':          # Наклейки на стіну — дзеркальні фігурні
        if re.search(r'самокле', n):
            P.put('Основа', 'Клейова')
        if re.search(r'акрил', n) or (sp.get('Матеріал') or '').strip() == 'Акрил':
            P.put('Матеріал', 'Акрил')

    elif cat == '4652744':          # Етажерки
        tiers = first_match(n, [(r'тр[иь]\w*ярус|трехъярус|3-ярус', '3'),
                                (r'чотири\w*ярус|четырехъярус|4-ярус', '4')])
        if tiers:
            P.put('Кількість полиць', tiers, numeric=True)
        P.put('Матеріал основи', first_match(n, [(r'метал|нержав', 'Метал'),
                                                 (r'пластик', 'Пластик')]))

    elif cat == '4652702':          # Контейнери
        P.put('Тип', 'Один предмет')

    elif cat == '83646':            # Надувні меблі
        P.put('Вид', first_match(n, [(r'крісл', 'Крісла'), (r'диван', 'Дивани'),
                                     (r'пуф', 'Пуфи'), (r'ліжк', 'Ліжка'),
                                     (r'матрац', 'Матраци')]))

    elif cat == '3130405':          # Садові меблі
        P.put('Тип', first_match(n, [(r'стіл(?!ець)|столик', 'Стіл'), (r'стілець|стул', 'Стілець'),
                                     (r'крісл', 'Крісло'), (r'табурет', 'Табурет')]))

    elif cat == '4629178':          # Стелажі
        P.put('Вид', 'Стелажі')
        if re.search(r'метал|нержав', n):
            P.put('Матеріал каркаса', 'Метал')

    elif cat == '2798167':          # Журнальні столи
        if re.search(r'журнальн', n):
            P.put('Тип', 'Журнальний стіл')
        P.put('Форма', first_match(n, [(r'оваль', 'Овальна'), (r'кругл', 'Кругла'),
                                       (r'трикутн', 'Трикутна (сектор)')]))

    elif cat == '4674142':          # Ігрові килимки
        P.put('Тип', 'Розвивальні' if re.search(r'розвива', n) else None)
        P.put_many('Особливості', [v for pat, v in [(r'термо', 'Термокилимки'),
                                                    (r'двосторон', 'Двосторонні')]
                                   if re.search(pat, n)])

    elif cat == '267137':           # Речі для догляду — дитячий манікюрний набір
        P.put('Тип', 'Манікюрне приладдя')

    # для покупця, не фільтр: повний розмір і площа, як у постачальника
    # Якщо «Розміру» немає, складаємо його з розмірів, які вже пройшли звірку
    # з назвою: нових чисел тут не з'являється, лише інший запис тих самих.
    # Rozetka #7253098 п.3 (15.09): «Розмір» постачальника («914,4*152,5*1,5мм»)
    # і його площа (0.084 при назві 275х285 = 0.0784) розходились із назвою.
    # Коли в назві є повний розмір — і «Розмір», і площа рахуються з неї.
    m3 = _TRIPLE.search(raw_name or '')
    if m3:
        size = 'х'.join(fmt(float(m3.group(i).replace(',', '.'))) for i in (1, 2, 3)) + ' мм'
    elif nd:                          # «0.40х10м» → «400х10000 мм», без чисел постачальника
        size = 'х'.join(fmt(x) for x in nd) + ' мм'
    else:
        size = sp.get('Розмір')
        if not size and W and L:
            # довжина першою — так пишуть назви постачальника («3000х12х4мм»)
            size = 'х'.join(fmt(x) for x in (L, W, T) if x) + ' мм'
    P.extra('Розмір', size)
    area = sp.get('Площа, що покривається панеллю')
    if area:
        if nd and len(nd) >= 2:      # не множина tri: у 680х680х4 дві сторони однакові
            a, b = sorted(nd)[-2:]
            area = fmt(round(a * b / 1e6, 4))
        P.extra('Площа покриття однією одиницею, м²', area.replace(',', '.'))
    return P.out


_UNIT_NORM = {'микрон': 'мкм', 'мк': 'мкм'}
_BARE_NUM = re.compile(r'^\d+(?:[.,]\d+)?$')


def with_unit(name: str, value: str, opts: dict) -> str:
    """Rozetka #7253098 п.2 (15.09): «не вказані одиниці виміру в частині параметрів».
    Число без одиниці → число + одиниця з довідника категорії Rozetka (у ній число
    й пораховане в build_params). Назви з одиницею («Довжина, мм», «…, м²») — як є."""
    unit = (opts.get(name) or (None, None, None))[1]
    if not unit or not _BARE_NUM.match(value or '') or re.search(r',\s*\S+$', name):
        return value
    return f'{value} {_UNIT_NORM.get(unit, unit)}'


# Довідник «Килимів» дає ширину й довжину діапазонами в метрах, і між ними є
# проміжки (0.45–0.5). Значення, що впало в проміжок, не виводимо.
RUG_BUCKETS = {
    'Ширина': [(0, 0.3, 'до 0.3'), (0.3, 0.45, '0.3 - 0.45'), (0.5, 0.8, '0.5 - 0.8'),
               (0.9, 1.2, '0.9 - 1.2'), (1.3, 1.5, '1.3 - 1.5'), (1.6, 1.8, '1.6 - 1.8'),
               (1.9, 2.3, '1.9 - 2.3'), (2.4, 2.6, '2.4 - 2.6')],
    'Довжина': [(0, 0.5, 'до 0.5'), (0.5, 1.0, '0.5 - 1'), (1.1, 1.5, '1.1 - 1.5'),
                (1.6, 2.0, '1.6 - 2'), (2.1, 2.5, '2.1 - 2.5'), (2.6, 3.0, '2.6 - 3'),
                (3.1, 3.5, '3.1 - 3.5'), (3.6, 4.0, '3.6 - 4')],
}


def rug_bucket(pname: str, metres: float):
    for lo, hi, label in RUG_BUCKETS[pname]:
        if (lo < metres <= hi) or (lo == 0 and metres <= hi):
            return label
    return None


# ── Фото ───────────────────────────────────────────────────────────────────
def pictures(offer, mode: str, stats) -> list:
    kept, seen = [], set()
    for el in offer.findall('picture'):
        url = re.sub(r'^http://', 'https://', (el.text or '').strip())
        if not url.lower().startswith('https://') or CYRILLIC.search(url):
            stats['фото: відкинуто URL'] += 1
            continue
        if url in seen:
            continue
        seen.add(url)
        kept.append(url)
    want = PHOTO_OVERRIDE.get(offer.get('id'))
    if want:
        want = re.sub(r'^http://', 'https://', want)
        if want in kept:
            stats['фото: замінено перше (колаж/інтер’єр/текст)'] += 1
            kept = [want] + [u for u in kept if u != want]
        else:
            stats['фото: заміну не знайдено в джерелі'] += 1
    if mode == 'first':
        return kept[:1]
    return kept[:MAX_PICTURES]


# ── Генерація ──────────────────────────────────────────────────────────────
_MARKDOWN = re.compile(r'уц[іе]нк|уценен|розпродаж|распродаж', re.I)


def generate(out_file: str, photo_mode: str) -> None:
    out_file = _safe_output(out_file)
    good, bad = load_map()
    options = load_options()
    shop = ET.parse(CACHE).getroot().find('shop')
    offers = shop.find('offers').findall('offer')
    stats = collections.Counter()
    drops = []
    used_cats = collections.OrderedDict()
    body = []
    param_hist = collections.Counter()
    n_params = []

    for o in offers:
        sp = {}
        for p in o.findall('param'):
            k = (p.get('name') or '').strip()
            if k and k not in sp:
                sp[k] = (p.text or '').strip()
        article = sp.get('Артикул', '').strip()
        raw_ua = (o.findtext('name_ua') or '').strip()
        raw_ru = (o.findtext('name') or '').strip()
        vendor = (o.findtext('vendor') or '').strip()
        cid = (o.findtext('categoryId') or '').strip()

        def drop(reason):
            drops.append((article, reason, raw_ua))
            stats[f'відсіяно: {reason}'] += 1

        if _MARKDOWN.search(raw_ua) or _MARKDOWN.search(raw_ru):
            drop('уцінка/розпродаж — розділ «Знижені в ціні»')
            continue
        if cid not in good:
            tier = bad.get(cid, ('немає в мапі',))[0]
            drop(f'категорія на рішенні власника ({tier})')
            continue
        if not vendor:
            drop('без бренду')
            continue
        if not article:
            drop('без артикула')
            continue
        if photo_mode == 'first' and article in BAD_FIRST_PHOTO:
            drop('перше фото — інфографіка')
            continue
        if o.get('id') in PHOTO_EXCLUDE:
            drop('немає фото лише з товаром (Rozetka п.4)')
            continue
        try:
            price = float((o.findtext('price') or '0').replace(',', '.'))
        except ValueError:
            price = 0.0
        if price <= 0:
            drop('без ціни')
            continue
        pics = pictures(o, photo_mode, stats)
        if not pics:
            drop('без фото')
            continue

        rz, rz_name = good[cid]
        opts = options.get(rz)
        if opts is None:
            drop(f'немає довідника характеристик для {rz}')
            continue
        kind = KIND.get(rz, rz_name)
        name_ua = build_name(fix_ua(raw_ua), vendor, article, kind)
        name_ru = build_name(raw_ru or raw_ua, vendor, article, kind)

        desc_ua = align_desc_sizes(unit_only_description(
            clean_description(fix_ua(o.findtext('description_ua') or ''), stats), stats), raw_ua, stats)
        desc_ru = align_desc_sizes(unit_only_description(
            clean_description(o.findtext('description') or '', stats), stats), raw_ua, stats)
        if plain_len(desc_ua) < 50:
            drop('опис порожній після чистки')
            continue
        if plain_len(desc_ru) < 50:
            desc_ru = desc_ua
            stats['опис ru замінено українським'] += 1

        prm = build_params(rz, opts, sp, name_ua, raw_ua, stats, cid)
        if len(prm) < MIN_PARAMS:
            drop(f'характеристик {len(prm)} < {MIN_PARAMS}')
            continue
        for k in prm:
            param_hist[(rz, k)] += 1
        n_params.append(len(prm))

        avail = (o.get('available') or 'true').strip().lower() != 'false'
        try:
            qty = int(float(o.findtext('stock_quantity') or 0))
        except ValueError:
            qty = 0
        stock = qty if avail and qty > 0 else (1 if avail else 0)

        if rz not in used_cats:
            used_cats[rz] = (len(used_cats) + 1, rz_name)
        lines = [f'      <offer id="{esc(o.get("id"))}" available="{"true" if avail else "false"}">',
                 f'        <price>{price_rules.price_for(price, markup_for(rz, article))}</price>',
                 '        <currencyId>UAH</currencyId>',
                 f'        <categoryId>{used_cats[rz][0]}</categoryId>']
        lines += [f'        <picture>{esc(u)}</picture>' for u in pics]
        lines += [f'        <vendor>{esc(vendor)}</vendor>',
                  f'        <article>{esc(article)}</article>',
                  f'        <stock_quantity>{stock}</stock_quantity>',
                  f'        <name>{esc(name_ru)}</name>',
                  f'        <name_ua>{esc(name_ua)}</name_ua>',
                  f'        <description>{cdata(desc_ru)}</description>',
                  f'        <description_ua>{cdata(desc_ua)}</description_ua>']
        for k, vals in prm.items():
            v = with_unit(k, vals[0], opts) if len(vals) == 1 else cdata('<br>'.join(vals))
            if len(vals) == 1 and v != vals[0]:
                stats['характеристика: додано одиницю'] += 1
            lines.append(f'        <param name="{esc(k)}">{v if len(vals) > 1 else esc(v)}</param>')
        lines.append('      </offer>')
        body += lines
        stats['у фіді'] += 1
        stats['у фіді: в наявності' if avail else 'у фіді: немає в наявності'] += 1

    head = ['<?xml version="1.0" encoding="UTF-8"?>',
            f'<yml_catalog date="{datetime.now():%Y-%m-%d %H:%M}">',
            '  <shop>',
            f'    <name>{esc(SHOP_NAME)}</name>',
            f'    <company>{esc(SHOP_COMPANY)}</company>',
            f'    <url>{esc(SHOP_URL)}</url>',
            '    <currencies><currency id="UAH" rate="1" /></currencies>',
            '    <categories>']
    head += [f'      <category id="{i}" rz_id="{rz}">{esc(nm)}</category>'
             for rz, (i, nm) in used_cats.items()]
    head += ['    </categories>', '    <offers>']
    tail = ['    </offers>', '  </shop>', '</yml_catalog>', '']
    tmp = out_file + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('\n'.join(head + body + tail))
    ET.parse(tmp)            # невалідний XML не має замінити робочий файл
    os.replace(tmp, out_file)

    with open(DROPS, 'w', encoding='utf-8') as f:
        f.write('article\treason\tname_ua\n')
        for a, r, nm in sorted(drops, key=lambda x: (x[1], x[0])):
            f.write(f'{a}\t{r}\t{nm}\n')

    print(f'\n→ {out_file}')
    print(f'офферів у джерелі: {len(offers)} · у фіді: {stats["у фіді"]} '
          f'(в наявності {stats["у фіді: в наявності"]}) · категорій: {len(used_cats)}')
    print(f'фото: режим «{photo_mode}» · характеристик на картку: '
          f'мін {min(n_params)} медіана {sorted(n_params)[len(n_params) // 2]} макс {max(n_params)}')
    print('\nлічильники:')
    for k, v in sorted(stats.items()):
        if not k.startswith('у фіді'):
            print(f'  {v:6}  {k}')
    print(f'\nвідсіяні з причинами → {DROPS}')
    return param_hist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--output', default=OUT)
    ap.add_argument('--fetch', action='store_true', help='спершу завантажити свіжий фід')
    ap.add_argument('--photos', choices=('first', 'all'), default='first')
    ap.add_argument('--param-report', action='store_true')
    a = ap.parse_args()
    if a.fetch or not os.path.exists(CACHE):
        fetch_source()
    hist = generate(a.output, a.photos)
    if a.param_report:
        print('\nзаповненість характеристик за категоріями:')
        for (rz, k), v in sorted(hist.items()):
            print(f'  {rz:>8}  {v:5}  {k}')


if __name__ == '__main__':
    main()
