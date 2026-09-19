"""Зв'язок текстових команд із переданими адаптерами читання."""

from integrations.errors import ApiError
from tg_dispatcher.ai_brain import commands, intents


def build_fetchers(rozetka=None, novaposhta=None, stock_lookup=None,
                   feeds_status=None, system_status=None) -> dict:
    fetchers = {}
    if rozetka is not None:
        def orders_new(marketplace=None, **kwargs):
            if marketplace not in (None, 'rozetka'):
                raise ApiError('helper', f'майданчик {marketplace} ще не підключено')
            return rozetka.active_orders()

        fetchers['orders_new'] = orders_new
        fetchers['order_details'] = lambda order_id, **kwargs: rozetka.order(order_id)
    if novaposhta is not None:
        fetchers['ttn_status'] = lambda ttn, **kwargs: novaposhta.ttn_status(ttn)
    if stock_lookup is not None:
        fetchers['stock'] = lambda sku, **kwargs: stock_lookup(sku)
    if feeds_status is not None:
        fetchers['feeds'] = lambda **kwargs: feeds_status()
    if system_status is not None:
        fetchers['system'] = lambda **kwargs: system_status()
    return fetchers


def answer(text: str, fetchers: dict) -> str:
    if not text or not text.strip():
        return commands.fmt_help()
    return commands.dispatch(intents.parse(text), fetchers)
