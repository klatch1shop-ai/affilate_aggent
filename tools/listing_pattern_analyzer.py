#!/usr/bin/env python3
"""«Ідеальна картка»: витяг патерну оформлення з живих карток маркетплейсу.

Той самий підхід, що Helium10 Listing Analyzer чи SellerSprite на Amazon:
беремо вибірку вже опублікованих карток тієї самої категорії того самого
майданчика, знімаємо з них СТРУКТУРУ й перетворюємо на правила генерації.

Чому вибірка, а не один зразок: один приклад дає здогадку, десять дають
патерн. Характеристику вважаємо обовʼязковою для категорії, якщо вона
заповнена у більшості карток (перетин, не обʼєднання) — саме так
відрізняється «так прийнято» від «так зробив один продавець».

КРИТИЧНЕ ПРАВИЛО. Синтезуємо шаблон, ніколи не копіюємо текст. Причина не
лише авторська: дубльований опис знижує власну картку в пошуку й позбавляє
магазин упізнаваного голосу. З чужих карток беремо порядок полів, набір
характеристик, типові довжини — і жодного речення.

Каталог і назви читаються звичайним requests. Характеристики та опис
рендеряться клієнтським JS, тому там потрібен Camoufox.

Запуск:
    python3 tools/listing_pattern_analyzer.py \\
        --marketplace rozetka --category 4647534 \\
        --url "https://rozetka.com.ua/ua/eroticheskoe-bele/c4647534/producer=passion/" \\
        --sample 10 --label "Еротична білизна"
    python3 tools/listing_pattern_analyzer.py --report
"""
import argparse
import collections
import json
import os
import re
import sys
import time

import requests
import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
PRODUCT_RE = re.compile(r'https://rozetka\.com\.ua/ua/[a-z0-9\-]+/p\d+/')
# Частка карток, з якої характеристика вважається нормою категорії
REQUIRED_SHARE = 0.6


def ensure_tables(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS listing_samples (
            marketplace TEXT NOT NULL,
            category    TEXT NOT NULL,
            url         TEXT NOT NULL,
            title       TEXT,
            chars       JSONB,
            desc_len    INTEGER,
            photos      INTEGER,
            fetched_at  TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (marketplace, category, url)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS listing_patterns (
            marketplace  TEXT NOT NULL,
            category     TEXT NOT NULL,
            label        TEXT,
            sample_size  INTEGER,
            name_order   TEXT,
            required     JSONB,
            optional     JSONB,
            desc_median  INTEGER,
            photo_median INTEGER,
            notes        TEXT,
            built_at     TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (marketplace, category)
        )
    """)


def collect_urls(cat_url: str, n: int) -> list:
    """Посилання на картки з видачі категорії — звичайним запитом."""
    r = requests.get(cat_url, headers={'User-Agent': UA}, timeout=60)
    r.raise_for_status()
    urls = list(dict.fromkeys(PRODUCT_RE.findall(r.text)))
    logger.info(f'У видачі знайдено карток: {len(urls)}')
    return urls[:n]


def scrape_cards(urls: list) -> list:
    """Назва, характеристики, довжина опису, кількість фото — через Camoufox."""
    from camoufox.sync_api import Camoufox
    out = []
    with Camoufox(headless=True, humanize=True, geoip=True, locale='uk-UA') as br:
        page = br.new_page()
        page.set_default_timeout(45000)
        for i, u in enumerate(urls, 1):
            rec = {'url': u, 'title': None, 'chars': {}, 'desc_len': 0,
                   'photos': 0}
            try:
                page.goto(u + 'characteristics/', wait_until='domcontentloaded')
                page.wait_for_timeout(4500)
                rec['title'] = (page.title() or '').split(' – ')[0].strip()
                # Характеристики Rozetka віддає списком визначень <dl>:
                # назва в <dt>, значення в <dd>. Розбір усього тексту сторінки
                # тут не працює — у нього потрапляють блоки доставки й продавця.
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(2000)
                for dl in page.locator('dl').all():
                    try:
                        dts = [x.strip().rstrip(':')
                               for x in dl.locator('dt').all_inner_texts()]
                        dds = [x.strip()
                               for x in dl.locator('dd').all_inner_texts()]
                    except Exception:
                        continue
                    # inner_text усього <dl> склеює dt і dd в один потік і
                    # збивається на багаторядкових значеннях — тому окремо
                    for k, v in zip(dts, dds):
                        if (2 < len(k) < 42 and 1 < len(v) < 160
                                and k not in ('Код', 'Продавець')):
                            rec['chars'].setdefault(k, v.replace('\n', ', '))
                page.goto(u + 'about/', wait_until='domcontentloaded')
                page.wait_for_timeout(3500)
                txt = page.inner_text('body')
                idx = txt.find('Про товар')
                rec['desc_len'] = len(txt[idx:idx + 6000]) if idx > 0 else 0
                # рахуємо тільки галерею картки, не рекомендації внизу
                rec['photos'] = max(
                    page.locator('[class*="gallery"] img').count(),
                    page.locator('[class*="preview"] img').count())
            except Exception as e:
                logger.warning(f'{u}: {type(e).__name__}')
            out.append(rec)
            logger.info(f'  [{i}/{len(urls)}] характеристик '
                        f'{len(rec["chars"])}, фото {rec["photos"]}  '
                        f'{(rec["title"] or "")[:48]}')
            time.sleep(1.0)
    return out


def build_pattern(cards: list) -> dict:
    """Патерн категорії: що заповнено у більшості карток."""
    ok = [c for c in cards if c['chars'] or c['title']]
    freq = collections.Counter()
    for c in ok:
        freq.update(c['chars'].keys())
    n = max(len(ok), 1)
    required = [k for k, v in freq.most_common() if v / n >= REQUIRED_SHARE]
    optional = [k for k, v in freq.most_common()
                if 0 < v / n < REQUIRED_SHARE]
    dl = sorted(c['desc_len'] for c in ok if c['desc_len'])
    ph = sorted(c['photos'] for c in ok if c['photos'])
    return {
        'sample': len(ok),
        'freq': dict(freq.most_common()),
        'required': required,
        'optional': optional,
        'desc_median': dl[len(dl) // 2] if dl else 0,
        'photo_median': ph[len(ph) // 2] if ph else 0,
    }


def analyse_name_order(cards: list) -> dict:
    """Чи закінчується назва на Колір і Розмір, чи є артикул у дужках."""
    stat = collections.Counter()
    SIZE = re.compile(r'\b(?:XS|S|M|L|XL|XXL|2XL|3XL|[0-9]XL/[0-9]XL'
                      r'|(?:XS|S|M|L|XL)/(?:S|M|L|XL|XXL))\b')
    COLOR = re.compile(r'\b(?:Чорний|Білий|Червоний|Рожевий|Синій|Зелений|'
                       r'Бежевий|Тілесний|Золотий|Сріблястий|Фіолетовий)\b', re.I)
    for c in cards:
        t = c['title'] or ''
        if not t:
            continue
        stat['усього'] += 1
        if SIZE.search(t):
            stat['є розмір'] += 1
        if COLOR.search(t):
            stat['є колір'] += 1
        if re.search(r'\(\s*[A-Z0-9\-]{4,}\s*\)', t):
            stat['є артикул у дужках'] += 1
        if ',' in t:
            stat['є кома'] += 1
        tail = t[-40:]
        if SIZE.search(tail) and COLOR.search(tail):
            m_c, m_s = COLOR.search(tail), SIZE.search(tail)
            stat['колір перед розміром' if m_c.start() < m_s.start()
                 else 'розмір перед кольором'] += 1
    return dict(stat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--marketplace', default='rozetka')
    ap.add_argument('--category')
    ap.add_argument('--url')
    ap.add_argument('--label', default='')
    ap.add_argument('--sample', type=int, default=10)
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure_tables(cur)
    conn.commit()

    if a.report:
        cur.execute('SELECT * FROM listing_patterns ORDER BY marketplace, category')
        for r in cur.fetchall():
            print(f"\n═══ {r['marketplace']} / {r['category']} — {r['label']}")
            print(f"   вибірка {r['sample_size']} карток")
            print(f"   обовʼязкові : {', '.join(r['required'] or [])}")
            print(f"   опційні     : {', '.join((r['optional'] or [])[:10])}")
            print(f"   опис ~{r['desc_median']} симв. | фото ~{r['photo_median']}")
            print(f"   назва: {r['name_order']}")
        return

    if not (a.category and a.url):
        ap.error('потрібні --category і --url')

    cards = scrape_cards(collect_urls(a.url, a.sample))
    pat = build_pattern(cards)
    order = analyse_name_order(cards)

    psycopg2.extras.execute_values(cur, """
        INSERT INTO listing_samples
          (marketplace, category, url, title, chars, desc_len, photos)
        VALUES %s
        ON CONFLICT (marketplace, category, url) DO UPDATE SET
          title=EXCLUDED.title, chars=EXCLUDED.chars,
          desc_len=EXCLUDED.desc_len, photos=EXCLUDED.photos, fetched_at=NOW()
    """, [(a.marketplace, a.category, c['url'], c['title'],
           psycopg2.extras.Json(c['chars']), c['desc_len'], c['photos'])
          for c in cards])
    cur.execute("""
        INSERT INTO listing_patterns (marketplace, category, label, sample_size,
            name_order, required, optional, desc_median, photo_median, notes)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (marketplace, category) DO UPDATE SET
          label=EXCLUDED.label, sample_size=EXCLUDED.sample_size,
          name_order=EXCLUDED.name_order, required=EXCLUDED.required,
          optional=EXCLUDED.optional, desc_median=EXCLUDED.desc_median,
          photo_median=EXCLUDED.photo_median, notes=EXCLUDED.notes,
          built_at=NOW()
    """, (a.marketplace, a.category, a.label, pat['sample'],
          json.dumps(order, ensure_ascii=False),
          psycopg2.extras.Json(pat['required']),
          psycopg2.extras.Json(pat['optional']),
          pat['desc_median'], pat['photo_median'],
          'структура знята з живих карток; текст не копіюється'))
    conn.commit()

    print(f"\n══ ПАТЕРН {a.marketplace}/{a.category} — {a.label} ══")
    print(f"   вибірка: {pat['sample']} карток")
    print(f"\n   ЧАСТОТА ХАРАКТЕРИСТИК:")
    for k, v in pat['freq'].items():
        mark = 'ОБОВʼЯЗКОВА' if v / max(pat['sample'], 1) >= REQUIRED_SHARE else ''
        print(f"      {k[:34]:36} {v}/{pat['sample']}  {mark}")
    print(f"\n   опис ~{pat['desc_median']} символів | фото ~{pat['photo_median']}")
    print(f"\n   НАЗВА: {json.dumps(order, ensure_ascii=False)}")
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
