#!/usr/bin/env python3
"""TOPTUL → XML прайс-лист для Rozetka Маркетплейс.

Окремий файл, окремий генератор, окремий запис у crontab. Магазин той самий,
що й у NOIRE, але фід ІНШИЙ: `output/toptul_rozetka.xml`. Чинний
`output/noire_rozetka.xml` цей інструмент не має права торкнутись — там 4147
позицій на модерації (заявки 4469692/4469693 від 17.08.2026), і будь-яка
зміна файлу під ними означала б зняття карток із продажу. Заборона не на
словах: `_safe_output()` відмовляється писати у файл із префіксом `noire`.

Джерело — фід постачальника `/tmp/toptul.xml` (6895 офферів). На відміну від
Carvol, наявність тут позначена чесно: 5689 `true` / 1206 `false`, тож
`available` беремо з фіду, а не вигадуємо.

Вимоги Rozetka, вивчені на NOIRE (кожна коштувала окремого листа модератора):
  * назва — Тип · Бренд · Модель · (Артикул), без ком і без пунктуації поза
    дужками артикула;
  * `<description>` ОБОВʼЯЗКОВИЙ, `<description_ua>` теж (p185, ред. 29.06.2026);
  * фото лише https, без повторів URL у межах картки;
  * `stock_quantity` 0 при `available="false"` — норма, а не помилка;
  * багатозначна характеристика — ОДИН тег `<param>` зі значеннями через
    `<br>` у CDATA. Два теги з тим самим іменем валідатор рахує дублем:
    саме так виникли 1403 попередження у звіті від 15.08.2026;
  * категорія — `rz_id` із `toptul_rozetka_category_map`, і лише з рівнів,
    де відповідність або поставлена руками, або підтверджена двома методами.

Запуск:
    python3 tools/toptul_rozetka_generator.py --fields      # інвентаризація
    python3 tools/toptul_rozetka_generator.py --limit 50
    python3 tools/toptul_rozetka_generator.py -o output/toptul_rozetka.xml
"""
import argparse
import collections
import html
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from loguru import logger  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402
# Ознака російської береться з перекладача, а не пишеться тут удруге. Два
# власні визначення «російського» неминуче розійшлись би, і тоді перевірка
# «скільки лишилось російського» міряла б не те, що виправляв перекладач.
# `unknown_words` — кошик слів поза обома словниками. Він друкується поруч із
# нулем свідомо: 25.08.2026 самоперевірка звітувала «російською: 0», тоді як у
# фіді лежало 1189 вживань російських назв характеристик, і саме відсутність
# третього числа не дала цього побачити.
from toptul_translate import RU, unknown_words, lexicon_sizes  # noqa: E402
# `ru_words` — та сама ознака, що за `RU`, але переліком слів: для описів
# потрібне не «є/немає», а скільки й яких, щоб число збігалося з незалежним
# `toptul_ru_audit.py`. Збіг двох чисел і є доказ, що замір не бреше.
from uk_lexicon import ru_words  # noqa: E402
# Словник хибних УКРАЇНСЬКИХ форм — той самий файл і той самий код, що в
# перекладачі описів (`data/toptul_uk_fixes.tsv`). Імпорт, а не друга копія:
# два переліки розійшлись би, і аудит перекладача звітував би нуль, доки у
# фіді лежать ті самі форми. Ознака мови їх не бачить за побудовою —
# «відвертка» і «слесарний» написані українськими літерами, тож `ru_words`
# на них мовчить, а замір показує чистий фід.
from toptul_desc_translate import load_fixes, apply_fixes, bad_forms  # noqa: E402
from toptul_ru_audit import strip_article, strip_vendor  # noqa: E402
# Дві фільтрові характеристики, яких постачальник не дає окремим полем
# («Розмір посадкового квадрата», «Кількість граней») — зауваження Rozetka
# #7253098 п.3. Модуль окремий, бо його правила треба перевіряти без БД,
# мережі й фіду: `toptul_filter_extract.py --selftest`.
from toptul_filter_extract import extract as extract_filters  # noqa: E402
from toptul_filter_extract import load_reference  # noqa: E402
# Мішане написання: `дoзвoляє` з латинськими `o`, `cили` з латинською `c`.
# Виправляється ПЕРЕД перекладом і перед будь-яким заміром, бо інакше кожна
# наступна перевірка міряє не те слово, що бачить око: пошук Rozetka такого
# тексту не знаходить, а `ru_words` у кириличному залишку `cили` бачить
# російське `или` — саме звідти останні 6 «російських вживань» 01.09.2026.
from homoglyph import fix_text as fix_homoglyphs  # noqa: E402
from homoglyph import leftovers as homoglyph_leftovers  # noqa: E402

FEED = os.getenv('TOPTUL_FEED_FILE', '/tmp/toptul.xml')
OUT = os.path.join(BASE_DIR, 'output', 'toptul_rozetka.xml')

SHOP_NAME = 'klatch1 shop'
SHOP_COMPANY = '3721108'
SHOP_URL = 'https://cs4053918.prom.ua/'

# Ціна постачальника — це РРЦ. Рішення власника від 11.08.2026 для цього
# магазину: комісію майданчика несе бізнес, а не покупець, тож множник 1.0.
# Формула з гросапом на комісію (CLAUDE.md, «Формули ціноутворення») лишається
# доступною через --commission, але вмикається свідомо: змінити політику цін
# «за замовчуванням» — не рішення генератора.
MARKUP = float(os.getenv('TOPTUL_MARKUP_ROZETKA', '1.0'))
DEFAULT_COMMISSION = float(os.getenv('TOPTUL_RZ_COMMISSION', '12.0'))

# Рівні відповідності категорій, яким довіряємо. `review` і `none` сюди не
# входять свідомо: хибна категорія гірша за відсутню — товар лягає туди, де
# його не шукають, і фільтри до нього не застосовуються (SKILL-04).
ALLOWED_TIERS = ('manual', 'auto', 'validated', 'validated-2models')

MIN_PARAMS = 3          # вимога Rozetka; нижче — попередження валідатора
# 150, а не 255. 255 — межа, за якою валідатор дає ПОМИЛКУ, 150 — за якою
# він дає попередження. Ціль прогону з черги — нуль і того, і того.
MAX_NAME = 150
MAX_PICTURES = 15
MAX_PARAM_LEN = 500
CYRILLIC = re.compile(r'[а-яА-ЯіІєЄїЇґҐёЁ]')

# Характеристики, значення яких — власні назви. Їх не перекладають, тож і в
# замір «скільки лишилось російського» вони не входять (див. нижче).
BRAND_PARAMS = ('Бренд', 'Виробник', 'Країна-виробник', 'Модель')


def esc(t) -> str:
    return html.escape(str(t) if t is not None else '', quote=True)


def cdata(t: str) -> str:
    """Багатозначний параметр Rozetka: значення через <br> усередині CDATA."""
    return '<![CDATA[' + (t or '').replace(']]>', ']]&gt;') + ']]>'


def _safe_output(path: str) -> str:
    """Не дати згенерувати поверх чинного фіду NOIRE.

    Правило автономного запуску №2: NOIRE не чіпати. Помилка тут не
    виправляється — cron підхопить файл і зніме з продажу 4147 позицій, які
    зараз на модерації. Тому перевірка не в інструкції, а в коді.
    """
    full = os.path.abspath(path)
    if os.path.basename(full).lower().startswith('noire'):
        sys.exit(f'ВІДМОВА: {full} — це фід NOIRE, писати в нього заборонено')
    return full


# ── Крок 1 правила позитивного контролю: які теги у фіді НАСПРАВДІ є ────────
# Різні майданчики й різні вивантаження називають те саме по-різному
# (`name`/`name_ua`, `description`/`description_ua`, `vendorCode`/`article`).
# Запит із неправильною назвою дає нуль, не помиляючись, — і саме так
# 15.08.2026 перевірка описів «не знайшла нічого» в порожньому тезі.
# Тому теги не вгадуються: беремо перший кандидат, у якого в цьому файлі
# справді є непорожні значення, і друкуємо заміри по ВСІХ кандидатах.
FIELD_CANDIDATES = {
    'name':    ('name_ua', 'name'),
    'desc':    ('description_ua', 'description'),
    'vendor':  ('vendor', 'brand', 'manufacturer'),
    'article': ('vendorCode', 'article', 'model'),
    'price':   ('price', 'price_promo'),
    'qty':     ('stock_quantity', 'quantity', 'stock'),
    'cat':     ('categoryId',),
}


def resolve_fields(offers: list) -> dict:
    """{роль: реальний тег}. Друкує заміри по кожному кандидату."""
    resolved, report = {}, []
    for role, cands in FIELD_CANDIDATES.items():
        counts = [(t, sum(1 for o in offers if (o.findtext(t) or '').strip()))
                  for t in cands]
        pick = next((t for t, n in counts if n), None)
        resolved[role] = pick
        report.append((role, pick, counts))
    logger.info('Теги фіду (роль → тег: непорожніх офферів):')
    for role, pick, counts in report:
        body = ', '.join(f'{t}={n}' for t, n in counts)
        mark = pick or 'НЕМАЄ ЖОДНОГО'
        logger.info(f'   {role:8} → {mark:16} [{body}]')
    return resolved


def _txt(offer, tag, default=''):
    if not tag:
        return default
    return (offer.findtext(tag) or default).strip()


# ── Назва товару ───────────────────────────────────────────────────────────
# Відділ адаптації (лист 10.08.2026): порядок Тип - Виробник - Модель -
# Артикул у дужках, коми не ставляться, виробник у назві мусить збігатися
# з <vendor>. Назви TOPTUL цього не тримають: там повне речення з комами
# («Ключ накидной силовой односторонний, 41 мм»). Текст не переписуємо —
# прибираємо пунктуацію й дописуємо бренд та артикул.
#
# Дюймова позначка — виняток. У назвах ключів і головок `1/2"` це одиниця
# виміру, а не лапка: прибрати її означало б зіпсувати змістовну частину.
# Тому лапка знімається лише там, де перед нею не цифра й не дріб.
_PUNCT = re.compile(r'[,;:«»„“”‚’`´!?…]+')
_STRAY_QUOTE = re.compile(r'(?<![\d/])"')
_MULTISPACE = re.compile(r'\s+')


def clean_name_text(s: str) -> str:
    s = _PUNCT.sub(' ', s or '')
    s = _STRAY_QUOTE.sub(' ', s)
    s = s.replace('(', ' ').replace(')', ' ')   # дужки лишає тільки артикул
    s = _MULTISPACE.sub(' ', s).strip(' .-')
    return s


def build_name(raw: str, vendor: str, article: str, kind: str) -> str:
    """Тип · Бренд · Модель · (Артикул) — без ком і зайвої пунктуації."""
    head = clean_name_text(raw)
    # Бренд і артикул можуть уже стояти в назві постачальника; повторювати
    # їх не треба — Rozetka показує дубль як неохайність.
    # Шукаємо і сиру форму, і форму без мішаного написання. Артикул у тезі
    # `<article>` лишається дослівно постачальницьким («артикули не
    # змінились»), а в тексті назви мішане написання вже зняте — тобто
    # `GIZMATIС3045` з тега й `GIZMATIC3045` у назві більше не рівні рядки.
    # Порівняння лише за сирою формою давало артикул ДВІЧІ: «…клапана
    # GIZMATIC3045 ХЗСО (GIZMATIС3045)».
    for v in {vendor, fix_homoglyphs(vendor)[0]} if vendor else ():
        head = re.sub(rf'\b{re.escape(v)}\b', ' ', head, flags=re.I)
    for a in {article, fix_homoglyphs(article)[0]} if article else ():
        head = re.sub(rf'\b{re.escape(a)}\b', ' ', head, flags=re.I)
    head = _MULTISPACE.sub(' ', head).strip()
    # Назва, що починається з цифри, — попередження валідатора. У фіді TOPTUL
    # так починаються розмірні позиції («10 мм торцева головка»); ставимо
    # попереду тип із категорії Rozetka, а не викидаємо товар.
    if head and head[0].isdigit() and kind:
        head = f'{kind} {head}'
    parts = [p for p in (head or kind, vendor) if p]
    name = _MULTISPACE.sub(' ', ' '.join(parts)).strip()
    tail = f' ({article})' if article else ''
    if len(name) + len(tail) > MAX_NAME:
        name = name[:MAX_NAME - len(tail)].rsplit(' ', 1)[0].strip(' -')
    return name + tail


# ── Опис ───────────────────────────────────────────────────────────────────
# Опис не має містити інформації про доставку й оплату (sellerhelp p212,
# ред. 12.06.2026). Прибираємо реченнями, а не словами: обрізок речення
# читається гірше, ніж його відсутність.
_DELIVERY = re.compile(
    r'[^.!?]*\b(доставк\w*|оплат\w*|способи оплати|самовивіз\w*)\b[^.!?]*[.!?]\s*',
    re.I)
_TAGS = re.compile(r'<[^>]+>')


def plain(desc: str) -> str:
    return _MULTISPACE.sub(' ', _TAGS.sub(' ', desc or '')).strip()



# ── Заборонений вміст опису (зауваження Rozetka #7253098 від 24.08.2026) ──
# «Опис не повинен містити посилання, рекламу, пропозиції інших товарів, ціни,
#  інформацію про компанію, точки видачі, адреси, імена, номери телефонів,
#  умови оформлення замовлення, про доставку/оплату, стоп-слова, емодзі.»
#
# Речення з таким вмістом ВИДАЛЯЄМО цілком: вирізати лише посилання означало б
# лишити «дивіться відео за посиланням:» без посилання.
_EMOJI = re.compile(r'[\U0001F300-\U0001FAFF\u2190-\u21FF\u2300-\u27BF\uFE0F]')
_BANNED_SENT = re.compile(
    r'https?://|www\.|youtu\.?be|\.com\b|\.ua\b'                 # посилання
    r'|наш(?:ому|ій|ого|а|ий)\s+(?:інтернет-)?(?:магазин|компані)'   # про компанію
    r'|\b\d[\d\s]{2,}\s*(?:грн|₴|uah)\b'                          # ціни
    r'|\+?38\s*\(?0\d{2}\)?[\s-]?\d{3}'                          # телефони
    r'|нова\s+пошта|укрпошт|накладен\w+\s+платіж'                   # доставка
    r'|\bдостав(?:ка|ки|ку|кою)\b|\bоплат(?:а|и|у|ою)\b',          # оплата
    re.I)


def clean_description(text: str) -> tuple:
    """Прибирає заборонений вміст. Повертає (чистий текст, що саме прибрано)."""
    removed = []
    if _EMOJI.search(text):
        text = _EMOJI.sub('', text)
        removed.append('емодзі')
    # ділимо на речення й відкидаємо ті, де є заборонене
    parts = re.split(r'(?<=[.!?])\s+', text)
    keep = []
    for sent in parts:
        if _BANNED_SENT.search(sent):
            removed.append('речення')
            continue
        keep.append(sent)
    out = ' '.join(keep)
    return re.sub(r'\s{2,}', ' ', out).strip(), removed


# ── Країна-виробник ────────────────────────────────────────────────────────
# Зауваження менеджера Rozetka (#7253098): «Країна-виробник товару» — фільтр
# категорії, а бракувало його в 4766 товарах із 5512. У фіді постачальника
# країни немає взагалі, тому виводимо з бренду.
#
# TOPTUL — Тайвань, не Китай: Rotar Machinery Industrial Co., Тайчжун,
# власне виробництво з 1981 р. (перевірено 24.08.2026). Це 3274 товари, і
# помилка тут була б помітною — країна виробника легко перевіряється.
BRAND_COUNTRY = {
    'toptul': 'Тайвань',
}
DEFAULT_COUNTRY = 'Китай'   # рішення власника 24.08.2026 для решти брендів


def country_for(vendor: str) -> str:
    return BRAND_COUNTRY.get((vendor or '').strip().lower(), DEFAULT_COUNTRY)

def synth_description(name: str, prm: dict, vendor: str, article: str) -> str:
    """Резервний опис із того, що вже підтверджено характеристиками.

    Нічого не додумується й немає оцінних слів: інакше опис розходився б із
    карткою, а це рівно те зауваження, за яке нас уже правили по обʼєму.
    """
    out = [f'{name}.']
    facts = [f'{k} — {v}' for k, v in list(prm.items())[:6]]
    if facts:
        out.append('Характеристики: ' + '; '.join(facts) + '.')
    if vendor:
        out.append(f'Виробник — {vendor}.')
    if article:
        out.append(f'Артикул виробника — {article}.')
    return ' '.join(out)


# ── Довідники з бази ───────────────────────────────────────────────────────

def load_categories(cur) -> tuple:
    """(довірені, відхилені).

    Довірені — `toptul_id → (rz_id, rz_name)` з рівнів `ALLOWED_TIERS`.
    Відхилені — `toptul_id → (tier, rz_id, toptul_name)` для решти рядків
    таблиці. Другий словник потрібен не генератору, а ЗВІТУ: без нього обидві
    причини вибуття зливаються в одне число, і воно бреше. Так і було до
    25.08.2026 — лічильник «категорія без rz_id: 205» рахував разом 128
    офферів, де `rz_id` справді NULL, і 77, де `rz_id` є, але це відхилена
    здогадка рівня `review` («Інструмент для пайки → Набори інструментів»,
    журнал 23.08). Перші — рішення власника «не тримати у фіді», другі —
    наслідок SKILL-04 (хибна категорія гірша за відсутню).
    """
    cur.execute("""SELECT toptul_id, toptul_name, rz_id, rz_name, tier
                   FROM toptul_rozetka_category_map""")
    rows = cur.fetchall()
    good = {r['toptul_id']: (str(r['rz_id']), r['rz_name']) for r in rows
            if r['rz_id'] is not None and r['tier'] in ALLOWED_TIERS}
    bad = {r['toptul_id']: (r['tier'], r['rz_id'], r['toptul_name'])
           for r in rows if r['toptul_id'] not in good}
    by_tier = collections.Counter(r['tier'] for r in rows
                                  if r['toptul_id'] in good)
    logger.info('Категорій з rz_id: ' + ', '.join(
        f'{t} — {n}' for t, n in sorted(by_tier.items())))
    if bad:
        by_bad = collections.Counter(t for t, _, _ in bad.values())
        logger.info('Категорій поза фідом: ' + ', '.join(
            f'{t} — {n}' for t, n in sorted(by_bad.items())))
    return good, bad


# Словники нормалізуються ТИМ САМИМ виправленням мішаного написання, що й
# текст фіду, і саме тому — обидві половини пари.
#
# Чому ключ. Ключі збиралися з СИРОГО тексту постачальника, а він мішаний:
# `Вороток 1/2" Г-образный большой (Мотор Сiч) В12ГМС` — з латинською `i`.
# Виправивши текст і не виправивши ключ, ми втратили б цей переклад мовчки:
# на першому прогоні 01.09.2026 рядок повернувся у фід російським
# («Г-образный большой» замість «Г-образний великий»), і жоден лічильник про
# втрату не сказав — назва просто перестала збігатись. Таких ключів 44.
#
# Чому значення. У 46 випадках мішане написання лежить у самому ПЕРЕКЛАДІ:
# модель скопіювала зіпсовану літеру з оригіналу. Виправлення тексту до
# підстановки їх не зачіпає — переклад підставляється після.
def _hg(s: str) -> str:
    return fix_homoglyphs(s or '')[0]


def load_translations(cur) -> dict:
    """kind → {оригінал: переклад}. Порожньо, якщо перекладу ще немає."""
    out = collections.defaultdict(dict)
    try:
        cur.execute('SELECT kind, src, dst FROM toptul_translation')
        for r in cur.fetchall():
            out[r['kind']][_hg(r['src'])] = _hg(r['dst'])
    except psycopg2.Error:
        cur.connection.rollback()
        logger.warning('toptul_translation недоступна — переклад не застосовано')
    logger.info('Перекладів: ' + (', '.join(
        f'{k} — {len(v)}' for k, v in sorted(out.items())) or 'немає'))
    return out


def load_desc_translations(cur) -> dict:
    """{російське речення: український переклад}.

    Описи перекладаються ПО РЕЧЕННЯХ, а не цілими текстами, і таблиця тут
    окрема (`toptul_desc_translation`, `tools/toptul_desc_translate.py`).
    Причина в даних: із 433 описів з російськими словами **287 мають лише
    1–2 російські слова** серед сотень українських. Віддати такий опис моделі
    цілком означало б переписати й те, що переписувати не просили.

    Речення, якого немає в словнику, лишається як є — це видно в
    самоперевірці нижче («описів російською»), а не ховається.
    """
    out = {}
    try:
        cur.execute('SELECT src, dst FROM toptul_desc_translation')
        out = {_hg(r['src']): _hg(r['dst']) for r in cur.fetchall()}
    except psycopg2.Error:
        cur.connection.rollback()
        logger.warning('toptul_desc_translation недоступна — описи без перекладу')
    logger.info(f'Перекладів описів (речень): {len(out)}')
    return out


# Розбиття на речення мусить бути ЗВОРОТНИМ: склеївши назад через один
# пробіл, маємо отримати той самий рядок. Це властивість, а не побажання —
# на ній тримається обіцянка «не чіпаємо речення, які й так українські».
# Перевірено на всіх 433 описах: розбіжностей 0 (текст уже пройшов `plain()`,
# тому пробіли зведені). Той самий регекс — у `toptul_desc_translate.py`.
_SENT = re.compile(r'(?<=[.!?])\s+')


def translate_desc(text: str, tr_desc: dict) -> tuple:
    """(текст, скільки речень замінено)."""
    if not tr_desc or not text:
        return text, 0
    n = 0
    out = []
    for s in _SENT.split(text):
        d = tr_desc.get(s.strip())
        if d and d != s.strip():
            out.append(d)
            n += 1
        else:
            out.append(s)
    return ' '.join(out), n


def load_commission(cur) -> dict:
    """rz_id → ставка, %. Потрібна лише при --commission."""
    try:
        cur.execute("""SELECT category_id, commission FROM rozetka_cpa_rates""")
        return {str(r['category_id']): float(r['commission'])
                for r in cur.fetchall() if r['commission'] is not None}
    except psycopg2.Error:
        cur.connection.rollback()
        return {}


def calc_price(price: float, rate, use_commission: bool) -> int:
    if not use_commission:
        return max(1, math.ceil(price * MARKUP))
    comm = rate if rate is not None else DEFAULT_COMMISSION
    return max(1, math.ceil(price * (1 + comm / 100) / 10) * 10)


# ── Характеристики ─────────────────────────────────────────────────────────

def collect_params(offer, tr: dict, hits=None) -> dict:
    """{назва: [значення]} з перекладом і без сміттєвих значень.

    Повторювані теги з тим самим іменем зводяться в один список — далі вони
    підуть ОДНИМ тегом через <br>, як вимагає p185.
    """
    out = collections.OrderedDict()
    for p in offer.findall('param'):
        name = (p.get('name') or '').strip()
        value = (p.text or '').strip()
        if not name or not value:
            continue
        # Мішане написання знімається ДО пошуку в словнику: ключі
        # `toptul_translation` набрані однією абеткою (перевірено — жодного
        # мішаного токена в 3010 рядках), тож `Пapaмeтp` із латинськими
        # літерами не збігся б із жодним і лишився б неперекладеним.
        name, hg_n = fix_homoglyphs(name)
        value, hg_v = fix_homoglyphs(value)
        if hits is not None:
            hits.extend(['мішане написання виправлено в характеристиці']
                        * (sum(hg_n.values()) + sum(hg_v.values())))
        name = tr.get('name', {}).get(name, name)
        value = tr.get('value', {}).get(value, value)
        # Нульова гарантія — попередження валідатора й нульова користь для
        # покупця: Rozetka такої характеристики не приймає.
        if name.lower().startswith('гарант') and re.fullmatch(
                r'0\s*(міс\w*|місяц\w*|мес\w*|р\w*)?', value, re.I):
            continue
        bucket = out.setdefault(name, [])
        if value not in bucket:
            bucket.append(value)
    return out


def pictures(offer, stats) -> list:
    """https, без повторів URL, без кирилиці, не більш ніж MAX_PICTURES."""
    kept, seen = [], set()
    for el in offer.findall('picture'):
        url = (el.text or '').strip()
        if not url:
            continue
        url = re.sub(r'^http://', 'https://', url)
        if not url.lower().startswith('https://'):
            stats['фото: не http(s)'] += 1
            continue
        if CYRILLIC.search(url):
            # Валідатор Rozetka рахує це помилкою, і небезпідставно: такі
            # посилання частина клієнтів просто не відкриває.
            stats['фото: кирилиця в URL'] += 1
            continue
        if url in seen:
            stats['фото: повтор URL'] += 1
            continue
        seen.add(url)
        kept.append(url)
    return kept[:MAX_PICTURES]


def generate(out_file=OUT, limit=None, use_commission=False, drops_file=None):
    out_file = _safe_output(out_file)
    # Перелік відсіяних — не звіт «для галочки»: критерій пункту черги вимагає
    # назвати ПРИЧИНУ по кожному, що не потрапив. Збирається тут, а не окремим
    # скриптом, свідомо: другий код із власною копією правил розійшовся б із
    # генератором, і перелік описував би не той фід (та сама причина, з якої
    # ознака російської імпортується, а не пишеться вдруге).
    drops = [] if drops_file else None
    if not os.path.exists(FEED):
        sys.exit(f'Фід постачальника не знайдено: {FEED} '
                 f'(змінна TOPTUL_FEED_FILE)')

    root = ET.parse(FEED).getroot()
    shop = root.find('shop')
    offers = shop.find('offers').findall('offer')
    logger.info(f'Офферів у фіді постачальника: {len(offers)}')
    fields = resolve_fields(offers)

    # Довідник значень Rozetka з `paramid`/`valueid`. Модуль свідомо падає, а
    # не міряє впівсили: без довідника фільтрові характеристики просто не
    # додались би, а звіт показав би нуль, який читається як «нема чого
    # додавати». Того самого класу нуль 25.08 приховував 478 російських описів.
    ref = load_reference()
    logger.info(f'Довідник фільтрів Rozetka: {len(ref)} категорій, '
                + ', '.join(sorted({n for v in ref.values() for n in v})))

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cats, blocked = load_categories(cur)
    tr = load_translations(cur)
    tr_desc = load_desc_translations(cur)
    fixes = load_fixes()
    logger.info(f'Словник хибних українських форм: {len(fixes)} правил')
    rates = load_commission(cur) if use_commission else {}
    cur.close()
    conn.close()
    if not cats:
        logger.error('toptul_rozetka_category_map порожня для довірених рівнів')
        return 0

    if limit:
        offers = offers[:limit]

    # ── блок категорій: локальний id → rz_id ───────────────────────────────
    rz_used, order = {}, []
    for cid, (rz, rzname) in sorted(cats.items(), key=lambda x: x[1][1] or ''):
        if rz not in rz_used:
            rz_used[rz] = (len(rz_used) + 1, rzname)
            order.append(rz)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<yml_catalog date="{datetime.now():%Y-%m-%d %H:%M}">',
             '  <shop>',
             f'    <name>{esc(SHOP_NAME)}</name>',
             f'    <company>{esc(SHOP_COMPANY)}</company>',
             f'    <url>{esc(SHOP_URL)}</url>',
             '    <currencies><currency id="UAH" rate="1" /></currencies>',
             '    <categories>']
    for rz in order:
        lid, rzname = rz_used[rz]
        lines.append(f'      <category id="{lid}" rz_id="{esc(rz)}">'
                     f'{esc(rzname)}</category>')
    lines += ['    </categories>', '    <offers>']

    stats = collections.Counter()
    ru_names, ru_param_names, ru_param_values = [], collections.Counter(), collections.Counter()
    unk_words = collections.Counter()
    # Описи в самоперевірці не міряли ЗОВСІМ, і саме тому 25.08 генератор
    # рапортував самі нулі, доки у фіді лежало 478 російських описів. Замір,
    # якого немає, — це не нуль, це тиша. Тепер описи рахуються тут і мають
    # збігтись із числом незалежного `toptul_ru_audit.py`.
    ru_desc_offers, ru_desc_words = 0, collections.Counter()
    # Замір ПІСЛЯ виправлення, по тих самих рядках, що йдуть у файл. Нуль тут
    # доводить не «словник спрацював», а «у фіді таких форм немає»: словник
    # міг би й промахнутись мимо (`бит` проти `бита`), і саме це видно тут.
    bad_left = collections.Counter()
    # Мішане написання, яке лишилось у ТОМУ САМОМУ рядку, що йде у файл.
    # Нуль тут довести не можна й не треба: частина токенів (`тORIN`,
    # `PROЗ`, `Vрес`) не має однозначної заміни, і правило 5 черги забороняє
    # її вигадувати. Тому лічильник не «мусить бути нуль», а мусить збігтися
    # з переліком `homoglyph.py --audit`, який власник бачить поіменно.
    hg_left = collections.Counter()
    seen_ids, seen_names = set(), collections.Counter()

    for o in offers:
        sku = (o.get('id') or '').strip()
        cid = _txt(o, fields['cat'])
        if not sku:
            stats['пропущено: без id'] += 1
            continue
        if sku in seen_ids:
            stats['пропущено: дубль id'] += 1
            continue
        if cid not in cats:
            # Причини різні, тому й лічильники різні — див. load_categories().
            tier = blocked.get(cid, (None, None, None))[0]
            if cid not in blocked:
                stats['пропущено: категорія відсутня в мапінгу'] += 1
            elif blocked[cid][1] is None:
                stats['пропущено: категорія без rz_id'] += 1
            else:
                stats[f'пропущено: категорія недовіреного рівня ({tier})'] += 1
            continue
        rz, rzname = cats[cid]

        try:
            price = float((_txt(o, fields['price']) or '0').replace(',', '.'))
        except ValueError:
            price = 0.0
        if price <= 0:
            stats['пропущено: без ціни'] += 1
            continue

        pics = pictures(o, stats)
        if not pics:
            stats['пропущено: без фото'] += 1
            continue

        vendor = _txt(o, fields['vendor']) or os.getenv(
            'TOPTUL_DEFAULT_VENDOR', 'TOPTUL')
        article = _txt(o, fields['article']) or sku
        # `pending` заведено ДО `collect_params()`, бо мітки про виправлене
        # мішане написання зʼявляються вже там, а оффер ще може відсіятись на
        # MIN_PARAMS — див. розбір нижче.
        pending = []
        prm = collect_params(o, tr, pending)
        # Бренд — факт про товар, а не заповнювач: він є в кожному оффері
        # TOPTUL і водночас це фільтрова характеристика Rozetka. Додаємо
        # тільки якщо постачальник не дав її сам.
        if vendor and not any(k.lower() in ('бренд', 'виробник', 'торгова марка')
                              for k in prm):
            prm['Бренд'] = [vendor]
        n_prm_supplier = len(prm)

        raw_name = _txt(o, fields['name'])
        if not raw_name:
            stats['пропущено: без назви'] += 1
            continue
        # Лічильники, які не можна ставити одразу: усе нижче рахується для
        # оффера, який ще може відсіятись на MIN_PARAMS. Раніше такого місця
        # не було — перевірка стояла вище, — і числа «виправлень» описували
        # рівно те, що пішло у файл. Щоб це лишилось правдою, мітки
        # накопичуються й переносяться в `stats` після перевірки.
        #
        # Мішане написання знімається з СИРОЇ назви, тобто до `build_name()`.
        # Це не дрібниця порядку, а вимога власника: артикул і бренд
        # `build_name()` дописує САМ, уже після цього рядка, тож `GIZMATIС3045`
        # у тезі `<article>` лишається дослівно таким, як у постачальника
        # («артикули не змінились»), а виправляється лише текст назви.
        raw_name, hg = fix_homoglyphs(raw_name)
        pending.extend(['мішане написання виправлено в назві']
                       * sum(hg.values()))
        # Переклад накладається на СИРУ назву, до `build_name()`. Інакше
        # словник довелось би вести для похідного рядка, який змінюється від
        # кожної правки правил побудови (зняття бренду, артикула, пунктуації).
        tr_name = tr.get('title', {}).get(raw_name)
        if tr_name and tr_name != raw_name:
            raw_name = tr_name
            pending.append('назву перекладено зі словника')
        name = build_name(raw_name, vendor, article, rzname)
        name, fx = apply_fixes(name, fixes)
        for label in fx:
            pending.append(f'хибна форма виправлена в назві: {label}')
        if len(name) < 5:
            stats['пропущено: назва коротша 5 символів'] += 1
            continue

        # ── фільтрові характеристики з характеристик і назви ───────────────
        # Робиться ПІСЛЯ `build_name()`, бо запасне джерело — саме побудована
        # назва, і саме на ній зроблено замір покриття. `param_ids` тримає
        # `paramid`/`valueid` окремо: у `prm` лежить лише текст, щоб решта
        # перевірок (російська, непізнані слова, MIN_PARAMS) бачила ці
        # характеристики так само, як усі інші.
        param_ids = {}
        for pname, d in extract_filters(rz, prm, name, ref, sku).items():
            prm[pname] = list(d['values'])
            param_ids[pname] = (d['paramid'], d['valueids'])
            pending.append(f'фільтр додано: {pname} (з {d["source"]})')
            for v in d['dropped']:
                pending.append(f'фільтр: значення поза довідником — {v}')
            for v in d.get('trimmed', ()):
                pending.append(
                    f'фільтр: зрізано другим значенням ComboBox — {v}')

        # MIN_PARAMS міряється ПІСЛЯ видобування фільтрів, і саме тут — не
        # вище. До 01.09.2026 перевірка стояла одразу за `collect_params()`,
        # тобто оффер відсіювався ДО того, як міг би отримати «Робочий
        # розмір», «Вид» чи «Розмір посадкового квадрата», а коментар у блоці
        # вище стверджував протилежне — що MIN_PARAMS бачить ці
        # характеристики «так само, як усі інші». Наслідок був не
        # теоретичний: видобування фільтрів для 1179 відсіяних не
        # викликалось жодного разу, і робота 25.08 та 01.09 їх не торкнулась.
        # Порядок кроків тепер такий: характеристики постачальника → назва →
        # фільтри з назви й характеристик → перевірка мінімуму. Назва
        # потрібна раніше за перевірку, бо вона ж є запасним джерелом
        # значень; тому перед перевіркою лишились тільки ті відсіви (без
        # назви, назва коротша 5), які від кількості характеристик не
        # залежать.
        if len(prm) < MIN_PARAMS:
            stats['пропущено: менше 3 характеристик'] += 1
            if drops is not None:
                drops.append((sku, 'менше 3 характеристик', rz, rzname,
                              n_prm_supplier, len(prm),
                              ' | '.join(sorted(prm)), name))
            continue
        for label in pending:
            stats[label] += 1
        stats['фільтри врятували оффер від MIN_PARAMS'] += (
            n_prm_supplier < MIN_PARAMS)
        seen_names[name] += 1

        # Заміряється лише те, що МОЖНА виправити перекладом. Бренд і артикул
        # `build_name()` дописує сам, узявши з тегів, а перекладати їх
        # заборонено («бренди, моделі, артикули НЕ перекладай»), тож товари
        # брендів «Молния» і «Дальнобойщик» та артикулів на кшталт `ЭКСТРХ`
        # рахувались російськими НАЗАВЖДИ — мета, якої не досягти. Той самий
        # випадок, що «Бренд: Молния» 23.08. Виняток той самий, що в
        # `toptul_ru_audit.py`, і саме звідти імпортований: два власні
        # визначення розійшлись би, і числа генератора з незалежним аудитом
        # перестали б збігатись — а їхній збіг і є доказ, що замір не бреше.
        measured = strip_vendor(strip_article(name, article), vendor)
        if RU.search(measured):
            ru_names.append((sku, name))

        avail = (o.get('available') or 'true').strip().lower() != 'false'
        try:
            qty = int(float(_txt(o, fields['qty']) or 0))
        except ValueError:
            qty = 0
        # Нуль при available="false" — штатне позначення «немає в наявності»,
        # а не дефект (SKILL-19, rozetka_xml_validator). Зворотне — товар
        # оголошено доступним із нульовим залишком — Rozetka приймає й одразу
        # ховає, тож там ставимо принаймні одиницю.
        stock = qty if avail and qty > 0 else (1 if avail else 0)

        desc = plain(_txt(o, fields['desc']))
        # Мішане написання — ПЕРШИМ, ще до словника речень. Порядок вимушений
        # двічі: ключі `toptul_desc_translation` набрані однією абеткою, тож
        # зіпсоване речення не збіглося б із жодним; і `apply_fixes()` нижче
        # шукає хибні українські форми буквально, а `відвepткa` з латинськими
        # літерами повз такий пошук проходить.
        desc, hg = fix_homoglyphs(desc)
        if hg:
            stats['опис: виправлено мішане написання'] += sum(hg.values())
            stats['опис: з мішаним написанням'] += 1
        # Переклад накладається ОДРАЗУ після `plain()` — до вирізання речень
        # про доставку й до `clean_description()`. Причина та сама, що й із
        # назвою товару: словник ведеться для тексту постачальника, а не для
        # похідного, який змінюється від кожної правки правил чистки.
        desc, n_tr = translate_desc(desc, tr_desc)
        if n_tr:
            stats['опис: речень перекладено'] += n_tr
            stats['опис: перекладено'] += 1
        # Лічильник звіряється з текстом ДО вирізання, а не з сирим описом:
        # інакше після появи перекладу він рахував би ще й перекладені речення
        # і показував би роботу, якої не робив.
        before_delivery = desc
        desc = _DELIVERY.sub('', desc).strip()
        if desc != before_delivery:
            stats['опис: прибрано згадку доставки/оплати'] += 1
        desc, removed = clean_description(desc)
        for what in set(removed):
            stats[f'опис: прибрано {what}'] += 1
        if not desc:
            desc = synth_description(name, {k: ' / '.join(v)
                                            for k, v in prm.items()},
                                     vendor, article)
            stats['опис: зібрано з характеристик'] += 1

        desc, fx = apply_fixes(desc, fixes)
        for label in fx:
            stats[f'хибна форма виправлена в описі: {label}'] += 1

        # Міряється саме той рядок, який піде у фід, і саме `description_ua`:
        # тег `description` — російська версія картки, російський текст у
        # ньому доречний.
        dru = ru_words(desc)
        if dru:
            ru_desc_offers += 1
            for w in dru:
                ru_desc_words[w] += 1

        seen_ids.add(sku)
        body = [f'      <offer id="{esc(sku)}" '
                f'available="{"true" if avail else "false"}">',
                f'        <price>{calc_price(price, rates.get(rz), use_commission)}'
                f'</price>',
                '        <currencyId>UAH</currencyId>',
                f'        <categoryId>{rz_used[rz][0]}</categoryId>']
        body += [f'        <picture>{esc(u)}</picture>' for u in pics]
        body.append(f'        <vendor>{esc(vendor)}</vendor>')
        body.append(f'        <article>{esc(article)}</article>')
        body.append(f'        <stock_quantity>{stock}</stock_quantity>')
        body.append(f'        <name_ua>{esc(name)}</name_ua>')
        body.append(f'        <name>{esc(name)}</name>')
        # Обидва теги обовʼязкові в p185; текст той самий, іншого в нас немає,
        # а порожній обовʼязковий тег гірший за повторений.
        body.append(f'        <description>{esc(desc)}</description>')
        body.append(f'        <description_ua>{esc(desc)}</description_ua>')
        # Характеристики виправляються ОСТАННІМИ й з двома винятками, кожен
        # із власною причиною:
        #   * `BRAND_PARAMS` — власна назва не є мовою (та сама засторога, що
        #     й «Бренд: Молния» 23.08);
        #   * характеристики з `paramid`/`valueid` — їхній текст мусить
        #     дослівно збігатися з довідником Rozetka, інакше p210 перестає
        #     діяти й фільтр відвалюється. У наших двох фільтрових
        #     характеристиках значення числові, тож правило нічого не ловить,
        #     але покладатись на це — те саме, що не мати правила.
        fixed = {}
        for k, vals in prm.items():
            if k in BRAND_PARAMS or k in param_ids:
                fixed[k] = vals
                continue
            nk, fx = apply_fixes(k, fixes)
            nv = []
            for v in vals:
                s, f2 = apply_fixes(str(v), fixes)
                nv.append(s)
                fx += f2
            for label in fx:
                stats[f'хибна форма виправлена в характеристиці: {label}'] += 1
            # Виправлення може ЗЛИТИ дві назви в одну («Слесарні» і «Слюсарні»
            # поруч), і мовчазне `fixed[nk] = nv` тоді загубило б значення
            # однієї з них. Два теги з тим самим іменем дали 1403 попередження
            # 15.08, тому саме злиття правильне — але воно мусить бути злиттям.
            if nk in fixed:
                fixed[nk] += [v for v in nv if v not in fixed[nk]]
                stats['характеристики злиті після виправлення форми'] += 1
            else:
                fixed[nk] = nv
        prm = fixed

        for label in bad_forms(name, fixes) + bad_forms(desc, fixes):
            bad_left[label] += 1
        for tok, why in homoglyph_leftovers(name) + homoglyph_leftovers(desc):
            hg_left[tok] += 1
        for k, vals in prm.items():
            for tok, why in homoglyph_leftovers(k + ' ' + ' '.join(
                    str(v) for v in vals)):
                hg_left[tok] += 1
        for k, vals in prm.items():
            for label in bad_forms(k, fixes):
                bad_left[label] += 1
            for v in vals:
                for label in bad_forms(str(v), fixes):
                    bad_left[label] += 1
            if RU.search(k):
                ru_param_names[k] += 1
            for w in unknown_words(k):
                unk_words[w] += 1
            for v in vals:
                # Власна назва — не мова, і перекладати її не можна: у
                # прикладі «Бренд: Молния» (3 вживання) українізація зіпсувала
                # б бренд, за яким товар шукають. Перекладач це знає («бренди,
                # моделі, артикули НЕ перекладай»), тож і замір мусить рахувати
                # так само — інакше він вимагає виправити те, що виправляти
                # заборонено, і нуля не буде ніколи.
                if k not in BRAND_PARAMS and RU.search(v):
                    ru_param_values[v] += 1
                if k not in BRAND_PARAMS:
                    for w in unknown_words(v):
                        unk_words[w] += 1
            pid, vids = param_ids.get(k, (None, None))
            if pid and vids and all(v is not None for v in vids):
                # p210 (ред. 12.06.2026): «Ми гарантуємо зіставлення вказаних
                # вами характеристик, які ТОЧНО збігаються з параметрами в
                # категорії»; з `paramid`/`valueid` здогадки немає взагалі.
                # Кілька значень тут пишуться ЧЕРЕЗ КОМУ, а не через `<br>`, —
                # так у прикладі самої довідки (`valueid="2296922, 2645254"`),
                # і порядок тексту мусить відповідати порядку id. `<br>` нижче
                # лишається для характеристик БЕЗ id: там формат довідкою не
                # описаний, а два теги з тим самим іменем дали 1403
                # попередження 15.08.2026.
                body.append(
                    f'        <param name="{esc(k)}" paramid="{pid}" '
                    f'valueid="{", ".join(str(i) for i in vids)}">'
                    f'{esc(", ".join(str(v) for v in vals))}</param>')
                stats[f'фільтр із paramid/valueid: {k}'] += 1
            elif len(vals) > 1:
                joined = ' <br> '.join(str(v)[:240] for v in vals)
                body.append(f'        <param name="{esc(k)}">{cdata(joined)}'
                            f'</param>')
                stats['характеристик зведено в один тег'] += 1
            else:
                body.append(f'        <param name="{esc(k)}">'
                            f'{esc(str(vals[0])[:MAX_PARAM_LEN])}</param>')
        if not any('краї' in k.lower() for k in prm):
            body.append(f'        <param name="Країна-виробник товару">'
                        f'{esc(country_for(vendor))}</param>')
            stats['країна: додано'] += 1
        body.append('      </offer>')
        lines += body
        stats['офферів у фіді'] += 1
        stats['available true' if avail else 'available false'] += 1

    lines += ['    </offers>', '  </shop>', '</yml_catalog>', '']
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    if drops is not None:
        with open(drops_file, 'w', encoding='utf-8') as f:
            f.write('sku\tпричина\trz_id\tкатегорія\tхарактеристик '
                    'постачальника\tхарактеристик після фільтрів\t'
                    'характеристики\tназва\n')
            for row in drops:
                f.write('\t'.join(str(c).replace('\t', ' ').replace('\n', ' ')
                                  for c in row) + '\n')
        logger.info(f'Відсіяні: {len(drops)} → {drops_file}')

    logger.success(f'Згенеровано: {stats["офферів у фіді"]} → {out_file}')
    for k, v in sorted(stats.items()):
        logger.info(f'   {k}: {v}')

    # ── Крок 2 правила позитивного контролю: нуль треба пояснити ───────────
    # Ці три числа — не прикраса звіту. Доки вони не нульові, українізація
    # фіду не завершена, і сказати «переклали» не можна. Якщо ж вони нульові
    # ПРИ ПОРОЖНІЙ таблиці перекладу — це не чистий фід, а мовчазна
    # перевірка, тому таблицю друкуємо теж (див. load_translations).
    dups = [n for n, c in seen_names.items() if c > 1]
    logger.info('── самоперевірка ──')
    logger.info(f'   назв із російськими словами : {len(ru_names)}')
    for sku, n in ru_names[:15]:
        logger.info(f'      {sku}: {n[:70]}')
    logger.info(f'   назв характеристик російською: {len(ru_param_names)} '
                f'різних, {sum(ru_param_names.values())} вживань')
    for n, c in ru_param_names.most_common(10):
        logger.info(f'      {c:5}  {n}')
    logger.info(f'   значень характеристик російською: {len(ru_param_values)} '
                f'різних, {sum(ru_param_values.values())} вживань')
    for n, c in ru_param_values.most_common(10):
        logger.info(f'      {c:5}  {n[:70]}')
    logger.info(f'   ОПИСІВ з російськими словами: {ru_desc_offers} оферів, '
                f'{len(ru_desc_words)} різних слів, '
                f'{sum(ru_desc_words.values())} вживань')
    for w, c in ru_desc_words.most_common(10):
        logger.info(f'      {c:5}  {w}')
    logger.info(f'   ХИБНИХ УКРАЇНСЬКИХ ФОРМ у фіді: {len(bad_left)} різних, '
                f'{sum(bad_left.values())} вживань')
    for w, c in bad_left.most_common(10):
        logger.info(f'      {c:5}  {w}')
    logger.info(f'   МІШАНОГО НАПИСАННЯ лишилось: {len(hg_left)} різних, '
                f'{sum(hg_left.values())} вживань (без однозначної заміни)')
    for w, c in hg_left.most_common(15):
        logger.info(f'      {c:5}  {w}')
    uk_n, ru_n = lexicon_sizes()
    logger.info(f'   словники ознаки: {uk_n} укр. словоформ, {ru_n} рос. слів')
    logger.info(f'   НЕПІЗНАНИХ слів (поза обома словниками): {len(unk_words)} '
                f'різних, {sum(unk_words.values())} вживань')
    for w, c in unk_words.most_common(15):
        logger.info(f'      {c:5}  {w}')
    logger.info(f'   дублікатів назв: {len(dups)}')
    for n in dups[:10]:
        logger.info(f'      {n[:70]}')
    logger.info('Далі: python3 tools/rozetka_xml_validator.py '
                f'{os.path.relpath(out_file, BASE_DIR)} --no-xlsx')
    return stats['офферів у фіді']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--output', default=OUT)
    ap.add_argument('--limit', type=int)
    ap.add_argument('--fields', action='store_true',
                    help='лише інвентаризація тегів фіду постачальника')
    ap.add_argument('--commission', action='store_true',
                    help='ціна з гросапом на комісію Rozetka замість РРЦ')
    ap.add_argument('--drops', metavar='FILE',
                    help='TSV з офферами, відсіяними за MIN_PARAMS, і причиною')
    a = ap.parse_args()

    if a.fields:
        offers = ET.parse(FEED).getroot().find('shop').find('offers')
        resolve_fields(offers.findall('offer'))
        return
    n = generate(a.output, a.limit, a.commission, a.drops)
    sys.exit(0 if n else 1)


if __name__ == '__main__':
    main()
