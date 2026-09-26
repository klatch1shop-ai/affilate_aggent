"""Читання повідомлень і замовлень Prom через підставлений транспорт."""

from .errors import ApiError, AuthError
from .retry import call_with_retry

BASE = 'https://my.prom.ua/api/v1'


class PromClient:
    def __init__(self, get, token, sleep):
        if not token or not token.strip():
            raise AuthError('prom', 'відсутній токен')
        self._get = get
        self._token = token
        self._sleep = sleep

    def _list(self, resource, params):
        limit = params['limit']
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('limit має бути цілим числом від 1 до 100')
        try:
            status, body = call_with_retry(
                lambda: self._get(f'{BASE}/{resource}/list', params=params, headers={
                    'Authorization': f'Bearer {self._token}',
                }), sleep=self._sleep,
            )
        except (ConnectionError, TimeoutError):
            raise ApiError('prom', 'немає зв’язку') from None
        if status in (401, 403):
            raise AuthError('prom', 'невірний або прострочений токен', code=status)
        if status != 200:
            raise ApiError('prom', 'помилка HTTP', code=status)
        if not isinstance(body, dict) or not isinstance(body.get(resource), list):
            raise ApiError('prom', f'відсутній або некоректний список {resource}')
        return body[resource]

    def messages(self, limit: int = 100, last_id=None) -> list[dict]:
        params = {'limit': limit}
        if last_id is not None:
            params['last_id'] = last_id
        return self._list('messages', params)

    def orders(self, limit: int = 50, status: str | None = None) -> list[dict]:
        params = {'limit': limit}
        if status is not None:
            params['status'] = status
        return self._list('orders', params)

    def order(self, order_id) -> dict:
        """Одне замовлення (`GET /orders/{id}`) — реєстр `orders_get`, 26.09.2026."""
        try:
            status, body = call_with_retry(
                lambda: self._get(f'{BASE}/orders/{order_id}', params={}, headers={
                    'Authorization': f'Bearer {self._token}',
                }), sleep=self._sleep,
            )
        except (ConnectionError, TimeoutError):
            raise ApiError('prom', 'немає зв’язку') from None
        if status in (401, 403):
            raise AuthError('prom', 'невірний або прострочений токен', code=status)
        if status == 404:
            raise ApiError('prom', 'замовлення не знайдено', code=404)
        if status != 200:
            raise ApiError('prom', 'помилка HTTP', code=status)
        if not isinstance(body, dict) or not isinstance(body.get('order'), dict):
            raise ApiError('prom', 'відсутнє або некоректне замовлення')
        return body['order']
