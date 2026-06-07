# Dropshipping Agent System — Повна технічна документація

> Станом на: 2026-06-07

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
| Катран | Розетка | 🔄 в процесі (XML готовий, ~40% товарів) |

---

## 2. Інфраструктура

```
┌─────────────────────────────────────────────────────┐
│  НОУТБУК  100.126.131.55                            │
│  RTX 4050 6GB — Ollama, embedding_service.py        │
│  Запускає: katran_xml_generator.py (AVX)            │
└───────────────────┬─────────────────────────────────┘
                    │ Tailscale VPN
┌───────────────────▼─────────────────────────────────┐
│  СЕРВЕР   tek@100.82.24.112                         │
│  ├── PostgreSQL (Docker agent_postgres)             │
│  ├── Redis (черги завдань, embedding queue)         │
│  ├── Qdrant (векторна БД для /learn правил)         │
│  └── systemd --user сервіси:                        │
│      ├── rozetka-order-agent  (постійно)            │
│      ├── epicentr-order-agent (постійно)            │
│      ├── tg-dispatcher        (постійно)            │
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
docker exec -it agent_postgres psql -U agentadmin agentdb
```

---

## 3. Компоненти системи та їх взаємодія

```
Постачальник фід
  │
  ▼
[XML Generator] ──► data/*.xml ──► GitHub
                                      │
                              Розетка (raw URL, 1/год)
  │
  ▼
[Order Agent] ◄── Маркетплейс API (Розетка/Єпіцентр/Prom)
  │
  ├── підтверджує замовлення
  ├── формує Excel бланк
  ├── відправляє на email постачальника
  └── зберігає в БД → Telegram сповіщення
         │
         ▼
[TG Dispatcher] ◄── PDF накладної від Carvol
  │                              │
  ▼                              ▼
 /ttn команда          ttn_pdf_parser → np_api
                           │
                           ▼
                       rozetka_order_agent.set_ttn()
                           │
                       status 61 → status 3 → верифікація
```

---

## 4. Всі скрипти

### 4.1 agents/orders/ — Основні агенти замовлень

| Файл | Статус | Опис |
|---|---|---|
| `rozetka_order_agent.py` | ✅ v4 | Розетка: нові замовлення → confirm(2) → Excel → Carvol TG → set_ttn → ship(3) |
| `rozetka_github_sync.py` | ✅ cron 1/год | Оновлює ціни/наявність у `carvol_rozetka.xml` → git push |
| `katran_xml_generator.py` | ✅ готовий | Генерує `katran_rozetka.xml` з ZIP-фіду Катрана + маппінг з БД |
| `katran_github_sync.py` | ✅ готовий | Запускає katran_xml_generator → git push (щогодинна синхронізація) |
| `epicentr_order_agent.py` | ✅ активний | Єпіцентр: нові замовлення TOPTUL → confirm → Excel → email opt@grandinstrument.ua |
| `epicentr_xml_generator.py` | ✅ | Генерує XML фід для Єпіцентру з TOPTUL |
| `ttn_pdf_parser.py` | ✅ | Парсить PDF накладних НП: ТТН (14 цифр), ім'я, місто, телефон |
| `np_api.py` | ✅ | Nova Poshta API: `get_ttn_info()`, `match_order_by_np_data()` |
| `price_engine.py` | ✅ | Двигун ціноутворення: TOPTUL РРЦ → ціна Prom з урахуванням CPA |
| `price_updater.py` | ✅ cron 8:00 | Щоденне оновлення цін через price_engine |
| `price_audit.py` | ✅ | Аудит цін: порівняння з конкурентами, алерти |
| `feed_sync.py` | ✅ cron /4год | Синхронізація фіду Prom (наявність, без ціни) |
| `rozetka_feed_sync.py` | ✅ | Синхронізація фіду Розетки в реальному часі через API |
| `order_agent.py` | ✅ | Агент замовлень Prom.ua |
| `order_agent_daemon.py` | ✅ systemd | Daemon Prom: кожні 5 хв перевіряє нові замовлення |
| `fetch_prom_categories.py` | ✅ | Завантажує категорії Prom в БД |

### 4.2 agents/scraper/ — Скрапери і генератори

| Файл | Статус | Опис |
|---|---|---|
| `generate_carvol_xml.py` | ✅ | Початкова генерація carvol_rozetka.xml (разовий) |
| `xml_generator.py` | ✅ | Загальний генератор XML для Розетки |
| `category_classifier.py` | ✅ | AI класифікація категорій (Ollama/Claude) |
| `import_carvol.py` | ✅ | Імпорт Carvol товарів у carvol_products |
| `import_supplier_feed.py` | ✅ | Імпорт фіду постачальника в my_products |
| `import_from_prom.py` | ✅ | Імпорт з Prom API |
| `import_from_prom_xml.py` | ✅ | Імпорт з Prom XML фіду |
| `market_price_analyzer.py` | ✅ | Аналіз цін конкурентів |
| `rozetka_card_agent.py` | ✅ | Робота з картками товарів Розетки |
| `epicentr_cabinet.py` | ✅ | Playwright: кабінет Єпіцентру |
| `carvol_category_map.py` | ✅ | Маппінг категорій Carvol |
| `run_night_processing.py` | ✅ | Нічний пакетний запуск |
| `playwright_base.py` | ✅ | Базовий клас для Playwright скраперів |
| `find_url.py` | 🔄 | Пошук URL товарів |
| `debug_page.py` | 🔄 | Дебаг Playwright сторінок |
| `generate_params_from_name.py` | 🔄 | Генерація характеристик з назви |
| `scraper_agent.py` | ✅ | Загальний агент скрапінгу |

### 4.3 agents/ — Доменні агенти

| Файл | Опис |
|---|---|
| `checker/acceptance_checker.py` | Перевірка прийнятності замовлень |
| `dev/dev_agent.py` | Агент для розробки/налагодження |
| `efficiency/efficiency_agent.py` | Аналіз ефективності продажів |
| `finance/finance_agent.py` | Фінансова звітність, P&L |
| `marketing/card_optimizer.py` | Оптимізація карток товарів (SEO) |
| `marketing/marketing_agent.py` | Маркетинговий агент |
| `interfaces/instruction_parser.py` | Парсинг інструкцій вільним текстом |
| `interfaces/telegram_gateway.py` | Шлюз Telegram → агент |

### 4.4 tg_dispatcher/ — Telegram бот

| Файл | Опис |
|---|---|
| `main.py` | Головний Telegram бот (aiogram 3.x): /start, /status, /prices, /orders, /learn, /ttn, голосові, PDF |
| `ai_brain/voice_handler.py` | faster-whisper: голос → текст |

**Безпека (security_middleware):**
- `ADMIN_ID` — повний доступ до всіх команд
- `CARVOL_TG_CHAT_ID` — тільки document (PDF накладні)
- Всі решта — мовчки відхиляються

### 4.5 shared/ — Спільні утиліти

| Файл | Опис |
|---|---|
| `utils/db.py` | Підключення до PostgreSQL |
| `utils/pricing.py` | `calc_price()`, `get_prom_cpa()` |
| `utils/redis_queue.py` | Черга завдань Redis |
| `utils/memory.py` | Пам'ять агентів (Qdrant) |
| `utils/model_selector.py` | Вибір LLM (Ollama/Claude) |
| `utils/ollama_worker.py` | Worker для Ollama на ноутбуці |
| `utils/skill_loader.py` | Завантаження skills |
| `mcp_servers/rozetka_mcp.py` | MCP сервер Розетки |
| `mcp_servers/epicentr_mcp.py` | MCP сервер Єпіцентру |
| `mcp_servers/prom_mcp.py` | MCP сервер Prom |
| `mcp_servers/browser_mcp.py` | MCP браузерний агент |
| `mcp_servers/agent_mcp_server.py` | Загальний MCP агент |

### 4.6 tools/ — Утилітні скрипти

| Файл | Опис |
|---|---|
| `epicentr_category_mapper.py` | Маппінг категорій Єпіцентру |
| `epicentr_confirm_categories.py` | Підтвердження категорій Єпіцентру |
| `fix_rozetka_xml.py` | Виправлення XML для Розетки |
| `competitor_scraper.py` | Скрапінг цін конкурентів |
| `prom_seo_optimizer.py` | SEO оптимізація Prom |
| `prom_feed_converter/scripts/` | Конвертація фідів Prom |

### 4.7 Кореневі файли

| Файл | Опис |
|---|---|
| `embedding_service.py` | **Ноутбук**: генерація embeddings через Redis queue (sentence-transformers, RTX 4050) |
| `orchestrator/orchestrator.py` | LangGraph оркестратор агентів |
| `orchestrator/telegram_bot.py` | Старий TG бот (замінено tg_dispatcher) |
| `dashboard/api.py` | REST API дашборду |
| `cli.py` | CLI інтерфейс |
| `enrich_agent.py` / `enrich_with_ai.py` | Збагачення карток товарів через AI |
| `mass_enrich.py` | Масове збагачення |
| `ingest_prices.py` | Завантаження цін у БД |
| `update_db_schema.py` | Міграція схеми БД |

---

## 5. База даних (PostgreSQL, 31 таблиця)

### Товари
| Таблиця | Записів | Опис |
|---|---|---|
| `my_products` | ~5 908 | TOPTUL товари: sku, name_uk, price_supplier, price_our, availability, prom_id, epicentr_category_id, attributes (JSONB) |
| `carvol_products` | ~8 304 | Carvol товари автоелектроніки |
| `scraped_products` | - | Товари зі скрапінгу конкурентів |

### Замовлення
| Таблиця | Опис |
|---|---|
| `orders` | Prom замовлення: prom_order_id, status, customer_name/phone, delivery, items (JSONB), ttn |
| `rozetka_processed_orders` | Розетка: order_id, status, phone, recipient, city, ttn |
| `epicentr_processed_orders` | Єпіцентр: оброблені замовлення |

### Категорії та маппінги
| Таблиця | Опис |
|---|---|
| `katran_categories` | 5 124 категорії Катрана: id, parent_id, name, rozetka_category, rozetka_rz_id, commission_pct, product_count |
| `epicentr_categories` | 4 054 категорії Єпіцентру |
| `rozetka_categories` | 37 категорій Розетки |
| `prom_categories` | Категорії Prom |
| `supplier_category_mapping` | 384 маппінги постачальник→маркетплейс |
| `toptul_epicentr_category_map` | Маппінг TOPTUL→Єпіцентр |
| `rozetka_category_mapping` | Деталізований маппінг для Розетки |
| `epicentr_sku_mapping` | Маппінг SKU для Єпіцентру |

### Ціни та комісії
| Таблиця | Опис |
|---|---|
| `price_history` | Історія змін цін |
| `price_engine_config` | Налаштування price_engine |
| `market_prices` | Ціни конкурентів (моніторинг) |
| `competitor_prices` | Ціни конкурентів (scraped) |
| `prom_cpa_rates` | 68 категорій Prom з % комісії |
| `epicentr_cpa_rates` | 236 категорій Єпіцентру з % комісії |
| `rozetka_cpa_rates` | 16 категорій Розетки з діапазонами |

### Атрибути / правила
| Таблиця | Опис |
|---|---|
| `epicentr_attributes` | Характеристики для Єпіцентру |
| `epicentr_rules` | Правила обробки Єпіцентру |

### Система та логи
| Таблиця | Опис |
|---|---|
| `agents` | Реєстр агентів |
| `tasks` | Завдання агентів |
| `alerts` | Алерти системи |
| `event_logs` | Лог подій |
| `skill_updates` | Оновлення skills агентів |
| `browser_sessions` | Playwright сесії |
| `browser_action_log` | Лог дій браузера |
| `prom_feed_validator_log` | Лог валідації фідів Prom |

---

## 6. Cron-розклад (сервер)

```
┌─────────────────────────────────────────────────────────────────┐
│ 0 8 * * *    price_updater.py         — оновлення цін (08:00)  │
│ 0 */4 * * *  feed_sync.py             — синхронізація Prom (4/год) │
│ 0 * * * *    rozetka_github_sync.py   — ціни Carvol XML (1/год) │
│ (planned)    katran_github_sync.py    — ціни Катран XML (1/год) │
└─────────────────────────────────────────────────────────────────┘
```

**Systemd --user сервіси (постійно):**
- `rozetka-order-agent` — обробка замовлень Розетки
- `epicentr-order-agent` — обробка замовлень Єпіцентру
- `tg-dispatcher` — Telegram бот
- `feed-server` — HTTP сервер фідів

---

## 7. Стан розробки

### ✅ Готово і працює
- Автоматична обробка замовлень Розетки (Carvol): new → confirm → Excel → Telegram
- Автоматична обробка замовлень Єпіцентру (TOPTUL): new → confirm → Excel → email
- Автоматичне встановлення ТТН: PDF від Carvol → parse → match → set_ttn → status 61 → ship
- Carvol XML генерація та щогодинна синхронізація через GitHub
- Катран XML генератор (`katran_xml_generator.py` + `katran_github_sync.py`)
- Ціновий двигун TOPTUL → Prom (щоденно)
- Синхронізація фіду Prom (кожні 4 год)
- Telegram бот: команди, голос (Whisper), PDF обробка, безпека
- 31 таблиця БД з повною схемою
- Маппінг 1449 категорій Катрана (27 батьківських, пропагація на дочірні, ~40% товарів)
- MCP сервери (Розетка, Єпіцентр, Prom, browser, filesystem)

### 🔄 В процесі
- Катран: маппінг решти ~60% категорій (потрібна перевірка rz_id в PriceCreator)
- Налаштування другого GitHub посилання для Катрана в кабінеті Розетки

### ❌ Заплановано
- `katran_order_agent.py` — агент замовлень Катрана
- Виправлення Молотки/Біти/Набори пневмо/Мультиметри для Єпіцентру
- Перевірка XML katran_rozetka.xml через валідатор Розетки
- Поповнити баланс Prom (~325 грн залишилось)

---

## 8. Відомі проблеми

| Проблема | Деталі |
|---|---|
| AVX на сервері | sentence-transformers дає exit 132. Embeddings тільки на ноутбуці через Redis queue |
| SSL Розетка | `verify=False` обов'язково — старий сервер Celeron з протухлим сертифікатом |
| Статичний токен Розетки | `gapi_...` — треба активність раз на добу |
| Carvol XML ще не активований | Відправлено Розетці, очікується активація |
| ~60% товарів Катрана без категорій | rz_id невідомі для ~14 батьківських категорій |

---

## 9. Змінні середовища (.env)

| Змінна | Призначення |
|---|---|
| `ROZETKA_API_TOKEN` | Bearer токен Розетки |
| `EPICENTR_TOKEN` | Bearer токен Єпіцентру |
| `PROM_API_TOKEN` | Токен Prom.ua |
| `KATRAN_FEED_URL_STOCK` | URL ZIP-архіву фіду Катрана |
| `NP_API_KEY` | Nova Poshta API ключ |
| `CARVOL_TG_CHAT_ID` | Telegram Chat ID Carvol (8035052611) |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram бота |
| `TELEGRAM_ADMIN_ID` | ID адміна (6762672351) |
| `SMTP_USER/PASS/HOST/PORT` | Gmail SMTP |
| `DATABASE_URL` | PostgreSQL підключення |
| `REDIS_URL` | Redis підключення |

---

## 10. Контакти

| Роль | Контакт |
|---|---|
| Розетка (менеджер) | Софія Івановська ivanovskaya@rozetka.ua |
| TOPTUL / Гранд Інструмент | rusanov@grandinstrument.ua, opt@grandinstrument.ua |
| Carvol (Email) | carvolua@gmail.com |
| Carvol (Telegram) | +380971574150, Chat ID: 8035052611 |
| Катран (менеджер) | Сергій Голубцов srgolubtsov@katran.vn.ua +380632822022 |
| Єпіцентр | e.tambovskiy@epicentrk.ua |

---

## 11. TODO (наступні сесії)

1. **Катран категорії** — підтвердити rz_id через PriceCreator:
   `seller.rozetka.com.ua/gomer/pricevalidate/check/index`
   Кандидати: Кабелі(80329), USB(80333), Картриджі(80296), Корпуси ПК(80038),
   Кулери(80049), Чорнила(73126), Чохли(4638562), Плівки(4638563),
   LED(4638153), Світильники(4638228), ЗП мобільні(4638593), USB Hub(80339)

2. **Валідатор XML** Катрана — перевірити katran_rozetka.xml через Розетку

3. **GitHub посилання** — налаштувати друге посилання для Катрана в кабінеті Розетки (через Софію)

4. **Cron katran_github_sync** — додати на сервері:
   ```
   0 * * * * /home/tek/agent-system/venv/bin/python3 /home/tek/agent-system/agents/orders/katran_github_sync.py >> /tmp/katran_sync_cron.log 2>&1
   ```

5. **katran_order_agent.py** — агент замовлень Катрана (аналог rozetka_order_agent)
