"""
Модуль розбору намірів текстових/голосових команд.
Визначає намір, параметри та впевненість на основі тексту.
"""

import re
from typing import Any

# --- Компіляція регулярних виразів для параметрів ---
_TTN_RE = re.compile(r'\b\d{14}\b')
_ORDER_ID_RE = re.compile(r'\b\d{9}\b')
_SKU_RE = re.compile(r'\b([a-zA-Z]{2}\d{4,5})\b')
# Основи слів, а не повні форми: «розетка / розетки / розетці / на розетці».
# Приймання 16.09: повні форми давали marketplace=None у трьох фразах з чотирьох.
_MARKETPLACE_KEYWORDS = {
    'розетк': 'rozetka',
    'розетц': 'rozetka',
    'rozetka': 'rozetka',
    'пром': 'prom',
    'prom': 'prom',
    'єпіцентр': 'epicentr',
    'епіцентр': 'epicentr',
    'epicentr': 'epicentr',
}
_PERIOD_KEYWORDS = {
    'сьогодні': 'today',
    'сегодня': 'today',
    'вчора': 'yesterday',
    'вчера': 'yesterday',
    'тиждень': 'week',
    'за тиждень': 'week',
    'за неделю': 'week',
}

# --- Ключові слова намірів (українська/російська) ---
_INTENT_KEYWORDS: dict[str, list[str]] = {
    'orders_new': [
        'замовленн', 'заказ',          # основа слова: «замовлення розетки», «заказы»
        'нові замовлення', 'новые заказы',
        'замовлення за сьогодні', 'заказы за сегодня',
        'щось замовили', 'что-то заказали',
        'які замовлення', 'какие заказы',
    ],
    'order_status': [
        'статус замовлення', 'статус заказа',
        'що із замовленням', 'что с заказом',
        'про замовлення', 'про заказ',
    ],
    'ttn_status': [
        'де посилка', 'где посылка',
        'статус ттн', 'статус накладної',
        'статус накладной', 'ттн',
    ],
    'stock': [
        'наявність', 'наличие',
        'на складі', 'на складе',
        'сколько', 'скільки',
        'є в наявності', 'есть в наличии',
    ],
    'price_alerts': [
        'цінові алерти', 'ценовые алерты',
        'демпінг', 'демпинг',          # основа: «демпінг», «демпінгує»
        'перевір ціни', 'проверь цены',
        'ціна', 'цены', 'ціни',
    ],
    'feed_status': [
        'фід', 'фид',
        'фіди', 'фиды',
        'публікація', 'публикация',
        'опублікувати', 'опубликовать',
    ],
    'system_status': [
        'як справи', 'как дела',
        'статус системи', 'статус системы',
        'сервіси жив', 'сервисы жив',
        'агенти', 'агенты',
    ],
    'help': [
        'допомога', 'помощь',
        'команди', 'команды',
        'що ти вмієш', 'что ты умеешь',
        'як користуватися', 'как пользоваться',
    ],
}

# --- Ключові слова для цін (для визначення 0.5 впевненості) ---
_PRICE_GENERIC_WORDS = {'ціна', 'цены', 'ціни', 'демпінг', 'демпинг'}

def _normalize(text: str) -> str:
    """Нормалізація тексту: нижній регістр, прибираємо зайві пробіли та розділові."""
    text = text.lower()
    text = re.sub(r'[^a-zа-яіїєґ0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def _extract_params(normalized: str) -> dict[str, Any]:
    """Вилучення параметрів з нормалізованого тексту."""
    params: dict[str, Any] = {}

    # 1. ТТН (14 цифр) — перевіряємо першим
    ttn_match = _TTN_RE.search(normalized)
    if ttn_match:
        params['ttn'] = ttn_match.group()

    # 2. Номер замовлення (9 цифр) — лише якщо не знайдено ТТН
    if 'ttn' not in params:
        order_match = _ORDER_ID_RE.search(normalized)
        if order_match:
            params['order_id'] = order_match.group()

    # 3. Артикул (SKU)
    sku_match = _SKU_RE.search(normalized)
    if sku_match:
        # Повертаємо великими літерами
        params['sku'] = sku_match.group(1).upper()

    # 4. Маркетплейс
    for keyword, marketplace in _MARKETPLACE_KEYWORDS.items():
        if keyword in normalized:
            params['marketplace'] = marketplace
            break

    # 5. Період
    for keyword, period in _PERIOD_KEYWORDS.items():
        if keyword in normalized:
            params['period'] = period
            break

    return params

def _determine_intent(normalized: str, params: dict[str, Any]) -> tuple[str, float]:
    """Визначення наміру та впевненості на основі параметрів та ключових слів."""
    # --- 1. Якщо є параметри, що однозначно визначають намір ---
    if 'ttn' in params:
        return 'ttn_status', 1.0
    if 'order_id' in params:
        return 'order_status', 1.0
    if 'sku' in params:
        # Якщо поряд з артикулом є слово про ціну → price_alerts, інакше → stock
        sku_index = normalized.find(params['sku'].lower())
        context = normalized[max(0, sku_index - 20):sku_index + len(params['sku']) + 20]
        if any(word in context for word in _PRICE_GENERIC_WORDS):
            return 'price_alerts', 1.0
        return 'stock', 1.0

    # --- 2. Якщо параметрів немає, шукаємо за ключовими словами ---
    best_intent = 'unknown'
    best_confidence = 0.0
    best_score = 0  # кількість збігів ключових слів

    for intent, keywords in _INTENT_KEYWORDS.items():
        hits = [kw for kw in keywords if kw in normalized]
        if not hits:
            continue
        longest = max(len(kw) for kw in hits)
        # довжина найдовшого збігу важливіша за кількість: «що із замовленням»
        # конкретніше за основу «замовленн»
        score = len(hits) + longest / 100
        if score <= best_score:
            continue
        best_score, best_intent = score, intent
        # Впевненість рахується з самих збігів, а не з дробового рахунку:
        # приймання 16.09 — намір визначався, а confidence лишалась 0.0.
        matched = max(hits, key=len)
        if len(hits) >= 2 or longest >= 8:
            best_confidence = 0.8
        elif matched in _PRICE_GENERIC_WORDS:
            best_confidence = 0.5          # лише загальне слово про ціну
        else:
            best_confidence = 0.8

    return best_intent, best_confidence

def parse(text: str) -> dict[str, Any]:
    """
    Аналіз тексту команди та повернення структурованого результату.
    
    Параметри:
        text: вхідний текст (голосова чи текстова команда)
    
    Повертає:
        Словник з ключами: intent, params, mutating, confidence, raw
    """
    # Обробка порожнього або некоректного тексту
    if not text or not isinstance(text, str):
        return {
            'intent': 'unknown',
            'params': {},
            'mutating': False,
            'confidence': 0.0,
            'raw': text if isinstance(text, str) else '',
        }

    raw_text = text                      # §2.1: raw — вхідний текст без змін
    normalized = _normalize(text)
    params = _extract_params(normalized)
    intent, confidence = _determine_intent(normalized, params)

    return {
        'intent': intent,
        'params': params,
        'mutating': False,  # У цій версії завжди False
        'confidence': confidence,
        'raw': raw_text,
    }
