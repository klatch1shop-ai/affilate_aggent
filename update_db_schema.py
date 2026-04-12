import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT", 5432),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

def update():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    # Додаємо колонки для результатів AI
    cur.execute("""
        ALTER TABLE products 
        ADD COLUMN IF NOT EXISTS title_epicentr TEXT,
        ADD COLUMN IF NOT EXISTS description_epicentr TEXT,
        ADD COLUMN IF NOT EXISTS specs_json JSONB,
        ADD COLUMN IF NOT EXISTS category_epicentr TEXT;
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Таблиця 'products' оновлена. Тепер є куди зберігати дані!")

if __name__ == "__main__":
    update()
