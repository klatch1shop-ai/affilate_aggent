# Dropshipping Pipeline — покроковий опис

> Станом на: 2026-06-07

---

## Pipeline A: Carvol → Розетка (активний)

### Крок 1: Завантаження фіду постачальника

**Скрипт:** автоматично в `rozetka_order_agent.py` та `rozetka_github_sync.py`
```
Джерело: https://carvol.prom.ua/rozetka_feed.xml?rozetka_hash_tag=...
Формат: XML (offers з available, price, stock_quantity)
```

### Крок 2: Оновлення XML фіду

**Скрипт:** `agents/orders/rozetka_github_sync.py` (cron `0 * * * *`)
```python
# Алгоритм:
# 1. Завантажує Carvol фід
# 2. Читає поточний data/carvol_rozetka.xml з GitHub
# 3. Оновлює тільки <price> та <stock_quantity> / available=""
# 4. Структуру (категорії, назви, фото) НЕ ЧІПАЄ
# 5. git add data/carvol_rozetka.xml → commit → push
```

Комісії Розетки для Carvol (прогресивна шкала по category_id):
- до 5999 грн → 18%, 6000-9999 → 12%, 10000-19999 → 7%, 20000+ → 5%

### Крок 3: Розетка підтягує XML

Розетка автоматично оновлює каталог раз на годину з:
```
https://raw.githubusercontent.com/klatch1shop-ai/affilate_aggent/main/data/carvol_rozetka.xml
```

### Крок 4: Нове замовлення → підтвердження

**Сервіс:** `rozetka-order-agent.service` (постійно)  
**Скрипт:** `agents/orders/rozetka_order_agent.py`

```
GET /orders/search?types=4          ← нові замовлення
  │
  ├── статус 40/49/6? → пропустити
  │
  ▼
PATCH /orders/{id} {"status": 2}    ← підтверджуємо
  │
  ▼
Формуємо Excel (xlsxwriter):
  order_id | SKU | name | qty | price | customer | city | warehouse
  │
  ▼
Відправляємо Excel у Telegram Carvol (chat_id: 8035052611)
  │
  ▼
save_to_db('accepted'): phone, recipient, city, total_price → rozetka_processed_orders
  │
  ▼
Telegram адміну: "✅ Замовлення #123 підтверджено, Excel відправлено Carvol"
```

### Крок 5: Отримання ТТН від Carvol

**Сервіс:** `tg-dispatcher.service` → `handle_document()`  
**Файли:** `tg_dispatcher/main.py` + `agents/orders/ttn_pdf_parser.py` + `agents/orders/np_api.py`

```
Carvol надсилає PDF накладної НП у Telegram (chat_id: 8035052611)
  │
  ▼
security_middleware: перевіряємо chat_id == CARVOL_TG_CHAT_ID
  │
  ▼
handle_document → завантажуємо PDF
  │
  ▼
parse_ttn_pdf (pdfplumber):
  ├── ТТН: regex "XX XXXX XXXX XXXX" → 14 цифр
  ├── Ім'я: Cyrillic mixed-case після "КОМУ:"
  └── Місто: "Місто, Відділення..." pattern
  │
  ▼
get_ttn_info (NP API: TrackingDocument/getStatusDocuments):
  ├── RecipientFullName, PhoneRecipient
  ├── CityRecipient, WarehouseRecipient
  └── CashPaymentAmount (COD)
  │
  ▼
match_order_by_np_data (з БД):
  ├── 1. phone match (score 1.0)  ← пріоритет
  ├── 2. name + price (fuzzy ≥0.6 + ±5%)
  └── 3. price ±5% (fallback)
     │
     Fallback якщо NP API недоступний:
     match_order_by_ttn_data (з PDF даних)
```

### Крок 6: Встановлення ТТН і відправка

```
Один збіг знайдено:
  │
  ▼
set_ttn():
  ├── POST /orders/add-ttn {"order_id", "ttn", "delivery_service_id": 1}  ← primary
  └── PATCH /orders/{id} {"ttn": "номер"}  ← fallback якщо add-ttn повернув помилку
  │
  ▼
Розетка автоматично ставить status 61 (ТТН додано)
  │
  ▼
change_status(3): PATCH /orders/{id} {"status": 3}  ← передано в доставку
  │
  ▼
Верифікація (через 2 секунди):
  GET /orders/{id} → перевіряємо ttn != None
  └── ALARM адміну якщо ТТН не збереглось!
  │
  ▼
Telegram адміну: "✅ #123 → ТТН 20451450921650 встановлено, status 3"

Кілька збігів:
  └── Telegram адміну: список варіантів → /ttn ORDER_ID TTN
```

---

## Pipeline B: TOPTUL → Єпіцентр (активний)

### Крок 1: Завантаження фіду TOPTUL

```
Джерело: https://toptul.online/products_feed.xml?hash_tag=...
Формат: XML (yml_catalog, vendorCode = наш SKU)
Оновлення: щогодинне (у постачальника)
```

### Крок 2: Нове замовлення Єпіцентру

**Сервіс:** `epicentr-order-agent.service` (постійно)  
**Скрипт:** `agents/orders/epicentr_order_agent.py`

```
GET https://merchant-api.epicentrm.com.ua/orders (нові)
  │
  ▼
Перевірка наявності кожного SKU у фіді TOPTUL (реальний час)
  │
  ├── всі в наявності → підтверджуємо замовлення
  └── щось відсутнє → Telegram алерт адміну
  │
  ▼
Формуємо Excel бланк → відправляємо на opt@grandinstrument.ua
  │
  ▼
save_to_db → Telegram сповіщення адміну
```

---

## Pipeline C: Катран → Розетка (в процесі)

### Крок 1: Завантаження фіду Катрана

**Скрипт:** `agents/orders/katran_xml_generator.py` (запускати на **ноутбуці**)
```
Джерело: KATRAN_FEED_URL_STOCK (.env) → ZIP архів → katran.xml
Формат: <price><products><product> (НЕ yml_catalog!)
```

### Крок 2: Парсинг полів Катрана

```python
# Ключові поля:
code          # внутрішній код
artikul       # артикул (стає id та article в XML Розетки)
name          # назва товару
price_rrc     # РРЦ в гривнях з ПДВ → BASE для ціни
stock         # "есть" / "в резервах" / "" → available
stock_quantity
categoryId    # id категорії → маппінг в katran_categories
vendor        # виробник
images/image  # фото (multiple)
description   # опис
warranty      # гарантія (міс)
```

### Крок 3: Маппінг категорій

```python
# Таблиця katran_categories в БД:
# id, parent_id, name, rozetka_category, rozetka_rz_id, commission_pct

# Поточне покриття:
# - 1449 категорій змаппованих (27 батьківських + пропагація)
# - ~40% товарів мають rz_id (3005 з 7441)
# - ~60% без rz_id → використовується DEFAULT (Ручний інструмент)

get_category_map() → {katran_id: {rz_id, name, commission}}
```

**Пропагація (запускати після UPDATE батьків):**
```sql
DO $$ DECLARE r INT; p INT := 0; BEGIN LOOP p := p+1;
  UPDATE katran_categories c SET rozetka_rz_id=pr.rozetka_rz_id,
    rozetka_category=pr.rozetka_category, commission_pct=pr.commission_pct
  FROM katran_categories pr WHERE c.parent_id=pr.id
    AND c.rozetka_rz_id IS NULL AND pr.rozetka_rz_id IS NOT NULL;
  GET DIAGNOSTICS r = ROW_COUNT; EXIT WHEN r=0 OR p>=5; END LOOP; END $$;
```

### Крок 4: Розрахунок ціни

```python
def calc_price(price_rrc: float, commission_pct: float) -> int:
    raw = price_rrc * (1 + commission_pct / 100)
    return int(math.ceil(raw / 10) * 10)

# Приклад: price_rrc=1000 грн, commission=19.44%
# → raw = 1194.4 → ceil до десятки → 1200 грн
```

### Крок 5: Генерація XML Розетки

**Скрипт:** `agents/orders/katran_xml_generator.py`
```
Вихід: data/katran_rozetka.xml

Структура offer:
  <offer id="{artikul}" available="{true/false}">
    <url>...</url>
    <price>{розрахована ціна}</price>
    <stock_quantity>{кількість}</stock_quantity>
    <categoryId>{rozetka_rz_id}</categoryId>
    <vendor>{vendor}</vendor>
    <picture>...</picture> (до 10 фото)
    <name>{name}</name>
    <description>{description}</description>
    <article>{artikul}</article>
    <warranty>{warranty}</warranty>
  </offer>
```

### Крок 6: Синхронізація через GitHub

**Скрипт:** `agents/orders/katran_github_sync.py`
```
katran_xml_generator.main() → data/katran_rozetka.xml
  │
  ▼
git add -f data/katran_rozetka.xml
git commit -m "sync: katran feed 2026-06-07 10:00 (3005 offers)"
git push
  │
  ▼
Розетка завантажує XML (після налаштування посилання в кабінеті)
```

**Cron (додати на сервері):**
```
0 * * * * /home/tek/agent-system/venv/bin/python3 /home/tek/agent-system/agents/orders/katran_github_sync.py >> /tmp/katran_sync_cron.log 2>&1
```

---

## Pipeline D: TOPTUL → Prom (активний)

### Ціноутворення (щоденно 08:00)

**Скрипт:** `agents/orders/price_updater.py` → `price_engine.py`

```
TOPTUL XML фід (РРЦ ціни, знижка 12%)
  │
  ▼
Для кожного SKU:
  zakupka = price_supplier * 0.88
  min_price = (zakupka + 20) / (1 - CPA) * 1.12
  │
  ├── CPA з prom_cpa_rates по категорії
  └── Округлення вгору до цілих
  │
  ▼
price_history → фіксуємо зміни
my_products.price_our → оновлюємо
  │
  ▼
Prom API: PUT /products/{id}/prices (батчами)
  │
  ▼
Telegram звіт + CSV алертів
```

### Синхронізація наявності (кожні 4 год)

**Скрипт:** `agents/orders/feed_sync.py` (cron `0 */4 * * *`)
```
TOPTUL XML → порівняти availability з my_products
  │
  ▼
Prom API: оновити availability (БЕЗ ціни!)
```

---

## Pipeline E: Замовлення Prom (активний)

**Сервіс:** `order_agent_daemon.py` (systemd, кожні 5 хв — через cron або daemon)

```
GET /orders?status=new (Prom API)
  │
  ▼
Для кожного замовлення:
  ├── Перевірити SKU у фіді TOPTUL (реальний час)
  ├── Якщо все є → підтвердити + Excel → email rusanov@grandinstrument.ua
  └── Telegram адміну
  │
  ▼
save_to_db → orders таблиця
```

---

## Загальна схема всіх потоків

```
TOPTUL XML ──────────────────────────────────► Prom.ua
   (РРЦ, 12% знижка)       price_engine.py   (5908 товарів)
        │                                          │
        └──► epicentr_xml_generator.py ──► Єпіцентр
                                           (5893 товари)

Carvol Prom feed ──► rozetka_github_sync.py ──► GitHub raw URL ──► Розетка
   (live XML)            (1/год)               carvol_rozetka.xml  (8304 товари)

Katran ZIP/XML ──► katran_xml_generator.py ──► GitHub raw URL ──► Розетка
   (price_rrc)       (1/год, ноутбук)         katran_rozetka.xml  (~3005 товари)

Розетка замовлення ──► rozetka_order_agent ──► Excel ──► Carvol TG
                              │                              │
                              ◄──────────── PDF накладної ──┘
                              │
                         ttn_pdf_parser
                              │
                         np_api (Nova Poshta)
                              │
                         set_ttn → status 61 → status 3
```

---

## Ключові API endpoints

### Розетка
```
Base URL: https://api-seller.rozetka.com.ua
SSL: verify=False (обов'язково!)

GET  /orders/search?types=4              — нові замовлення
GET  /orders/search?status={n}           — за статусом
GET  /orders/{id}                        — деталі + верифікація TTN
PATCH /orders/{id} {"status": 2}         — підтвердити
PATCH /orders/{id} {"status": 3}         — передати в доставку
PATCH /orders/{id} {"status": 6}         — скасувати
POST  /orders/add-ttn {"order_id","ttn","delivery_service_id":1}  — TTN (primary)
PATCH /orders/{id} {"ttn": "номер"}      — TTN fallback
GET  /items/search?article={артикул}     — owox_id товару
PUT  /items/update-price-stock/{owox_id} — оновити ціну/наявність (real-time)
```

### Nova Poshta
```
URL: https://api.novaposhta.ua/v2.0/json/
POST body: {apiKey, modelName: "TrackingDocument",
            calledMethod: "getStatusDocuments",
            methodProperties: {Documents: [{DocumentNumber, Phone}]}}
```

### Єпіцентр
```
Base URL: https://merchant-api.epicentrm.com.ua
Auth: Bearer EPICENTR_TOKEN
GET /orders (нові)
POST /orders/{id}/confirm
```

### Prom.ua
```
Base URL: https://my.prom.ua/api/v1
Auth: Bearer PROM_API_TOKEN
GET /orders/list?status=pending_payment
PUT /orders/set_status {"ids":[], "status":"confirmed"}
PUT /products/edit_prices {"products":[{"id","price"}]}
```
