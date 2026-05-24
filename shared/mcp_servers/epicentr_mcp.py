"""
shared/mcp_servers/epicentr_mcp.py
=====================================
MCP сервер для Єпіцентр Merchant API.

Семантична агрегація: 25 endpoints → 12 розумних інструментів.
Принцип: LangGraph оперує поняттями бізнесу, а не деталями API.

Статуси замовлень (з YAML):
  new → confirmed_by_merchant → confirmed → sent → delivered → completed
  canceled / canceled_by_merchant / returned / return_requested

Запуск:
    python3 shared/mcp_servers/epicentr_mcp.py

Як systemd:
    systemctl --user start epicentr-mcp
"""

import os, sys, httpx, asyncio
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from mcp.server.fastmcp import FastMCP
from typing import Optional, Literal

mcp = FastMCP("Epicentr Marketplace API")

BASE_URL = os.getenv('EPICENTR_API_URL', 'https://api.epicentrm.com.ua')
TOKEN    = os.getenv('EPICENTR_TOKEN', '')
HEADERS  = {
    'Authorization': f'Bearer {TOKEN}',
    'Content-Type':  'application/json',
}

# ── Data Contract: єдиний словник статусів для LangGraph ──────────────────
# LangGraph не знає про внутрішні коди Єпіцентру
UNIFIED_TO_EPICENTR = {
    'new':       'new',
    'accepted':  'confirmed_by_merchant',
    'confirmed': 'confirmed',
    'shipped':   'sent',
    'delivered': 'delivered',
    'completed': 'completed',
    'cancelled': 'canceled_by_merchant',
}

EPICENTR_TO_UNIFIED = {v: k for k, v in UNIFIED_TO_EPICENTR.items()}


# ══════════════════════════════════════════════════════════════════════════
# ДОМЕН 1: ЗАМОВЛЕННЯ (OMS)
# ══════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_orders(
    status: Optional[str] = None,
    limit: int = 20,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> str:
    """
    Отримати список замовлень Єпіцентру з фільтрацією.

    Args:
        status: Фільтр за статусом (new/accepted/confirmed/shipped/delivered/completed/cancelled)
        limit: Кількість замовлень (макс 100)
        date_from: Дата від (формат: 2026-05-01T00:00:00)
        date_to: Дата до (формат: 2026-05-31T23:59:59)

    Returns:
        JSON список замовлень з id, статусом, сумою, клієнтом
    """
    params = {'limit': min(limit, 100)}

    # Конвертуємо уніфікований статус → Єпіцентр
    if status and status in UNIFIED_TO_EPICENTR:
        params['statusCode'] = UNIFIED_TO_EPICENTR[status]
    elif status:
        params['statusCode'] = status

    if date_from:
        params['dateFrom'] = date_from
    if date_to:
        params['dateTo'] = date_to

    async with httpx.AsyncClient(timeout=30) as client:
        # Отримуємо замовлення і загальну кількість паралельно
        r_orders = await client.get(f'{BASE_URL}/v3/oms/orders', headers=HEADERS, params=params)
        r_total  = await client.get(f'{BASE_URL}/v3/oms/orders/total', headers=HEADERS, params=params)

        if r_orders.status_code != 200:
            return f'❌ Помилка {r_orders.status_code}: {r_orders.text[:200]}'

        data   = r_orders.json()
        total  = r_total.json().get('total', '?') if r_total.status_code == 200 else '?'
        orders = data.get('items', [])

        lines = [f'📦 Замовлення Єпіцентру ({len(orders)} з {total}):']
        for o in orders:
            # Статус: з statusCode або з cancel.previousStatusCode
            status_code = o.get('statusCode') or (o.get('cancel') or {}).get('previousStatusCode', '?')
            unified = EPICENTR_TO_UNIFIED.get(status_code, status_code)

            # Ціна: сума items або пряме поле
            price = o.get('totalPrice') or o.get('total')
            if not price and o.get('items'):
                price = sum(i.get('subtotal', 0) for i in o['items'])

            # Клієнт: з address або client
            addr = o.get('address') or {}
            client_name = f"{addr.get('firstName','')} {addr.get('lastName','')}".strip()
            phone = addr.get('phone', '')

            # ID: зовнішній або внутрішній
            ext_id = o.get('externalId') or o.get('id', '?')[:8] + '...'

            lines.append(
                f"  #{ext_id} | {unified:25} | "
                f"{price or '?'} грн | {client_name} {phone} | id:{o.get('id','?')[:8]}..."
            )
        return '\n'.join(lines)


@mcp.tool()
async def get_order(order_id: str) -> str:
    """
    Отримати повні деталі одного замовлення Єпіцентру.

    Args:
        order_id: UUID замовлення (або зовнішній ID з маркетплейсу)

    Returns:
        Повна інформація: клієнт, доставка, товари, статус, ТТН
    """
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f'{BASE_URL}/v5/oms/orders/{order_id}', headers=HEADERS)

        if r.status_code != 200:
            return f'❌ Замовлення {order_id} не знайдено. Код: {r.status_code}'

        o = r.json()
        unified = EPICENTR_TO_UNIFIED.get(o.get('statusCode', ''), o.get('statusCode', '?'))

        lines = [
            f'📋 Замовлення #{o.get("externalId")} (id: {o.get("id")})',
            f'Статус: {unified}',
            f'Сума: {o.get("totalPrice")} грн',
        ]

        if o.get('client'):
            c = o['client']
            lines.append(f'Клієнт: {c.get("firstName","")} {c.get("lastName","")} | {c.get("phone","")}')

        if o.get('delivery'):
            d = o['delivery']
            lines.append(f'Доставка: {d.get("provider","")} | {d.get("address","")}')
            if d.get('ttn'):
                lines.append(f'ТТН: {d["ttn"]}')

        if o.get('items'):
            lines.append(f'Товарів: {len(o["items"])}')
            for item in o['items'][:3]:
                lines.append(f'  - {item.get("title","?")} x{item.get("quantity",1)} = {item.get("totalPrice","?")} грн')

        return '\n'.join(lines)


@mcp.tool()
async def update_order_status(
    order_id: str,
    action: Literal['accept', 'confirm', 'ship', 'cancel'],
    comment: Optional[str] = None,
    cancel_reason: Optional[str] = None,
) -> str:
    """
    Змінити статус замовлення Єпіцентру.

    Args:
        order_id: UUID замовлення
        action: Дія — accept(прийняти)/confirm(підтвердити)/ship(відправити)/cancel(скасувати)
        comment: Коментар до зміни статусу
        cancel_reason: Причина скасування (обов'язково для cancel)

    Returns:
        Результат операції
    """
    ACTION_MAP = {
        'accept':  'confirmed_by_merchant',
        'confirm': 'confirmed',
        'ship':    'sent',
        'cancel':  'canceled_by_merchant',
    }
    target_status = ACTION_MAP.get(action, action)

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Перевіряємо дозволені статуси
        r_allowed = await client.get(
            f'{BASE_URL}/v2/oms/orders/{order_id}/allowed-statuses',
            headers=HEADERS
        )

        if r_allowed.status_code == 200:
            allowed = [s.get('code') for s in r_allowed.json().get('items', [])]
            if target_status not in allowed:
                return (f'❌ Статус "{action}" недоступний для цього замовлення.\n'
                       f'Доступні: {[EPICENTR_TO_UNIFIED.get(s,s) for s in allowed]}')

        # 2. Формуємо payload
        if action == 'cancel':
            payload = {
                'reason_code': cancel_reason or 'other',
                'comment': comment or 'Скасовано продавцем',
            }
        else:
            payload = {'comment': comment} if comment else {}

        # 3. Змінюємо статус
        url = f'{BASE_URL}/v2/oms/orders/{order_id}/change-status/to/{target_status}'
        r = await client.post(url, json=payload, headers=HEADERS)

        if r.status_code in (200, 202, 204):
            action_ua = {'accept':'прийнято','confirm':'підтверджено',
                        'ship':'відправлено','cancel':'скасовано'}
            return f'✅ Замовлення {order_id[:8]}... {action_ua.get(action, action)}'

        return f'❌ Помилка зміни статусу. Код: {r.status_code} | {r.text[:200]}'


@mcp.tool()
async def add_order_ttn(
    order_id: str,
    ttn: str,
    delivery_provider: Literal['nova_poshta', 'ukrposhta', 'meest', 'justin'] = 'nova_poshta',
) -> str:
    """
    Додати ТТН до замовлення і автоматично перевести в статус "Відправлено".

    Args:
        order_id: UUID замовлення
        ttn: Номер ТТН (14 цифр для Нової Пошти)
        delivery_provider: Служба доставки (за замовчуванням nova_poshta)

    Returns:
        Результат з посиланням на трекінг
    """
    # Валідація ТТН Нової Пошти
    if delivery_provider == 'nova_poshta' and not (len(ttn) == 14 and ttn.isdigit()):
        return f'❌ Невірний формат ТТН НП. Має бути 14 цифр, отримано: {ttn}'

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Додаємо ТТН через створення відправлення
        payload = {'provider': delivery_provider, 'number': ttn}
        url = f'{BASE_URL}/v3/oms/orders/{order_id}/shipping/{delivery_provider}'
        r = await client.post(url, json=payload, headers=HEADERS)

        if r.status_code not in (200, 201, 202, 204):
            # Fallback: спробуємо через v1 endpoint
            r = await client.patch(
                f'{BASE_URL}/v1/oms/orders/{order_id}/shipment-number',
                json={'provider': delivery_provider, 'number': ttn},
                headers=HEADERS
            )

        if r.status_code in (200, 201, 202, 204):
            # 2. Автоматично змінюємо статус на "sent"
            status_url = f'{BASE_URL}/v2/oms/orders/{order_id}/change-status/to/sent'
            await client.post(status_url, json={'comment': f'ТТН {ttn} додано'}, headers=HEADERS)
            return (f'✅ ТТН {ttn} додано до замовлення {order_id[:8]}...\n'
                   f'Трекінг: https://novaposhta.ua/tracking/?cargo_number={ttn}')

        return f'❌ Помилка додавання ТТН. Код: {r.status_code} | {r.text[:200]}'


@mcp.tool()
async def update_order_client(
    order_id: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> str:
    """
    Оновити дані клієнта в замовленні (ПІБ, телефон, email).

    Args:
        order_id: UUID замовлення
        first_name: Ім'я клієнта
        last_name: Прізвище клієнта
        phone: Телефон (формат: 380661112233)
        email: Email клієнта
    """
    payload = {}
    if first_name: payload['firstName'] = first_name
    if last_name:  payload['lastName']  = last_name
    if phone:      payload['phone']     = phone
    if email:      payload['email']     = email

    if not payload:
        return '❌ Вкажіть хоча б одне поле для оновлення'

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f'{BASE_URL}/v3/oms/orders/{order_id}/client-data',
            json=payload, headers=HEADERS
        )
        if r.status_code in (200, 202, 204):
            return f'✅ Дані клієнта оновлено для замовлення {order_id[:8]}...'
        return f'❌ Помилка. Код: {r.status_code} | {r.text[:200]}'


@mcp.tool()
async def update_order_delivery(
    order_id: str,
    delivery_provider: str,
    settlement_id: Optional[str] = None,
    office_id: Optional[str] = None,
    address: Optional[str] = None,
) -> str:
    """
    Змінити адресу доставки в замовленні.

    Args:
        order_id: UUID замовлення
        delivery_provider: Провайдер (nova_poshta/ukrposhta/meest)
        settlement_id: UUID міста/населеного пункту
        office_id: UUID відділення
        address: Адреса (для кур'єрської доставки)
    """
    payload = {}
    if settlement_id: payload['settlementId'] = settlement_id
    if office_id:     payload['officeId']     = office_id
    if address:       payload['address']      = address

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f'{BASE_URL}/v3/oms/orders/{order_id}/delivery-data/{delivery_provider}',
            json=payload, headers=HEADERS
        )
        if r.status_code in (200, 202, 204):
            return f'✅ Адресу доставки оновлено для замовлення {order_id[:8]}...'
        return f'❌ Помилка. Код: {r.status_code} | {r.text[:200]}'


@mcp.tool()
async def add_order_comment(order_id: str, comment: str) -> str:
    """
    Додати коментар до замовлення Єпіцентру.

    Args:
        order_id: UUID замовлення
        comment: Текст коментаря

    Returns:
        Результат операції
    """
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f'{BASE_URL}/v2/oms/orders/{order_id}/comments',
            json={'text': comment}, headers=HEADERS
        )
        if r.status_code in (200, 201, 202):
            return f'✅ Коментар додано до замовлення {order_id[:8]}...'
        return f'❌ Помилка. Код: {r.status_code} | {r.text[:200]}'


@mcp.tool()
async def get_cancel_reasons() -> str:
    """
    Отримати список причин скасування замовлення клієнтом.
    Використовується при скасуванні замовлення.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f'{BASE_URL}/v2/oms/order-cancel-reasons/customer',
            headers=HEADERS
        )
        if r.status_code != 200:
            return f'❌ Помилка. Код: {r.status_code}'

        reasons = r.json().get('items', [])
        lines = ['📋 Причини скасування:']
        for reason in reasons:
            lines.append(f"  {reason.get('code','?')} — {reason.get('title','?')}")
        return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════════════
# ДОМЕН 2: ДОСТАВКА (DELIVERY)
# ══════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def find_delivery_office(
    provider: Literal['nova_poshta', 'ukrposhta', 'meest', 'justin'],
    city_name: str,
    office_number: Optional[str] = None,
) -> str:
    """
    Знайти відділення служби доставки за назвою міста.
    Використовується для валідації адреси клієнта.

    Args:
        provider: Служба доставки
        city_name: Назва міста (наприклад: Рівне, Київ)
        office_number: Номер відділення для пошуку (опційно)

    Returns:
        Список відділень з ID для оновлення замовлення
    """
    # Учасник для НП = np, для інших — аналогічно
    participant_map = {
        'nova_poshta': 'np',
        'ukrposhta':   'up',
        'meest':       'meest',
        'justin':      'justin',
    }
    participant = participant_map.get(provider, provider)

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Знаходимо місто
        r = await client.get(
            f'{BASE_URL}/v3/deliveries/providers/{provider}/participants/{participant}/settlements',
            headers=HEADERS,
            params={'search': city_name, 'limit': 5}
        )

        if r.status_code != 200:
            return f'❌ Помилка пошуку міста. Код: {r.status_code}'

        settlements = r.json().get('items', [])
        if not settlements:
            return f'❌ Місто "{city_name}" не знайдено для {provider}'

        settlement = settlements[0]
        settlement_id = settlement.get('id')

        # 2. Отримуємо відділення
        r2 = await client.get(
            f'{BASE_URL}/v3/deliveries/providers/{provider}/participants/{participant}'
            f'/settlements/{settlement_id}/offices',
            headers=HEADERS,
            params={'limit': 20}
        )

        if r2.status_code != 200:
            return f'✅ Місто: {settlement.get("title")} (id: {settlement_id})\n❌ Відділення не знайдено'

        offices = r2.json().get('items', [])
        lines = [f'📍 {provider} | {settlement.get("title")} (settlement_id: {settlement_id})']
        for o in offices[:10]:
            number = o.get('number', o.get('title', '?'))
            if office_number and str(office_number) not in str(number):
                continue
            lines.append(f'  Відд.{number} | {o.get("address","?")} | id:{o.get("id","?")}')

        return '\n'.join(lines)


@mcp.tool()
async def get_delivery_invoice(
    provider: str,
    company_id: str,
    invoice_number: str,
) -> str:
    """
    Отримати інформацію по накладній (ТТН) через Єпіцентр API.

    Args:
        provider: Служба доставки (nova_poshta тощо)
        company_id: UUID компанії
        invoice_number: Номер накладної (ТТН)
    """
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f'{BASE_URL}/v3/deliveries/{provider}/companies/{company_id}/invoice/{invoice_number}',
            headers=HEADERS
        )
        if r.status_code == 200:
            return str(r.json())
        return f'❌ Накладна не знайдена. Код: {r.status_code}'


# ══════════════════════════════════════════════════════════════════════════
# ДОМЕН 3: PIM (КАТАЛОГ ТОВАРІВ)
# ══════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_categories(search: Optional[str] = None, limit: int = 20) -> str:
    """
    Отримати категорії товарів Єпіцентру.

    Args:
        search: Пошук за назвою категорії (наприклад: Воротки)
        limit: Кількість результатів

    Returns:
        Список категорій з ID для використання в XML імпорті
    """
    params = {'limit': limit}
    if search:
        params['search'] = search

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f'{BASE_URL}/v2/pim/categories', headers=HEADERS, params=params)

        if r.status_code != 200:
            return f'❌ Помилка. Код: {r.status_code}'

        items = r.json().get('items', [])
        lines = [f'📁 Категорії Єпіцентру ({len(items)}):']
        for cat in items:
            title = next((t['title'] for t in cat.get('translations', [])
                         if t.get('languageCode') == 'ua'), cat.get('code', '?'))
            lines.append(f'  [{cat.get("code","?")}] {title}')
        return '\n'.join(lines)


@mcp.tool()
async def get_attribute_options(
    attribute_set_code: str,
    attribute_code: str,
    search: Optional[str] = None,
) -> str:
    """
    Отримати доступні значення (valuecodes) для атрибуту товару.
    Використовується для заповнення XML імпорту.

    Args:
        attribute_set_code: Код набору атрибутів (наприклад: 2618)
        attribute_code: Код атрибуту (наприклад: brand, country_of_origin, measure)
        search: Пошук за значенням (наприклад: TOPTUL, Тайвань)

    Returns:
        Список valuecodes для підстановки в XML
    """
    async with httpx.AsyncClient(timeout=30) as client:
        params = {'limit': 100}
        r = await client.get(
            f'{BASE_URL}/v2/pim/attribute-sets/{attribute_set_code}'
            f'/attributes/{attribute_code}/options',
            headers=HEADERS, params=params
        )

        if r.status_code != 200:
            return f'❌ Помилка. Код: {r.status_code}'

        items = r.json().get('items', [])
        if search:
            items = [i for i in items
                    if any(search.lower() in (t.get('value','') or '').lower()
                           for t in i.get('translations', []))]

        lines = [f'🏷️ Значення атрибуту {attribute_code} (набір {attribute_set_code}):']
        for item in items[:20]:
            val = next((t.get('value','') for t in item.get('translations', [])
                       if t.get('languageCode') == 'ua'), '?')
            lines.append(f'  code={item.get("code","?")} | {val}')
        return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════════════
# ЗАПУСК
# ══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import asyncio
    print('[Epicentr MCP] Запуск через stdio...')
    mcp.run(transport='stdio')
