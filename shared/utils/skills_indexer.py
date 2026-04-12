import os, glob, hashlib
from loguru import logger
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "../../shared/skills")
COLLECTION = "agent_skills"
VECTOR_SIZE = 384

client = QdrantClient(
    host=os.getenv("QDRANT_HOST", "localhost"),
    port=int(os.getenv("QDRANT_PORT", 6333))
)

_embedder = None

def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder

def ensure_collection():
    try:
        client.get_collection(COLLECTION)
        logger.info(f"[SKILLS RAG] Collection '{COLLECTION}' exists")
    except:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
        )
        logger.info(f"[SKILLS RAG] Collection '{COLLECTION}' created")

def index_all_skills():
    ensure_collection()
    embedder = get_embedder()

    skill_files = glob.glob(os.path.join(SKILLS_DIR, "**/*.md"), recursive=True)
    skill_files += glob.glob(os.path.join(SKILLS_DIR, "*.md"))
    skill_files = list(set(skill_files))

    logger.info(f"[SKILLS RAG] Found {len(skill_files)} skill files")
    points = []

    for path in skill_files:
        with open(path) as f:
            content = f.read()

        # Визначаємо агента з шляху
        parts = path.replace(SKILLS_DIR, "").strip("/").split("/")
        agent = parts[0] if len(parts) > 1 else "global"
        skill_name = os.path.basename(path).replace(".md", "")

        # Розбиваємо на chunks по 500 символів з overlap
        chunks = []
        if len(content) <= 600:
            chunks = [content]
        else:
            step = 400
            size = 600
            for i in range(0, len(content), step):
                chunk = content[i:i+size]
                if chunk.strip():
                    chunks.append(chunk)

        for i, chunk in enumerate(chunks):
            vector = embedder.encode(chunk).tolist()
            point_id = int(hashlib.md5(f"{path}:{i}".encode()).hexdigest()[:8], 16)
            points.append(PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "agent": agent,
                    "skill_name": skill_name,
                    "path": path,
                    "chunk_index": i,
                    "content": chunk,
                    "full_skill_name": f"{agent}/{skill_name}"
                }
            ))

    # Зберігаємо батчами
    batch_size = 50
    for i in range(0, len(points), batch_size):
        batch = points[i:i+batch_size]
        client.upsert(collection_name=COLLECTION, points=batch)

    logger.success(f"[SKILLS RAG] Indexed {len(points)} chunks from {len(skill_files)} skills")
    return len(points)

def search_skills(query: str, agent: str = None, limit: int = 3) -> str:
    """
    Шукає релевантні skills по запиту.
    Повертає текст для вставки в промпт.
    """
    try:
        ensure_collection()
        embedder = get_embedder()
        vector = embedder.encode(query).tolist()

        filter_cond = None
        if agent:
            filter_cond = Filter(must=[
                FieldCondition(key="agent", match=MatchValue(value=agent))
            ])

        results = client.query_points(
            collection_name=COLLECTION,
            query=vector,
            limit=limit,
            query_filter=filter_cond
        ).points

        if not results:
            return ""

        context = "\n\n### Релевантні інструкції:\n"
        seen_skills = set()
        for r in results:
            skill_key = r.payload["full_skill_name"]
            if skill_key not in seen_skills:
                seen_skills.add(skill_key)
                context += f"\n**{r.payload['skill_name']}** (score={r.score:.2f}):\n"
                context += r.payload["content"] + "\n"

        return context

    except Exception as e:
        logger.error(f"[SKILLS RAG] Search error: {e}")
        return ""

if __name__ == "__main__":
    count = index_all_skills()
    print(f"\n✅ Проіндексовано {count} chunks")
    print("\nТест пошуку 'аналіз конкурентів':")
    result = search_skills("аналіз конкурентів", agent="marketing")
    print(result[:500])
