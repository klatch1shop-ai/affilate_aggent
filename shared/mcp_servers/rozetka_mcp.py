"""
shared/mcp_servers/rozetka_mcp.py
===================================
MCP сервер для Rozetka Seller API.

Функції:
- Авторизація та управління токеном
- Читання та управління замовленнями
- Збереження ТТН
- Управління статусами
- Валідація XML перед відправкою

Документація: https://api-seller.rozetka.com.ua/apidoc/

Запуск:
    python3 shared/mcp_servers/rozetka_mcp.py
"""

import os, sys, json, asyncio, time
import requests
from datetime import datetime
from loguru import logger
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../.env'))

ROZETKA_LOGIN = os.getenv('ROZETKA_LOGIN', '')
ROZETKA_PASSWORD = os.getenv('ROZETKA_PASSWORD', '')
ROZETKA_BASE = 'https://api-seller.rozetka.com.ua'

app = Server('rozetka-marketplace-mcp')

# Кеш токена
_token_cache = {'token': None, 'expires_at': 0}


# =============================================
# АВТОРИЗАЦІЯ
# =============================================

def get_rozetka_token() -> str:
    """Отримує або оновлює Bearer токен Розетки (живе 24 години)."""
    now = time.time()
    if _token_cache['token'] and now < _token_cache['expires_at']:
        return _token_cache['token']

    try:
        resp = requests.post(
            f'{ROZETKA_BASE}/sites',
            json={'username': ROZETKA_LOGIN, 'password': ROZETKA_PASSWORD},
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get('content', {}).get('access_token', '')
        if token:
            _token_cache['token'] = token
            _token_cache['expires_at'] = now + 23 * 3600  # 23 години
            logger.success('[ROZETKA MCP] Токен отримано')
        return token
    except Exception as e:
        logger.error(f'[ROZETKA MCP] Помилка авторизації: {e}')
        return ''


def rozetka_get(endpoint: str, params: dict = None) -> dict:
    token = get_rozetka_token()
    if not token:
        return {'error': 'Не вдалось отримати токен авторизації'}
    try:
        resp = requests.get(
            f'{ROZETKA_BASE}/{endpoint.lstrip("/")}',
            headers={'Authorization': f'Bearer {token}'},
            params=params or {},
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {'error': str(e)}


def rozetka_post(endpoint: str, data) -> dict:
    token = get_rozetka_token()
    if not token:
        return {'error': 'Не вдалось отримати токен авторизації'}
    try:
        resp = requests.post(
            f'{ROZETKA_BASE}/{endpoint.lstrip("/")}',
            headers={'Authorization': f'Bearer {token}'},
            json=data,
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {'error': str(e)}


def fmt(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


# =============================================
# СПИСОК ІНСТРУМЕНТІВ
# =============================================

@app.list_tools()
async def list_tools():
    return [

        types.Tool(
            name='rozetka_get_orders',
            description=(
                'Отримати список замовлень з Розетки. '
                'expand=status_available показує доступні статуси для кожного замовлення.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'page': {'type': 'integer', 'default': 1},
                    'per_page': {'type': 'integer', 'default': 20},
                    'status': {
                        'type': 'string',
                        'description': 'Фільтр по статусу замовлення'
                    }
                }
            }
        ),

        types.Tool(
            name='rozetka_get_order',
            description='Отримати деталі замовлення Розетки по ID.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'order_id': {'type': 'integer', 'description': 'ID замовлення'}
                },
                'required': ['order_id']
            }
        ),

        types.Tool(
            name='rozetka_set_order_status',
            description=(
                'Змінити статус замовлення на Розетці. '
                'Обов\'язково вказати ТТН для статусу "sent".'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'order_id': {'type': 'integer'},
                    'status': {
                        'type': 'string',
                        'description': 'Новий статус замовлення'
                    },
                    'ttn': {
                        'type': 'string',
                        'description': 'ТТН Нової Пошти (для статусу sent)'
                    },
                    'cancellation_reason': {
                        'type': 'string',
                        'description': 'Причина скасування'
                    }
                },
                'required': ['order_id', 'status']
            }
        ),

        types.Tool(
            name='rozetka_get_xml_status',
            description=(
                'Перевірити статус XML прайсу на Розетці: '
                'коли останній раз синхронізувався, кількість товарів, помилки.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {}
            }
        ),

        types.Tool(
            name='rozetka_validate_xml',
            description=(
                'Відправити XML на валідатор Розетки для перевірки перед завантаженням. '
                'Повертає список помилок якщо є.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'xml_url': {
                        'type': 'string',
                        'description': 'URL XML файлу (напр. GitHub raw URL)',
                        'default': 'https://raw.githubusercontent.com/klatch1shop-ai/affilate_aggent/main/data/carvol_rozetka.xml'
                    }
                }
            }
        ),

        types.Tool(
            name='rozetka_get_shop_info',
            description='Отримати інформацію про магазин на Розетці: назва, статус, рейтинг.',
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

    if name == 'rozetka_get_orders':
        params = {
            'expand': 'status_available',
            'page': arguments.get('page', 1),
            'per_page': arguments.get('per_page', 20),
        }
        if arguments.get('status'):
            params['status'] = arguments['status']

        data = rozetka_get('orders', params)

        if 'error' in data:
            return [types.TextContent(type='text', text=f'❌ {data["error"]}')]

        orders = data.get('content', {}).get('orders', data.get('content', []))
        if isinstance(orders, dict):
            orders = list(orders.values())

        result = []
        for o in (orders if isinstance(orders, list) else []):
            result.append({
                'id': o.get('id'),
                'status': o.get('status'),
                'date': str(o.get('created', ''))[:10],
                'customer': o.get('user_phone', ''),
                'total': o.get('total_price', o.get('price', '')),
                'items_count': len(o.get('items', [])),
            })

        return [types.TextContent(type='text', text=f'Замовлень: {len(result)}\n\n{fmt(result)}')]

    elif name == 'rozetka_get_order':
        data = rozetka_get(f'orders/{arguments["order_id"]}', {'expand': 'status_available'})

        if 'error' in data:
            return [types.TextContent(type='text', text=f'❌ {data["error"]}')]

        return [types.TextContent(type='text', text=fmt(data.get('content', data)))]

    elif name == 'rozetka_set_order_status':
        payload = {'status': arguments['status']}
        if arguments.get('ttn'):
            payload['declaration_id'] = arguments['ttn']
        if arguments.get('cancellation_reason'):
            payload['cancellation_reason'] = arguments['cancellation_reason']

        data = rozetka_post(f'orders/{arguments["order_id"]}/status', payload)

        if 'error' in data:
            return [types.TextContent(type='text', text=f'❌ {data["error"]}')]

        return [types.TextContent(
            type='text',
            text=f'✅ Статус замовлення #{arguments["order_id"]} змінено на "{arguments["status"]}"'
        )]

    elif name == 'rozetka_get_xml_status':
        data = rozetka_get('prices')

        if 'error' in data:
            return [types.TextContent(type='text', text=f'❌ {data["error"]}')]

        return [types.TextContent(type='text', text=fmt(data.get('content', data)))]

    elif name == 'rozetka_validate_xml':
        xml_url = arguments.get('xml_url',
            'https://raw.githubusercontent.com/klatch1shop-ai/affilate_aggent/main/data/carvol_rozetka.xml')

        try:
            resp = requests.post(
                'https://seller.rozetka.com.ua/gomer/pricevalidate/check/index',
                data={'url': xml_url},
                timeout=60
            )
            return [types.TextContent(type='text', text=f'Відповідь валідатора:\n{resp.text[:2000]}')]
        except Exception as e:
            return [types.TextContent(type='text', text=f'❌ Помилка валідації: {e}')]

    elif name == 'rozetka_get_shop_info':
        data = rozetka_get('sites/current')

        if 'error' in data:
            return [types.TextContent(type='text', text=f'❌ {data["error"]}')]

        return [types.TextContent(type='text', text=fmt(data.get('content', data)))]

    return [types.TextContent(type='text', text=f'❌ Невідомий інструмент: {name}')]


async def main():
    logger.info('[ROZETKA MCP] Запуск...')
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())

if __name__ == '__main__':
    asyncio.run(main())
