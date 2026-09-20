"""Збирання повідомлень через передані функції без власних мережевих дій."""

from datetime import datetime, timedelta

from .normalize import from_rozetka


def collect_rozetka(list_page, get_chat, store, now: datetime,
                    first_run_hours: int = 24, max_pages: int = 20,
                    msg_type: str | None = None) -> dict:
    """Обійти список чатів, не зсуваючи курсор за неповного збору."""
    if now.utcoffset() is None or max_pages < 1:
        raise ValueError('Потрібні час із зоною та додатна межа сторінок')
    cursor_key = 'rozetka' if msg_type is None else f'rozetka:{msg_type}'
    cursor = store.get_cursor(cursor_key)
    result = dict(new=[], cursor=cursor, errors=[], chats_checked=0)
    newest = cursor
    cutoff = now - timedelta(hours=first_run_hours)
    page, page_count = 1, 1
    while page <= min(page_count, max_pages):
        try:
            content = list_page(page) if msg_type is None else list_page(page, msg_type)
            page_count = max(page_count, int(content['_meta']['pageCount']))
            chats = content['chats']
        except Exception:
            result['errors'].append(f'Не вдалося отримати сторінку {page}')
            break
        result['chats_checked'] += len(chats)
        for chat in chats:
            chat_id = chat.get('id', '?')
            try:
                updated = chat['updated']
                newest = max(newest, updated) if newest is not None else updated
                if cursor is not None and updated <= cursor:
                    continue
                messages = from_rozetka(get_chat(chat_id))
                added = store.add_new(messages)
                result['new'].extend(msg for msg in added if msg.direction == 'in'
                                     and (cursor is not None or msg.created >= cutoff))
            except Exception:
                # Текст винятку може містити приватні дані покупця.
                result['errors'].append(f'Не вдалося обробити чат {chat_id}')
        page += 1
    if page_count > max_pages:
        result['errors'].append(
            f'Неповний обхід: отримано {page - 1} сторінок із {page_count}')
    result['new'].sort(key=lambda msg: msg.created)
    if not result['errors'] and newest is not None:
        store.set_cursor(cursor_key, newest)
        result['cursor'] = newest
    return result
