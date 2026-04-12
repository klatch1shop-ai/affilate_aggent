import os, hashlib, time
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from loguru import logger
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

client = QdrantClient(host=os.getenv("QDRANT_HOST", "localhost"), port=int(os.getenv("QDRANT_PORT", 6333)))
COLLECTION = "agent_memory"
VECTOR_SIZE = 384

def ensure_collection():
    try:
        client.get_collection(COLLECTION)
    except:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
        )
        logger.info("[MEMORY] Collection created")

def get_embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")

def save_memory(agent_name: str, content: str, metadata: dict = None):
    try:
        ensure_collection()
        embedder = get_embedder()
        vector = embedder.encode(content).tolist()
        point_id = int(hashlib.md5(f"{agent_name}:{content[:100]}:{time.time()}".encode()).hexdigest()[:8], 16)
        client.upsert(collection_name=COLLECTION, points=[
            PointStruct(id=point_id, vector=vector, payload={
                "agent": agent_name,
                "content": content[:1000],
                "metadata": metadata or {},
                "timestamp": time.time()
            })
        ])
        logger.info(f"[MEMORY] Saved for {agent_name}: {content[:50]}")
        return True
    except Exception as e:
        logger.error(f"[MEMORY] Save error: {e}")
        return False

def search_memory(query: str, agent_name: str = None, limit: int = 5) -> list:
    try:
        ensure_collection()
        embedder = get_embedder()
        vector = embedder.encode(query).tolist()
        filter_cond = None
        if agent_name:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            filter_cond = Filter(must=[FieldCondition(key="agent", match=MatchValue(value=agent_name))])
        results = client.query_points(
            collection_name=COLLECTION,
            query=vector,
            limit=limit,
            query_filter=filter_cond
        ).points
        return [{"content": r.payload["content"], "score": r.score, "agent": r.payload["agent"]} for r in results]
    except Exception as e:
        logger.error(f"[MEMORY] Search error: {e}")
        return []

def get_context_for_task(task: str, agent_name: str = None) -> str:
    memories = search_memory(task, agent_name, limit=3)
    if not memories:
        return ""
    context = "\n\nРелевантний досвід з памяті:\n"
    for m in memories:
        context += f"- [{m['agent']}] {m['content'][:200]}\n"
    return context
