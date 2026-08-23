#!/usr/bin/env python3
"""
agents/orders/supplier_stock.py
================================
ЄДИНА служба наявності в постачальника — спільна для Єпіцентру, Rozetka і Prom.
Постачальники ті самі на всіх майданчиках, тому логіка має бути одна.

Відповідає на одне питання: «чи є цей артикул у постачальника прямо зараз».
Нічого не змінює, статусів не рухає, замовлень не скасовує.

ТРИ СТАНИ, і третій обовʼязковий:
    in_stock      — постачальник каже, що є
    out_of_stock  — постачальник каже, що немає
    unknown       — не змогли дізнатись (фід не відповів, артикул не наш)

«unknown» НІКОЛИ не прирівнювати до «немає»: скасоване через нашу помилку
замовлення коштує дорожче, ніж затримка. Правило з SKILL-19.

СЕМАНТИКА ФІДІВ РІЗНА — це головна пастка:
  • Carvol  — у фіді ЛИШЕ available="true"; відсутність артикула = немає.
              Обережно: наявність Carvol доведено ненадійною (артикул був у
              фіді з залишком, а в постачальника його не було, 08.2026).
  • TOPTUL  — у фіді є і "true", і "false"; читаємо як є.
  • SexOpt  — xls із кількістю; поріг зняття з продажу ≤1 шт (як у
              tools/noire_stock_sync.py).

Строк, який визначає поведінку: на підтвердження замовлення в Єпіцентрі є
2 години, далі блокування компанії (SKILL-20). Тому в кожного джерела —
жорсткий таймаут, а відмова джерела дає «unknown», а не зупинку.

Запуск:
    python3 agents/orders/supplier_stock.py SO1340 QBR-W GAAE1616
    python3 agents/orders/supplier_stock.py --selftest
"""
import os
import sys
import json
import time
import argparse
import xml.etree.ElementTree as ET

import requests
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))

CACHE_DIR = '/tmp/supplier_stock'
CACHE_TTL = int(os.getenv('SUPPLIER_STOCK_TTL', '900'))     # 15 хв
TIMEOUT   = 90

IN, OUT, UNKNOWN = 'in_stock', 'out_of_stock', 'unknown'

CARVOL_FEED = ('https://carvol.prom.ua/rozetka_feed.xml'
               '?rozetka_hash_tag=2251d0779efad97117ac08d7efd82c2f'
               '&product_ids=&label_ids=&languages=uk%2Cru&group_ids=')
TOPTUL_FEED = ('https://toptul.online/products_feed.xml'
               '?hash_tag=442309995a1416e3104d287504a1846f&sales_notes=&product_ids='
               '&label_ids=3882792&exclude_fields=&html_description=1&yandex_cpa='
               '&process_presence_sure=&languages=uk%2Cru&group_ids=')
SEXOPT_XLS  = 'https://smtm.com.ua/_prices/price-retail-horoshop.xls'
SEXOPT_MIN  = 1          # ≤1 шт вважаємо «немає» — як у noire_stock_sync


# ─────────────────────────────────────────────────────────────────────────────
# кеш: у сплеску замовлень не тягнемо фід по разу на позицію
# ─────────────────────────────────────────────────────────────────────────────
def _cache_path(name):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f'{name}.json')


def _cache_read(name):
    p = _cache_path(name)
    if not os.path.exists(p):
        return None
    if time.time() - os.path.getmtime(p) > CACHE_TTL:
        return None
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _cache_write(name, data):
    try:
        with open(_cache_path(name), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f'кеш {name}: {e}')


def _norm(sku):
    return str(sku or '').strip().upper()


# ─────────────────────────────────────────────────────────────────────────────
# джерела
# ─────────────────────────────────────────────────────────────────────────────
def _xml_offers(url, name):
    """{SKU: available} з YML-фіду. None = джерело не відповіло."""
    cached = _cache_read(name)
    if cached is not None:
        return cached
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        logger.error(f'{name}: фід не прочитано — {e}')
        return None
    out = {}
    for o in root.findall('.//offer'):
        av = (o.get('available') or '').strip().lower() == 'true'
        for tag in ('vendorCode', 'article'):
            v = _norm(o.findtext(tag))
            if v:
                out[v] = av
        if o.get('id'):
            out.setdefault(_norm(o.get('id')), av)
    _cache_write(name, out)
    logger.info(f'{name}: {len(out)} артикулів')
    return out


def carvol_map():
    return _xml_offers(CARVOL_FEED, 'carvol')


def toptul_map():
    return _xml_offers(TOPTUL_FEED, 'toptul')


def sexopt_map():
    """{SKU: кількість} з роздрібного xls SexOpt. None = не прочитано."""
    cached = _cache_read('sexopt')
    if cached is not None:
        return cached
    try:
        import io, xlrd
        r = requests.get(SEXOPT_XLS, timeout=TIMEOUT)
        r.raise_for_status()
        wb = xlrd.open_workbook(file_contents=r.content)
        sh = wb.sheet_by_index(0)
    except Exception as e:
        logger.error(f'sexopt: xls не прочитано — {e}')
        return None

    head = [str(sh.cell_value(0, c)).strip().lower() for c in range(sh.ncols)]
    def col(*names):
        for i, h in enumerate(head):
            if any(n in h for n in names):
                return i
        return None
    c_sku = col('артикул', 'sku', 'код')
    c_qty = col('кільк', 'колич', 'наявн', 'залиш', 'stock', 'qty')
    if c_sku is None:
        logger.error(f'sexopt: не знайдено колонку артикула у {head[:8]}')
        return None

    out = {}
    for r_i in range(1, sh.nrows):
        sku = _norm(sh.cell_value(r_i, c_sku))
        if not sku:
            continue
        qty = 0.0
        if c_qty is not None:
            try:
                qty = float(str(sh.cell_value(r_i, c_qty)).replace(',', '.').strip() or 0)
            except Exception:
                qty = 0.0
        out[sku] = qty
    _cache_write('sexopt', out)
    logger.info(f'sexopt: {len(out)} артикулів (колонка кількості: '
                f'{head[c_qty] if c_qty is not None else "НЕМАЄ"})')
    return out


# ─────────────────────────────────────────────────────────────────────────────
# перевірка
# ─────────────────────────────────────────────────────────────────────────────
def check(skus) -> dict:
    """
    {SKU: {'state', 'supplier', 'source', 'qty', 'note'}}
    Джерела тягнуться один раз на виклик і кешуються на CACHE_TTL.
    """
    skus = [_norm(s) for s in skus if _norm(s)]
    if not skus:
        return {}
    cv, tp, sx = carvol_map(), toptul_map(), sexopt_map()
    res = {}
    for sku in skus:
        if sx is not None and sku in sx:
            qty = sx[sku]
            res[sku] = {'state': IN if qty > SEXOPT_MIN else OUT,
                        'supplier': 'sexopt', 'source': 'price-retail-horoshop.xls',
                        'qty': qty, 'note': f'поріг ≤{SEXOPT_MIN} шт = немає'}
        elif tp is not None and sku in tp:
            res[sku] = {'state': IN if tp[sku] else OUT, 'supplier': 'toptul',
                        'source': 'products_feed.xml', 'qty': None,
                        'note': 'фід має явні true/false'}
        elif cv is not None and sku in cv:
            res[sku] = {'state': IN, 'supplier': 'carvol',
                        'source': 'rozetka_feed.xml', 'qty': None,
                        'note': 'у фіді Carvol лише true; наявність доведено ненадійною'}
        elif cv is not None and sx is not None and tp is not None:
            # усі три джерела живі й ніде немає — для Carvol це означає «немає»,
            # але ми не знаємо, чий це артикул, тому чесно: невідомо
            res[sku] = {'state': UNKNOWN, 'supplier': None, 'source': None,
                        'qty': None, 'note': 'артикула немає в жодному фіді'}
        else:
            dead = [n for n, m in (('carvol', cv), ('toptul', tp), ('sexopt', sx))
                    if m is None]
            res[sku] = {'state': UNKNOWN, 'supplier': None, 'source': None,
                        'qty': None, 'note': f'джерела не відповіли: {", ".join(dead)}'}
    return res


ICON = {IN: '✅', OUT: '❌', UNKNOWN: '❓'}


def format_line(sku, r) -> str:
    q = f' ({r["qty"]:g} шт)' if r.get('qty') is not None else ''
    sup = f' · {r["supplier"]}' if r.get('supplier') else ''
    return f'{ICON[r["state"]]} {sku}{q}{sup}'


def selftest():
    for name, fn in (('carvol', carvol_map), ('toptul', toptul_map), ('sexopt', sexopt_map)):
        m = fn()
        if m is None:
            print(f'  {name:8} НЕ ВІДПОВІВ')
        else:
            vals = list(m.values())[:3]
            print(f'  {name:8} {len(m):6} артикулів | приклади значень: {vals}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('skus', nargs='*')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest or not a.skus:
        selftest()
        return
    for sku, r in check(a.skus).items():
        print(f'{format_line(sku, r):46} {r["note"]}')


if __name__ == '__main__':
    main()
