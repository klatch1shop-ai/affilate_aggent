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
_ARTICLE_RE = re.compile(r'\b[a-zA-Z]{2,6}\d{3,8}[a-zA-Z]*(?:-[a-zA-Z]+)*\b')
_PARAM_KEYWORDS = {
    'status': {
        'cancelled': ('скасован', 'отмен'),
        'completed': ('виконан', 'доставлен', 'отриман'),
        'delivering': ('в дорозі', 'доставляються', 'отправлен'),
    },
    'source': {
        'toptul': ('toptul', 'топтул'),
        'noire': ('noire', 'нуар'),
        'dropoffice': ('dropoffice', 'дропофіс'),
        'carvol': ('carvol', 'карвол'),
    },
    'goods_tab': {
        'moderation': ('модерац',),
        'errors': ('помилк',),
        'hidden': ('прихован',),
    },
}
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
    'ttn_stuck': ['без руху', 'застряг', 'не забрали'],
    'label': ['етикетк', 'надрукуй', 'друк'],
    'refunds': ['повернен'],
    'item_comments': ['відгук', 'питання про товари'],
    'unanswered_chats': [
        'чекає відповіді', 'чати без відповіді', 'нові повідомлення покупців',
    ],
    'moderation': ['модерац', 'помилки товарів', 'приховані товари'],
    'balance': ['баланс', 'грошей на баланс'],
    'invoices': ['рахунк'],
    'backup_status': ['бекап', 'резервна копія'],
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

def _extract_params(normalized: str, raw: str) -> dict[str, Any]:
    """Вилучення параметрів зі збереженням дефісів в артикулах."""
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
    else:
        article_match = _ARTICLE_RE.search(raw)
        if article_match:
            params['article'] = article_match.group().upper()

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

    for key, values in _PARAM_KEYWORDS.items():
        for value, keywords in values.items():
            if any(keyword in normalized for keyword in keywords):
                params[key] = value
                break

    return params

def _determine_intent(normalized: str, params: dict[str, Any]) -> tuple[str, float]:
    """Визначення наміру та впевненості на основі параметрів та ключових слів."""
    # --- 1. Якщо є параметри, що однозначно визначають намір ---
    if 'ttn' in params:
        if any(word in normalized for word in ('етикетк', 'надрукуй', 'друк')):
            return 'label', 1.0
        return 'ttn_status', 1.0
    if 'order_id' in params:
        if 'повернен' in normalized:
            return 'refund_detail', 1.0
        if 'викуп' in normalized or 'рейтинг покупця' in normalized:
            return 'buyer_rating', 1.0
        return 'order_status', 1.0
    if ('article' in params or 'sku' in params) and re.search(
            r'\b[ув] постачальник(?:а|ів)\b', normalized):
        return 'supplier_stock', 1.0
    if 'sku' in params:
        # Якщо поряд з артикулом є слово про ціну → price_alerts, інакше → stock
        sku_index = normalized.find(params['sku'].lower())
        context = normalized[max(0, sku_index - 20):sku_index + len(params['sku']) + 20]
        if any(word in context for word in _PRICE_GENERIC_WORDS):
            return 'price_alerts', 1.0
        return 'stock', 1.0

    # --- 2. Однозначні комбінації випереджають загальні слова ---
    if re.search(r'\b(?:без|нема|немає) ттн\b', normalized):
        return 'orders_without_ttn', 1.0
    if re.search(r'\bттн від постачальник|\bприйшли ттн\b', normalized):
        return 'supplier_ttn', 1.0
    has_orders = bool(re.search(r'\b(?:замовлен|заказ)', normalized))
    if has_orders and re.search(r'\b(?:скільки|сколько|кількість|количество)\b', normalized):
        return 'orders_counts', 1.0
    if has_orders and 'status' in params:
        return 'orders_search', 1.0
    if 'відгуки про магазин' in normalized or 'оцінки магазину' in normalized:
        return 'shop_reviews', 1.0

    # --- 3. Решта — ключові слова зі старою шкалою впевненості ---
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
    params = _extract_params(normalized, raw_text)
    intent, confidence = _determine_intent(normalized, params)

    return {
        'intent': intent,
        'params': params,
        'mutating': False,  # У цій версії завжди False
        'confidence': confidence,
        'raw': raw_text,
    }
