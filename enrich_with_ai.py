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

def fetch_precise_data(sku):
    search_url = f"https://www.grandinstrument.ua/search/?search={sku}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=15.0) as client:
            resp = client.get(search_url)
            soup = BeautifulSoup(resp.text, 'html.parser')
            features = ""
            table = soup.find('table')
            if table:
                features = table.get_text(separator=' ', strip=True)
            if len(features) < 100:
                main_content = soup.find('main') or soup.find('div', id='content')
                if main_content:
                    features = main_content.get_text(separator=' ', strip=True)
            return features[:4000]
    except:
        return ""

def ask_ollama(raw_text, sku, original_name):
    prompt = f"""
    Ти - професійний контент-менеджер Епіцентру.
    Твоє завдання: створити ідеальну картку товару для {original_name} (артикул {sku}).
    
    ВИМОГИ:
    1. title: Має бути у форматі "Насадка (біта) Toptul 1/4" SL3x0,5мм 25мм {sku}" (або відповідний типу товару заголовок)
    2. description: Напиши 3 речення. Обов'язково згадай бренд Toptul та міцність матеріалів.
    3. specs: Витягни тільки технічні параметри.
    4. category: Вибери найбільш підходящу категорію для Епіцентру.

    ТЕКСТ ДЛЯ АНАЛІЗУ:
    {raw_text}

    Відповідай ТІЛЬКИ чистим JSON.
    """
    payload = {"model": MODEL_NAME, "prompt": prompt, "stream": False, "format": "json"}
    try:
        resp = httpx.post(OLLAMA_URL, json=payload, timeout=120.0)
        return resp.json().get("response")
    except:
        return None

def process():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        # Шукаємо товар GAAR (набір інструментів), щоб побачити багаті дані
        cur.execute("SELECT sku, name_uk FROM products WHERE sku LIKE 'GAAR%' LIMIT 1;")
        product = cur.fetchone()
        cur.close()
        conn.close()
        
        if product:
            sku, name = product
            print(f"🛠️ Обробляємо інструмент: {name} ({sku})")
            raw_data = fetch_precise_data(sku)
            result = ask_ollama(raw_data, sku, name)
            print("\n💎 ГОТОВА КАРТКА ДЛЯ ЕПІЦЕНТРУ:")
            print(result)
        else:
            print("❌ Товар з артикулом GAAR не знайдено в базі.")
    except Exception as e:
        print(f"❌ Помилка БД: {e}")

if __name__ == "__main__":
    process()
