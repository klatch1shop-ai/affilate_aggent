import os, sys, json, time
from dotenv import load_dotenv
from loguru import logger
from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

from shared.utils.db import log_event, create_alert, update_agent_status, get_connection
from shared.utils.redis_queue import push_task, pop_task, get_queue_length
from shared.utils.skill_loader import load_all_skills, get_skills_context

AGENT_NAME = "orchestrator"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "dolphin-llama3")

AGENT_QUEUES = {
    "scraper": "queue:scraper",
    "marketing": "queue:marketing",
    "developer": "queue:developer",
    "finance": "queue:finance",
    "efficiency": "queue:efficiency",
}

def get_llm():
    return OllamaLLM(model=OLLAMA_MODEL, base_url="http://localhost:11434", temperature=0.1)

def get_system_snapshot() -> dict:
    try:
        import redis as r
        rd = r.Redis(host="localhost", port=6379, decode_responses=True)
        snap = rd.get("system:snapshot")
        return json.loads(snap) if snap else {}
    except:
        return {}

def save_system_snapshot(snapshot: dict):
    try:
        import redis as r
        rd = r.Redis(host="localhost", port=6379, decode_responses=True)
        rd.set("system:snapshot", json.dumps(snapshot, ensure_ascii=False))
    except Exception as e:
        logger.error(f"Snapshot save error: {e}")

def get_agents_status() -> dict:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, status FROM agents")
        result = {r["name"]: r["status"] for r in cur.fetchall()}
        cur.close(); conn.close()
        return result
    except:
        return {}

def route_task(command: str) -> dict:
    skills_context = load_all_skills("orchestrator")
    snapshot = get_system_snapshot()
    agents_status = get_agents_status()
    queues = {a: get_queue_length(f"queue:{a}") for a in AGENT_QUEUES}

    llm = get_llm()
    # Простий прямий промпт без template для кращої відповіді від Ollama
    full_prompt = f"""### Instruction:
You are a routing system. Analyze the admin command and return ONLY a JSON object.
Available agents: scraper, marketing, developer, finance, efficiency

Command: {command}

Agent descriptions:
- scraper: parse prices and products from Prom/Rozetka/Epicentr marketplaces
- marketing: analyze trends, competitors, find new products
- developer: write code, API integrations, CRM
- finance: calculate margins, financial reports, risks
- efficiency: monitor system performance, find anomalies

### Response (JSON only, no other text):
{{"agent": "agent_name", "task_type": "task_type", "description": "what to do", "priority": 7, "context": {{}}}}

### Assistant:
{{"""

    result = llm.invoke(full_prompt)
    try:
        # Очистити відповідь і знайти JSON
        clean = result.strip()
        # Якщо починається без { — додати
        if clean and not clean.startswith("{"):
            clean = "{" + clean
        # Прибрати все після останньої }
        end = clean.rfind("}") + 1
        clean = clean[:end]
        # Прибрати null і сміття після JSON
        clean = clean.split("\nnull")[0].split("\n\n")[0]
        decision = json.loads(clean)
        
        # Оновити snapshot
        snap = get_system_snapshot()
        snap["last_command"] = command
        snap["last_decision"] = decision
        snap["agents"] = agents_status
        snap["queues"] = queues
        save_system_snapshot(snap)
        
        return decision
    except Exception as e:
        logger.error(f"Parse error: {e} | raw: {result}")
        return None

def process_command(command: str):
    logger.info(f"[ORCHESTRATOR] Command: {command}")
    log_event(AGENT_NAME, "INFO", f"Command: {command}")
    update_agent_status(AGENT_NAME, "busy")

    decision = route_task(command)
    if not decision:
        create_alert(AGENT_NAME, "Помилка маршрутизації", "LLM не зміг прийняти рішення", "ERROR")
        update_agent_status(AGENT_NAME, "idle")
        return None

    agent = decision.get("agent")
    if agent not in AGENT_QUEUES:
        logger.warning(f"Unknown agent: {agent}")
        update_agent_status(AGENT_NAME, "idle")
        return None

    task = {
        "type": decision.get("task_type"),
        "description": decision.get("description"),
        "priority": decision.get("priority", 5),
        "context": decision.get("context", {}),
        "source": "orchestrator",
        "timestamp": time.time()
    }

    push_task(AGENT_QUEUES[agent], task)
    log_event(AGENT_NAME, "INFO", f"Task -> {agent}: {task['type']}", decision)
    create_alert(AGENT_NAME, f"Задача → {agent}", decision.get("description",""), "INFO")

    logger.success(f"[ORCHESTRATOR] -> {agent}: {task['type']}")
    update_agent_status(AGENT_NAME, "idle")
    return decision

def listen_loop():
    logger.info("[ORCHESTRATOR] Started with Skills support. Listening...")
    update_agent_status(AGENT_NAME, "idle")
    
    # Ініціалізувати snapshot
    snap = {
        "goal": "Автоматизація дропшипінг-бізнесу на Prom, Rozetka, Епіцентр",
        "started_at": time.time(),
        "agents": get_agents_status(),
        "queues": {}
    }
    save_system_snapshot(snap)
    
    while True:
        try:
            task = pop_task("queue:orchestrator", timeout=5)
            if task:
                command = task.get("description", "")
                if command:
                    process_command(command)
        except Exception as e:
            logger.error(f"[ORCHESTRATOR] Loop error: {e}")
            update_agent_status(AGENT_NAME, "idle")
            time.sleep(5)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cmd", type=str)
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args()

    if args.cmd:
        result = process_command(args.cmd)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.snapshot:
        snap = get_system_snapshot()
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    elif args.listen:
        listen_loop()
    else:
        parser.print_help()
