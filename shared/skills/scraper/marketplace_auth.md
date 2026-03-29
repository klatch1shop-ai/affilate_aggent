# Скіл авторизації на маркетплейсах

## Підтримувані маркетплейси
1. Prom.ua — API токен
2. Rozetka — партнерський доступ
3. Епіцентр — дропшипінг партнер

## Prom.ua авторизація

### Отримання токена
1. Зайти на https://my.prom.ua
2. Налаштування → API → Згенерувати токен
3. Зберегти в .env: PROM_API_TOKEN=your_token

### Перевірка токена
```python
async def check_prom_auth() -> dict:
    import httpx, os
    token = os.getenv("PROM_API_TOKEN","")
    if not token:
        return {"status": "error", "message": "Токен не встановлено"}
    url = "https://my.prom.ua/api/v1/products/list"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers, params={"limit": 1})
        if resp.status_code == 200:
            return {"status": "ok", "marketplace": "prom"}
        return {"status": "error", "code": resp.status_code}
```

### Доступні операції з токеном
- Читання товарів магазину
- Додавання/редагування товарів
- Отримання замовлень
- Оновлення статусів замовлень
- Керування категоріями

## Rozetka авторизація

### Реєстрація партнера
1. Зайти на https://partner.rozetka.com.ua
2. Заповнити форму партнера
3. Отримати логін і пароль
4. Зберегти: ROZETKA_LOGIN, ROZETKA_PASSWORD

### API авторизація
```python
async def get_rozetka_token() -> str:
    import httpx, os
    url = "https://api.seller.rozetka.com.ua/sites"
    data = {
        "username": os.getenv("ROZETKA_LOGIN",""),
        "password": os.getenv("ROZETKA_PASSWORD","")
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=data)
        return resp.json().get("content",{}).get("access_token","")
```

### Доступні операції
- Завантаження товарів (YML/XML)
- Отримання замовлень
- Оновлення залишків і цін
- Статистика продажів

## Епіцентр дропшипінг

### Реєстрація
1. Зайти на https://epicentrk.ua/ua/dropshipping/
2. Заповнити форму дропшипера
3. Отримати особистий кабінет
4. Зберегти: EPICENTR_LOGIN, EPICENTR_PASSWORD

### Перевірка доступу
```python
async def check_epicentr_auth() -> dict:
    import httpx, os
    url = "https://epicentrk.ua/api/user/profile/"
    headers = {
        "Authorization": f"Bearer {os.getenv('EPICENTR_TOKEN','')}",
        "X-Requested-With": "XMLHttpRequest"
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            return {"status": "ok", "marketplace": "epicentr"}
        return {"status": "error", "code": resp.status_code}
```

## Збереження токенів

### .env структура
```
# Prom.ua
PROM_API_TOKEN=your_prom_token_here

# Rozetka Partner
ROZETKA_LOGIN=your_login
ROZETKA_PASSWORD=your_password
ROZETKA_TOKEN=auto_generated

# Епіцентр
EPICENTR_LOGIN=your_login
EPICENTR_PASSWORD=your_password
EPICENTR_TOKEN=auto_generated

# Додаткові сервіси
SERPAPI_KEY=optional_for_search
TWOCAPTCHA_KEY=optional_for_captcha
```

## Перевірка всіх підключень
```python
async def check_all_auth() -> dict:
    results = {}
    results["prom"] = await check_prom_auth()
    results["rozetka"] = await check_rozetka_auth()
    results["epicentr"] = await check_epicentr_auth()
    return results
```

## Ротація і безпека токенів
- Токени зберігаються ТІЛЬКИ в .env
- Ніколи не логувати токени в event_logs
- Перевіряти токени кожні 24 години
- При помилці 401 — повідомити адміна через Telegram
