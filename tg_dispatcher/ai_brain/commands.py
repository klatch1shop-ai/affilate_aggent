"""Текстові відповіді бота із запитами, переданими ззовні."""

import re


COMMANDS: dict = {
    'orders_new': {'needs': [], 'fetcher': 'orders_new', 'title': 'Нові замовлення'},
    'order_status': {'needs': ['order_id'], 'fetcher': 'order_details', 'title': 'Стан замовлення'},
    'ttn_status': {'needs': ['ttn'], 'fetcher': 'ttn_status', 'title': 'Стан посилки'},
    'stock': {'needs': ['sku'], 'fetcher': 'stock', 'title': 'Наявність товару'},
    'feed_status': {'needs': [], 'fetcher': 'feeds', 'title': 'Стан фідів'},
    'system_status': {'needs': [], 'fetcher': 'system', 'title': 'Стан системи'},
    'price_alerts': {'needs': [], 'fetcher': 'price_alerts', 'title': 'Перевірка цін'},
    'help': {'needs': [], 'fetcher': None, 'title': 'Довідка'},
}

# Межі за цифрами не дозволяють приховати частину номера замовлення чи ТТН.
_PHONE = re.compile(r'(?<!\d)\+?(?:380\d{7,9}|0\d{9,11})(?!\d)')
_PROMPTS = {
    'order_id': 'Вкажіть номер замовлення (9 цифр)',
    'ttn': 'Вкажіть номер ТТН (14 цифр)',
    'sku': 'Вкажіть артикул',
}
_EXAMPLES = {
    'orders_new': 'замовлення розетки за сьогодні',
    'order_status': 'що із замовленням 906209393',
    'ttn_status': 'де посилка 20451537526626',
    'stock': 'скільки SO3270 на складі',
    'feed_status': 'стан фідів',
    'system_status': 'статус системи',
    'price_alerts': 'перевір ціни',
    'help': 'що ти вмієш',
}


def _safe(text: str) -> str:
    """Приховати телефонні номери в усіх текстових полях відповіді."""
    return _PHONE.sub('[телефон приховано]', text)


def missing_params(parsed: dict) -> list:
    """Перелічити відсутні або порожні обов'язкові параметри."""
    needs = COMMANDS.get(parsed.get('intent'), {}).get('needs', [])
    params = parsed.get('params') or {}
    return [key for key in needs if not str(params.get(key) or '').strip()]


def dispatch(parsed: dict, fetchers: dict) -> str:
    """Виконати команду через передану функцію та підготувати відповідь."""
    intent = parsed.get('intent')
    if intent not in COMMANDS or parsed.get('confidence', 0) < 0.5 or intent == 'help':
        return fmt_help()
    missing = missing_params(parsed)
    if missing:
        return _safe('\n'.join(_PROMPTS[key] for key in missing))
    command = COMMANDS[intent]
    fetcher = fetchers.get(command['fetcher'])
    if fetcher is None:
        return _safe(f"⚠️ Команда ще не підключена: {command['title']}")
    allowed = command['needs'] + ['marketplace', 'period']
    params = {key: value for key, value in (parsed.get('params') or {}).items()
              if key in allowed}
    try:
        result = fetcher(**params)
        if intent == 'stock':
            return fmt_stock(result, params['sku'])
        formatters = {
            'orders_new': fmt_orders,
            'order_status': fmt_order,
            'ttn_status': fmt_ttn,
            'feed_status': fmt_feeds,
        }
        if intent in formatters:
            return formatters[intent](result)
        return _safe(result)
    except Exception:
        # Не розкриваємо дані покупців, що могли потрапити в текст винятку.
        return _safe(f"⚠️ Не вдалося виконати дію: {command['title']}")


def fmt_orders(orders: list) -> str:
    """Показати кількість замовлень і стислий рядок для кожного."""
    if not orders:
        return 'Нових замовлень немає'
    lines = [f'Нові замовлення: {len(orders)}']
    for order in orders:
        lines.append(f"№{order.get('id', '—')} — {order.get('amount', '—')} грн; "
                     f"позицій: {len(order.get('purchases') or [])}")
    return _safe('\n'.join(lines))


def fmt_order(order: dict) -> str:
    """Показати замовлення, кожну його позицію та наявну ТТН."""
    lines = [f"Замовлення №{order.get('id', '—')}",
             f"Статус: {order.get('status', '—')}",
             f"Сума: {order.get('amount', '—')} грн"]
    for purchase in order.get('purchases') or []:
        item = purchase.get('item') or {}
        lines.append(f"{item.get('article', '—')} × {purchase.get('quantity', '—')}")
    if order.get('ttn'):
        lines.append(f"ТТН: {order['ttn']}")
    return _safe('\n'.join(lines))


def fmt_ttn(info: dict) -> str:
    """Показати відомі реквізити посилки, допускаючи неповну відповідь."""
    fields = [('Number', 'ТТН'), ('Status', 'Статус'),
              ('WarehouseRecipient', 'Відділення отримувача'),
              ('ScheduledDeliveryDate', 'Очікувана дата доставки')]
    lines = [f'{title}: {info[key]}' for key, title in fields if info.get(key)]
    return _safe('\n'.join(lines) if lines else 'Даних про посилку немає')


def fmt_stock(row: dict | None, sku: str) -> str:
    """Показати залишок і роздрібну ціну або відсутність артикулу."""
    if row is None:
        return _safe(f'Артикул {sku} не знайдено')
    unavailable = row.get('available') is False or row.get('quantity') == 0
    status = 'немає в наявності' if unavailable else 'в наявності'
    return _safe(f"Артикул {row.get('sku', sku)}: {row.get('name', '—')}\n"
                 f"{status}; кількість: {row.get('quantity', '—')}\n"
                 f"Ціна: {row.get('price_retail', '—')} грн")


def fmt_feeds(feeds: dict) -> str:
    """Показати стан, вік і кількість офферів кожного майданчика."""
    lines = [f"{'✅' if info.get('ok') else '❌'} {marketplace}: "
             f"вік {info.get('age_min', '—')} хв; офферів: {info.get('offers', '—')}"
             for marketplace, info in feeds.items()]
    return _safe('\n'.join(lines) if lines else 'Даних про фіди немає')


def fmt_help() -> str:
    """Показати приклад фрази для кожної доступної команди."""
    return _safe('\n'.join(f"{command['title']}: «{_EXAMPLES[intent]}»"
                           for intent, command in COMMANDS.items()))
