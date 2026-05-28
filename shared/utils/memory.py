import os, hashlib, time, json
import redis
from loguru import logger
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../.env'))

rd = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    decode_responses=True
)

def save_memory(agent_name: str, content: str, metadata: dict = None):
    try:
        point_id = int(hashlib.md5(f'{agent_name}:{content[:100]}:{time.time()}'.encode()).hexdigest()[:8], 16)
        task = {
            'action': 'embed',
            'text': content,
            'collection': 'agent_memory',
            'point_id': point_id,
            'payload': {
                'agent': agent_name,
                'content': content[:1000],
                'metadata': metadata or {},
                'timestamp': time.time()
            }
        }
        rd.rpush('queue:embeddings', json.dumps(task, ensure_ascii=False))
        logger.info(f'[MEMORY] Queued embed for {agent_name}: {content[:50]}')
        return True
    except Exception as e:
        logger.error(f'[MEMORY] Error: {e}')
        return False

def search_memory(query: str, agent_name: str = None, limit: int = 5) -> list:
    try:
        reply_key = f'reply:memory:{int(time.time()*1000)}'
        task = {
            'action': 'search',
            'text': query,
            'collection': 'agent_memory',
            'limit': limit,
            'agent_filter': agent_name,
            'reply_key': reply_key
        }
        rd.rpush('queue:embeddings', json.dumps(task, ensure_ascii=False))
        for _ in range(20):
            result = rd.get(reply_key)
            if result:
                return json.loads(result)
            time.sleep(0.5)
        return []
    except Exception as e:
        logger.error(f'[MEMORY] Search error: {e}')
        return []

def get_context_for_task(task: str, agent_name: str = None) -> str:
    memories = search_memory(task, agent_name, limit=3)
    if not memories:
        return ''
    context = '\n\nРелевантний досвід з памяті:\n'
    for m in memories:
        context += f'- [{m.get("payload",{}).get("agent","?")}] {m.get("content","")[:200]}\n'
    return context
