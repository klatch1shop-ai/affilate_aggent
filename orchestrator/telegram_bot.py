import os, sys, json
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

from shared.utils.db import log_event, create_alert, get_connection
from shared.utils.redis_queue import push_task, get_queue_length

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", "0"))

def is_admin(update):
    return update.effective_user.id == ADMIN_ID

def get_system_status():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, status, updated_at FROM agents ORDER BY name")
        agents = cur.fetchall()
        cur.execute("SELECT COUNT(*) as cnt FROM alerts WHERE is_read = false")
        unread = cur.fetchone()
        cur.execute("SELECT COUNT(*) as cnt FROM event_logs WHERE created_at > NOW() - INTERVAL '1 hour'")
        recent = cur.fetchone()
        cur.close(); conn.close()
        queues = {a: get_queue_length(f"queue:{a}") for a in
                  ["orchestrator","scraper","marketing","developer","finance","efficiency"]}
        emoji = {"idle":"\U0001f7e2","busy":"\U0001f7e1","error":"\U0001f534"}
        lines = ["*Agent System — статус*\n"]
        lines.append("*Агенти:*")
        for a in agents:
            e = emoji.get(a["status"], "\u26aa")
            q = queues.get(a["name"], 0)
            lines.append(f"{e} `{a['name']}` — {a['status']} | черга: {q}")
        lines.append(f"\n*Непрочитаних сповіщень:* {unread['cnt']}")
        lines.append(f"*Подій за годину:* {recent['cnt']}")
        lines.append(f"\n_Оновлено: {datetime.now().strftime('%H:%M:%S')}_")
        return "\n".join(lines)
    except Exception as e:
        return f"Помилка: {e}"

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001f4ca Статус", callback_data="status"),
         InlineKeyboardButton("\U0001f514 Сповіщення", callback_data="alerts")],
        [InlineKeyboardButton("\U0001f4cb Логи", callback_data="logs"),
         InlineKeyboardButton("\U0001f4e6 Черги", callback_data="queues")],
        [InlineKeyboardButton("\U0001f916 Команда агенту", callback_data="send_command")],
    ])

async def start(update, context):
    if not is_admin(update): return
    await update.message.reply_text(
        "*Agent System — панель керування*\n\nВибери дію або напиши команду:",
        parse_mode="Markdown", reply_markup=main_keyboard())

async def handle_text(update, context):
    if not is_admin(update): return
    text = update.message.text.strip()
    if text.startswith("/"): return
    task = {"type":"admin_command","description":text,"priority":8,"source":"telegram"}
    push_task("queue:orchestrator", task)
    log_event("orchestrator","INFO",f"Telegram: {text}",{"from":"admin"})
    await update.message.reply_text(
        f"\U00002705 Команду передано оркестратору:\n`{text}`",
        parse_mode="Markdown", reply_markup=main_keyboard())

async def button_handler(update, context):
    q = update.callback_query
    await q.answer()
    if not is_admin(update): return

    if q.data == "status":
        await q.edit_message_text(get_system_status(), parse_mode="Markdown", reply_markup=main_keyboard())

    elif q.data == "alerts":
        try:
            conn = get_connection(); cur = conn.cursor()
            cur.execute("SELECT level,source,title,message,created_at FROM alerts ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall(); cur.close(); conn.close()
            lv = {"INFO":"\u2139\ufe0f","WARNING":"\u26a0\ufe0f","ERROR":"\u274c"}
            lines = ["*Останні сповіщення:*\n"]
            for r in rows:
                t = r["created_at"].strftime("%H:%M") if r["created_at"] else ""
                lines.append(f"{lv.get(r['level'],'\U0001f4cc')} [{t}] *{r['title']}*")
                if r["message"]: lines.append(f"   {r['message'][:80]}")
            text = "\n".join(lines) if rows else "Сповіщень немає"
        except Exception as e:
            text = f"Помилка: {e}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f519 Назад", callback_data="status")]])
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

    elif q.data == "logs":
        try:
            conn = get_connection(); cur = conn.cursor()
            cur.execute("SELECT el.level,el.message,el.created_at,a.name as agent FROM event_logs el LEFT JOIN agents a ON el.agent_id=a.id ORDER BY el.created_at DESC LIMIT 10")
            rows = cur.fetchall(); cur.close(); conn.close()
            lines = ["*Останні події:*\n"]
            for r in rows:
                t = r["created_at"].strftime("%H:%M:%S") if r["created_at"] else ""
                lines.append(f"`{t}` [{r['agent'] or '?'}] {r['message'][:60]}")
            text = "\n".join(lines)
        except Exception as e:
            text = f"Помилка: {e}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f519 Назад", callback_data="status")]])
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

    elif q.data == "queues":
        queues = {a: get_queue_length(f"queue:{a}") for a in
                  ["orchestrator","scraper","marketing","developer","finance","efficiency"]}
        lines = ["*Черги завдань:*\n"]
        for name, count in queues.items():
            bar = "\u2588" * min(count,10) if count > 0 else "\u2591"
            lines.append(f"`{name:12}` {bar} {count}")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f519 Назад", callback_data="status")]])
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)

    elif q.data == "send_command":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f519 Назад", callback_data="status")]])
        await q.edit_message_text(
            "Напиши команду текстом.\n\nПриклади:\n- _Знайди топ товари на Rozetka_\n- _Звіт по продажах за тиждень_\n- _Перевір продуктивність агентів_",
            parse_mode="Markdown", reply_markup=kb)

def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не встановлений"); return
    logger.info("[TELEGRAM BOT] Starting...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.success("[TELEGRAM BOT] Running.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
