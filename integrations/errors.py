"""Спільні помилки адаптерів із приховуванням контактів."""

from tg_dispatcher.privacy import mask_private


class ApiError(Exception):
    def __init__(self, service: str, message: str, code=None):
        self.service = service
        self.code = code
        text = f'{service}: {message}'
        if code is not None:
            text += f' (код {code})'
        super().__init__(mask_private(text))


class AuthError(ApiError):
    """Ключ відсутній, невірний або прострочений."""


class NotFound(ApiError):
    """Запитаного об'єкта немає."""
