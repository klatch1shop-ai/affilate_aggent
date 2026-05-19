import os
import requests

def load_env():
    if os.path.exists('.env'):
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    os.environ[k.strip()] = v.strip('"').strip("'").strip()

def test_real_oms_route():
    load_env()
    token = os.getenv("EPICENTR_TOKEN")
    base_url = "https://merchant-api.epicentrm.com.ua"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Тестуємо реальний корінь OMS, який вказано в інструкції по статусах
    url = f"{base_url}/v2/oms/orders"
    
    print(f"[🔍] Стукаємо в офіційний OMS за адресою: {url}")
    try:
        # Епіцентр може вимагати чіткі параметри пагінації для GET
        params = {"limit": 10, "offset": 0}
        response = requests.get(url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            print("[🍏 УСПІХ!] OMS модуль відповів кодом 200.")
            print(f"Дані: {response.json()}")
        elif response.status_code == 405:
            print("[⚠️ МЕТОД ЗАБОРОНЕНО - 405]")
            print("Ендпоінт /v2/oms/orders існує, але не приймає GET запити без конкретного ID замовлення!")
            print("Це підтверджує інструкцію: Епіцентр вимагає роботу з конкретними {orderId}.")
        elif response.status_code == 404:
            print("[❌ 404] Сервер все одно не бачить цей шлях колекцій замовлень.")
        else:
            print(f"[ℹ️ Статус {response.status_code}]: {response.text}")
            
    except Exception as e:
        print(f"[💥 ПОМИЛКА]: {e}")

if __name__ == "__main__":
    test_real_oms_route()
