"""Зв'язок текстових команд із переданими адаптерами читання."""

from integrations.errors import ApiError
from tg_dispatcher.ai_brain import commands, intents


def build_fetchers(rozetka=None, novaposhta=None, stock_lookup=None,
                   feeds_status=None, system_status=None, unanswered=None,
                   backup_status=None, supplier_stock=None, supplier_ttn=None,
                   orders_without_ttn=None, ttn_stuck=None) -> dict:
    fetchers = {}
    if rozetka is not None:
        def orders_new(marketplace=None, **kwargs):
            if marketplace not in (None, 'rozetka'):
                raise ApiError('helper', f'майданчик {marketplace} ще не підключено')
            return rozetka.active_orders()

        def order_details(order_id, **kwargs):
            order = rozetka.order(order_id)
            if novaposhta is None:
                return order
            order = dict(order)
            ttn = ''.join(str(order.get('ttn') or '').split())
            if len(ttn) == 14 and ttn.isascii() and ttn.isdigit():
                try:
                    order['ttn_info'] = novaposhta.ttn_status(ttn)
                except (ApiError, ValueError) as error:
                    order['ttn_info'] = {'error': str(error)}
            return order

        fetchers['orders_new'] = orders_new
        fetchers['order_details'] = order_details

        def orders_search(status, **kwargs):
            groups = {'completed': 2, 'cancelled': 3, 'delivering': 1}
            if status not in groups:
                raise ValueError('Невідомий стан замовлень')
            return [order for order in rozetka.orders(1)
                    if order.get('status_group') == groups[status]
                    and (status != 'delivering' or str(order.get('ttn') or '').strip())]

        def refunds(**kwargs):
            return ([dict(row, kind='refund') for row in rozetka.refunds()]
                    + [dict(row, kind='ticket') for row in rozetka.return_tickets()])

        def moderation(source=None, goods_tab=None, **kwargs):
            from integrations.rozetka import SOURCES

            sources = [source] if source is not None else SOURCES
            tabs = [goods_tab] if goods_tab is not None else ('moderation', 'errors', 'hidden')
            return {src: {tab: rozetka.goods_count(tab, src) for tab in tabs}
                    for src in sources}

        # Старі адаптери можуть ще не підтримувати нові методи читання.
        for intent, method_name in (
                ('orders_counts', 'order_counts'), ('item_comments', 'item_comments'),
                ('shop_reviews', 'shop_reviews'), ('balance', 'balance')):
            method = getattr(rozetka, method_name, None)
            if callable(method):
                fetchers[intent] = _without_params(method)
        if callable(getattr(rozetka, 'orders', None)):
            fetchers['orders_search'] = orders_search
        if all(callable(getattr(rozetka, name, None)) for name in ('refunds', 'return_tickets')):
            fetchers['refunds'] = refunds
        if callable(getattr(rozetka, 'refund_for_order', None)):
            fetchers['refund_detail'] = lambda order_id, **kwargs: rozetka.refund_for_order(order_id)
        if callable(getattr(rozetka, 'goods_count', None)):
            fetchers['moderation'] = moderation
    if novaposhta is not None:
        fetchers['ttn_status'] = lambda ttn, **kwargs: novaposhta.ttn_status(ttn)
    if stock_lookup is not None:
        fetchers['stock'] = lambda sku, **kwargs: stock_lookup(sku)
    if feeds_status is not None:
        fetchers['feeds'] = lambda **kwargs: feeds_status()
    if system_status is not None:
        fetchers['system'] = lambda **kwargs: system_status()
    for intent, function in (
            ('unanswered_chats', unanswered), ('backup_status', backup_status),
            ('supplier_ttn', supplier_ttn), ('orders_without_ttn', orders_without_ttn),
            ('ttn_stuck', ttn_stuck)):
        if function is not None:
            fetchers[intent] = _without_params(function)
    if supplier_stock is not None:
        fetchers['supplier_stock'] = lambda article, **kwargs: supplier_stock(article)
    return fetchers


def _without_params(function):
    """Прийняти параметри команди для залежності без аргументів."""
    return lambda **kwargs: function()


def answer(text: str, fetchers: dict) -> str:
    if not text or not text.strip():
        return commands.fmt_help()
    return commands.dispatch(intents.parse(text), fetchers)
