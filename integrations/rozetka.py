"""Читання замовлень і чатів Rozetka через підставлений транспорт."""

import re

from tg_dispatcher.privacy import mask_private

from .errors import ApiError, AuthError, NotFound
from .retry import call_with_retry

BASE = 'https://api-seller.rozetka.com.ua'
AUTH_CODES = {1004, 1020, 5401, 6001}
ORDER_FIELDS = ('id', 'created', 'status', 'status_group', 'amount', 'cost', 'ttn', 'total_quantity')
PURCHASE_FIELDS = ('quantity', 'price', 'cost', 'ttn')
SOURCES = {'dropoffice': 55861, 'toptul': 55634, 'noire': 54788, 'carvol': 51949}
GOODS_TABS = ('moderation', 'errors', 'hidden', 'on-sale', 'new')
REFUND_FIELDS = ('id', 'status_title', 'reason_title', 'order_id', 'item_name', 'item_id', 'datetime', 'read')
REFUND_DETAIL_FIELDS = REFUND_FIELDS + (
    'order_date', 'chat_id', 'sub_reason_title', 'sub_reason_comment',
    'decision_title', 'sub_decision_title',
)


def clean_refund(r: dict, detail: bool = False) -> dict:
    """Залишити дозволені поля повернення й приховати контакти в текстах."""
    fields = REFUND_DETAIL_FIELDS if detail else REFUND_FIELDS
    result = {field: r.get(field) for field in fields}
    for field in fields:
        if isinstance(result[field], str):
            result[field] = mask_private(result[field])
    return result


def clean_comment(c: dict) -> dict:
    """Очистити питання чи відгук про товар від даних покупця."""
    record = c.get('record') or {}
    item = c.get('item') or {}
    result = {field: c.get(field) for field in ('id', 'type', 'created', 'status', 'mark')}
    result.update({
        'read': bool(c.get('is_reade')),
        'has_answer': bool(c.get('has_children')),
        'title': record.get('title'),
        'article': item.get('article'),
        'item_name': item.get('name_ua') or item.get('name'),
        'text': mask_private(c['text']) if isinstance(c.get('text'), str) else None,
    })
    return result


def clean_review(r: dict) -> dict:
    """Залишити дозволені поля відгуку про магазин і маскувати тексти."""
    result = {field: r.get(field) for field in (
        'id', 'order_id', 'vote', 'status', 'created_at', 'read', 'problem_solved',
    )}
    for field in ('comment', 'reply'):
        value = r.get(field)
        result[field] = mask_private(value) if isinstance(value, str) else None
    return result


def _clean_return_ticket(ticket: dict) -> dict:
    """Залишити лише дозволені поля квитка повернення та його позицій."""
    result = {field: ticket.get(field) for field in (
        'id', 'order_id', 'carrier', 'ttn', 'status', 'expires_at',
    )}
    result['items'] = [
        {field: item.get(field) for field in ('name', 'qty_expected', 'qty_received', 'status')}
        for item in ticket.get('items') or []
    ]
    return result


def clean_order(order: dict) -> dict:
    """Залишити лише дозволені поля замовлення й позицій."""
    result = {field: order.get(field) for field in ORDER_FIELDS}
    result['purchases'] = []
    for purchase in order.get('purchases') or []:
        item = purchase.get('item') or {}
        clean = {field: purchase.get(field) for field in PURCHASE_FIELDS}
        clean['item'] = {
            'article': item.get('article'),
            'name': item.get('name_ua') or item.get('name') or purchase.get('item_name'),
        }
        result['purchases'].append(clean)
    return result


class RozetkaClient:
    def __init__(self, get, token, sleep, max_pages=10):
        if not token or not token.strip():
            raise AuthError('rozetka', 'відсутній токен')
        if type(max_pages) is not int or max_pages < 1:
            raise ValueError('max_pages має бути додатним цілим числом')
        self._get = get
        self._token = token
        self._sleep = sleep
        self._max_pages = max_pages

    def _request(self, path, params):
        try:
            status, body = call_with_retry(
                lambda: self._get(BASE + path, params=params, headers={
                    'Authorization': f'Bearer {self._token}', 'Content-Language': 'uk',
                }), sleep=self._sleep,
            )
        except (ConnectionError, TimeoutError):
            raise ApiError('rozetka', 'немає зв’язку') from None
        envelope = body if isinstance(body, dict) else {}
        errors = envelope.get('errors')
        errors = errors if isinstance(errors, dict) else {}
        code = errors.get('code')
        if status == 401 or code in AUTH_CODES:
            raise AuthError('rozetka', 'невірний або прострочений токен', code=code or status)
        if status != 200:
            raise ApiError('rozetka', 'помилка HTTP', code=status)
        if envelope.get('success') is not True:
            message = str(errors.get('message') or 'некоректна відповідь')
            message = message.replace(self._token, '[токен приховано]')
            error = NotFound if code == 5404 or message == 'not_found' else ApiError
            if isinstance(code, str):
                code = code.replace(self._token, '[токен приховано]')
            raise error('rozetka', message, code=code)
        if not isinstance(envelope.get('content'), dict):
            raise ApiError('rozetka', 'відсутній або некоректний content')
        return envelope['content']

    def orders(self, types: int) -> list[dict]:
        result = []
        page = 1
        while True:
            content = self._request('/orders/search', {
                'types': types, 'page': page, 'expand': 'purchases', 'sort': '-id',
            })
            meta = content.get('_meta')
            count = meta.get('pageCount') if isinstance(meta, dict) else None
            orders = content.get('orders')
            if type(count) is not int or count < 0 or not isinstance(orders, list):
                raise ApiError('rozetka', 'некоректна сторінка замовлень')
            if count > self._max_pages:
                raise ApiError('rozetka', f'неповний список: {count} сторінок')
            try:
                result.extend(clean_order(order) for order in orders)
            except (AttributeError, TypeError):
                raise ApiError('rozetka', 'некоректне замовлення') from None
            if page >= count:
                return result
            page += 1

    def active_orders(self) -> list[dict]:
        orders = self.orders(4) + self.orders(2)
        unique = {order['id']: order for order in orders}
        return sorted(unique.values(), key=lambda order: order['id'], reverse=True)

    def order(self, order_id) -> dict:
        if type(order_id) not in (int, str) or not re.fullmatch(r'[0-9]{9}', str(order_id)):
            raise ValueError('номер замовлення має містити 9 цифр')
        content = self._request(f'/orders/{order_id}', {'expand': 'purchases,delivery,payment'})
        try:
            return clean_order(content)
        except (AttributeError, TypeError):
            raise ApiError('rozetka', 'некоректне замовлення') from None

    def chats_page(self, page: int) -> dict:
        return self._request('/messages/search', {'page': page})

    def chat(self, chat_id) -> dict:
        return self._request(f'/messages/{chat_id}', {'expand': 'messages'})

    def _read_list(self, path, key, cleaner, params=None) -> list[dict]:
        """Прочитати всі сторінки нового списку без мовчазного обрізання."""
        result = []
        page = 1
        while True:
            content = self._request(path, {**(params or {}), 'page': page})
            meta = content.get('_meta')
            count = meta.get('pageCount') if isinstance(meta, dict) else None
            items = content.get(key)
            if type(count) is not int or count < 0 or not isinstance(items, list):
                raise ApiError('rozetka', 'некоректна сторінка списку')
            if count > self._max_pages:
                raise ApiError('rozetka', f'неповний список: {count} сторінок')
            if count == 0:
                return result
            try:
                result.extend(cleaner(item) for item in items)
            except (AttributeError, TypeError):
                raise ApiError('rozetka', 'некоректний елемент списку') from None
            if page >= count:
                return result
            page += 1

    def order_counts(self) -> dict:
        content = self._request('/orders/counts', {})
        fields = {'new': 'new', 'in_work': 'inNotDone', 'delivering': 'delivering',
                  'done': 'inDone', 'unwatched': 'unwatched'}
        try:
            return {key: int(content[field]) if field in content else None
                    for key, field in fields.items()}
        except (TypeError, ValueError, OverflowError):
            raise ApiError('rozetka', 'некоректні лічильники замовлень') from None

    def refunds(self) -> list[dict]:
        return self._read_list('/order-refund/search', 'orderRefunds', clean_refund)

    def refund_detail(self, refund_id) -> dict:
        if type(refund_id) not in (str, int, float) or not str(refund_id).strip():
            raise ValueError('ідентифікатор повернення має бути непорожнім рядком або числом')
        content = self._request(f'/order-refund/detail/{refund_id}', {})
        return clean_refund(content, detail=True)

    def refund_for_order(self, order_id) -> list[dict]:
        if type(order_id) not in (int, str) or not re.fullmatch(r'[0-9]{9}', str(order_id)):
            raise ValueError('номер замовлення має містити 9 цифр')
        return self._read_list('/order-refund/search', 'orderRefunds', clean_refund,
                               {'order_id': order_id})

    def return_tickets(self) -> list[dict]:
        return self._read_list('/item-return/ticket/search', 'tickets', _clean_return_ticket)

    def item_comments(self) -> list[dict]:
        return self._read_list('/item-comments/search', 'itemComments', clean_comment)

    def shop_reviews(self) -> list[dict]:
        return self._read_list('/market-reviews/search', 'marketReviews', clean_review)

    def balance(self) -> dict:
        content = self._request('/balances/total', {})
        balances = content.get('totalBalance')
        fields = {'balance': 'balance', 'sum_in_gray': 'sumInGray',
                  'subscription_balance': 'subscription_balance'}
        if (not isinstance(balances, list) or not balances
                or not isinstance(balances[0], dict)
                or any(balances[0].get(field) is None for field in fields.values())):
            raise ApiError('rozetka', 'відсутній або некоректний баланс')
        return {key: str(balances[0][field]) for key, field in fields.items()}

    def goods_count(self, tab: str, source: str | None = None) -> int:
        if not isinstance(tab, str) or tab not in GOODS_TABS:
            raise ValueError('невідома вкладка товарів')
        if source is not None and (not isinstance(source, str) or source not in SOURCES):
            raise ValueError('невідоме джерело товарів')
        params = {'page': 1}
        if source is not None:
            params['sync_source_id'] = SOURCES[source]
        content = self._request(f'/goods/{tab}', params)
        meta = content.get('_meta')
        if not isinstance(meta, dict) or 'totalCount' not in meta:
            raise ApiError('rozetka', 'відсутній лічильник товарів')
        try:
            return int(meta['totalCount'])
        except (TypeError, ValueError, OverflowError):
            raise ApiError('rozetka', 'некоректний лічильник товарів') from None

    def messages_counts(self) -> dict:
        content = self._request('/messages/counts', {})
        return {key: value for key, value in content.items() if type(value) is int}
