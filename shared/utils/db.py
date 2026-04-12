import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from loguru import logger

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", 5432),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        cursor_factory=RealDictCursor
    )

def log_event(agent_name: str, level: str, message: str, metadata: dict = None):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM agents WHERE name = %s", (agent_name,)
        )
        row = cur.fetchone()
        agent_id = row["id"] if row else None
        cur.execute(
            """INSERT INTO event_logs (agent_id, level, message, metadata)
               VALUES (%s, %s, %s, %s)""",
            (agent_id, level, message, psycopg2.extras.Json(metadata or {}))
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"DB log error: {e}")

def create_alert(source: str, title: str, message: str, level: str = "INFO"):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO alerts (source, title, message, level)
               VALUES (%s, %s, %s, %s)""",
            (source, title, message, level)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Alert error: {e}")

def update_agent_status(agent_name: str, status: str):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """UPDATE agents SET status = %s, updated_at = NOW()
               WHERE name = %s""",
            (status, agent_name)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Status update error: {e}")
