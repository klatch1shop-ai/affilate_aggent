"""
shared/mcp_servers/epicentr_mcp.py
=====================================
MCP сервер для Єпіцентру + внутрішня БД агентної системи.

Єпіцентр:
- Немає офіційного Seller API
- Управління через адмін-панель: admin.epicentrm.com.ua
- Активація товарів тільки через XLS імпорт

Тому цей сервер надає:
1. Доступ до внутрішньої БД (my_products, price_history, orders)
2. Генерацію XLS для імпорту в Єпіцентр
3. Статистику та аналітику по товарах
4. Управління класифікацією категорій

Запуск:
    python3 shared/mcp_servers/epicentr_mcp.py
"""

import os, sys, json, asyncio
import requests
from datetime import date, datetime, timedelta
from loguru import logger
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../.env'))
from shared.utils.db import get_connection

app = Server('epicentr-db-mcp')


def fmt(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def db_query(sql: str, params=None) -> list:
    """Виконує SELECT запит і повертає список dict."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql, params or ())
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def db_execute(sql: str, params=None) -> int:
    """Виконує INSERT/UPDATE/DELETE і повертає кількість рядків."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql, params or ())
    affected = cur.rowcount
    conn.commit()
    cur.close(); conn.close()
    return affected


# =============================================
# СПИСОК ІНСТРУМЕНТІВ
# =============================================

@app.list_tools()
async def list_tools():
    return [

        # ── ТОВАРИ (my_products) ─────────────────────────────────────
        types.Tool(
            name='db_get_products',
            description=(
                'Отримати товари з БД my_products. '
                'Можна фільтрувати по категорії Єпіцентру, наявності ціни, SKU.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'limit': {'type': 'integer', 'default': 20},
                    'has_epicentr_category': {
                        'type': 'boolean',
                        'description': 'True = тільки з категорією, False = без категорії'
                    },
                    'has_price': {
                        'type': 'boolean',
                        'description': 'Тільки товари з ціною'
                    },
                    'sku': {'type': 'string', 'description': 'Пошук по SKU'},
                    'category': {'type': 'string', 'description': 'Фільтр по назві категорії Єпіцентру'}
                }
            }
        ),

        types.Tool(
            name='db_get_products_stats',
            description=(
                'Статистика товарів в БД: '
                'загальна кількість, з ціною, з категорією Єпіцентру, '
                'без категорії (чернетки), недоступні у фіді.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {}
            }
        ),

        types.Tool(
            name='db_classify_product',
            description=(
                'Встановити категорію Єпіцентру для товару вручну. '
                'Використовується для корекції результатів AI класифікатора.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'sku': {'type': 'string', 'description': 'SKU товару'},
                    'epicentr_category_id': {'type': 'integer', 'description': 'ID категорії з таблиці epicentr_categories'},
                    'epicentr_category_name': {'type': 'string', 'description': 'Назва категорії'}
                },
                'required': ['sku', 'epicentr_category_name']
            }
        ),

        # ── ЦІНИ (price_history) ─────────────────────────────────────
        types.Tool(
            name='db_get_price_history',
            description=(
                'Отримати історію цін товару. '
                'Показує як змінювались ціни постачальника і наші ціни по днях.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'sku': {'type': 'string', 'description': 'SKU товару'},
                    'days': {'type': 'integer', 'default': 30, 'description': 'За скільки днів'},
                    'only_changes': {
                        'type': 'boolean',
                        'default': True,
                        'description': 'Тільки дні зі змінами цін'
                    }
                },
                'required': ['sku']
            }
        ),

        types.Tool(
            name='db_get_price_alerts',
            description=(
                'Отримати алерти цін за останні N днів. '
                'Показує товари зі значними змінами цін або зникненням з фіду.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'days': {'type': 'integer', 'default': 7},
                    'limit': {'type': 'integer', 'default': 50},
                    'min_change_pct': {
                        'type': 'number',
                        'default': 20.0,
                        'description': 'Мінімальний % зміни для включення в результат'
                    }
                }
            }
        ),

        types.Tool(
            name='db_get_weekly_price_report',
            description=(
                'Тижневий звіт по цінах: '
                'скільки товарів подорожчало/подешевшало, '
                'середня зміна по категоріях, топ змін.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {}
            }
        ),

        # ── ЗАМОВЛЕННЯ (orders) ──────────────────────────────────────
        types.Tool(
            name='db_get_orders',
            description=(
                'Отримати замовлення з внутрішньої БД. '
                'Тут зберігаються всі замовлення з Prom з деталями.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'limit': {'type': 'integer', 'default': 20},
                    'status': {'type': 'string'},
                    'days': {'type': 'integer', 'default': 30, 'description': 'За останні N днів'}
                }
            }
        ),

        types.Tool(
            name='db_get_orders_stats',
            description=(
                'Статистика замовлень: '
                'сьогодні, цього тижня, місяця. '
                'Кількість і суми по статусах.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {}
            }
        ),

        types.Tool(
            name='db_update_ttn',
            description='Внести ТТН до замовлення в БД.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'prom_order_id': {'type': 'integer'},
                    'ttn': {'type': 'string', 'description': 'Номер ТТН'}
                },
                'required': ['prom_order_id', 'ttn']
            }
        ),

        # ── ЄПІЦЕНТР КАТЕГОРІЇ ───────────────────────────────────────
        types.Tool(
            name='db_get_epicentr_categories',
            description=(
                'Отримати категорії Єпіцентру з БД. '
                'Можна шукати по назві для визначення правильної категорії.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'search': {'type': 'string', 'description': 'Пошук по назві категорії'},
                    'limit': {'type': 'integer', 'default': 20}
                }
            }
        ),

        # ── CPA СТАВКИ ───────────────────────────────────────────────
        types.Tool(
            name='db_get_cpa_rates',
            description=(
                'Отримати CPA ставки маркетплейсів. '
                'marketplace: prom / epicentr / rozetka'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'marketplace': {
                        'type': 'string',
                        'enum': ['prom', 'epicentr', 'rozetka'],
                        'default': 'prom'
                    },
                    'search': {'type': 'string', 'description': 'Пошук по назві категорії'}
                }
            }
        ),

        # ── АНАЛІТИКА ────────────────────────────────────────────────
        types.Tool(
            name='db_get_unavailable_products',
            description=(
                'Отримати товари яких немає у фіді TOPTUL більше N днів. '
                'Допомагає виявити товари які треба деактивувати на маркетплейсах.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'days': {
                        'type': 'integer',
                        'default': 3,
                        'description': 'Мінімум днів відсутності у фіді'
                    },
                    'limit': {'type': 'integer', 'default': 50}
                }
            }
        ),

        types.Tool(
            name='db_run_query',
            description=(
                'Виконати довільний SELECT SQL запит до БД агентної системи. '
                'ТІЛЬКИ читання — INSERT/UPDATE/DELETE заблоковано для безпеки.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'sql': {
                        'type': 'string',
                        'description': 'SQL SELECT запит'
                    }
                },
                'required': ['sql']
            }
        ),

    ]


# =============================================
# ОБРОБКА ВИКЛИКІВ
# =============================================

@app.call_tool()
async def call_tool(name: str, arguments: dict):

    # ── db_get_products ──────────────────────────────────────────────
    if name == 'db_get_products':
        conditions = []
        params = []

        if arguments.get('has_price') is True:
            conditions.append('price_our > 0')
        elif arguments.get('has_price') is False:
            conditions.append('(price_our IS NULL OR price_our = 0)')

        if arguments.get('has_epicentr_category') is True:
            conditions.append('epicentr_category_id IS NOT NULL')
        elif arguments.get('has_epicentr_category') is False:
            conditions.append('epicentr_category_id IS NULL')

        if arguments.get('sku'):
            conditions.append('sku ILIKE %s')
            params.append(f'%{arguments["sku"]}%')

        if arguments.get('category'):
            conditions.append('epicentr_category_name ILIKE %s')
            params.append(f'%{arguments["category"]}%')

        where = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
        limit = arguments.get('limit', 20)
        params.append(limit)

        rows = db_query(
            f'SELECT sku, name_uk, price_supplier, price_our, '
            f'epicentr_category_name, epicentr_confidence, prom_category_name '
            f'FROM my_products {where} ORDER BY sku LIMIT %s',
            params
        )
        return [types.TextContent(type='text', text=f'Знайдено: {len(rows)}\n\n{fmt(rows)}')]

    # ── db_get_products_stats ────────────────────────────────────────
    elif name == 'db_get_products_stats':
        rows = db_query('''
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN price_our > 0 THEN 1 END) as with_price,
                COUNT(CASE WHEN epicentr_category_id IS NOT NULL THEN 1 END) as with_epicentr_cat,
                COUNT(CASE WHEN epicentr_category_id IS NULL AND price_our > 0 THEN 1 END) as drafts_no_category,
                COUNT(CASE WHEN prom_category_name IS NOT NULL THEN 1 END) as with_prom_cat,
                COUNT(CASE WHEN prom_group_name IS NOT NULL THEN 1 END) as with_prom_group
            FROM my_products
        ''')

        # Статистика по confidence
        conf_rows = db_query('''
            SELECT epicentr_confidence, COUNT(*) as cnt
            FROM my_products
            WHERE epicentr_confidence IS NOT NULL
            GROUP BY epicentr_confidence
            ORDER BY cnt DESC
        ''')

        result = {
            'summary': dict(rows[0]) if rows else {},
            'epicentr_confidence': {r['epicentr_confidence']: r['cnt'] for r in conf_rows}
        }
        return [types.TextContent(type='text', text=fmt(result))]

    # ── db_classify_product ──────────────────────────────────────────
    elif name == 'db_classify_product':
        affected = db_execute(
            '''UPDATE my_products SET
                epicentr_category_id = %s,
                epicentr_category_name = %s,
                epicentr_confidence = 'manual'
            WHERE sku = %s''',
            (
                arguments.get('epicentr_category_id'),
                arguments['epicentr_category_name'],
                arguments['sku']
            )
        )
        if affected:
            return [types.TextContent(
                type='text',
                text=f'✅ SKU {arguments["sku"]} → категорія "{arguments["epicentr_category_name"]}"'
            )]
        return [types.TextContent(type='text', text=f'❌ SKU {arguments["sku"]} не знайдено в БД')]

    # ── db_get_price_history ─────────────────────────────────────────
    elif name == 'db_get_price_history':
        sku = arguments['sku'].upper()
        days = arguments.get('days', 30)
        only_changes = arguments.get('only_changes', True)

        conditions = ['sku = %s', 'date >= %s']
        params = [sku, date.today() - timedelta(days=days)]

        if only_changes:
            conditions.append('is_change = TRUE')

        rows = db_query(
            f'SELECT date, feed_price, our_price, feed_diff_pct, our_diff_pct, '
            f'cpa_rate, available, stock, is_alert, alert_reason '
            f'FROM price_history WHERE {" AND ".join(conditions)} ORDER BY date DESC',
            params
        )
        return [types.TextContent(
            type='text',
            text=f'Історія цін {sku} за {days} днів ({len(rows)} записів):\n\n{fmt(rows)}'
        )]

    # ── db_get_price_alerts ──────────────────────────────────────────
    elif name == 'db_get_price_alerts':
        days = arguments.get('days', 7)
        limit = arguments.get('limit', 50)
        min_pct = arguments.get('min_change_pct', 20.0)

        rows = db_query(
            '''SELECT sku, date, feed_price, our_price, prev_our_price,
                      our_diff_pct, available, stock, alert_reason
               FROM price_history
               WHERE is_alert = TRUE
                 AND date >= %s
                 AND ABS(our_diff_pct) >= %s
               ORDER BY ABS(our_diff_pct) DESC
               LIMIT %s''',
            (date.today() - timedelta(days=days), min_pct, limit)
        )
        return [types.TextContent(
            type='text',
            text=f'Алерти за {days} днів (зміна >{min_pct}%): {len(rows)}\n\n{fmt(rows)}'
        )]

    # ── db_get_weekly_price_report ───────────────────────────────────
    elif name == 'db_get_weekly_price_report':
        week_ago = date.today() - timedelta(days=7)

        # Загальна статистика
        summary = db_query(
            '''SELECT
                COUNT(*) FILTER (WHERE our_diff_pct > 1)  as price_up,
                COUNT(*) FILTER (WHERE our_diff_pct < -1) as price_down,
                COUNT(*) FILTER (WHERE is_alert = TRUE)   as alerts,
                COUNT(*) FILTER (WHERE available = FALSE) as unavailable,
                ROUND(AVG(ABS(our_diff_pct)) FILTER (WHERE is_change AND ABS(our_diff_pct) > 0), 2) as avg_change_pct
               FROM price_history
               WHERE date >= %s''',
            (week_ago,)
        )

        # Топ подорожчань
        top_up = db_query(
            '''SELECT sku, MIN(prev_our_price) as was, MAX(our_price) as now,
                      ROUND(MAX(our_diff_pct), 1) as pct
               FROM price_history
               WHERE date >= %s AND our_diff_pct > 1
               GROUP BY sku ORDER BY pct DESC LIMIT 10''',
            (week_ago,)
        )

        # Топ здешевлень
        top_down = db_query(
            '''SELECT sku, MAX(prev_our_price) as was, MIN(our_price) as now,
                      ROUND(MIN(our_diff_pct), 1) as pct
               FROM price_history
               WHERE date >= %s AND our_diff_pct < -1
               GROUP BY sku ORDER BY pct ASC LIMIT 10''',
            (week_ago,)
        )

        result = {
            'period': f'{week_ago} — {date.today()}',
            'summary': dict(summary[0]) if summary else {},
            'top_price_up': top_up,
            'top_price_down': top_down,
        }
        return [types.TextContent(type='text', text=fmt(result))]

    # ── db_get_orders ────────────────────────────────────────────────
    elif name == 'db_get_orders':
        conditions = ['created_at >= %s']
        params = [datetime.now() - timedelta(days=arguments.get('days', 30))]

        if arguments.get('status'):
            conditions.append('status = %s')
            params.append(arguments['status'])

        params.append(arguments.get('limit', 20))

        rows = db_query(
            f'SELECT prom_order_id, status, customer_name, customer_phone, '
            f'total_price, supplier_email_sent, ttn, created_at '
            f'FROM orders WHERE {" AND ".join(conditions)} '
            f'ORDER BY created_at DESC LIMIT %s',
            params
        )
        return [types.TextContent(type='text', text=f'Замовлень: {len(rows)}\n\n{fmt(rows)}')]

    # ── db_get_orders_stats ──────────────────────────────────────────
    elif name == 'db_get_orders_stats':
        rows = db_query('''
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN created_at >= NOW() - INTERVAL '1 day' THEN 1 END) as today,
                COUNT(CASE WHEN created_at >= NOW() - INTERVAL '7 days' THEN 1 END) as week,
                COUNT(CASE WHEN created_at >= NOW() - INTERVAL '30 days' THEN 1 END) as month,
                COUNT(CASE WHEN status = 'confirmed' THEN 1 END) as confirmed,
                COUNT(CASE WHEN status = 'check_needed' THEN 1 END) as need_check,
                COUNT(CASE WHEN ttn IS NULL OR ttn = '' THEN 1 END) as without_ttn,
                ROUND(SUM(total_price) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days'), 2) as month_revenue
            FROM orders
        ''')
        return [types.TextContent(type='text', text=fmt(dict(rows[0]) if rows else {}))]

    # ── db_update_ttn ────────────────────────────────────────────────
    elif name == 'db_update_ttn':
        affected = db_execute(
            'UPDATE orders SET ttn=%s, updated_at=NOW() WHERE prom_order_id=%s',
            (arguments['ttn'], arguments['prom_order_id'])
        )
        if affected:
            return [types.TextContent(
                type='text',
                text=f'✅ ТТН {arguments["ttn"]} збережено для замовлення #{arguments["prom_order_id"]}'
            )]
        return [types.TextContent(type='text', text=f'❌ Замовлення #{arguments["prom_order_id"]} не знайдено')]

    # ── db_get_epicentr_categories ───────────────────────────────────
    elif name == 'db_get_epicentr_categories':
        params = []
        where = ''
        if arguments.get('search'):
            where = 'WHERE final_category ILIKE %s'
            params.append(f'%{arguments["search"]}%')
        params.append(arguments.get('limit', 20))

        rows = db_query(
            f'SELECT id, level1, level2, level3, final_category '
            f'FROM epicentr_categories {where} '
            f'ORDER BY final_category LIMIT %s',
            params
        )
        return [types.TextContent(type='text', text=f'Категорій: {len(rows)}\n\n{fmt(rows)}')]

    # ── db_get_cpa_rates ─────────────────────────────────────────────
    elif name == 'db_get_cpa_rates':
        mp = arguments.get('marketplace', 'prom')
        search = arguments.get('search', '')

        table_map = {
            'prom': 'prom_cpa_rates',
            'epicentr': 'epicentr_cpa_rates',
            'rozetka': 'rozetka_cpa_rates',
        }
        table = table_map.get(mp, 'prom_cpa_rates')

        if mp == 'rozetka':
            sql = f'SELECT category_id, category_name, base_commission, price_ranges FROM {table}'
        else:
            sql = f'SELECT category_name, cpa_rate FROM {table}'

        params = []
        if search:
            sql += ' WHERE category_name ILIKE %s'
            params.append(f'%{search}%')

        sql += ' ORDER BY category_name'
        rows = db_query(sql, params)
        return [types.TextContent(type='text', text=f'{mp.upper()} CPA ({len(rows)} категорій):\n\n{fmt(rows)}')]

    # ── db_get_unavailable_products ──────────────────────────────────
    elif name == 'db_get_unavailable_products':
        days = arguments.get('days', 3)
        limit = arguments.get('limit', 50)
        cutoff = date.today() - timedelta(days=days)

        rows = db_query(
            '''SELECT ph.sku, mp.name_uk, mp.price_our,
                      COUNT(*) as unavailable_days,
                      MAX(ph.date) as last_seen_unavailable
               FROM price_history ph
               JOIN my_products mp ON ph.sku = mp.sku
               WHERE ph.available = FALSE AND ph.date >= %s
               GROUP BY ph.sku, mp.name_uk, mp.price_our
               HAVING COUNT(*) >= %s
               ORDER BY unavailable_days DESC
               LIMIT %s''',
            (cutoff, days, limit)
        )
        return [types.TextContent(
            type='text',
            text=f'Товари відсутні у фіді {days}+ днів: {len(rows)}\n\n{fmt(rows)}'
        )]

    # ── db_run_query ─────────────────────────────────────────────────
    elif name == 'db_run_query':
        sql = arguments.get('sql', '').strip()

        # Безпека — тільки SELECT
        sql_upper = sql.upper().lstrip()
        if not sql_upper.startswith('SELECT') and not sql_upper.startswith('WITH'):
            return [types.TextContent(
                type='text',
                text='❌ Дозволено тільки SELECT запити. INSERT/UPDATE/DELETE заблоковано.'
            )]

        try:
            rows = db_query(sql)
            return [types.TextContent(
                type='text',
                text=f'Результат ({len(rows)} рядків):\n\n{fmt(rows)}'
            )]
        except Exception as e:
            return [types.TextContent(type='text', text=f'❌ Помилка SQL: {e}')]

    return [types.TextContent(type='text', text=f'❌ Невідомий інструмент: {name}')]


# =============================================
# ЗАПУСК
# =============================================

async def main():
    logger.info('[EPICENTR/DB MCP] Запуск...')
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())

if __name__ == '__main__':
    asyncio.run(main())
