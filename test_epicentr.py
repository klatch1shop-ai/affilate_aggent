import httpx
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("EPICENTR_TOKEN")
BASE_URL = os.getenv("EPICENTR_API_URL")

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36"
}

def check():
    # Метод для перевірки токена (отримання власного профілю)
    url = f"{BASE_URL}/cabinet/profile" 
    print(f"🛰️ Тестуємо з'єднання: {url}")
    
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            if response.status_code == 200:
                print("✅ Успіх! Зв'язок з Епіцентром встановлено.")
                print("Дані профілю:", response.json())
            elif response.status_code == 401:
                print("❌ Помилка: Токен невірний або термін дії вичерпано (Unauthorized).")
            else:
                print(f"❌ Помилка API: {response.status_code}")
                # Спробуємо інший ендпоінт, якщо цей закритий
                print("Спробуємо отримати довідник категорій...")
                cat_url = f"{BASE_URL}/directories/categories"
                res_cat = client.get(cat_url, headers=headers)
                print(f"Статус категорій: {res_cat.status_code}")
                if res_cat.status_code == 200:
                     print("✅ Категорії отримано!")
    except Exception as e:
        print(f"❌ Помилка: {e}")

if __name__ == "__main__":
    check()
