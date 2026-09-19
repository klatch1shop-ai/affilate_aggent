"""Перетворення відповідей майданчиків без перенесення контактних полів."""

from datetime import datetime
from zoneinfo import ZoneInfo

from .model import BuyerMessage, kyiv_to_utc


def _optional_id(value):
    return None if value is None else str(value)


def from_rozetka(chat: dict) -> list[BuyerMessage]:
    """Нормалізувати повідомлення чату Rozetka та впорядкувати за часом."""
    result = [BuyerMessage(
        marketplace='rozetka', chat_id=str(chat['id']), msg_id=str(msg['id']),
        direction='out' if msg.get('sender') == 2 else 'in',
        body=msg.get('body') or '', created=kyiv_to_utc(msg['created']),
        buyer_name=(chat.get('user') or {}).get('contact_fio') or '',
        subject=chat.get('subject') or '', order_id=_optional_id(chat.get('order_id')),
        item_id=_optional_id(chat.get('item_id')), has_files=bool(msg.get('files')),
    ) for msg in chat.get('messages', [])]
    return sorted(result, key=lambda msg: msg.created)


def from_prom(msg: dict) -> BuyerMessage | None:
    """Нормалізувати повідомлення Prom, пропускаючи видалені."""
    if msg.get('status') == 'deleted':
        return None
    created = datetime.fromisoformat(msg['date_created'])
    if created.utcoffset() is None:
        created = created.replace(tzinfo=ZoneInfo('Europe/Kyiv'))
    return BuyerMessage(
        marketplace='prom', chat_id=str(msg['id']), msg_id=str(msg['id']),
        direction='in', body=msg.get('message') or '', created=created,
        buyer_name=msg.get('client_full_name') or '', subject=msg.get('subject') or '',
        item_id=_optional_id(msg.get('product_id')),
    )
