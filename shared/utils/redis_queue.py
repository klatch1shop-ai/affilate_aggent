import os
import json
import redis
from dotenv import load_dotenv
from loguru import logger

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

r = redis.Redis(
    host="localhost",
    port=int(os.getenv("REDIS_PORT", 6379)),
    decode_responses=True
)

def push_task(queue_name: str, task: dict):
    try:
        r.rpush(queue_name, json.dumps(task))
        logger.info(f"Task pushed to {queue_name}: {task.get('type')}")
    except Exception as e:
        logger.error(f"Redis push error: {e}")

def pop_task(queue_name: str, timeout: int = 5):
    try:
        result = r.blpop(queue_name, timeout=timeout)
        if result:
            _, data = result
            return json.loads(data)
    except Exception as e:
        logger.error(f"Redis pop error: {e}")
    return None

def get_queue_length(queue_name: str) -> int:
    return r.llen(queue_name)
