import os, json, time
import redis
from loguru import logger
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../.env'))

rd = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    decode_responses=True
)

def index_all_skills():
    task = {'action': 'index_skills'}
    rd.rpush('queue:embeddings', json.dumps(task))
    logger.info('[SKILLS] index_all_skills task queued to embedding service')

def search_skills(query: str, agent: str = None, limit: int = 3) -> str:
    try:
        reply_key = f'reply:skills:{int(time.time()*1000)}'
        task = {
            'action': 'search',
            'text': query,
            'collection': 'agent_skills',
            'limit': limit,
            'agent_filter': agent,
            'reply_key': reply_key
        }
        rd.rpush('queue:embeddings', json.dumps(task, ensure_ascii=False))
        for _ in range(20):
            result = rd.get(reply_key)
            if result:
                results = json.loads(result)
                if not results:
                    return ''
                context = '\n\n### Релевантні інструкції:\n'
                seen = set()
                for r in results:
                    p = r.get('payload', {})
                    key = p.get('full_skill_name', '')
                    if key not in seen:
                        seen.add(key)
                        context += f'\n**{p.get("skill_name","")}** (score={r.get("score",0):.2f}):\n'
                        context += p.get('content', '') + '\n'
                return context
            time.sleep(0.5)
        return ''
    except Exception as e:
        logger.error(f'[SKILLS] Search error: {e}')
        return ''
