import psycopg2
import httpx
from bs4 import BeautifulSoup
import json
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
OLLAMA_URL = os.getenv("OLLAMA_URL")
MODEL_NAME = os.getenv("OLLAMA_MODEL")

def fetch_data(sku):
    url = f"https://www.grandinstrument.ua/search/?search={sku}"
    try:
        with httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=15.0) as client:
            resp = client.get(url)
            soup = BeautifulSoup(resp.text, 'html.parser')
            return soup.get_text(separator=' ', strip=True)[:4000]
    except: return ""

def process_batch(limit=5):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # Беремо 5 товарів, які ще не оброблені
    cur.execute("SELECT sku, name_uk FROM products WHERE status = 'new' LIMIT %s;", (limit,))
    products = cur.fetchall()
    
    for sku, name in products:
        print(f"🔄 Обробка: {sku}...")
        raw_text = fetch_data(sku)
        
        prompt = f"Зроби опис для Епіцентру. Товар: {name}, Артикул: {sku}. Текст: {raw_text}. Відповідай ТІЛЬКИ JSON: title, description, specs (dict), category."
        
        try:
            resp = httpx.post(OLLAMA_URL, json={"model": MODEL_NAME, "prompt": prompt, "stream": False, "format": "json"}, timeout=120.0)
            ai_data = json.loads(resp.json().get("response"))
            
            # Зберігаємо в базу
            cur.execute("""
                UPDATE products 
                SET title_epicentr = %s, description_epicentr = %s, specs_json = %s, category_epicentr = %s, status = 'processed'
                WHERE sku = %s
            """, (ai_data.get('title'), ai_data.get('description'), json.dumps(ai_data.get('specs')), ai_data.get('category'), sku))
            conn.commit()
            print(f"✅ Збережено: {sku}")
        except Exception as e:
            print(f"❌ Помилка {sku}: {e}")
            
    cur.close()
    conn.close()

if __name__ == "__main__":
    process_batch(5) # Спробуємо обробити 5 штук за раз
