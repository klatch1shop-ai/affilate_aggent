"""Зведення фактів про товар із переданих даних без зовнішніх дій."""

from datetime import timedelta


WINDOWS = (30, 90)
KNOWN_GAPS = ('покази й кліки на маркетплейсі', 'перегляди й переходи із соцмереж')


def build(sku, *, orders, returns, questions, reviews, prices, our_price, now) -> dict:
    """Зібрати показники SKU з включними нижніми межами часових вікон."""
    cutoffs = {days: now - timedelta(days=days) for days in WINDOWS}
    recent_orders = {
        days: [order for order in orders if order['created'] >= cutoff]
        for days, cutoff in cutoffs.items()
    }
    done = sum(order['status'] == 'done' for order in recent_orders[90])
    cancelled = sum(order['status'] == 'cancelled' for order in recent_orders[90])
    closed = done + cancelled
    recent_reviews = [review for review in reviews if review['created'] >= cutoffs[90]]
    cheapest = min(prices, key=lambda item: item['price']) if prices else None
    min_price = cheapest['price'] if cheapest is not None else None
    price_gap = None
    # Відсоткова різниця від нульової бази не визначена.
    if our_price is not None and min_price is not None and min_price != 0:
        price_gap = round((our_price - min_price) / min_price * 100, 1)

    gaps = list(KNOWN_GAPS)
    if not prices:
        gaps.append('немає цін конкурентів')
    if not recent_reviews:
        gaps.append('немає відгуків')
    if not recent_orders[90]:
        gaps.append('немає замовлень за 90 днів')

    return {
        'sku': sku,
        'orders_30': len(recent_orders[30]),
        'orders_90': len(recent_orders[90]),
        'sum_30': round(sum(order.get('sum', 0) for order in recent_orders[30]
                            if order['status'] == 'done'), 2),
        'buyout': round(done / closed, 2) if closed else None,
        'returns_30': sum(item['created'] >= cutoffs[30] for item in returns),
        'questions_open': sum(item['answered'] is False for item in questions),
        'reviews_count': len(recent_reviews),
        'rating': (round(sum(item['rating'] for item in recent_reviews)
                         / len(recent_reviews), 2) if recent_reviews else None),
        'our_price': our_price,
        'min_price': min_price,
        'min_seller': cheapest['seller'] if cheapest is not None else None,
        'price_gap': price_gap,
        'gaps': gaps,
    }


def _money(value):
    """Відформатувати суму з пробілами між тисячами."""
    return f'{value:,.2f}'.replace(',', ' ')


def report(funnel: dict) -> str:
    """Повернути текстове зведення з явним переліком прогалин у даних."""
    buyout = ('даних нема' if funnel['buyout'] is None
              else f"{round(funnel['buyout'] * 100)}%")
    lines = [
        f"📊 {funnel['sku']}",
        f"Замовлення: {funnel['orders_30']} за 30 дн · {funnel['orders_90']} за 90 дн"
        f" · виконано на {_money(funnel['sum_30'])} ₴",
        f"Викуп: {buyout} · повернень за 30 дн: {funnel['returns_30']}",
        f"Питання без відповіді: {funnel['questions_open']}",
        f"Відгуки: {funnel['reviews_count']}",
    ]
    if funnel['rating'] is not None:
        lines[-1] += f" · середня {funnel['rating']:.2f}"

    price_parts = []
    if funnel['our_price'] is not None:
        price_parts.append(f"{_money(funnel['our_price'])} ₴")
    if funnel['min_price'] is not None:
        price_parts.append(f"найдешевший конкурент {_money(funnel['min_price'])} ₴"
                           f" ({funnel['min_seller']})")
    gap = funnel['price_gap']
    if gap is not None:
        if gap < 0:
            price_parts.append(f'ми дешевші на {abs(gap):.1f}%')
        elif gap > 0:
            price_parts.append(f'ми дорожчі на {gap:.1f}%')
        else:
            price_parts.append('ціна однакова')
    if price_parts:
        lines.append('Ціна: ' + ' · '.join(price_parts))
    lines.append('Чого не знаємо: ' + '; '.join(funnel['gaps']))
    return '\n'.join(lines)
