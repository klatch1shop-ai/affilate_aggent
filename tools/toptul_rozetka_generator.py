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
from toptul_translate import RU  # noqa: E402

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
    if vendor:
        head = re.sub(rf'\b{re.escape(vendor)}\b', ' ', head, flags=re.I)
    if article:
        head = re.sub(rf'\b{re.escape(article)}\b', ' ', head, flags=re.I)
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

def load_categories(cur) -> dict:
    """toptul_id → (rz_id, rz_name) лише для довірених рівнів."""
    cur.execute("""SELECT toptul_id, rz_id, rz_name, tier
                   FROM toptul_rozetka_category_map
                   WHERE rz_id IS NOT NULL AND tier = ANY(%s)""",
                (list(ALLOWED_TIERS),))
    rows = cur.fetchall()
    by_tier = collections.Counter(r['tier'] for r in rows)
    logger.info('Категорій з rz_id: ' + ', '.join(
        f'{t} — {n}' for t, n in sorted(by_tier.items())))
    return {r['toptul_id']: (str(r['rz_id']), r['rz_name']) for r in rows}


def load_translations(cur) -> dict:
    """kind → {оригінал: переклад}. Порожньо, якщо перекладу ще немає."""
    out = collections.defaultdict(dict)
    try:
        cur.execute('SELECT kind, src, dst FROM toptul_translation')
        for r in cur.fetchall():
            out[r['kind']][r['src']] = r['dst']
    except psycopg2.Error:
        cur.connection.rollback()
        logger.warning('toptul_translation недоступна — переклад не застосовано')
    logger.info('Перекладів: ' + (', '.join(
        f'{k} — {len(v)}' for k, v in sorted(out.items())) or 'немає'))
    return out


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

def collect_params(offer, tr: dict) -> dict:
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


def generate(out_file=OUT, limit=None, use_commission=False):
    out_file = _safe_output(out_file)
    if not os.path.exists(FEED):
        sys.exit(f'Фід постачальника не знайдено: {FEED} '
                 f'(змінна TOPTUL_FEED_FILE)')

    root = ET.parse(FEED).getroot()
    shop = root.find('shop')
    offers = shop.find('offers').findall('offer')
    logger.info(f'Офферів у фіді постачальника: {len(offers)}')
    fields = resolve_fields(offers)

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cats = load_categories(cur)
    tr = load_translations(cur)
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
            stats['пропущено: категорія без rz_id'] += 1
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
        prm = collect_params(o, tr)
        # Бренд — факт про товар, а не заповнювач: він є в кожному оффері
        # TOPTUL і водночас це фільтрова характеристика Rozetka. Додаємо
        # тільки якщо постачальник не дав її сам.
        if vendor and not any(k.lower() in ('бренд', 'виробник', 'торгова марка')
                              for k in prm):
            prm['Бренд'] = [vendor]
        if len(prm) < MIN_PARAMS:
            stats['пропущено: менше 3 характеристик'] += 1
            continue

        raw_name = _txt(o, fields['name'])
        if not raw_name:
            stats['пропущено: без назви'] += 1
            continue
        # Переклад накладається на СИРУ назву, до `build_name()`. Інакше
        # словник довелось би вести для похідного рядка, який змінюється від
        # кожної правки правил побудови (зняття бренду, артикула, пунктуації).
        tr_name = tr.get('title', {}).get(raw_name)
        if tr_name and tr_name != raw_name:
            raw_name = tr_name
            stats['назву перекладено зі словника'] += 1
        name = build_name(raw_name, vendor, article, rzname)
        if len(name) < 5:
            stats['пропущено: назва коротша 5 символів'] += 1
            continue
        seen_names[name] += 1
        if RU.search(name):
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
        desc = _DELIVERY.sub('', desc).strip()
        if desc != plain(_txt(o, fields['desc'])):
            stats['опис: прибрано згадку доставки/оплати'] += 1
        if not desc:
            desc = synth_description(name, {k: ' / '.join(v)
                                            for k, v in prm.items()},
                                     vendor, article)
            stats['опис: зібрано з характеристик'] += 1

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
        for k, vals in prm.items():
            if RU.search(k):
                ru_param_names[k] += 1
            for v in vals:
                if RU.search(v):
                    ru_param_values[v] += 1
            if len(vals) > 1:
                joined = ' <br> '.join(str(v)[:240] for v in vals)
                body.append(f'        <param name="{esc(k)}">{cdata(joined)}'
                            f'</param>')
                stats['характеристик зведено в один тег'] += 1
            else:
                body.append(f'        <param name="{esc(k)}">'
                            f'{esc(str(vals[0])[:MAX_PARAM_LEN])}</param>')
        body.append('      </offer>')
        lines += body
        stats['офферів у фіді'] += 1
        stats['available true' if avail else 'available false'] += 1

    lines += ['    </offers>', '  </shop>', '</yml_catalog>', '']
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

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
    a = ap.parse_args()

    if a.fields:
        offers = ET.parse(FEED).getroot().find('shop').find('offers')
        resolve_fields(offers.findall('offer'))
        return
    n = generate(a.output, a.limit, a.commission)
    sys.exit(0 if n else 1)


if __name__ == '__main__':
    main()
