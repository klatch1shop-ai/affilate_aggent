import os, json, time, uuid, httpx
import redis as redis_lib
from loguru import logger
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
QUEUE_KEY = "queue:ollama"
RESULT_TTL = 300  # 5 хвилин

def get_redis():
    return redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def ollama_generate(model: str, prompt: str, timeout: int = 120) -> str:
    """Прямий виклик Ollama API"""
    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        logger.error(f"[OLLAMA] Generate error: {e}")
        raise

def request_llm(model: str, prompt: str, timeout: int = 120) -> str:
    """
    Відправити запит до Ollama через чергу.
    Викликається з агентів замість прямого OllamaLLM.
    Блокує до отримання відповіді.
    """
    rd = get_redis()
    request_id = str(uuid.uuid4())
    result_key = f"ollama:result:{request_id}"

    task = {
        "id": request_id,
        "model": model,
        "prompt": prompt,
        "timeout": timeout,
        "result_key": result_key,
        "created_at": time.time()
    }

    rd.lpush(QUEUE_KEY, json.dumps(task))
    logger.debug(f"[OLLAMA CLIENT] Queued request {request_id[:8]} model={model}")

    # Чекаємо результат (блокуючий pop з таймаутом)
    deadline = time.time() + timeout + 30
    while time.time() < deadline:
        result_raw = rd.get(result_key)
        if result_raw:
            rd.delete(result_key)
            result = json.loads(result_raw)
            if result.get("error"):
                raise Exception(result["error"])
            return result.get("response", "")
        time.sleep(0.5)

    raise TimeoutError(f"Ollama request {request_id[:8]} timed out after {timeout}s")

def run_worker():
    """
    Воркер — запускається окремим процесом.
    Обробляє запити по одному, щоб не перевантажувати GPU.
    """
    rd = get_redis()
    logger.info(f"[OLLAMA WORKER] Started. Listening {QUEUE_KEY}...")

    while True:
        try:
            # Блокуючий pop — чекає задачу
            item = rd.brpop(QUEUE_KEY, timeout=5)
            if not item:
                continue

            _, raw = item
            task = json.loads(raw)
            request_id = task["id"]
            model = task["model"]
            result_key = task["result_key"]

            # Перевірка чи задача не застаріла
            age = time.time() - task.get("created_at", time.time())
            if age > task.get("timeout", 120):
                logger.warning(f"[OLLAMA WORKER] Skipping stale request {request_id[:8]} (age={age:.0f}s)")
                continue

            logger.info(f"[OLLAMA WORKER] Processing {request_id[:8]} model={model} prompt_len={len(task['prompt'])}")
            start = time.time()

            try:
                response = ollama_generate(model, task["prompt"], task.get("timeout", 120))
                elapsed = time.time() - start
                logger.success(f"[OLLAMA WORKER] Done {request_id[:8]} in {elapsed:.1f}s")
                result = {"response": response, "elapsed": elapsed}
            except Exception as e:
                logger.error(f"[OLLAMA WORKER] Error {request_id[:8]}: {e}")
                result = {"error": str(e)}

            rd.set(result_key, json.dumps(result), ex=RESULT_TTL)

        except Exception as e:
            logger.error(f"[OLLAMA WORKER] Loop error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    run_worker()
