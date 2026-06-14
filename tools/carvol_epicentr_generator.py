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

import os, sys, re, hashlib, json, argparse, math
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
OTHER_BRAND_CODE = '827b4a70220f11ea918e001e67ecc97b'

# Комісія Єпіцентру по кодах категорій (% від ціни продажу)
# Джерело: таблиця epicentr_cpa_rates; відсутні категорії → дефолт 15%
EPICENTR_COMMISSION: dict[str, float] = {
    '8743': 15.0,  # Перехідні рамки для автомагнітол
    '4907': 15.0,  # Магнітоли
    '3729': 15.0,  # Камери заднього огляду
    '2821': 15.0,  # Кабелі та перехідники
    '2848': 15.0,  # Аксесуари для автосигналізацій
    '2883': 15.0,  # LED-світло для автомобіля
    '2866': 15.0,  # Автомагнітоли
}
DEFAULT_COMMISSION = 15.0

# ── Єпіцентр PIM — valuecodes обов'язкових атрибутів ──────────────────────
# Джерело: tools/epicentr_attrs_explorer.py → таблиця epicentr_required_attrs

# attr 4866 — Марка автомобіля (multiselect, обов'язк. для 8743/3729/2866)
CAR_BRAND_UNIVERSAL = '3ad4056127c7c0038b78a7f24cc80941'   # 'універсальна'

# attr 6513 — Тип камери (select, обов'язк. 3729)
CAM_TYPE_UNIVERSAL = '7299e5c152994121d88f9bcd470856b4'    # 'універсальна'
CAM_TYPE_STOCK     = '7cf79577178c3c5c36f436083e063655'    # 'штатна'

# attr 11926 — Вид камери (select, обов'язк. 3729)
CAM_VIEW_EMBEDDED  = '7e95d2c4d062009c0be07a7f6977630a'   # 'врізна'
CAM_VIEW_PLATE     = 'ca3e67de55b5f4715e6f07126b29c833'   # 'рамка номеру'
CAM_VIEW_HANDLE    = 'bdfa916fc1b271066db95a8b50331c53'   # 'ручка багажника'

# attr 1514 — Роздільна здатність (select, обов'язк. 3729)
CAM_RES_640x480    = '9c9e3de91c6ed6fec1e4e1dd00ff42f5'   # '640x480'
CAM_RES_800x600    = 'e8cf43113ee5de6956e9e2604fd30726'   # '800x600'

# attr 51 — Вид рамки (multiselect, обов'язк. 8743)
FRAME_VIEW_FRAME   = 'oygfpb2qe85gkxu2'                   # 'рамка'

# attr 52 — Матеріал рамки (multiselect, обов'язк. 8743)
FRAME_MATERIAL_PLASTIC = '59474de511ea0'                   # 'пластик'

# attr 5575 — Розмір DIN (multiselect, обов'язк. 8743)
DIN_1       = 'b1ae2e6b91a1585c7f8f41c4d9ccf31a'          # '1 DIN'
DIN_2       = 'ac6de55906304dde5f3e2a9dce129472'          # '2 DIN'
DIN_STOCK   = 'f4b058f379b8a1e4f51ab8a2d19967b3'          # 'штатний'

# attr 12097 — Базовий колір (multiselect, обов'язк. 8743)
COLOR_BLACK  = '3ec160321d45b95cf3a540ad3a2bf896'         # 'чорний'
COLOR_GREY   = '59474de51f852'                             # 'сірий'
COLOR_SILVER = 'cda97fb08eda186db32c35530a77c169'         # 'срібло'

# attr 6547 — Монтажний розмір (select, обов'язк. 2866)
HU_DIN_1    = 'f50736375652d028ada0830633d6eabb'          # '1 DIN'
HU_DIN_2    = 'bf24a9c8dba87b73eff8558f920465dd'          # '2 DIN'
HU_DIN_STK  = 'f80c33cd5ad122b0061bcef59e834cf3'          # 'штатний'

# attr 6546 — Тип магнітоли (multiselect, обов'язк. 2866)
HU_TYPE_MULTIMEDIA = '6c37e1c5438d5c1def462d317a0badf4'  # 'мультимедіа'
HU_TYPE_NODISK     = '35f1542c708837463fa1ff36deeaa05f'  # 'бездискові'

# attr 6534 — Роз'єми (multiselect, обов'язк. 2866)
CONN_USB    = 'e0a4ed3c6ee0b0bd090f6fc9d3adae32'
CONN_AUX    = '6f4bfa054da3527036ed99c99b056ed8'
CONN_ISO    = '6f3dc117d0547a99070154f3b3d22cc1'
CONN_SD     = '23b8a01e61f6865a9110b464893915e0'
CONN_VIDEO_IN  = 'ce077fc1f63803d602423e1050710686'
CONN_CAM_OUT   = '2ea7e4f7513debab41bbd993a7e3fdf0'

# attr 11263 — Бездротові технології (multiselect, обов'язк. 2866)
WIRELESS_BT   = 'aa4cebda1eede9c3c1da569d448e0fca'
WIRELESS_WIFI = '24a7fbd807c8ae71bd5fe1b8a4029069'
WIRELESS_FM   = '6e41ac3ba4c89064a8cdc28547f8656e'

# attr 1548 — Тип тюнера (multiselect, обов'язк. 2866)
TUNER_DIGITAL  = '53b3e9a8edcf1f6eb9ce25aa1fdfb321'      # 'цифровий'
TUNER_ANALOG   = 'd528f19e248a8483d98ac08888337941'       # 'аналоговий'

# attr 1382 — Діапазон радіосигналу (multiselect, обов'язк. 4907)
RADIO_FM = '08eb2c3faa8be25954b063a2354e8886'

# attr 1384 — Налаштування частоти (multiselect, обов'язк. 4907) — 1 option
FREQ_DIGITAL = '46c7d550fed92fd045ac77e40674d8c0'          # 'цифрова'

# attr 5093 — Живлення (multiselect, обов'язк. 4907)
POWER_UNIVERSAL = 'a41774d7ec6d5740d58fe417dd76d8fa'       # 'універсальне'
POWER_NETWORK   = '0380ad214b03e5ae48e604b6c0f54ed0'       # 'від мережі'

# attr 6187 — ПДК (select, обов'язк. 4907)
REMOTE_YES = 'c5f6ccdb5b9768be76e66076d0c4a4ac'            # 'з пультом'
REMOTE_NO  = 'fb646e75fba1511bf08fa378fe404a54'            # 'без пульта'

# attr 78 — Колір виробника (multiselect, обов'язк. 4907)
COLOR_MFR_BLACK  = 'ff8cwdpi'                              # 'чорний'
COLOR_MFR_SILVER = 'wdlnhtlh'                              # 'срібний'
COLOR_MFR_RED    = '5uooq3p5'                              # 'червоний'


def _p(name: str, code: str, valuecode: str, value: str) -> str:
    """Генерує рядок <param> з valuecode."""
    return f'    <param name="{name}" paramcode="{code}" valuecode="{valuecode}">{value}</param>'


def _detect_din(name: str) -> str:
    """Детектує DIN розмір з назви товару (1DIN / 2DIN / штатний)."""
    n = name.lower()
    if '1 din' in n or '1din' in n:
        return '1 DIN'
    if 'штатний' in n or 'штатн' in n:
        return 'штатний'
    # Більшість QIV/Teyes — 2DIN (9"/10" головні пристрої)
    return '2 DIN'


def _detect_frame_color(name: str) -> str:
    """Детектує колір рамки з назви ('graphite'→grey, 'silver'→silver, default→black)."""
    n = name.lower()
    if 'graphite' in n or 'gray' in n or 'grey' in n or 'сір' in n:
        return 'grey'
    if 'silver' in n or 'срібл' in n:
        return 'silver'
    return 'black'


def _detect_cam_view(name: str) -> str:
    """Детектує вид камери з назви."""
    n = name.lower()
    if 'рамка номер' in n or 'номерн' in n or 'plate' in n:
        return 'plate'
    if 'ручка' in n or 'handle' in n:
        return 'handle'
    return 'embedded'


def _detect_cam_resolution(name: str) -> str:
    """Детектує роздільну здатність камери."""
    n = name.lower()
    if '1080' in n or 'fhd' in n or 'full hd' in n:
        return '1920х1080'
    if '720' in n or 'hd' in n:
        return '1280x720'
    if '800tvl' in n or '800 tvl' in n:
        return '800x600'
    return '640x480'


def get_category_params(cat_code: str, name: str, car_brand_map: dict | None = None) -> list[str]:
    """
    Повертає список рядків <param> для обов'язкових атрибутів категорії.
    car_brand_map: {name_lower: (valuecode, name_ua)} з epicentr_car_brands.
    """
    params = []
    cbm = car_brand_map or {}

    if cat_code == '8743':
        # Перехідні рамки для автомагнітол
        din = _detect_din(name)
        din_code = DIN_2 if din == '2 DIN' else (DIN_1 if din == '1 DIN' else DIN_STOCK)
        color = _detect_frame_color(name)
        color_code = COLOR_GREY if color == 'grey' else (COLOR_SILVER if color == 'silver' else COLOR_BLACK)
        color_ua = {'grey': 'сірий', 'silver': 'срібло', 'black': 'чорний'}[color]
        car_brands = detect_car_brands_from_name(name, cbm)
        params += [
            _p('Розмір', '5575', din_code, din),
            _p('Вид', '51', FRAME_VIEW_FRAME, 'рамка'),
            *[_p('Марка автомобіля', '4866', vc, nu) for vc, nu in car_brands],
            _p('Матеріал', '52', FRAME_MATERIAL_PLASTIC, 'пластик'),
            _p('Базовий колір', '12097', color_code, color_ua),
        ]

    elif cat_code == '2866':
        # Автомагнітоли (Android head units — QIV Q1/Q4/Q5, Mekede, Teyes)
        din = _detect_din(name)
        din_code = HU_DIN_2 if din == '2 DIN' else (HU_DIN_1 if din == '1 DIN' else HU_DIN_STK)
        car_brands = detect_car_brands_from_name(name, cbm)
        params += [
            *[_p('Марка автомобіля', '4866', vc, nu) for vc, nu in car_brands],
            _p('Тип магнітоли', '6546', HU_TYPE_MULTIMEDIA, 'мультимедіа'),
            _p('Монтажний розмір', '6547', din_code, din),
            _p("Роз'єми", '6534', CONN_USB, 'USB'),
            _p("Роз'єми", '6534', CONN_AUX, 'AUX'),
            _p("Роз'єми", '6534', CONN_ISO, 'ISO'),
            _p("Роз'єми", '6534', CONN_VIDEO_IN, 'відеовхід'),
            _p("Роз'єми", '6534', CONN_CAM_OUT, 'вихід для камери заднього огляду'),
            _p('Бездротові технології', '11263', WIRELESS_BT, 'Bluetooth'),
            _p('Бездротові технології', '11263', WIRELESS_WIFI, 'Wi-Fi'),
            _p('Тип тюнера', '1548', TUNER_DIGITAL, 'цифровий'),
        ]

    elif cat_code == '3729':
        # Камери заднього огляду
        view = _detect_cam_view(name)
        view_code = {'plate': CAM_VIEW_PLATE, 'handle': CAM_VIEW_HANDLE}.get(view, CAM_VIEW_EMBEDDED)
        view_ua   = {'plate': 'рамка номеру', 'handle': 'ручка багажника'}.get(view, 'врізна')
        res = _detect_cam_resolution(name)
        res_map = {
            '1920х1080': 'cafccc0c1fdaad0ac4607a755b066978',
            '1280x720':  '1170fde30dfd911f207e2467bc15419c',
            '800x600':   CAM_RES_800x600,
            '640x480':   CAM_RES_640x480,
        }
        res_code = res_map.get(res, CAM_RES_640x480)
        car_brands = detect_car_brands_from_name(name, cbm)
        params += [
            *[_p('Марка автомобіля', '4866', vc, nu) for vc, nu in car_brands],
            _p('Роздільна здатність екрана', '1514', res_code, res),
            _p('Вид', '11926', view_code, view_ua),
            _p('Тип', '6513', CAM_TYPE_UNIVERSAL, 'універсальна'),
            _p('Паркувальна розмітка', '6510', 'yes', 'так'),
            _p('Автозатемнення', '6564', 'no', 'ні'),
        ]

    elif cat_code == '4907':
        # Магнітоли (портативні)
        params += [
            _p('Підтримуваний діапазон радіосигналу', '1382', RADIO_FM, 'FM'),
            _p('Налаштування частоти', '1384', FREQ_DIGITAL, 'цифрова'),
            _p('Живлення', '5093', POWER_UNIVERSAL, 'універсальне (мережа або батарейки)'),
            _p('Пульт дистанційного керування', '6187', REMOTE_YES, 'з пультом дистанційного керування'),
            _p('Колір виробника', '78', COLOR_MFR_BLACK, 'чорний'),
        ]
    # 2848 — тільки float dims (weight/width/height/length), вже є в offer
    # 2821 — не знайдено в PIM API, пропускаємо

    return params


def calc_sell_price(rrc: float, cat_code: str) -> float:
    """Ціна продажу = РРЦ gross-up на комісію Єпіцентру, округлення вгору до 10."""
    comm = EPICENTR_COMMISSION.get(cat_code, DEFAULT_COMMISSION)
    return math.ceil(rrc / (1 - comm / 100) / 10) * 10


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


# ── Бренди авто Єпіцентру (epicentr_car_brands, attr 4866) ─────────────────

_car_brand_map: dict[str, tuple[str, str]] = {}  # name_lower → (valuecode, name_ua)


def _load_car_brand_map() -> dict[str, tuple[str, str]]:
    global _car_brand_map
    if _car_brand_map:
        return _car_brand_map
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT valuecode, name_ua, name_lower FROM epicentr_car_brands")
        for r in cur.fetchall():
            key = r['name_lower'] or (r['name_ua'] or '').lower()
            if key:
                _car_brand_map[key] = (r['valuecode'], r['name_ua'])
        cur.close(); conn.close()
        logger.info(f"Бренди авто завантажено: {len(_car_brand_map)} записів")
    except Exception as e:
        logger.warning(f"epicentr_car_brands недоступна: {e}")
    return _car_brand_map


def detect_car_brands_from_name(name: str, car_brand_map: dict) -> list[tuple[str, str]]:
    """
    Знаходить марки авто в назві товару по слову (word boundary).
    Повертає список (valuecode, name_ua) — кожен як окремий <param paramcode="4866">.
    Якщо жодного не знайдено — повертає [(CAR_BRAND_UNIVERSAL, 'універсальна')].
    """
    found = []
    name_lower = name.lower()
    for brand_lower, (valuecode, name_ua) in car_brand_map.items():
        pattern = r'\b' + re.escape(brand_lower) + r'\b'
        if re.search(pattern, name_lower):
            found.append((valuecode, name_ua))
    return found if found else [(CAR_BRAND_UNIVERSAL, 'універсальна')]


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
    car_brand_map = _load_car_brand_map()

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
    price_samples: list[tuple] = []  # (article, cat_code, rrc, sell_price)

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

        sell_price = calc_sell_price(price, cat_code)
        if len(price_samples) < 5:
            price_samples.append((article, cat_code, price, sell_price))

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
            v_code = OTHER_BRAND_CODE
            v_text = 'Інше'
            cnt_vendor_other += 1
            vendor_unknown_stats[vendor] = vendor_unknown_stats.get(vendor, 0) + 1
            if vendor not in _unknown_vendors_warned:
                logger.warning(f"Невідомий бренд → Єпіцентр 'Інше': '{vendor}'")
                _unknown_vendors_warned.add(vendor)

        avail = 'true'

        offer: list[str] = [
            f'  <offer id="{escape_xml(article)}" available="{avail}">',
            f'    <price>{sell_price:.2f}</price>',
            f'    <category code="{escape_xml(cat_code)}">{escape_xml(cat_name)}</category>',
            f'    <attribute_set code="{escape_xml(cat_code)}">{escape_xml(cat_name)}</attribute_set>',
            f'    <name lang="ua">{escape_xml(name)}</name>',
            f'    <name lang="ru">{escape_xml(name)}</name>',
        ]

        for pic_url in pictures[:10]:
            if pic_url:
                offer.append(f'    <picture>{escape_xml(pic_url)}</picture>')

        if desc:
            offer.append(f'    <description lang="ua">{escape_xml(desc)}</description>')

        if v_code:
            brand_param = f'    <param name="Бренд" paramcode="brand" valuecode="{escape_xml(v_code)}">{escape_xml(v_text)}</param>'
        else:
            brand_param = f'    <param name="Бренд" paramcode="brand">{escape_xml(v_text)}</param>'

        extra_params = get_category_params(cat_code, name, car_brand_map)

        offer += [
            f'    <vendor code="{escape_xml(v_code)}">{escape_xml(v_text)}</vendor>',
            f'    <country_of_origin code="{COUNTRY_CODE}">{COUNTRY_NAME}</country_of_origin>',
            '    <param name="Міра виміру" paramcode="measure" valuecode="measure_pcs">шт.</param>',
            '    <param name="Мінімальна кратність товару" paramcode="ratio">1</param>',
            brand_param,
            *extra_params,
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
    if price_samples:
        print(f'\n  Приклади ціноутворення (РРЦ → ціна з комісією 15%):')
        print(f'  {"Артикул":<20} {"Кат":>6}  {"РРЦ (uah)":>12}  {"→":>2}  {"Ціна продажу":>12}  {"Надбавка":>8}')
        for art, cat, rrc, sp in price_samples:
            markup = sp - rrc
            print(f'  {art:<20} {cat:>6}  {rrc:>12.2f}  {"→":>2}  {sp:>12.2f}  {markup:>+8.2f}')
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
