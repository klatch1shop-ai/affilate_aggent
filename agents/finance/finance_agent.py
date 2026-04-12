import os, sys, json, asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

from shared.utils.ollama_worker import request_llm
from shared.utils.skills_indexer import search_skills
from shared.utils.db import log_event, update_agent_status, create_alert, get_connection
from shared.utils.redis_queue import pop_task

AGENT_NAME = "finance"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "dolphin-llama3")

def get_llm(model=None):
    return model or os.getenv('OLLAMA_MODEL', 'llama3.2:3b'), temperature=0.1)

def get_usd_rate() -> float:
    try:
        import httpx
        resp = httpx.get("https://bank.gov.ua/NBUStatService/v1/statdataportal/exchange?json", timeout=10)
        for item in resp.json():
            if item.get("cc") == "USD":
                return float(item.get("rate", 41.0))
    except Exception as e:
        logger.warning(f"[FINANCE] USD rate error: {e}")
    return 41.0

def get_products_stats() -> dict:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                marketplace,
                COUNT(*) as total,
                AVG(price) as avg_price,
                MIN(price) as min_price,
                MAX(price) as max_price,
                COUNT(*) FILTER (WHERE in_stock = true) as in_stock
            FROM scraped_products GROUP BY marketplace
        """)
        stats = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) as total FROM scraped_products")
        total = cur.fetchone()
        cur.close(); conn.close()
        for s in stats:
            for k in ["avg_price","min_price","max_price"]:
                if s.get(k): s[k] = round(float(s[k]), 2)
        return {"marketplace_stats": stats, "total_products": total["total"] if total else 0}
    except Exception as e:
        logger.error(f"[FINANCE] Stats error: {e}")
        return {}

def calculate_dropship_margin(buy_price: float, sell_multiplier: float = 1.35) -> dict:
    sell_price = round(buy_price * sell_multiplier, 2)
    margin = round(sell_price - buy_price, 2)
    margin_pct = round((margin / sell_price) * 100, 1)
    prom_fee = round(sell_price * 0.05, 2)
    rozetka_fee = round(sell_price * 0.12, 2)
    net_prom = round(margin - prom_fee, 2)
    net_rozetka = round(margin - rozetka_fee, 2)
    return {
        "buy_price": buy_price,
        "sell_price": sell_price,
        "gross_margin": margin,
        "margin_pct": margin_pct,
        "prom_fee_5pct": prom_fee,
        "rozetka_fee_12pct": rozetka_fee,
        "net_profit_prom": net_prom,
        "net_profit_rozetka": net_rozetka,
    }

def weekly_report() -> dict:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT level, COUNT(*) as cnt
            FROM event_logs
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY level
        """)
        logs = {r["level"]: r["cnt"] for r in cur.fetchall()}
        cur.execute("""
            SELECT COUNT(*) as cnt FROM alerts
            WHERE created_at > NOW() - INTERVAL '7 days'
        """)
        alerts_week = cur.fetchone()
        cur.execute("""
            SELECT name, status FROM agents
        """)
        agents = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()

        usd = get_usd_rate()
        products = get_products_stats()

        sample_margins = [
            calculate_dropship_margin(500),
            calculate_dropship_margin(1000),
            calculate_dropship_margin(2000),
            calculate_dropship_margin(5000),
        ]

        return {
            "period": "last_7_days",
            "usd_rate": usd,
            "event_logs": logs,
            "alerts_count": alerts_week["cnt"] if alerts_week else 0,
            "agents": agents,
            "products": products,
            "margin_examples": sample_margins,
            "generated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"[FINANCE] Weekly report error: {e}")
        return {}

def analyze_with_llm(data: dict, task: str) -> str:
    try:
        model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        skills = search_skills(task, agent="finance", limit=2)
        prompt = f"""Ти — фінансовий аналітик дропшипінг-бізнесу в Україні.

{skills}

Задача: {task}

Дані:
{json.dumps(data, ensure_ascii=False, default=str)}

Дай структурований аналіз:
1. Фінансовий стан системи
2. Рентабельність по майданчиках
3. Ризики наступного тижня
4. Рекомендації для збільшення прибутку

Відповідай українською мовою. Будь конкретним."""
        return request_llm(model, prompt)
    except Exception as e:
        return f"Помилка аналізу: {e}"

async def run_weekly_report():
    logger.info("[FINANCE] Generating weekly report...")
    update_agent_status(AGENT_NAME, "busy")
    log_event(AGENT_NAME, "INFO", "Weekly report started")

    data = weekly_report()
    analysis = analyze_with_llm(data, "Тижневий фінансовий звіт дропшипінг системи")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO event_logs (agent_id, level, message, metadata)
        SELECT a.id, 'INFO', 'Weekly financial report', %s
        FROM agents a WHERE a.name = %s
    """, (json.dumps({"report": data, "analysis": analysis}, ensure_ascii=False, default=str), AGENT_NAME))
    conn.commit(); cur.close(); conn.close()

    create_alert(AGENT_NAME, "Тижневий звіт готовий", analysis[:200], "INFO")
    update_agent_status(AGENT_NAME, "idle")
    logger.success("[FINANCE] Weekly report done")
    return {"data": data, "analysis": analysis}

async def run_margin_calc(prices: list = None):
    if not prices:
        prices = [300, 500, 1000, 2000, 5000]
    logger.info(f"[FINANCE] Margin calculation for: {prices}")
    results = [calculate_dropship_margin(p) for p in prices]
    log_event(AGENT_NAME, "INFO", "Margin calculation done", {"prices": prices})
    for r in results:
        print(f"Купівля: {r['buy_price']} грн | Продаж: {r['sell_price']} грн | "
              f"Prom: {r['net_profit_prom']} грн | Rozetka: {r['net_profit_rozetka']} грн")
    return results

def listen_loop():
    logger.info("[FINANCE] Listening queue:finance...")
    update_agent_status(AGENT_NAME, "idle")
    while True:
        task = pop_task("queue:finance", timeout=5)
        if task:
            desc = task.get("description","").lower()
            if "звіт" in desc or "report" in desc:
                asyncio.run(run_weekly_report())
            elif "маржа" in desc or "margin" in desc:
                asyncio.run(run_margin_calc())
            else:
                asyncio.run(run_weekly_report())

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--margin", action="store_true")
    parser.add_argument("--listen", action="store_true")
    args = parser.parse_args()
    if args.report:
        result = asyncio.run(run_weekly_report())
        print(result.get("analysis",""))
    elif args.margin:
        asyncio.run(run_margin_calc())
    elif args.listen:
        listen_loop()
    else:
        parser.print_help()
