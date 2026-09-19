"""Час ранкового звіту та його текст без зовнішніх викликів."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from tg_dispatcher.inbox.render import LABELS
from tg_dispatcher.privacy import mask_private


KYIV = ZoneInfo('Europe/Kyiv')


def due(now: datetime, last_sent: date | None, hour: int = 9) -> bool:
    """Перевірити час звіту та відсутність надсилання за київську дату."""
    if now.utcoffset() is None:
        raise ValueError('Поточний час має містити часову зону')
    local = now.astimezone(KYIV)
    return local.hour >= hour and last_sent != local.date()


def build_digest(now: datetime, orders, unanswered, feeds, services) -> str:
    """Зібрати звіт, явно позначивши недоступні джерела даних."""
    if now.utcoffset() is None:
        raise ValueError('Поточний час має містити часову зону')
    lines = [f'☀️ Ранковий звіт {now.astimezone(KYIV):%d.%m}']
    if orders is None:
        lines.append('⚠️ Замовлення: не вдалося отримати')
    else:
        lines.append(f'🆕 Замовлень у роботі: {len(orders)}')
        lines.extend(f"№{order.get('id', '—')} — {order.get('amount', '—')} грн"
                     for order in orders[:10])
        if len(orders) > 10:
            lines.append(f'… ще {len(orders) - 10}')

    if unanswered is None:
        lines.append('⚠️ Чати покупців: не вдалося отримати')
    else:
        lines.append(f'💬 Чати без відповіді: {len(unanswered)}')
        lines.extend(f"{LABELS[item['marketplace']]} · чат {item['chat_id']}: "
                     f"{item['waiting_min']} хв" for item in unanswered)

    if feeds is None:
        lines.append('⚠️ Фіди: не вдалося отримати')
    else:
        problems = [(name, info) for name, info in feeds.items() if not info.get('ok')]
        lines.append('📦 Фіди з проблемами:' if problems else '📦 Фіди: усі в нормі')
        for name, info in problems:
            age = info.get('age_min')
            lines.append(f"❌ {name}: вік {age if age is not None else '—'} хв; "
                         f"офферів: {info.get('offers', '—')}")

    if services is None:
        lines.append('⚠️ Служби: не вдалося отримати')
    else:
        problems = [(name, state) for name, state in services.items() if state != 'active']
        lines.append('🖥 Служби з проблемами:' if problems else '🖥 Служби: усі працюють')
        lines.extend(f'❌ {name}: {state}' for name, state in problems)
    return mask_private('\n'.join(lines))
