"""
tg_dispatcher/main.py
=======================
Telegram ШІ-Диспетчер — головна точка входу.

Стек:
- aiogram 3.x — асинхронний Telegram фреймворк
- faster-whisper — локальний STT (голос→текст) на GPU/CPU
- LangGraph — оркестратор агента з інструментами
- Qdrant — векторна БД для /learn правил

Безпека: бот відповідає ТІЛЬКИ ADMIN_ID з .env

Запуск:
    cd /home/tek/agent-system/tg_dispatcher
    python3 main.py

Як сервіс:
    systemctl --user start tg-dispatcher
"""

import os, sys, asyncio, logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, Voice
from aiogram.filters import CommandStart, Command
from aiogram.utils.markdown import bold, italic

# Завантажуємо .env з agent-system
load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))

TOKEN    = os.getenv('TELEGRAM_BOT_TOKEN', '')
ADMIN_ID = int(os.getenv('TELEGRAM_ADMIN_ID', '0'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp  = Dispatcher()


# =============================================
# МІДЛВАР БЕЗПЕКИ — відхиляє всіх крім ADMIN
# =============================================

@dp.message.outer_middleware()
async def security_middleware(handler, event, data):
    if event.from_user.id != ADMIN_ID:
        logger.warning(f'Відхилено доступ від ID: {event.from_user.id} (@{event.from_user.username})')
        return
    return await handler(event, data)


# =============================================
# КОМАНДИ
# =============================================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f'👋 Привіт, босс!\n\n'
        f'Я твій ШІ-диспетчер агентної системи.\n\n'
        f'<b>Команди:</b>\n'
        f'/status — статус системи\n'
        f'/prices — цінові алерти\n'
        f'/orders — нові замовлення\n'
        f'/learn [текст] — навчити агента правилу\n\n'
        f'Або пиши/говори вільним текстом:\n'
        f'«Онови ціни в Єпіцентрі»\n'
        f'«Скільки замовлень сьогодні?»\n'
        f'«Знайди ціни конкурентів на BAEA1217»',
        parse_mode='HTML'
    )


@dp.message(Command('status'))
async def cmd_status(message: Message):
    """Статус системи з БД."""
    try:
        sys.path.append('/home/tek/agent-system')
        from shared.utils.db import get_connection
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('''
            SELECT
                (SELECT COUNT(*) FROM my_products WHERE price_our > 0) as products,
                (SELECT COUNT(*) FROM price_history WHERE date = CURRENT_DATE) as prices_today,
                (SELECT COUNT(*) FROM orders WHERE created_at >= NOW() - INTERVAL '24 hours') as orders_today,
                (SELECT COUNT(*) FROM my_products WHERE epicentr_category_id IS NULL AND price_our > 0) as drafts,
                (SELECT COUNT(*) FROM my_products WHERE epicentr_confidence = 'high') as classified_high
        ''')
        s = dict(cur.fetchone())
        cur.close(); conn.close()

        await message.answer(
            f'📊 <b>Статус системи</b>\n\n'
            f'📦 Товарів з ціною: {s["products"]}\n'
            f'💰 Цін оновлено сьогодні: {s["prices_today"]}\n'
            f'🛒 Замовлень за 24г: {s["orders_today"]}\n'
            f'📝 Чернеток без категорії: {s["drafts"]}\n'
            f'✅ Класифіковано (high): {s["classified_high"]}',
            parse_mode='HTML'
        )
    except Exception as e:
        await message.answer(f'❌ Помилка БД: {e}')


@dp.message(Command('prices'))
async def cmd_prices(message: Message):
    """Цінові алерти за сьогодні."""
    try:
        sys.path.append('/home/tek/agent-system')
        from shared.utils.db import get_connection
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('''
            SELECT sku, our_price, prev_our_price, our_diff_pct, alert_reason
            FROM price_history
            WHERE date = CURRENT_DATE AND is_alert = TRUE AND ABS(our_diff_pct) >= 10
            ORDER BY ABS(our_diff_pct) DESC LIMIT 10
        ''')
        rows = cur.fetchall()
        cur.close(); conn.close()

        if not rows:
            await message.answer('✅ Значних змін цін сьогодні немає')
            return

        text = f'⚠️ <b>Цінові алерти сьогодні</b>:\n\n'
        for r in rows:
            emoji = '📈' if r['our_diff_pct'] > 0 else '📉'
            text += f'{emoji} <code>{r["sku"]}</code>: {r["prev_our_price"]:.0f}→{r["our_price"]:.0f} ({r["our_diff_pct"]:+.1f}%)\n'
        await message.answer(text, parse_mode='HTML')
    except Exception as e:
        await message.answer(f'❌ Помилка: {e}')


@dp.message(Command('orders'))
async def cmd_orders(message: Message):
    """Замовлення за останні 24 години."""
    try:
        sys.path.append('/home/tek/agent-system')
        from shared.utils.db import get_connection
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('''
            SELECT prom_order_id, epicentr_order_id, status, customer_name, total_price, created_at
            FROM orders
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC LIMIT 10
        ''')
        rows = cur.fetchall()
        cur.close(); conn.close()

        if not rows:
            await message.answer('📭 Замовлень за останні 24г немає')
            return

        text = f'🛒 <b>Замовлення за 24г</b> ({len(rows)}):\n\n'
        for r in rows:
            order_id = r['prom_order_id'] or r['epicentr_order_id'] or '?'
            text += f'#{order_id} — {r["customer_name"] or "?"} — {r["total_price"]} грн ({r["status"]})\n'
        await message.answer(text, parse_mode='HTML')
    except Exception as e:
        await message.answer(f'❌ Помилка: {e}')


@dp.message(Command('learn'))
async def cmd_learn(message: Message):
    """Навчити агента новому правилу."""
    instruction = message.text.replace('/learn', '').strip()
    if not instruction:
        await message.answer(
            '📚 Використання:\n'
            '/learn [опис зміни]\n\n'
            'Приклад:\n'
            '/learn Єпіцентр змінив кнопку export. Тепер вона в меню Товари → Вивантажити'
        )
        return

    try:
        sys.path.append('/home/tek/agent-system')
        from agents.interfaces.instruction_parser import InstructionParser
        parser = InstructionParser()
        result = await parser.apply_instruction(instruction, message.from_user.id)

        if result['success']:
            await message.answer(
                f'✅ Правило збережено!\n\n'
                f'📝 Файл: {result["skill_file"]}'
            )
        else:
            await message.answer(f'❌ Помилка: {result["error"]}')
    except Exception as e:
        await message.answer(f'❌ Помилка: {e}')


# =============================================
# ГОЛОСОВІ ПОВІДОМЛЕННЯ
# =============================================

@dp.message(F.voice)
async def handle_voice(message: Message):
    """Приймає голосове → STT → обробляє як текст."""
    status_msg = await message.answer('🎤 Розшифровую аудіо...')

    file_path = f'/tmp/voice_{message.message_id}.ogg'
    try:
        # Завантажуємо файл
        file = await bot.get_file(message.voice.file_id)
        await bot.download_file(file.file_path, destination=file_path)

        # STT через faster-whisper
        try:
            from ai_brain.voice_handler import transcribe_audio_async
            text = await transcribe_audio_async(file_path)

            if text:
                await status_msg.edit_text(f'📝 Почув:\n<i>{text}</i>', parse_mode='HTML')
                # Обробляємо як текстову команду
                message.text = text
                await handle_text(message)
            else:
                await status_msg.edit_text('❌ Не вдалось розпізнати. Спробуй чіткіше.')
        except ImportError:
            await status_msg.edit_text(
                '⚠️ faster-whisper не встановлено.\n'
                'Встанови: pip install faster-whisper'
            )
    except Exception as e:
        logger.error(f'Voice error: {e}')
        await status_msg.edit_text(f'🔧 Помилка обробки аудіо: {e}')
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


# =============================================
# ТЕКСТОВІ КОМАНДИ (вільний текст)
# =============================================

@dp.message(F.text)
async def handle_text(message: Message):
    """Роутить вільний текст до відповідного агента."""
    text = message.text.lower().strip()

    # Роутинг по ключових словах
    if any(w in text for w in ['єпіцентр', 'епіцентр', 'epicentr']):
        await route_epicentr(message, text)
    elif any(w in text for w in ['розетка', 'rozetka']):
        await message.answer('🏬 Розетка — перевіряю... [в розробці]')
    elif any(w in text for w in ['prom', 'пром', 'ціни', 'price']):
        await cmd_prices(message)
    elif any(w in text for w in ['замовлення', 'order']):
        await cmd_orders(message)
    elif any(w in text for w in ['статус', 'status', 'стан']):
        await cmd_status(message)
    elif any(w in text for w in ['конкурент', 'competitor']):
        await message.answer('🔍 Моніторинг конкурентів — в розробці')
    else:
        # TODO: LangGraph агент
        await message.answer(
            f'🤔 Не зрозумів: «{message.text[:50]}»\n\n'
            f'Спробуй:\n'
            f'• /status — статус системи\n'
            f'• /prices — цінові алерти\n'
            f'• /orders — замовлення\n'
            f'• «Єпіцентр XLS» — скачати товари\n'
            f'• «ціни конкурентів SKU» — перевірка'
        )


async def route_epicentr(message: Message, text: str):
    if any(w in text for w in ['xls', 'скачай', 'вивантаж', 'export']):
        await message.answer('⏳ Скачую XLS товарів Єпіцентру...\n[Playwright запускається]')
        # TODO: browser_mcp виклик
    elif any(w in text for w in ['ціни', 'оновити', 'import', 'завантаж']):
        await message.answer('⏳ Генерую XLS цін і завантажую в Єпіцентр...')
    elif any(w in text for w in ['api', 'endpoint']):
        await message.answer('⏳ Перехоплюю API endpoints...')
    elif any(w in text for w in ['замовлення', 'order']):
        await cmd_orders(message)
    else:
        await message.answer(
            '🏪 <b>Єпіцентр</b> — що зробити?\n\n'
            '• «Єпіцентр XLS» — скачати товари\n'
            '• «Єпіцентр ціни» — оновити ціни\n'
            '• «Єпіцентр API» — знайти endpoints',
            parse_mode='HTML'
        )


# =============================================
# ЗАПУСК
# =============================================

async def main():
    logger.info('=== Telegram ШІ-Диспетчер запуск ===')
    logger.info(f'Admin ID: {ADMIN_ID}')
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == '__main__':
    asyncio.run(main())
