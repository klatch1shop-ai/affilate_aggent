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
    'головка торцева':          'Воротки, тріскачки та головки',
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
