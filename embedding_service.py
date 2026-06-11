"""
Embedding Service — запускається на НОУТБУЦІ.
Слухає Redis чергу 'queue:embeddings', генерує вектори, зберігає в Qdrant на сервері.
"""
import os, json, time, glob, hashlib
import redis
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

SERVER_IP = os.getenv("SERVER_IP", "100.82.24.112")
rd = redis.Redis(host=SERVER_IP, port=6379, decode_responses=True)
qdrant = QdrantClient(host=SERVER_IP, port=6333)
model = SentenceTransformer("all-MiniLM-L6-v2")

COLLECTIONS = {
    "agent_memory": 384,
    "agent_skills": 384,
}

def ensure_collections():
    for name, size in COLLECTIONS.items():
        try:
            qdrant.get_collection(name)
        except:
            qdrant.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=size, distance=Distance.COSINE)
            )
            logger.info(f"Created collection: {name}")

def process_embed_request(task: dict):
    text = task.get("text", "")
    collection = task.get("collection", "agent_memory")
    point_id = task.get("point_id")
    payload = task.get("payload", {})
    vector = model.encode(text).tolist()
    qdrant.upsert(
        collection_name=collection,
        points=[PointStruct(id=point_id, vector=vector, payload=payload)]
    )
    logger.info(f"Embedded → {collection} | id={point_id} | {text[:50]}")

def process_search_request(task: dict):
    text = task.get("text", "")
    collection = task.get("collection", "agent_memory")
    limit = task.get("limit", 5)
    agent_filter = task.get("agent_filter")
    reply_key = task.get("reply_key")
    vector = model.encode(text).tolist()
    filter_cond = None
    if agent_filter:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        filter_cond = Filter(must=[FieldCondition(key="agent", match=MatchValue(value=agent_filter))])
    results = qdrant.query_points(
        collection_name=collection,
        query=vector,
        limit=limit,
        query_filter=filter_cond
    ).points
    output = [{"content": r.payload.get("content",""), "score": r.score, "payload": r.payload} for r in results]
    if reply_key:
        rd.set(reply_key, json.dumps(output, ensure_ascii=False), ex=30)

def index_skills():
    skills_dir = os.path.join(os.path.dirname(__file__), "shared/skills")
    files = list(set(
        glob.glob(os.path.join(skills_dir, "**/*.md"), recursive=True) +
        glob.glob(os.path.join(skills_dir, "*.md"))
    ))
    logger.info(f"[EMBEDDING SERVICE] Indexing {len(files)} skill files...")
    for path in files:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        parts = path.replace(skills_dir, "").strip("/").split("/")
        agent = parts[0] if len(parts) > 1 else "global"
        skill_name = os.path.basename(path).replace(".md", "")
        chunks = [content[i:i+600] for i in range(0, len(content), 400) if content[i:i+600].strip()]
        for i, chunk in enumerate(chunks):
            point_id = int(hashlib.md5(f"{path}:{i}".encode()).hexdigest()[:8], 16)
            process_embed_request({
                "text": chunk,
                "collection": "agent_skills",
                "point_id": point_id,
                "payload": {
                    "agent": agent,
                    "skill_name": skill_name,
                    "path": path,
                    "chunk_index": i,
                    "content": chunk,
                    "full_skill_name": f"{agent}/{skill_name}"
                }
            })
    logger.success(f"[EMBEDDING SERVICE] Done indexing {len(files)} files")

def listen():
    ensure_collections()
    logger.info(f"[EMBEDDING SERVICE] Started. Listening on {SERVER_IP}...")
    while True:
        try:
            item = rd.blpop("queue:embeddings", timeout=5)
            if not item:
                continue
            task = json.loads(item[1])
            action = task.get("action", "embed")
            if action == "embed":
                process_embed_request(task)
            elif action == "search":
                process_search_request(task)
            elif action == "index_skills":
                index_skills()
        except Exception as e:
            logger.error(f"[EMBEDDING SERVICE] Error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--index":
        ensure_collections()
        index_skills()
    else:
        listen()
