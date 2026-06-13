#!/usr/bin/env python3
"""
tools/carvol_epicentr_generator.py
====================================
Генератор XML для Єпіцентру з оптового прайсу Carvol (SpreadsheetML формат).

Запуск (на сервері):
    cd /home/tek/agent-system && source venv/bin/activate
    python3 tools/carvol_epicentr_generator.py
    python3 tools/carvol_epicentr_generator.py --input data/carvol_opt_20260613.xml
    python3 tools/carvol_epicentr_generator.py --input data/carvol_opt_20260613.xml --output exports/carvol_epicentr.xml
"""

import os, sys, re, hashlib, json, argparse
import xml.etree.ElementTree as ET
from datetime import datetime
from difflib import SequenceMatcher
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection

# ── Шляхи за замовчуванням ─────────────────────────────────────────────────

INPUT_FILE  = os.path.join(BASE_DIR, 'data', 'carvol_opt_20260613.xml')
OUTPUT_FILE = os.path.join(BASE_DIR, 'exports', 'carvol_epicentr.xml')
FEED_FILE   = os.path.join(BASE_DIR, 'data', 'carvol_feed.xml')

# SpreadsheetML namespace
SS_NS = 'urn:schemas-microsoft-com:office:spreadsheet'


def _t(name: str) -> str:
    return f'{{{SS_NS}}}{name}'


# ── Єпіцентр — константи ───────────────────────────────────────────────────

COUNTRY_CODE    = 'chn'
COUNTRY_NAME    = 'Китай'
DEFAULT_WEIGHT  = 500
DEFAULT_WIDTH   = 200
DEFAULT_HEIGHT  = 100
DEFAULT_LENGTH  = 200

# Категорія-дефолт якщо fuzzy-match не знайшов відповідника (≥0.6)
DEFAULT_EPICENTR_CAT = ('4907', 'Магнітоли')
DEFAULT_VENDOR = 'Carvol'


# ── SpreadsheetML парсер ────────────────────────────────────────────────────

def _cell_value(cell) -> str:
    """Повертає текст клітинки незалежно від namespace. Знімає апостроф Excel-prefix."""
    for tag in (_t('Data'), 'Data'):
        data_el = cell.find(tag)
        if data_el is not None:
            val = (data_el.text or '').strip()
            # Excel зберігає текстові числа з апострофом-префіксом (не видний в UI)
            if val.startswith("'"):
                val = val[1:]
            return val
    return ''


def _row_cells(row) -> list[str]:
    """
    Повертає список значень рядка з врахуванням ss:Index (розріджені рядки).
    ss:Index — 1-based позиція клітинки; пропуски заповнюються порожнім рядком.
    """
    result: list[str] = []
    pos = 0
    cells = row.findall(_t('Cell')) or row.findall('Cell')
    for cell in cells:
        # ss:Index може бути в namespace або без
        idx_attr = cell.get(_t('Index')) or cell.get('ss:Index')
        if idx_attr:
            target = int(idx_attr) - 1  # 0-based
            while pos < target:
                result.append('')
                pos += 1
        result.append(_cell_value(cell))
        pos += 1
    return result


def _find_header_row(rows: list) -> int:
    """
    Знаходить індекс рядка-заголовка: шукає рядок з ≥4 непорожніх клітинок.
    Carvol прайс має 3 рядки-шапки (назва, дата, пустий) перед реальними заголовками.
    """
    for i, row in enumerate(rows[:10]):
        vals = [v for v in _row_cells(row) if v.strip()]
        if len(vals) >= 4:
            return i
    return 0


def parse_spreadsheet_ml(filepath: str) -> list[dict]:
    """
    Парсить SpreadsheetML (Excel XML) файл.
    Автоматично знаходить рядок заголовків (пропускаючи службові рядки шапки).
    Повертає список dict {header_lower: value} для кожного рядка даних.
    """
    logger.info(f"Парсимо SpreadsheetML: {filepath}")
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Перший Worksheet
    ws = root.find(f'.//{_t("Worksheet")}')
    if ws is None:
        ws = root.find('.//Worksheet')
    if ws is None:
        raise ValueError("Worksheet не знайдено в SpreadsheetML")

    table = ws.find(_t('Table'))
    if table is None:
        table = ws.find('Table')
    if table is None:
        raise ValueError("Table не знайдено в Worksheet")

    rows = table.findall(_t('Row'))
    if not rows:
        rows = table.findall('Row')
    logger.info(f"Рядків у файлі: {len(rows)}")

    if not rows:
        return []

    # Автодетекція рядка заголовків
    header_row_idx = _find_header_row(rows)
    logger.info(f"Рядок заголовків: {header_row_idx}")

    headers = [h.lower().strip() for h in _row_cells(rows[header_row_idx])]
    logger.info(f"Заголовки ({len(headers)}): {headers}")

    records: list[dict] = []
    for row in rows[header_row_idx + 1:]:
        vals = _row_cells(row)
        if not any(v.strip() for v in vals):
            continue
        while len(vals) < len(headers):
            vals.append('')
        records.append({headers[i]: vals[i] for i in range(len(headers))})

    logger.info(f"Записів після парсингу: {len(records)}")
    return records


# ── Автодетекція колонок ────────────────────────────────────────────────────

# Шаблони для пошуку потрібних стовпців за назвою заголовка
_COL_PATTERNS: dict[str, list[str]] = {
    'article':  ['артикул', 'код товару', 'код', 'sku', 'article', 'part'],
    'name':     ['найменування', 'назва', 'name', 'наименование', 'товар'],
    'stock':    ['залишок', 'наявність', 'залишки', 'остаток', 'stock', '+/-', 'наліч'],
    # 'роздріб (uah)' — точний формат Carvol прайсу
    'price':    ['роздріб (uah)', 'роздрібна', 'роздріб', 'price uah', 'ціна грн',
                 'прайс', 'ціна роздр', 'rrc', 'ціна'],
    'vendor':   ['бренд', 'виробник', 'brand', 'марка', 'vendor'],
    'category': ['категорія', 'розділ', 'группа', 'group', 'category',
                 'підгрупа', 'тип', 'вид'],
    'model':    ['модель', 'model'],
    'desc':     ['опис', 'description', 'описание', 'характеристик'],
}


def detect_columns(headers: list[str]) -> dict[str, int]:
    """
    Визначає індекси потрібних колонок за ключовими словами.
    Патерни відсортовані від специфічних до загальних — перший збіг виграє.
    """
    mapping: dict[str, int] = {}
    for field, patterns in _COL_PATTERNS.items():
        for pattern in patterns:          # спочатку специфічніші патерни
            for i, h in enumerate(headers):
                if pattern in h:
                    if field not in mapping:
                        mapping[field] = i
                    break
            if field in mapping:
                break
    return mapping


# ── Маппінг категорій Carvol → Єпіцентр ────────────────────────────────────

_epicentr_cats: list[tuple[str, str]] = []
_cat_cache: dict[str, tuple[str, str]] = {}


def _load_epicentr_cats() -> list[tuple[str, str]]:
    global _epicentr_cats
    if _epicentr_cats:
        return _epicentr_cats
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT code, name_ua
        FROM epicentr_categories
        WHERE name_ua IS NOT NULL AND name_ua <> ''
        ORDER BY code
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    _epicentr_cats = [(r['code'], r['name_ua']) for r in rows]
    logger.info(f"Завантажено {len(_epicentr_cats)} категорій Єпіцентру")
    return _epicentr_cats


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').lower().strip())


def _best_match(query: str, candidates: list[tuple[str, str]]) -> tuple[float, str, str]:
    """Повертає (score, code, name) найкращого збігу."""
    q = _norm(query)
    best_score, best_code, best_name = 0.0, '', ''
    for code, name in candidates:
        n = _norm(name)
        raw = SequenceMatcher(None, q, n).ratio()
        # Штраф якщо кандидат містить "зайві" слова (дає хибний збіг "Комплекти"→"DJ-комплекти")
        len_ratio = min(len(q), len(n)) / max(len(q), len(n)) if max(len(q), len(n)) else 1
        score = raw * (0.5 + 0.5 * len_ratio)
        if score > best_score:
            best_score, best_code, best_name = score, code, name
    return best_score, best_code, best_name


_manual_map: dict[str, tuple[str, str]] = {}


def _load_manual_map() -> dict[str, tuple[str, str]]:
    """Завантажує ручний маппінг з таблиці carvol_epicentr_cat_map."""
    global _manual_map
    if _manual_map:
        return _manual_map
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT carvol_cat, epicentr_code, epicentr_name FROM carvol_epicentr_cat_map")
        for r in cur.fetchall():
            _manual_map[r['carvol_cat'].strip()] = (r['epicentr_code'], r['epicentr_name'])
        cur.close(); conn.close()
        logger.info(f"Ручний маппінг: {len(_manual_map)} записів")
    except Exception as e:
        logger.warning(f"carvol_epicentr_cat_map недоступна: {e}")
    return _manual_map


def map_category(carvol_cat: str) -> tuple[str, str]:
    """
    Повертає (epicentr_code, epicentr_name) для категорії Carvol.
    Стратегія (пріоритет зверху вниз):
    1. Ручний маппінг (carvol_epicentr_cat_map) — точний збіг або по кореневій категорії
    2. Точний fuzzy-збіг по epicentr_categories
    3. Матч по листовій категорії (після останнього ' > ')
    4. Матч по повному шляху
    """
    key = (carvol_cat or '').strip()
    if not key:
        return DEFAULT_EPICENTR_CAT

    if key in _cat_cache:
        return _cat_cache[key]

    manual = _load_manual_map()

    # 1a. Точний ручний маппінг
    if key in manual:
        result = manual[key]
        _cat_cache[key] = result
        logger.debug(f"  CAT '{key}' → '{result[1]}' (manual exact)")
        return result

    # 1b. Ручний маппінг по кореню шляху (частина до першого ' > ')
    root_cat = key.split(' > ')[0].strip()
    if root_cat != key and root_cat in manual:
        result = manual[root_cat]
        _cat_cache[key] = result
        logger.debug(f"  CAT '{key}' (root='{root_cat}') → '{result[1]}' (manual root)")
        return result

    candidates = _load_epicentr_cats()

    # 2. Точний fuzzy-збіг
    key_norm = _norm(key)
    for code, name in candidates:
        if _norm(name) == key_norm:
            _cat_cache[key] = (code, name)
            logger.debug(f"  CAT '{key}' → '{name}' (fuzzy exact)")
            return (code, name)

    # 3. Матч по листовій категорії (частина після останнього ' > ')
    leaf = key.split(' > ')[-1].strip()
    if leaf and leaf != key:
        # Спочатку ручний маппінг для листа
        if leaf in manual:
            result = manual[leaf]
            _cat_cache[key] = result
            logger.debug(f"  CAT '{key}' (leaf='{leaf}') → '{result[1]}' (manual leaf)")
            return result
        score, code, name = _best_match(leaf, candidates)
        if score >= 0.72:
            result = (code, name)
            _cat_cache[key] = result
            logger.debug(f"  CAT '{key}' (leaf='{leaf}') → '{name}' (score={score:.2f})")
            return result

    # 4. Матч по повному шляху
    score, code, name = _best_match(key, candidates)
    if score >= 0.72 and code:
        result = (code, name)
        logger.debug(f"  CAT '{key}' → '{name}' (score={score:.2f})")
    else:
        result = DEFAULT_EPICENTR_CAT
        logger.warning(f"  CAT '{key}' не знайдено (best={score:.2f} '{name}') → DEFAULT")

    _cat_cache[key] = result
    return result


# ── Фото з таблиці carvol_products ─────────────────────────────────────────

_pics_cache: dict[str, list[str]] = {}


def _load_pics() -> None:
    if _pics_cache:
        return
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT article, pictures
            FROM carvol_products
            WHERE pictures IS NOT NULL AND pictures <> '[]'
        """)
        for r in cur.fetchall():
            pics = r['pictures']
            if isinstance(pics, str):
                try:
                    pics = json.loads(pics)
                except json.JSONDecodeError:
                    pics = []
            if pics and r['article']:
                _pics_cache[r['article'].upper()] = [p for p in pics if p]
        cur.close(); conn.close()
        logger.info(f"Фото завантажено для {len(_pics_cache)} товарів")
    except Exception as exc:
        logger.warning(f"Не вдалось завантажити фото з БД: {exc}")


def get_pictures(article: str) -> list[str]:
    return _pics_cache.get((article or '').upper(), [])


# ── Дані з Rozetka XML feed (описи, фото, vendor) ──────────────────────────

_feed_cache: dict[str, dict] = {}


def _load_feed_data(feed_file: str) -> None:
    """Завантажує описи, фото і vendor з Prom/Rozetka XML фіду Carvol."""
    if _feed_cache:
        return
    if not os.path.exists(feed_file):
        logger.warning(f"Feed файл не знайдено: {feed_file}")
        return
    try:
        tree = ET.parse(feed_file)
        root = tree.getroot()
        offers = root.findall('.//offer')
        for o in offers:
            art = (o.findtext('article', '') or '').strip()
            if not art:
                continue
            key = art.upper()
            desc = (o.findtext('description_ua', '') or o.findtext('description', '') or '').strip()
            pics = [p.text for p in o.findall('picture') if p.text and p.text.strip()]
            vendor = (o.findtext('vendor', '') or '').strip()
            _feed_cache[key] = {'desc': desc, 'pics': pics, 'vendor': vendor}
        logger.info(f"Feed завантажено: {len(_feed_cache)} товарів з {feed_file}")
    except Exception as exc:
        logger.warning(f"Не вдалось завантажити feed: {exc}")


# ── Бренди Єпіцентру (epicentr_brand_map) ──────────────────────────────────

_brand_map: dict[str, dict] = {}  # key=brand_name.lower()
_unknown_vendors_warned: set[str] = set()


def _load_brand_map() -> dict[str, dict]:
    global _brand_map
    if _brand_map:
        return _brand_map
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT brand_name, valuecode, value_ua FROM epicentr_brand_map")
        for r in cur.fetchall():
            key = (r['brand_name'] or '').lower().strip()
            if key:
                _brand_map[key] = {'valuecode': r['valuecode'], 'value_ua': r['value_ua']}
        cur.close(); conn.close()
        logger.info(f"Бренди Єпіцентру завантажено: {len(_brand_map)} записів")
    except Exception as e:
        logger.warning(f"epicentr_brand_map недоступна: {e}")
    return _brand_map


def get_valid_vendor(vendor_name: str, conn=None) -> dict | None:
    """
    Шукає бренд в epicentr_brand_map (case-insensitive).
    Повертає {'valuecode': ..., 'value_ua': ...} або None якщо не знайдено.
    """
    bmap = _load_brand_map()
    key = (vendor_name or '').lower().strip()
    return bmap.get(key)


# ── Хелпери ─────────────────────────────────────────────────────────────────

def escape_xml(text) -> str:
    s = str(text) if text is not None else ''
    return (s
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&apos;'))


def parse_price(raw: str) -> float:
    try:
        return float(re.sub(r'[^\d.,]', '', raw).replace(',', '.'))
    except (ValueError, TypeError):
        return 0.0


# ── Основна функція генерації ────────────────────────────────────────────────

def generate_xml(
    input_file: str = INPUT_FILE,
    output_file: str = OUTPUT_FILE,
    feed_file: str = FEED_FILE,
) -> int:
    # 1. Парсинг SpreadsheetML
    records = parse_spreadsheet_ml(input_file)
    if not records:
        logger.error("Файл порожній або не містить записів")
        return 0

    headers = list(records[0].keys())
    col = detect_columns(headers)
    logger.info(f"Детектовані колонки: { {k: headers[v] for k, v in col.items()} }")

    missing = [f for f in ('article', 'price') if f not in col]
    if missing:
        logger.error(f"Обов'язкові колонки не знайдено: {missing}")
        logger.error(f"Доступні заголовки: {headers}")
        return 0

    # 2. Фільтр залишок: '+' або '++' (є в наявності), '-' = немає
    if 'stock' in col:
        stock_key = headers[col['stock']]
        filtered = [r for r in records if '+' in r.get(stock_key, '').strip()]
        logger.info(f"Залишок містить '+': {len(filtered)} з {len(records)} записів")
    else:
        logger.warning("Колонка 'залишок' не знайдена — беремо всі записи")
        filtered = records

    if not filtered:
        logger.error("Немає товарів з залишком '+'")
        return 0

    # 3. Фото з БД + дані з Rozetka feed (описи, фото, vendor) + бренди Єпіцентру
    _load_pics()
    _load_feed_data(feed_file)
    _load_brand_map()

    # 4. Генерація XML
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{datetime.now().strftime("%Y-%m-%d %H:%M")}">',
        '<offers>',
    ]

    cnt_total = 0
    cnt_no_price = 0
    cnt_no_article = 0
    cnt_with_pics = 0
    cnt_pics_from_feed = 0
    cnt_desc_from_feed = 0
    cnt_desc_auto = 0
    cnt_vendor_from_feed = 0
    cnt_vendor_default = 0
    cnt_vendor_valid = 0    # знайдено в epicentr_brand_map
    cnt_vendor_other = 0    # не знайдено → Єпіцентр прийме як "Інше"
    vendor_unknown_stats: dict[str, int] = {}
    cat_stats: dict[str, int] = {}

    for rec in filtered:
        article = rec.get(headers[col['article']], '').strip()
        if not article:
            cnt_no_article += 1
            continue

        price = parse_price(rec.get(headers[col['price']], '') if 'price' in col else '')
        if price <= 0:
            cnt_no_price += 1
            continue

        name    = rec.get(headers[col['name']], '').strip()     if 'name'     in col else ''
        vendor  = rec.get(headers[col['vendor']], '').strip()   if 'vendor'   in col else ''
        model   = rec.get(headers[col['model']], '').strip()    if 'model'    in col else ''
        cat_raw = rec.get(headers[col['category']], '').strip() if 'category' in col else ''
        desc    = rec.get(headers[col['desc']], '').strip()     if 'desc'     in col else ''

        # Feed-дані для fallback
        feed_item = _feed_cache.get(article.upper(), {})

        # Назва: беремо з файлу або складаємо як [Бренд] [Модель] [Артикул]
        if not name:
            parts = [p for p in [vendor, model or article] if p]
            name = ' '.join(parts) or article

        # Vendor: прайс → feed → дефолт
        if not vendor:
            feed_vendor = feed_item.get('vendor', '')
            if feed_vendor:
                vendor = feed_vendor
                cnt_vendor_from_feed += 1
            else:
                vendor = DEFAULT_VENDOR
                cnt_vendor_default += 1

        # Опис: прайс → feed → авто-генерація
        if not desc:
            feed_desc = feed_item.get('desc', '')
            if feed_desc:
                desc = feed_desc
                cnt_desc_from_feed += 1
            else:
                desc = f'<p>{escape_xml(name)} — якісний автоаксесуар для вашого автомобіля.</p>'
                cnt_desc_auto += 1

        cat_code, cat_name = map_category(cat_raw)
        cat_stats[cat_name] = cat_stats.get(cat_name, 0) + 1

        # Фото: БД → feed
        pictures = get_pictures(article)
        if pictures:
            cnt_with_pics += 1
        else:
            feed_pics = feed_item.get('pics', [])
            if feed_pics:
                pictures = feed_pics
                cnt_pics_from_feed += 1

        # Пошук бренду в epicentr_brand_map
        brand_info = get_valid_vendor(vendor)
        if brand_info:
            v_code = brand_info['valuecode']
            v_text = brand_info['value_ua']
            cnt_vendor_valid += 1
        else:
            v_code = ''
            v_text = vendor
            cnt_vendor_other += 1
            vendor_unknown_stats[vendor] = vendor_unknown_stats.get(vendor, 0) + 1
            if vendor not in _unknown_vendors_warned:
                logger.warning(f"Невідомий бренд для Єпіцентру (буде 'Інше'): '{vendor}'")
                _unknown_vendors_warned.add(vendor)

        avail = 'true'

        offer: list[str] = [
            f'  <offer id="{escape_xml(article)}" available="{avail}">',
            f'    <price>{price:.2f}</price>',
            f'    <category code="{escape_xml(cat_code)}">{escape_xml(cat_name)}</category>',
            f'    <attribute_set code="{escape_xml(cat_code)}">{escape_xml(cat_name)}</attribute_set>',
            f'    <name lang="ua">{escape_xml(name)}</name>',
        ]

        for pic_url in pictures[:10]:
            if pic_url:
                offer.append(f'    <picture>{escape_xml(pic_url)}</picture>')

        if desc:
            offer.append(f'    <description lang="ua"><![CDATA[{desc}]]></description>')

        if v_code:
            brand_param = f'    <param name="Бренд" paramcode="brand" valuecode="{escape_xml(v_code)}">{escape_xml(v_text)}</param>'
        else:
            brand_param = f'    <param name="Бренд" paramcode="brand">{escape_xml(v_text)}</param>'

        offer += [
            f'    <vendor code="{escape_xml(v_code)}">{escape_xml(v_text)}</vendor>',
            f'    <country_of_origin code="{COUNTRY_CODE}">{COUNTRY_NAME}</country_of_origin>',
            '    <param name="Міра виміру" paramcode="measure" valuecode="measure_pcs">шт.</param>',
            '    <param name="Мінімальна кратність товару" paramcode="ratio">1</param>',
            brand_param,
            f'    <weight>{DEFAULT_WEIGHT}</weight>',
            f'    <width>{DEFAULT_WIDTH}</width>',
            f'    <height>{DEFAULT_HEIGHT}</height>',
            f'    <length>{DEFAULT_LENGTH}</length>',
            '  </offer>',
        ]

        lines.extend(offer)
        cnt_total += 1

    lines += ['</offers>', '</yml_catalog>']

    # 5. Збереження
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))

    size_kb = os.path.getsize(output_file) // 1024

    # 6. Статистика
    logger.success(f"XML збережено: {output_file} ({cnt_total} офферів, {size_kb} KB)")

    sep = '=' * 52
    print(f'\n{sep}')
    print(f'  Генерація: {output_file}')
    print(sep)
    cnt_no_pics = cnt_total - cnt_with_pics - cnt_pics_from_feed
    print(f'  Записів у файлі:         {len(records)}')
    print(f'  З наявністю "+":         {len(filtered)}')
    print(f'  Згенеровано офферів:     {cnt_total}')
    print(f'  Пропущено (ціна=0):      {cnt_no_price}')
    print(f'  Пропущено (немає арт.):  {cnt_no_article}')
    print(f'  З фото (з БД):           {cnt_with_pics}')
    print(f'  З фото (з feed):         {cnt_pics_from_feed}')
    print(f'  Без фото:                {cnt_no_pics}')
    print(f'  Опис з feed:             {cnt_desc_from_feed}')
    print(f'  Опис авто-генерація:     {cnt_desc_auto}')
    print(f'  Vendor з feed:           {cnt_vendor_from_feed}')
    print(f'  Vendor дефолт (Carvol):  {cnt_vendor_default}')
    print(f'  Vendor code (Єпіцентр):  {cnt_vendor_valid}')
    print(f'  Vendor=Інше (невідомий): {cnt_vendor_other}')
    print(f'  Розмір файлу:            {size_kb} KB')
    print(f'\n  Детектовані колонки:')
    for field, idx in col.items():
        print(f'    {field:12} → [{idx}] "{headers[idx]}"')
    print(f'\n  Топ категорій Єпіцентру:')
    for cat, cnt in sorted(cat_stats.items(), key=lambda x: -x[1])[:15]:
        print(f'    {cnt:5}  {cat}')
    if vendor_unknown_stats:
        print(f'\n  Невідомі бренди (топ-20):')
        for brand, cnt in sorted(vendor_unknown_stats.items(), key=lambda x: -x[1])[:20]:
            print(f'    {cnt:5}  {brand}')
    print(sep)

    return cnt_total


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Генератор XML Єпіцентру з прайсу Carvol (SpreadsheetML)'
    )
    parser.add_argument('--input',  default=INPUT_FILE,  help='Шлях до SpreadsheetML файлу')
    parser.add_argument('--output', default=OUTPUT_FILE, help='Шлях для збереження XML')
    parser.add_argument('--feed',   default=FEED_FILE,   help='Шлях до Rozetka XML feed (описи/фото/vendor)')
    args = parser.parse_args()

    total = generate_xml(args.input, args.output, args.feed)
    sys.exit(0 if total > 0 else 1)
