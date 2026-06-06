# Prom.ua API — повна документація

## Базова інформація
- Base URL: https://my.prom.ua/api/v1
- Auth: Authorization: Bearer {PROM_API_TOKEN}
- Токен: в .env як PROM_API_TOKEN
- Магазин ID: 4053918

## Ключові endpoints

### Товари
GET  /products/list          — список товарів (limit, last_id для пагінації)
GET  /products/{id}          — один товар по ID
POST /products/edit          — редагування товарів (масив об'єктів!)

### Формат /products/edit:
```python
# ВАЖЛИВО: передається масив, не словник!
payload = [
    {'id': 123456, 'price': 299.0},
    {'id': 234567, 'price': 450.0},
]
resp = requests.post('https://my.prom.ua/api/v1/products/edit',
    headers={'Authorization': f'Bearer {token}'},
    json=payload)  # масив!
# Відповідь: {"processed_ids": [123456, 234567], "errors": {}}
```

### Пагінація /products/list:
```python
# Завантажити всі товари
all_products = {}
last_id = None
while True:
    params = {'limit': 100}
    if last_id:
        params['last_id'] = last_id
    resp = requests.get(url, headers=headers, params=params)
    products = resp.json().get('products', [])
    if not products:
        break
    for p in products:
        all_products[p['sku']] = p
    last_id = products[-1]['id']
    if len(products) < 100:
        break
```

### Замовлення
GET  /orders/list            — список замовлень (status, limit)
GET  /orders/{id}            — одне замовлення
POST /orders/set_status      — змінити статус

### Статуси замовлень:
- pending → нове
- accepted → прийнято
- delivered → доставлено
- cancelled → скасовано
- declined → відхилено

### Доставка
POST /delivery/save_declaration_id — зберегти ТТН до замовлення

### Повідомлення
GET  /messages/list          — список повідомлень
POST /messages/reply         — відповісти покупцю

## Важливі особливості

### Наявність (presence):
- 'available' = в наявності
- 'order' = під замовлення
- 'not_available' = немає

### Фід TOPTUL — SKU в тегу vendorCode:
```python
# ПРАВИЛЬНО:
sku_el = offer.find('vendorCode')
sku = sku_el.text.strip() if sku_el is not None else ''

# НЕПРАВИЛЬНО (немає такого параметру):
# for p in offer.findall('param'):
#     if 'артикул' in p.get('name','').lower()
```

### Налаштування імпорту Prom (важливо!):
- Зняти галочку "Ціна" в імпорті якщо оновлюємо ціни через API
- Інакше фід перезапише наші ціни кожні 4 години
- Шлях: my.prom.ua → Товари → Імпорт → Інформація яку оновлювати

### Дешева доставка:
- Несумісна з дропшипінгом від постачальника
- Вимкнути: Налаштування → Способи доставки → НП → вимкнути "Дешева доставка"

## Агенти що використовують API

### order_agent.py (кожні 5 хв):
- Нові замовлення → перевірка наявності у фіді → підтвердження → Excel постачальнику

### price_updater.py (щодня о 8:00):
- Фід → порівняння цін → оновлення БД → оновлення Prom
