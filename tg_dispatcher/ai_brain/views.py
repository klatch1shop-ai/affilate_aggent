"""Текстові відповіді нових команд читання без приватних контактів."""

from collections.abc import Callable

from tg_dispatcher.inbox.render import LABELS
from tg_dispatcher.privacy import mask_private


def _value(row, key):
    """Показати невідоме значення рискою, зберігши нулі."""
    value = row.get(key)
    return '—' if value is None else str(value)


def _text(lines):
    """Маскувати всі поля остаточної відповіді."""
    return mask_private('\n'.join(lines))


def orders_counts(result, params):
    return _text([f'{title}: {_value(result, key)}' for key, title in (
        ('new', 'Нових'), ('in_work', 'У роботі'), ('delivering', 'В дорозі'),
        ('done', 'Виконано'), ('unwatched', 'Непереглянутих'))])


def orders_search(result, params):
    titles = {'cancelled': 'Скасовані замовлення', 'completed': 'Виконані замовлення',
              'delivering': 'Замовлення в дорозі'}
    if not result:
        return _text(['Замовлень немає'])
    return _text([f"{titles.get(params.get('status'), 'Замовлення')}: {len(result)}"]
                 + [f"№{_value(row, 'id')} — {_value(row, 'amount')} грн" for row in result])


def orders_without_ttn(result, params):
    if not result:
        return _text(['✅ Усі замовлення мають ТТН'])
    return _text([f'Без ТТН: {len(result)}'] + [
        f"№{_value(row, 'id')} ({_value(row, 'source')}) з {_value(row, 'created')}"
        for row in result])


def ttn_stuck(result, params):
    if not result:
        return _text(['✅ Посилок без руху немає'])
    return _text([f'Без руху: {len(result)}'] + [
        f"{_value(row, 'ttn')} — {_value(row, 'status')}, {_value(row, 'days')} дн."
        for row in result])


def refunds(result, params):
    if not result:
        return _text(['Повернень немає'])
    lines = [f'Повернення: {len(result)}']
    for row in result:
        detail = (f"повернення товару, ТТН {_value(row, 'ttn')}" if row.get('kind') == 'ticket'
                  else f"{_value(row, 'item_name')} — {_value(row, 'status_title')}")
        lines.append(f"№{_value(row, 'order_id')} — {detail}")
    return _text(lines)


def refund_detail(result, params):
    if not result:
        return _text(['Повернень по цьому замовленню немає'])
    lines = []
    for row in result:
        lines.extend([f"Замовлення №{_value(row, 'order_id')}",
                      f"Товар: {_value(row, 'item_name')}",
                      f"Статус: {_value(row, 'status_title')}",
                      f"Причина: {_value(row, 'reason_title')}"])
        lines.extend(str(row[key]) for key in ('sub_reason_title', 'sub_reason_comment')
                     if row.get(key))
        lines.append(f"Рішення: {_value(row, 'decision_title')}")
        if row.get('sub_decision_title'):
            lines.append(str(row['sub_decision_title']))
    return _text(lines)


def item_comments(result, params):
    new = sum(not row.get('read') for row in result)
    lines = [f'Питання й відгуки: {len(result)} (нових: {new})']
    for row in result:
        icon = '❓' if row.get('type') == 'question' else '⭐'
        mark = '🆕 ' if not row.get('read') else ''
        # Маскування до обрізання не залишає частини телефону чи email.
        text = mask_private(str(row.get('text') or ''))[:120]
        lines.append(f"{mark}{icon} {_value(row, 'title')} — {text}")
    return _text(lines)


def shop_reviews(result, params):
    lines = [f'Відгуки про магазин: {len(result)}']
    for row in result:
        icon = '👍' if row.get('vote') == 'like' else '👎'
        comment = mask_private(str(row.get('comment') or ''))[:120]
        lines.append(f"{icon} №{_value(row, 'order_id')}: {comment}")
    return _text(lines)


def _duration(minutes):
    """Подати тривалість очікування у хвилинах, годинах або днях."""
    minutes = int(minutes)
    if minutes < 60:
        return f'{minutes} хв'
    hours, remainder = divmod(minutes, 60)
    if hours < 24:
        return f'{hours} год {remainder} хв'
    days, hours = divmod(hours, 24)
    return f'{days} д {hours} год'


def unanswered_chats(result, params):
    if not result:
        return _text(['✅ Усім покупцям відповіли'])
    lines = [f'Без відповіді: {len(result)}']
    for row in result:
        marketplace = _value(row, 'marketplace')
        label = LABELS.get(marketplace, marketplace)
        lines.append(f"{label} · чат {_value(row, 'chat_id')}: {_duration(row['waiting_min'])}")
    return _text(lines)


def moderation(result, params):
    titles = {'moderation': 'модерація', 'errors': 'помилки', 'hidden': 'приховані'}
    return _text([f"{source}: " + ', '.join(
        f'{titles.get(tab, tab)} {count}' for tab, count in tabs.items())
        for source, tabs in result.items()])


def supplier_stock(result, params):
    states = {'in_stock': 'є', 'out': 'немає', 'unknown': 'невідомо'}
    return _text([f"Артикул {_value(result, 'article')}: {states.get(result.get('state'), 'невідомо')}",
                  f"Кількість: {_value(result, 'qty')}",
                  f"Ціна: {_value(result, 'price')} грн"])


def supplier_ttn(result, params):
    if not result:
        return _text(['ТТН сьогодні ще не надходили'])
    return _text([f'ТТН від постачальників: {len(result)}'] + [
        f"№{_value(row, 'order_id')} — {_value(row, 'ttn')} ({_value(row, 'supplier')})"
        for row in result])


def balance(result, params):
    return _text([f'{title}: {_value(result, key)} грн' for key, title in (
        ('balance', 'Баланс'), ('sum_in_gray', 'Заблоковано'), ('subscription_balance', 'Підписка'))])


def backup_status(result, params):
    if result.get('last') is None:
        return _text(['❌ Бекапів не знайдено'])
    icon = '✅' if result.get('ok') else '❌'
    return _text([f"{icon} Бекап: {_value(result, 'last')}",
                  f"Розмір: {_value(result, 'size_mb')} МБ",
                  f"{_value(result, 'age_h')} год тому"])


FORMATTERS: dict[str, Callable] = {
    'orders_counts': orders_counts,
    'orders_search': orders_search,
    'orders_without_ttn': orders_without_ttn,
    'ttn_stuck': ttn_stuck,
    'refunds': refunds,
    'refund_detail': refund_detail,
    'item_comments': item_comments,
    'shop_reviews': shop_reviews,
    'unanswered_chats': unanswered_chats,
    'moderation': moderation,
    'supplier_stock': supplier_stock,
    'supplier_ttn': supplier_ttn,
    'balance': balance,
    'backup_status': backup_status,
}
