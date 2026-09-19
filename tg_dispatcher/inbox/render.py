"""Безпечні HTML-картки повідомлень та нагадування."""

from html import escape

from tg_dispatcher.privacy import mask_private
from .model import BuyerMessage


LABELS = {'rozetka': '🟢 Rozetka', 'prom': '🟣 Prom', 'epicentr': '🟠 Епіцентр'}
MAX_BODY = 3000


def _safe(value) -> str:
    return escape(mask_private(str(value)))


def card(msg: BuyerMessage) -> str:
    """Підготувати картку, приховавши контакти перед обрізанням тексту."""
    lines = [f'{LABELS[msg.marketplace]} · чат {_safe(msg.chat_id)}']
    for label, value in (('Покупець', msg.buyer_name), ('Тема', msg.subject),
                         ('Замовлення', msg.order_id), ('Товар', msg.item_id)):
        if value:
            lines.append(f'{label}: {_safe(value)}')
    body = mask_private(msg.body)
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + '…'
    lines.extend(['', escape(body)])
    if msg.has_files:
        lines.append('📎 Є вкладення')
    lines.append('Відповідайте реплаєм на це повідомлення')
    return '\n'.join(lines)


def reminder(items: list[dict]) -> str:
    """Показати кількість чатів та тривалість очікування."""
    if not items:
        return ''
    lines = [f'⏰ Чатів без відповіді: {len(items)}']
    lines.extend(f"{LABELS[item['marketplace']]} · чат {_safe(item['chat_id'])}: "
                 f"{_safe(item['waiting_min'])} хв" for item in items)
    return '\n'.join(lines)
