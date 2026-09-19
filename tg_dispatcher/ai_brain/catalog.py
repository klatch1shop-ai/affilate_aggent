"""Каталог намірів, рівнів ризику та прикладів для довідки бота."""

RISK_LEVELS = ('R0', 'R1', 'R2', 'R3')
GROUPS = ('Замовлення', 'Посилки', 'Покупці', 'Повернення', 'Товари',
          'Постачальники', 'Гроші', 'Система')

CATALOG: dict[str, dict] = {
    'orders_new': {
        'title': 'Нові замовлення', 'risk': 'R0', 'needs': [],
        'example': 'нові замовлення', 'group': 'Замовлення',
    },
    'order_status': {
        'title': 'Стан замовлення', 'risk': 'R0', 'needs': ['order_id'],
        'example': 'що із замовленням 906372863', 'group': 'Замовлення',
    },
    'orders_counts': {
        'title': 'Кількість замовлень', 'risk': 'R0', 'needs': [],
        'example': 'скільки замовлень у роботі', 'group': 'Замовлення',
    },
    'orders_search': {
        'title': 'Пошук замовлень', 'risk': 'R0', 'needs': ['status'],
        'example': 'скасовані замовлення за тиждень', 'group': 'Замовлення',
    },
    'orders_without_ttn': {
        'title': 'Замовлення без ТТН', 'risk': 'R0', 'needs': [],
        'example': 'замовлення без ттн', 'group': 'Замовлення',
    },
    'ttn_status': {
        'title': 'Стан посилки', 'risk': 'R0', 'needs': ['ttn'],
        'example': 'де посилка 20451539117101', 'group': 'Посилки',
    },
    'ttn_stuck': {
        'title': 'Посилки без руху', 'risk': 'R0', 'needs': [],
        'example': 'посилки без руху', 'group': 'Посилки',
    },
    'label': {
        'title': 'Етикетка посилки', 'risk': 'R0', 'needs': ['ttn'],
        'example': 'етикетка 20451539117101', 'group': 'Посилки',
    },
    'buyer_rating': {
        'title': 'Викуп покупця', 'risk': 'R0', 'needs': ['order_id'],
        'example': 'викуп покупця 906372863', 'group': 'Покупці',
    },
    'item_comments': {
        'title': 'Питання й відгуки про товари', 'risk': 'R0', 'needs': [],
        'example': 'нові відгуки', 'group': 'Покупці',
    },
    'shop_reviews': {
        'title': 'Відгуки про магазин', 'risk': 'R0', 'needs': [],
        'example': 'відгуки про магазин', 'group': 'Покупці',
    },
    'unanswered_chats': {
        'title': 'Чати без відповіді', 'risk': 'R0', 'needs': [],
        'example': 'хто чекає відповіді', 'group': 'Покупці',
    },
    'refunds': {
        'title': 'Заявки на повернення', 'risk': 'R0', 'needs': [],
        'example': 'заявки на повернення', 'group': 'Повернення',
    },
    'refund_detail': {
        'title': 'Деталі повернення', 'risk': 'R0', 'needs': ['order_id'],
        'example': 'повернення по 906372863', 'group': 'Повернення',
    },
    'stock': {
        'title': 'Наявність товару', 'risk': 'R0', 'needs': ['sku'],
        'example': 'скільки SO3270 на складі', 'group': 'Товари',
    },
    'price_alerts': {
        'title': 'Перевірка цін', 'risk': 'R0', 'needs': [],
        'example': 'перевір ціни', 'group': 'Товари',
    },
    'moderation': {
        'title': 'Модерація товарів', 'risk': 'R0', 'needs': [],
        'example': 'товари на модерації', 'group': 'Товари',
    },
    'supplier_stock': {
        'title': 'Наявність у постачальника', 'risk': 'R0', 'needs': ['article'],
        'example': 'є у постачальника KAAA1404', 'group': 'Постачальники',
    },
    'supplier_ttn': {
        'title': 'ТТН від постачальників', 'risk': 'R0', 'needs': [],
        'example': 'ттн від постачальників', 'group': 'Постачальники',
    },
    'balance': {
        'title': 'Баланс', 'risk': 'R0', 'needs': [],
        'example': 'баланс розетки', 'group': 'Гроші',
    },
    'invoices': {
        'title': 'Рахунки на оплату', 'risk': 'R0', 'needs': [],
        'example': 'рахунки на оплату', 'group': 'Гроші',
    },
    'feed_status': {
        'title': 'Стан фідів', 'risk': 'R0', 'needs': [],
        'example': 'стан фідів', 'group': 'Система',
    },
    'system_status': {
        'title': 'Стан системи', 'risk': 'R0', 'needs': [],
        'example': 'статус системи', 'group': 'Система',
    },
    'backup_status': {
        'title': 'Стан резервної копії', 'risk': 'R0', 'needs': [],
        'example': 'коли був бекап', 'group': 'Система',
    },
    'help': {
        'title': 'Довідка', 'risk': 'R0', 'needs': [],
        'example': 'що ти вмієш', 'group': 'Система',
    },
}


def by_group() -> dict[str, list[str]]:
    """Згрупувати наміри в порядку груп і записів каталогу."""
    result = {}
    for group in GROUPS:
        intents = [intent for intent, entry in CATALOG.items() if entry['group'] == group]
        if intents:
            result[group] = intents
    return result


def help_text(available: set[str] | None = None) -> str:
    """Показати приклади доступних команд без самої команди довідки."""
    lines = []
    for group, intents in by_group().items():
        visible = [intent for intent in intents
                   if intent != 'help' and (available is None or intent in available)]
        if not visible:
            continue
        lines.append(f'{group}:')
        for intent in visible:
            entry = CATALOG[intent]
            lines.append(f"• {entry['title']}: «{entry['example']}»")
    return '\n'.join(lines)
