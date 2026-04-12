import requests
import xml.etree.ElementTree as ET
import json
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

# 1. Налаштування
XML_URL = os.getenv("TOPTUL_FEED_URL")
OLLAMA_URL = os.getenv("OLLAMA_URL")
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

def extract_attributes_with_ai(name, description):
    prompt = f"""
    Ти експерт з інструментів Toptul. Проаналізуй цей товар:
    Назва: {name}
    Опис: {description}
    
    Знайди і поверни ТІЛЬКИ JSON об'єкт з такими ключами:
    - "матеріал"
    - "кількість_предметів"
    - "тип_інструменту"
    
    Відповідь має бути ТІЛЬКИ валідним JSON кодом без зайвих слів.
    """
    
    payload = {
        "model": "llama3.2:3b",
        "prompt": prompt,
        "stream": False,
        "format": "json"
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=payload)
        return json.loads(response.json()['response'])
    except Exception as e:
        print(f"Помилка Ollama: {e}")
        return None

def main():
    print("1. Завантажуємо фід...")
    response = requests.get(XML_URL)
    root = ET.fromstring(response.content)
    
    offer = root.find('.//offer')
    if offer is None:
        print("Товари не знайдені.")
        return

    sku = offer.find('vendorCode').text if offer.find('vendorCode') is not None else offer.get('id')
    name = offer.find('name').text
    description = offer.find('description').text if offer.find('description') is not None else ""
    
    print(f"\n2. Товар: {name}")
    print("3. AI аналізує...")
    
    attributes = extract_attributes_with_ai(name, description)
    print(f"AI результат: {json.dumps(attributes, ensure_ascii=False, indent=2)}")
    
    if attributes:
        try:
            conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO products (sku, name_uk, description_raw, attributes, status)
                VALUES (%s, %s, %s, %s, 'ready')
                ON CONFLICT (sku) DO UPDATE SET attributes = EXCLUDED.attributes;
            """, (sku, name, description, json.dumps(attributes)))
            conn.commit()
            cur.close()
            conn.close()
            print("✅ Збережено в БД на сервері!")
        except Exception as e:
            print(f"❌ Помилка БД: {e}")

if __name__ == "__main__":
    main()
