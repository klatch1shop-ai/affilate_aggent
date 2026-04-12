import psycopg2
import httpx
from bs4 import BeautifulSoup
import time
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

def get_product_to_process():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    # Беремо один товар зі статусом 'new' (наприклад, з обладнання)
    cur.execute("SELECT sku, name_uk FROM products WHERE status = 'new' LIMIT 1;")
    res = cur.fetchone()
    cur.close()
    conn.close()
    return res

def fetch_specs(sku):
    print(f"🔍 Шукаємо технічні характеристики для артикула: {sku}...")
    # Формуємо прямий пошуковий запит на сайт постачальника
    url = f"https://www.grandinstrument.ua/search/?search={sku}"
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        with httpx.Client(headers=headers, follow_redirects=True) as client:
            response = client.get(url)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                # Шукаємо блок з описом або характеристиками
                # На багатьох сайтах це блоки з класами 'description' або 'characteristics'
                text = soup.get_text(separator=' ', strip=True)
                return text[:2000] # Беремо перші 2000 символів для аналізу AI
    except Exception as e:
        return f"Помилка збору: {e}"
    return "Дані не знайдено"

def start():
    product = get_product_to_process()
    if not product:
        print("📭 Всі товари вже оброблені!")
        return

    sku, name = product
    print(f"📦 Товар з бази: {name}")
    
    raw_data = fetch_specs(sku)
    
    if len(raw_data) > 100:
        print(f"✅ Дані знайдено! (отримано {len(raw_data)} символів)")
        print("\n--- ПЕРЕДАЧА В OLLAMA ---")
        print(f"Зараз твоя RTX 4050 отримає цей текст і сформує опис для Епіцентру.")
    else:
        print("⚠️ Не вдалося знайти детальні характеристики автоматично.")

if __name__ == "__main__":
    start()
