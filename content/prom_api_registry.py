"""Реєстр методів Prom API (усі 21, з офіційного OpenAPI, 26.09.2026).

Джерело: https://prom.ua/cloud-cgi/static/uaprom-static/docs/swagger/documentation.json
(Swagger 2.0). Публічний список методів — закрита бета для обмеженого кола
компаній (public-api.docs.prom.ua), тому джерело істини саме ця специфікація,
а не сторінка документації (SPA, текст не в HTML).

Навіщо реєстр окремо від `integrations/prom.py`: той — робочий адаптер лише
на 2 методи (`orders/list`, `messages/list`), тут — ПОВНИЙ перелік того, що
взагалі можна викликати, з коротким описом кожного. Це вхід для генератора
команд Telegram (Gemini): короткий опис методу → природна фраза + параметри.

Лише дані та чисті функції. Жодних мережевих викликів.
"""

RISK = {
    'read': 'R0',            # GET — нічого не змінює
    'write': 'R2',           # POST, що міняє наш бізнес-стан (статус, відповідь)
    'write_external': 'R3',  # POST, що зачіпає покупця напряму (відповідь, повернення)
}

METHODS: dict[str, dict] = {
    'orders_list': {
        'path': '/orders/list', 'verb': 'GET', 'tag': 'Orders', 'risk': RISK['read'],
        'summary': 'Список замовлень компанії',
        'params': {'status': 'str', 'date_from': 'str', 'date_to': 'str',
                   'limit': 'int', 'last_id': 'int'},
    },
    'orders_get': {
        'path': '/orders/{id}', 'verb': 'GET', 'tag': 'Orders', 'risk': RISK['read'],
        'summary': 'Інформація про одне замовлення',
        'params': {'id': 'int*'},
    },
    'orders_set_status': {
        'path': '/orders/set_status', 'verb': 'POST', 'tag': 'Orders', 'risk': RISK['write'],
        'summary': 'Зміна статусу одного або кількох замовлень',
        'params': {'status': 'str', 'ids': 'list[int]',
                   'cancellation_reason': 'str', 'cancellation_text': 'str'},
    },
    'orders_refund': {
        'path': '/orders/refund', 'verb': 'POST', 'tag': 'Orders', 'risk': RISK['write_external'],
        'summary': 'Повернення грошей покупцю',
        'params': {'ids': 'list[int]'},
    },
    'messages_list': {
        'path': '/messages/list', 'verb': 'GET', 'tag': 'Messages', 'risk': RISK['read'],
        'summary': 'Список повідомлень (питань) покупців компанії',
        'params': {'status': 'str', 'date_from': 'str', 'date_to': 'str',
                   'limit': 'int', 'last_id': 'int'},
    },
    'messages_get': {
        'path': '/messages/{id}', 'verb': 'GET', 'tag': 'Messages', 'risk': RISK['read'],
        'summary': 'Інформація про одне повідомлення',
        'params': {'id': 'int*'},
    },
    'messages_set_status': {
        'path': '/messages/set_status', 'verb': 'POST', 'tag': 'Messages', 'risk': RISK['write'],
        'summary': 'Зміна статусу одного або кількох повідомлень (напр. «прочитано»)',
        'params': {'status': 'str', 'ids': 'list[int]'},
    },
    'messages_reply': {
        'path': '/messages/reply', 'verb': 'POST', 'tag': 'Messages', 'risk': RISK['write_external'],
        'summary': 'Відповідь на повідомлення покупця',
        'params': {'id': 'int', 'message': 'str'},
    },
    'clients_list': {
        'path': '/clients/list', 'verb': 'GET', 'tag': 'Clients', 'risk': RISK['read'],
        'summary': 'Список клієнтів компанії',
        'params': {'limit': 'int', 'last_id': 'int', 'search_term': 'str'},
    },
    'clients_get': {
        'path': '/clients/{id}', 'verb': 'GET', 'tag': 'Clients', 'risk': RISK['read'],
        'summary': 'Інформація про одного клієнта',
        'params': {'id': 'int*'},
    },
    'products_list': {
        'path': '/products/list', 'verb': 'GET', 'tag': 'Products', 'risk': RISK['read'],
        'summary': 'Список товарів компанії',
        'params': {'limit': 'int', 'last_id': 'int', 'group_id': 'int'},
    },
    'products_get': {
        'path': '/products/{id}', 'verb': 'GET', 'tag': 'Products', 'risk': RISK['read'],
        'summary': 'Інформація про один товар за внутрішнім id Prom',
        'params': {'id': 'int*'},
    },
    'products_get_by_external_id': {
        'path': '/products/by_external_id/{id}', 'verb': 'GET', 'tag': 'Products',
        'risk': RISK['read'],
        'summary': 'Інформація про товар за нашим зовнішнім id (SKU)',
        'params': {'id': 'str*'},
    },
    'products_edit': {
        'path': '/products/edit', 'verb': 'POST', 'tag': 'Products', 'risk': RISK['write'],
        'summary': 'Редагування товарів (ціна, наявність, опис тощо) за id Prom',
        'params': {},
    },
    'products_edit_by_external_id': {
        'path': '/products/edit_by_external_id', 'verb': 'POST', 'tag': 'Products',
        'risk': RISK['write'],
        'summary': 'Редагування товарів за нашим зовнішнім id (SKU)',
        'params': {},
    },
    'products_import_url': {
        'path': '/products/import_url', 'verb': 'POST', 'tag': 'Products', 'risk': RISK['write'],
        'summary': 'Імпорт товарів з прайс-файлу за посиланням (наш фід)',
        'params': {'url': 'str*', 'force_update': 'bool', 'only_available': 'bool',
                   'mark_missing_product_as': 'str', 'updated_fields': 'list[str]'},
    },
    'products_import_file': {
        'path': '/products/import_file', 'verb': 'POST', 'tag': 'Products', 'risk': RISK['write'],
        'summary': 'Імпорт товарів із завантаженого файлу',
        'params': {'file': 'str', 'data': 'dict'},
    },
    'products_import_status': {
        'path': '/products/import/status/{id}', 'verb': 'GET', 'tag': 'Products',
        'risk': RISK['read'],
        'summary': 'Стан виконання раніше запущеного імпорту товарів',
        'params': {'id': 'int*'},
    },
    'groups_list': {
        'path': '/groups/list', 'verb': 'GET', 'tag': 'Groups', 'risk': RISK['read'],
        'summary': 'Список товарних груп (категорій) компанії',
        'params': {'limit': 'int', 'last_id': 'int'},
    },
    'payment_options_list': {
        'path': '/payment_options/list', 'verb': 'GET', 'tag': 'PaymentOption',
        'risk': RISK['read'],
        'summary': 'Список доступних способів оплати компанії',
        'params': {},
    },
    'delivery_save_declaration_id': {
        'path': '/delivery/save_declaration_id', 'verb': 'POST', 'tag': 'Delivery',
        'risk': RISK['write'],
        'summary': 'Прив’язка номера декларації (ТТН) до замовлення',
        'params': {'order_id': 'int', 'declaration_id': 'str', 'delivery_type': 'str'},
    },
}


def by_tag() -> dict[str, list[str]]:
    """Ідентифікатори методів згруповані за офіційним тегом (Orders, Products…)."""
    out: dict[str, list[str]] = {}
    for mid, m in METHODS.items():
        out.setdefault(m['tag'], []).append(mid)
    return out


def by_risk(risk: str) -> list[str]:
    return [mid for mid, m in METHODS.items() if m['risk'] == risk]


def registry_line(mid: str) -> str:
    """Один рядок реєстру для промпту Gemini: id · verb path · опис · параметри."""
    m = METHODS[mid]
    params = ', '.join(f'{k}:{v}' for k, v in m['params'].items()) or '—'
    return f"{mid} · {m['verb']} {m['path']} · {m['summary']} · параметри: {params}"


def registry_text() -> str:
    return '\n'.join(registry_line(mid) for mid in METHODS)
