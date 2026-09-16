```python
"""
Модуль розбору намірів (інтентів) з тексту для Telegram-бота.

Реалізує повністю детермінований розбір тексту без звернень до мережі,
LLM чи бази даних. Працює з українською та російською мовами.
"""

import re
from typing import Any

# Компіляція регулярних виразів для пошуку параметрів
REGEX_TTN = re.compile(r'\b\d{14}\b')  # ТТН: 14 цифр поспіль
REGEX_ORDER = re.compile(r'\b\d{9}\b')  # Замовлення: 9 цифр поспіль
REGEX_SKU = re.compile(r'\b([a-zA-Z]{2}\d{4,5})\b')  # Артикул: 2 літери + 4-5 цифр

# Мапінг маркетплейсів
MARKETPLACES = {
    'rozetka': ['розетка', 'rozetka'],
    'prom': ['пром', 'prom'],
    'epicentr': ['єпіцентр', 'епіцентр', 'epicentr']
}

# Мапінг періодів
PERIODS = {
    'today': ['сьогодні', 'сегодня'],
    'yesterday': ['вчора', 'вчера'],
    'week': ['тиждень', 'неделю', 'за тиждень', 'за неделю']
}

# Ключові слова для кожного наміру
INTENT_KEYWORDS = {
    'orders_new': [
        'замовлення', 'заказ', 'нові', 'новые', 'сьогодні', 'сегодня',
        'сьогоднішні', 'сегодняшні', 'щось замовили', 'что-то заказали'
    ],
    'order_status': [
        'статус замовлення', 'статус заказа', 'що із замовленням',
        'что с заказом', 'де замовлення', 'где заказ'
    ],
    'ttn_status': [
        'ттн', 'накладна', 'накладная', 'посилка', 'посылка',
        'відстеження', 'отслеживание', 'tracking'
    ],
    'stock': [
        'наявність', 'наличие', 'скільки', 'сколько', 'на складі',
        'на складе', 'є в наявності', 'есть в наличии'
    ],
    'price_alerts': [
        'ціни', 'ціна', 'цены', 'цена', 'цінові', 'ценовые',
        'демпінг', 'демпинг', 'демпінгує', 'демпингует'
    ],
    'feed_status': [
        'фід', 'фид', 'фіди', 'фиди', 'фідів', 'фидов',
        'публікація', 'публикация', 'публікації', 'публикации',
        'оновились', 'обновились'
    ],
    'system_status': [
        'статус системи', 'статус системы', 'як справи', 'как дела',
        'сервіси', 'сервисы', 'агенти', 'агенты'
    ],
    'help': [
        'допомога', 'помощь', 'команди', 'команды',
        'що ти вмієш', 'что ты умеешь', 'допоможи', 'помоги'
    ]
}

# Порядок намірів для розрішення зв'язків
INTENT_PRIORITY = [
    'orders_new', 'order_status', 'ttn_status', 'stock',
    'price_alerts', 'feed_status', 'system_status', 'help', 'unknown'
]

def _normalize_text(text: str) -> str:
    """Нормалізує текст для розбору."""
    # Переводимо в нижній регістр
    text = text.lower()
    # Замінюємо множинні пробіли на один
    text = re.sub(r'\s+', ' ', text)
    # Видаляємо знаки пунктуації, залишаючи лише букви, цифри та пробіли
    text = re.sub(r'[^\w\s]', ' ', text)
    # Видаляємо зайві пробіли на початку та кінці
    return text.strip()

def _extract_params(text: str) -> dict[str, Any]:
    """Витягує параметри з тексту."""
    params: dict[str, Any] = {}
    normalized = _normalize_text(text)
    
    # Пошук ТТН (14 цифр) - перевіряємо першим за вимогою
    ttn_match = REGEX_TTN.search(normalized)
    if ttn_match:
        params['ttn'] = ttn_match.group(0)
    
    # Пошук номера замовлення (9 цифр)
    order_match = REGEX_ORDER.search(normalized)
    if order_match:
        params['order_id'] = order_match.group(0)
    
    # Пошук артикулу (2 літери + 4-5 цифр)
    sku_match = REGEX_SKU.search(normalized)
    if sku_match:
        # Повертаємо великими літерами
        params['sku'] = sku_match.group(1).upper()
    
    # Пошук маркетплейсу
    for mp_name, mp_keywords in MARKETPLACES.items():
        if any(keyword in normalized for keyword in mp_keywords):
            params['marketplace'] = mp_name
            break
    
    # Пошук періоду
    for period_name, period_keywords in PERIODS.items():
        if any(keyword in normalized for keyword in period_keywords):
            params['period'] = period_name
            break
    
    return params

def _calculate_confidence(intent: str, params: dict[str, Any], text: str) -> float:
    """Обчислює впевненість у розпізнаному намірі."""
    if intent == 'unknown':
        return 0.0
    
    # Якщо є параметр, що однозначно визначає намір
    if intent == 'ttn_status' and 'ttn' in params:
        return 1.0
    if intent == 'order_status' and 'order_id' in params:
        return 1.0
    if intent == 'stock' and 'sku' in params:
        return 1.0
    if intent == 'price_alerts' and 'sku' in params:
        return 1.0
    
    # Перевірка наявності ключових слів наміру
    normalized = _normalize_text(text)
    keywords = INTENT_KEYWORDS.get(intent, [])
    matched_keywords = [kw for kw in keywords if kw in normalized]
    
    if len(matched_keywords) >= 2:
        # Два або більше ключових слів
        return 0.8
    elif len(matched_keywords) == 1:
        # Одне загальне слово
        return 0.5
    
    return 0.0

def _determine_intent(text: str, params: dict[str, Any]) -> str:
    """Визначає намір за параметрами та ключовими словами."""
    normalized = _normalize_text(text)
    
    # Правило 1: Параметр сильніший за слова
    # 14 цифр → ttn_status
    if 'ttn' in params:
        return 'ttn_status'
    
    # 9 цифр → order_status
    if 'order_id' in params:
        return 'order_status'
    
    # Артикул → stock, але зі словом «ціна» → price_alerts
    if 'sku' in params:
        price_keywords = ['ціни', 'ціна', 'цены', 'цена', 'цінові', 'ценовые']
        if any(kw in normalized for kw in price_keywords):
            return 'price_alerts'
        return 'stock'
    
    # Правило 2: Знаходимо намір за ключовими словами
    # Обчислюємо кількість збігів для кожного наміру
    scores: dict[str, int] = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in normalized)
        if count > 0:
            scores[intent] = count
    
    # Якщо є збіги, обираємо намір з найбільшою кількістю ключових слів
    if scores:
        # Знаходимо максимальний рахунок
        max_score = max(scores.values())
        # Знаходимо всі наміри з максимальним рахунком
        candidates = [intent for intent, score in scores.items() if score == max_score]
        
        # Якщо кілька кандидатів, обираємо за пріоритетом
        for intent in INTENT_PRIORITY:
            if intent in candidates:
                return intent
    
    # Якщо нічого не знайдено
    return 'unknown'

def parse(text: str) -> dict[str, Any]:
    """
    Аналізує вхідний текст та повертає структуровану інформацію про намір.
    
    Args:
        text: Вхідний текст для аналізу
        
    Returns:
        Словник з ключами:
        - intent: str - розпізнаний намір
        - params: dict - знайдені параметри
        - mutating: bool - чи змінює дія стан системи (завжди False)
        - confidence: float - впевненість у розпізнанні (0.0-1.0)
        - raw: str - оригінальний вхідний текст
    """
    # Обробка порожнього або None тексту
    if not text:
        text = ""
    
    # Витягуємо параметри
    params = _extract_params(text)
    
    # Визначаємо намір
    intent = _determine_intent(text, params)
    
    # Обчислюємо впевненість
    confidence = _calculate_confidence(intent, params, text)
    
    # Формуємо результат
    result = {
        'intent': intent,
        'params': params,
        'mutating': False,  # У цій версії завжди False
        'confidence': confidence,
        'raw': text
    }
    
    return result
```