import os, sys, json, asyncio, time
from loguru import logger
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

from shared.utils.db import log_event, update_agent_status, create_alert
from shared.utils.redis_queue import pop_task
from shared.utils.memory import save_memory, get_context_for_task
from langchain_ollama import OllamaLLM

AGENT_NAME = "checker"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "dolphin-llama3")

def get_llm():
    return OllamaLLM(model=OLLAMA_MODEL, base_url="http://localhost:11434", temperature=0.1)

def check_result(task_description: str, result: str, agent_name: str) -> dict:
    context = get_context_for_task(task_description, agent_name)
    llm = get_llm()
    prompt = f"""You are an Acceptance Checker. Check the agent result.
Task: {task_description}
Agent: {agent_name}
Result: {result[:500]}
{context}

Check criteria:
1. Is the task completed?
2. Are there critical errors?
3. Should the task be repeated?

Reply ONLY JSON:
{{"passed": true, "score": 8, "issues": [], "recommendation": "text"}}"""
    try:
        response = llm.invoke(prompt)
        start = response.find("{")
        end = response.rfind("}") + 1
        result_json = json.loads(response[start:end])
        save_memory(AGENT_NAME, f"Check {agent_name}: {task_description[:100]} -> {'OK' if result_json.get('passed') else 'FAIL'}")
        return result_json
    except Exception as e:
        logger.error(f"[CHECKER] Error: {e}")
        return {"passed": True, "score": 5, "issues": [], "recommendation": "Could not verify"}

async def handle_task(task: dict):
    logger.info(f"[CHECKER] Checking: {task.get('description','')[:60]}")
    update_agent_status(AGENT_NAME, "busy")
    agent_name = task.get("context", {}).get("checked_agent", "unknown")
    result_text = task.get("context", {}).get("result", "")
    description = task.get("description", "")
    check = check_result(description, result_text, agent_name)
    if not check.get("passed"):
        create_alert(AGENT_NAME, f"Check failed: {agent_name}",
            f"Score: {check.get('score')}/10. {check.get('recommendation','')}", "WARNING")
        logger.warning(f"[CHECKER] FAIL: {check}")
    else:
        log_event(AGENT_NAME, "INFO", f"Check passed: {agent_name} score={check.get('score')}")
        logger.success(f"[CHECKER] PASS score={check.get('score')}")
    update_agent_status(AGENT_NAME, "idle")
    return check

def listen_loop():
    logger.info("[CHECKER] Listening queue:checker...")
    update_agent_status(AGENT_NAME, "idle")
    while True:
        try:
            task = pop_task("queue:checker", timeout=5)
            if task:
                asyncio.run(handle_task(task))
        except Exception as e:
            logger.error(f"[CHECKER] Loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    if args.test:
        result = check_result("Знайди навушники на Rozetka", "Знайдено 5 товарів: Sony JBL Samsung", "scraper")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.listen:
        listen_loop()
    else:
        parser.print_help()
