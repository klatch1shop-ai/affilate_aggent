#!/usr/bin/env python3
"""Звірка цін на noire.com.ua з роздрібною ціною SexOpt.

Навіщо: сайт (Хорошоп) живе окремо від наших фідів — синхронізація оновлює
Єпіцентр і Rozetka, а картку на сайті ніхто автоматично не чіпає. Коли SexOpt
піднімає РРЦ, на сайті якийсь час висить стара, нижча ціна. Це порушує
правило постачальника «мінімальна ціна на всіх каналах = роздрібна ціна
SexOpt». Знайдено на SO2818: сайт 4369, РРЦ 4579.

Перевіряємо ТІЛЬКИ товари, у яких ціна змінилась у поточному циклі — скрейп
усіх 13 тис. карток щодня надто дорогий і сайту, і нам.

Нічого не виправляємо. Хорошоп — окрема система, автоматична зміна цін там
без явного дозволу власника неприпустима. Модуль лише повідомляє.

Чому requests, а не Camoufox: на noire.com.ua стоїть JS-челендж, але він
декоративний — цикл нічого не обчислює, а значення cookie віддається прямо
в тілі тієї ж сторінки. Досить прочитати hash і поставити cookie. Це
принципово: синхронізація крутиться на usa1 (3,8 ГБ RAM), і запускати там
Firefox кожні дві години не можна.

Запуск:
    python3 tools/noire_site_price_check.py --skus SO2818,SO6627
    python3 tools/noire_site_price_check.py --changed-only   # з БД, за добу
"""
import argparse
import difflib
import os
import re
import sys
import time

import requests
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

SITE = 'https://noire.com.ua'
SITEMAP = f'{SITE}/content/export/noire.com.ua/catalog-sitemap.xml'
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')

# Скільки карток максимум відкриваємо за один цикл. Оберіг від дня, коли
# постачальник перерахує пів каталогу: краще перевірити частину й сказати
# про це, ніж на годину завісити дволінійний cron.
MAX_CHECKS = int(os.getenv('NOIRE_SITE_CHECK_MAX', '60'))
PAUSE = float(os.getenv('NOIRE_SITE_CHECK_PAUSE', '0.7'))

TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'h', 'ґ': 'g', 'д': 'd', 'е': 'e',
    'є': 'ie', 'ж': 'zh', 'з': 'z', 'и': 'y', 'і': 'i', 'ї': 'i', 'й': 'i',
    'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
    'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch',
    'ш': 'sh', 'щ': 'shch', 'ь': '', 'ю': 'iu', 'я': 'ia', "'": '', '’': '',
}


def slugify(name: str) -> str:
    """Назва товару → слаг у тій самій транслітерації, що вживає Хорошоп."""
    s = ''.join(TRANSLIT.get(c, c) for c in (name or '').lower())
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def open_session():
    """Сесія з пройденим челенджем. None, якщо сайт недоступний."""
    s = requests.Session()
    s.headers['User-Agent'] = UA
    try:
        r = s.get(f'{SITE}/', timeout=30)
        m = re.search(r'defaultHash\s*=\s*"([a-f0-9]+)"', r.text)
        if m:
            s.cookies.set('challenge_passed', m.group(1),
                          domain='noire.com.ua', path='/')
        return s
    except requests.RequestException as e:
        logger.warning(f'Сайт недоступний: {e}')
        return None


def load_catalog(session) -> dict:
    """слаг → URL для всіх карток сайту (одна сторінка sitemap)."""
    try:
        r = session.get(SITEMAP, timeout=60)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f'sitemap недоступний: {e}')
        return {}
    urls = re.findall(r'<loc>(.*?)</loc>', r.text)
    return {u.rstrip('/').rsplit('/', 1)[-1]: u for u in urls}


def site_price(session, url: str):
    """Ціна з мікророзмітки картки. None, якщо сторінки чи ціни немає."""
    try:
        r = session.get(url, timeout=30)
        if r.status_code != 200:
            return None
        m = re.search(r'itemprop="price"[^>]*content="([\d.]+)"', r.text)
        return float(m.group(1)) if m else None
    except (requests.RequestException, ValueError):
        return None


def check(items: list, max_checks: int = MAX_CHECKS) -> dict:
    """items: [(sku, name, price_retail)] → результат звірки.

    Порушенням вважаємо лише ціну сайту НИЖЧУ за РРЦ. Вища ціна правила
    постачальника не порушує: РРЦ — це мінімум, а не фікс.
    """
    out = {'checked': 0, 'skipped': len(items), 'not_found': 0,
           'below': [], 'above': 0, 'equal': 0}
    if not items:
        return out

    session = open_session()
    if session is None:
        return out
    catalog = load_catalog(session)
    if not catalog:
        return out

    slugs = list(catalog)
    for sku, name, retail in items[:max_checks]:
        out['skipped'] -= 1
        match = difflib.get_close_matches(slugify(name), slugs, n=1, cutoff=0.9)
        if not match:
            out['not_found'] += 1
            continue
        price = site_price(session, catalog[match[0]])
        time.sleep(PAUSE)
        if price is None:
            out['not_found'] += 1
            continue
        out['checked'] += 1
        if price < float(retail) - 0.5:
            out['below'].append((sku, price, float(retail), catalog[match[0]]))
        elif price > float(retail) + 0.5:
            out['above'] += 1
        else:
            out['equal'] += 1

    if out['below']:
        logger.warning(f"Ціна сайту нижча за РРЦ: {len(out['below'])} поз.")
    logger.info(f"Звірка сайту: перевірено {out['checked']}, збіг "
                f"{out['equal']}, нижче РРЦ {len(out['below'])}, "
                f"вище {out['above']}, не знайдено {out['not_found']}")
    return out


def tg_lines(res: dict, limit: int = 8) -> str:
    """Рядки для Telegram-звіту. Порожньо, якщо порушень немає."""
    if not res.get('below'):
        return ''
    msg = (f"\n\n⚠️ <b>Ціна сайту нижча за РРЦ: {len(res['below'])} поз.</b>"
           f"\nОнови картки в Хорошопі вручну")
    for sku, price, retail, _ in res['below'][:limit]:
        msg += f"\n{sku}: сайт {price:.0f} &lt; РРЦ {retail:.0f}"
    if len(res['below']) > limit:
        msg += f"\n… ще {len(res['below']) - limit}"
    if res.get('skipped'):
        msg += f"\n(не перевірено через ліміт: {res['skipped']})"
    return msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skus', help='через кому')
    ap.add_argument('--limit', type=int, default=MAX_CHECKS)
    a = ap.parse_args()

    from shared.utils.db import get_connection
    conn = get_connection()
    cur = conn.cursor()
    if a.skus:
        cur.execute('SELECT sku, name, price_retail FROM sexopt_products '
                    'WHERE sku = ANY(%s)', (a.skus.split(','),))
    else:
        cur.execute('SELECT sku, name, price_retail FROM sexopt_products '
                    'WHERE available IS TRUE AND price_retail > 0 '
                    'ORDER BY random() LIMIT %s', (a.limit,))
    items = [(r['sku'], r['name'], r['price_retail']) for r in cur.fetchall()]
    cur.close()
    conn.close()

    res = check(items, a.limit)
    for sku, price, retail, url in res['below']:
        print(f'{sku}: сайт {price:.0f} < РРЦ {retail:.0f}  {url}')


if __name__ == '__main__':
    main()
