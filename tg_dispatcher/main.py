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
ADMIN_ID         = int(os.getenv('TELEGRAM_ADMIN_ID', '0'))
CARVOL_TG_CHAT_ID = int(os.getenv('CARVOL_TG_CHAT_ID', '0'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp  = Dispatcher()

sys.path.insert(0, '/home/tek/agent-system')


# =============================================
# МІДЛВАР БЕЗПЕКИ — відхиляє всіх крім ADMIN
# =============================================

@dp.message.outer_middleware()
async def security_middleware(handler, event, data):
    user_id = event.from_user.id
    if user_id == ADMIN_ID:
        return await handler(event, data)
    # Carvol може надсилати тільки document (PDF накладні)
    if CARVOL_TG_CHAT_ID and user_id == CARVOL_TG_CHAT_ID:
        if getattr(event, 'document', None):
            return await handler(event, data)
        # 18.09.2026: 17.09 Carvol надіслав ТТН ТЕКСТОМ, і тут вони зникли без сліду —
        # два замовлення добу без ТТН. Тепер текст іде в окремий обробник.
        if getattr(event, 'text', None):
            return await handle_carvol_text(event)
        # решта (фото, голос…) не губиться: копія власнику
        try:
            await bot.copy_message(ADMIN_ID, event.chat.id, event.message_id)
            await bot.send_message(ADMIN_ID, '📨 Carvol надіслав не PDF і не текст — копія вище, розберіться вручну.')
        except Exception as e:
            logger.error(f'TTN-IN: копія повідомлення Carvol не вдалась: {e}')
        # Було: мовчазне ігнорування. 09.09.2026 виявилось, що ТТН від Carvol
        # не надходять із 19.08, і розрізнити «не надсилали» від «надсилали, а
        # ми не прийняли» неможливо — слідів немає взагалі. Обробника фото в
        # диспетчері немає, тож накладна, надіслана картинкою, зникала тут.
        kinds = [k for k in ('photo', 'video', 'voice', 'audio', 'text',
                             'sticker', 'animation')
                 if getattr(event, k, None)]
        logger.warning(f'TTN-IN: Carvol надіслав {kinds or ["невідомий тип"]} '
                       f'замість документа — проігноровано')
        return
    logger.warning(f'Відхилено доступ від ID: {user_id} (@{event.from_user.username})')


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
        f'«Знайди ціни конкурентів на BAEA1217»\n\n'
        f'📄 Надішли PDF накладну НП — автоматично встановлю ТТН.',
        parse_mode='HTML'
    )


@dp.message(Command('status'))
async def cmd_status(message: Message):
    """Статус системи з БД."""
    try:
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


@dp.message(Command('ttn'))
async def cmd_ttn(message: Message):
    """/ttn ORDER_ID ТТН — внести ТТН вручну (18.09.2026: бот радив цю команду, але її не було)."""
    from ai_brain.carvol_text import parse_ttn_command
    from agents.orders.rozetka_order_agent import set_ttn, change_status, get_order_details, _ttn_of
    p = parse_ttn_command(message.text)
    if not p:
        await message.answer('Формат: <code>/ttn 906298386 20451539117101</code> '
                             '(номер замовлення — 9 цифр, ТТН — 14)', parse_mode='HTML')
        return
    oid, ttn = int(p[0]), p[1]
    ok_ttn = await asyncio.to_thread(set_ttn, oid, ttn)
    ok_st = await asyncio.to_thread(change_status, oid, 3) if ok_ttn else False
    await asyncio.sleep(2)
    actual = _ttn_of(await asyncio.to_thread(get_order_details, oid) or {})
    logger.info(f'/ttn #{oid} {ttn}: set_ttn={ok_ttn}, status3={ok_st}, GET={actual!r}')
    if ok_ttn and actual == ttn:
        await message.answer(f'✅ #{oid}: ТТН <code>{ttn}</code> внесено й перевірено (GET). '
                             f'Статус {"«передано в доставку»" if ok_st else "НЕ змінено — перевірте"}.',
                             parse_mode='HTML')
    else:
        await message.answer(f'🚨 #{oid}: ТТН НЕ збереглась (set_ttn={ok_ttn}, GET: {actual or "порожньо"}).',
                             parse_mode='HTML')


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
# PDF НАКЛАДНІ (ТТН від Carvol) — повністю автоматично
# =============================================

def _fmt_source_info(ttn: str, data_source: str,
                     ttn_info: dict | None, parsed: dict) -> str:
    """Формує блок з даними для повідомлення адміну."""
    # Беремо поля з НП API якщо є, інакше з PDF
    np = ttn_info or {}
    recipient = np.get('recipient_name') or parsed.get('recipient') or 'не знайдено'
    phone     = np.get('recipient_phone') or parsed.get('phone')     or 'не знайдено'
    city      = np.get('city')           or parsed.get('city')       or 'не знайдено'
    warehouse = np.get('warehouse') or ''
    city_line = f'{city} {warehouse}'.strip() if warehouse else city

    source_icon = '🌐 НП API' if 'НП API' in data_source else '📄 PDF'
    return (
        f'📋 <b>Дані ({source_icon}):</b>\n'
        f'ТТН: <code>{ttn}</code>\n'
        f'Отримувач: {recipient}\n'
        f'Телефон: <code>{phone}</code>\n'
        f'Місто: {city_line}'
    )


async def handle_carvol_text(message: Message):
    """Текст від Carvol: ЗАВЖДИ копія власнику; якщо є ТТН — знайти замовлення.

    Режим CARVOL_TEXT_TTN (.env): apply (за замовчуванням, власник 18.09) — внести
    самостійно, лише якщо НП підтвердила телефон одержувача рівно одного
    кандидата; confirm — лише запропонувати замовлення й готову команду /ttn.
    """
    text = message.text or ''
    logger.warning(f'TTN-IN: текст від Carvol: {text[:300]!r}')
    await bot.send_message(ADMIN_ID, f'📨 <b>Carvol написав:</b>\n{html_escape(text[:1500])}', parse_mode='HTML')

    from ai_brain.carvol_text import extract_ttns, extract_order_ids, resolve
    ttns = extract_ttns(text)
    if not ttns:
        return
    from agents.orders.rozetka_order_agent import (get_orders_by_status, get_order_details, set_ttn,
                                                   change_status, _ttn_of)
    from agents.orders.np_api import get_ttn_info
    cands = []
    for st in (2, 26):
        for o in await asyncio.to_thread(get_orders_by_status, st) or []:
            d = await asyncio.to_thread(get_order_details, o['id']) or o
            if _ttn_of(d):
                continue
            dl = d.get('delivery') or {}
            cands.append({'order_id': o['id'], 'phone': dl.get('recipient_phone') or '',
                          'recipient': str(dl.get('recipient_title') or '')})
    ids = extract_order_ids(text)
    hint = ids[0] if len(ids) == 1 and len(ttns) == 1 else None
    # Carvol відповідає (reply) на наше повідомлення з замовленням — номер звідти точніший
    from ai_brain.carvol_text import order_from_reply
    reply = message.reply_to_message
    reply_oid = order_from_reply((reply.caption or reply.text or '') if reply else '')
    if reply_oid and len(ttns) == 1:
        hint = reply_oid
    # власник 18.09.2026: «треба автоматично все» — за замовчуванням вносимо самі
    # (лише коли НП підтвердила телефон рівно одного кандидата); confirm — лише пропозиція
    mode = (os.getenv('CARVOL_TEXT_TTN') or 'apply').strip().lower()
    for ttn in ttns:
        oid, why = await asyncio.to_thread(resolve, ttn, cands, get_ttn_info, hint)
        logger.info(f'TTN-IN: текст → ttn={ttn} → #{oid} ({why}), режим {mode}')
        if not oid:
            await bot.send_message(ADMIN_ID, f'❓ ТТН <code>{ttn}</code> — замовлення не визначено: {why}.\n'
                                             f'Відкритих без ТТН: {len(cands)}. Вкажіть: <code>/ttn ORDER_ID {ttn}</code>',
                                   parse_mode='HTML')
            continue
        if mode != 'apply':
            await bot.send_message(ADMIN_ID, f'🔎 ТТН <code>{ttn}</code> → замовлення <b>#{oid}</b> ({why}).\n'
                                             f'Підтвердіть командою:\n<code>/ttn {oid} {ttn}</code>',
                                   parse_mode='HTML')
            continue
        ok_ttn = await asyncio.to_thread(set_ttn, oid, ttn)
        ok_st = await asyncio.to_thread(change_status, oid, 3) if ok_ttn else False
        await asyncio.sleep(2)
        actual = _ttn_of(await asyncio.to_thread(get_order_details, oid) or {})
        ok = ok_ttn and actual == ttn
        await bot.send_message(ADMIN_ID, (f'✅ #{oid}: ТТН <code>{ttn}</code> внесено й перевірено (GET), '
                                          f'статус {"«передано в доставку»" if ok_st else "НЕ змінено"} · {why}') if ok else
                               (f'🚨 #{oid}: ТТН <code>{ttn}</code> НЕ збереглась (GET: {actual or "порожньо"}). '
                                f'Вручну: <code>/ttn {oid} {ttn}</code>'), parse_mode='HTML')


def html_escape(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


@dp.message(F.document)
async def handle_document(message: Message):
    """PDF накладна НП від Carvol або адміна — автоматичне встановлення ТТН."""
    from_carvol    = CARVOL_TG_CHAT_ID and message.from_user.id == CARVOL_TG_CHAT_ID
    target_chat_id = ADMIN_ID if from_carvol else message.chat.id

    doc = message.document
    logger.info(f'TTN-IN: документ від {message.from_user.id} '
                f'(carvol={bool(from_carvol)}): {doc.file_name!r} '
                f'{doc.mime_type!r} {doc.file_size} байт')
    if not doc.mime_type or 'pdf' not in doc.mime_type.lower():
        logger.warning(f'TTN-IN: не PDF ({doc.mime_type!r}) — відхилено')
        if not from_carvol:
            await bot.send_message(target_chat_id, '📎 Підтримуються тільки PDF файли (накладні НП).')
        return

    label      = '📄 Carvol надіслав накладну — обробляю...' if from_carvol else '📄 Обробляю PDF накладну...'
    status_msg = await bot.send_message(target_chat_id, label)
    pdf_path   = f'/tmp/ttn_{message.message_id}.pdf'

    try:
        file = await bot.get_file(doc.file_id)
        await bot.download_file(file.file_path, destination=pdf_path)

        from agents.orders.ttn_pdf_parser import parse_ttn_pdf, match_order_by_ttn_data
        from agents.orders.np_api import get_ttn_info, match_order_by_np_data
        from agents.orders.rozetka_order_agent import set_ttn, change_status, get_order_details

        # --- Крок 1: парсинг PDF ---
        parsed = await asyncio.to_thread(parse_ttn_pdf, pdf_path)
        ttn    = parsed.get('ttn')
        logger.info(f'TTN-IN: розбір PDF → ttn={ttn!r}, '
                    f'полів={sorted(parsed.keys()) if parsed else None}')

        if not ttn:
            info = _fmt_source_info('не знайдено', 'PDF', None, parsed)
            await status_msg.edit_text(
                f'⚠️ <b>ТТН не знайдено в PDF</b>\n\n{info}\n\n'
                f'Вкажи вручну: /ttn ORDER_ID НОМЕР_ТТН',
                parse_mode='HTML',
            )
            return

        pdf_url = f"https://api.novaposhta.ua/v2.0/print/orders/?orders[]={ttn}&type=pdf"

        # --- Крок 2: НП API для уточнення даних ---
        await status_msg.edit_text(
            f'📄 ТТН <code>{ttn}</code> — перевіряю в НП API...',
            parse_mode='HTML',
        )

        ttn_info    = await asyncio.to_thread(get_ttn_info, ttn, parsed.get('phone') or '')
        np_ok       = not ttn_info.get('error') and (
            ttn_info.get('recipient_name') or ttn_info.get('recipient_phone')
        )
        data_source = 'НП API' if np_ok else 'PDF'
        source_info = _fmt_source_info(ttn, data_source, ttn_info if np_ok else None, parsed)

        if ttn_info.get('error'):
            logger.warning(f'НП API error для {ttn}: {ttn_info["error"]}')

        # --- Крок 3: матчинг замовлення ---
        matches = []
        match_source = data_source

        if np_ok:
            matches = await asyncio.to_thread(match_order_by_np_data, ttn_info)
            if not matches:
                # fallback на PDF-дані
                matches = await asyncio.to_thread(match_order_by_ttn_data, parsed)
                match_source = 'PDF (fallback)'

        if not matches:
            matches = await asyncio.to_thread(match_order_by_ttn_data, parsed)
            match_source = 'PDF'

        if not matches:
            logger.warning(f'TTN-IN: ttn={ttn} — замовлення НЕ знайдено '
                           f'(джерело матчингу {match_source})')
            await status_msg.edit_text(
                f'❌ <b>Замовлення не знайдено</b>\n\n{source_info}\n\n'
                f'Джерело матчингу: {match_source}\n\n'
                f'Вкажи вручну:\n<code>/ttn ORDER_ID {ttn}</code>',
                parse_mode='HTML',
            )
            return

        # --- Кілька збігів або жодного: розрізняємо телефоном у НП ---
        # 18.09.2026: при однаковій ціні збігів кілька (телефон у PDF замаскований),
        # бот зупинявся й радив неіснуючу команду /ttn. Тепер: ТТН перевіряється в НП
        # з телефоном кожного кандидата; рівно один підтверджений — він і є.
        if len(matches) != 1:
            from ai_brain.carvol_text import resolve
            pool = [m['order_id'] for m in matches]
            if not pool:
                from agents.orders.rozetka_order_agent import get_orders_by_status, _ttn_of
                for st in (2, 26):
                    for o in await asyncio.to_thread(get_orders_by_status, st) or []:
                        pool.append(o['id'])
            cands = []
            from agents.orders.rozetka_order_agent import _ttn_of as _has_ttn
            for oid_ in dict.fromkeys(pool):
                d_ = await asyncio.to_thread(get_order_details, oid_) or {}
                if _has_ttn(d_):
                    continue                     # у замовлення вже є ТТН — другу не даємо
                cands.append({'order_id': oid_, 'phone': (d_.get('delivery') or {}).get('recipient_phone') or ''})
            oid_np, why_np = await asyncio.to_thread(resolve, ttn, cands, get_ttn_info)
            logger.info(f'TTN-IN: {len(matches)} збігів → перевірка НП телефоном: #{oid_np} ({why_np})')
            if oid_np:
                matches = [{'order_id': oid_np, 'score': 1.0, 'match_by': 'НП: телефон одержувача'}]
                match_source = f'{match_source} → НП-телефон'

        # --- Кілька збігів — список без кнопок ---
        if len(matches) > 1:
            lines = '\n'.join(
                f'  #{m["order_id"]} ({m["score"]:.0%}, by {m.get("match_by","?")})'
                for m in matches[:5]
            )
            await status_msg.edit_text(
                f'🔍 <b>Знайдено {len(matches)} збігів</b> [{match_source}]\n\n'
                f'{source_info}\n\n'
                f'Збіги:\n{lines}\n\n'
                f'Вкажи вручну:\n<code>/ttn ORDER_ID {ttn}</code>',
                parse_mode='HTML',
            )
            return

        # --- Один збіг — автоматично ---
        order_id = matches[0]['order_id']
        score    = matches[0]['score']
        match_by = matches[0].get('match_by', '?')

        await status_msg.edit_text(
            f'{source_info}\n\n'
            f'⏳ #{order_id} (score {score:.0%}, by {match_by}) [{match_source}]\n'
            f'Встановлюю ТТН...',
            parse_mode='HTML',
        )

        # --- Крок 4: set_ttn + change_status(3) ---
        ok_ttn    = await asyncio.to_thread(set_ttn, order_id, ttn)
        ok_status = await asyncio.to_thread(change_status, order_id, 3) if ok_ttn else False
        logger.info(f'TTN-IN: #{order_id} ttn={ttn} → set_ttn={ok_ttn}, '
                    f'change_status(3)={ok_status}')

        if ok_ttn:
            try:
                from shared.utils.db import get_connection
                conn = get_connection()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE rozetka_processed_orders SET ttn=%s, status='shipped' WHERE order_id=%s",
                    (ttn, order_id)
                )
                conn.commit()
                cur.close(); conn.close()
            except Exception as db_err:
                logger.error(f'DB update TTN failed for #{order_id}: {db_err}')

        # --- Крок 5: верифікація GET /orders/{id} ---
        await asyncio.sleep(2)
        order_data   = await asyncio.to_thread(get_order_details, order_id)
        actual_ttn   = (order_data.get('ttn') or '').strip()
        ttn_verified = (actual_ttn == ttn)

        if ok_ttn and ok_status and ttn_verified:
            await status_msg.edit_text(
                f'{source_info}\n\n'
                f'✅ <b>Готово!</b>\n'
                f'Замовлення: <b>#{order_id}</b>\n'
                f'ТТН <code>{ttn}</code> — встановлено та підтверджено (GET)\n'
                f'Статус → «Передано в доставку»\n'
                f'📄 <a href="{pdf_url}">PDF накладна</a>',
                parse_mode='HTML',
            )
        elif ok_ttn and ok_status and not ttn_verified:
            await status_msg.edit_text(
                f'🚨 <b>ALARM! ТТН не збереглось у Розетці</b>\n\n'
                f'{source_info}\n\n'
                f'Замовлення: <b>#{order_id}</b>\n'
                f'set_ttn: ✅  |  change_status: ✅\n'
                f'Верифікація GET: ❌ поле ttn = <code>{actual_ttn or "порожньо"}</code>\n\n'
                f'Встанови вручну:\n<code>/ttn {order_id} {ttn}</code>\n'
                f'📄 <a href="{pdf_url}">PDF накладна</a>',
                parse_mode='HTML',
            )
        elif ok_ttn and not ok_status:
            v_icon = '✅' if ttn_verified else '❌'
            await status_msg.edit_text(
                f'⚠️ <b>ТТН встановлено, статус НЕ змінився</b>\n\n'
                f'Замовлення: <b>#{order_id}</b>\n'
                f'ТТН <code>{ttn}</code>: {v_icon} (GET)\n'
                f'Статус → 3: ❌ помилка API\n\nПеревір вручну.',
                parse_mode='HTML',
            )
        else:
            await status_msg.edit_text(
                f'🚨 <b>ALARM! Не вдалось встановити ТТН</b>\n\n'
                f'{source_info}\n\n'
                f'Замовлення: <b>#{order_id}</b>\n'
                f'set_ttn: ❌\n\n'
                f'Встанови вручну:\n<code>/ttn {order_id} {ttn}</code>\n'
                f'📄 <a href="{pdf_url}">PDF накладна</a>',
                parse_mode='HTML',
            )

    except Exception as e:
        logger.error(f'handle_document error: {e}', exc_info=True)
        await status_msg.edit_text(f'❌ Помилка обробки PDF: {e}')
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


# =============================================
# ГОЛОСОВІ ПОВІДОМЛЕННЯ
# =============================================

@dp.message(F.voice)
async def handle_voice(message: Message):
    """Приймає голосове → STT → обробляє як текст."""
    status_msg = await message.answer('🎤 Розшифровую аудіо...')

    file_path = f'/tmp/voice_{message.message_id}.ogg'
    try:
        file = await bot.get_file(message.voice.file_id)
        await bot.download_file(file.file_path, destination=file_path)

        try:
            from ai_brain.voice_handler import transcribe_audio_async
            text = await transcribe_audio_async(file_path)

            if text:
                await status_msg.edit_text(f'📝 Почув:\n<i>{text}</i>', parse_mode='HTML')
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
        await message.answer(
            f'🤔 Не зрозумів: «{message.text[:50]}»\n\n'
            f'Спробуй:\n'
            f'• /status — статус системи\n'
            f'• /prices — цінові алерти\n'
            f'• /orders — замовлення\n'
            f'• «Єпіцентр XLS» — скачати товари\n'
            f'• «ціни конкурентів SKU» — перевірка\n'
            f'• 📄 PDF накладна — встановити ТТН'
        )


async def route_epicentr(message: Message, text: str):
    if any(w in text for w in ['xls', 'скачай', 'вивантаж', 'export']):
        await message.answer('⏳ Скачую XLS товарів Єпіцентру...\n[Playwright запускається]')
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
