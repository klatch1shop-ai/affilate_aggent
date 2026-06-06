"""
shared/mcp_servers/prom_mcp.py
================================
MCP сервер для Prom.ua Seller API.

Дозволяє Claude та агентам напряму:
- читати та керувати замовленнями
- оновлювати ціни та наявність товарів
- відповідати на повідомлення покупців
- зберігати ТТН Нової Пошти
- отримувати статистику магазину

Запуск як stdio MCP:
    python3 shared/mcp_servers/prom_mcp.py

Підключення в claude_desktop_config.json:
    {
        "mcpServers": {
            "prom": {
                "command": "/home/tek/agent-system/venv/bin/python3",
                "args": ["/home/tek/agent-system/shared/mcp_servers/prom_mcp.py"]
            }
        }
    }
"""

import os, sys, json, asyncio, time
import requests
from datetime import datetime, timezone, timedelta
from loguru import logger
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../.env'))

# =============================================
# КОНФІГУРАЦІЯ
# =============================================

PROM_TOKEN = os.getenv('PROM_API_TOKEN', '')
PROM_BASE = 'https://my.prom.ua/api/v1'
PROM_HEADERS = {'Authorization': f'Bearer {PROM_TOKEN}'}

app = Server('prom-marketplace-mcp')


# =============================================
# УТИЛІТИ
# =============================================

def prom_get(endpoint: str, params: dict = None) -> dict:
    """GET запит до Prom API."""
    try:
        resp = requests.get(
            f'{PROM_BASE}/{endpoint.lstrip("/")}',
            headers=PROM_HEADERS,
            params=params or {},
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {'error': str(e)}


def prom_post(endpoint: str, data) -> dict:
    """POST запит до Prom API."""
    try:
        resp = requests.post(
            f'{PROM_BASE}/{endpoint.lstrip("/")}',
            headers=PROM_HEADERS,
            json=data,
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {'error': str(e)}


def fmt(obj) -> str:
    """Серіалізує об'єкт в JSON рядок."""
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


# =============================================
# СПИСОК ІНСТРУМЕНТІВ
# =============================================

@app.list_tools()
async def list_tools():
    return [

        # ── ЗАМОВЛЕННЯ ──────────────────────────────────────────────
        types.Tool(
            name='prom_get_orders',
            description=(
                'Отримати список замовлень з Prom.ua. '
                'Можна фільтрувати по статусу та кількості. '
                'Статуси: pending (нові), accepted (прийняті), '
                'delivered (доставлені), cancelled (скасовані), declined (відхилені).'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'status': {
                        'type': 'string',
                        'description': 'Фільтр по статусу: pending/accepted/delivered/cancelled/declined',
                        'enum': ['pending', 'paid', 'accepted', 'delivered', 'cancelled', 'declined']
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Кількість замовлень (max 100)',
                        'default': 20
                    },
                    'date_from': {
                        'type': 'string',
                        'description': 'Фільтр від дати (ISO формат, напр. 2026-05-01)'
                    }
                }
            }
        ),

        types.Tool(
            name='prom_get_order',
            description='Отримати деталі конкретного замовлення по ID.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'order_id': {
                        'type': 'integer',
                        'description': 'ID замовлення Prom'
                    }
                },
                'required': ['order_id']
            }
        ),

        types.Tool(
            name='prom_set_order_status',
            description=(
                'Змінити статус замовлення. '
                'Типовий flow: pending → accepted → delivered. '
                'Можна скасувати: cancelled або declined.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'order_ids': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'Список ID замовлень'
                    },
                    'status': {
                        'type': 'string',
                        'description': 'Новий статус',
                        'enum': ['accepted', 'delivered', 'cancelled', 'declined']
                    },
                    'cancellation_reason': {
                        'type': 'string',
                        'description': 'Причина скасування (якщо status=cancelled/declined)'
                    }
                },
                'required': ['order_ids', 'status']
            }
        ),

        types.Tool(
            name='prom_save_ttn',
            description=(
                'Зберегти ТТН (номер накладної Нової Пошти) до замовлення. '
                'Після збереження покупець отримує сповіщення з трекінгом.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'order_id': {
                        'type': 'integer',
                        'description': 'ID замовлення'
                    },
                    'ttn': {
                        'type': 'string',
                        'description': 'Номер ТТН Нової Пошти (14 цифр)'
                    },
                    'delivery_type': {
                        'type': 'string',
                        'description': 'Тип доставки',
                        'default': 'nova_poshta'
                    }
                },
                'required': ['order_id', 'ttn']
            }
        ),

        # ── ТОВАРИ ──────────────────────────────────────────────────
        types.Tool(
            name='prom_get_products',
            description=(
                'Отримати список товарів магазину з Prom.ua. '
                'Повертає SKU, ціну, наявність, ID товару.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'limit': {
                        'type': 'integer',
                        'description': 'Кількість товарів (max 100)',
                        'default': 50
                    },
                    'last_id': {
                        'type': 'integer',
                        'description': 'ID останнього товару для пагінації'
                    },
                    'sku': {
                        'type': 'string',
                        'description': 'Фільтр по SKU (точний збіг)'
                    }
                }
            }
        ),

        types.Tool(
            name='prom_update_prices',
            description=(
                'Масове оновлення цін товарів на Prom.ua. '
                'Передається список об\'єктів {id, price}. '
                'Максимум 100 товарів за раз.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'updates': {
                        'type': 'array',
                        'description': 'Список оновлень [{id: prom_id, price: нова_ціна}]',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'integer'},
                                'price': {'type': 'number'}
                            },
                            'required': ['id', 'price']
                        }
                    }
                },
                'required': ['updates']
            }
        ),

        types.Tool(
            name='prom_update_presence',
            description=(
                'Змінити наявність товарів на Prom.ua. '
                'available = в наявності, not_available = немає.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'updates': {
                        'type': 'array',
                        'description': 'Список [{id: prom_id, presence: "available"/"not_available"}]',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'integer'},
                                'presence': {
                                    'type': 'string',
                                    'enum': ['available', 'not_available', 'order']
                                }
                            },
                            'required': ['id', 'presence']
                        }
                    }
                },
                'required': ['updates']
            }
        ),

        # ── ПОВІДОМЛЕННЯ ─────────────────────────────────────────────
        types.Tool(
            name='prom_get_messages',
            description='Отримати список повідомлень від покупців.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'limit': {
                        'type': 'integer',
                        'default': 20,
                        'description': 'Кількість повідомлень'
                    },
                    'only_unread': {
                        'type': 'boolean',
                        'default': True,
                        'description': 'Тільки непрочитані'
                    }
                }
            }
        ),

        types.Tool(
            name='prom_reply_message',
            description='Відповісти покупцю на повідомлення в Prom.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'thread_id': {
                        'type': 'integer',
                        'description': 'ID гілки повідомлень'
                    },
                    'text': {
                        'type': 'string',
                        'description': 'Текст відповіді'
                    }
                },
                'required': ['thread_id', 'text']
            }
        ),

        # ── АНАЛІТИКА ────────────────────────────────────────────────
        types.Tool(
            name='prom_get_shop_stats',
            description=(
                'Отримати статистику магазину: '
                'кількість замовлень за сьогодні/тиждень/місяць, '
                'суму продажів, нові/необроблені замовлення.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {}
            }
        ),

    ]


# =============================================
# ОБРОБКА ВИКЛИКІВ
# =============================================

@app.call_tool()
async def call_tool(name: str, arguments: dict):

    # ── prom_get_orders ──────────────────────────────────────────────
    if name == 'prom_get_orders':
        params = {'limit': arguments.get('limit', 20)}
        status = arguments.get('status')
        if status:
            params['status'] = status

        data = prom_get('orders/list', params)

        if 'error' in data:
            return [types.TextContent(type='text', text=f'❌ Помилка: {data["error"]}')]

        orders = data.get('orders', [])

        # Фільтр по даті якщо вказано
        date_from = arguments.get('date_from')
        if date_from and orders:
            try:
                cutoff = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
                orders = [o for o in orders
                         if datetime.fromisoformat(
                             o.get('date_created', '').replace('Z', '+00:00')
                         ) >= cutoff]
            except:
                pass

        # Форматуємо для зручного читання
        result = []
        for o in orders:
            delivery = o.get('delivery_address') or {}
            if isinstance(delivery, dict):
                city = (delivery.get('city') or {}).get('name', '')
                wh = (delivery.get('warehouse') or {}).get('description', '')
                delivery_str = f'{city} {wh}'.strip()
            else:
                delivery_str = str(delivery)

            payment = o.get('payment_option') or {}
            payment_name = payment.get('name', '') if isinstance(payment, dict) else str(payment)

            result.append({
                'id': o.get('id'),
                'status': o.get('status'),
                'date': o.get('date_created', '')[:10],
                'customer': f"{o.get('client_last_name','')} {o.get('client_first_name','')}".strip(),
                'phone': o.get('phone') or o.get('client_phone', ''),
                'price': o.get('price'),
                'payment': payment_name,
                'delivery': delivery_str,
                'products_count': len(o.get('products', [])),
                'products': [
                    {'sku': p.get('sku'), 'name': p.get('name', '')[:50], 'qty': p.get('quantity')}
                    for p in o.get('products', [])
                ]
            })

        summary = f'Знайдено замовлень: {len(result)}'
        if status:
            summary += f' зі статусом "{status}"'

        return [types.TextContent(type='text', text=f'{summary}\n\n{fmt(result)}')]

    # ── prom_get_order ───────────────────────────────────────────────
    elif name == 'prom_get_order':
        order_id = arguments['order_id']
        data = prom_get(f'orders/{order_id}')

        if 'error' in data:
            return [types.TextContent(type='text', text=f'❌ Помилка: {data["error"]}')]

        return [types.TextContent(type='text', text=fmt(data.get('order', data)))]

    # ── prom_set_order_status ────────────────────────────────────────
    elif name == 'prom_set_order_status':
        payload = {
            'ids': arguments['order_ids'],
            'status': arguments['status'],
        }
        if arguments.get('cancellation_reason'):
            payload['cancellation_reason'] = arguments['cancellation_reason']

        data = prom_post('orders/set_status', payload)

        if 'error' in data:
            return [types.TextContent(type='text', text=f'❌ Помилка: {data["error"]}')]

        return [types.TextContent(
            type='text',
            text=f'✅ Статус змінено на "{arguments["status"]}" для замовлень: {arguments["order_ids"]}'
        )]

    # ── prom_save_ttn ────────────────────────────────────────────────
    elif name == 'prom_save_ttn':
        payload = {
            'order_id': arguments['order_id'],
            'declaration_id': arguments['ttn'],
            'delivery_type': arguments.get('delivery_type', 'nova_poshta'),
        }
        data = prom_post('delivery/save_declaration_id', payload)

        if 'error' in data:
            return [types.TextContent(type='text', text=f'❌ Помилка: {data["error"]}')]

        return [types.TextContent(
            type='text',
            text=f'✅ ТТН {arguments["ttn"]} збережено до замовлення #{arguments["order_id"]}'
        )]

    # ── prom_get_products ────────────────────────────────────────────
    elif name == 'prom_get_products':
        params = {'limit': arguments.get('limit', 50)}
        if arguments.get('last_id'):
            params['last_id'] = arguments['last_id']

        data = prom_get('products/list', params)

        if 'error' in data:
            return [types.TextContent(type='text', text=f'❌ Помилка: {data["error"]}')]

        products = data.get('products', [])

        # Фільтр по SKU
        sku_filter = arguments.get('sku', '').strip().upper()
        if sku_filter:
            products = [p for p in products if (p.get('sku') or '').upper() == sku_filter]

        result = [
            {
                'id': p.get('id'),
                'sku': p.get('sku'),
                'name': p.get('name', '')[:60],
                'price': p.get('price'),
                'presence': p.get('presence'),
                'group': (p.get('group') or {}).get('name', ''),
                'category': (p.get('category') or {}).get('caption', ''),
            }
            for p in products
        ]

        return [types.TextContent(
            type='text',
            text=f'Товарів: {len(result)}\n\n{fmt(result)}'
        )]

    # ── prom_update_prices ───────────────────────────────────────────
    elif name == 'prom_update_prices':
        updates = arguments.get('updates', [])
        if not updates:
            return [types.TextContent(type='text', text='❌ Немає даних для оновлення')]

        # Батчами по 100
        total_updated = 0
        errors = []

        for i in range(0, len(updates), 100):
            batch = updates[i:i+100]
            data = prom_post('products/edit', batch)

            if 'error' in data:
                errors.append(f'Батч {i//100+1}: {data["error"]}')
            else:
                processed = data.get('processed_ids', [])
                total_updated += len(processed)

            if i + 100 < len(updates):
                time.sleep(0.5)

        msg = f'✅ Оновлено цін: {total_updated} з {len(updates)}'
        if errors:
            msg += f'\n❌ Помилки: {"; ".join(errors)}'

        return [types.TextContent(type='text', text=msg)]

    # ── prom_update_presence ─────────────────────────────────────────
    elif name == 'prom_update_presence':
        updates = arguments.get('updates', [])
        if not updates:
            return [types.TextContent(type='text', text='❌ Немає даних для оновлення')]

        total_updated = 0
        for i in range(0, len(updates), 100):
            batch = updates[i:i+100]
            data = prom_post('products/edit', batch)
            if 'processed_ids' in data:
                total_updated += len(data['processed_ids'])
            if i + 100 < len(updates):
                time.sleep(0.5)

        return [types.TextContent(
            type='text',
            text=f'✅ Оновлено наявність: {total_updated} товарів'
        )]

    # ── prom_get_messages ────────────────────────────────────────────
    elif name == 'prom_get_messages':
        params = {'limit': arguments.get('limit', 20)}
        data = prom_get('messages/list', params)

        if 'error' in data:
            return [types.TextContent(type='text', text=f'❌ Помилка: {data["error"]}')]

        messages = data.get('messages', [])

        if arguments.get('only_unread', True):
            messages = [m for m in messages if not m.get('is_read', False)]

        result = [
            {
                'thread_id': m.get('thread_id'),
                'from': m.get('author', {}).get('name', '') if isinstance(m.get('author'), dict) else '',
                'text': m.get('text', '')[:200],
                'date': m.get('created_at', '')[:16],
                'is_read': m.get('is_read', False),
            }
            for m in messages
        ]

        return [types.TextContent(
            type='text',
            text=f'Повідомлень: {len(result)}\n\n{fmt(result)}'
        )]

    # ── prom_reply_message ───────────────────────────────────────────
    elif name == 'prom_reply_message':
        payload = {
            'thread_id': arguments['thread_id'],
            'text': arguments['text'],
        }
        data = prom_post('messages/reply', payload)

        if 'error' in data:
            return [types.TextContent(type='text', text=f'❌ Помилка: {data["error"]}')]

        return [types.TextContent(
            type='text',
            text=f'✅ Відповідь надіслана в гілку #{arguments["thread_id"]}'
        )]

    # ── prom_get_shop_stats ──────────────────────────────────────────
    elif name == 'prom_get_shop_stats':
        # Отримуємо замовлення за останні 30 днів
        today = datetime.now(timezone.utc)
        month_ago = (today - timedelta(days=30)).isoformat()

        data_all = prom_get('orders/list', {'limit': 100})
        orders = data_all.get('orders', [])

        # Статистика
        stats = {
            'total_orders': len(orders),
            'pending': 0,
            'accepted': 0,
            'delivered': 0,
            'cancelled': 0,
            'total_revenue': 0.0,
            'today_orders': 0,
            'week_orders': 0,
        }

        today_date = today.date()
        week_ago = today - timedelta(days=7)

        for o in orders:
            status = o.get('status', '')
            stats[status] = stats.get(status, 0) + 1

            try:
                price = float(str(o.get('price', 0)).replace(' грн', '').replace(',', '.').split()[0])
                if status not in ('cancelled', 'declined'):
                    stats['total_revenue'] += price
            except:
                pass

            try:
                order_date = datetime.fromisoformat(o.get('date_created', '').replace('Z', '+00:00'))
                if order_date.date() == today_date:
                    stats['today_orders'] += 1
                if order_date >= week_ago:
                    stats['week_orders'] += 1
            except:
                pass

        stats['total_revenue'] = round(stats['total_revenue'], 2)

        return [types.TextContent(type='text', text=fmt(stats))]

    return [types.TextContent(type='text', text=f'❌ Невідомий інструмент: {name}')]


# =============================================
# ЗАПУСК
# =============================================

async def main():
    logger.info('[PROM MCP] Запуск...')
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == '__main__':
    asyncio.run(main())
