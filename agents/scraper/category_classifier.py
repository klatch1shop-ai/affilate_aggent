"""
AI Класифікатор категорій товарів для Єпіцентру і Розетки
Використовує: БД категорій + словник + llama3.2:3b на GPU
Швидкість: 0.1-0.3с на товар після прогріву моделі
"""
import re, time, sys, json
from loguru import logger
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection
import requests

OLLAMA = 'http://100.126.131.55:11434'
MODEL = 'llama3.2:3b'

# Словник: підрядки назви → категорія Єпіцентру
EPICENTR_KEYWORDS = {
    # Ключі
    'ключ рожков':      'Ключі та набори ключів',
    'ключ накидн':      'Ключі та набори ключів',
    'ключ комбін':      'Ключі та набори ключів',
    'ключ розвідн':     'Ключі та набори ключів',
    'ключ трубн':       'Ключі та набори ключів',
    'ключ шестигран':   'Ключі та набори ключів',
    'ключ балон':       'Балонні та свічні ключі',
    'ключ динамометр':  'Динамометричні ключі',
    'динамометричний ключ': 'Динамометричні ключі',
    'ключ торцев':      'Воротки, тріскачки та головки',
    'набір ключів':     'Ключі та набори ключів',
    # Головки та воротки
    'головка торцев':   'Воротки, тріскачки та головки',
    'набір головок':    'Воротки, тріскачки та головки',
    'вороток':          'Воротки, тріскачки та головки',
    'тріскачка':        'Воротки, тріскачки та головки',
    # Викрутки
    'викрутка':         'Викрутки',
    'набір викруток':   'Викрутки',
    # Плоскогубці
    'плоскогубці':      'Шарнірно-губцевий інструмент',
    'пасатижі':         'Шарнірно-губцевий інструмент',
    'кліщі':            'Шарнірно-губцевий інструмент',
    'бокорізи':         'Шарнірно-губцевий інструмент',
    'кусачки':          'Шарнірно-губцевий інструмент',
    # Молотки
    'молоток':          'Молотки',
    'кувалда':          'Молотки',
    'киянка':           'Молотки',
    # Знімачі
    'знімач підшипник': 'Знімачі підшипників',
    'знімач':           'Механічні знімачі',
    # Домкрати
    'домкрат':          'Домкрати',
    # Набори
    'набір інструмент': 'Набори інструментів',
    # Зубила
    'зубило':           'Зубила',
    'кернер':           'Зубила',
    'борідок':          'Зубила',
    # Напилки
    'напилок':          'Напилки',
    'надфіль':          'Напилки',
    # Лещата і струбцини
    'лещата':           'Лещата',
    'струбцина':        'Струбцини та затискачі',
    # Пневмо
    'пневмо':           'Пневмоінструмент та обладнання',
    'гайковерт пневм':  'Пневмогайковерти',
    'компресор':        'Компресори',
    # Вимірювальний
    'термометр':        'Детектори',
    'пірометр':         'Пірометри',
    'мультиметр':       'Мультиметри',
    'рулетка':          'Рулетки',
    'рівень':           'Рівні',
    'штангенциркуль':   'Штангенциркулі',
    'мікрометр':        'Детектори',
    'манометр':         'Детектори',
    # Електроінструмент
    'дриль':            'Електроінструменти',
    'шуруповерт':       'Шуруповерти',
    'перфоратор':       'Перфоратори',
    'болгарка':         'Болгарки',
    'лобзик':           'Електролобзики',
    # Підйомне
    'домкрат':          'Домкрати',
    'таль':             'Талі',
    'лебідка':          'Ручні лебідки',
    # Шиномонтаж і підйомне
    'шиномонтажний стенд': 'Обладнання для шиномонтажу',
    'шиномонтажн':      'Обладнання для шиномонтажу',
    'балансувальн':     'Обладнання для шиномонтажу',
    'підйомник автомобільний': 'Підйомники',
    'підйомник 2-х стійков': 'Підйомники',
    'підйомник 4-х стійков': 'Підйомники',
    'підйомник':        'Підйомники',
    'шиномонтажний стенд': 'Верстати для шиномонтажу',
    'шиномонтажний':    'Верстати для шиномонтажу',
    'балансувальний стенд': 'Балансувальні верстати',
    'балансувальн':     'Балансувальні верстати',
    'стенд заправки':   'Обладнання для заправлення автокондиціонерів',
    'стенд для руук':   'Стенди розвал-сходження',
    'стапель':          'Стапелі рихтувальні',
    'рихтувальний стапель': 'Стапелі рихтувальні',
    'верстат проточк':  'Верстати для проточування гальмівних дисків',
    'проточки гальмів': 'Верстати для проточування гальмівних дисків',
    'сканер launch':    'Автомобільні діагностичні сканери',
    'мультимарочний сканер': 'Автомобільні діагностичні сканери',
    'візок з інструмент': 'Ящики та органайзери для інструментів',
    'головка з насадкою': 'Воротки, тріскачки та головки',
    'свічна головка':   'Воротки, тріскачки та головки',
    'насадка hex':      'Воротки, тріскачки та головки',
    'програмування ключів': 'Автомобільні діагностичні сканери',
    'підйомне':         'Підіймальне обладнання для СТО',
    'кран підкатн':     'Крани підкатні гідравлічні',
    'стапель':          'Рихтувальне обладнання',
    'рихтування':       'Рихтувальне обладнання',
    # Кондиціонери СТО
    'кондиціонер':      'Обладнання для автокондиціонерів',
    'заправлення кондиціонер': 'Обладнання для заправлення автокондиціонерів',
    'обслуговування кондиціонер': 'Обладнання для автокондиціонерів',
    # Розвал-сходження
    'розвал':           'Стенди розвал-сходження',
    'руук':             'Стенди розвал-сходження',
    # Діагностика
    'діагностичн':      'Діагностичне обладнання для СТО',
    'сканер':           'Автомобільні діагностичні сканери',
    # Мастило
    'заміна мастила':   'Обладнання для заміни мастила',
    'нагнітач мастила': 'Нагнітачі мастила',
    # Насадки і біти
    'насадка':          'Біти для шуруповерта',
    'біта':             'Біти для шуруповерта',
    'спліт':            'Біти для шуруповерта',
}

# Словник для Розетки
ROZETKA_KEYWORDS = {
    'ключ рожков':      'Ключі та знімачі',
    'ключ накидн':      'Ключі та знімачі',
    'ключ комбін':      'Ключі та знімачі',
    'ключ шестигран':   'Ключі шестигранні',
    'ключ динамометр':  'Динамометричні ключі',
    'динамометричний':  'Динамометричні ключі',
    'головка торцев':   'Головки торцеві',
    'набір головок':    'Головки торцеві',
    'вороток':          'Головки торцеві',
    'тріскачка':        'Головки торцеві',
    'викрутка':         'Викрутки',
    'плоскогубці':      'Затискний інструмент',
    'пасатижі':         'Затискний інструмент',
    'молоток':          'Молотки та кувалди',
    'кувалда':          'Молотки та кувалди',
    'знімач':           'Знімачі та виштовхувачі',
    'домкрат':          'Підйомне обладнання',
    'набір інструмент': 'Набори інструментів',
    'пневмо':           'Пневмоінструмент',
    'компресор':        'Пневмоінструмент',
    'вимірювальний':    'Вимірювальний інструмент',
    'мультиметр':       'Вимірювальний інструмент',
}

def find_candidates(product_name: str, marketplace: str = 'epicentr') -> list:
    name_lower = product_name.lower()
    keywords = EPICENTR_KEYWORDS if marketplace == 'epicentr' else ROZETKA_KEYWORDS
    
    conn = get_connection()
    cur = conn.cursor()
    candidates = []
    keyword_matches = []

    # Крок 1: словник (найдовший збіг має пріоритет)
    matched_keywords = sorted(
        [(kw, cat) for kw, cat in keywords.items() if kw in name_lower],
        key=lambda x: -len(x[0])
    )
    
    for kw, cat_name in matched_keywords[:3]:
        if marketplace == 'epicentr':
            cur.execute('''SELECT id, final_category as name FROM epicentr_categories
                WHERE final_category ILIKE %s ORDER BY LENGTH(final_category) LIMIT 3''',
                (f'%{cat_name}%',))
        else:
            cur.execute('''SELECT id, title_ua as name FROM rozetka_categories
                WHERE title_ua ILIKE %s LIMIT 3''', (f'%{cat_name}%',))
        
        for row in cur.fetchall():
            if row['name'] not in [c['name'] for c in candidates]:
                candidates.append({'id': row['id'], 'name': row['name'], 'source': 'keyword'})
                keyword_matches.append(row['name'])

    # Крок 2: якщо мало кандидатів — пошук по першому слову
    if len(candidates) < 3:
        first_word = name_lower.split()[0] if name_lower.split() else ''
        if len(first_word) > 3:
            if marketplace == 'epicentr':
                cur.execute('''SELECT id, final_category as name FROM epicentr_categories
                    WHERE final_category ILIKE %s LIMIT 5''', (f'%{first_word}%',))
            else:
                cur.execute('''SELECT id, title_ua as name FROM rozetka_categories
                    WHERE title_ua ILIKE %s LIMIT 5''', (f'%{first_word}%',))
            for row in cur.fetchall():
                if row['name'] not in [c['name'] for c in candidates]:
                    candidates.append({'id': row['id'], 'name': row['name'], 'source': 'search'})

    cur.close(); conn.close()
    return candidates[:8], len(keyword_matches) > 0

def classify(product_name: str, marketplace: str = 'epicentr') -> dict:
    candidates, has_keyword = find_candidates(product_name, marketplace)
    
    if not candidates:
        return {'category_id': None, 'category_name': None, 'confidence': 'none'}
    
    # Якщо є один чіткий keyword match — довіряємо
    keyword_cats = [c for c in candidates if c['source'] == 'keyword']
    if len(keyword_cats) == 1:
        return {
            'category_id': keyword_cats[0]['id'],
            'category_name': keyword_cats[0]['name'],
            'confidence': 'high'
        }
    
    # LLM вибір
    cats_list = '\n'.join([f'{i+1}. {c["name"]}' for i, c in enumerate(candidates)])
    prompt = f'Товар: {product_name}\nВибери найточнішу категорію. Відповідь ТІЛЬКИ номером.\n{cats_list}\nНомер:'
    
    try:
        resp = requests.post(f'{OLLAMA}/api/generate', json={
            'model': MODEL,
            'prompt': prompt,
            'stream': False,
            'options': {'num_predict': 5, 'temperature': 0}
        }, timeout=15)
        answer = resp.json()['response'].strip()
        num = re.search(r'\d+', answer)
        if num:
            idx = int(num.group()) - 1
            if 0 <= idx < len(candidates):
                return {
                    'category_id': candidates[idx]['id'],
                    'category_name': candidates[idx]['name'],
                    'confidence': 'medium'
                }
    except Exception as e:
        logger.error(f'Ollama error: {e}')
    
    return {
        'category_id': candidates[0]['id'],
        'category_name': candidates[0]['name'],
        'confidence': 'low'
    }

def classify_batch(marketplace: str = 'epicentr', limit: int = 100):
    """Масова класифікація товарів з my_products"""
    conn = get_connection()
    cur = conn.cursor()
    
    # Додаємо колонки якщо немає
    if marketplace == 'epicentr':
        cur.execute('ALTER TABLE my_products ADD COLUMN IF NOT EXISTS epicentr_category_id INTEGER')
        cur.execute('ALTER TABLE my_products ADD COLUMN IF NOT EXISTS epicentr_category_name VARCHAR(500)')
        cur.execute('ALTER TABLE my_products ADD COLUMN IF NOT EXISTS epicentr_confidence VARCHAR(20)')
    
    conn.commit()
    
    # Беремо товари без категорії
    cur.execute(f'''SELECT id, sku, name_uk 
        FROM my_products 
        WHERE epicentr_category_id IS NULL AND price_supplier > 0
        LIMIT %s''', (limit,))
    products = cur.fetchall()
    logger.info(f'Classifying {len(products)} products for {marketplace}')
    
    stats = {'high': 0, 'medium': 0, 'low': 0, 'none': 0}
    
    for p in products:
        name = p['name_uk'] or p['sku']
        result = classify(name, marketplace)
        
        cur.execute('''UPDATE my_products SET
            epicentr_category_id=%s,
            epicentr_category_name=%s,
            epicentr_confidence=%s
            WHERE id=%s''',
            (result['category_id'], result['category_name'],
             result['confidence'], p['id']))
        
        stats[result['confidence']] = stats.get(result['confidence'], 0) + 1
        logger.info(f"[{result['confidence']:6}] {name[:50]} → {result['category_name']}")
    
    conn.commit()
    cur.close(); conn.close()
    logger.success(f'Done: {stats}')
    return stats

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--marketplace', default='epicentr')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--sku', type=str, default=None)
    args = parser.parse_args()
    
    if args.sku:
        result = classify(args.sku, args.marketplace)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        classify_batch(args.marketplace, args.limit)
