# Dropshipping Agent System — Повна технічна документація

> Станом на: 2026-06-07  
> Глибокий аналіз кожної функції. Оновлено автоматично.

---

## 1. Про систему

Автоматизована платформа дропшипінгу на українських маркетплейсах.  
Купуємо товари у постачальників без складу, продаємо через маркетплейси.

**Постачальники → Маркетплейси:**
| Постачальник | Маркетплейс | Статус |
|---|---|---|
| TOPTUL / Гранд Інструмент | Prom.ua | ✅ активно |
| TOPTUL / Гранд Інструмент | Єпіцентр | ✅ активно |
| Carvol | Розетка | ✅ активно |
| Катран | Розетка | 🔄 XML готовий, ~40% товарів, чекаємо GitHub лінк |

---

## 2. Інфраструктура

```
┌─────────────────────────────────────────────────────┐
│  НОУТБУК  100.126.131.55                            │
│  RTX 4050 6GB — Ollama, embedding_service.py        │
│  Запускає: katran_xml_generator.py (потребує AVX)   │
└───────────────────┬─────────────────────────────────┘
                    │ Tailscale VPN
┌───────────────────▼─────────────────────────────────┐
│  СЕРВЕР   tek@100.82.24.112                         │
│  ├── PostgreSQL (Docker agent_postgres)             │
│  ├── Redis (черги завдань, embedding queue)         │
│  ├── Qdrant (векторна БД для /learn правил)         │
│  └── systemd --user сервіси:                        │
│      ├── rozetka-order-agent  (постійно, кожні 5 хв)│
│      ├── epicentr-order-agent (постійно, кожні 5 хв)│
│      ├── tg-dispatcher        (постійно, polling)   │
│      └── feed-server          (постійно)            │
└───────────────────┬─────────────────────────────────┘
                    │ GitHub raw URL
┌───────────────────▼─────────────────────────────────┐
│  GITHUB  klatch1shop-ai/affilate_aggent             │
│  data/carvol_rozetka.xml   — фід Carvol для Розетки │
│  data/katran_rozetka.xml   — фід Катрана для Розетки│
└─────────────────────────────────────────────────────┘
```

### Підключення
```bash
ssh tek@100.82.24.112
cd /home/tek/agent-system && source venv/bin/activate
docker exec -it agent_postgres psql -U agent agentdb
```

---

## 3. Архітектура потоків даних

```
Постачальник XML фід (Carvol/TOPTUL/Катран)
  │
  ▼
[XML Generator] ──► data/*.xml ──► git push ──► GitHub
                                                  │
                                    Розетка читає (кожну год)
  │
  ▼
[Order Agent] ◄── API Розетки/Єпіцентру (polling кожні 5 хв)
  │
  ├── перевіряє наявність у фіді постачальника
  ├── підтверджує замовлення (status 2 / confirmed_by_merchant)
  ├── формує Excel бланк (xlsxwriter)
  ├── надсилає Telegram або email постачальнику
  └── зберігає в PostgreSQL → Telegram сповіщення адміну
         │
         ▼
[Carvol] надсилає PDF накладну НП
         │
         ▼
[TG Dispatcher: handle_document]
  ├── parse_ttn_pdf() — витягує ТТН (14 цифр), телефон, ім'я, місто
  ├── get_ttn_info() — уточнює дані через НП API
  ├── match_order_by_np_data() — знаходить замовлення в БД
  └── set_ttn() → status 61 → change_status(3) → верифікація GET
```

---

## 4. Детальний аналіз кожного файлу

---

### 4.1 `agents/orders/rozetka_order_agent.py` — 785 рядків

Головний агент обробки замовлень Розетки. Версія v4.

#### Функції:

**`tg(msg)`**  
Відправляє повідомлення адміну через Telegram Bot API. Тихо ігнорує помилки.

**`get_token() → str`**  
Повертає ROZETKA_API_TOKEN з .env. Кидає Exception якщо не задано.

**`rz_headers() → dict`**  
Формує headers для API Розетки: `Authorization: Bearer ...`, `Content-Language: uk`.

**`get_carvol_feed(force=False) → dict`**  
Завантажує XML фід Carvol (Prom-формат) і повертає `{article: {available, price, qty}}`.  
Кешує на 1 годину в `_carvol_cache`.  
⚠️ Враховує qty > 0 для available.

**`get_new_orders() → list`**  
Отримує замовлення з 5 різних endpoint: types=4 (нові), status=1, 26, 55, 61.  
Дедуплікує за order_id в dict. Повертає всі унікальні замовлення.

**`get_orders_by_status(status) → list`**  
Повертає замовлення за одним конкретним статусом. Допоміжна функція.

**`get_order_details(order_id) → dict`**  
GET /orders/{id}?expand=purchases,delivery,status_available,payment_type.  
Повертає повні деталі замовлення або порожній dict при помилці.

**`change_status(order_id, status) → bool`**  
PATCH /orders/{id} з {status: N}. Повертає True при успіху.

**`set_ttn(order_id, ttn) → bool`**  
Встановлює ТТН двома способами:
1. POST /orders/add-ttn — primary (Розетка автоматично встановлює статус 61)
2. PATCH /orders/{id} {ttn: ...} — fallback якщо перший не спрацював

**`confirm_order(order_id) → bool | None`**  
Складна функція підтвердження:
- Перевіряє поточний статус і доступні переходи
- Якщо вже 2/55/61 — повертає True (вже підтверджено)
- Пробує status=2, якщо недоступний → через 55 → потім 2
- `FORBIDDEN_STATUSES = {40, 49, 6}` — ніколи не перейти на них
- Fallback: cabinet-seller.rozetka.com.ua PUT
- Повертає None = потрібне ручне підтвердження (сигнал адміну)

**`cancel_order(order_id, comment) → bool`**  
PATCH /orders/{id} {status: 6}. Скасовує замовлення.

**`is_already_processed(order_id) → bool`**  
Перевіряє БД. Також CREATE TABLE IF NOT EXISTS при першому виклику.

**`get_db_status(order_id) → str | None`**  
Повертає поточний статус замовлення з БД (accepted, pending_manual, etc.).

**`delete_from_db(order_id)`**  
Видаляє запис з БД для повторної обробки (використовується для pending_manual).

**`save_to_db(order, status)`**  
Зберігає замовлення з phone/recipient/city для подальшого TTN-матчингу.  
ON CONFLICT DO UPDATE — оновлює існуючий запис.

**`_order_recipient_info(order) → dict`**  
Допоміжна: витягує {customer, phone, city, warehouse, total, payment_str} з вкладеної структури Розетки. Обробляє різні формати recipient_title.

**`create_order_excel(order, items_info) → str`**  
Генерує XLSX бланк замовлення для постачальника (xlsxwriter):  
- Рядки 1-5: шапка (перевізник, оплата, коментар, номер замовлення, код клієнта)
- З рядка 7: таблиця товарів (№, Артикул, Найменування, Кількість)
- Форматування: синій заголовок, bold артикул, червоний код клієнта

**`send_excel_to_carvol_telegram(excel_path, order_id, items_info, order) → bool`**  
Відправляє XLSX файл у Telegram-чат Carvol (chat ID з .env).  
Caption містить отримувача, телефон, місто, тип оплати, список SKU.

**`send_to_supplier(order, excel_path, items_info) → bool`**  
Fallback: надсилає Excel поштою на CARVOL_EMAIL через SMTP/Gmail.

**`process_order(order, feed)`**  
Головна логіка обробки одного замовлення:
1. Перевіряє статус в БД (pending_manual, accepted — пропускає)
2. Отримує деталі замовлення
3. Перевіряє наявність кожного SKU у фіді Carvol
4. Якщо товару немає → cancel_order + повідомлення
5. Якщо передоплата → чекаємо (saving_payment)
6. Якщо статус 61 → Excel + save as accepted
7. Підтверджує (status 2) → Excel → Telegram/email → save('accepted')

**`main()`**  
Нескінченний цикл: кожні 300 секунд перевіряє нові замовлення.

#### Що можна покращити:
- Retry логіка для API помилок (зараз тільки логуємо)
- Метрики: час обробки, кількість успішних/неуспішних
- Обробка часткової наявності (частина SKU є, частина ні)
- Кеш get_order_details щоб не дублювати запити

---

### 4.2 `tg_dispatcher/main.py` — 506 рядків

Telegram ШІ-диспетчер. Aiogram 3.x, асинхронний.

#### Функції:

**`security_middleware(handler, event, data)`**  
Outer middleware — фільтрує всі повідомлення:
- ADMIN_ID → повний доступ
- CARVOL_TG_CHAT_ID → тільки document (PDF) 
- Всі решта → мовчки відхиляються (без відповіді)

**`cmd_start(message)`**  
Відповідає приватним списком команд і підказкою про PDF накладні.

**`cmd_status(message)`**  
Запит до PostgreSQL: кількість товарів, цін сьогодні, замовлень за 24г, чернеток.

**`cmd_prices(message)`**  
Цінові алерти з price_history: зміни > 10% за сьогодні, топ-10 по abs(diff_pct).

**`cmd_orders(message)`**  
Список замовлень з таблиці orders за останні 24 год.

**`cmd_learn(message)`**  
/learn [текст] → InstructionParser.apply_instruction() → зберігає в Qdrant.

**`_fmt_source_info(ttn, data_source, ttn_info, parsed) → str`**  
Форматує блок даних для повідомлення: ТТН, отримувач, телефон, місто.  
Пріоритет: НП API дані > PDF дані.

**`handle_document(message)`**  
Повний автоматичний пайплайн обробки PDF накладної:
1. Перевіряє MIME тип (тільки PDF)
2. Завантажує файл з Telegram
3. `parse_ttn_pdf()` → ТТН, телефон, ім'я, місто
4. `get_ttn_info()` → уточнення через НП API
5. `match_order_by_np_data()` або `match_order_by_ttn_data()` → збіг
6. Один збіг → `set_ttn()` + `change_status(3)` + оновлення БД
7. Верифікація GET /orders/{id} через 2 секунди
8. ALARM якщо ТТН не збереглось
9. Кілька збігів → список для ручного /ttn ORDER_ID TTN

**`handle_voice(message)`**  
Голосове → faster-whisper (STT) → redirect до handle_text.

**`handle_text(message)`**  
Роутинг вільного тексту:
- "єпіцентр/epicentr" → route_epicentr()
- "розетка/rozetka" → заглушка [в розробці]
- "prom/ціни/price" → cmd_prices()
- "замовлення/order" → cmd_orders()
- "статус/status" → cmd_status()
- решта → підказка

**`route_epicentr(message, text)`**  
Sub-router для Єпіцентр-специфічних команд (XLS, ціни, API, замовлення).

**`main()`**  
Запускає dp.start_polling() з drop_pending_updates=True.

#### Що можна покращити:
- /ttn команда: реалізована в логіці handle_document але немає окремого хендлера
- Inline кнопки для вибору замовлення при кількох збігах
- /stats — більш детальна статистика за місяць
- Webhook замість polling для Production (менше затримка)
- Обробка Excel від Carvol (не тільки PDF)

---

### 4.3 `orchestrator/orchestrator.py` — 244 рядки

LLM-оркестратор агентів. Використовує Ollama на ноутбуці.

#### Функції:

**`get_system_snapshot() → dict`**  
Читає JSON snapshot з Redis key "system:snapshot".

**`save_system_snapshot(snapshot)`**  
Зберігає JSON snapshot до Redis.

**`get_agents_status() → dict`**  
SELECT name, status FROM agents → {name: status}.

**`generate_and_save_skill(task_description, agent_name) → str`**  
Генерує Markdown skill-файл через LLM (промпт з інструкцією структури).  
Зберігає в `shared/skills/{agent_name}/auto_{name}.md`.  
Індексує в Qdrant через `index_all_skills()`.

**`route_task(command) → dict | None`**  
Основна функція маршрутизації:
1. Завантажує skills context для "orchestrator"
2. Якщо скілів немає → generate_and_save_skill()
3. Формує промпт для LLM з агентами і командою
4. Парсить JSON відповідь (robust: шукає {}, чистить сміття)
5. Оновлює snapshot
6. Повертає {agent, task_type, description, priority, context}

**`process_command(command) → dict | None`**  
Обробляє команду:
1. route_task() → рішення
2. Формує task dict
3. push_task() в чергу відповідного агента
4. save_memory() в Qdrant
5. log_event() + create_alert()

**`listen_loop()`**  
Нескінченний цикл: pop_task("queue:orchestrator") → process_command().

#### Що можна покращити:
- Підключити Claude API замість Ollama для точнішого routing
- Додати feedback loop: агент повідомляє про результат
- Таймаути на завдання (якщо агент не відповів за N хвилин)
- A/B тест різних промптів для routing

---

### 4.4 `shared/utils/pricing.py` — 497 рядків

Централізована утиліта ціноутворення.

#### Функції:

**`translate_category(category_name) → str`**  
Словник з ~100 записів RU→UK для категорій Prom API.  
Повертає оригінал якщо переклад не знайдено.

**`get_prom_cpa(prom_category_name) → float`**  
Пошук комісії Prom у таблиці prom_cpa_rates (3 рівні):
1. Точний збіг (LOWER =)
2. Часткове входження (LIKE %name%)
3. Зворотнє входження (%category_name% LIKE name)
4. Fallback: DEFAULT_PROM_CPA = 15%

**`get_rozetka_commission(category_id, price) → float`**  
Читає price_ranges з rozetka_cpa_rates для категорії.  
Повертає комісію відповідно до діапазону ціни (дорожче → менше комісія).

**`get_epicentr_cpa(epicentr_category_name) → float`**  
Аналогічний пошук для Єпіцентру. 2 рівні: точний + частковий.

**`calc_price(rrс_price, commission_rate, min_price, round_to) → float`**  
`raw = rrс_price * (1 + commission_rate)`  
Округлення вгору до round_to (10 грн).  
Мінімум min_price (40 грн).  
⚠️ Формула `РРЦ * (1 + CPA)` а не `РРЦ / (1 - CPA)` — важлива відмінність.

**`calc_prom_price(rrс_price, prom_category_name) → (price, pct)`**  
Зручна обгортка: get_prom_cpa() + calc_price().

**`calc_rozetka_price(rrс_price, rozetka_category_id) → (price, pct)`**  
Зручна обгортка для Розетки.

**`calc_epicentr_price(rrс_price, epicentr_category_name) → (price, pct)`**  
Зручна обгортка для Єпіцентру.

#### Що можна покращити:
- Кешування результатів get_prom_cpa (часто повторюються ті самі категорії)
- Формула ціни: варто перевірити яка правильніша — `*(1+cpa)` чи `/(1-cpa)`
- Додати логіку "мінімальний маржа в грн" не тільки у відсотках

---

### 4.5 `shared/utils/db.py` — 68 рядків

Мінімальна обгортка для PostgreSQL.

**`get_connection() → psycopg2.connection`**  
Підключення через psycopg2 з RealDictCursor (результати як dicts).  
Параметри з .env: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD.

**`log_event(agent_name, level, message, metadata)`**  
INSERT до event_logs з agent_id за назвою агента.

**`create_alert(source, title, message, level)`**  
INSERT до alerts.

**`update_agent_status(agent_name, status)`**  
UPDATE agents SET status, updated_at.

#### Що можна покращити:
- Connection pool (psycopg2.pool або asyncpg)
- Retry при connection timeout
- Context manager для auto-commit/rollback

---

### 4.6 `shared/utils/redis_queue.py` — 34 рядки

Redis-черга для міжагентної комунікації.

**`push_task(queue_name, task)`**  
rpush (додає в кінець черги).

**`pop_task(queue_name, timeout=5) → dict | None`**  
blpop (блокуючий pop з лівого кінця, тайм-аут 5 сек).

**`get_queue_length(queue_name) → int`**  
llen (довжина черги).

---

### 4.7 `shared/utils/memory.py` — 66 рядків

Векторна пам'ять агентів через Qdrant.

**`save_memory(agent_name, content, metadata) → bool`**  
Формує task для embedding_service і кладе в `queue:embeddings`.  
point_id = MD5 hash з agent+content+timestamp (int).

**`search_memory(query, agent_name, limit) → list`**  
Відправляє search task з reply_key, чекає до 10 секунд (polling 0.5s).

**`get_context_for_task(task, agent_name) → str`**  
Форматує топ-3 релевантних спогади для контексту LLM.

#### Архітектурна нотатка:
Пам'ять асинхронна через Redis queue → embedding_service на ноутбуці → Qdrant на сервері.  
Цей підхід обов'язковий через відсутність AVX на сервері.

---

### 4.8 `shared/utils/model_selector.py` — 41 рядок

**`get_model(task_type) → str`**  
Словник: routing→llama3.2:3b, code/analysis→qwen2.5:7b.  
Значення беруться з .env (OLLAMA_MODEL_*).

---

### 4.9 `embedding_service.py` — 127 рядків

Запускається ТІЛЬКИ на ноутбуці (RTX 4050, sentence-transformers вимагає AVX).

**`ensure_collections()`**  
Створює Qdrant колекції "agent_memory" і "agent_skills" (384-dim COSINE) якщо не існують.

**`process_embed_request(task)`**  
model.encode(text) → qdrant.upsert(). Зберігає вектор з payload.

**`process_search_request(task)`**  
model.encode(query) → qdrant.query_points() → відповідь через Redis reply_key.

**`index_skills()`**  
Читає всі .md файли з shared/skills/, розбиває на chunks по 600 символів,  
індексує кожен chunk в "agent_skills" колекцію.

**`listen()`**  
blpop("queue:embeddings") → dispatch за action: embed/search/index_skills.

---

### 4.10 `agents/orders/ttn_pdf_parser.py` — 160 рядків

Парсер PDF накладних Нової Пошти.

**`normalize_phone(phone) → str`**  
+380XXXXXXXXX або 380... → 0XXXXXXXXX.

**`_extract_ttn(text) → str | None`**  
Regexp: `\b(\d{2})\s+(\d{4})\s+(\d{4})\s+(\d{4})\b` (формат НП: "20 4514 5092 1650").  
Fallback: 14 поспіль цифр.

**`_extract_recipient_block(text) → (recipient, city)`**  
Складний парсер дволонкового PDF:
- Шукає рядок "КОМУ" як початок блоку отримувача
- name_re: Прізвище Ім'я По-батькові (mixed case Cyrillic)
- city: спочатку ALL CAPS (місто призначення), потім "Місто, Відділення"

**`parse_ttn_pdf(pdf_path) → dict`**  
Відкриває PDF через pdfplumber, витягує весь текст, запускає всі екстрактори.  
Повертає: {ttn, phone, recipient, city}.

**`_similarity(a, b) → float`**  
SequenceMatcher ratio для нечіткого порівняння рядків.

**`match_order_by_ttn_data(parsed) → list`**  
Шукає в rozetka_processed_orders:
1. Точний збіг phone → score 1.0
2. Якщо не знайдено: fuzzy порівняння recipient+city (combined >= 0.6)

---

### 4.11 `agents/orders/np_api.py` — 192 рядки

Інтеграція з Nova Poshta API.

**`_normalize_phone(phone) → str`**  
Аналогічно ttn_pdf_parser.

**`get_ttn_info(ttn, phone) → dict`**  
POST до api.novaposhta.ua TrackingDocument/getStatusDocuments.  
Повертає: recipient_name, recipient_phone, city, warehouse, cod_sum, status, status_code.  
При помилці повертає error key.

**`_similarity(a, b) → float`**  
SequenceMatcher ratio.

**`_price_score(actual, expected) → float`**  
Оцінка схожості ціни: 0.0 якщо різниця > 5%, інакше пропорційний score.

**`match_order_by_np_data(ttn_info) → list`**  
3-рівневий пошук в rozetka_processed_orders:
1. **phone** — точний збіг → score 1.0 (match_by='phone')
2. **name+price** — fuzzy ім'я >=0.6 + ціна ±5% → weighted (0.7*name + 0.3*price)
3. **price** — тільки ціна ±5% → price score
Повертає після першого рівня де є збіги.

---

### 4.12 `tools/katran_category_xml.py` — генератор XML по категоріях (2026-06-07)

Генерує Розетка YML-XML для конкретних rz_id категорій Катрана.

**Ключові константи:**
- `SKIP_CATEGORIES = {"80255"}` — пропускати повністю (Батарейки)
- `ACCESSORIES_ALLOWED_CATS = {"80071"}` — де "Без бренду" дозволено
- `ACCESSORY_KEYWORDS` — насадка/фільтр для/мішок для/щітка для/тощо

**`generate_category_xml(rz_ids, output_file) → dict`**  
3-прохідна генерація:
1. Pass 1: фільтрація (rz_id, наявність, дедуп артикулів)
2. Pass 2: лічильник однакових назв (для розрізнення → додає артикул)
3. Pass 3: будова офферів + фільтри уцінок/б.в./аксесуарів без бренду

Фільтри в Pass 3:
- уцінки: `"уцін" in vendor.lower() or vendor.startswith("!") or "б/у" in vendor.lower()`
- артикул _У: `artikul.endswith("_У")`
- аксесуари без бренду: `vendor == "Без бренду" and rz_id not in ACCESSORIES_ALLOWED_CATS and any(kw in name for kw in ACCESSORY_KEYWORDS)`

Статистика: `{total, categories, cat_names, brands, skipped_price, skipped_sale, skipped_accessory}`

**Usage:**
```bash
python3 tools/katran_category_xml.py 80158,237815
python3 tools/katran_category_xml.py 80011 --output /tmp/my.xml
```

---

### 4.12b `tools/rozetka_xml_validator.py` — валідатор XML фідів (2026-06-07)

Універсальний валідатор YML-XML фідів для Розетки.

**Перевірки структурні (ERR):**
- XML синтаксис, UTF-8 кодування
- yml_catalog → shop → currencies → categories → offers
- Унікальність `offer id`
- `categoryId` кожного оффера є в `<categories>`
- Обов'язкові поля: price>0, currencyId=UAH, picture (HTTPS, <1999 chars, без кирилиці), name 5-255 chars, vendor не пустий/no-name, article, stock_quantity>0

**Попередження якості (WARN):**
- Категорія DEFAULT (25636737) — товар без маппінгу
- Назва >150 символів
- Менше 3 параметрів
- Гарантія = 0 місяців
- HTTP фото (не HTTPS)
- Назва = артикул (без нормальної назви)
- vendor = "Без бренду"

**Виводить:**
- Консоль: прогрес по офферах + підсумок (Помилок/Попереджень)
- `/tmp/validation_report.json` — машинозчитуваний звіт
- `/tmp/validation_report.xlsx` — Excel звіт (пропускається з `--no-xlsx`)

**Usage:**
```bash
python3 tools/rozetka_xml_validator.py data/katran_rozetka.xml
python3 tools/rozetka_xml_validator.py --no-xlsx /tmp/katran_cat_80158.xml
```

---

### 4.12c `tools/katran_pipeline.py` — автоматичний pipeline (2026-06-07)

Повний pipeline генерації, валідації і публікації фіду Катрана.

**Кроки:**
1. Отримує список rz_id з БД або з аргументу `--categories`
2. Завантажує фід Катрана (один раз для всіх категорій)
3. Для кожної категорії: `generate_category_xml()` → окремий XML в `--output-dir`
4. `run_validator()` на кожному файлі
5. Зберігає `pipeline_report.json` (rz_id, name, offers_count, errors, warnings, status)
6. Виводить зведену таблицю
7. `merge_xmls()` → `data/katran_rozetka.xml`
8. Фінальний валідатор на merged файлі
9. `git_push()` якщо вказано `--push`

**Імпортує логіку** з `tools/katran_category_xml.py` (не дублює код).

**Usage:**
```bash
python3 tools/katran_pipeline.py --categories ALL --push
python3 tools/katran_pipeline.py --categories 80158,80011,80193
python3 tools/katran_pipeline.py --categories ALL --output-dir /tmp/my_pipeline/
```

---

### 4.13 `agents/orders/katran_xml_generator.py` — 279 рядків

Генератор Розетка-фіду з фіду Катрана.

**`get_katran_feed() → ET.Element`**  
Завантажує ZIP-архів з KATRAN_FEED_URL_STOCK,  
розпаковує перший XML файл.

**`get_category_map() → dict`**  
SELECT з katran_categories WHERE rozetka_rz_id IS NOT NULL.  
Повертає {katran_category_id: {rz_id, name, commission}}.  
При помилці БД — порожній dict (fallback на defaults).

**`calc_price(price_rrc, commission_pct) → int`**  
`ceil(price_rrc * (1 + commission_pct/100) / 10) * 10`

**`is_in_stock(stock_str) → bool`**  
"есть"/"є" → True, "в резервах" → False.

**`parse_float(text) → float`**  
Безпечний парсер float з коми→крапка.

**`clean_text(text) → str`**  
strip().

**`fix_name(name, artikul) → str`**  
Нормалізує пробіли, обрізає до 255 символів. Якщо немає → artikul.

**`xml_escape(text) → str`**  
&amp; &lt; &gt; &quot; для XML.

**`generate_xml(output_file) → (path, count, stats)`**  
Головна функція:
1. Завантажує фід Катрана
2. Завантажує cat_map з БД
3. Фільтрує: тільки is_in_stock() + name + price > 0
4. Будує текстовий XML (не ElementTree) для YML catalog формату
5. Зберігає в data/katran_rozetka.xml
6. Повертає статистику (total/in_stock/skipped_*)

---

### 4.13 `agents/orders/rozetka_github_sync.py` — 257 рядків

Щоденна (cron 7:00) синхронізація цін Carvol у XML.

**`tg(msg)`**  
Telegram сповіщення.

**`calc_price(price, cat_id) → float`**  
Локальна таблиця CPA_RULES по cat_id (1-16).  
ceil(price * (1 + rate) / 10) * 10.

**`fetch_carvol_live() → dict`**  
Завантажує живий фід Carvol, повертає {article: {price, qty, available}}.

**`update_prices_only(live) → dict`**  
Читає data/carvol_rozetka.xml, оновлює ТІЛЬКИ:
- offer[@available]
- `<price>`
- `<stock_quantity>`
Структура, категорії, назви, фото — незмінні.  
Зберігає приклади (перші 5) для перевірки.

**`git_push() → bool`**  
git add → git commit → git push.  
Перевіряє "nothing to commit" як успіх.

**`main()`**  
fetch_carvol_live() → update_prices_only() → git_push() → Telegram звіт.

---

### 4.14 `agents/orders/price_engine.py` — 794 рядки

Головний двигун ціноутворення. Найбільший файл системи.

**`tg(text)` / `tg_file(path, caption)`**  
Telegram: текст і файловий вкладення.

**`load_config() → dict`**  
Конфігурація з price_engine_config (alert_threshold_pct, min_price, round_to, etc.).

**`update_config(key, value)`**  
Upsert до price_engine_config.

**`load_feed() → dict`**  
XML фід TOPTUL → {SKU: {price, available, stock}}.  
SKU береться з `<vendorCode>` або offer id.

**`load_previous_prices() → dict`**  
DISTINCT ON (sku) ORDER BY date DESC з price_history.  
Повертає останню відому ціну для кожного SKU.

**`load_db_products(limit) → list`**  
SELECT з my_products: sku, price_supplier, price_our + prom_category_name (якщо є).

**`load_prom_map() → dict`**  
Завантажує всі товари з Prom API (pagination по last_id, батчі по 100).  
{SKU: {id, price}}.

**`process_products(feed, db_products, prev_prices, config, full_mode) → (records, prom_updates, stats)`**  
Ядро price engine:
- Для кожного товару з БД → знаходить у фіді → calc_price з CPA
- Порівнює з попередньою ціною
- Визначає is_change (зміна > 1 грн) і is_alert (зміна > threshold%)
- full_mode: зберігає навіть без змін
- Готує prom_updates для API батч-оновлення

**`save_history(records, dry_run) → int`**  
INSERT INTO price_history + UPDATE my_products.price_our.  
ON CONFLICT (sku, date) DO UPDATE.

**`update_prom_prices(prom_updates, prom_map, records, dry_run) → int`**  
POST /products/edit батчами по 100.  
Позначає prom_updated=TRUE в history.

**`write_alerts_csv(records, filepath) → str | None`**  
Записує алерти у CSV (utf-8-sig для Excel сумісності).

**`cleanup_old_history(days_keep)`**  
DELETE WHERE date < cutoff.

**`run(full_mode, dry_run, no_prom, limit, report_only)`**  
Режими: normal/full/dry-run/no-prom/report-only/limit.  
Надсилає Telegram звіт + CSV файл алертів.

---

### 4.15 `agents/orders/price_audit.py` — 471 рядок

Аудит цін (одноразовий або за розкладом).

**`tg_message(text)` / `tg_file(path, caption)`**  
Telegram функції.

**`load_feed() → dict`**  
XML фід TOPTUL.

**`load_db_products() → list`**  
Завантажує товари з my_products.

**`audit_prices(feed, db_products, alert_threshold) → (all_results, alerts)`**  
Порівнює поточну ціну БД з новою розрахованою.  
Визначає: зміна%, CPA джерело, is_alert.

**`write_csv(results, file_path)`**  
Записує повний звіт у CSV з 15 колонками.

**`run(alert_threshold, send_telegram)`**  
Запускає аудит, відправляє 2 CSV файли (повний + алерти).

---

### 4.16 `agents/orders/price_updater.py` — 395 рядків

Щоденне оновлення цін на Prom (cron 8:00).

**`load_feed() → dict`**  
XML фід TOPTUL.

**`load_prom_map() → dict`**  
Prom API pagination → {SKU: {id, price}}.

**`load_db_products(limit, force) → list`**  
Товари з my_products. force=True → всі, False → тільки ті де є prom_id.

**`run(force, dry_run, limit)`**  
1. feed → prom_map → db_products
2. Для кожного: якщо ціна змінилась (або force) → calc_price → оновлює БД
3. Батч POST /products/edit до Prom API
4. Telegram звіт з топ-3 змін

---

### 4.17 `agents/orders/feed_sync.py` — 232 рядки

Синхронізація наявності/цін для Єпіцентру (cron кожні 4 год).

**`tg(msg)`**  
Telegram.

**`epicentr_price(price_our, category_name) → float`**  
price_our * 1.15 (або 1.10 для компресорів) → ceil до 10 грн.

**`fetch_feed() → dict`**  
XML фід TOPTUL → {sku: {available, price, name}}.

**`sync_with_db(feed) → dict`**  
JOIN my_products + epicentr_sku_mapping.  
Якщо ціна постачальника змінилась: UPDATE price_supplier, price_our, epicentr_price.

**`generate_update_xml(feed) → (in_stock, out_of_stock)`**  
XML для автооновлення Єпіцентру (offer id + price + availability).  
Зберігає в shared/feeds/epicentr_update.xml.

**`main()`**  
fetch_feed → sync_with_db → generate_update_xml → Telegram звіт.

---

### 4.18 `agents/orders/epicentr_xml_generator.py` — 398 рядків

Генератор повного XML для первинного імпорту в Єпіцентр.

**`load_feed_data() → dict`**  
Завантажує фід TOPTUL для фото і описів. Кешує в `_feed_cache`.

**`generate_xml(output_path, category_filter, limit, confidence_filter) → int`**  
Генерує XML по стандарту Єпіцентру (yml_catalog):
- Кожен offer: price, availability, category, attribute_set, name(ua/ru), picture(x10), description, vendor, country, params
- Параметри: measure(шт.), ratio(1), brand(TOPTUL), country(Тайвань)
- Бере тільки товари з epicentr_category_id IS NOT NULL + confidence IN filter

**`generate_by_category(output_dir, confidence_filter) → dict`**  
Генерує окремий XML файл для кожної категорії.  
Зручно для покрокового завантаження в кабінет.

---

### 4.19 `agents/orders/epicentr_order_agent.py` — 487 рядків

Агент замовлень Єпіцентру. Аналог rozetka_order_agent.

**`tg(msg)`** / **`parse_price(val) → float`**  
Утиліти.

**`get_feed_data(force) → dict`**  
XML фід TOPTUL → {sku: {available, price, name}}.

**`get_new_orders() → list`**  
GET /v3/oms/orders?statusCode=new.

**`get_order_details(order_id) → dict`**  
GET /v5/oms/orders/{id}.

**`accept_order(order_id) → bool`**  
1. GET allowed-statuses → перевіряє "confirmed_by_merchant"
2. POST change-status/to/confirmed_by_merchant

**`cancel_order(order_id, reason) → bool`**  
POST change-status/to/canceled_by_merchant з reason_code.

**`save_to_db(order, status)`**  
INSERT до epicentr_processed_orders (замовлення JSONB).

**`is_already_processed(order_id) → bool`**  
SELECT з epicentr_processed_orders.

**`create_order_excel(order, items_info) → str`**  
Аналогічний Розетці Excel бланк але для TOPTUL/Гранд Інструмент.

**`send_to_supplier(order, excel_path, items_info) → bool`**  
SMTP email на opt@grandinstrument.ua.

**`process_order(order, feed)`**  
1. Перевіряє наявність SKU у фіді TOPTUL
2. Шукає our_sku через epicentr_sku_mapping
3. Скасовує якщо немає товару
4. accept_order → Excel → email → save('accepted')

**`main()`**  
Нескінченний цикл кожні 300 сек.

---

### 4.20 `shared/mcp_servers/rozetka_mcp.py` — 318 рядків

MCP сервер Розетки для Claude Code.

**`get_rozetka_token() → str`**  
POST /sites з login/password → Bearer token. Кешує на 23 години.

**`rozetka_get(endpoint, params) → dict`**  
GET з Bearer auth.

**`rozetka_post(endpoint, data) → dict`**  
POST з Bearer auth.

**Інструменти MCP:**
- `rozetka_get_orders` — список замовлень з фільтром за статусом
- `rozetka_get_order` — деталі замовлення
- `rozetka_set_order_status` — зміна статусу + ТТН
- `rozetka_get_xml_status` — стан XML прайсу
- `rozetka_validate_xml` — валідатор PriceCreator
- `rozetka_get_shop_info` — інфо про магазин

---

### 4.21 `shared/mcp_servers/epicentr_mcp.py` — 568 рядків

MCP сервер Єпіцентру. FastMCP (12 інструментів).

**Статус-маппінг:**  
`UNIFIED_TO_EPICENTR` і `EPICENTR_TO_UNIFIED` — двонаправлений словник.

**Інструменти MCP:**
- `search_orders(status, limit, date_from, date_to)` — список з уніфікованими статусами
- `get_order(order_id)` — повні деталі
- `update_order_status(order_id, action)` — accept/confirm/ship/cancel + перевірка allowed
- `add_order_ttn(order_id, ttn, provider)` — ТТН + автоматично ship
- `update_order_client(...)` — зміна даних клієнта
- `update_order_delivery(...)` — зміна адреси доставки
- `add_order_comment(order_id, comment)` — коментар
- `get_cancel_reasons()` — список причин скасування
- `find_delivery_office(provider, city_name, office_number)` — відділення НП/УП
- `get_delivery_invoice(provider, company_id, invoice_number)` — інфо по ТТН
- `get_categories(search, limit)` — категорії PIM
- `get_attribute_options(attribute_set_code, attribute_code, search)` — valuecodes для XML

---

### 4.22 `agents/scraper/scraper_agent.py` — 309 рядків

Playwright скрапер для конкурентного аналізу.

**`human_delay(min_ms, max_ms)`**  
Рандомна затримка для anti-bot.

**`human_scroll(page, steps)`**  
Імітація скролу мишкою.

**`build_stealth_context(playwright) → (browser, context)`**  
Stealth браузер: рандомний User-Agent, viewport, locale=uk-UA.  
JS патч: navigator.webdriver → undefined.

**`parse_rozetka(category_url, max_items) → list`**  
Парсить `li.catalog-grid__cell`: title, price, url.

**`parse_prom(search_query, max_items) → list`**  
Парсить `div[data-qaid='product_gallery_item']`.

**`prom_api_get_products(max_items) → list`**  
Офіційний Prom API (pagination): всі товари магазину.

**`save_products(products)`**  
UPSERT до scraped_products по MD5(marketplace+url+title).

**`handle_task(task) → list`**  
Роутер задач: rozetka/prom_api/prom/default.

**`listen_loop()`**  
pop_task("queue:scraper") → handle_task().

---

### 4.23 `dashboard/api.py` — 387 рядків

FastAPI дашборд.

**`fix_types(rows) → list`**  
Конвертує datetime→isoformat, Decimal→float.

**`update_env(key, value)`**  
Патчить .env файл (read + regex replace + write).

**`mask_token(val) → str`**  
"•••••1234" для безпечного відображення токенів.

**`get_stats() → dict`**  
Агрегований стан системи: агенти, алерти, логи, продукти, черги.

**Endpoints:**
- `GET /api/stats` — стан системи
- `POST /api/command` — відправити команду оркестратору
- `POST /api/alerts/read` — позначити алерти прочитаними
- `GET /api/products` — список товарів з фільтрацією та пагінацією
- `POST /api/products/{id}/upload-prom` — запустити upload до Prom
- `GET /api/settings` — налаштування (токени замасковані)
- `POST /api/settings` — зберегти токени в .env
- `POST /api/settings/check/{marketplace}` — перевірити підключення
- `WebSocket /ws` — realtime stats кожні 5 сек
- `WebSocket /ws/chat` — лог подій кожну 1 сек

---

### 4.24 `cli.py` — 347 рядків

Термінальний CLI для адміністрування.

**`print_status()`** — агенти + черги + snapshot + статистика  
**`print_logs(agent_name, limit)`** — кольоровий лог подій  
**`print_queues()`** — прогрес-бари черг  
**`print_alerts(limit)`** — алерти з позначкою NEW  
**`print_skills(agent_name)`** — список skills по агентах  
**`send_command(cmd)`** — push до queue:orchestrator  
**`interactive_chat()`** — REPL для оркестратора  
**`create_skill_interactive()`** — інтерактивне створення .md skill файлу  
**`check_marketplaces()`** — перевірка Prom API + Ollama + Docker сервіси  

---

## 5. База даних (PostgreSQL, 31+ таблиця)

### Товари
| Таблиця | Записів | Опис |
|---|---|---|
| `my_products` | ~5 908 | TOPTUL товари: sku, name_uk, price_supplier, price_our, availability, prom_id, epicentr_category_id, attributes (JSONB) |
| `carvol_products` | ~8 304 | Carvol товари автоелектроніки |
| `scraped_products` | - | Товари зі скрапінгу конкурентів |

### Замовлення
| Таблиця | Опис |
|---|---|
| `orders` | Prom: prom_order_id, status, customer_name/phone, delivery, items (JSONB), ttn |
| `rozetka_processed_orders` | Розетка: order_id, status, **phone, recipient, city, ttn** (для TTN-матчингу) |
| `epicentr_processed_orders` | Єпіцентр: order_id, ext_id, status, items JSONB |

### Категорії та маппінги
| Таблиця | Записів | Опис |
|---|---|---|
| `katran_categories` | 5 124 | id, parent_id, name, rozetka_category, rozetka_rz_id, commission_pct, product_count |
| `epicentr_categories` | 4 054 | Категорії Єпіцентру |
| `rozetka_categories` | 37 | Категорії Розетки |
| `prom_categories` | - | Категорії Prom |
| `supplier_category_mapping` | 384 | Маппінг постачальник→маркетплейс |
| `epicentr_sku_mapping` | - | Маппінг SKU Єпіцентру → наш SKU |

### Ціни та комісії
| Таблиця | Опис |
|---|---|
| `price_history` | SKU, date, feed_price, our_price, diff_pct, is_alert, prom_updated |
| `price_engine_config` | alert_threshold_pct, min_price, history_days_keep, etc. |
| `prom_cpa_rates` | 68 категорій Prom з % комісії |
| `epicentr_cpa_rates` | 236 категорій Єпіцентру з % комісії |
| `rozetka_cpa_rates` | 16 категорій Розетки з price_ranges JSON |

### Система та логи
| Таблиця | Опис |
|---|---|
| `agents` | Реєстр агентів (name, status, updated_at) |
| `event_logs` | Лог подій (agent_id, level, message, metadata JSONB) |
| `alerts` | Алерти (source, title, message, level, is_read) |

---

## 6. Cron-розклад (сервер)

```
0 8 * * *    price_updater.py         — оновлення цін Prom (08:00)
0 */4 * * *  feed_sync.py             — синхронізація Єпіцентр (кожні 4 год)
0 7 * * *    rozetka_github_sync.py   — ціни Carvol XML (07:00)
(planned)    katran_github_sync.py    — ціни Катран XML (щогодинно)
```

**Systemd --user сервіси (постійно):**
- `rozetka-order-agent` — обробка замовлень Розетки (цикл 300с)
- `epicentr-order-agent` — обробка замовлень Єпіцентру (цикл 300с)
- `tg-dispatcher` — Telegram бот (polling)
- `feed-server` — HTTP сервер для фідів

---

## 7. Стан розробки

### ✅ Готово і працює
- Автоматична обробка замовлень Розетки (Carvol): new → confirm → Excel → Telegram
- Автоматична обробка замовлень Єпіцентру (TOPTUL): new → confirm → Excel → email
- Автоматичне встановлення ТТН: PDF від Carvol → parse → match (3 рівні) → set_ttn → ship(3) → верифікація
- Carvol XML генерація та щоденна синхронізація через GitHub
- Катран XML генератор + katran_github_sync.py (готові, чекаємо GitHub лінк в кабінеті)
- Ціновий двигун TOPTUL → Prom (щоденно, alert CSV)
- Синхронізація фіду Єпіцентру (кожні 4 год)
- Telegram бот: команди, голос (Whisper), PDF обробка, безпека
- MCP сервери (Розетка, Єпіцентр) для Claude Code
- Dashboard (FastAPI + WebSocket)
- Маппінг 1790 категорій Катрана (34 категорії в XML → ~45% товарів, 2486 офферів)
- `tools/katran_category_xml.py` — генератор XML по окремих rz_id категоріях
- `tools/rozetka_xml_validator.py` — валідатор XML фідів Розетки (ERR/WARN/JSON/XLSX звіт)
- `tools/katran_pipeline.py` — автоматичний pipeline (генерація → валідація → merge → push)
- `shared/knowledge_base/rozetka/api_advanced.txt` — розширена API документація (повернення, відгуки, реклама, причини скасування)

### 🔄 В процесі
- Маппінг решти ~55% категорій Катрана (IT-категорії: смартфони, планшети, кабелі, USB тощо)
- Налаштування GitHub посилання для Катрана в кабінеті Розетки (через менеджера Софію)

### ❌ Заплановано
- `katran_order_agent.py` — агент замовлень Катрана (аналог rozetka_order_agent)
- /ttn окрема команда в tg_dispatcher (зараз тільки в handle_document)
- Виправлення Молотки/Біти/Набори пневмо/Мультиметри для Єпіцентру
- Перевірка XML katran_rozetka.xml через валідатор Розетки
- Агент моніторингу цін конкурентів (real-time)

---

## 8. Відомі обмеження та проблеми

| Проблема | Деталі | Рішення |
|---|---|---|
| AVX на сервері | sentence-transformers → exit 132 | embedding_service тільки на ноутбуці через Redis queue |
| SSL Розетка | `verify=False` обов'язково | Старий сервер Celeron з протухлим сертом |
| Статичний токен Розетки | `gapi_...` — треба активність раз на добу | Cron-запит або keep-alive |
| ~55% товарів Катрана без категорій | IT-категорії (смартфони, кабелі, USB) без rz_id | Перевірити в PriceCreator |
| Cron rozetka_github_sync зламаний | Відносний шлях без cd → файл не знайдено | Замінити на абсолютний шлях або додати cd |
| Prom баланс | ~325 грн залишилось | Поповнити |
| patch-скрипти з docstrings | `r"""..."""` конфліктує з внутрішніми `"""` | Використовувати окремий файл |

---

## 9. Що можна покращити (по компонентах)

### rozetka_order_agent.py
- **Retry логіка**: API помилки зараз тільки логуються — потрібен retry з exponential backoff
- **Часткова наявність**: якщо 2 товари з 3 є → не скасовувати, а питати адміна
- **Передоплата**: зараз просто чекає, але не слідкує — потрібен окремий цикл перевірки

### tg_dispatcher/main.py
- **Inline кнопки**: при кількох TTN збігах показувати кнопки вибору замість тексту
- **/ttn команда**: зараз немає окремого хендлера — додати `@dp.message(Command('ttn'))`
- **Webhook**: замість polling для Production (менша затримка, менше запитів)
- **Обробка Excel від Carvol**: приймати xlsx підтвердження, не тільки PDF

### price_engine.py
- **Кешування CPA**: get_prom_cpa() викликається тисячі разів — потрібен in-memory dict cache
- **Паралельна обробка**: батчі товарів можна обробляти паралельно (asyncio або ThreadPool)
- **Автозапуск Prom update**: зараз окремий скрипт (price_updater.py) — об'єднати

### np_api.py / ttn_pdf_parser.py
- **Кілька ТТН в одному PDF**: наразі береться тільки перший знайдений
- **Нормалізація ПІБ**: різні порядки слів (Прізвище Ім'я vs Ім'я Прізвище)
- **Кешування NP API**: одна ТТН може запитуватись кілька разів

### orchestrator/orchestrator.py
- **LLM**: замінити Ollama на Claude API для точнішого routing
- **Feedback loop**: агент повідомляє оркестратор про результат
- **Таймаути**: якщо агент не відповів за N хвилин — переводити задачу

### dashboard/api.py
- **Авторизація**: зараз без auth — додати хоча б API key
- **WebSocket broadcasting**: зараз не використовується активно
- **Метрики**: додати endpoint для Prometheus/Grafana

---

## 10. Масштабування для інших клієнтів

Система спроектована для одного магазину, але може бути адаптована:

### Мінімальні зміни для другого клієнта
1. **Конфіг у БД**: перенести MARKETPLACE, SUPPLIER_CODE, TG_CHAT_ID зі змінних в таблицю `clients`
2. **Multi-tenant схема**: додати `client_id` до orders, my_products, price_history
3. **Окремий .env на клієнта**: або prefix-based (CLIENT1_ROZETKA_TOKEN, etc.)

### Архітектурні зміни
```
clients таблиця:
  id, name, marketplaces JSONB, suppliers JSONB, settings JSONB

rozetka_order_agent → class RozetkaAgent(client_id):
  self.token = clients[client_id].rozetka_token
  self.tg_chat = clients[client_id].tg_chat_id
```

### Що вже легко масштабується
- **price_engine.py**: додати `client_id` параметр, CPA таблиці вже поділені
- **XML генератори**: параметр SHOP_NAME/SHOP_URL
- **TG dispatcher**: можна запустити кілька ботів для різних клієнтів
- **Redis queues**: `queue:rozetka:client1`, `queue:rozetka:client2`

### Що потребує значного рефакторингу
- Hardcoded `sys.path.append('/home/tek/agent-system')` — повинно бути відносним
- Hardcoded `/home/tek/agent-system/shared/feeds/` — потрібна конфігурація шляхів
- Hardcoded `SUPPLIER_CODE = '000160594'` — переносити в .env або БД

---

## 11. Змінні середовища (.env)

| Змінна | Призначення |
|---|---|
| `ROZETKA_API_TOKEN` | Статичний Bearer токен Розетки (`gapi_...`) |
| `EPICENTR_TOKEN` | Bearer токен Єпіцентру |
| `PROM_API_TOKEN` | Токен Prom.ua |
| `KATRAN_FEED_URL_STOCK` | URL ZIP-архіву фіду Катрана |
| `NP_API_KEY` | Nova Poshta API ключ |
| `CARVOL_TG_CHAT_ID` | Telegram Chat ID Carvol (8035052611) |
| `CARVOL_SUPPLIER_EMAIL` | Email Carvol (carvolua@gmail.com) |
| `CARVOL_SUPPLIER_CODE` | Код клієнта Carvol |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram бота |
| `TELEGRAM_ADMIN_ID` | ID адміна (6762672351) |
| `TG_BOT_TOKEN` | Дублює TELEGRAM_BOT_TOKEN (для агентів) |
| `TG_CHAT_ID` | Дублює TELEGRAM_ADMIN_ID (для агентів) |
| `SMTP_USER/PASS/HOST/PORT` | Gmail SMTP |
| `DB_HOST/PORT/NAME/USER/PASSWORD` | PostgreSQL |
| `REDIS_HOST/PORT` | Redis |
| `SERVER_IP` | IP сервера (для embedding_service на ноутбуці) |
| `OLLAMA_MODEL` | Модель Ollama (dolphin-llama3) |
| `OLLAMA_MODEL_ROUTING/CODE/TEXT/ANALYSIS/DEFAULT` | Моделі по типах задач |

---

## 12. Контакти

| Роль | Контакт |
|---|---|
| Розетка (менеджер) | Софія Івановська ivanovskaya@rozetka.ua |
| TOPTUL / Гранд Інструмент | rusanov@grandinstrument.ua, opt@grandinstrument.ua |
| Carvol (Email) | carvolua@gmail.com |
| Carvol (Telegram) | +380971574150, Chat ID: 8035052611 |
| Катран (менеджер) | Сергій Голубцов srgolubtsov@katran.vn.ua +380632822022 |
| Єпіцентр (менеджер) | e.tambovskiy@epicentrk.ua |

---

## 13. TODO (наступні сесії)

1. **Катран категорії** — підтвердити rz_id через PriceCreator:
   `seller.rozetka.com.ua/gomer/pricevalidate/check/index`  
   Кандидати: Кабелі(80329), USB(80333), Картриджі(80296), Корпуси ПК(80038),
   Кулери(80049), Чорнила(73126), Чохли(4638562), Плівки(4638563),
   LED(4638153), Світильники(4638228), ЗП мобільні(4638593), USB Hub(80339)

2. **Валідатор XML** Катрана — перевірити katran_rozetka.xml через Розетку

3. **GitHub посилання** — налаштувати друге посилання для Катрана (через Софію Івановську)

4. **Cron katran_github_sync** — додати на сервері:
   ```
   0 * * * * /home/tek/agent-system/venv/bin/python3 /home/tek/agent-system/agents/orders/katran_github_sync.py >> /tmp/katran_sync_cron.log 2>&1
   ```

5. **/ttn команда** в tg_dispatcher — окремий хендлер `@dp.message(Command('ttn'))`

6. **katran_order_agent.py** — агент замовлень Катрана

7. **Виправлення Єпіцентр** — Молотки/Біти/Набори пневмо/Мультиметри
