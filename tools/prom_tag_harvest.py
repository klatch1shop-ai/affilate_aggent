#!/usr/bin/env python3
"""Широкий шар семантичного ядра — з тегових сторінок каталогу Prom.

Наші шаблони дають переважно «точні» фрази: тип + бренд + модель. Широкий
шар (категорія + призначення, без бренду) потрібен окремо — за ним шукає
покупець, який ще не обрав марку.

Джерело — самі тегові сторінки Prom. На сторінці категорії майданчик
виводить перелік посилань на кшталт «Жіночі вібратори», «Вібратор для
клітора», «Вібратор мова». Це фрази, під які Prom **завів окрему сторінку**,
тобто вважає їх вартими індексації — прямий сигнал попиту, не здогадка.

Автодоповнення пошуку зняти не вдалося: у headless підказки не рендеряться,
XHR не перехоплюється. Тегові сторінки дають той самий сигнал і стабільно.

Запуск:
    python3 tools/prom_tag_harvest.py --list
    python3 tools/prom_tag_harvest.py --report
"""
import argparse, json, os, re, sys, time
import psycopg2.extras
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection

OUT = os.path.join(BASE_DIR, 'docs', 'prom_tags.json')
# Збираємо не з вгаданих адрес категорій, а зі сторінки ПОШУКУ за словом
# категорії: там Prom сам виводить свої тегові сторінки, зокрема з піддомену
# love.prom.ua. Вгадування URL дало нуль для «Лубрикантів» і «БДСМ» —
# найбільших категорій каталогу.
CATS = {
    'Вібратори': 'вібратор',
    'Мастурбатори': 'мастурбатор',
    'Анальні пробки': 'анальна пробка',
    'Фалоімітатори': 'фалоімітатор',
    'Лубриканти': 'лубрикант',
    'Бдсм-іграшки': 'бдсм',
    'Вакуумні стимулятори': 'вакуумний стимулятор',
    'Страпони': 'страпон',
    'Вакуумні помпи': 'вакуумна помпа',
    'Презервативи': 'презерватив',
    'Масажери простати': 'масажер простати',
    'Вагінальні кульки': 'вагінальні кульки',
    'Еротичні подарунки': 'еротичний подарунок',
    'Збуджуючі засоби': 'збуджуючий засіб',
    'Насадки на член та ерекційні кільця': 'ерекційне кільце',
    'Секс-машини': 'секс машина',
}
# російські відповідники — щоб російський шар збирався симетрично, а не
# лишався бідним, як це вже одного разу сталося з keywords
CATS_RU = {
    'Вібратори': 'вибратор', 'Мастурбатори': 'мастурбатор',
    'Анальні пробки': 'анальная пробка', 'Фалоімітатори': 'фаллоимитатор',
    'Лубриканти': 'лубрикант', 'Бдсм-іграшки': 'бдсм',
    'Вакуумні стимулятори': 'вакуумный стимулятор', 'Страпони': 'страпон',
    'Вакуумні помпи': 'вакуумная помпа', 'Презервативи': 'презерватив',
    'Масажери простати': 'массажер простаты', 'Вагінальні кульки': 'вагинальные шарики',
    'Еротичні подарунки': 'эротический подарок', 'Збуджуючі засоби': 'возбуждающее средство',
    'Насадки на член та ерекційні кільця': 'эрекционное кольцо',
    'Секс-машини': 'секс машина',
}
BAD = re.compile(r'купити|ціна|дешев|акці|знижк|доставк|магазин|prom|розетк', re.I)


def ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS prom_category_tags (
        category TEXT NOT NULL, phrase TEXT NOT NULL, url TEXT,
        found_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY (category, phrase))""")


def harvest(page, url):
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_timeout(4000)
    page.mouse.wheel(0, 9000)
    page.wait_for_timeout(2500)
    out = []
    for a in page.locator('a').all():
        try:
            h = a.get_attribute('href') or ''
            t = (a.inner_text() or '').strip()
        except Exception:
            continue
        if not t or BAD.search(t):
            continue
        # тегова сторінка: /ua/Щось.html без ідентифікатора товару
        # Тегова сторінка Prom. Українська версія має префікс /ua/, а
        # РОСІЙСЬКА — без префікса взагалі (prom.ua/search → love.prom.ua/
        # Zhenskie-vibratory.html). Вимога префікса відкидала весь російський
        # шар: 0 фраз на 16 категорій.
        if re.search(r'/(?:(?:ua|ru)/)?[A-Za-z][\w\-]+\.html$', h) \
                and not re.search(r'/c\d+-', h):
            if 2 <= len(t.split()) <= 5 and t.lower() not in [x[0] for x in out]:
                out.append((t.lower(), h))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur); conn.commit()

    if a.report:
        cur.execute("""SELECT category, count(*) c FROM prom_category_tags
                       GROUP BY 1 ORDER BY c DESC""")
        for r in cur.fetchall():
            cur.execute("""SELECT phrase FROM prom_category_tags
                           WHERE category=%s ORDER BY phrase LIMIT 6""", (r['category'],))
            ph = ', '.join(x['phrase'] for x in cur.fetchall())
            print(f"{r['category'][:24]:26} {r['c']:3}  {ph[:96]}")
        return

    from camoufox.sync_api import Camoufox
    total = 0
    with Camoufox(headless=True, humanize=True, geoip=True, locale='uk-UA') as br:
        page = br.new_page(); page.set_default_timeout(60000)
        jobs = ([(c, 'ua', q) for c, q in CATS.items()]
                + [(c, 'ru', q) for c, q in CATS_RU.items()])
        for cat, lang, term in jobs:
            # російська версія — без мовного префікса в шляху
            pref = 'ua/' if lang == 'ua' else ''
            url = (f'https://prom.ua/{pref}search?search_term='
                   + term.replace(' ', '%20'))
            try:
                tags = harvest(page, url)
            except Exception as e:
                print(f'{cat}: {type(e).__name__}'); continue
            if tags:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO prom_category_tags (category, phrase, url, lang)
                    VALUES %s ON CONFLICT DO NOTHING""",
                    [(cat, t, h, lang) for t, h in tags])
                conn.commit()
            total += len(tags)
            print(f'{cat[:24]:26} [{lang}] {len(tags):3} фраз', flush=True)
            time.sleep(2)
    print(f'\nусього зібрано: {total}')


if __name__ == '__main__':
    main()
