import os, sys, json, asyncio
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger
from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

from shared.utils.db import log_event, update_agent_status, create_alert, get_connection
from shared.utils.redis_queue import pop_task, get_queue_length

AGENT_NAME = "efficiency"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "dolphin-llama3")

def get_llm():
    return OllamaLLM(model=OLLAMA_MODEL, base_url="http://localhost:11434", temperature=0.2)

def collect_system_metrics() -> dict:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, status, updated_at FROM agents ORDER BY name")
        agents = [dict(r) for r in cur.fetchall()]
        cur.execute("""
            SELECT a.name, el.level, COUNT(*) as cnt
            FROM event_logs el
            JOIN agents a ON el.agent_id = a.id
            WHERE el.created_at > NOW() - INTERVAL '24 hours'
            GROUP BY a.name, el.level ORDER BY a.name
        """)
        logs_24h = [dict(r) for r in cur.fetchall()]
        cur.execute("""
            SELECT level, COUNT(*) as cnt FROM alerts
            WHERE created_at > NOW() - INTERVAL '24 hours'
            GROUP BY level
        """)
        alerts_24h = {r["level"]: r["cnt"] for r in cur.fetchall()}
        cur.execute("""
            SELECT a.name,
                COUNT(*) FILTER (WHERE el.level = 'ERROR') as errors,
                COUNT(*) FILTER (WHERE el.level = 'INFO') as info,
                MAX(el.created_at) as last_active
            FROM agents a
            LEFT JOIN event_logs el ON el.agent_id = a.id
            GROUP BY a.name
        """)
        agent_health = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()

        queues = {a: get_queue_length(f"queue:{a}") for a in
                  ["orchestrator","scraper","marketing","developer","finance","efficiency"]}

        for h in agent_health:
            if h.get("last_active"):
                h["last_active"] = h["last_active"].isoformat()

        for a in agents:
            if a.get("updated_at"):
                a["updated_at"] = a["updated_at"].isoformat()

        return {
            "agents": agents,
            "logs_24h": logs_24h,
            "alerts_24h": alerts_24h,
            "agent_health": agent_health,
            "queues": queues,
            "collected_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"[EFFICIENCY] Metrics error: {e}")
        return {}

def analyze_performance(metrics: dict) -> str:
    try:
        llm = get_llm()
        prompt = PromptTemplate(
            input_variables=["metrics"],
            template="""Ти — системний аналітик мультиагентної системи автоматизації бізнесу.

Проаналізуй метрики системи за останні 24 години:
{metrics}

Дай структурований звіт:
1. Загальний стан системи (здорова/є проблеми/критично)
2. Які агенти працюють добре, які мають проблеми
3. Вузькі місця та неефективності
4. Конкретні кроки для покращення продуктивності
5. Рекомендації щодо нових скілів або правил для агентів

Відповідай українською. Будь конкретним і actionable."""
        )
        chain = prompt | llm
        return chain.invoke({"metrics": json.dumps(metrics, ensure_ascii=False, default=str)})
    except Exception as e:
        return f"Помилка аналізу: {e}"

def detect_anomalies(metrics: dict) -> list:
    anomalies = []
    health = metrics.get("agent_health", [])
    for agent in health:
        errors = agent.get("errors") or 0
        if errors > 5:
            anomalies.append({
                "agent": agent["name"],
                "type": "high_errors",
                "value": errors,
                "message": f"Агент {agent['name']} має {errors} помилок за 24 год"
            })
    queues = metrics.get("queues", {})
    for agent, count in queues.items():
        if count > 10:
            anomalies.append({
                "agent": agent,
                "type": "queue_overflow",
                "value": count,
                "message": f"Черга агента {agent} переповнена: {count} задач"
            })
    agents = metrics.get("agents", [])
    offline = [a for a in agents if a["status"] == "offline"]
    for a in offline:
        anomalies.append({
            "agent": a["name"],
            "type": "offline",
            "message": f"Агент {a['name']} офлайн"
        })
    return anomalies

async def run_efficiency_check():
    logger.info("[EFFICIENCY] Running system efficiency check...")
    update_agent_status(AGENT_NAME, "busy")
    log_event(AGENT_NAME, "INFO", "Efficiency check started")

    metrics = collect_system_metrics()
    anomalies = detect_anomalies(metrics)

    if anomalies:
        for a in anomalies:
            create_alert(AGENT_NAME, f"Аномалія: {a['type']}", a["message"], "WARNING")
            logger.warning(f"[EFFICIENCY] Anomaly: {a['message']}")

    analysis = analyze_performance(metrics)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO event_logs (agent_id, level, message, metadata)
        SELECT a.id, 'INFO', 'Efficiency report', %s
        FROM agents a WHERE a.name = %s
    """, (json.dumps({
        "metrics": metrics,
        "anomalies": anomalies,
        "analysis": analysis
    }, ensure_ascii=False, default=str), AGENT_NAME))
    conn.commit(); cur.close(); conn.close()

    create_alert(AGENT_NAME, "Перевірка ефективності завершена",
                 f"Аномалій: {len(anomalies)}. " + analysis[:150], "INFO")

    update_agent_status(AGENT_NAME, "idle")
    logger.success(f"[EFFICIENCY] Check done. Anomalies: {len(anomalies)}")
    return {"metrics": metrics, "anomalies": anomalies, "analysis": analysis}

def listen_loop():
    logger.info("[EFFICIENCY] Listening queue:efficiency...")
    update_agent_status(AGENT_NAME, "idle")
    while True:
        task = pop_task("queue:efficiency", timeout=5)
        if task:
            asyncio.run(run_efficiency_check())

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--listen", action="store_true")
    args = parser.parse_args()
    if args.check:
        result = asyncio.run(run_efficiency_check())
        print("\n=== АНОМАЛІЇ ===")
        for a in result.get("anomalies", []):
            print(f"  {a['message']}")
        print("\n=== АНАЛІЗ ===")
        print(result.get("analysis",""))
    elif args.listen:
        listen_loop()
    else:
        parser.print_help()
