"""
agents/interfaces/telegram_gateway.py
========================================
Telegram Gateway — командний центр агентної системи.

Функції:
- Виконання задач по текстових командах
- /learn — навчання агента новим правилам
- Human-in-the-loop підтвердження через кнопки
- Автосповіщення про події системи
- Роутинг до browser_mcp, prom_mcp, epicentr_mcp

Запуск:
    python3 agents/interfaces/telegram_gateway.py

Команди:
    /start              — вітання і список команд
    /status             — статус системи
    /prices             — звіт по цінах
    /orders             — нові замовлення
    /learn <текст>      — навчити агента новому правилу
    /screenshot         — скріншот поточної сторінки
    <будь-який текст>   — виконати як browser команду
"""

import os, sys, json, asyncio
from datetime import datetime
from loguru import logger
import requests as req
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection
from agents.interfaces.instruction_parser import InstructionParser

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
ADMIN_ID = int(os.getenv('TELEGRAM_ADMIN_ID', '0'))

# Pending confirmations: {user_id: {callback_data: handler}}
pending_confirmations = {}


# =============================================
# УТИЛІТИ
# =============================================

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def db_query(sql: str, params=None) -> list:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql, params or ())
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


# =============================================
# КОМАНДИ
# =============================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вітання і список команд."""
    if not is_admin(update.effective_user.id):
        return

    text = '''🤖 <b>Agent System — Командний центр</b>

<b>Швидкі команди:</b>
/status — статус системи і агентів
/prices — звіт по цінах
/orders — нові замовлення Prom
/alerts — цінові алерти

<b>Дії:</b>
/learn <текст> — навчити агента новому правилу

<b>Або пиши вільним текстом:</b>
"Онови ціни в Єпіцентрі"
"Скачай прайс Грандінструмент"
"Перевір замовлення Розетки"
"Знайди ціни конкурентів на BAEA1217"
'''
    await update.message.reply_text(text, parse_mode='HTML')


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статус системи."""
    if not is_admin(update.effective_user.id):
        return

    try:
        # Статистика з БД
        stats = db_query('''
            SELECT
                (SELECT COUNT(*) FROM my_products WHERE price_our > 0) as products,
                (SELECT COUNT(*) FROM price_history WHERE date = CURRENT_DATE) as prices_today,
                (SELECT COUNT(*) FROM price_history WHERE date = CURRENT_DATE AND is_alert = TRUE) as alerts_today,
                (SELECT COUNT(*) FROM orders WHERE created_at >= NOW() - INTERVAL '24 hours') as orders_today,
                (SELECT COUNT(*) FROM my_products WHERE epicentr_category_id IS NULL AND price_our > 0) as epicentr_drafts
        ''')
        s = stats[0] if stats else {}

        text = f'''📊 <b>Статус системи</b>
{datetime.now().strftime("%d.%m.%Y %H:%M")}

📦 Товарів з ціною: {s.get("products", "?")}
💰 Цін оновлено сьогодні: {s.get("prices_today", "?")}
⚠️ Цінових алертів: {s.get("alerts_today", "?")}
🛒 Замовлень сьогодні: {s.get("orders_today", "?")}
📝 Чернеток Єпіцентру: {s.get("epicentr_drafts", "?")}'''

        await update.message.reply_text(text, parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f'❌ Помилка: {e}')


async def cmd_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Звіт по цінах."""
    if not is_admin(update.effective_user.id):
        return

    rows = db_query('''
        SELECT sku, our_price, prev_our_price, our_diff_pct, alert_reason
        FROM price_history
        WHERE date = CURRENT_DATE AND is_alert = TRUE AND ABS(our_diff_pct) >= 15
        ORDER BY ABS(our_diff_pct) DESC
        LIMIT 10
    ''')

    if not rows:
        await update.message.reply_text('✅ Значних змін цін сьогодні немає')
        return

    text = f'⚠️ <b>Цінові алерти сьогодні</b> ({len(rows)} топ):\n\n'
    for r in rows:
        emoji = '📈' if r['our_diff_pct'] > 0 else '📉'
        text += f'{emoji} <code>{r["sku"]}</code>: {r["prev_our_price"]:.0f}→{r["our_price"]:.0f} грн ({r["our_diff_pct"]:+.1f}%)\n'
        if r['alert_reason']:
            text += f'   └ {r["alert_reason"]}\n'

    await update.message.reply_text(text, parse_mode='HTML')


async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Нові замовлення."""
    if not is_admin(update.effective_user.id):
        return

    rows = db_query('''
        SELECT prom_order_id, status, customer_name, total_price, created_at
        FROM orders
        WHERE created_at >= NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC
        LIMIT 10
    ''')

    if not rows:
        await update.message.reply_text('📭 Замовлень за останні 24 години немає')
        return

    text = f'🛒 <b>Замовлення за 24 години</b> ({len(rows)}):\n\n'
    for r in rows:
        text += f'#{r["prom_order_id"]} — {r["customer_name"]} — {r["total_price"]} грн ({r["status"]})\n'

    await update.message.reply_text(text, parse_mode='HTML')


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Цінові алерти."""
    await cmd_prices(update, context)


# =============================================
# /LEARN — НАВЧАННЯ АГЕНТА
# =============================================

async def cmd_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Навчає агента новому правилу.
    /learn Розетка змінила кнопку. Тепер "Вивантажити XML" в меню ліворуч.
    """
    if not is_admin(update.effective_user.id):
        return

    instruction = ' '.join(context.args) if context.args else ''
    if not instruction:
        await update.message.reply_text(
            '📚 Використання:\n/learn <опис зміни>\n\n'
            'Приклад:\n/learn Єпіцентр змінив кнопку export. Тепер вона в меню Товари → Вивантажити'
        )
        return

    parser = InstructionParser()
    result = await parser.apply_instruction(instruction, update.effective_user.id)

    if result['success']:
        await update.message.reply_text(
            f'✅ Правило збережено!\n\n'
            f'📝 Файл: {result["skill_file"]}\n'
            f'📖 Додано: {result["added_text"][:100]}...'
        )
    else:
        await update.message.reply_text(f'❌ Помилка: {result["error"]}')


# =============================================
# ТЕКСТОВІ КОМАНДИ (ВІЛЬНИЙ ТЕКСТ)
# =============================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обробляє довільні текстові команди.
    Роутить до відповідного агента.
    """
    if not is_admin(update.effective_user.id):
        return

    text = update.message.text.lower().strip()
    user_id = update.effective_user.id

    # Роутинг по ключових словах
    if any(w in text for w in ['єпіцентр', 'epicentr', 'епіцентр']):
        await handle_epicentr_command(update, text)

    elif any(w in text for w in ['розетка', 'rozetka']):
        await handle_rozetka_command(update, text)

    elif any(w in text for w in ['prom', 'пром', 'прайс', 'ціни', 'price']):
        await handle_prom_command(update, text)

    elif any(w in text for w in ['конкурент', 'competitor', 'конкуренти']):
        await handle_competitor_command(update, text)

    elif any(w in text for w in ['грандінструмент', 'grandinstrument', 'постачальник', 'прайс']):
        await handle_supplier_command(update, text)

    else:
        # Невідома команда — пропонуємо варіанти
        keyboard = [
            [InlineKeyboardButton("📊 Статус", callback_data='cmd_status')],
            [InlineKeyboardButton("💰 Ціни", callback_data='cmd_prices'),
             InlineKeyboardButton("🛒 Замовлення", callback_data='cmd_orders')],
            [InlineKeyboardButton("🌐 Єпіцентр XLS", callback_data='epicentr_export'),
             InlineKeyboardButton("🔍 API endpoints", callback_data='epicentr_intercept')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f'🤔 Не зрозумів команду: "{text[:50]}"\n\nОберіть дію:',
            reply_markup=reply_markup
        )


async def handle_epicentr_command(update: Update, text: str):
    """Роутить команди Єпіцентру."""
    if any(w in text for w in ['скачай', 'export', 'вивантаж', 'xls']):
        await update.message.reply_text('⏳ Скачую XLS товарів Єпіцентру...')
        # TODO: запустити epicentr_cabinet.export_products_xls()
        await update.message.reply_text('✅ [Заглушка] XLS скачано')

    elif any(w in text for w in ['ціни', 'price', 'завантаж', 'import']):
        await update.message.reply_text('⏳ Генерую XLS з цінами і завантажую в Єпіцентр...')
        # TODO: generate_prices_xls() → import_prices_xls()
        await update.message.reply_text('✅ [Заглушка] Ціни оновлено')

    elif any(w in text for w in ['api', 'endpoint', 'перехоп']):
        await update.message.reply_text('⏳ Перехоплюю API endpoints Єпіцентру...')
        # TODO: intercept_api_endpoints()
        await update.message.reply_text('✅ [Заглушка] Endpoints знайдено')

    else:
        await update.message.reply_text(
            '🏪 <b>Єпіцентр</b> — оберіть дію:',
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Скачати XLS товарів", callback_data='epicentr_export')],
                [InlineKeyboardButton("📤 Завантажити ціни", callback_data='epicentr_import')],
                [InlineKeyboardButton("🔍 Знайти API endpoints", callback_data='epicentr_intercept')],
                [InlineKeyboardButton("🗺 Маппінг артикулів", callback_data='epicentr_map')],
            ])
        )


async def handle_rozetka_command(update: Update, text: str):
    await update.message.reply_text('🏬 Розетка — перевіряю статус...\n[Функція в розробці]')


async def handle_prom_command(update: Update, text: str):
    await cmd_prices(update, None)


async def handle_competitor_command(update: Update, text: str):
    await update.message.reply_text('🔍 Моніторинг конкурентів — в розробці')


async def handle_supplier_command(update: Update, text: str):
    await update.message.reply_text('📦 Постачальник — в розробці')


# =============================================
# INLINE КНОПКИ (Human-in-the-loop)
# =============================================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє натискання inline кнопок."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = update.effective_user.id

    if not is_admin(user_id):
        return

    # Перевіряємо pending confirmations
    if user_id in pending_confirmations and data in pending_confirmations[user_id]:
        handler = pending_confirmations[user_id].pop(data)
        await handler(query, data)
        return

    # Стандартні кнопки
    if data == 'cmd_status':
        await cmd_status(update, context)
    elif data == 'cmd_prices':
        await cmd_prices(update, context)
    elif data == 'cmd_orders':
        await cmd_orders(update, context)
    elif data == 'epicentr_export':
        await query.edit_message_text('⏳ Скачую XLS товарів Єпіцентру...')
        # TODO: asyncio.create_task(run_epicentr_export(query))
        await query.edit_message_text('✅ [Заглушка] XLS скачано')
    elif data == 'epicentr_import':
        await query.edit_message_text('⏳ Завантажую ціни в Єпіцентр...')
    elif data == 'epicentr_intercept':
        await query.edit_message_text('⏳ Перехоплюю API endpoints...')
    elif data == 'epicentr_map':
        await query.edit_message_text('⏳ Маппінг артикулів...')


# =============================================
# ПУБЛІЧНІ ФУНКЦІЇ ДЛЯ СПОВІЩЕНЬ
# =============================================

async def send_alert(message: str, screenshot_path: str = None,
                     buttons: list = None, callback_handlers: dict = None):
    """
    Відправляє сповіщення адміну.

    buttons: [{'text': 'Так', 'data': 'confirm_yes'}, ...]
    callback_handlers: {'confirm_yes': async_func, 'confirm_no': async_func}
    """
    bot = Application.builder().token(TELEGRAM_TOKEN).build().bot

    reply_markup = None
    if buttons:
        keyboard = [[InlineKeyboardButton(b['text'], callback_data=b['data']) for b in buttons]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if callback_handlers:
            pending_confirmations[ADMIN_ID] = callback_handlers

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )

    if screenshot_path and os.path.exists(screenshot_path):
        with open(screenshot_path, 'rb') as f:
            await bot.send_photo(chat_id=ADMIN_ID, photo=f)


# =============================================
# ЗАПУСК БОТА
# =============================================

def main():
    logger.info('[Telegram Gateway] Запуск...')

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Команди
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('status', cmd_status))
    app.add_handler(CommandHandler('prices', cmd_prices))
    app.add_handler(CommandHandler('orders', cmd_orders))
    app.add_handler(CommandHandler('alerts', cmd_alerts))
    app.add_handler(CommandHandler('learn', cmd_learn))

    # Текстові повідомлення
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Inline кнопки
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.success('[Telegram Gateway] Бот запущено')
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
