"""Планування відповіді власника без надсилання повідомлень."""

from tg_dispatcher.privacy import mask_private
from .store import InboxStore


REPLY_MODES = ('off', 'draft', 'live')
MAX_REPLY = 2000


def plan_reply(reply_to_tg_id: int | None, text: str, store: InboxStore, mode: str) -> dict:
    """Перевірити прив'язку, текст та режим у встановленому порядку."""
    if mode not in REPLY_MODES:
        raise ValueError('Невідомий режим відповіді')
    result = dict(ok=False, action='none', marketplace=None, chat_id=None,
                  body='', message='Повідомлення не пов’язане з чатом покупця')
    chat = store.chat_for_tg(reply_to_tg_id) if reply_to_tg_id is not None else None
    if chat is None:
        return result
    result['marketplace'], result['chat_id'] = chat
    body = text.strip()
    if not body:
        result['message'] = 'Текст відповіді порожній'
    elif len(body) > MAX_REPLY:
        result['message'] = f'Відповідь має містити не більше {MAX_REPLY} символів'
    elif mask_private(body) != body or any(
        word in body.lower() for word in
        ('http://', 'https://', 'www.', 't.me/', 'viber', 'telegram', 'whatsapp')
    ):
        result['message'] = 'Контакти й посилання у відповіді заборонені'
    elif mode == 'off':
        result['message'] = 'Відповіді вимкнено'
    else:
        result.update(ok=True, body=body, action='send' if mode == 'live' else 'none',
                      message='Відповідь готова до надсилання' if mode == 'live'
                      else 'Чернетка відповіді підготовлена')
    return result
