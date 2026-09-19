"""Читання замовлень і чатів Rozetka через підставлений транспорт."""

import re

from .errors import ApiError, AuthError, NotFound
from .retry import call_with_retry

BASE = 'https://api-seller.rozetka.com.ua'
AUTH_CODES = {1004, 1020, 5401, 6001}
ORDER_FIELDS = ('id', 'created', 'status', 'status_group', 'amount', 'cost', 'ttn', 'total_quantity')
PURCHASE_FIELDS = ('quantity', 'price', 'cost', 'ttn')


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
