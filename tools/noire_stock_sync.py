#!/usr/bin/env python3
"""
NOIRE / SexOpt → синхронізація ціни та наявності
=================================================

Два режими:

  --quick   кожні 2 год. Джерело: price-retail-horoshop.xls (3,5 МБ).
            Оновлює price_retail і available. Порог зняття з продажу: ≤1 шт.
            Містить і ціну, і кількість, тому важкий XML тут не потрібен.

  --full    раз на добу до 8:00. Джерело: import-retail-ua-2.xml (54 МБ).
            Оновлює описи, фото, характеристики; виявляє нові товари.

Анти-демпінг: наша ціна в Єпіцентрі не може опуститись нижче роздрібної
ціни SexOpt. Формула gross-up це забезпечує лише поки price_retail свіжий —
саме тому quick-цикл і потрібен. Додатково стоїть явна підлога.

Запуск:
    python3 tools/noire_stock_sync.py --quick [--dry]
    python3 tools/noire_stock_sync.py --full  [--dry]
"""
import argparse
import io
import os
import sys
import re
from datetime import datetime

import requests
import xlrd
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

XLS_URL = 'https://smtm.com.ua/_prices/price-retail-horoshop.xls'
XML_URL = 'https://smtm.com.ua/_prices/import-retail-ua-2.xml'

# Позиція знімається з продажу, якщо залишок не більший за це число.
# 1, а не 0: між нашим оновленням і замовленням покупця остання одиниця
# встигає піти, а підтверджене замовлення на відсутній товар — це штраф
# рейтингом від Єпіцентру.
MIN_STOCK = int(os.getenv('NOIRE_MIN_STOCK', '1'))

TG_TOKEN = os.getenv('TG_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT = os.getenv('TG_CHAT_ID') or os.getenv('TELEGRAM_ADMIN_ID')


def tg(text: str):
    if not (TG_TOKEN and TG_CHAT):
        return
    try:
        requests.post(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                      json={'chat_id': TG_CHAT, 'text': text,
                            'parse_mode': 'HTML'}, timeout=15)
    except Exception as e:
        logger.warning(f'TG: {e}')


def parse_price(val) -> float:
    """Ціна з довільного формату (перенесено з epicentr_order_agent.py)."""
    if val is None or val == '':
        return 0.0
    s = str(val).replace('грн', '').replace('\xa0', '').replace(' ', '')
    s = re.sub(r'(\d)\s+(\d)', r'\1\2', s).replace(',', '.').strip()
    m = re.search(r'\d+(?:\.\d+)?', s)
    return float(m.group()) if m else 0.0


def fetch_xls() -> dict:
    """→ {SKU: {'price': float, 'qty': float}}"""
    r = requests.get(XLS_URL, timeout=180)
    r.raise_for_status()
    sh = xlrd.open_workbook(file_contents=r.content).sheet_by_index(0)
    data = {}
    for i in range(1, sh.nrows):
        sku = str(sh.cell_value(i, 0)).strip().upper()
        if not sku:
            continue
        try:
            qty = float(sh.cell_value(i, 4))
        except (ValueError, TypeError):
            qty = 0.0
        data[sku] = {'price': parse_price(sh.cell_value(i, 2)), 'qty': qty}
    logger.info(f'XLS: {len(data)} SKU, у продажу (>{MIN_STOCK}): '
                f'{sum(1 for v in data.values() if v["qty"] > MIN_STOCK)}')
    return data


def quick_sync(dry=False) -> dict:
    live = fetch_xls()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT sku, price_retail, available FROM sexopt_products')
    ours = {r['sku'].strip().upper(): (float(r['price_retail'] or 0),
                                       bool(r['available'])) for r in cur.fetchall()}

    st = {'price': 0, 'off': 0, 'on': 0, 'missing': 0, 'raised': 0}
    price_up, turned_off = [], []

    for sku, (old_price, old_avail) in ours.items():
        info = live.get(sku)
        if not info:
            # у прайсі більше немає — знімаємо з продажу, ціну не чіпаємо
            if old_avail and not dry:
                cur.execute('UPDATE sexopt_products SET available=FALSE WHERE sku=%s',
                            (sku,))
            st['missing'] += 1
            continue

        new_price = info['price']
        new_avail = info['qty'] > MIN_STOCK

        if new_price > 0 and abs(new_price - old_price) > 0.01:
            if not dry:
                cur.execute('UPDATE sexopt_products SET price_retail=%s WHERE sku=%s',
                            (new_price, sku))
            st['price'] += 1
            if new_price > old_price:
                st['raised'] += 1
                price_up.append((sku, old_price, new_price))

        if new_avail != old_avail:
            if not dry:
                cur.execute('UPDATE sexopt_products SET available=%s WHERE sku=%s',
                            (new_avail, sku))
            if new_avail:
                st['on'] += 1
            else:
                st['off'] += 1
                turned_off.append(sku)

    if not dry:
        conn.commit()
    cur.close()
    conn.close()

    logger.info(f"Ціни оновлено: {st['price']} (з них подорожчали {st['raised']}) | "
                f"знято з продажу: {st['off']} | повернуто: {st['on']} | "
                f"немає у прайсі: {st['missing']}")
    st['price_up'] = price_up[:10]
    st['turned_off'] = turned_off[:10]
    return st


def check_antidumping() -> list:
    """Наша ціна в Єпіцентрі vs роздрібна SexOpt.

    Порушення = ціна у фіді нижча за роздрібну постачальника. Такого бути
    не може за формулою gross-up, але перевірка ловить два реальні сценарії:
    застарілий фід після підняття цін постачальником і MARKUP < 1.
    """
    sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
    from noire_epicentr_generator import calc_sell_price

    feed = os.path.join(BASE_DIR, 'output', 'noire_epicentr_phase1.xml')
    if not os.path.exists(feed):
        logger.warning('Фіду немає — перевірку пропущено')
        return []
    xml = open(feed, encoding='utf-8').read()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT sku, price_retail FROM sexopt_products')
    retail = {r['sku'].strip().upper(): float(r['price_retail'] or 0)
              for r in cur.fetchall()}
    cur.close()
    conn.close()

    bad = []
    for m in re.finditer(r'<offer id="([^"]+)".*?<price>([\d.]+)</price>.*?'
                         r'<category code="(\d+)"', xml, re.S):
        sku, price, cat = m.group(1).upper(), float(m.group(2)), m.group(3)
        rp = retail.get(sku, 0)
        if rp and price < rp:
            bad.append((sku, price, rp, calc_sell_price(rp, cat)))
    return bad


def full_sync(dry=False) -> dict:
    """Щоденний прохід: описи/фото/характеристики + нові товари."""
    logger.info('Качаю import-retail-ua-2.xml…')
    r = requests.get(XML_URL, timeout=600)
    r.raise_for_status()
    logger.info(f'Отримано {len(r.content)/1024/1024:.1f} МБ')

    import xml.etree.ElementTree as ET
    root = ET.fromstring(r.content)
    offers = root.findall('.//offer')

    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT sku FROM sexopt_products')
    known = {r['sku'].strip().upper() for r in cur.fetchall()}

    st = {'total': len(offers), 'new': 0, 'desc': 0, 'pics': 0}
    new_skus = []
    for o in offers:
        sku = (o.get('id') or '').strip().upper()
        if not sku:
            continue
        if sku not in known:
            st['new'] += 1
            new_skus.append(sku)
            continue
        d = o.findtext('description')
        if d and d.strip() and not dry:
            cur.execute("""UPDATE sexopt_products SET description_html=%s
                           WHERE sku=%s AND (description_source IS NULL
                                 OR description_source='original')""",
                        (d.strip(), sku))
            if cur.rowcount:
                st['desc'] += 1
        pics = [p.text for p in o.findall('picture') if p.text]
        if pics and not dry:
            cur.execute('UPDATE sexopt_products SET pictures=%s WHERE sku=%s',
                        (pics, sku))
            st['pics'] += 1
    if not dry:
        conn.commit()
    cur.close()
    conn.close()
    st['new_skus'] = new_skus[:20]
    logger.info(f"Офферів у файлі: {st['total']} | нових SKU: {st['new']} | "
                f"описів оновлено: {st['desc']}")
    return st


FEED = os.path.join(BASE_DIR, 'output', 'noire_epicentr_phase1.xml')


def regenerate_feed() -> dict:
    """Перезібрати XML і перевірити валідатором.

    Пишеться через тимчасовий файл і atomic replace: фід можуть у цей момент
    читати або заливати, а половинчастий XML гірший за вчорашній повний.
    Публікація в кабінет НЕ виконується — тільки підтримка файлу в актуальному
    стані, щоб заливка не потребувала ручного кроку «не забути перегенерувати».
    """
    import subprocess, tempfile, shutil, time as _t
    py = sys.executable
    t0 = _t.time()
    tmp = tempfile.NamedTemporaryFile(suffix='.xml', delete=False,
                                      dir=os.path.dirname(FEED)).name
    res = {'ok': False, 'seconds': 0, 'offers': 0,
           'pass': 0, 'warn': 0, 'fail': 0}
    try:
        r = subprocess.run([py, os.path.join(BASE_DIR, 'tools',
                                             'noire_epicentr_generator.py'),
                            '-x', '7216,9464', '-o', tmp],
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or not os.path.getsize(tmp):
            logger.error(f'Генератор впав (rc={r.returncode}): '
                         f'{(r.stderr or "")[-300:]}')
            return res
        v = subprocess.run([py, os.path.join(BASE_DIR, 'tools',
                                             'noire_epicentr_validator.py'), tmp],
                           capture_output=True, text=True, timeout=900)
        out = v.stdout or ''
        for key, pat in (('offers', r'ПІДСУМОК:\s*(\d+)'),
                         ('pass', r'PASS.*?:\s*(\d+)'),
                         ('warn', r'WARN.*?:\s*(\d+)'),
                         ('fail', r'FAIL.*?:\s*(\d+)')):
            m = re.search(pat, out)
            if m:
                res[key] = int(m.group(1))
        # tempfile створює файл з правами 600 — повертаємо звичайні 644,
        # інакше фід стане недоступним для вебсервера чи іншого користувача
        os.chmod(tmp, 0o644)
        shutil.move(tmp, FEED)          # atomic у межах одного розділу
        res['ok'] = True
        res['seconds'] = round(_t.time() - t0, 1)
        logger.info(f"Фід перезібрано за {res['seconds']}с: {res['offers']} офферів, "
                    f"PASS {res['pass']} / WARN {res['warn']} / FAIL {res['fail']}")
    except subprocess.TimeoutExpired:
        logger.error('Генерація фіду перевищила ліміт часу')
    except Exception as e:
        logger.error(f'regenerate_feed: {e}')
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--full', action='store_true')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--no-tg', action='store_true')
    ap.add_argument('--no-regen', action='store_true',
                    help='не перезбирати XML після оновлення БД')
    a = ap.parse_args()
    logger.add(os.path.join(BASE_DIR, 'logs', 'noire_sync.log'),
               rotation='10 MB', retention='30 days')

    if a.quick:
        st = quick_sync(dry=a.dry)
        changed = st['price'] + st['off'] + st['on'] + st['missing']
        feed = {}
        if changed and not a.dry and not a.no_regen:
            feed = regenerate_feed()
        elif not changed:
            logger.info('Змін немає — фід не перезбирався')
        bad = check_antidumping()
        msg = (f"🔄 <b>NOIRE sync</b> {datetime.now():%H:%M}\n"
               f"Ціни: {st['price']} (↑{st['raised']})\n"
               f"Знято з продажу: {st['off']} | повернуто: {st['on']}\n"
               f"Немає у прайсі: {st['missing']}")
        if feed.get('ok'):
            msg += (f"\n\n📄 Фід оновлено за {feed['seconds']}с: "
                    f"{feed['offers']} офферів, готово "
                    f"<b>{feed['pass'] + feed['warn']}</b>, FAIL {feed['fail']}")
        elif feed:
            msg += "\n\n❌ <b>Перезбирання фіду не вдалось</b> — дивись лог"
        if bad:
            msg += f"\n\n⚠️ <b>Демпінг: {len(bad)} поз.</b> — фід нижчий за прайс SexOpt"
            for sku, p, rp, need in bad[:5]:
                msg += f"\n{sku}: {p:.0f} &lt; {rp:.0f} (треба {need:.0f})"
            msg += "\nПотрібна перегенерація фіду"
        logger.info(f'Анти-демпінг: порушень {len(bad)}')
        if not a.no_tg and (st['price'] or st['off'] or bad):
            tg(msg)
    elif a.full:
        st = full_sync(dry=a.dry)
        if not a.no_tg and st['new']:
            tg(f"📦 <b>NOIRE: нові товари у постачальника</b>\n"
               f"{st['new']} шт — потребують класифікації та описів\n"
               f"Приклади: {', '.join(st['new_skus'][:8])}")
    else:
        ap.print_help()


if __name__ == '__main__':
    main()
