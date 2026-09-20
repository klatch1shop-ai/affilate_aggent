"""Добір тем зі звернень покупців і каталогу."""

from itertools import zip_longest


def from_questions(comments: list[dict], *, limit: int = 10) -> list[dict]:
    """Вибрати найновіші питання без відповіді, по одному на артикул."""
    eligible = sorted(
        (c for c in comments if c.get('type') == 'question' and c.get('has_answer') is False),
        key=lambda c: c['created'], reverse=True,
    )
    seen = set()
    result = []
    for c in eligible:
        if c['article'] in seen:
            continue
        seen.add(c['article'])
        result.append({'kind': 'question', 'title': c.get('item_name') or c['title'],
                       'article': c['article'], 'source': c['text'], 'created': c['created']})
    return result[:max(0, limit)]


def from_catalog(products: list[dict], *, limit: int = 10, min_price: float = 0) -> list[dict]:
    """Вибрати доступні товари за кількістю продажів."""
    eligible = sorted(
        (p for p in products if p['available'] and p['price'] >= min_price),
        key=lambda p: p['sold'], reverse=True,
    )
    return [{'kind': 'product', 'title': p['name'], 'article': p['sku'],
             'source': '', 'sold': p['sold']} for p in eligible[:max(0, limit)]]


def merge(*groups, limit: int = 10) -> list[dict]:
    """Чергувати позиції груп; для артикула брати тему з першої групи."""
    preferred = {}
    for group in groups:
        for topic in group:
            preferred.setdefault(topic['article'], topic)
    result = []
    seen = set()
    for row in zip_longest(*groups):
        for topic in row:
            if topic is None or topic['article'] in seen:
                continue
            seen.add(topic['article'])
            result.append(preferred[topic['article']])
    return result[:max(0, limit)]
