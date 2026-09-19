"""Читання статусу ТТН Нової Пошти без персональних полів."""

import re

from .errors import ApiError, AuthError, NotFound
from .retry import call_with_retry

URL = 'https://api.novaposhta.ua/v2.0/json/'
SAFE_FIELDS = ('Number', 'Status', 'StatusCode', 'CityRecipient', 'WarehouseRecipient',
               'ScheduledDeliveryDate', 'ActualDeliveryDate', 'RecipientDateTime')
RATE_LIMIT_TEXT = 'To many requests'


class NovaPoshtaClient:
    def __init__(self, post, api_key, sleep, delays=(5, 15, 30)):
        if not api_key or not api_key.strip():
            raise AuthError('novaposhta', 'відсутній ключ')
        self._post = post
        self._api_key = api_key
        self._sleep = sleep
        self._delays = tuple(delays)

    def ttn_status(self, ttn: str, phone: str = '') -> dict:
        if not isinstance(ttn, str):
            raise ValueError('ТТН має містити 14 цифр')
        ttn = ''.join(ttn.split())
        if not re.fullmatch(r'[0-9]{14}', ttn):
            raise ValueError('ТТН має містити 14 цифр')
        payload = {
            'apiKey': self._api_key,
            'modelName': 'TrackingDocument',
            'calledMethod': 'getStatusDocuments',
            'methodProperties': {'Documents': [{'DocumentNumber': ttn, 'Phone': phone or ''}]},
        }
        for attempt in range(len(self._delays) + 1):
            try:
                status, body = call_with_retry(
                    lambda: self._post(URL, json=payload, headers={}), sleep=self._sleep,
                )
            except (ConnectionError, TimeoutError):
                raise ApiError('novaposhta', 'немає зв’язку') from None
            if status != 200:
                raise ApiError('novaposhta', 'помилка HTTP', code=status)
            if not isinstance(body, dict):
                raise ApiError('novaposhta', 'некоректна відповідь')
            errors = body.get('errors') or []
            if not isinstance(errors, list) or not all(isinstance(e, str) for e in errors):
                raise ApiError('novaposhta', 'некоректний список помилок')
            limited = any(RATE_LIMIT_TEXT.lower() in error.lower() for error in errors)
            data = body.get('data')
            empty = body.get('success') is True and data == []
            if limited or empty:
                if attempt < len(self._delays):
                    self._sleep(self._delays[attempt])
                    continue
                if limited:
                    raise ApiError('novaposhta', 'вичерпано ліміт запитів', code='rate_limit')
                raise NotFound('novaposhta', 'ТТН не знайдено')
            if body.get('success') is not True:
                message = '; '.join(errors) or 'некоректна відповідь'
                raise ApiError('novaposhta', message.replace(self._api_key, '[ключ приховано]'))
            if not isinstance(data, list) or not data or not isinstance(data[0], dict):
                raise ApiError('novaposhta', 'некоректні дані відправлення')
            return {field: data[0][field] for field in SAFE_FIELDS if field in data[0]}
