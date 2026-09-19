"""Єдина модель повідомлення та перетворення часу."""

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


MARKETPLACES = ('rozetka', 'prom', 'epicentr')


@dataclass(frozen=True)
class BuyerMessage:
    marketplace: str
    chat_id: str
    msg_id: str
    direction: str
    body: str
    created: datetime
    buyer_name: str = ''
    subject: str = ''
    order_id: str | None = None
    item_id: str | None = None
    has_files: bool = False

    def __post_init__(self):
        if self.marketplace not in MARKETPLACES:
            raise ValueError('Невідомий майданчик')
        if self.direction not in ('in', 'out'):
            raise ValueError('Невідомий напрямок повідомлення')
        for value in (self.chat_id, self.msg_id):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Ідентифікатор має бути непорожнім рядком')
        if not isinstance(self.created, datetime) or self.created.utcoffset() is None:
            raise ValueError('Час повідомлення має містити часову зону')
        object.__setattr__(self, 'created', self.created.astimezone(timezone.utc))


def kyiv_to_utc(value: str) -> datetime:
    """Перевести київський час у UTC з урахуванням літнього часу."""
    return datetime.strptime(value, '%Y-%m-%d %H:%M:%S').replace(
        tzinfo=ZoneInfo('Europe/Kyiv')).astimezone(timezone.utc)
