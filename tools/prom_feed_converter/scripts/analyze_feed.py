"""
analyze_feed.py
---------------
Аналіз вхідного файлу від постачальника: XLS/XLSX/CSV/XML/YML.
Підтримує URL — завантажує автоматично.

Запуск:
  python3 analyze_feed.py файл.xlsx
  python3 analyze_feed.py файл.xml
  python3 analyze_feed.py https://example.com/feed.xml
"""
import sys
import os
import re
import tempfile
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from datetime import datetime

import chardet
import pandas as pd


# ── Шляхи ────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
OUTPUT_DIR  = SCRIPT_DIR.parent / 'output'
REPORT_PATH = OUTPUT_DIR / 'analysis_report.txt'

# ── Словники для авто-маппінгу ────────────────────────────────────────────────
MAPPING_KEYWORDS = {
    'name':         ['назва', 'наименование', 'найменування', 'название', 'name', 'title',
                     'товар', 'product', 'номенклатура'],
    'article':      ['артикул', 'article', 'sku', 'код товара', 'код товару', 'part number',
                     'partnumber', 'part_number', 'oem', 'номер', 'vendorcode'],
    'price':        ['ціна', 'цена', 'price', 'вартість', 'стоимость', 'прайс'],
    'availability': ['наявність', 'наличие', 'available', 'склад', 'залишок', 'остаток',
                     'кількість', 'количество', 'qty', 'stock', 'в наличии'],
    'category':     ['категорія', 'категория', 'category', 'categoryid', 'category_name',
                     'розділ', 'раздел', 'группа', 'група', 'тип', 'type'],
    'photo':        ['фото', 'photo', 'image', 'зображення', 'картинка', 'picture', 'img',
                     'url', 'посилання', 'ссылка', 'link'],
    'description':  ['опис', 'описание', 'description', 'характеристика', 'характеристики',
                     'детальний', 'подробное'],
    'car_brand':    ['марка', 'бренд', 'brand', 'виробник', 'производитель', 'make',
                     'автомобіль', 'автомобиль', 'vendor', 'param__марка',
                     'param__марка авто', 'param__виробник'],
    'car_model':    ['модель', 'model', 'модифікація', 'модификация',
                     'param__модель', 'param__модель авто'],
    'year':         ['рік', 'год', 'year', 'роки', 'годы', 'від', 'до', 'від-до',
                     'param__рік', 'param__год', 'param__роки випуску'],
}

MAPPING_LABELS = {
    'name':         'Назва товару',
    'article':      'Артикул / SKU',
    'price':        'Ціна',
    'availability': 'Наявність / Кількість',
    'category':     'Категорія',
    'photo':        'Фото / URL',
    'description':  'Опис',
    'car_brand':    'Марка авто',
    'car_model':    'Модель авто',
    'year':         'Рік',
}

# Теги які відображаємо у прикладі рядків (решта param__ можуть бути сотні)
XML_CORE_COLS = ('id', 'available', 'name', 'price', 'oldprice', 'currencyId',
                 'categoryId', 'category_name', 'vendor', 'vendorCode',
                 'article', 'barcode', 'picture', 'description')


# ── Завантаження URL ──────────────────────────────────────────────────────────

def download_url(url: str) -> tuple[str, str]:
    """
    Завантажує URL у тимчасовий файл.
    Повертає (local_path, detected_ext).
    """
    print(f'Завантажуємо: {url}')
    parsed   = urllib.parse.urlparse(url)
    url_path = parsed.path.lower()

    ext = '.xml'
    for candidate in ('.xml', '.yml', '.xlsx', '.xls', '.csv'):
        if url_path.endswith(candidate):
            ext = candidate
            break

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir='/tmp')
    tmp.close()

    try:
        req = urllib.request.Request(
            url, headers={'User-Agent': 'Mozilla/5.0 FeedAnalyzer/1.0'}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            ct = resp.headers.get('Content-Type', '')
            if ext == '.xml' and 'yml' in ct:
                ext = '.yml'
            data = resp.read()

        with open(tmp.name, 'wb') as f:
            f.write(data)

        size_kb = len(data) / 1024
        print(f'Завантажено {size_kb:.1f} KB → {tmp.name}')
        return tmp.name, ext
    except Exception as e:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        sys.exit(f'Помилка завантаження {url}: {e}')


# ── Зчитування XLS/XLSX/CSV ───────────────────────────────────────────────────

def detect_csv_encoding(path: str) -> str:
    with open(path, 'rb') as f:
        raw = f.read(65536)
    result = chardet.detect(raw)
    return result.get('encoding') or 'utf-8'


def read_tabular(path: str) -> pd.DataFrame:
    ext = Path(path).suffix.lower()

    if ext == '.csv':
        enc = detect_csv_encoding(path)
        for sep in [';', ',', '\t', '|']:
            try:
                df = pd.read_csv(path, sep=sep, encoding=enc, dtype=str,
                                 keep_default_na=False, low_memory=False)
                if df.shape[1] > 1:
                    return df
            except Exception:
                continue
        return pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False)

    if ext == '.xlsx':
        return pd.read_excel(path, engine='openpyxl', dtype=str, keep_default_na=False)

    if ext == '.xls':
        try:
            import xlrd  # noqa: F401
            return pd.read_excel(path, engine='xlrd', dtype=str, keep_default_na=False)
        except ImportError:
            sys.exit(
                'Для читання .xls потрібен xlrd:\n'
                '  pip install xlrd\n'
                'Або конвертуйте файл у .xlsx і запустіть знову.'
            )

    sys.exit(f'Непідтримуваний формат: {ext}')


# ── Зчитування XML/YML ────────────────────────────────────────────────────────

def detect_xml_encoding(raw: bytes) -> str:
    m = re.match(rb'<\?xml[^?]*encoding=["\']([^"\']+)["\']', raw[:500])
    if m:
        return m.group(1).decode('ascii', errors='ignore')
    result = chardet.detect(raw[:65536])
    return result.get('encoding') or 'utf-8'


def _find_offers_root(root: ET.Element) -> ET.Element | None:
    """Шукає <offers> в різних варіантах структури фіду."""
    for path in ('shop/offers', 'offers', './/offers'):
        el = root.find(path)
        if el is not None:
            return el
    return None


def parse_xml_feed(path: str) -> tuple[pd.DataFrame, dict]:
    """
    Парсить YML/XML фід (Prom/Rozetka/Epicentr/Yandex Market).
    Повертає (DataFrame, xml_meta).
    """
    with open(path, 'rb') as f:
        raw = f.read()

    enc = detect_xml_encoding(raw)
    try:
        text = raw.decode(enc, errors='replace')
    except (LookupError, UnicodeDecodeError):
        text = raw.decode('utf-8', errors='replace')

    # ElementTree вимагає bytes з коректним encoding у декларації
    xml_bytes = text.encode('utf-8')
    # Замінюємо оголошення кодування на utf-8 щоб не конфліктувало
    xml_bytes = re.sub(
        rb'(<\?xml[^?]*encoding=)["\'][^"\']+["\']',
        rb'\1"utf-8"',
        xml_bytes[:500]
    ) + xml_bytes[500:]

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        sys.exit(f'Помилка парсингу XML: {e}')

    shop_el = root.find('shop')
    shop    = shop_el if shop_el is not None else root

    # ── Категорії з <categories> ──
    categories: dict[str, str] = {}
    cats_el = shop.find('categories')
    if cats_el is None:
        cats_el = root.find('.//categories')
    if cats_el is not None:
        for cat in cats_el.findall('category'):
            cid  = cat.get('id', '')
            name = (cat.text or '').strip()
            if cid:
                categories[cid] = name

    # ── Offers ──
    offers_el = _find_offers_root(root)
    if offers_el is None:
        sys.exit('Не знайдено тег <offers> у XML файлі.')

    offers = offers_el.findall('offer')
    if not offers:
        sys.exit('<offers> порожній — жодного <offer> не знайдено.')

    rows: list[dict] = []
    param_counter: Counter = Counter()
    n_with_pictures    = 0
    n_with_description = 0

    for offer in offers:
        row: dict[str, str] = {
            'id':        offer.get('id', ''),
            'available': offer.get('available', ''),
        }

        for tag in ('name', 'price', 'oldprice', 'currencyId', 'categoryId',
                    'vendor', 'vendorCode', 'description', 'barcode', 'article'):
            el = offer.find(tag)
            row[tag] = (el.text or '').strip() if el is not None else ''

        pictures = [p.text.strip() for p in offer.findall('picture') if p.text and p.text.strip()]
        row['picture'] = ' | '.join(pictures)
        if pictures:
            n_with_pictures += 1

        if row.get('description'):
            n_with_description += 1

        for param in offer.findall('param'):
            pname = (param.get('name') or '').strip()
            if not pname:
                continue
            param_counter[pname] += 1
            col = f'param__{pname}'
            val = (param.text or '').strip()
            if col in row and row[col]:
                row[col] += f', {val}'
            else:
                row[col] = val

        rows.append(row)

    df = pd.DataFrame(rows).fillna('')

    if categories and 'categoryId' in df.columns:
        df['category_name'] = df['categoryId'].map(categories).fillna('')

    xml_meta = {
        'categories':         categories,
        'n_offers':           len(offers),
        'n_with_pictures':    n_with_pictures,
        'n_with_description': n_with_description,
        'param_counts':       param_counter,
        'encoding':           enc,
    }
    return df, xml_meta


# ── Спільний аналіз ───────────────────────────────────────────────────────────

def fill_stats(df: pd.DataFrame) -> list[tuple[str, float, int]]:
    total = len(df)
    result = []
    for col in df.columns:
        filled = int(df[col].apply(lambda x: bool(str(x).strip())).sum())
        pct    = (filled / total * 100) if total else 0.0
        result.append((col, pct, filled))
    return result


def find_category_column(df: pd.DataFrame, mapping: dict) -> str | None:
    cats = mapping.get('category')
    if cats:
        return cats[0]
    best, best_score = None, 0
    for col in df.columns:
        n_uniq = df[col].nunique()
        if 2 <= n_uniq <= max(50, len(df) * 0.3):
            if n_uniq > best_score:
                best, best_score = col, n_uniq
    return best


def auto_map(df: pd.DataFrame) -> dict[str, list[str]]:
    cols_lower = {col: col.lower().strip() for col in df.columns}
    result: dict[str, list[str]] = {k: [] for k in MAPPING_KEYWORDS}
    for col, col_l in cols_lower.items():
        for field, keywords in MAPPING_KEYWORDS.items():
            for kw in keywords:
                if kw in col_l:
                    if col not in result[field]:
                        result[field].append(col)
                    break
    return result


def category_summary(df: pd.DataFrame, cat_col: str) -> list[tuple[str, int]]:
    counts = df[cat_col].value_counts()
    return [(str(c), int(n)) for c, n in counts.items()]


# ── Форматування звіту ────────────────────────────────────────────────────────

def bar(pct: float, width: int = 20) -> str:
    filled = round(pct / 100 * width)
    return '█' * filled + '░' * (width - filled)


def build_report(
    source:    str,
    local_path: str | None,
    df:         pd.DataFrame,
    xml_meta:   dict | None = None,
) -> str:
    lines: list[str] = []
    W = 72

    def hr(ch='─'):
        lines.append(ch * W)

    def h1(title: str):
        hr('═'); lines.append(f'  {title}'); hr('═')

    def h2(title: str):
        lines.append(''); hr(); lines.append(f'  {title}'); hr()

    is_xml  = xml_meta is not None
    is_url  = source.startswith('http')
    fmt_lbl = 'XML/YML' if is_xml else Path(source).suffix.upper().lstrip('.')

    # ── Заголовок ──
    h1('АНАЛІЗ ФАЙЛУ ПОСТАЧАЛЬНИКА')
    if is_url:
        lines.append(f'  URL     : {source}')
        lines.append(f'  Кеш     : {local_path}')
    else:
        lines.append(f'  Файл    : {source}')
    if local_path and os.path.exists(local_path):
        lines.append(f'  Розмір  : {os.path.getsize(local_path) / 1024:.1f} KB')
    lines.append(f'  Формат  : {fmt_lbl}')
    if is_xml:
        lines.append(f'  Кодування: {xml_meta["encoding"]}')
    lines.append(f'  Дата    : {datetime.now().strftime("%Y-%m-%d %H:%M")}')

    # ── 1. Загальна статистика ──
    h2('1. ЗАГАЛЬНА СТАТИСТИКА')
    lines.append(f'  Рядків (товарів)       : {len(df):,}')
    if is_xml:
        lines.append(f'  Offers у XML           : {xml_meta["n_offers"]:,}')
        lines.append(f'  З картинками           : {xml_meta["n_with_pictures"]:,}  '
                     f'({xml_meta["n_with_pictures"]/max(xml_meta["n_offers"],1)*100:.1f}%)')
        lines.append(f'  З описом               : {xml_meta["n_with_description"]:,}  '
                     f'({xml_meta["n_with_description"]/max(xml_meta["n_offers"],1)*100:.1f}%)')
        n_params = len(xml_meta['param_counts'])
        lines.append(f'  Унікальних param       : {n_params}')
    lines.append(f'  Колонок у DataFrame    : {len(df.columns)}')

    # ── 2. Список колонок ──
    h2('2. КОЛОНКИ ФАЙЛУ')
    core_cols  = [c for c in df.columns if not c.startswith('param__')]
    param_cols = [c for c in df.columns if c.startswith('param__')]
    for i, col in enumerate(core_cols, 1):
        lines.append(f'  {i:>3}. {col}')
    if param_cols:
        lines.append(f'  --- param-характеристики ({len(param_cols)} шт.) ---')
        for i, col in enumerate(param_cols, len(core_cols) + 1):
            lines.append(f'  {i:>3}. {col}')

    # ── 3. Заповненість колонок ──
    h2('3. ЗАПОВНЕНІСТЬ КОЛОНОК  (% непорожніх)')
    stats = fill_stats(df)
    # Окремо core і param, param — тільки заповнені
    core_stats  = [(c, p, n) for c, p, n in stats if not c.startswith('param__')]
    param_stats = [(c, p, n) for c, p, n in stats if c.startswith('param__') and p > 0]
    for col, pct, n in core_stats:
        b = bar(pct)
        lines.append(f'  {col:<30} {b} {pct:5.1f}%  ({n:,}/{len(df):,})')
    if param_stats:
        lines.append('')
        lines.append('  param-характеристики:')
        for col, pct, n in sorted(param_stats, key=lambda x: -x[1]):
            short = col[7:]  # без 'param__'
            b = bar(pct)
            lines.append(f'    {short:<28} {b} {pct:5.1f}%  ({n:,}/{len(df):,})')

    # ── 4. Авто-маппінг ──
    mapping = auto_map(df)
    h2('4. ВИЯВЛЕНІ КОЛОНКИ ДЛЯ МАППІНГУ')
    found_any = False
    for field, cols in mapping.items():
        label = MAPPING_LABELS[field]
        if cols:
            found_any = True
            lines.append(f'  {label:<25} → {", ".join(cols)}')
        else:
            lines.append(f'  {label:<25}   ⚠ не знайдено')
    if not found_any:
        lines.append('  ⚠  Жодного поля не вдалось визначити автоматично.')

    # ── 5. Категорії з DataFrame ──
    cat_col = find_category_column(df, mapping)
    # Для XML краще показувати category_name якщо є
    if is_xml and 'category_name' in df.columns:
        cat_col = 'category_name'

    h2('5. УНІКАЛЬНІ КАТЕГОРІЇ')
    if is_xml and xml_meta['categories']:
        cat_map = xml_meta['categories']
        # Рахуємо offers по categoryId
        if 'categoryId' in df.columns:
            counts_by_id = df['categoryId'].value_counts()
            lines.append(f'  {"ID":<6} {"Назва категорії":<42} {"К-сть":>6}')
            hr()
            for cid, cnt in counts_by_id.items():
                cname = cat_map.get(str(cid), f'(id={cid})')
                cname_t = (cname[:39] + '...') if len(cname) > 42 else cname
                lines.append(f'  {str(cid):<6} {cname_t:<42} {cnt:>6}')
            lines.append('')
            lines.append(f'  Всього унікальних категорій: {len(counts_by_id)}  '
                         f'(у довіднику: {len(cat_map)})')
    elif cat_col:
        lines.append(f'  Колонка: «{cat_col}»')
        lines.append('')
        cats = category_summary(df, cat_col)
        lines.append(f'  {"Категорія":<45} {"К-сть":>6}')
        hr()
        for cat, cnt in cats:
            t = (cat[:42] + '...') if len(cat) > 45 else cat
            lines.append(f'  {t:<45} {cnt:>6}')
        lines.append('')
        lines.append(f'  Всього унікальних категорій: {len(cats)}')
    else:
        lines.append('  ⚠  Колонку категорій не знайдено.')

    # ── 6. Топ param-характеристики (тільки для XML) ──
    if is_xml and xml_meta['param_counts']:
        h2('6. НАЙЧАСТІШІ PARAM-ХАРАКТЕРИСТИКИ')
        top_params = xml_meta['param_counts'].most_common(30)
        total_off  = xml_meta['n_offers']
        lines.append(f'  {"Param name":<35} {"Offers":>7}  {"% покриття":>10}')
        hr()
        for pname, cnt in top_params:
            pct = cnt / total_off * 100
            lines.append(f'  {pname:<35} {cnt:>7}  {pct:>9.1f}%')
        next_section = '7'
    else:
        next_section = '6'

    # ── Приклад рядків ──
    h2(f'{next_section}. ПЕРШІ 3 РЯДКИ (приклад)')
    sample_cols = XML_CORE_COLS if is_xml else df.columns
    sample = df.head(3)
    for i, (_, row) in enumerate(sample.iterrows(), 1):
        lines.append(f'  ─── Рядок {i} ───')
        for col in sample_cols:
            if col not in df.columns:
                continue
            val = str(row[col]).strip()
            if not val:
                continue
            truncated = (val[:55] + '...') if len(val) > 58 else val
            lines.append(f'    {col:<30} : {truncated}')
        # Кілька перших param якщо є
        if is_xml:
            shown = 0
            for col in df.columns:
                if col.startswith('param__') and str(row.get(col, '')).strip():
                    val = str(row[col]).strip()
                    truncated = (val[:55] + '...') if len(val) > 58 else val
                    lines.append(f'    {col:<30} : {truncated}')
                    shown += 1
                    if shown >= 8:
                        remaining = sum(
                            1 for c in df.columns
                            if c.startswith('param__') and str(row.get(c, '')).strip()
                        ) - shown
                        if remaining > 0:
                            lines.append(f'    ... ще {remaining} param ...')
                        break
        lines.append('')

    hr('═')
    lines.append(f'  Звіт збережено: {REPORT_PATH}')
    hr('═')

    return '\n'.join(lines)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print('Використання: python3 analyze_feed.py <файл або URL>')
        print('  Підтримувані формати: xlsx, xls, csv, xml, yml')
        sys.exit(1)

    source    = sys.argv[1]
    local_path: str | None = None
    is_url    = source.lower().startswith('http')
    xml_meta: dict | None = None
    tmp_to_delete: str | None = None

    try:
        if is_url:
            local_path, ext = download_url(source)
            tmp_to_delete   = local_path
        else:
            local_path = source
            ext        = Path(source).suffix.lower()
            if not os.path.exists(local_path):
                sys.exit(f'Файл не знайдено: {local_path}')

        print(f'Читаємо: {local_path}  (формат: {ext})')

        if ext in ('.xml', '.yml'):
            df, xml_meta = parse_xml_feed(local_path)
        else:
            df = read_tabular(local_path)
            df = df.dropna(how='all')
            df.columns = [str(c).strip() for c in df.columns]

        print(f'Завантажено {len(df):,} рядків, {len(df.columns)} колонок')
        print('Аналізуємо...')

        report = build_report(source, local_path, df, xml_meta)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding='utf-8')

        print(report)

    finally:
        if tmp_to_delete and os.path.exists(tmp_to_delete):
            os.unlink(tmp_to_delete)


if __name__ == '__main__':
    main()
