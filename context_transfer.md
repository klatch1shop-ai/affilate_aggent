# Context Transfer — Dropshipping Agent System

Дата: 2026-05-29

## Стан проекту

### Завершено
- **ttn_pdf_parser.py** (`agents/orders/ttn_pdf_parser.py`)
  - `parse_ttn_pdf(pdf_path)` — витягує ТТН (regex `\b(\d{2})\s+(\d{4})\s+(\d{4})\s+(\d{4})\b`), телефон, ім'я, місто
  - `match_order_by_ttn_data(parsed)` — матчинг по phone (score 1.0) або fuzzy name+city (≥0.6)
  - `normalize_phone()` — будь-який формат → 0XXXXXXXXX

- **np_api.py** (`agents/orders/np_api.py`)
  - `get_ttn_info(ttn, phone)` — POST TrackingDocument/getStatusDocuments → dict з recipient_name, recipient_phone, city, warehouse, cod_sum, status
  - `match_order_by_np_data(ttn_info)` — 3 рівні: phone exact (1.0) → name+price fuzzy (n*0.7+p*0.3) → price ±5%

- **rozetka_order_agent.py** — повністю переписаний (v4)
  - `set_ttn(order_id, ttn)` — спочатку POST /orders/add-ttn (→ auto status 61), fallback PATCH /orders/{id} {"ttn": ttn}
  - `change_status(order_id, status)` — PATCH /orders/{id}
  - `get_order_details(order_id)` — GET /orders/{id}
  - `get_orders_by_status(status)` — GET /orders/search?status={status}
  - `save_to_db(order, status)` — зберігає phone, recipient, city для матчингу
  - `process_order()` — confirm(2) → Excel → send_excel_to_carvol_telegram → save_to_db('accepted')
  - verify=False на всіх 5 Rozetka API викликах + urllib3.disable_warnings

- **tg_dispatcher/main.py** — handle_document повністю автоматичний
  - Без підтверджень: один збіг → set_ttn + change_status(3) → верифікація GET
  - `_fmt_source_info()` — показує джерело (НП API або PDF) в повідомленнях
  - security_middleware: CARVOL_TG_CHAT_ID (8035052611) може надсилати тільки PDF
  - Усі відповіді від Carvol → ADMIN_ID (6762672351)
  - ALARM повідомлення якщо ТТН не підтвердилось через GET верифікацію

### Послідовність статусів Розетки
```
new (types=4) → status 2 (підтверджено) → set_ttn → status 61 (auto) → status 3 (доставка)
```

### Матчинг замовлень — пріоритет
1. NP API: phone exact → name(≥0.6)+price(±5%) → price(±5%)
2. Fallback PDF: phone exact → name+city fuzzy(≥0.6)
3. Fallback PDF якщо NP API error або 0 збігів

### .env змінні (сервер)
```
ROZETKA_API_TOKEN=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ADMIN_ID=6762672351
CARVOL_TG_CHAT_ID=8035052611
NP_API_KEY=          # ПОРОЖНЬО — потрібно заповнити з my.novaposhta.ua
ANTHROPIC_API_KEY=   # потрібно виправити (зараз placeholder)
```

## Pending задачі
1. **NP_API_KEY** — заповнити в .env на сервері (my.novaposhta.ua/settings/index#apikeys)
2. **ANTHROPIC_API_KEY** — виправити placeholder в .env
3. Закрити 3 зависших замовлення Єпіцентр вручну через dashboard
4. Прибрати .bak файли на сервері (`find /home/tek/agent-system -name "*.bak"`)

## Технічні нотатки
- **AVX**: сервер — старий Celeron без AVX. sentence-transformers там не запускати (exit 132)
- **SSL**: verify=False для всіх Rozetka API запитів
- **Патч-скрипти**: не використовувати `r"""` якщо всередині є docstrings `"""` — конфлікт. Писати новий блок в окремий .py файл
- **asyncio.to_thread** — всі синхронні DB/API виклики в async хендлерах
- **NP TTN формат**: `XX XXXX XXXX XXXX` (14 цифр з пробілами) або 14 цифр підряд
- **psycopg2 RealDictCursor** — row["field"] синтаксис в match функціях
