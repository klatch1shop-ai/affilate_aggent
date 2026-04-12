import os, sys, json, asyncio
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

from shared.utils.ollama_worker import request_llm
from shared.utils.skills_indexer import search_skills
from shared.utils.db import log_event, update_agent_status, create_alert, get_connection
from shared.utils.redis_queue import pop_task

AGENT_NAME = "developer"
OLLAMA_MODEL = os.getenv("DEV_OLLAMA_MODEL", "deepseek-coder-v2")

def get_llm(model=None):
    return model or os.getenv('OLLAMA_MODEL', 'llama3.2:3b'), temperature=0.2)

def write_code(task_description: str, language: str = "python") -> str:
    model = os.getenv("OLLAMA_DEV_MODEL", "deepseek-coder:6.7b-instruct-q4_K_M")
    skills = search_skills(task_description, agent="developer", limit=2)
    prompt = f"""Ти — senior розробник. Напиши повний робочий код.

{skills}

Мова: {language}
Задача: {task_description}

Вимоги:
- Чистий, робочий код
- Коментарі українською
- Обробка помилок
- Готовий до використання

Поверни ТІЛЬКИ код без пояснень."""
    return request_llm(model, prompt, timeout=180)

def analyze_code(code: str) -> str:
    model = os.getenv("OLLAMA_DEV_MODEL", "deepseek-coder:6.7b-instruct-q4_K_M")
    prompt = f"""Проаналізуй код і дай короткий звіт:
1. Що робить цей код
2. Можливі проблеми
3. Рекомендації щодо покращення

Код:
{code}

Відповідай українською мовою."""
    return request_llm(model, prompt, timeout=180)

async def handle_task(task: dict):
    desc = task.get("description", "")
    task_type = task.get("type", "")
    logger.info(f"[DEV] Task: {task_type} — {desc}")
    update_agent_status(AGENT_NAME, "busy")
    log_event(AGENT_NAME, "INFO", f"Dev task: {desc[:100]}")

    lang = "python"
    if "javascript" in desc.lower() or "js" in desc.lower(): lang = "javascript"
    elif "sql" in desc.lower(): lang = "sql"
    elif "bash" in desc.lower(): lang = "bash"

    code = write_code(desc, lang)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = {"python":"py","javascript":"js","sql":"sql","bash":"sh"}.get(lang,"txt")
    filename = f"task_{timestamp}.{ext}"
    filepath = save_code(filename, code, desc)
    create_alert(AGENT_NAME, f"Код написано: {filename}", f"Задача: {desc[:100]}", "INFO")
    update_agent_status(AGENT_NAME, "idle")
    return {"file": filepath, "lines": len(code.splitlines())}

def listen_loop():
    logger.info("[DEV] Listening queue:developer...")
    update_agent_status(AGENT_NAME, "idle")
    while True:
        task = pop_task("queue:developer", timeout=5)
        if task:
            asyncio.run(handle_task(task))

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", type=str, help="Написати код за описом")
    parser.add_argument("--listen", action="store_true")
    args = parser.parse_args()
    if args.code:
        update_agent_status(AGENT_NAME, "busy")
        result = write_code(args.code)
        print(result)
        update_agent_status(AGENT_NAME, "idle")
    elif args.listen:
        listen_loop()
    else:
        parser.print_help()
