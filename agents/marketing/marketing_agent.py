import os, sys, json, asyncio
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

from shared.utils.ollama_worker import request_llm
from shared.utils.skills_indexer import search_skills
from shared.utils.db import log_event, update_agent_status, create_alert, get_connection
from shared.utils.redis_queue import pop_task, push_task

AGENT_NAME = "marketing"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "dolphin-llama3")

def get_llm(model=None):
    return model or os.getenv('OLLAMA_MODEL', 'llama3.2:3b'), temperature=0.3)

def get_google_trends(keywords: list, geo: str = "UA") -> dict:
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="uk-UA", tz=120, timeout=(10,30))
        pt.build_payload(keywords[:5], cat=0, timeframe="today 3-m", geo=geo)
        interest = pt.interest_over_time()
        if interest.empty:
            return {}
        result = {}
        for kw in keywords[:5]:
            if kw in interest.columns:
                result[kw] = {
                    "avg": float(interest[kw].mean()),
                    "trend": "up" if interest[kw].iloc[-1] > interest[kw].iloc[0] else "down",
                    "peak": float(interest[kw].max()),
                }
        return result
    except Exception as e:
        logger.error(f"[MARKETING] Trends error: {e}")
        return {}

def get_related_queries(keyword: str, geo: str = "UA") -> list:
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="uk-UA", tz=120, timeout=(10,30))
        pt.build_payload([keyword], timeframe="today 3-m", geo=geo)
        related = pt.related_queries()
        if keyword in related and related[keyword]["top"] is not None:
            return related[keyword]["top"]["query"].tolist()[:10]
        return []
    except Exception as e:
        logger.error(f"[MARKETING] Related queries error: {e}")
        return []

def analyze_with_llm(data: dict, task_desc: str) -> str:
    try:
        model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        skills = search_skills(task_desc, agent="marketing", limit=2)
        prompt = f"""Ти — експерт з маркетингу та дропшипінгу в Україні.
Проаналізуй дані та дай конкретні рекомендації.

Задача: {task_desc}
{skills}

Дані:
{json.dumps(data, ensure_ascii=False)}

Дай відповідь у форматі:
1. Ключові висновки (3-5 пунктів)
2. Топ-3 рекомендації для дропшипінгу
3. Ризики та застереження

Відповідай українською мовою."""
        return request_llm(model, prompt)
    except Exception as e:
        logger.error(f"[MARKETING] LLM error: {e}")
        return f"Помилка аналізу: {e}"

def save_report(report_type: str, data: dict, analysis: str):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO event_logs (agent_id, level, message, metadata)
            SELECT a.id, 'INFO', %s, %s
            FROM agents a WHERE a.name = %s
        """, (f"Marketing report: {report_type}", json.dumps({"analysis": analysis, "data": data}, ensure_ascii=False), AGENT_NAME))
        conn.commit(); cur.close(); conn.close()
        logger.success(f"[MARKETING] Report saved: {report_type}")
    except Exception as e:
        logger.error(f"[MARKETING] Save error: {e}")

async def run_trends_analysis(keywords: list = None):
    if not keywords:
        keywords = ["навушники", "смартфон", "ноутбук", "планшет", "розумний годинник"]
    logger.info(f"[MARKETING] Analyzing trends: {keywords}")
    update_agent_status(AGENT_NAME, "busy")
    log_event(AGENT_NAME, "INFO", "Starting trends analysis", {"keywords": keywords})

    trends_data = get_google_trends(keywords)
    related = {}
    for kw in keywords[:2]:
        related[kw] = get_related_queries(kw)
    data = {"trends": trends_data, "related_queries": related, "analyzed_at": datetime.now().isoformat()}
    analysis = analyze_with_llm(data, "Аналіз трендів для дропшипінгу в Україні")
    save_report("trends_analysis", data, analysis)

    top_trending = sorted(trends_data.items(), key=lambda x: x[1].get("avg", 0), reverse=True)[:3] if trends_data else []
    if top_trending:
        msg = "Топ тренди: " + ", ".join([f"{k} (avg:{v['avg']:.0f})" for k, v in top_trending])
        create_alert(AGENT_NAME, "Аналіз трендів завершено", msg, "INFO")

    update_agent_status(AGENT_NAME, "idle")
    logger.success("[MARKETING] Trends analysis done")
    return {"trends": trends_data, "analysis": analysis}

async def run_competitor_analysis(category: str = "електроніка"):
    logger.info(f"[MARKETING] Competitor analysis: {category}")
    update_agent_status(AGENT_NAME, "busy")
    log_event(AGENT_NAME, "INFO", f"Competitor analysis: {category}")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT marketplace, COUNT(*) as count,
               AVG(price) as avg_price, MIN(price) as min_price, MAX(price) as max_price
        FROM scraped_products WHERE category ILIKE %s
        GROUP BY marketplace
    """, (f"%{category}%",))
    stats = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT title, price, marketplace, url FROM scraped_products WHERE category ILIKE %s ORDER BY price ASC LIMIT 20", (f"%{category}%",))
    products = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()

    data = {"category": category, "marketplace_stats": stats, "cheapest_products": products}
    analysis = analyze_with_llm(data, f"Аналіз конкурентів у категорії {category} для дропшипінгу")
    save_report("competitor_analysis", data, analysis)

    update_agent_status(AGENT_NAME, "idle")
    logger.success("[MARKETING] Competitor analysis done")
    return {"stats": stats, "analysis": analysis}

def listen_loop():
    logger.info("[MARKETING] Listening queue:marketing...")
    update_agent_status(AGENT_NAME, "idle")
    while True:
        try:
            task = pop_task("queue:marketing", timeout=5)
            if task:
                task_type = task.get("type", "")
                desc = task.get("description","").lower()
                if "trend" in task_type.lower() or "тренд" in desc:
                    asyncio.run(run_trends_analysis())
                elif "competitor" in task_type.lower() or "конкурент" in desc:
                    asyncio.run(run_competitor_analysis())
                else:
                    asyncio.run(run_trends_analysis())
        except Exception as e:
            logger.error(f"[MARKETING] Loop error: {e}")
            update_agent_status(AGENT_NAME, "idle")
            import time; time.sleep(5)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--trends", action="store_true")
    parser.add_argument("--competitors", type=str, default="електроніка")
    parser.add_argument("--listen", action="store_true")
    args = parser.parse_args()

    if args.trends:
        result = asyncio.run(run_trends_analysis())
        print(result.get("analysis", ""))
    elif args.competitors:
        result = asyncio.run(run_competitor_analysis(args.competitors))
        print(result.get("analysis", ""))
    elif args.listen:
        listen_loop()
    else:
        parser.print_help()
