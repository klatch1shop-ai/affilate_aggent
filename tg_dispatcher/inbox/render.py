"""Безпечні HTML-картки повідомлень та нагадування."""

from html import escape
from zoneinfo import ZoneInfo

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


def human_duration(minutes: int) -> str:
    """Показати очікування у хвилинах, годинах або днях."""
    if minutes < 60:
        return f'{minutes} хв'
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f'{hours} год {minutes} хв'
    days, hours = divmod(hours, 24)
    return f'{days} д {hours} год'


def thread_card(messages: list[BuyerMessage], limit: int = 3) -> str:
    """Показати останні репліки чату з київським часом і прихованими контактами."""
    if not messages or limit <= 0:
        return ''
    recent = sorted(messages, key=lambda msg: msg.created)[-limit:]
    last = recent[-1]
    header = [f'{LABELS[last.marketplace]} · чат {_safe(last.chat_id)}']
    for label, value in (('Тема', last.subject), ('Замовлення', last.order_id),
                         ('Товар', last.item_id)):
        if value:
            header.append(f'{label}: {_safe(value)}')
    lines = [' · '.join(header)]
    for msg in recent:
        icon = '👤' if msg.direction == 'in' else '🏪'
        when = msg.created.astimezone(ZoneInfo('Europe/Kyiv')).strftime('%H:%M %d.%m')
        body = escape(mask_private(msg.body)[:600])
        lines.append(f'{icon} {when} {body}')
    lines.append('Відповідайте реплаєм на це повідомлення')
    return '\n'.join(lines)


def reminder_detail(items: list[dict]) -> str:
    """Показати нагадування з темою та уривком останнього питання."""
    if not items:
        return ''
    lines = [f'⏰ Чекають відповіді: {len(items)}']
    for item in items:
        lines.append(f"{LABELS[item['marketplace']]} · чат {_safe(item['chat_id'])} · "
                     f"{human_duration(item['waiting_min'])}")
        subject = _safe(item.get('subject', ''))
        body = escape(mask_private(item.get('last_text', ''))[:120])
        if subject or body:
            lines.append(f'{subject} — {body}')
    return '\n'.join(lines)
