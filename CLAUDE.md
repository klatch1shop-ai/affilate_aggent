# Dropshipping Agent System — Інструкції для Claude Code

## Про проект
Автоматизація дропшипінг-бізнесу на маркетплейсах Prom.ua, Розетка, Єпіцентр.
Постачальники: TOPTUL/Гранд Інструмент (Prom+Єпіцентр), Carvol (Розетка).

## Інфраструктура
- Сервер tek@100.82.24.112 (Tailscale) — PostgreSQL, Redis, Qdrant, всі агенти
- Ноутбук 100.126.131.55 — Ollama (RTX 4050), embedding_service.py
- З'єднання — Tailscale VPN між всіма машинами
- GitHub — github.com/klatch1shop-ai/affilate_aggent

## Підключення до сервера
ssh tek@100.82.24.112
Всі команди на сервері: cd /home/tek/agent-system && source venv/bin/activate

## База даних
docker exec -it agent_postgres psql -U agent agentdb

## Розетка API
Base URL: https://api-seller.rozetka.com.ua
Auth: Bearer ROZETKA_API_TOKEN з .env
SSL: verify=False обов'язково (старий сервер Celeron з протухлим сертом)
PATCH /orders/{id} {"status": 2} — підтвердити замовлення
PATCH /orders/{id} {"status": 3} — передано в доставку
PATCH /orders/{id} {"status": 6} — скасувати
POST  /orders/add-ttn {"order_id", "ttn", "delivery_service_id": 1} — встановити ТТН (primary)
PATCH /orders/{id} {"ttn": "номер"} — встановити ТТН (fallback якщо add-ttn не спрацював)
GET /orders/search?types=4 — нові замовлення
GET /orders/search?status={status} — замовлення за статусом
GET /orders/{id} — деталі замовлення (для верифікації ТТН)

## Послідовність статусів Розетки
new (types=4) → confirm → status 2 (підтверджено)
→ set_ttn [POST /orders/add-ttn] → status 61 (TTN додано, автоматично Розеткою)
→ change_status(3) → status 3 (передано в доставку)
Скасування: status 6

Цикл TTN:
1. process_order підтверджує → Excel → Carvol Telegram → save_to_db('accepted')
2. PDF від Carvol → handle_document → parse → NP API → match → set_ttn → status 61 → change_status(3) → верифікація GET

## Nova Poshta API
URL: https://api.novaposhta.ua/v2.0/json/
Key: NP_API_KEY в .env (отримати на my.novaposhta.ua/settings/index#apikeys)
Method: POST TrackingDocument/getStatusDocuments
Повертає: RecipientFullName, PhoneRecipient, CityRecipient, WarehouseRecipient, CashPaymentAmount, StatusCode

## Постачальник Carvol (Розетка)
Telegram ID: 8035052611 (CARVOL_TG_CHAT_ID в .env)
Telegram: +380971574150
Email: carvolua@gmail.com
Цикл: ми відправляємо Excel → вони скидають PDF накладної НП з ТТН

## Автоматизація ТТН — РЕАЛІЗОВАНО (2026-05-29)
1. Нове замовлення → підтверджуємо (status 2) → Excel в Telegram Carvol → save_to_db('accepted')
2. Carvol скидає PDF накладної → бот отримує від chat ID 8035052611
3. handle_document: parse_ttn_pdf → витягує ТТН (формат "20 4514 5092 1650") + телефон/ім'я/місто
4. get_ttn_info (NP API) → уточнює дані отримувача та cod_sum
5. match_order_by_np_data: phone (score 1.0) → name+price (fuzzy 0.6+) → price (±5%)
   Fallback: match_order_by_ttn_data з PDF якщо NP API недоступний
6. Один збіг → set_ttn() + change_status(3) автоматично без підтверджень
7. Верифікація: GET /orders/{id} через 2с → ALARM якщо ТТН не збереглось
8. Кілька збігів → список адміну → ручне /ttn ORDER_ID TTN

## Ключові файли агентів
- agents/orders/ttn_pdf_parser.py — парсинг PDF накладних НП (parse_ttn_pdf, match_order_by_ttn_data)
- agents/orders/np_api.py — NP API інтеграція (get_ttn_info, match_order_by_np_data)
- agents/orders/rozetka_order_agent.py — Розетка агент (set_ttn з POST+fallback PATCH, change_status, get_order_details, process_order)
- tg_dispatcher/main.py — Telegram бот (handle_document, security_middleware, /ttn команда)

## Важливі правила
1. Завжди перевіряти синтаксис: python3 -c "import ast; ast.parse(open('file.py').read())"
2. Перед змінами робити backup: cp file.py file.py.bak
3. SSL verify=False для Розетки API (старий сервер Celeron)
4. НЕ запускати sentence-transformers на сервері (немає AVX — exit code 132)
5. Embeddings генеруються на ноутбуці через Redis queue:embeddings
6. Логи: /tmp/rozetka_order_agent.log, /tmp/epicentr_order_agent.log
7. Патч-скрипти — не використовувати r"""...""" якщо всередині є docstrings з """. Використовувати окремий файл + звичайний open().read()

## Telegram бот
Token: TELEGRAM_BOT_TOKEN в .env
Admin ID: 6762672351
Carvol Chat ID: 8035052611 (CARVOL_TG_CHAT_ID в .env)
Файл: tg_dispatcher/main.py (aiogram 3.x)
security_middleware: ADMIN_ID — повний доступ; CARVOL_TG_CHAT_ID — тільки document (PDF)

## Активні сервіси
systemctl --user: epicentr-order-agent, rozetka-order-agent, tg-dispatcher, feed-server
