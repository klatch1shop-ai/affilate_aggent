# Prom.ua API — повна документація

## Базова інформація
- Base URL: https://my.prom.ua/api/v1
- Авторизація: Bearer token в заголовку
- Формат: JSON
- Ліміт: 1000 запитів/годину

## Автентифікація
```python
headers = {"Authorization": f"Bearer {PROM_TOKEN}"}
```

## Ендпоінти товарів

### Список товарів
GET /products/list
Параметри:
- search_term: рядок пошуку
- limit: кількість (max 100)
- price_from / price_to: ціновий діапазон
- status: on_display / hidden / deleted
- group_id: ID категорії

### Один товар
GET /products/{id}

### Редагувати товар
POST /products/edit
Body: {"id": 123, "price": 999, "status": "on_display"}

### Імпорт товарів
POST /products/import
Body: {"products": [...]}

## Ендпоінти замовлень

### Список замовлень
GET /orders/list
Параметри:
- status: pending / received / delivered / canceled
- limit: max 100
- date_from / date_to: фільтр по даті

### Одне замовлення
GET /orders/{id}

### Оновити статус
POST /orders/{id}/set_status
Body: {"status": "received", "comment": "..."}

## Ендпоінти категорій
GET /groups/list — список категорій магазину
GET /groups/{id} — одна категорія

## Webhook події
- order_created — нове замовлення
- order_status_changed — зміна статусу
- message_received — нове повідомлення

## Формат товару
```json
{
  "id": 123456,
  "name": "Назва товару",
  "price": "999.00",
  "status": "on_display",
  "url": "https://prom.ua/p123456.html",
  "category": {"id": 1, "caption": "Електроніка"},
  "images": [{"url": "https://..."}],
  "description": "Опис...",
  "presence": "available"
}
```

## Коди помилок
- 401: невірний токен
- 422: невірні параметри
- 429: перевищено ліміт запитів
- 500: помилка сервера

## Важливо для дропшипінгу
- Комісія Prom: 5% від суми продажу
- Мінімальна ціна товару: 1 грн
- Максимум фото: 20 шт на товар
- Оновлення цін: максимум 100 товарів за запит
