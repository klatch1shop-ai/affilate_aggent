# API Reference — Маркетплейси та Доставка

> Оновлено: 2026-06-13 | БД: `SELECT * FROM marketplace_api_methods`

## Зміст
- [Prom.ua](#promua)
- [Rozetka](#rozetka)
- [Єпіцентр OMS](#єпіцентр-oms)
- [Єпіцентр PIM](#єпіцентр-pim)
- [Нова Пошта](#нова-пошта)
- [Статуси замовлень](#статуси-замовлень)
- [Статистика реалізації](#статистика-реалізації)

---

## Prom.ua

**Base URL:** `https://my.prom.ua/api/v1`
**Auth:** `Authorization: Bearer PROM_API_TOKEN`
**MCP файл:** `shared/mcp_servers/prom_mcp.py`

### Замовлення

| Метод | HTTP | Endpoint | MCP Tool | Реалізовано |
|-------|------|----------|----------|------------|
| Список замовлень | GET | `/orders/list` | `prom_get_orders` | ✅ |
| Деталі замовлення | GET | `/orders/{id}` | `prom_get_order` | ✅ |
| Зміна статусу | POST | `/orders/set_status` | `prom_set_order_status` | ✅ |
| Зберегти ТТН | POST | `/delivery/save_declaration_id` | `prom_save_ttn` | ✅ |

```
Статуси Prom: pending → accepted → delivered
              pending → cancelled | declined
```

**Приклад зміни статусу:**
```python
POST /orders/set_status
{"ids": [123, 456], "status": "accepted"}
```

**Приклад збереження ТТН:**
```python
POST /delivery/save_declaration_id
{"order_id": 123, "declaration_id": "20451450921650", "delivery_type": "nova_poshta"}
```

### Товари

| Метод | HTTP | Endpoint | MCP Tool | Реалізовано |
|-------|------|----------|----------|------------|
| Список товарів | GET | `/products/list` | `prom_get_products` | ✅ |
| Деталі товару | GET | `/products/{id}` | — | ❌ |
| Оновлення цін/наявності | POST | `/products/edit` | `prom_update_prices` / `prom_update_presence` | ✅ |
| Імпорт товарів | POST | `/products/import` | — | ❌ |
| Групи товарів | GET | `/groups/list` | — | ❌ |

**Параметри оновлення:**
```python
POST /products/edit
[{"id": 1, "price": 155.00}, {"id": 2, "presence": "not_available"}]
# presence: "available" | "not_available" | "order"
```

### Повідомлення

| Метод | HTTP | Endpoint | MCP Tool | Реалізовано |
|-------|------|----------|----------|------------|
| Список повідомлень | GET | `/messages/list` | `prom_get_messages` | ✅ |
| Відповідь покупцю | POST | `/messages/reply` | `prom_reply_message` | ✅ |

### Відгуки (не реалізовано)

| Метод | HTTP | Endpoint |
|-------|------|----------|
| Список відгуків | GET | `/reviews/list` |
| Відповідь на відгук | POST | `/reviews/reply` |

### Аналітика

| Метод | HTTP | Endpoint | MCP Tool | Реалізовано |
|-------|------|----------|----------|------------|
| Статистика магазину | GET | `/orders/list` (агрегація) | `prom_get_shop_stats` | ✅ |
| Статус фіду | GET | `/company/get_last_import_file` | — | ❌ |

---

## Rozetka

**Base URL:** `https://api-seller.rozetka.com.ua` ⚠️ з ДЕФІСОМ!
**Auth:** `Authorization: Bearer ROZETKA_API_TOKEN` (статичний `gapi_...`)
**SSL:** `verify=False` (старий сервер Celeron з протухлим сертом)
**MCP файл:** `shared/mcp_servers/rozetka_mcp.py`
**Агент:** `agents/orders/rozetka_order_agent.py`

> ⚠️ `api.seller.rozetka.com.ua` (без дефісу) → 404!

### Авторизація

```python
POST /sites
{"username": "login", "password": "pass"}
# → content.access_token живе 24 год
# Статичний gapi_... токен діє поки є активність раз на добу
```

### Замовлення

| Метод | HTTP | Endpoint | MCP Tool | Реалізовано |
|-------|------|----------|----------|------------|
| Нові замовлення | GET | `/orders/search?types=4` | `rozetka_get_orders` | ✅ |
| За статусом | GET | `/orders/search?status={s}` | `rozetka_get_orders` | ✅ |
| Деталі замовлення | GET | `/orders/{id}?expand=status_available` | `rozetka_get_order` | ✅ |
| Підтвердити (status=2) | PATCH | `/orders/{id}` | — | ✅ |
| Відправити (status=3) | PATCH | `/orders/{id}` | — | ✅ |
| Скасувати (status=6) | PATCH | `/orders/{id}` | — | ✅ |
| Додати ТТН (primary) | POST | `/orders/add-ttn` | — | ✅ |
| Додати ТТН (fallback) | PATCH | `/orders/{id}` | — | ✅ |

**Послідовність статусів:**
```
types=4 (нові) → PATCH status=2 → POST /orders/add-ttn → auto status=61 → PATCH status=3
                                                                          ↓
                                                               GET /orders/{id} верифікація
```

**Додавання ТТН:**
```python
# Primary (рекомендовано):
POST /orders/add-ttn
{"order_id": 12345, "ttn": "20451450921650", "delivery_service_id": 1}
# → статус автоматично стає 61

# Fallback (якщо primary не спрацював):
PATCH /orders/{id}
{"ttn": "20451450921650"}
```

**Статуси Розетки:**
- `2` — підтверджено продавцем
- `3` — передано в доставку
- `6` — скасовано
- `61` — ТТН додано (автоматично після add-ttn)

### Товари

| Метод | HTTP | Endpoint | Реалізовано |
|-------|------|----------|------------|
| Пошук за артикулом | GET | `/items/search?article={SKU}` | ❌ |
| Деталі товару | GET | `/items/{id}` | ❌ |
| Оновлення ціни/наявності | PUT | `/items/update-price-stock/{owox_id}` | ❌ |
| Лічильники товарів | GET | `/items/counts` | ❌ |
| Статуси модерації | GET | `/items/statuses-moderation` | ❌ |
| Ініціювати експорт | GET | `/items/create-export-file?marketId={id}` | ❌ |
| Завантажити XLS | GET | `/items/download-export-file?marketId={id}` | ❌ |

**Оновлення в реальному часі (до 800мс):**
```python
PUT /items/update-price-stock/{owox_id}
{"stock_quantity": 15}           # тільки наявність
{"stock_quantity": 0}            # зняти з продажу
{"stock_quantity": 10, "price": 999}  # ціна + наявність
# ВАЖЛИВО: 1 товар на запит, batch НЕ підтримується!
```

### XML Фід

| Метод | HTTP | Endpoint | MCP Tool | Реалізовано |
|-------|------|----------|----------|------------|
| Статус прайсу | GET | `/prices` | `rozetka_get_xml_status` | ✅ |
| Завантажити фід | POST | `/item-price-updates/create` | — | ❌ |
| Статус завантаження | GET | `/item-price-updates/search` | — | ❌ |
| Валідація XML | POST | `seller.rozetka.com.ua/gomer/pricevalidate/...` | `rozetka_validate_xml` | ✅ |

- Автооновлення фіду: **раз на годину**
- Реальний час: тільки `PUT /items/update-price-stock/{id}`

### Категорії (Legacy API, без дефісу)

| Метод | HTTP | Endpoint | Реалізовано |
|-------|------|----------|------------|
| Пошук категорій | GET | `api.seller.rozetka.com.ua/market-categories/search` | ❌ |
| Характеристики категорії | GET | `api.seller.rozetka.com.ua/market-categories/category-options?category_id={id}` | ❌ |
| Маппінг категорій | POST | `/price-markets/create-bindings-categories` | ❌ |

> Маппінг зберігається в БД таблиці `katran_categories`

---

## Єпіцентр OMS

**Base URL:** `https://api.epicentrm.com.ua`
**Auth:** `Authorization: Bearer EPICENTR_TOKEN`
**MCP файл:** `shared/mcp_servers/epicentr_mcp.py`
**Агент:** `agents/orders/epicentr_order_agent.py` (планується)

> ⚠️ Потрібна активація в кабінеті: `admin.epicentrm.com.ua` → Налаштування → Додаткові параметри → **"Підключення до API по замовленням"**

> ⚠️ **Різні версії API!** v1, v2, v3, v5 — для різних ендпоінтів.

### Замовлення

| Метод | HTTP | Endpoint | MCP Tool | Реалізовано |
|-------|------|----------|----------|------------|
| Список замовлень | GET | `/v3/oms/orders` | `search_orders` | ✅ |
| Кількість замовлень | GET | `/v3/oms/orders/total` | `search_orders` | ✅ |
| Деталі замовлення | GET | `/v5/oms/orders/{id}` | `get_order` | ✅ |
| Дозволені статуси | GET | `/v2/oms/orders/{id}/allowed-statuses` | `update_order_status` | ✅ |
| Зміна статусу | POST | `/v2/oms/orders/{id}/change-status/to/{status}` | `update_order_status` | ✅ |
| Додати ТТН (primary) | POST | `/v3/oms/orders/{id}/shipping/{provider}` | `add_order_ttn` | ✅ |
| Додати ТТН (fallback) | PATCH | `/v1/oms/orders/{id}/shipment-number` | `add_order_ttn` | ✅ |
| Оновити дані клієнта | POST | `/v3/oms/orders/{id}/client-data` | `update_order_client` | ✅ |
| Оновити адресу | POST | `/v3/oms/orders/{id}/delivery-data/{provider}` | `update_order_delivery` | ✅ |
| Додати коментар | POST | `/v2/oms/orders/{id}/comments` | `add_order_comment` | ✅ |
| Причини скасування | GET | `/v2/oms/order-cancel-reasons/customer` | `get_cancel_reasons` | ✅ |

**Послідовність статусів (ЗАБОРОНЕНО пропускати!):**
```
new → confirmed_by_merchant → confirmed → sent → delivered → completed
                                    ↓
                          canceled_by_merchant (будь-який етап)
```

**Зміна статусу:**
```python
POST /v2/oms/orders/{uuid}/change-status/to/confirmed_by_merchant
{"comment": "Прийнято"}

# Скасування:
POST /v2/oms/orders/{uuid}/change-status/to/canceled_by_merchant
{"reason_code": "out_of_stock", "comment": "Немає в наявності"}
```

**Важливо:** Єпіцентр **приховує контакти клієнта** на статусі "new". Щоб отримати телефон/ім'я — спочатку змінити статус на `confirmed_by_merchant`.

**Додавання ТТН:**
```python
# Primary:
POST /v3/oms/orders/{uuid}/shipping/nova_poshta
{"provider": "nova_poshta", "number": "20451450921650"}

# Fallback:
PATCH /v1/oms/orders/{uuid}/shipment-number
{"provider": "nova_poshta", "number": "20451450921650"}

# Потім:
POST /v2/oms/orders/{uuid}/change-status/to/sent
```

### Доставка

| Метод | HTTP | Endpoint | MCP Tool | Реалізовано |
|-------|------|----------|----------|------------|
| Знайти місто | GET | `/v3/deliveries/providers/{p}/participants/{part}/settlements` | `find_delivery_office` | ✅ |
| Знайти відділення | GET | `/v3/deliveries/providers/{p}/participants/{part}/settlements/{id}/offices` | `find_delivery_office` | ✅ |
| Інфо по ТТН | GET | `/v3/deliveries/{p}/companies/{company_id}/invoice/{ttn}` | `get_delivery_invoice` | ✅ |

**Маппінг провайдерів:**
- `nova_poshta` / participant `np`
- `ukrposhta` / participant `up`
- `meest` / participant `meest`
- `justin` / participant `justin`

---

## Єпіцентр PIM

**Base URL:** `https://api.epicentrm.com.ua`
**Auth:** той самий токен що і OMS

### Каталог

| Метод | HTTP | Endpoint | MCP Tool | Реалізовано |
|-------|------|----------|----------|------------|
| Категорії | GET | `/v2/pim/categories` | `get_categories` | ✅ |
| Значення атрибутів | GET | `/v2/pim/attribute-sets/{set}/attributes/{attr}/options` | `get_attribute_options` | ✅ |

**Використання категорій:**
```python
GET /v2/pim/categories?search=Воротки&limit=20
# → code="2618" підставляємо в XML фід

GET /v2/pim/attribute-sets/2618/attributes/brand/options?limit=100
# → code="toptul" підставляємо в <value_code> XML
```

---

## Нова Пошта

**Base URL:** `https://api.novaposhta.ua/v2.0/json/`
**Auth:** `apiKey` в тілі кожного запиту
**Всі запити:** POST з JSON body `{apiKey, modelName, calledMethod, methodProperties}`
**NP_API_KEY:** в `.env`

### Структура запиту

```json
{
  "apiKey": "NP_API_KEY",
  "modelName": "TrackingDocument",
  "calledMethod": "getStatusDocuments",
  "methodProperties": {
    "Documents": [{"DocumentNumber": "20451450921650"}]
  }
}
```

### Трекінг

| modelName | calledMethod | Опис | Реалізовано |
|-----------|-------------|------|------------|
| `TrackingDocument` | `getStatusDocuments` | Статус посилки за ТТН | ✅ |

**Відповідь трекінгу:**
```json
{
  "data": [{
    "StatusCode": "7",
    "Status": "Одержано",
    "RecipientFullName": "Петренко Іван",
    "PhoneRecipient": "380671234567",
    "CityRecipient": "Рівне",
    "WarehouseRecipient": "Відділення №1",
    "CashPaymentAmount": "1500.00"
  }]
}
```

### Адреси

| modelName | calledMethod | Опис | Реалізовано |
|-----------|-------------|------|------------|
| `Address` | `getCities` | Пошук міст | ❌ |
| `Address` | `getWarehouses` | Відділення в місті | ❌ |

### Накладні (ТТН)

| modelName | calledMethod | Опис | Реалізовано |
|-----------|-------------|------|------------|
| `InternetDocument` | `save` | Створити ТТН | ❌ |
| `InternetDocument` | `delete` | Видалити ТТН | ❌ |
| `InternetDocument` | `getDocumentPrice` | Розрахунок вартості | ❌ |

### Контрагенти

| modelName | calledMethod | Опис | Реалізовано |
|-----------|-------------|------|------------|
| `CounterpartyGeneral` | `getCounterparties` | Список контрагентів-відправників | ❌ |

---

## Статуси замовлень

### Уніфіковані статуси (внутрішній словник)

| Уніфікований | Prom | Розетка | Єпіцентр |
|-------------|------|---------|----------|
| `new` | `pending` | `types=4` | `new` |
| `accepted` | `accepted` | `2` | `confirmed_by_merchant` |
| `confirmed` | — | — | `confirmed` |
| `shipped` | `delivered` | `3` | `sent` |
| `ttn_added` | — | `61` | — |
| `delivered` | — | — | `delivered` |
| `completed` | — | — | `completed` |
| `cancelled` | `cancelled`/`declined` | `6` | `canceled_by_merchant` |

### Маппінг Єпіцентру (epicentr_mcp.py)

```python
UNIFIED_TO_EPICENTR = {
    'new':       'new',
    'accepted':  'confirmed_by_merchant',
    'confirmed': 'confirmed',
    'shipped':   'sent',
    'delivered': 'delivered',
    'completed': 'completed',
    'cancelled': 'canceled_by_merchant',
}
```

---

## Статистика реалізації

> Актуальна вибірка з БД:
> ```sql
> SELECT marketplace, COUNT(*) AS total,
>   SUM(CASE WHEN is_implemented THEN 1 ELSE 0 END) AS done
> FROM marketplace_api_methods GROUP BY marketplace;
> ```

| Маркетплейс | Всього | Реалізовано | Не реалізовано |
|-------------|--------|-------------|----------------|
| Prom.ua | ~12 | 8 | 4 |
| Rozetka | ~18 | 9 | 9 |
| Єпіцентр OMS | ~11 | 11 | 0 |
| Єпіцентр PIM | ~2 | 2 | 0 |
| Єпіцентр Delivery | ~3 | 3 | 0 |
| Нова Пошта | ~8 | 2 | 6 |
| **Всього** | **~54** | **35** | **~19** |

### Що ще не реалізовано (пріоритет)

**Розетка (priority 2-3):**
- `PUT /items/update-price-stock/{id}` — реальний час оновлення наявності
- `GET /items/search` — пошук owox_id за артикулом
- `POST /item-price-updates/create` — завантаження фіду

**Нова Пошта (priority 4-6):**
- `Address/getWarehouses` — відділення для автопідстановки адреси
- `InternetDocument/save` — створення ТТН (потребує налаштування відправника)
- `InternetDocument/getDocumentPrice` — калькулятор доставки

**Prom (priority 5-7):**
- `reviews/list` + `reviews/reply` — відповіді на відгуки
- `products/import` — імпорт через фід

---

## Файли реалізації

| Компонент | Файл |
|-----------|------|
| Prom MCP | `shared/mcp_servers/prom_mcp.py` |
| Rozetka MCP | `shared/mcp_servers/rozetka_mcp.py` |
| Єпіцентр MCP | `shared/mcp_servers/epicentr_mcp.py` |
| Агент MCP | `shared/mcp_servers/agent_mcp_server.py` |
| Розетка агент | `agents/orders/rozetka_order_agent.py` |
| НП API | `agents/orders/np_api.py` |
| PDF парсер | `agents/orders/ttn_pdf_parser.py` |
| Telegram бот | `tg_dispatcher/main.py` |
| БД таблиця | `infrastructure/api_methods.sql` |
