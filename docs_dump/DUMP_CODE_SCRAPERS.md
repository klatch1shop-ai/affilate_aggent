# DUMP_CODE_SCRAPERS.md — повний код agents/scraper/* (+competitor_scraper)

### `agents/scraper/carvol_category_map.py` — 22 рядків

````python
# Маппінг категорій Prom → Розетка
# Перевірено через пошук на rozetka.com.ua

CATEGORY_MAP = {
    '340407':   ('1',  'Камери заднього огляду',              '167898'),
    '340415':   ('2',  'Штатні головні пристрої',             '166828'),
    '340431':   ('3',  'Кабелі та перехідники автозвуку',     '4660837'),
    '121238':   ('4',  'Перехідні рамки для автомагнітол',    '4633641'),
    '340409':   ('5',  'Автомобільні антени',                 '4638279'),
    '340416':   ('6',  'Відеореєстратори',                    '4638109'),
    '341631':   ('7',  'Кронштейни та тримачі',               '4660615'),
    '12123208': ('8',  'Альтернативна оптика',                '4657811'),
    '120224':   ('9',  'Автомобільна проводка',               '4660843'),
    '12020613': ('10', 'LED лампи автомобільні',              '4638283'),
    '120206':   ('11', 'Автомобільне освітлення',             '4638283'),
    '12020601': ('12', 'Автомобільні фари',                   '4638283'),
    '12020306': ('13', 'Блоки керування',                     '4660615'),
    '12020307': ('14', 'Запобіжники та перемикачі',           '4660843'),
    '121203':   ('15', 'Автомобільні дефлектори',             '4660615'),
    '3407':     ('16', 'Аксесуари для мототехніки',           '4660615'),
    'default':  ('17', 'Автоелектроніка',                     '4638107'),
}

````

### `agents/scraper/category_classifier.py` — 383 рядків

````python
"""
AI Класифікатор категорій товарів для Єпіцентру і Розетки
v3: qwen2.5:7b + розумний пошук по БД + підказки
"""
import re, time, sys
from loguru import logger
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection
import requests

OLLAMA = 'http://100.126.131.55:11434'
MODEL  = 'qwen2.5:7b'

# Прямий маппінг: підрядок назви → точна назва категорії в БД
DIRECT_MAP = {
    'головка для пошкодж':      'Воротки, тріскачки та головки',
    'головка ударна':             'Воротки, тріскачки та головки',
    'головка для':                'Воротки, тріскачки та головки',
    'головка торцева':            'Воротки, тріскачки та головки',
    'головка з насадкою':       'Воротки, тріскачки та головки',
    'головка hex':              'Воротки, тріскачки та головки',
    'головка torx':             'Воротки, тріскачки та головки',
    'набір головок':            'Воротки, тріскачки та головки',
    'вороток':                  'Воротки, тріскачки та головки',
    'тріскачка':                'Воротки, тріскачки та головки',
    'подовжувач':               'Воротки, тріскачки та головки',
    'карданний шарнір':         'Воротки, тріскачки та головки',
    'ключ рожковий':            'Ключі та набори ключів',
    'ключ накидний':            'Ключі та набори ключів',
    'ключ комбінований':        'Ключі та набори ключів',
    'ключ розвідний':           'Ключі та набори ключів',
    'ключ шестигранний':        'Ключі та набори ключів',
    'набір ключів':             'Ключі та набори ключів',
    'ключ балонний':            'Балонні та свічні ключі',
    'ключ свічний':             'Балонні та свічні ключі',
    'динамометричний ключ':     'Динамометричні ключі',
    'ключ динамометричний':     'Динамометричні ключі',
    'викрутка акумуляторна':    'Викрутки акумуляторні',
    'викрутка':                 'Викрутки',
    'набір викруток':           'Викрутки',
    'плоскогубці':              'Шарнірно-губцевий інструмент',
    'пасатижі':                 'Шарнірно-губцевий інструмент',
    'бокорізи':                 'Шарнірно-губцевий інструмент',
    'кусачки':                  'Шарнірно-губцевий інструмент',
    'кліщі':                    'Шарнірно-губцевий інструмент',
    'круглогубці':              'Шарнірно-губцевий інструмент',
    'молоток':                  'Молотки',
    'кувалда':                  'Молотки',
    'киянка':                   'Молотки',
    'знімач масляних':          'Знімачі мастильних фільтрів',
    'знімач підшипник':         'Знімачі підшипників',
    'знімач':                   'Знімачі універсальні',
    'набір інструментів':       'Набори інструментів',
    'пневмогайковерт':          'Пневмогайковерти',
    'гайковерт':                'Гайковерти',
    'пневмодриль':              'Пневмодрилі',
    'пневмошліфмашина':         'Пневмошліфмашини',
    'пневмоножиці':             'Пневмоножиці',
    'пневмостеплер':            'Пневмостеплери',
    'набір пневмоінструменту':  'Набори пневмоінструменту',
    'компресорна головка':      'Пневмоінструмент та обладнання',
    'компресор':                'Компресори',
    'шуруповерт':               'Шуруповерти',
    'відбійний молоток':        'Відбійні молотки',
    'біта ':                    'Біти для шуруповерта',
    'набір біт':                'Біти для шуруповерта',
    'бітотримач':               'Біти для шуруповерта',
    'штангенциркуль':           'Штангенциркулі',
    'мікрометр':                'Вимірювальний інструмент',
    'нутромір':                 'Вимірювальний інструмент',
    'лінійна шкала':            'Вимірювальний інструмент',
    'індикатор годинного':      'Вимірювальний інструмент',
    'динамометр':               'Динамометри',
    'ліхтар налобний':          'Ліхтарі налобні',
    'ліхтар':                   'Ліхтарі',
    'траверса':                 'Траверси',
    'індукційна котушка':       'Індукційні нагрівачі',
    'індукційний нагрівач':     'Індукційні нагрівачі',
    'ультразвукова ванна':      'Ультразвукові ванни',
    'рихтувальне':              'Пристосування рихтувальні',
    'стапель':                  'Стапелі рихтувальні',
    'балансувальний верстат':   'Балансувальні верстати',
    'верстат для шиномонтажу':  'Верстати для шиномонтажу',
    'набір захисту':            'Набір захисту для катання',
    'стенд для фарбування':     'Стенди для фарбування',
    'стенд для ремонту двигуна':'Стенди для ремонту двигуна',
    'стенд для форсунок':       'Стенди для перевірки форсунок',
    'adas':                     'Інформаційні стенди',
    'зубило':                   'Слюсарний інструмент',
    'кернер':                   'Слюсарний інструмент',
    'напилок':                  'Слюсарний інструмент',
    'верстак':                  'Інструментальні столи та верстаки',
    'свердло':                  'Свердла',
    'паяльник':                 'Паяльники та випалювачі',
    'ящик для інструментів':    'Ящики та органайзери для інструментів',
    'мікрометр':                'Спеціалізовані електровимірювальні прилади',
    'нутромір':                 'Спеціалізовані електровимірювальні прилади',
    'лінійна шкала':            'Спеціалізовані електровимірювальні прилади',
    'індикатор годинного':      'Спеціалізовані електровимірювальні прилади',
    'цифровий індикатор':       'Спеціалізовані електровимірювальні прилади',
    'грузовий комплект':        'Автосканери',
    'адаптер для діагностики':  'Автосканери',
    'сполучник на шланг':       'Фітинги для пневмоінструменту',
    'з\'єднувач на шланг':       'Фітинги для пневмоінструменту',
    'фітинг':                    'Фітинги для пневмоінструменту',
    'крестовина латунь':         'Фітинги для пневмоінструменту',
    'тройник латунь':            'Фітинги для пневмоінструменту',
    'бачок для фарбопульта':     'Пневмопістолети для розпилювання і нагнітання',
    'бачок пластиковий':         'Пневмопістолети для розпилювання і нагнітання',
    'бачок металевий':           'Пневмопістолети для розпилювання і нагнітання',
    'бачок нейлоновий':          'Пневмопістолети для розпилювання і нагнітання',
    'термометр':                 'Спеціалізовані електровимірювальні прилади',
    'пірометр':                  'Спеціалізовані електровимірювальні прилади',
    'анемометр':                 'Спеціалізовані електровимірювальні прилади',
    'тестер напруги':            'Спеціалізовані електровимірювальні прилади',
    'мультиметр':                'Спеціалізовані електровимірювальні прилади',
    'безконтактний тестер':      'Спеціалізовані електровимірювальні прилади',
    'безконтактний інфрачервон': 'Спеціалізовані електровимірювальні прилади',
    'балонний ключ':             'Балонні та свічні ключі',
    'бачок для гальмівної':      'Інструмент для ремонту двигуна',
    'шайба':                     'Витратні матеріали для пневмоінструменту',
    'муфта':                     'Фітинги для пневмоінструменту',
    'ніпель':                    'Фітинги для пневмоінструменту',
    'швидкоз\'єднання':          'Фітинги для пневмоінструменту',
    'автотестер':                'Автосканери',
    'діагностика':               'Автосканери',
    'сканер':                    'Автосканери',
    'компресометр':              'Інструмент для ремонту двигуна',
    'маслозаміна':               'Інструмент для ремонту двигуна',
    'оливозаміна':               'Інструмент для ремонту двигуна',
    'зубчате колесо':            'Інструмент для ремонту двигуна',
    'регулятор тиску':           'Пневмоінструмент та обладнання',
    'манометр':                  'Спеціалізовані електровимірювальні прилади',
    'щуп':                       'Вимірювальний інструмент',
    'калібр':                    'Спеціалізовані електровимірювальні прилади',
    'автосканер':               'Автосканери',
    'мотор-тестер':             'Автосканери',
}

CATEGORY_HINTS = {
    'Воротки, тріскачки та головки':    'головки торцеві, воротки T-подібні, тріскачки, подовжувачі',
    'Ключі та набори ключів':           'ріжкові, накидні, комбіновані, шестигранні HEX ключі',
    'Балонні та свічні ключі':          'балонні, свічні ключі',
    'Динамометричні ключі':             'ключі з обмежувачем моменту',
    'Викрутки':                         'викрутки плоскі, хрестові, Torx',
    'Викрутки акумуляторні':            'акумуляторні електровикрутки',
    'Шарнірно-губцевий інструмент':     'плоскогубці, пасатижі, бокорізи, кусачки, кліщі',
    'Молотки':                          'молотки, кувалди, киянки',
    'Знімачі підшипників':              'знімачі підшипників puller',
    'Знімачі мастильних фільтрів':      'знімачі масляних фільтрів',
    'Знімачі універсальні':             'механічні знімачі 2-3 лапи',
    'Набори інструментів':              'набори в кейсі або сумці',
    'Пневмогайковерти':                 'пневматичні гайковерти impact wrench',
    'Гайковерти':                       'електричні акумуляторні гайковерти',
    'Компресори':                       'компресори поршневі безмасляні для майстерні',
    'Пневмоінструмент та обладнання':   'пневмопістолети, фітинги, компресорні головки',
    'Набори пневмоінструменту':         'набори пневматичного інструменту',
    'Біти для шуруповерта':             'біти Phillips/PZ/Torx/HEX, бітотримачі',
    'Відбійні молотки':                 'відбійні молотки, бетоноломи',
    'Шуруповерти':                      'шуруповерти акумуляторні та мережеві',
    'Штангенциркулі':                   'штангенциркулі механічні та цифрові',
    'Вимірювальний інструмент':         'мікрометри, нутроміри, індикатори, лінійки',
    'Ліхтарі':                          'ліхтарі ручні тактичні',
    'Ліхтарі налобні':                  'налобні ліхтарі headlamp',
    'Траверси':                         'траверси пневмо-гідравлічні для зняття двигунів',
    'Індукційні нагрівачі':             'індукційні нагрівачі котушки для зняття деталей',
    'Ультразвукові ванни':              'ультразвукові очищувачі ванни',
    'Пристосування рихтувальні':        'рихтувальні пристосування, споттери',
    'Стапелі рихтувальні':              'стапелі для правки кузова',
    'Балансувальні верстати':           'верстати для балансування коліс',
    'Верстати для шиномонтажу':         'шиномонтажні верстати',
    'Набір захисту для катання':        'захист для скейту роликів велосипеда',
    'Стенди для фарбування':            'стенди для фарбування кузовних деталей',
    'Стенди для ремонту двигуна':       'стенди-кантувачі для ремонту двигуна',
    'Стенди для перевірки форсунок':    'стенди діагностики очистки форсунок GDI EFI',
    'Інформаційні стенди':              'ADAS стенди калібрування камер датчиків',
    'Динамометри':                      'динамометри тягові стискаючі',
    'Слюсарний інструмент':             'зубила, кернери, напилки',
    'Інструментальні столи та верстаки':'верстаки слюсарні',
    'Свердла':                          'свердла по металу дереву бетону',
    'Паяльники та випалювачі':          'паяльники паяльні станції',
    'Ящики та органайзери для інструментів': 'ящики органайзери кейси',
    'Автосканери':                      'автодіагностичні сканери OBD мотор-тестери',
}


def build_prompt(product_name: str, candidates: list) -> str:
    lines = []
    for i, c in enumerate(candidates):
        hint = CATEGORY_HINTS.get(c['name'], '')
        suffix = f' ({hint})' if hint else ''
        lines.append(f'{i+1}. {c["name"]}{suffix}')
    return (
        f'Ти класифікатор товарів для маркетплейсу Єпіцентр.\n'
        f'Обери ОДНУ найточнішу категорію зі списку.\n\n'
        f'Товар: {product_name}\n\n'
        f'Категорії:\n' + '\n'.join(lines) + f'\n\n'
        f'Відповідь: ТІЛЬКИ цифра від 1 до {len(candidates)}.'
    )


def search_db(cur, pattern: str, marketplace: str, limit: int = 5) -> list:
    """
    Пошук категорій в БД.
    Точний збіг на початку → починається з → містить.
    """
    exact = pattern.strip('%')
    if marketplace == 'epicentr':
        cur.execute(
            'SELECT id, final_category as name FROM epicentr_categories '
            'WHERE final_category ILIKE %s '
            'ORDER BY '
            '  CASE WHEN LOWER(final_category) = LOWER(%s) THEN 0 '
            '       WHEN LOWER(final_category) LIKE LOWER(%s) THEN 1 '
            '       ELSE 2 END, '
            '  LENGTH(final_category) '
            'LIMIT %s',
            (f'%{exact}%', exact, exact + '%', limit)
        )
    else:
        cur.execute(
            'SELECT id, title_ua as name FROM rozetka_categories '
            'WHERE title_ua ILIKE %s '
            'ORDER BY CASE WHEN LOWER(title_ua)=LOWER(%s) THEN 0 ELSE 1 END '
            'LIMIT %s',
            (f'%{exact}%', exact, limit)
        )
    return [{'id': r['id'], 'name': r['name']} for r in cur.fetchall()]


def find_candidates(product_name: str, marketplace: str = 'epicentr') -> tuple:
    """
    Пошук кандидатів — 4 стратегії по черзі.
    """
    name_lower = product_name.lower().strip()
    conn = get_connection()
    cur  = conn.cursor()
    candidates    = []
    keyword_match = False

    def add(rows: list, source: str):
        for r in rows:
            if r['name'] not in [c['name'] for c in candidates]:
                candidates.append({**r, 'source': source})

    # ── Стратегія 1: прямий DIRECT_MAP (найдовший збіг) ──────────────
    matched = sorted(
        [(kw, cat) for kw, cat in DIRECT_MAP.items() if kw in name_lower],
        key=lambda x: -len(x[0])
    )
    for kw, cat_name in matched[:2]:
        rows = search_db(cur, cat_name, marketplace, 3)
        add(rows, 'direct')
        if rows:
            keyword_match = True

    # Один чіткий прямий збіг — не потрібен LLM
    if len([c for c in candidates if c['source'] == 'direct']) == 1 and len(candidates) == 1:
        cur.close(); conn.close()
        return candidates, True

    # ── Стратегія 2: перші два значущих слова ────────────────────────
    words = [w for w in re.split(r'[\s,()./\-]+', name_lower) if len(w) > 3]
    if len(words) >= 2:
        bigram = words[0] + ' ' + words[1]
        add(search_db(cur, bigram, marketplace, 4), 'bigram')

    # ── Стратегія 3: перше слово ─────────────────────────────────────
    if words:
        add(search_db(cur, words[0], marketplace, 6), 'word1')

    # ── Стратегія 4: друге слово (якщо перше загальне) ───────────────
    generic = {'набір', 'комплект', 'цифровий', 'цифрова', 'електронний',
               'безмасляний', 'поршневий', 'акумуляторний', 'пневматичний',
               'ручний', 'автоматичний', 'механічний', 'гідравлічний'}
    if words and words[0] in generic and len(words) > 1:
        add(search_db(cur, words[1], marketplace, 5), 'word2')

    # ── Стратегія 5: корінь першого слова (7 символів) ───────────────
    if len(candidates) < 2 and words:
        root = words[0][:7]
        if len(root) >= 5:
            add(search_db(cur, root, marketplace, 6), 'root')

    cur.close(); conn.close()
    return candidates[:8], keyword_match


def classify(product_name: str, marketplace: str = 'epicentr') -> dict:
    candidates, keyword_match = find_candidates(product_name, marketplace)

    if not candidates:
        return {'category_id': None, 'category_name': None, 'confidence': 'none'}

    # Один прямий збіг → high confidence без LLM
    direct = [c for c in candidates if c['source'] == 'direct']
    if len(direct) == 1 and len(candidates) <= 2:
        return {
            'category_id':   direct[0]['id'],
            'category_name': direct[0]['name'],
            'confidence':    'high'
        }

    # LLM вибір
    prompt = build_prompt(product_name, candidates)
    try:
        resp = requests.post(f'{OLLAMA}/api/generate', json={
            'model':   MODEL,
            'prompt':  prompt,
            'stream':  False,
            'options': {'num_predict': 10, 'temperature': 0}
        }, timeout=60)
        answer = resp.json()['response'].strip()
        num = re.search(r'\d+', answer)
        if num:
            idx = int(num.group()) - 1
            if 0 <= idx < len(candidates):
                confidence = 'medium' if keyword_match else 'low'
                return {
                    'category_id':   candidates[idx]['id'],
                    'category_name': candidates[idx]['name'],
                    'confidence':    confidence
                }
    except Exception as e:
        logger.error(f'Ollama error: {e}')

    return {
        'category_id':   candidates[0]['id'],
        'category_name': candidates[0]['name'],
        'confidence':    'low'
    }


def classify_batch(marketplace: str = 'epicentr', limit: int = 100, sku: str = None):
    conn = get_connection()
    cur  = conn.cursor()

    cur.execute('ALTER TABLE my_products ADD COLUMN IF NOT EXISTS epicentr_category_id INTEGER')
    cur.execute('ALTER TABLE my_products ADD COLUMN IF NOT EXISTS epicentr_category_name VARCHAR(500)')
    cur.execute('ALTER TABLE my_products ADD COLUMN IF NOT EXISTS epicentr_confidence VARCHAR(20)')
    conn.commit()

    if sku:
        cur.execute('SELECT sku, name_uk FROM my_products WHERE sku=%s', (sku,))
    else:
        cur.execute(
            'SELECT sku, name_uk FROM my_products '
            'WHERE (epicentr_category_id IS NULL OR epicentr_confidence = %s) '
            'AND price_supplier > 0 ORDER BY sku LIMIT %s',
            ('none', limit)
        )
    products = cur.fetchall()
    logger.info(f'Classifying {len(products)} products for {marketplace}')

    stats = {'high': 0, 'medium': 0, 'low': 0, 'none': 0}
    for p in products:
        name   = p['name_uk'] or ''
        result = classify(name, marketplace)
        cur.execute(
            'UPDATE my_products SET '
            'epicentr_category_id=%s, epicentr_category_name=%s, epicentr_confidence=%s '
            'WHERE sku=%s',
            (result['category_id'], result['category_name'], result['confidence'], p['sku'])
        )
        conn.commit()
        conf = result['confidence']
        stats[conf] = stats.get(conf, 0) + 1
        logger.info(f"[{conf:6}] {name[:55]} → {result['category_name']}")

    cur.close(); conn.close()
    logger.success(f'Done: {stats}')
    return stats


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--marketplace', default='epicentr')
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--sku', type=str, default=None)
    args = parser.parse_args()
    classify_batch(args.marketplace, args.limit, args.sku)

````

### `agents/scraper/debug_page.py` — 34 рядків

````python
import asyncio
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

async def save_html():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            locale="uk-UA"
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        page = await context.new_page()
        await page.goto("https://rozetka.com.ua/ua/electronics/c4627901/", wait_until="networkidle", timeout=40000)
        await asyncio.sleep(4)
        html = await page.content()
        with open("/tmp/rozetka.html", "w") as f:
            f.write(html)
        print(f"Saved {len(html)} bytes")
        # Знайти всі li, div з класами що схожі на картку товару
        items_li = await page.query_selector_all("li")
        items_div = await page.query_selector_all("div[class*='product'], div[class*='goods'], div[class*='item']")
        print(f"li elements: {len(items_li)}")
        print(f"product divs: {len(items_div)}")
        # Перші класи li
        for el in items_li[:5]:
            cls = await el.get_attribute("class")
            if cls:
                print(f"  li class: {cls}")
        await browser.close()

asyncio.run(save_html())

````

### `agents/scraper/epicentr_cabinet.py` — 500 рядків

````python
"""
agents/scraper/epicentr_cabinet.py
=====================================
Автоматизація кабінету Єпіцентру через Playwright.

Функції:
- Логін і збереження сесії
- Скачування XLS всіх товарів → маппінг артикулів
- Завантаження XLS з оновленими цінами/наявністю
- Перехоплення API endpoints
- Підтвердження замовлень

Запуск:
    python3 agents/scraper/epicentr_cabinet.py --action export_products
    python3 agents/scraper/epicentr_cabinet.py --action import_prices --file /tmp/prices.xlsx
    python3 agents/scraper/epicentr_cabinet.py --action intercept_api
    python3 agents/scraper/epicentr_cabinet.py --action map_skus
"""

import os, sys, json, asyncio, argparse
import pandas as pd
from datetime import datetime
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection
from agents.scraper.playwright_base import PlaywrightBase

# =============================================
# КОНСТАНТИ
# =============================================

EPICENTR_LOGIN_URL  = 'https://admin.epicentrm.com.ua/login'
EPICENTR_CABINET    = 'https://admin.epicentrm.com.ua'
EPICENTR_PRODUCTS   = 'https://admin.epicentrm.com.ua/products'
EPICENTR_IMPORT     = 'https://admin.epicentrm.com.ua/import'
EPICENTR_ORDERS     = 'https://admin.epicentrm.com.ua/orders'

EPICENTR_EMAIL    = os.getenv('EPICENTR_EMAIL', '')
EPICENTR_PASSWORD = os.getenv('EPICENTR_PASSWORD', '')

DOWNLOAD_DIR = '/tmp/epicentr_downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# =============================================
# ОСНОВНИЙ КЛАС
# =============================================

class EpicentrCabinet(PlaywrightBase):

    def __init__(self, headless: bool = True):
        super().__init__(site='epicentr', headless=headless)

    # =============================================
    # АВТОРИЗАЦІЯ
    # =============================================

    async def login(self) -> bool:
        """
        Логін в кабінет Єпіцентру.
        Зберігає сесію після успішного логіну.
        """
        logger.info('[Єпіцентр] Логін...')
        start = datetime.now()

        await self.navigate(EPICENTR_LOGIN_URL, wait_for='domcontentloaded')
        await self.random_delay(1000, 2000)

        # Заповнюємо email
        email_filled = await self.resilient_fill(
            'input[type="email"], input[name="email"], #email',
            EPICENTR_EMAIL,
            'поле email'
        )
        if not email_filled:
            return False

        await self.random_delay(300, 700)

        # Заповнюємо пароль
        pass_filled = await self.resilient_fill(
            'input[type="password"], input[name="password"], #password',
            EPICENTR_PASSWORD,
            'поле пароль'
        )
        if not pass_filled:
            return False

        await self.random_delay(500, 1000)

        # Натискаємо Увійти
        clicked = await self.resilient_click(
            'button[type="submit"], .login-button, button:has-text("Увійти"), button:has-text("Войти")',
            'кнопка Увійти'
        )
        if not clicked:
            return False

        # Чекаємо на перехід до кабінету
        try:
            await self.page.wait_for_url('**/admin.epicentrm.com.ua/**', timeout=15000)
            if 'login' not in self.page.url:
                await self.save_session()
                duration = (datetime.now() - start).seconds
                await self._log_action('login', 'success', duration_ms=duration*1000)
                logger.success('[Єпіцентр] Логін успішний')
                return True
        except:
            pass

        # Перевіряємо помилку
        error_text = await self.get_text('.error, .alert-danger, [class*="error"]')
        if error_text:
            logger.error(f'[Єпіцентр] Помилка логіну: {error_text}')

        screenshot = await self.screenshot('login_failed')
        await self._telegram_alert('❌ [Єпіцентр] Не вдалось залогінитись', screenshot)
        await self._log_action('login', 'error', {'error': error_text})
        return False

    async def ensure_logged_in(self) -> bool:
        """Перевіряє авторизацію і логінить якщо треба."""
        # Перевіряємо поточну сторінку
        try:
            await self.navigate(EPICENTR_CABINET, wait_for='domcontentloaded')
            if 'login' not in self.page.url:
                logger.info('[Єпіцентр] Вже залогінений')
                return True
        except:
            pass
        return await self.login()

    # =============================================
    # СКАЧУВАННЯ XLS ТОВАРІВ
    # =============================================

    async def export_products_xls(self) -> str | None:
        """
        Скачує XLS всіх товарів з кабінету Єпіцентру.
        Повертає шлях до збереженого файлу.
        """
        logger.info('[Єпіцентр] Скачування XLS товарів...')

        if not await self.ensure_logged_in():
            return None

        await self.navigate(EPICENTR_PRODUCTS, wait_for='networkidle')
        await self.random_delay(1000, 2000)

        # Шукаємо кнопку Export/Вивантажити
        export_selectors = [
            'button:has-text("Вивантажити")',
            'button:has-text("Export")',
            'a:has-text("Вивантажити")',
            'a:has-text("Скачати")',
            '[data-action="export"]',
            '.export-button',
        ]

        file_path = None
        for selector in export_selectors:
            try:
                count = await self.page.locator(selector).count()
                if count > 0:
                    file_path = await self.download_file(selector, DOWNLOAD_DIR)
                    if file_path:
                        break
            except:
                continue

        if not file_path:
            # Спробуємо через меню
            screenshot = await self.screenshot('export_products')
            logger.warning('[Єпіцентр] Кнопка export не знайдена — аналіз сторінки...')

            # Self-Healing: аналізуємо DOM
            html = await self.page.inner_html('body')
            logger.info(f'[Єпіцентр] DOM розмір: {len(html)} символів')

            await self._telegram_alert(
                '⚠️ [Єпіцентр] Не знайдено кнопку Export товарів. '
                'Перевірте скріншот.',
                screenshot
            )
            return None

        logger.success(f'[Єпіцентр] XLS скачано: {file_path}')
        await self._log_action('export_products', 'success', {'file': file_path})
        return file_path

    # =============================================
    # МАППІНГ АРТИКУЛІВ
    # =============================================

    async def parse_xls_mapping(self, xls_path: str) -> dict:
        """
        Парсить XLS і витягує маппінг: наш_SKU ↔ артикул_Єпіцентру.
        Зберігає в таблицю epicentr_sku_mapping.
        """
        logger.info(f'[Єпіцентр] Парсинг XLS маппінгу: {xls_path}')

        try:
            df = pd.read_excel(xls_path)
            logger.info(f'Колонки XLS: {list(df.columns)}')
            logger.info(f'Рядків: {len(df)}')
        except Exception as e:
            logger.error(f'Помилка читання XLS: {e}')
            return {}

        # Визначаємо колонки (назви можуть відрізнятись)
        sku_col = None
        article_col = None
        id_col = None

        for col in df.columns:
            col_lower = str(col).lower()
            if any(k in col_lower for k in ['артикул', 'sku', 'код', 'article']):
                if sku_col is None:
                    sku_col = col
                else:
                    article_col = col
            if any(k in col_lower for k in ['id', 'ідентифікатор', 'номер']):
                id_col = col

        logger.info(f'SKU колонка: {sku_col}, Артикул: {article_col}, ID: {id_col}')

        mapping = {}
        saved = 0

        conn = get_connection()
        cur = conn.cursor()

        for _, row in df.iterrows():
            our_sku = str(row.get(sku_col, '')).strip() if sku_col else ''
            epicentr_article = str(row.get(article_col, '')).strip() if article_col else ''
            epicentr_id = row.get(id_col) if id_col else None

            if not our_sku or our_sku == 'nan':
                continue

            mapping[our_sku] = {
                'article': epicentr_article,
                'id': epicentr_id,
            }

            # Зберігаємо в БД
            try:
                cur.execute('''
                    INSERT INTO epicentr_sku_mapping (our_sku, epicentr_article, epicentr_product_id, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (our_sku) DO UPDATE SET
                        epicentr_article=EXCLUDED.epicentr_article,
                        epicentr_product_id=EXCLUDED.epicentr_product_id,
                        updated_at=NOW()
                ''', (our_sku, epicentr_article or None, int(epicentr_id) if epicentr_id else None))
                saved += 1
            except Exception as e:
                logger.error(f'Помилка збереження маппінгу {our_sku}: {e}')

        conn.commit(); cur.close(); conn.close()
        logger.success(f'[Єпіцентр] Маппінг збережено: {saved} товарів')
        return mapping

    # =============================================
    # ЗАВАНТАЖЕННЯ XLS З ЦІНАМИ
    # =============================================

    async def import_prices_xls(self, xls_path: str) -> bool:
        """
        Завантажує XLS з оновленими цінами/наявністю в Єпіцентр.
        """
        logger.info(f'[Єпіцентр] Завантаження цін: {xls_path}')

        if not await self.ensure_logged_in():
            return False

        await self.navigate(EPICENTR_IMPORT, wait_for='networkidle')
        await self.random_delay(1000, 2000)

        # Завантажуємо файл
        uploaded = await self.upload_file(
            'input[type="file"]',
            xls_path
        )
        if not uploaded:
            screenshot = await self.screenshot('import_upload_failed')
            await self._telegram_alert('❌ [Єпіцентр] Не вдалось завантажити XLS', screenshot)
            return False

        await self.random_delay(500, 1000)

        # Натискаємо кнопку Завантажити/Import
        clicked = await self.resilient_click(
            'button[type="submit"], button:has-text("Завантажити"), button:has-text("Імпорт"), button:has-text("Import")',
            'кнопка завантаження'
        )
        if not clicked:
            return False

        # Чекаємо на результат
        await self.random_delay(3000, 5000)
        try:
            await self.wait_for('.success, .alert-success, [class*="success"]', timeout=30000)
            result_text = await self.get_text('.success, .alert-success')
            logger.success(f'[Єпіцентр] Завантаження успішне: {result_text}')
            screenshot = await self.screenshot('import_success')
            await self._telegram_alert(
                f'✅ [Єпіцентр] XLS завантажено\n{result_text}',
                screenshot
            )
            await self._log_action('import_prices', 'success', {'file': xls_path})
            return True
        except:
            screenshot = await self.screenshot('import_result')
            result_text = await self.get_text('body')
            logger.info(f'[Єпіцентр] Результат завантаження: {result_text[:200]}')
            await self._telegram_alert(
                f'[Єпіцентр] Результат завантаження XLS — перевір скріншот',
                screenshot
            )
            return False

    # =============================================
    # ПЕРЕХОПЛЕННЯ API ENDPOINTS
    # =============================================

    async def intercept_api_endpoints(self) -> list:
        """
        Проходить по всіх розділах кабінету і перехоплює XHR запити.
        Повертає список унікальних API endpoints.
        """
        logger.info('[Єпіцентр] Перехоплення API endpoints...')

        if not await self.ensure_logged_in():
            return []

        await self.intercept_start('epicentrm.com.ua')

        # Переходимо по всіх ключових розділах
        sections = [
            (EPICENTR_PRODUCTS, 'products'),
            (EPICENTR_ORDERS, 'orders'),
            (EPICENTR_IMPORT, 'import'),
            (f'{EPICENTR_CABINET}/prices', 'prices'),
            (f'{EPICENTR_CABINET}/categories', 'categories'),
        ]

        for url, section in sections:
            try:
                logger.info(f'[Єпіцентр] Сканую: {section}')
                await self.navigate(url, wait_for='networkidle')
                await self.random_delay(2000, 3000)
                await self.scroll_down(2)
            except Exception as e:
                logger.warning(f'[Єпіцентр] Помилка {section}: {e}')

        requests = self.intercept_stop()

        # Аналізуємо унікальні endpoints
        endpoints = {}
        for r in requests:
            url = r['url']
            method = r['method']
            key = f'{method} {url.split("?")[0]}'
            if key not in endpoints:
                endpoints[key] = {
                    'method': method,
                    'url': url.split('?')[0],
                    'example_response': r.get('body', {}),
                    'count': 0
                }
            endpoints[key]['count'] += 1

        result = sorted(endpoints.values(), key=lambda x: -x['count'])

        # Зберігаємо в файл
        output_path = '/home/tek/agent-system/shared/skills/scraper/epicentr_api_discovered.json'
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)

        logger.success(f'[Єпіцентр] Знайдено {len(result)} унікальних endpoints → {output_path}')

        # Telegram звіт
        top_endpoints = '\n'.join([f'{e["method"]} {e["url"]}' for e in result[:10]])
        await self._telegram_alert(
            f'🔍 [Єпіцентр] Знайдено API endpoints: {len(result)}\n\nТоп-10:\n{top_endpoints}'
        )

        return result

    # =============================================
    # ГЕНЕРАЦІЯ XLS ДЛЯ ІМПОРТУ
    # =============================================

    async def generate_prices_xls(self, output_path: str = None) -> str:
        """
        Генерує XLS файл з поточними цінами і наявністю з БД.
        Формат відповідає вимогам Єпіцентру.
        """
        output_path = output_path or f'/tmp/epicentr_prices_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'

        # Отримуємо дані з БД
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT
                m.our_sku,
                m.epicentr_article,
                m.epicentr_product_id,
                p.price_our,
                p.available,
                p.stock
            FROM epicentr_sku_mapping m
            JOIN my_products p ON m.our_sku = p.sku
            WHERE p.price_our > 0
            ORDER BY m.our_sku
        ''')
        rows = cur.fetchall()
        cur.close(); conn.close()

        if not rows:
            logger.error('Немає даних для генерації XLS — спочатку запусти map_skus')
            return None

        # Формуємо DataFrame
        data = []
        for r in rows:
            data.append({
                'Артикул': r['epicentr_article'] or r['our_sku'],
                'Ціна': float(r['price_our']),
                'Наявність': 'В наявності' if r['available'] else 'Немає в наявності',
                'Залишок': r['stock'] or '',
            })

        df = pd.DataFrame(data)
        df.to_excel(output_path, index=False)
        logger.success(f'XLS згенеровано: {output_path} ({len(data)} товарів)')
        return output_path


# =============================================
# CLI ЗАПУСК
# =============================================

async def main():
    parser = argparse.ArgumentParser(description='Єпіцентр Cabinet Automation')
    parser.add_argument('--action', required=True,
        choices=['login', 'export_products', 'import_prices', 'intercept_api',
                 'map_skus', 'generate_prices'],
        help='Дія для виконання')
    parser.add_argument('--file', type=str, help='Шлях до файлу (для import_prices)')
    parser.add_argument('--visible', action='store_true', help='Запустити з відкритим браузером')
    args = parser.parse_args()

    async with EpicentrCabinet(headless=not args.visible) as cabinet:

        if args.action == 'login':
            success = await cabinet.login()
            print('✅ Логін успішний' if success else '❌ Логін невдалий')

        elif args.action == 'export_products':
            path = await cabinet.export_products_xls()
            if path:
                print(f'✅ XLS збережено: {path}')
            else:
                print('❌ Не вдалось скачати XLS')

        elif args.action == 'import_prices':
            if not args.file:
                print('❌ Вкажи --file шлях_до_файлу.xlsx')
                return
            success = await cabinet.import_prices_xls(args.file)
            print('✅ Завантажено' if success else '❌ Помилка завантаження')

        elif args.action == 'intercept_api':
            endpoints = await cabinet.intercept_api_endpoints()
            print(f'✅ Знайдено endpoints: {len(endpoints)}')

        elif args.action == 'map_skus':
            # Спочатку скачуємо XLS, потім парсимо маппінг
            xls_path = await cabinet.export_products_xls()
            if xls_path:
                mapping = await cabinet.parse_xls_mapping(xls_path)
                print(f'✅ Маппінг збережено: {len(mapping)} товарів')
            else:
                print('❌ Не вдалось отримати XLS')

        elif args.action == 'generate_prices':
            path = await cabinet.generate_prices_xls()
            if path:
                print(f'✅ XLS цін згенеровано: {path}')
            else:
                print('❌ Помилка генерації — спочатку запусти map_skus')


if __name__ == '__main__':
    asyncio.run(main())

````

### `agents/scraper/find_url.py` — 42 рядків

````python
import asyncio

async def find():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # відкриє вікно браузера
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            locale="uk-UA"
        )
        page = await context.new_page()
        await page.goto("https://rozetka.com.ua/ua/", wait_until="networkidle", timeout=40000)
        print("Відкрий категорію 'Електроніка' вручну в браузері")
        print("Потім подивись URL і натисни Enter тут...")
        input()
        url = page.url
        print(f"Поточний URL: {url}")
        
        # Зберегти HTML
        html = await page.content()
        with open("/tmp/rozetka_real.html", "w") as f:
            f.write(html)
        print(f"HTML збережено: {len(html)} bytes")
        
        # Знайти картки товарів
        selectors_to_try = [
            "li.catalog-grid__cell",
            "li[class*='catalog']",
            "div[class*='catalog']",
            "app-goods-tile-default",
            "rz-catalog-tile",
            "[class*='goods-tile']",
            "[class*='product-tile']",
        ]
        for sel in selectors_to_try:
            items = await page.query_selector_all(sel)
            if items:
                print(f"✓ Знайдено {len(items)} елементів з селектором: {sel}")
        
        await browser.close()

asyncio.run(find())

````

### `agents/scraper/generate_carvol_xml.py` — 117 рядків

````python
import os, sys, json
from datetime import datetime
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection
from agents.scraper.carvol_category_map import CATEGORY_MAP

SHOP_NAME = "klatch1 shop"
SHOP_COMPANY = "3721108"
SHOP_URL = "https://cs4053918.prom.ua/"

def escape_xml(text: str) -> str:
    if not text: return ""
    return (str(text)
        .replace('&', '&amp;')
        .replace('"', '&quot;')
        .replace("'", '&apos;')
        .replace('<', '&lt;')
        .replace('>', '&gt;'))

def generate_xml(output_file: str = "data/carvol_rozetka.xml"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT external_id, article, name_ua, description_ua,
               vendor, price, category_id, pictures, params,
               stock_quantity, available
        FROM carvol_products
        WHERE has_params = true AND price > 0 AND available = true
        ORDER BY category_id, vendor, article
    """)
    products = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    logger.info(f"[XML] {len(products)} products")

    categories_used = {}
    for p in products:
        cat_id, cat_name, rz_id = CATEGORY_MAP.get(p['category_id'], CATEGORY_MAP['default'])
        categories_used[cat_id] = (cat_name, rz_id)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{datetime.now().strftime("%Y-%m-%d %H:%M")}">',
        '  <shop>',
        f'    <name>{SHOP_NAME}</name>',
        f'    <company>{SHOP_COMPANY}</company>',
        f'    <url>{SHOP_URL}</url>',
        '    <currencies><currency id="UAH" rate="1"/></currencies>',
        '    <categories>',
    ]
    for cat_id, (cat_name, rz_id) in sorted(categories_used.items()):
        lines.append(f'      <category id="{cat_id}" rz_id="{rz_id}">{cat_name}</category>')
    lines += ['    </categories>', '    <offers>']

    names_used = set()
    processed = 0

    for p in products:
        sku = str(p['external_id'])
        article = escape_xml(p['article'] or sku)
        name_ua = escape_xml(p['name_ua'] or '')

        orig = name_ua
        counter = 1
        while name_ua in names_used:
            name_ua = f"{orig} {counter}"
            counter += 1
        names_used.add(name_ua)

        desc = escape_xml(p['description_ua'] or '')
        vendor = escape_xml(p['vendor'] or '')
        price = int(float(p['price']))
        stock = int(p['stock_quantity'] or 0)
        cat_id = CATEGORY_MAP.get(p['category_id'], CATEGORY_MAP['default'])[0]

        pics = p['pictures'] or []
        if isinstance(pics, str): pics = json.loads(pics)
        params = p['params'] or {}
        if isinstance(params, str): params = json.loads(params)

        lines.append(f'      <offer id="{sku}" available="true">')
        lines.append(f'        <price>{price}</price>')
        lines.append(f'        <currencyId>UAH</currencyId>')
        lines.append(f'        <categoryId>{cat_id}</categoryId>')
        for url in pics[:10]:
            if url: lines.append(f'        <picture>{url}</picture>')
        lines.append(f'        <vendor>{vendor}</vendor>')
        lines.append(f'        <article>{article}</article>')
        lines.append(f'        <stock_quantity>{stock}</stock_quantity>')
        lines.append(f'        <name_ua>{name_ua}</name_ua>')
        lines.append(f'        <name>{name_ua}</name>')
        if desc:
            lines.append(f'        <description_ua><![CDATA[<p>{desc}</p>]]></description_ua>')
        for k, v in params.items():
            if k and v and str(v).strip():
                lines.append(f'        <param name="{escape_xml(str(k))}">{escape_xml(str(v))}</param>')
        lines.append('      </offer>')
        processed += 1

    lines += ['    </offers>', '  </shop>', '</yml_catalog>']

    os.makedirs('data', exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    size_kb = os.path.getsize(output_file) // 1024
    logger.success(f"[XML] → {output_file} ({size_kb}KB, {processed} offers)")
    return output_file, processed

if __name__ == "__main__":
    file, count = generate_xml()
    print(f"\n✅ XML: {file}")
    print(f"   Товарів: {count}")
    print(f"   Розмір: {os.path.getsize(file)//1024}KB")

````

### `agents/scraper/generate_params_from_name.py` — 161 рядків

````python
import os, sys, json, re
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# Словник типів товарів з назви → параметри
TYPE_PARAMS = {
    'камера': {'Тип': 'Камера заднього огляду', 'Призначення': 'Відеоспостереження'},
    'кріплення': {'Тип': 'Кріплення'},
    'монітор': {'Тип': 'Монітор'},
    'реєстратор': {'Тип': 'Відеореєстратор'},
    'магнітола': {'Тип': 'Автомагнітола'},
    'адаптер': {'Тип': 'Адаптер'},
    'кабель': {'Тип': 'Кабель'},
    'антена': {'Тип': 'Антена'},
    'динамік': {'Тип': 'Динамік'},
    'сенсор': {'Тип': 'Сенсор'},
}

# Бренди автомобілів для параметра Сумісність
CAR_BRANDS = [
    'Audi', 'BMW', 'Mercedes', 'Toyota', 'Volkswagen', 'VW',
    'Ford', 'Hyundai', 'Kia', 'Nissan', 'Honda', 'Mazda',
    'Subaru', 'Mitsubishi', 'Volvo', 'Skoda', 'Renault',
    'Peugeot', 'Citroen', 'Opel', 'Chevrolet', 'Jeep',
    'Land Rover', 'Range Rover', 'Porsche', 'Lexus', 'Infiniti',
    'Acura', 'Cadillac', 'Lincoln', 'Buick', 'GMC',
    'Dodge', 'Chrysler', 'Jeep', 'RAM', 'Tesla',
    'Lada', 'ВАЗ', 'УАЗ', 'ГАЗ', 'МАЗ', 'КамАЗ',
    'truck', 'Truck', 'universal', 'Universal',
]

def extract_params_from_name(name: str, vendor: str, article: str) -> dict:
    """Витягує параметри з назви товару"""
    params = {}
    name_lower = name.lower()

    # 1. Бренд (vendor)
    if vendor:
        params['Бренд'] = vendor

    # 2. Тип товару з назви
    for keyword, type_params in TYPE_PARAMS.items():
        if keyword in name_lower:
            params.update(type_params)
            break

    # 3. Сумісність (марка авто)
    compat = []
    for brand in CAR_BRANDS:
        if brand.lower() in name_lower or brand in name:
            compat.append(brand)
    if compat:
        params['Сумісність'] = ', '.join(compat[:3])

    # 4. Артикул
    if article and article not in name:
        params['Артикул'] = article
    else:
        # Витягуємо артикул з дужок в назві
        match = re.search(r'\(([A-Z0-9\-\.\/]+)\)', name)
        if match:
            params['Артикул'] = match.group(1)

    # 5. Колір
    colors = {
        'чорн': 'Чорний', 'білий': 'Білий', 'срібн': 'Срібний',
        'сірий': 'Сірий', 'червон': 'Червоний', 'синій': 'Синій',
    }
    for color_key, color_val in colors.items():
        if color_key in name_lower:
            params['Колір'] = color_val
            break

    # 6. Розмір/діагональ
    size_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:дюйм|"|inch|\'\')', name_lower)
    if size_match:
        params['Діагональ'] = f'{size_match.group(1)}"'

    # 7. Роздільна здатність
    res_match = re.search(r'(\d{3,4}[xXх×]\d{3,4})', name)
    if res_match:
        params['Роздільна здатність'] = res_match.group(1)

    # 8. Країна виробник
    params['Країна-виробник'] = 'Китай'

    return params

def process_without_params(limit: int = None):
    """Обробляє товари без параметрів"""
    conn = get_connection()
    cur = conn.cursor()

    query = """SELECT id, article, name_ua, vendor 
               FROM carvol_products 
               WHERE has_params = false"""
    if limit:
        query += f" LIMIT {limit}"

    cur.execute(query)
    rows = cur.fetchall()
    logger.info(f"[PARAMS] Processing {len(rows)} products without params")

    updated = 0
    for row in rows:
        params = extract_params_from_name(
            row['name_ua'] or '',
            row['vendor'] or '',
            row['article'] or ''
        )

        has_params = len(params) >= 3

        cur.execute("""
            UPDATE carvol_products SET
                params = %s,
                has_params = %s,
                status = 'params_generated'
            WHERE id = %s
        """, (json.dumps(params, ensure_ascii=False), has_params, row['id']))
        updated += 1

    conn.commit()

    # Статистика після обробки
    cur.execute("SELECT has_params, COUNT(*) FROM carvol_products GROUP BY has_params")
    logger.info("[PARAMS] Result:")
    for r in cur.fetchall():
        logger.info(f"  has_params={r['has_params']}: {r['count']}")

    cur.close()
    conn.close()
    logger.success(f"[PARAMS] Done: {updated} updated")
    return updated

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.test:
        # Тест на кількох прикладах
        test_cases = [
            ("Кріплення під камеру заднього огляду для Audi QAU027B", "QIV", "QAU027B"),
            ("Камера заднього огляду QIV QCV-1058D для BMW X5", "QIV", "QCV-1058D"),
            ("Автомагнітола Teyes CC3 2K 9 дюймів для Toyota Camry", "Teyes", "CC3-2K-9"),
            ("Адаптер CAN шини для Volkswagen Golf VII Mekede", "Mekede", "CAN-VW-07"),
        ]
        for name, vendor, article in test_cases:
            params = extract_params_from_name(name, vendor, article)
            print(f"\nНазва: {name[:60]}")
            print(f"Параметри ({len(params)}): {json.dumps(params, ensure_ascii=False)}")
    else:
        count = process_without_params(args.limit)
        print(f"✅ Оновлено: {count} товарів")

````

### `agents/scraper/import_carvol.py` — 155 рядків

````python
import os, sys, json, re
from xml.etree import ElementTree as ET
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

FEED_FILE = "/home/tek/agent-system/data/carvol_feed.xml"

def fix_pic_url(url: str) -> str:
    """Виправляє URL фото з Prom CDN на прямий"""
    if not url:
        return ""
    # Prom CDN трансформації — беремо оригінальний ID
    # https://images.prom.ua/WkSMubxVO=/6304575772_k → потрібне пряме посилання
    # Спробуємо витягнути ID файлу
    match = re.search(r'/(\d+)_', url)
    if match:
        file_id = match.group(1)
        return f"https://images.prom.ua/{file_id}_b.jpg"
    return url

def check_name_unique(names: set, name: str, sku: str) -> str:
    """Робить назву унікальною якщо є дублі"""
    if name in names:
        # Додаємо артикул якщо не унікальна
        new_name = f"{name} ({sku})"
        if new_name in names:
            new_name = f"{name} {sku}"
        name = new_name
    names.add(name)
    return name

def parse_and_import():
    logger.info(f"[CARVOL] Parsing {FEED_FILE}...")
    tree = ET.parse(FEED_FILE)
    root = tree.getroot()
    shop = root.find('shop')
    offers = shop.find('offers').findall('offer')
    logger.info(f"[CARVOL] Found {len(offers)} offers")

    conn = get_connection()
    cur = conn.cursor()

    inserted = 0
    updated = 0
    skipped = 0
    names_seen = set()

    for offer in offers:
        try:
            external_id = offer.get('id', '').strip()
            available = offer.get('available', 'true') == 'true'

            article_el = offer.find('article')
            article = article_el.text.strip() if article_el is not None and article_el.text else external_id

            price_el = offer.find('price')
            price = float(price_el.text.replace(',','.')) if price_el is not None and price_el.text else 0

            name_ua_el = offer.find('name_ua')
            name_ua = name_ua_el.text.strip() if name_ua_el is not None and name_ua_el.text else ""

            # Унікальність назви
            name_ua = check_name_unique(names_seen, name_ua, article)

            desc_ua_el = offer.find('description_ua')
            desc_ua = desc_ua_el.text.strip() if desc_ua_el is not None and desc_ua_el.text else ""
            # Очищаємо від HTML
            desc_ua = re.sub(r'<[^>]+>', ' ', desc_ua)
            desc_ua = re.sub(r'\s+', ' ', desc_ua).strip()[:5000]

            vendor_el = offer.find('vendor')
            vendor = vendor_el.text.strip() if vendor_el is not None and vendor_el.text else ""

            category_el = offer.find('categoryId')
            category_id = category_el.text.strip() if category_el is not None and category_el.text else ""

            stock_el = offer.find('stock_quantity')
            stock = int(stock_el.text) if stock_el is not None and stock_el.text else 0

            # Фото — виправляємо URL
            pictures = []
            for pic in offer.findall('picture'):
                if pic.text and pic.text.strip():
                    fixed_url = fix_pic_url(pic.text.strip())
                    if fixed_url:
                        pictures.append(fixed_url)

            # Параметри
            params = {}
            for param in offer.findall('param'):
                name = param.get('name', '').strip()
                val = param.text.strip() if param.text else ''
                if name and val:
                    params[name] = val

            has_params = len(params) >= 3

            cur.execute("""
                INSERT INTO carvol_products
                    (external_id, article, name_ua, description_ua, vendor,
                     price, category_id, pictures, params, stock_quantity,
                     available, has_params, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'new')
                ON CONFLICT (external_id) DO UPDATE SET
                    price = EXCLUDED.price,
                    stock_quantity = EXCLUDED.stock_quantity,
                    available = EXCLUDED.available,
                    params = EXCLUDED.params,
                    status = 'updated'
            """, (
                external_id, article, name_ua, desc_ua, vendor,
                price, category_id, json.dumps(pictures),
                json.dumps(params), stock, available, has_params
            ))

            if cur.rowcount == 1:
                inserted += 1
            else:
                updated += 1

            if (inserted + updated) % 500 == 0:
                conn.commit()
                logger.info(f"[CARVOL] Progress: {inserted} inserted, {updated} updated")

        except Exception as e:
            logger.error(f"[CARVOL] Error {external_id}: {e}")
            skipped += 1

    conn.commit()
    cur.close()
    conn.close()

    logger.success(f"[CARVOL] Done: {inserted} inserted, {updated} updated, {skipped} skipped")
    return inserted, updated

if __name__ == "__main__":
    inserted, updated = parse_and_import()
    print(f"\n✅ Імпорт: {inserted} нових, {updated} оновлених")

    # Статистика
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT has_params, COUNT(*) FROM carvol_products GROUP BY has_params")
    for r in cur.fetchall():
        print(f"  has_params={r['has_params']}: {r['count']} товарів")
    cur.execute("SELECT vendor, COUNT(*) as cnt FROM carvol_products GROUP BY vendor ORDER BY cnt DESC LIMIT 5")
    print("\nТоп бренди:")
    for r in cur.fetchall():
        print(f"  {r['vendor']}: {r['cnt']}")
    cur.close()
    conn.close()

````

### `agents/scraper/import_from_prom.py` — 160 рядків

````python
import os, sys, json, asyncio
import aiohttp
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
from shared.utils.db import get_connection

TOKEN = os.getenv("PROM_API_TOKEN")
API_URL = "https://my.prom.ua/api/v1/products/list"

def get_our_skus() -> set:
    """Отримуємо SKU які є в нашій БД"""
    from shared.utils.db import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT sku FROM my_products WHERE sku IS NOT NULL")
    skus = {r["sku"] for r in cur.fetchall()}
    cur.close(); conn.close()
    logger.info(f"[PROM] Our SKUs in DB: {len(skus)}")
    return skus

async def fetch_all_products() -> list:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    our_skus = get_our_skus()
    all_products = []
    page_from_id = None
    found = 0

    async with aiohttp.ClientSession() as session:
        while True:
            params = {"limit": 100}
            if page_from_id:
                params["page_from_id"] = page_from_id

            async with session.get(API_URL, headers=headers, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"[PROM] HTTP {resp.status}: {text[:200]}")
                    break
                data = await resp.json()

            page = data.get("products", [])
            if not page:
                break

            for p in page:
                sku = p.get("sku","").strip()
                if sku in our_skus:
                    all_products.append(p)
                    found += 1

            if found % 500 == 0 and found > 0:
                logger.info(f"[PROM] Found {found} matching products...")

            if len(page) < 100:
                break
            page_from_id = page[-1]["id"]

            # Якщо знайшли всі наші товари — зупиняємось
            if found >= len(our_skus):
                logger.info("[PROM] All our SKUs found, stopping")
                break

    logger.success(f"[PROM] Total found: {len(all_products)} matching products")
    return all_products

def import_to_db(products: list):
    conn = get_connection()
    cur = conn.cursor()

    # Додаємо колонки якщо нема
    cur.execute("""
        ALTER TABLE my_products
        ADD COLUMN IF NOT EXISTS price_supplier DECIMAL(12,2),
        ADD COLUMN IF NOT EXISTS pictures JSONB,
        ADD COLUMN IF NOT EXISTS params JSONB,
        ADD COLUMN IF NOT EXISTS vendor VARCHAR(100),
        ADD COLUMN IF NOT EXISTS prom_id BIGINT
    """)
    conn.commit()

    updated = 0
    inserted = 0

    for p in products:
        sku = p.get("sku", "").strip()
        if not sku:
            continue

        price = float(p.get("price") or 0)
        name_uk = p.get("name", "").strip()
        description = p.get("description", "") or ""
        presence = p.get("presence", "")
        prom_id = p.get("id")

        # Фото
        images = p.get("images", []) or []
        pictures = [img.get("url", "") for img in images if img.get("url")]

        # Параметри
        attrs = p.get("attributes", []) or []
        params = {}
        for attr in attrs:
            name = attr.get("name", "")
            val = attr.get("value", "")
            if name and val:
                params[name] = val

        # Категорія
        category = p.get("category", {}) or {}
        category_name = category.get("caption", "") or category.get("name", "")

        # stock_quantity
        stock = 10 if presence in ("available", "positive") else 0

        # Спробуємо оновити по SKU
        cur.execute("""
            UPDATE my_products SET
                price_supplier = %s,
                pictures = %s,
                params = %s,
                vendor = 'TOPTUL',
                prom_id = %s,
                name_uk = CASE WHEN name_uk IS NULL OR name_uk = '' THEN %s ELSE name_uk END,
                description_raw = CASE WHEN description_raw IS NULL OR description_raw = '' THEN %s ELSE description_raw END,
                category_epicentr = CASE WHEN category_epicentr IS NULL OR category_epicentr = '' THEN %s ELSE category_epicentr END,
                status = 'processed'
            WHERE sku = %s
        """, (price, json.dumps(pictures), json.dumps(params),
              prom_id, name_uk, description, category_name, sku))

        if cur.rowcount > 0:
            updated += 1
        else:
            # Вставляємо новий
            cur.execute("""
                INSERT INTO my_products (sku, name_uk, description_raw, category_epicentr,
                    price_supplier, pictures, params, vendor, prom_id, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'TOPTUL', %s, 'processed')
                ON CONFLICT (sku) DO NOTHING
            """, (sku, name_uk, description, category_name,
                  price, json.dumps(pictures), json.dumps(params), prom_id))
            inserted += 1

    conn.commit()
    cur.close()
    conn.close()
    logger.success(f"[PROM] DB: {updated} updated, {inserted} inserted")
    return updated, inserted

async def main():
    products = await fetch_all_products()
    updated, inserted = import_to_db(products)
    print(f"\n✅ Готово: {updated} оновлено, {inserted} додано")
    print(f"   Всього в Prom: {len(products)} товарів")

if __name__ == "__main__":
    asyncio.run(main())

````

### `agents/scraper/import_from_prom_xml.py` — 161 рядків

````python
import os, sys, json, re
from xml.etree import ElementTree as ET
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from dotenv import load_dotenv
load_dotenv('/home/tekken/agent-system/.env')
from shared.utils.db import get_connection

FEED_FILE = "/home/tekken/agent-system/data/prom_feed.xml"

def parse_and_import():
    logger.info(f"[IMPORT] Parsing {FEED_FILE}...")
    tree = ET.parse(FEED_FILE)
    root = tree.getroot()
    shop = root.find('shop')
    offers = shop.find('offers').findall('offer')
    logger.info(f"[IMPORT] Found {len(offers)} offers")

    conn = get_connection()
    cur = conn.cursor()

    # Додаємо колонки якщо нема
    cur.execute("""
        ALTER TABLE my_products
        ADD COLUMN IF NOT EXISTS price_supplier DECIMAL(12,2),
        ADD COLUMN IF NOT EXISTS pictures JSONB,
        ADD COLUMN IF NOT EXISTS params JSONB,
        ADD COLUMN IF NOT EXISTS vendor VARCHAR(100),
        ADD COLUMN IF NOT EXISTS prom_id BIGINT,
        ADD COLUMN IF NOT EXISTS availability VARCHAR(20)
    """)
    conn.commit()

    updated = 0
    inserted = 0
    skipped = 0

    for offer in offers:
        prom_id = offer.get('id')
        available = offer.get('available', 'true')

        # SKU/артикул
        # SKU в vendorCode або article
        sku = None
        for tag in ['vendorCode', 'article']:
            el = offer.find(tag)
            if el is not None and el.text and el.text.strip():
                sku = el.text.strip()
                break
        if not sku:
            skipped += 1
            continue

        # Ціна
        price_el = offer.find('price')
        price = float(price_el.text) if price_el is not None and price_el.text else 0

        # Назва українська
        name_ua = None
        for tag in ['name_ua', 'model_ua', 'name', 'model']:
            el = offer.find(tag)
            if el is not None and el.text and el.text.strip():
                name_ua = el.text.strip()
                break

        # Опис
        desc_ua = None
        for tag in ['description_ua', 'description']:
            el = offer.find(tag)
            if el is not None and el.text and el.text.strip():
                desc_ua = el.text.strip()[:5000]
                break

        # Фото
        pictures = []
        for pic in offer.findall('picture'):
            if pic.text and pic.text.strip():
                url = pic.text.strip()
                if url.startswith('http'):
                    pictures.append(url)

        # Параметри
        params = {}
        param_list = []
        for param in offer.findall('param'):
            name = param.get('name', '')
            val = param.text or ''
            if name and val.strip():
                params[name] = val.strip()
            elif val.strip():
                param_list.append(val.strip())
        if param_list:
            params['_values'] = param_list

        # Vendor
        vendor_el = offer.find('vendor')
        vendor = vendor_el.text.strip() if vendor_el is not None and vendor_el.text else 'TOPTUL'

        # Stock
        stock_el = offer.find('stock_quantity')
        if stock_el is None:
            stock_el = offer.find('quantity_in_stock')
        stock = int(stock_el.text) if stock_el is not None and stock_el.text else (10 if available == 'true' else 0)

        # Категорія з прому
        cat_id = offer.find('categoryId')

        # Оновлюємо існуючий запис
        cur.execute("""
            UPDATE my_products SET
                price_supplier = %s,
                pictures = %s,
                params = %s,
                vendor = %s,
                prom_id = %s,
                availability = %s,
                name_uk = CASE WHEN name_uk IS NULL OR name_uk = '' THEN %s ELSE name_uk END,
                description_raw = CASE WHEN description_raw IS NULL OR description_raw = '' THEN %s ELSE description_raw END,
                status = 'processed'
            WHERE sku = %s
        """, (
            price, json.dumps(pictures), json.dumps(params),
            vendor, prom_id, available,
            name_ua, desc_ua, sku
        ))

        if cur.rowcount > 0:
            updated += 1
        else:
            # Вставляємо новий
            cur.execute("""
                INSERT INTO my_products
                    (sku, name_uk, description_raw, price_supplier, pictures, params, vendor, prom_id, availability, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'processed')
                ON CONFLICT (sku) DO UPDATE SET
                    price_supplier = EXCLUDED.price_supplier,
                    pictures = EXCLUDED.pictures,
                    params = EXCLUDED.params,
                    vendor = EXCLUDED.vendor,
                    prom_id = EXCLUDED.prom_id,
                    availability = EXCLUDED.availability,
                    status = 'processed'
            """, (sku, name_ua, desc_ua, price, json.dumps(pictures),
                  json.dumps(params), vendor, prom_id, available))
            inserted += 1

        if (updated + inserted) % 500 == 0:
            conn.commit()
            logger.info(f"[IMPORT] Progress: {updated} updated, {inserted} inserted, {skipped} skipped")

    conn.commit()
    cur.close()
    conn.close()

    logger.success(f"[IMPORT] Done: {updated} updated, {inserted} inserted, {skipped} skipped")
    return updated, inserted

if __name__ == "__main__":
    updated, inserted = parse_and_import()
    print(f"\n✅ Імпорт завершено: {updated} оновлено, {inserted} додано")

````

### `agents/scraper/import_supplier_feed.py` — 115 рядків

````python
import os, sys, json, re, requests
from loguru import logger
from xml.etree import ElementTree as ET

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
from shared.utils.db import get_connection

FEED_URL = "https://toptul.online/products_feed.xml?hash_tag=442309995a1416e3104d287504a1846f&sales_notes=&product_ids=&label_ids=3882792&exclude_fields=&html_description=1&yandex_cpa=&process_presence_sure=&languages=uk%2Cru&group_ids="

def download_feed(url: str) -> bytes:
    logger.info(f"[IMPORT] Downloading feed...")
    resp = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    logger.success(f"[IMPORT] Downloaded {len(resp.content)//1024}KB")
    return resp.content

def parse_and_import(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    shop = root.find("shop")
    offers = shop.find("offers")

    conn = get_connection()
    cur = conn.cursor()

    # Додаємо нові колонки якщо нема
    cur.execute("""
        ALTER TABLE my_products
        ADD COLUMN IF NOT EXISTS price_supplier DECIMAL(12,2),
        ADD COLUMN IF NOT EXISTS pictures JSONB,
        ADD COLUMN IF NOT EXISTS params JSONB,
        ADD COLUMN IF NOT EXISTS vendor VARCHAR(100)
    """)
    conn.commit()

    updated = 0
    skipped = 0

    for offer in offers.findall("offer"):
        sku = offer.get("id", "").strip()
        if not sku:
            continue

        # Ціна
        price_el = offer.find("price")
        price = float(price_el.text) if price_el is not None and price_el.text else 0

        # Фото
        pictures = [p.text for p in offer.findall("picture") if p.text]

        # Назва українська
        name_ua = None
        for tag in ["name_ua", "model_ua", "name", "model"]:
            el = offer.find(tag)
            if el is not None and el.text:
                name_ua = el.text.strip()
                break

        # Опис
        desc_ua = None
        for tag in ["description_ua", "description"]:
            el = offer.find(tag)
            if el is not None and el.text:
                desc_ua = el.text.strip()
                break

        # Параметри
        params = {}
        for param in offer.findall("param"):
            name = param.get("name", "")
            val = param.text or ""
            if name and val.strip():
                params[name] = val.strip()

        # Vendor
        vendor_el = offer.find("vendor")
        vendor = vendor_el.text.strip() if vendor_el is not None else "TOPTUL"

        # Оновлюємо існуючий запис або пропускаємо
        cur.execute("""
            UPDATE my_products SET
                price_supplier = %s,
                pictures = %s,
                params = %s,
                vendor = %s,
                description_raw = COALESCE(NULLIF(description_raw,''), %s),
                name_uk = COALESCE(NULLIF(name_uk,''), %s)
            WHERE sku = %s
        """, (
            price,
            json.dumps(pictures),
            json.dumps(params),
            vendor,
            desc_ua,
            name_ua,
            sku
        ))

        if cur.rowcount > 0:
            updated += 1
        else:
            skipped += 1

    conn.commit()
    cur.close()
    conn.close()

    logger.success(f"[IMPORT] Done: {updated} updated, {skipped} not found in DB")
    return updated

if __name__ == "__main__":
    xml_bytes = download_feed(FEED_URL)
    count = parse_and_import(xml_bytes)
    print(f"✅ Імпортовано: {count} товарів")

````

### `agents/scraper/market_price_analyzer.py` — 199 рядків

````python
import os, sys, json, re, time
from loguru import logger
from playwright.sync_api import sync_playwright

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

def get_competitor_prices(sku: str, min_price: float = 0) -> dict:
    """Отримує ціни конкурентів з Prom для артикулу"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(f'https://prom.ua/ua/search?search_term={sku}',
                      wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(2000)

            prices = []
            # Шукаємо ціни в елементах
            items = page.query_selector_all('[data-qaid="product_price"]')
            for item in items:
                text = item.inner_text().strip()
                nums = re.findall(r'\d[\d\s]*', text)
                for n in nums:
                    n = int(n.replace(' ', ''))
                    # Фільтруємо: ціна має бути більше закупки і менше 500000
                    if min_price * 0.8 < n < 500000:
                        prices.append(n)

            # Якщо не знайшло через data-qaid — шукаємо через JS
            if not prices:
                data = page.evaluate('''() => {
                    const items = document.querySelectorAll(".x-gallery-tile");
                    return Array.from(items).map(el => {
                        const price = el.querySelector("[class*=price]");
                        return price ? price.innerText : null;
                    }).filter(Boolean);
                }''')
                for text in data:
                    nums = re.findall(r'\d[\d\s]*', text)
                    for n in nums:
                        n = int(n.replace(' ', ''))
                        if min_price * 0.8 < n < 500000:
                            prices.append(n)

        except Exception as e:
            logger.error(f"[MARKET] Error for {sku}: {e}")
            prices = []
        finally:
            browser.close()

    if not prices:
        return {'sku': sku, 'error': 'no prices', 'count': 0}

    # Фільтруємо викиди тільки якщо є достатньо цін
    if len(prices) > 3:
        avg = sum(prices) / len(prices)
        std = (sum((p-avg)**2 for p in prices) / len(prices)) ** 0.5
        filtered = [p for p in prices if abs(p - avg) < 2 * std]
        if filtered:  # Якщо після фільтрації є ціни
            prices = filtered

    return {
        'sku': sku,
        'min': min(prices),
        'max': max(prices),
        'avg': round(sum(prices) / len(prices)),
        'median': sorted(prices)[len(prices)//2],
        'count': len(prices),
        'prices': sorted(prices),
    }

def get_cpa_rate(category_name: str = None) -> float:
    """Повертає CPA ставку для категорії з БД"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        if category_name:
            cur.execute("""SELECT cpa_rate FROM prom_cpa_rates 
                WHERE category_name ILIKE %s LIMIT 1""", (f"%{category_name}%",))
            row = cur.fetchone()
            if row:
                cur.close(); conn.close()
                return float(row["cpa_rate"]) / 100
        # Дефолт для інструментів
        cur.close(); conn.close()
    except:
        pass
    return 0.15  # 15% дефолт для інструментів TOPTUL

def calculate_our_price(zakupka: float, avg_market: float, cpa_rate: float = 0.15) -> float:
    """Розраховує нашу ціну з урахуванням реального CPA"""
    delivery = 20  # середня вартість доставки
    margin = 0.20  # бажана маржа 20%
    
    # Мінімальна ціна = (закупка + доставка) / (1 - CPA) * (1 + маржа)
    min_price = (zakupka + delivery) / (1 - cpa_rate) * (1 + margin)
    
    # Цільова = середня ринкова * 0.95 (на 5% нижче)
    target = avg_market * 0.95
    
    # Беремо більше з двох
    price = max(target, min_price)
    
    # Округлення до 10 грн
    return round(price / 10) * 10

def analyze_and_update(limit: int = 10):
    """Аналізує ціни і оновлює БД"""
    conn = get_connection()
    cur = conn.cursor()

    # Таблиця для зберігання ринкових цін
    cur.execute('''
        CREATE TABLE IF NOT EXISTS market_prices (
            sku VARCHAR(100) PRIMARY KEY,
            min_price DECIMAL(12,2),
            max_price DECIMAL(12,2),
            avg_price DECIMAL(12,2),
            median_price DECIMAL(12,2),
            sellers_count INTEGER,
            our_price DECIMAL(12,2),
            analyzed_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    conn.commit()

    # Беремо товари для аналізу
    cur.execute('''
        SELECT sku, price_supplier 
        FROM my_products 
        WHERE price_supplier > 0
        AND sku NOT IN (SELECT sku FROM market_prices)
        ORDER BY price_supplier DESC
        LIMIT %s
    ''', (limit,))
    products = cur.fetchall()
    logger.info(f"[MARKET] Analyzing {len(products)} products")

    for p in products:
        sku = p['sku']
        zakupka = float(p['price_supplier']) * 0.88

        logger.info(f"[MARKET] Searching: {sku}")
        result = get_competitor_prices(sku, min_price=zakupka)

        if result.get('count', 0) > 0:
            our_price = calculate_our_price(zakupka, result['avg'])
            cur.execute('''
                INSERT INTO market_prices 
                (sku, min_price, max_price, avg_price, median_price, sellers_count, our_price)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (sku) DO UPDATE SET
                    min_price=EXCLUDED.min_price,
                    avg_price=EXCLUDED.avg_price,
                    our_price=EXCLUDED.our_price,
                    analyzed_at=NOW()
            ''', (sku, result['min'], result['max'], result['avg'],
                  result['median'], result['count'], our_price))

            # Оновлюємо ціну в my_products
            cur.execute('UPDATE my_products SET price_our=%s WHERE sku=%s',
                       (our_price, sku))
            conn.commit()

            logger.success(f"[MARKET] {sku}: avg={result['avg']} → our={our_price} грн")
        else:
            logger.warning(f"[MARKET] {sku}: no competitors found")

        time.sleep(2)  # Пауза між запитами

    cur.close(); conn.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--sku", type=str, default=None)
    args = parser.parse_args()

    if args.sku:
        # Тест одного артикулу
        from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT price_supplier FROM my_products WHERE sku=%s", (args.sku,))
        row = cur.fetchone()
        zakupka = float(row['price_supplier']) * 0.88 if row else 100
        cur.close(); conn.close()

        result = get_competitor_prices(args.sku, zakupka)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get('count', 0) > 0:
            our = calculate_our_price(zakupka, result['avg'])
            print(f"Закупка: {zakupka:.0f} грн")
            print(f"Наша ціна: {our:.0f} грн")
    else:
        analyze_and_update(args.limit)

````

### `agents/scraper/playwright_base.py` — 514 рядків

````python
"""
agents/scraper/playwright_base.py
===================================
Базовий клас для всіх Playwright агентів.

Можливості:
- Self-Healing: автоматичний пошук нових селекторів при помилці
- Retry logic: повтор дій з exponential backoff
- Screenshot on error: скріншот при кожній помилці
- Session management: збереження/відновлення сесій
- Telegram alerts: сповіщення при критичних помилках
- Random delays: анти-бот поведінка
- Proxy support: ротація проксі
"""

import os, sys, json, asyncio, time, random
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Error as PlaywrightError

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# =============================================
# КОНСТАНТИ
# =============================================

SCREENSHOTS_DIR = '/home/tek/agent-system/logs/screenshots'
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')

# User Agents — реалістичні браузери
USER_AGENTS = [
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
]


# =============================================
# БАЗОВИЙ КЛАС
# =============================================

class PlaywrightBase:
    """
    Базовий клас для Playwright агентів.
    Успадковуй його в epicentr_cabinet.py, competitor_monitor.py і т.д.
    """

    def __init__(self, site: str, headless: bool = True, proxy: str = None):
        self.site = site
        self.headless = headless
        self.proxy = proxy
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None
        self.session_data = {}
        self._intercepted_requests = []

        # Фіксований UA для цієї сесії
        self.user_agent = self._get_or_create_ua()

        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    def _get_or_create_ua(self) -> str:
        """Отримує збережений UA або створює новий."""
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute('SELECT user_agent FROM browser_sessions WHERE site=%s', (self.site,))
            row = cur.fetchone()
            cur.close(); conn.close()
            if row and row['user_agent']:
                return row['user_agent']
        except:
            pass
        return random.choice(USER_AGENTS)

    # =============================================
    # ЗАПУСК І ЗУПИНКА
    # =============================================

    async def start(self):
        """Запускає браузер і відновлює сесію якщо є."""
        self.playwright = await async_playwright().start()

        launch_args = {
            'headless': self.headless,
            'args': [
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
            ]
        }

        if self.proxy:
            launch_args['proxy'] = {'server': self.proxy}

        self.browser = await self.playwright.chromium.launch(**launch_args)

        context_args = {
            'user_agent': self.user_agent,
            'viewport': {'width': 1280, 'height': 800},
            'locale': 'uk-UA',
            'timezone_id': 'Europe/Kyiv',
            'extra_http_headers': {
                'Accept-Language': 'uk-UA,uk;q=0.9,en;q=0.8',
            }
        }

        self.context = await self.browser.new_context(**context_args)

        # Приховуємо ознаки automation
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
        """)

        self.page = await self.context.new_page()

        # Відновлюємо сесію якщо є
        await self._load_session()

        logger.info(f'[{self.site}] Браузер запущено')
        return self

    async def stop(self):
        """Зупиняє браузер."""
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info(f'[{self.site}] Браузер зупинено')
        except Exception as e:
            logger.error(f'[{self.site}] Помилка зупинки: {e}')

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()

    # =============================================
    # СЕСІЇ
    # =============================================

    async def _load_session(self):
        """Відновлює cookies і localStorage з БД."""
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                'SELECT cookies, local_storage, valid_until FROM browser_sessions WHERE site=%s AND is_active=TRUE',
                (self.site,)
            )
            row = cur.fetchone()
            cur.close(); conn.close()

            if row and row['valid_until'] and row['valid_until'] > datetime.now():
                if row['cookies']:
                    await self.context.add_cookies(row['cookies'])
                if row['local_storage']:
                    self.session_data['local_storage'] = row['local_storage']
                logger.success(f'[{self.site}] Сесія відновлена (дійсна до {row["valid_until"].strftime("%d.%m %H:%M")})')
                return True
        except Exception as e:
            logger.warning(f'[{self.site}] Не вдалось відновити сесію: {e}')
        return False

    async def save_session(self, valid_hours: int = 23):
        """Зберігає поточну сесію в БД."""
        try:
            cookies = await self.context.cookies()
            valid_until = datetime.now() + timedelta(hours=valid_hours)

            conn = get_connection()
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO browser_sessions (site, cookies, user_agent, valid_until, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (site) DO UPDATE SET
                    cookies=EXCLUDED.cookies,
                    user_agent=EXCLUDED.user_agent,
                    valid_until=EXCLUDED.valid_until,
                    updated_at=NOW()
            ''', (self.site, json.dumps(cookies), self.user_agent, valid_until))
            conn.commit(); cur.close(); conn.close()
            logger.success(f'[{self.site}] Сесія збережена до {valid_until.strftime("%d.%m %H:%M")}')
        except Exception as e:
            logger.error(f'[{self.site}] Помилка збереження сесії: {e}')

    async def check_session(self) -> bool:
        """Перевіряє чи сесія активна в БД."""
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                'SELECT valid_until FROM browser_sessions WHERE site=%s AND is_active=TRUE',
                (self.site,)
            )
            row = cur.fetchone()
            cur.close(); conn.close()
            return bool(row and row['valid_until'] and row['valid_until'] > datetime.now())
        except:
            return False

    # =============================================
    # SELF-HEALING ACTIONS
    # =============================================

    async def resilient_click(self, selector: str, description: str = '', timeout: int = 10000) -> bool:
        """
        Клік з Self-Healing: якщо елемент не знайдено — шукаємо альтернативний селектор.
        """
        # Спроба 1: прямий клік
        try:
            await self.page.click(selector, timeout=timeout)
            logger.debug(f'[{self.site}] Click OK: {description or selector}')
            return True
        except PlaywrightError:
            pass

        # Спроба 2: пошук по тексту якщо selector виглядає як текст
        if not selector.startswith(('.', '#', '[', '*', 'button', 'a', 'div', 'span')):
            try:
                await self.page.get_by_text(selector, exact=False).first.click(timeout=5000)
                logger.info(f'[{self.site}] Click by text OK: {selector}')
                return True
            except PlaywrightError:
                pass

        # Спроба 3: Self-Healing через аналіз DOM
        logger.warning(f'[{self.site}] Element not found: {description or selector} — Self-Healing...')
        screenshot = await self.screenshot(f'error_click_{description or "unknown"}')

        new_selector = await self._find_selector_by_description(description or selector)
        if new_selector:
            try:
                await self.page.click(new_selector, timeout=5000)
                logger.success(f'[{self.site}] Self-Healing click OK: {new_selector}')
                await self._log_action('self_healing_click', 'success',
                    {'original': selector, 'healed': new_selector})
                return True
            except PlaywrightError:
                pass

        # Фінал: Telegram повідомлення
        await self._telegram_alert(
            f'⚠️ [{self.site}] Не можу клікнути: {description or selector}',
            screenshot
        )
        return False

    async def resilient_fill(self, selector: str, value: str, description: str = '') -> bool:
        """
        Заповнення поля з Self-Healing.
        """
        try:
            await self.page.fill(selector, value, timeout=10000)
            return True
        except PlaywrightError:
            logger.warning(f'[{self.site}] Fill failed: {description or selector} — Self-Healing...')
            screenshot = await self.screenshot(f'error_fill_{description or "unknown"}')

            new_selector = await self._find_selector_by_description(description or selector)
            if new_selector:
                try:
                    await self.page.fill(new_selector, value, timeout=5000)
                    return True
                except PlaywrightError:
                    pass

            await self._telegram_alert(
                f'⚠️ [{self.site}] Не можу заповнити поле: {description or selector}',
                screenshot
            )
            return False

    async def _find_selector_by_description(self, description: str) -> str | None:
        """
        Аналізує DOM і намагається знайти новий селектор.
        Шукає по тексту, placeholder, aria-label.
        """
        try:
            # Пробуємо різні варіанти пошуку
            variants = [
                f'[aria-label*="{description}"]',
                f'[placeholder*="{description}"]',
                f'[title*="{description}"]',
                f'button:has-text("{description}")',
                f'a:has-text("{description}")',
                f'[data-testid*="{description.lower().replace(" ", "-")}"]',
            ]
            for v in variants:
                try:
                    count = await self.page.locator(v).count()
                    if count > 0:
                        logger.info(f'Self-Healing знайшов: {v}')
                        return v
                except:
                    continue
        except:
            pass
        return None

    # =============================================
    # БАЗОВІ ДІЇ
    # =============================================

    async def navigate(self, url: str, wait_for: str = 'networkidle'):
        """Перехід на URL з очікуванням завантаження."""
        await self.page.goto(url, wait_until=wait_for, timeout=30000)
        await self.random_delay(500, 1500)

    async def wait_for(self, selector: str, timeout: int = 30000):
        """Чекає появи елемента."""
        await self.page.wait_for_selector(selector, timeout=timeout)

    async def get_text(self, selector: str) -> str:
        """Повертає текст елемента."""
        try:
            return await self.page.inner_text(selector)
        except:
            return ''

    async def get_table(self, selector: str) -> list:
        """Парсить HTML таблицю в список dict."""
        try:
            return await self.page.evaluate(f'''() => {{
                const table = document.querySelector('{selector}');
                if (!table) return [];
                const headers = [...table.querySelectorAll('th')].map(h => h.innerText.trim());
                return [...table.querySelectorAll('tbody tr')].map(row => {{
                    const cells = [...row.querySelectorAll('td')].map(c => c.innerText.trim());
                    return headers.reduce((obj, h, i) => {{ obj[h] = cells[i] || ''; return obj; }}, {{}});
                }});
            }}''')
        except:
            return []

    async def execute_js(self, script: str):
        """Виконує JS на сторінці."""
        return await self.page.evaluate(script)

    async def random_delay(self, min_ms: int = 300, max_ms: int = 1200):
        """Випадкова затримка для анти-бот поведінки."""
        delay = random.randint(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)

    async def scroll_down(self, times: int = 3):
        """Скрол вниз для нескінченного скролу."""
        for _ in range(times):
            await self.page.keyboard.press('End')
            await self.random_delay(800, 2000)

    # =============================================
    # СКРІНШОТИ
    # =============================================

    async def screenshot(self, name: str = 'screenshot') -> str:
        """Робить скріншот і зберігає в logs/screenshots/."""
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{SCREENSHOTS_DIR}/{self.site}_{name}_{ts}.png'
        await self.page.screenshot(path=filename, full_page=False)
        logger.debug(f'Screenshot: {filename}')
        return filename

    # =============================================
    # ПЕРЕХОПЛЕННЯ МЕРЕЖІ
    # =============================================

    async def intercept_start(self, filter_pattern: str = ''):
        """Починає запис XHR/fetch запитів."""
        self._intercepted_requests = []
        self._intercept_pattern = filter_pattern

        async def handle_response(response):
            url = response.url
            if filter_pattern and filter_pattern not in url:
                return
            if any(ext in url for ext in ['.css', '.js', '.png', '.jpg', '.woff', '.ico']):
                return
            try:
                body = await response.json()
                self._intercepted_requests.append({
                    'url': url,
                    'method': response.request.method,
                    'status': response.status,
                    'body': body,
                })
            except:
                pass

        self.page.on('response', handle_response)
        logger.info(f'[{self.site}] Intercept started (filter: {filter_pattern or "all"})')

    def intercept_stop(self) -> list:
        """Зупиняє запис і повертає всі перехоплені запити."""
        self.page.remove_listener('response', lambda *a: None)
        logger.info(f'[{self.site}] Intercepted {len(self._intercepted_requests)} requests')
        return self._intercepted_requests

    async def get_bearer_token(self) -> str:
        """Витягує Bearer token з localStorage або cookies."""
        try:
            # Перевіряємо localStorage
            token = await self.page.evaluate('''() => {
                const keys = ['token', 'access_token', 'auth_token', 'bearer', 'jwt'];
                for (const k of keys) {
                    const v = localStorage.getItem(k);
                    if (v) return v;
                }
                // Шукаємо в всіх ключах
                for (let i = 0; i < localStorage.length; i++) {
                    const k = localStorage.key(i);
                    const v = localStorage.getItem(k);
                    if (v && v.length > 20 && (v.startsWith('ey') || k.includes('token'))) {
                        return v;
                    }
                }
                return null;
            }''')
            if token:
                return token

            # Перевіряємо cookies
            cookies = await self.context.cookies()
            for c in cookies:
                if 'token' in c['name'].lower() or 'auth' in c['name'].lower():
                    return c['value']
        except:
            pass
        return ''

    # =============================================
    # ЗАВАНТАЖЕННЯ ФАЙЛІВ
    # =============================================

    async def download_file(self, click_selector: str, save_dir: str = '/tmp') -> str | None:
        """Клікає на посилання і чекає на завантаження файлу."""
        try:
            async with self.page.expect_download(timeout=60000) as download_info:
                await self.page.click(click_selector)
            download = await download_info.value
            filename = download.suggested_filename or f'download_{int(time.time())}'
            save_path = f'{save_dir}/{filename}'
            await download.save_as(save_path)
            logger.success(f'[{self.site}] Файл завантажено: {save_path}')
            return save_path
        except Exception as e:
            logger.error(f'[{self.site}] Download error: {e}')
            await self.screenshot('download_error')
            return None

    async def upload_file(self, selector: str, filepath: str) -> bool:
        """Завантажує файл через input[type=file]."""
        try:
            await self.page.set_input_files(selector, filepath)
            logger.success(f'[{self.site}] Файл завантажено: {filepath}')
            return True
        except Exception as e:
            logger.error(f'[{self.site}] Upload error: {e}')
            return False

    # =============================================
    # TELEGRAM СПОВІЩЕННЯ
    # =============================================

    async def _telegram_alert(self, message: str, screenshot_path: str = None):
        """Відправляє Telegram повідомлення і файл скріншоту."""
        import requests as req
        try:
            req.post(
                f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
                json={'chat_id': TELEGRAM_ADMIN, 'text': message, 'parse_mode': 'HTML'},
                timeout=10
            )
            if screenshot_path and os.path.exists(screenshot_path):
                with open(screenshot_path, 'rb') as f:
                    req.post(
                        f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto',
                        data={'chat_id': TELEGRAM_ADMIN},
                        files={'photo': f},
                        timeout=30
                    )
        except Exception as e:
            logger.error(f'Telegram alert error: {e}')

    # =============================================
    # ЛОГУВАННЯ В БД
    # =============================================

    async def _log_action(self, action: str, status: str, details: dict = None,
                          screenshot: str = None, duration_ms: int = None):
        """Записує дію в browser_action_log."""
        try:
            import json as _json
            conn = get_connection()
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO browser_action_log (site, action, status, details, screenshot, duration_ms)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (self.site, action, status,
                  _json.dumps(details or {}, ensure_ascii=False),
                  screenshot, duration_ms))
            conn.commit(); cur.close(); conn.close()
        except:
            pass

````

### `agents/scraper/rozetka_card_agent.py` — 167 рядків

````python
import os, sys, json, re
from loguru import logger
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
load_dotenv('/home/tek/agent-system/.env')

from shared.utils.db import get_connection
from shared.utils.ollama_worker import request_llm

# Словник перекладу параметрів рос→укр
PARAM_TRANSLATE = {
    "Тип": "Тип", "Вид": "Вид", "Категория": "Категорія",
    "Материал ручки": "Матеріал ручки", "Количество в наборе": "Кількість у наборі",
    "Реверсивная": "Реверсивна", "Отвертка": "Викрутка",
    "Универсальная": "Універсальна", "Многокомпонентный": "Багатокомпонентний",
    "Со сменными насадками": "Зі змінними насадками",
    "Односторонняя": "Одностороння", "Крестообразный": "Хрестоподібний",
    "Внешний": "Зовнішній", "Внутренний": "Внутрішній",
    "Длина": "Довжина", "Ширина": "Ширина", "Высота": "Висота",
    "Вес": "Вага", "Размер": "Розмір", "Цвет": "Колір",
    "Материал": "Матеріал", "Страна производитель": "Країна-виробник",
    "Тип привода": "Тип приводу", "Тип шлица": "Тип шліцу",
    "Исполнение биты": "Виконання біти", "Тип биты": "Тип біти",
}

def translate_params(params: dict) -> dict:
    """Перекладає параметри з російської на українську"""
    result = {}
    for key, val in params.items():
        if key == "_values":
            continue
        uk_key = PARAM_TRANSLATE.get(key, key)
        uk_val = PARAM_TRANSLATE.get(str(val), str(val))
        result[uk_key] = uk_val
    return result

def fix_name_ua(name: str, sku: str, vendor: str = "TOPTUL") -> str:
    """Виправляє назву за вимогами Розетки"""
    if not name:
        return f"Інструмент {vendor} {sku}"
    # Видалити заборонені символи
    name = re.sub(r'[,.](?!\d)', '', name)
    # Прибрати зайві пробіли
    name = re.sub(r'\s+', ' ', name).strip()
    # Перша літера велика
    name = name[0].upper() + name[1:] if name else name
    # Макс 255 символів
    return name[:255]

def generate_description_ua(sku: str, name: str, params: dict, raw_desc: str = "") -> str:
    """Генерує опис українською через Ollama"""
    model = "aya-expanse:8b"

    # Параметри для контексту
    params_text = "\n".join([f"- {k}: {v}" for k, v in params.items() if k != "_values"])

    # Очищаємо сирий опис від HTML і реклами
    clean_desc = re.sub(r'<[^>]+>', ' ', raw_desc or "")
    clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()[:1000]

    prompt = f"""Ти — копірайтер. Пиши ТІЛЬКИ українською мовою без жодних іноземних слів.

ПРИКЛАД ПРАВИЛЬНОГО ОПИСУ:
Ключ комбінований TOPTUL AAEB1010 — професійний інструмент для затягування та відкручування кріплення. Виготовлений зі сталі з хром-ванадієвим покриттям, забезпечує надійне зчеплення з гайками розміром 10 мм.

ПРИКЛАД НЕПРАВИЛЬНОГО (заборонено): "высококачественный инструмент", "professional tool", "незамінний помічник"

Напиши опис для цього товару:
Назва: {name}
Артикул: {sku}
Характеристики: {params_text}

ВИМОГИ:
- Максимум 250 символів
- ТІЛЬКИ українські слова (жодних російських, польських, англійських слів)
- Тільки факти про товар
- БЕЗ реклами, магазину, доставки, ціни
- 1-2 речення

Опис:"""

    try:
        result = request_llm(model, prompt, timeout=90)
        result = re.sub(r'<[^>]+>', '', result).strip()
        # Видалити лапки якщо LLM обгорнув відповідь
        result = result.strip('"\'')
        return result[:2000] if result else f"Професійний інструмент {vendor} {sku} (Тайвань)."
    except Exception as e:
        logger.error(f"[CARD AGENT] LLM error for {sku}: {e}")
        return f"Інструмент {name}. Виробник: TOPTUL (Тайвань). Артикул: {sku}."

def process_card(sku: str) -> dict:
    """Обробляє одну картку товару і повертає готовий offer"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT sku, name_uk, price_supplier, pictures, params,
               vendor, availability, description_raw, category_epicentr
        FROM my_products WHERE sku = %s
    """, (sku,))
    row = cur.fetchone()
    cur.close(); conn.close()

    if not row:
        logger.error(f"[CARD AGENT] SKU not found: {sku}")
        return None

    p = dict(row)
    vendor = p.get("vendor") or "TOPTUL"
    
    # Параметри
    raw_params = p.get("params") or {}
    if isinstance(raw_params, str):
        raw_params = json.loads(raw_params)
    
    # Перекладаємо параметри
    params_ua = translate_params(raw_params)
    
    # Базові параметри якщо порожньо
    if not params_ua:
        params_ua = {"Бренд": vendor, "Країна-виробник": "Тайвань"}

    # Виправляємо назву
    name_ua = fix_name_ua(p.get("name_uk", ""), sku, vendor)

    # Генеруємо опис через Ollama
    logger.info(f"[CARD AGENT] Generating description for {sku}...")
    desc_ua = generate_description_ua(
        sku, name_ua, params_ua, p.get("description_raw", "")
    )
    
    # Фото
    pictures = p.get("pictures") or []
    if isinstance(pictures, str):
        pictures = json.loads(pictures)
    pictures = [url for url in pictures if url and url.startswith("http")][:10]

    # Ціна
    price = float(p.get("price_supplier") or 0)
    available = p.get("availability", "true") == "true"
    stock = 10 if available and price > 0 else 0

    result = {
        "sku": sku,
        "name_ua": name_ua,
        "description_ua": desc_ua,
        "params": params_ua,
        "pictures": pictures,
        "price": price,
        "vendor": vendor,
        "stock": stock,
        "available": available and price > 0,
    }
    
    logger.success(f"[CARD AGENT] Done: {sku} | name: {name_ua[:50]} | desc: {desc_ua[:60]}")
    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sku", type=str, required=True)
    args = parser.parse_args()
    
    result = process_card(args.sku)
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))

````

### `agents/scraper/run_night_processing.py` — 76 рядків

````python
import os, sys, json, time
os.environ["CARD_MODEL"] = "aya-expanse:8b"
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')

from shared.utils.db import get_connection
from agents.scraper.rozetka_card_agent import process_card

def run_all():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT sku FROM my_products 
        WHERE price_supplier > 0 
        AND pictures IS NOT NULL
        AND status != 'xml_ready'
        ORDER BY sku
    """)
    skus = [r["sku"] for r in cur.fetchall()]
    cur.close(); conn.close()

    logger.info(f"[NIGHT] Total SKUs to process: {len(skus)}")
    
    processed = 0
    failed = 0
    results = []

    for i, sku in enumerate(skus):
        try:
            result = process_card(sku)
            if result:
                # Зберігаємо результат в БД
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("""
                    UPDATE my_products SET
                        name_uk = %s,
                        description_epicentr = %s,
                        params = %s,
                        status = 'xml_ready'
                    WHERE sku = %s
                """, (
                    result["name_ua"],
                    result["description_ua"],
                    json.dumps(result["params"]),
                    sku
                ))
                conn.commit()
                cur.close(); conn.close()
                processed += 1
                results.append(result)
            else:
                failed += 1
        except Exception as e:
            logger.error(f"[NIGHT] Error {sku}: {e}")
            failed += 1

        if (i+1) % 50 == 0:
            logger.info(f"[NIGHT] Progress: {i+1}/{len(skus)} | OK: {processed} | FAIL: {failed}")

        # Пауза між запитами щоб не перевантажувати Ollama
        time.sleep(1)

    logger.success(f"[NIGHT] Done! Processed: {processed}, Failed: {failed}")
    
    # Генеруємо фінальний XML
    from agents.scraper.xml_generator import generate_xml
    output_file = f"/home/tek/agent-system/data/rozetka_final_{int(time.time())}.xml"
    generate_xml(limit=99999, use_llm=False, output_file=output_file)
    logger.success(f"[NIGHT] XML generated: {output_file}")

if __name__ == "__main__":
    run_all()

````

### `agents/scraper/scraper_agent.py` — 309 рядків

````python
import os
import sys
import json
import time
import random
import asyncio
from loguru import logger
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from shared.utils.db import log_event, update_agent_status, get_connection
from shared.utils.redis_queue import pop_task, push_task

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

AGENT_NAME = "scraper"

# ── Fingerprint / anti-bot helpers ──────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]

async def human_delay(min_ms: int = 800, max_ms: int = 2800):
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))

async def human_scroll(page, steps: int = 4):
    for _ in range(steps):
        await page.mouse.wheel(0, random.randint(300, 700))
        await human_delay(300, 900)

async def build_stealth_context(playwright):
    ua = random.choice(USER_AGENTS)
    vp = random.choice(VIEWPORTS)
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-infobars",
        ]
    )
    context = await browser.new_context(
        user_agent=ua,
        viewport=vp,
        locale="uk-UA",
        timezone_id="Europe/Kiev",
        extra_http_headers={
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        }
    )
    # Маскуємо webdriver через JS
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        window.chrome = { runtime: {} };
    """)
    return browser, context

# ── Rozetka парсер ───────────────────────────────────────

async def parse_rozetka(category_url: str, max_items: int = 10) -> list:
    from playwright.async_api import async_playwright
    results = []
    logger.info(f"[SCRAPER] Rozetka: {category_url}")

    async with async_playwright() as p:
        browser, context = await build_stealth_context(p)
        page = await context.new_page()
        try:
            await page.goto(category_url, wait_until="domcontentloaded", timeout=30000)
            await human_delay(1500, 3000)
            await human_scroll(page, steps=3)
            await human_delay(800, 1500)

            items = await page.query_selector_all("li.catalog-grid__cell")
            logger.info(f"[SCRAPER] Found {len(items)} items on page")

            for item in items[:max_items]:
                try:
                    title_el = await item.query_selector("span.goods-tile__title")
                    price_el = await item.query_selector("span.goods-tile__price-value")
                    link_el  = await item.query_selector("a.goods-tile__heading")

                    title = await title_el.inner_text() if title_el else "N/A"
                    price_raw = await price_el.inner_text() if price_el else "0"
                    href  = await link_el.get_attribute("href") if link_el else ""

                    price = float(price_raw.replace("\u00a0", "").replace(",", ".").replace("грн", "").strip() or 0)

                    results.append({
                        "marketplace": "rozetka",
                        "title": title.strip(),
                        "price": price,
                        "url": href,
                    })
                except Exception as e:
                    logger.warning(f"Item parse error: {e}")
                    continue

        except Exception as e:
            logger.error(f"[SCRAPER] Page error: {e}")
        finally:
            await browser.close()

    return results

# ── Prom.ua парсер ───────────────────────────────────────

async def parse_prom(search_query: str, max_items: int = 10) -> list:
    from playwright.async_api import async_playwright
    url = f"https://prom.ua/search?search_term={search_query.replace(' ', '+')}"
    results = []
    logger.info(f"[SCRAPER] Prom: {url}")

    async with async_playwright() as p:
        browser, context = await build_stealth_context(p)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await human_delay(2000, 3500)
            await human_scroll(page, steps=3)

            items = await page.query_selector_all("div[data-qaid='product_gallery_item']")
            logger.info(f"[SCRAPER] Found {len(items)} items on page")

            for item in items[:max_items]:
                try:
                    title_el = await item.query_selector("span[data-qaid='product_name']")
                    price_el = await item.query_selector("span[data-qaid='product_price']")
                    link_el  = await item.query_selector("a[data-qaid='product_link']")

                    title = await title_el.inner_text() if title_el else "N/A"
                    price_raw = await price_el.inner_text() if price_el else "0"
                    href  = await link_el.get_attribute("href") if link_el else ""

                    price = float(price_raw.replace("\u00a0", "").replace(",", ".").replace("грн", "").strip() or 0)

                    results.append({
                        "marketplace": "prom",
                        "title": title.strip(),
                        "price": price,
                        "url": href,
                    })
                except Exception as e:
                    logger.warning(f"Item parse error: {e}")
                    continue

        except Exception as e:
            logger.error(f"[SCRAPER] Page error: {e}")
        finally:
            await browser.close()

    return results

# ── Prom.ua REST API ─────────────────────────────────────

async def prom_api_get_products(max_items: int = None) -> list:
    import aiohttp
    token = os.getenv("PROM_API_TOKEN")
    if not token:
        logger.error("[SCRAPER] PROM_API_TOKEN not set")
        return []

    api_url = "https://my.prom.ua/api/v1/products/list"
    headers = {"Authorization": f"Bearer {token}"}
    all_products = []
    page_from_id = None

    async with aiohttp.ClientSession() as session:
        while True:
            params = {"limit": 100}
            if page_from_id is not None:
                params["page_from_id"] = page_from_id

            async with session.get(api_url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"[SCRAPER] Prom API HTTP {resp.status}: {text[:200]}")
                    break
                data = await resp.json()

            page = data.get("products", [])
            if not page:
                break

            prev_count = len(all_products)
            for p in page:
                all_products.append({
                    "marketplace": "prom",
                    "title": p.get("name", "N/A"),
                    "price": float(p.get("price") or 0),
                    "url": p.get("url", ""),
                })

            new_count = len(all_products)
            if (new_count // 500) > (prev_count // 500):
                logger.info(f"[SCRAPER] Prom API: {new_count} products fetched so far...")

            if max_items and new_count >= max_items:
                all_products = all_products[:max_items]
                break

            if len(page) < 100:
                break

            page_from_id = page[-1]["id"]

    logger.info(f"[SCRAPER] Prom API: done, total {len(all_products)} products")
    return all_products

# ── Збереження в БД ──────────────────────────────────────

def save_products(products: list):
    if not products:
        return
    conn = get_connection()
    cur = conn.cursor()
    saved = 0
    for p in products:
        try:
            import hashlib
            ext_id = hashlib.md5(f"{p.get('marketplace','')}:{p.get('url','')}{p.get('title','')}".encode()).hexdigest()[:16]
            cur.execute("""
                INSERT INTO scraped_products (external_id, marketplace, title, price, url)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (external_id, marketplace) DO UPDATE
                SET price = EXCLUDED.price, title = EXCLUDED.title, scraped_at = NOW()
            """, (ext_id, p["marketplace"], p["title"], p["price"], p["url"]))
            saved += 1
        except Exception as e:
            logger.warning(f"Save error: {e}")
    conn.commit()
    cur.close()
    conn.close()
    logger.success(f"[SCRAPER] Saved {saved} products to DB")

# ── Головний обробник задач ──────────────────────────────

async def handle_task(task: dict):
    task_type = task.get("type", "")
    description = task.get("description", "")
    logger.info(f"[SCRAPER] Task: {task_type} — {description}")
    update_agent_status(AGENT_NAME, "busy")
    log_event(AGENT_NAME, "INFO", f"Started: {task_type}", task)

    products = []

    if "rozetka" in description.lower():
        url = "https://rozetka.com.ua/ua/notebooks/c80004/"
        if "електронік" in description.lower():
            url = "https://rozetka.com.ua/ua/electronics/c4627901/"
        products = await parse_rozetka(url, max_items=10)

    elif task_type == "prom_api":
        products = await prom_api_get_products()

    elif "prom" in description.lower():
        query = description.replace("prom", "").strip()
        products = await parse_prom(query, max_items=10)

    else:
        products = await parse_rozetka(
            "https://rozetka.com.ua/ua/electronics/c4627901/", max_items=10
        )

    save_products(products)
    log_event(AGENT_NAME, "INFO", f"Completed: {len(products)} products", {"count": len(products)})
    update_agent_status(AGENT_NAME, "idle")
    logger.success(f"[SCRAPER] Done: {len(products)} products")
    return products

def listen_loop():
    logger.info("[SCRAPER] Listening queue:scraper ...")
    update_agent_status(AGENT_NAME, "idle")
    while True:
        task = pop_task("queue:scraper", timeout=5)
        if task:
            asyncio.run(handle_task(task))

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Тест парсингу Rozetka")
    parser.add_argument("--listen", action="store_true", help="Слухати чергу")
    args = parser.parse_args()

    if args.test:
        products = asyncio.run(parse_rozetka(
            "https://rozetka.com.ua/ua/electronics/c4627901/", max_items=5
        ))
        print(json.dumps(products, ensure_ascii=False, indent=2))
    elif args.listen:
        listen_loop()
    else:
        parser.print_help()

````

### `agents/scraper/xml_generator.py` — 262 рядків

````python
import os, sys, json, re, time
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

from shared.utils.db import get_connection
from shared.utils.ollama_worker import request_llm

SHOP_NAME = "HYPER_STORE"
SHOP_URL = "https://prom.ua/ua/c3882792-hyper-store.html"
STOCK_DEFAULT = 10

# Маппінг категорій постачальника → rz_id Розетки
CATEGORY_MAP = {
    "Ручний інструмент та набори": ("1", "Ручний інструмент", "25636737"),
    "Набори інструментів": ("2", "Набори інструментів", "298224"),
    "Ключі": ("3", "Ключі та знімачі", "2798782"),
    "Викрутки": ("4", "Викрутки", "73501273"),
    "Головки торцеві": ("5", "Головки торцеві", "71859137"),
    "Пневмоінструмент": ("6", "Пневмоінструмент", "71512022"),
    "Затискний інструмент": ("7", "Затискний інструмент", "73354825"),
    "Вимірювальний інструмент": ("8", "Вимірювальний інструмент", "73557186"),
    "Підйомне обладнання": ("9", "Підйомне обладнання", "73501745"),
    "Шиномонтажне обладнання": ("10", "Шиномонтажне обладнання", "73082368"),
    "": ("11", "Ручний інструмент та набори", "25636737"),
}

def clean_html(text: str) -> str:
    """Видаляє HTML теги, фото, рекламу"""
    if not text:
        return ""
    # Видалити img теги
    text = re.sub(r'<img[^>]+>', '', text)
    # Видалити теги з data-end/data-start атрибутами
    text = re.sub(r'<[^>]+data-(?:end|start)[^>]+>', '', text)
    # Залишити тільки дозволені HTML теги
    allowed = re.sub(r'<(?!/?(?:p|ul|li|strong|b|br|h2|h3)\b)[^>]+>', '', text)
    return allowed.strip()

def generate_description(sku: str, name: str, description_raw: str, model=None) -> str:
    """Генерує чистий опис українською через LLM"""
    if not model:
        model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

    # Спочатку очищаємо від сміття
    clean = clean_html(description_raw or "")
    # Прибираємо російський текст — беремо тільки речення без кирилічних слів на рос.
    clean = clean[:3000]  # обмежуємо контекст

    prompt = f"""Ти — копірайтер для інтернет-магазину інструментів. 
Твоє завдання — написати короткий технічний опис товару українською мовою.

Товар: {name}
Артикул: {sku}
Вихідні дані (можуть бути на різних мовах, з HTML):
{clean}

Правила:
1. Пиши ТІЛЬКИ українською мовою
2. Максимум 500 символів
3. Тільки технічні факти про конкретний товар
4. Без реклами: заборонені слова "акція", "знижка", "топ", "найкращий", "незамінний"
5. Без згадок магазину, доставки, гарантії
6. Без фото, посилань, цін
7. Структура: 1-2 речення про призначення + ключові характеристики

Напиши тільки текст опису, без заголовків і зайвих слів."""

    try:
        result = request_llm(model, prompt, timeout=60)
        # Очищуємо від можливих HTML тегів у відповіді LLM
        result = re.sub(r'<[^>]+>', '', result).strip()
        return result[:2000]
    except Exception as e:
        logger.error(f"[XML] LLM error for {sku}: {e}")
        return f"Професійний інструмент TOPTUL {sku}. Виробник: TOPTUL (Тайвань)."

def fix_name(name_uk: str, sku: str) -> str:
    """Виправляє назву за вимогами Розетки"""
    if not name_uk:
        return f"Інструмент TOPTUL {sku}"

    # Видалити заборонені символи
    name = re.sub(r'[,.]', '', name_uk)
    # Прибрати зайві пробіли
    name = re.sub(r'\s+', ' ', name).strip()
    # Перша літера велика
    name = name[0].upper() + name[1:] if name else name
    # Максимум 255 символів
    return name[:255]

def get_category_info(category_epicentr: str) -> tuple:
    """Повертає (cat_id, cat_name, rz_id) для категорії"""
    for key, val in CATEGORY_MAP.items():
        if key and key.lower() in (category_epicentr or "").lower():
            return val
    return CATEGORY_MAP[""]  # default

def generate_xml(limit: int = 100, use_llm: bool = True, output_file: str = None):
    """Генерує XML файл для Розетки"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT sku, name_uk, description_raw, description_epicentr,
               category_epicentr, attributes, specs_json, status,
               price_supplier, pictures, params, vendor, availability
        FROM my_products
        WHERE status IN ('new', 'processed', 'ready')
        AND sku IS NOT NULL
        AND name_uk IS NOT NULL
        LIMIT %s
    """, (limit,))

    products = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    logger.info(f"[XML] Generating XML for {len(products)} products")

    # Збираємо унікальні категорії
    categories_used = {}
    for p in products:
        cat = p.get("category_epicentr") or ""
        cat_id, cat_name, rz_id = get_category_info(cat)
        categories_used[cat_id] = (cat_name, rz_id)

    # Генеруємо XML
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{datetime.now().strftime("%Y-%m-%d %H:%M")}">',
        '  <shop>',
        f'    <name>{SHOP_NAME}</name>',
        f'    <company>FOP Oliinyk Serhii</company>',
        f'    <url>{SHOP_URL}</url>',
        '    <currencies>',
        '      <currency id="UAH" rate="1"/>',
        '    </currencies>',
        '    <categories>',
    ]

    for cat_id, (cat_name, rz_id) in categories_used.items():
        lines.append(f'      <category id="{cat_id}" rz_id="{rz_id}">{cat_name}</category>')

    lines.append('    </categories>')
    lines.append('    <offers>')

    processed = 0
    skipped = 0

    for p in products:
        sku = p["sku"]
        name_uk = fix_name(p.get("name_uk", ""), sku)

        if not name_uk or len(name_uk) < 5:
            skipped += 1
            continue

        cat = p.get("category_epicentr") or ""
        cat_id, cat_name, rz_id = get_category_info(cat)

        # Генеруємо опис
        if use_llm and p.get("description_raw"):
            description = generate_description(sku, name_uk, p["description_raw"])
        elif p.get("description_epicentr"):
            description = re.sub(r'<[^>]+>', '', p["description_epicentr"])[:500]
        else:
            description = f"Професійний інструмент TOPTUL {sku}. Бренд TOPTUL — провідний виробник інструментів (Тайвань). Артикул: {sku}."

        # Параметри з поля params (імпортовано з Prom)
        params = []
        import json as _json2
        params_data = p.get("params") or {}
        if isinstance(params_data, str):
            params_data = _json2.loads(params_data)
        for key, val in params_data.items():
            if key == "_values":
                continue
            if val and str(val).strip():
                clean_key = str(key).strip()[:100]
                clean_val = str(val).strip()[:500]
                clean_val = clean_val.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                params.append(f'        <param name="{clean_key}">{clean_val}</param>')
        # Базові параметри якщо немає
        if not params:
            vendor = p.get("vendor") or "TOPTUL"
            params.append(f'        <param name="Бренд">{vendor}</param>')
            params.append('        <param name="Країна виробник">Тайвань</param>')

        # Фото з поля pictures (імпортовано з Prom)
        pictures = []
        pics_data = p.get("pictures") or []
        if isinstance(pics_data, str):
            import json as _json
            pics_data = _json.loads(pics_data)
        for url in pics_data[:10]:
            if url and url.startswith("http") and len(url) < 500:
                pictures.append(f'        <picture>{url}</picture>')
        if not pictures:
            pictures.append(f'        <!-- no pictures for {sku} -->')

        # Очищаємо description від спецсимволів XML
        desc_clean = description.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        offer = [
            f'      <offer id="{sku}" available="true">',
            f'        <price>{int(p.get("price_supplier") or 0)}</price>',
            f'        <currencyId>UAH</currencyId>',
            f'        <categoryId>{cat_id}</categoryId>',
        ]
        offer.extend(pictures)
        offer.extend([
            f'        <vendor>TOPTUL</vendor>',
            f'        <article>{sku}</article>',
            f'        <stock_quantity>{STOCK_DEFAULT}</stock_quantity>',
            f'        <name_ua>{name_uk}</name_ua>',
            f'        <description_ua><![CDATA[<p>{desc_clean}</p>]]></description_ua>',
        ])
        offer.extend(params)
        offer.append('      </offer>')
        lines.extend(offer)

        processed += 1
        if processed % 10 == 0:
            logger.info(f"[XML] Processed {processed}/{len(products)}")

    lines.extend([
        '    </offers>',
        '  </shop>',
        '</yml_catalog>',
    ])

    xml_content = '\n'.join(lines)

    if not output_file:
        output_file = f"data/rozetka_feed_{datetime.now().strftime('%Y%m%d_%H%M')}.xml"

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(xml_content)

    logger.success(f"[XML] Done: {processed} offers, {skipped} skipped → {output_file}")
    return output_file, processed

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50, help="Кількість товарів")
    parser.add_argument("--no-llm", action="store_true", help="Без LLM генерації описів")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    file, count = generate_xml(
        limit=args.limit,
        use_llm=not args.no_llm,
        output_file=args.output
    )
    print(f"\n✅ XML готовий: {file}")
    print(f"   Товарів: {count}")

````

### `tools/competitor_scraper.py` — 472 рядків

````python
#!/usr/bin/env python3
"""
competitor_scraper.py — збирає товари продавця на Rozetka.

Використання:
    python3 tools/competitor_scraper.py
    python3 tools/competitor_scraper.py --seller ttul --pages 5
    python3 tools/competitor_scraper.py --no-save   # тільки вивід у консоль
"""

import asyncio
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import argparse
from loguru import logger
from dotenv import load_dotenv
from shared.utils.db import get_connection

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

# ── Константи ─────────────────────────────────────────────

DEFAULT_SELLER = "ttul"
SELLER_URL = "https://rozetka.com.ua/ua/seller/{seller}/goods/"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]

# ── Stealth-браузер ───────────────────────────────────────

async def build_stealth_context(playwright, headless: bool = True):
    from playwright_stealth import Stealth

    browser = await playwright.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-infobars",
        ],
    )
    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport=random.choice(VIEWPORTS),
        locale="uk-UA",
        timezone_id="Europe/Kiev",
        extra_http_headers={
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        },
    )
    # Зберігаємо stealth instance для застосування до кожної нової page
    context._stealth = Stealth()
    return browser, context


async def human_delay(min_ms: int = 700, max_ms: int = 2000):
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


async def human_scroll(page, steps: int = 4):
    for _ in range(steps):
        await page.mouse.wheel(0, random.randint(300, 700))
        await human_delay(250, 700)


# ── DDL ───────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS competitor_products (
    id              SERIAL PRIMARY KEY,
    seller          TEXT        NOT NULL,
    title           TEXT        NOT NULL,
    price           NUMERIC(12, 2),
    category        TEXT,
    url             TEXT        UNIQUE,
    reviews_count   INTEGER     DEFAULT 0,
    scraped_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_competitor_seller
    ON competitor_products (seller);
CREATE INDEX IF NOT EXISTS idx_competitor_scraped_at
    ON competitor_products (scraped_at);
"""

def ensure_table():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    cur.close()
    conn.close()
    logger.debug("Table competitor_products: OK")


# ── Парсинг однієї сторінки товарів ──────────────────────

async def parse_page(page, seller: str, debug_dump: bool = False) -> list[dict]:
    """Витягує всі товари з поточної сторінки пагінації."""
    products = []

    # Debug: зберігаємо HTML після завантаження
    if debug_dump:
        try:
            html = await page.content()
            Path("/tmp/rozetka_debug.html").write_text(html, encoding="utf-8")
            logger.debug("HTML збережено в /tmp/rozetka_debug.html")
        except Exception as e:
            logger.warning(f"Не вдалось зберегти debug HTML: {e}")

    # Чекаємо поки картки завантажаться (Angular-компонент rz-product-tile)
    try:
        await page.wait_for_selector("rz-product-tile", timeout=30000)
    except Exception:
        logger.warning("Картки товарів не знайдені на сторінці")
        return products

    await human_scroll(page, steps=5)
    await human_delay(500, 1000)

    items = await page.query_selector_all("rz-product-tile")
    logger.debug(f"  Карток на сторінці: {len(items)}")

    for item in items:
        try:
            # Назва + URL (один елемент a.tile-title)
            title_el = await item.query_selector("a.tile-title")
            title = (await title_el.inner_text()).strip() if title_el else None
            if not title:
                continue
            url = await title_el.get_attribute("href") if title_el else None

            # Ціна
            price_el = await item.query_selector("[class*='price']")
            price_raw = (await price_el.inner_text()).strip() if price_el else "0"
            price = float(
                price_raw
                .replace("\u00a0", "")
                .replace("\xa0", "")
                .replace(",", ".")
                .replace("грн", "")
                .replace("₴", "")
                .strip() or 0
            )

            # Категорія з URL: https://rozetka.com.ua/ua/<category>/<id>/p<id>/
            category = None
            if url:
                parts = [p for p in url.split("/") if p and p not in ("ua", "https:", "rozetka.com.ua")]
                if parts:
                    category = parts[0]

            # Кількість відгуків
            reviews_el = await item.query_selector(".rating-block-rating")
            reviews_count = 0
            if reviews_el:
                raw = (await reviews_el.inner_text()).strip()
                digits = "".join(filter(str.isdigit, raw))
                reviews_count = int(digits) if digits else 0

            products.append({
                "seller": seller,
                "title": title,
                "price": price,
                "category": category,
                "url": url,
                "reviews_count": reviews_count,
            })

        except Exception as e:
            logger.warning(f"  Помилка парсингу картки: {e}")
            continue

    return products


# ── Пагінація ─────────────────────────────────────────────

async def get_total_pages(page) -> int:
    """Визначає кількість сторінок пагінації (rz-paginator)."""
    try:
        # Збираємо всі a.page всередині rz-paginator і беремо останній href
        links = await page.query_selector_all("rz-paginator a.page")
        max_page = 1
        for link in links:
            href = await link.get_attribute("href") or ""
            if "page=" in href:
                num = int(href.split("page=")[-1].split("&")[0])
                if num > max_page:
                    max_page = num
        return max_page
    except Exception:
        return 1


# ── Головний скрапер ──────────────────────────────────────

async def scrape_seller(seller: str, max_pages: int | None = None, headless: bool = True) -> list[dict]:
    from playwright.async_api import async_playwright

    base_url = SELLER_URL.format(seller=seller)
    all_products: list[dict] = []

    # Seller ID потрібен для API запитів (отримаємо з першої сторінки)
    seller_api_id: str | None = None

    async with async_playwright() as p:
        browser, context = await build_stealth_context(p, headless=headless)
        page = await context.new_page()
        # Застосовуємо stealth до сторінки
        if hasattr(context, '_stealth'):
            await context._stealth.apply_stealth_async(page)

        # ── Перехоплення API відповідей catalog-api ──────
        api_data: dict[int, list[dict]] = {}

        async def on_response(resp):
            if 'catalog-api.rozetka' in resp.url and resp.status == 200:
                try:
                    body = await resp.body()
                    data = json.loads(body)
                    goods = (data.get('data') or {}).get('goods', [])
                    # Визначаємо номер сторінки з URL
                    pnum = 1
                    if 'page:' in resp.url:
                        pnum = int(resp.url.split('page:')[1].split('&')[0])
                    if goods:
                        api_data[pnum] = goods
                        logger.debug(f"  API page {pnum}: {len(goods)} товарів")
                except Exception as e:
                    logger.debug(f"  API parse error: {e}")

        page.on('response', on_response)

        try:
            # ── Перша сторінка (SSR — парсимо DOM) ──────
            logger.info(f"Відкриваю {base_url}")
            await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
            await human_delay(1500, 2500)

            total_pages = await get_total_pages(page)
            if max_pages:
                total_pages = min(total_pages, max_pages)
            logger.info(f"Сторінок для обходу: {total_pages}")

            # Парсимо page 1 з DOM (SSR вже рендерений)
            products = await parse_page(page, seller, debug_dump=True)
            all_products.extend(products)
            logger.info(f"Стор. 1/{total_pages}: {len(products)} товарів")

            # ── Решта сторінок через API перехоплення ────
            for page_num in range(2, total_pages + 1):
                logger.info(f"Стор. {page_num}/{total_pages}")
                try:
                    api_data.pop(page_num, None)  # скидаємо старі дані

                    # Клікаємо пагінатор щоб Angular зробив API запит
                    link = await page.query_selector(
                        f"rz-paginator a.page[href*='page={page_num}']"
                    )
                    if link:
                        await link.click()
                    else:
                        await page.evaluate("""
                            () => {
                                const btn = document.querySelector(
                                    "[data-testid='pagination_to_next_page']:not(.disabled)"
                                );
                                if (btn) btn.click();
                            }
                        """)

                    # Чекаємо поки API відповідь буде перехоплена
                    for _ in range(40):  # до 8 секунд
                        if page_num in api_data:
                            break
                        await asyncio.sleep(0.2)

                    if page_num in api_data:
                        # Конвертуємо API дані у наш формат
                        products = _parse_api_goods(api_data[page_num], seller)
                    else:
                        # Fallback: парсимо DOM (якщо API не відповів)
                        logger.debug(f"  API не відповів, fallback DOM парсинг")
                        await page.wait_for_selector("rz-product-tile", timeout=20000)
                        await human_delay(1500, 2500)
                        products = await parse_page(page, seller)

                    all_products.extend(products)
                    logger.info(f"  +{len(products)} товарів  (всього: {len(all_products)})")

                except Exception as e:
                    logger.error(f"  Помилка на сторінці {page_num}: {e}")
                    continue

        finally:
            await browser.close()

    return all_products


def _parse_api_goods(goods: list[dict], seller: str) -> list[dict]:
    """Конвертує сирі дані catalog API у наш формат."""
    products = []
    for g in goods:
        try:
            title = g.get('title') or g.get('name') or ''
            if not title:
                continue

            # Ціна
            price_raw = g.get('price') or g.get('sell_price') or 0
            try:
                price = float(str(price_raw).replace('\xa0', '').replace(' ', '').replace(',', '.') or 0)
            except Exception:
                price = 0.0

            # URL
            url = g.get('href') or g.get('url') or ''

            # Категорія з URL
            category = None
            if url:
                parts = [p for p in url.split('/') if p and p not in ('ua', 'https:', 'rozetka.com.ua')]
                if parts:
                    category = parts[0]

            # Відгуки
            reviews_count = 0
            comments = g.get('comments_amount') or g.get('reviews_count') or 0
            if comments:
                try:
                    reviews_count = int(comments)
                except Exception:
                    pass

            products.append({
                'seller': seller,
                'title': title,
                'price': price,
                'category': category,
                'url': url,
                'reviews_count': reviews_count,
            })
        except Exception as e:
            logger.debug(f"  _parse_api_goods error: {e}")
    return products


# ── Збереження ────────────────────────────────────────────

def save_products(products: list[dict]) -> tuple[int, int]:
    """Повертає (saved, skipped)."""
    if not products:
        return 0, 0

    conn = get_connection()
    cur = conn.cursor()
    saved = skipped = 0

    for p in products:
        try:
            cur.execute(
                """
                INSERT INTO competitor_products
                    (seller, title, price, category, url, reviews_count, scraped_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE SET
                    price        = EXCLUDED.price,
                    reviews_count = EXCLUDED.reviews_count,
                    scraped_at   = EXCLUDED.scraped_at
                """,
                (
                    p["seller"], p["title"], p["price"],
                    p["category"], p["url"], p["reviews_count"],
                    datetime.utcnow(),
                ),
            )
            saved += 1
        except Exception as e:
            logger.warning(f"Помилка збереження: {e} | {p.get('url')}")
            skipped += 1

    conn.commit()
    cur.close()
    conn.close()
    return saved, skipped


# ── CLI ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Парсинг товарів продавця на Rozetka"
    )
    parser.add_argument(
        "--seller", default=DEFAULT_SELLER,
        help=f"Slug продавця (за замовчуванням: {DEFAULT_SELLER})",
    )
    parser.add_argument(
        "--pages", type=int, default=None,
        help="Максимальна кількість сторінок (за замовчуванням: всі)",
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="Не зберігати в БД, тільки вивести в консоль",
    )
    parser.add_argument(
        "--headful", action="store_true",
        help="Запустити браузер у видимому режимі (для ручного проходження Cloudflare)",
    )
    args = parser.parse_args()

    logger.info(f"Старт: seller={args.seller}, max_pages={args.pages or 'всі'}, headless={not args.headful}")

    products = asyncio.run(scrape_seller(args.seller, max_pages=args.pages, headless=not args.headful))

    if not products:
        logger.warning("Товарів не знайдено — перевір selector або доступність сайту")
        sys.exit(1)

    if args.no_save:
        for p in products:
            print(f"{p['price']:>10.2f} грн | {p['reviews_count']:>4} відг. | {p['title'][:60]}")
    else:
        ensure_table()
        saved, skipped = save_products(products)
        logger.success(
            f"Готово: знайдено {len(products)}, збережено {saved}, пропущено {skipped}"
        )

    # ── Звіт ──────────────────────────────────────────────
    if products:
        prices = [p["price"] for p in products if p["price"]]
        categories = {}
        for p in products:
            categories[p["category"] or "unknown"] = categories.get(p["category"] or "unknown", 0) + 1

        print("\n" + "=" * 55)
        print(f"  Продавець       : {args.seller}")
        print(f"  Всього товарів  : {len(products)}")
        if prices:
            print(f"  Мін. ціна       : {min(prices):.2f} грн")
            print(f"  Макс. ціна      : {max(prices):.2f} грн")
            print(f"  Середня ціна    : {sum(prices)/len(prices):.2f} грн")
        print(f"  Категорії ({len(categories)}):")
        for cat, cnt in sorted(categories.items(), key=lambda x: -x[1])[:10]:
            print(f"    {cnt:>4}x  {cat}")
        print("=" * 55)


if __name__ == "__main__":
    main()

````
