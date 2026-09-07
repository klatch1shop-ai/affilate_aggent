# SYSTEM.md — Dropshipping Agent System

> Репозиторій: `github.com/klatch1shop-ai/affilate_aggent` (гілка `main`)
> Призначення: автоматизація дропшипінгу на маркетплейсах України (Prom.ua, Rozetka, Єпіцентр; Khoroshop — у планах).
> Робочий формат розробки: **VS Code + Claude Code CLI, окремий термінал-чат на кожен напрямок/маркетплейс**, координація через файли репо (`TASKS.md`, `CLAUDE.md`).
> Документ описує реальний стан коду на дату внизу. Де доки в репо суперечать одна одній — це позначено явно.

---

## 0. Дві підсистеми в одному репо (читати першим)

У репозиторії фізично співіснують **два різні шари**, які легко сплутати:

| Шар | Що це | Файли / запуск | Статус |
|-----|-------|----------------|--------|
| **A. Операційний (реальний бізнес)** | Order-агенти маркетплейсів, XML-генератори, Telegram-диспетчер, cron | `agents/orders/*`, `tools/*`, `tg_dispatcher/*` + systemd/cron | ✅ працює, приносить замовлення |
| **B. Generic multiagent (каркас)** | Оркестратор + 5 LLM-агентів (marketing/finance/efficiency/dev/checker) на Ollama+Redis+Qdrant | `orchestrator/*`, `agents/{marketing,finance,efficiency,dev,checker}/*`, `start_all.sh` | 🟡 каркас, у щоденному обороті майже не використовується |

**Агенти-чати Claude Code (нижче, розділ 1) керують ШАРОМ A.** README.md описує переважно шар B і тому вводить в оману — справжня робота йде через order-агенти і генератори. Це найголовніше джерело плутанини в проєкті.

---

## 1. АГЕНТИ-ЧАТИ (VS Code + Claude Code)

Усі агенти стартують з **кореня одного репо** `affilate_aggent` (моно-репо, не кілька директорій). Кастомних конфігів `.claude/agents/*.md` у репо **немає** (перевірено) — тобто запускати `claude` без `--agent`, або створити конфіги за зразком нижче.

| Агент-чат | Робоча дир. | «Володіє» файлами | Daemon на сервері | Зовнішні сторони |
|-----------|-------------|-------------------|-------------------|------------------|
| **epicentr-agent** | корінь репо | `tools/carvol_epicentr_generator.py`, `epicentr_postprocess.py`, `tools/epicentr_xml_checker.py`, `tools/epicentr_quality_checker.py`, `tools/epicentr_pim_explorer.py`, `tools/epicentr_attrs_explorer.py`, `tools/epicentr_category_mapper.py`, `tools/epicentr_confirm_categories.py`, `tools/epicentr_fill_attributes.py`, `agents/orders/epicentr_order_agent.py`, `agents/orders/epicentr_xml_generator.py`, `agents/orders/carvol_epicentr_sync.py`, `agents/orders/feed_sync.py`, `agents/scraper/epicentr_cabinet.py`, `shared/knowledge_base/epicentr/`, `shared/mcp_servers/epicentr_mcp.py` | `epicentr-order-agent` | Менеджер Єпіцентру Євгеній Тамбовський `e.tambovskiy@epicentrk.ua`; постачальники TOPTUL і Carvol (через TG) |
| **rozetka-agent** | корінь репо | `agents/orders/rozetka_order_agent.py`, `rozetka_github_sync.py`, `rozetka_feed_sync.py`, `rozetka_price_manager.py`, `rozetka_price_corrector.py`, `ttn_pdf_parser.py`, `np_api.py`, `tools/fix_rozetka_xml.py`, `tools/rozetka_xml_validator.py`, `agents/scraper/rozetka_card_agent.py`, `shared/knowledge_base/rozetka/`, `shared/mcp_servers/rozetka_mcp.py` | `rozetka-order-agent`, `tg-dispatcher` | Постачальник Carvol (TG chat `8035052611`); менеджер Розетки Софія Івановська `ivanovskaya@rozetka.ua`; Nova Poshta API |
| **prom-agent** | корінь репо | `tools/prom_xml_generator.py`, `tools/prom_validator.py`, `tools/prom_seo_optimizer.py`, `tools/prom_tecdoc_splitter.py`, `tools/prom_feed_converter/`, `agents/orders/order_agent.py`, `order_agent_daemon.py`, `price_engine.py`, `price_updater.py`, `price_audit.py`, `fetch_prom_categories.py`, `agents/scraper/import_from_prom*.py`, `shared/knowledge_base/prom/`, `shared/mcp_servers/prom_mcp.py` | `order_agent_daemon` (Prom) | Клієнт Віктор (каталог auto-parts); постачальник TOPTUL/Гранд Інструмент (`rusanov@grandinstrument.ua`, `opt@grandinstrument.ua`, код клієнта `000160594`) |
| **katran** (під-напрям rozetka, новий постач.) | корінь репо, **запуск на ноутбуці** (потрібен AVX) | `agents/orders/katran_xml_generator.py`, `katran_github_sync.py`, `tools/katran_category_xml.py`, `tools/katran_pipeline.py` | — (cron на сервері планується) | Катран `katran.vn.ua/b2b`, менеджер Сергій Голубцов `srgolubtsov@katran.vn.ua`, +380632822022 |
| **khoroshop-agent** | корінь репо | **немає коду** (див. розділ 5а) | — | Постачальник «Секс Опт» (інтимні товари) |
| **orchestrator** (опц.) | корінь репо | `orchestrator/orchestrator.py`, `telegram_bot.py`, `shared/utils/*`, `cli.py`, `tools/watchdog.py`, `tools/web_api_explorer.py`, `tools/ai_xml_generator.py`, `TASKS.md`, git | shar B-агенти (`start_all.sh`) | — координує напрямки, веде git, daemon-нагляд |

**Спільне для всіх чатів:** БД `agentdb`, файл `.env`, `shared/utils/` (`db.py`, `pricing.py`, `redis_queue.py`), `CLAUDE.md`, `TASKS.md`, git-репо. **Специфічне** — генератори/чекери та knowledge_base кожного маркетплейсу.

### 1.1 Конфігурація VS Code
1. Відкрити VS Code у корені репо `affilate_aggent`.
2. Відкрити окремі термінали: epicentr / rozetka / prom / (katran) / orchestrator.
3. У кожному запустити `claude` (кастомних `.claude/agents/*.md` немає → без `--agent`).
4. Перша команда в кожному терміналі:
   ```
   Прочитай CLAUDE.md і TASKS.md (свій розділ). Потім чекай задачі. Перед будь-яким commit роби git pull --rebase.
   ```
5. **Рекомендація:** створити `.claude/agents/<name>.md` по одному на напрямок (allowed tools + правила з `docs/AGENT_RULES.md`), щоб обмежити кожен чат його файлами.

---

## 2. ІНФРАСТРУКТУРА І DAEMON-ПРОЦЕСИ

### 2.1 Машини
| Роль | Адреса (Tailscale) | Що крутить |
|------|--------------------|------------|
| Сервер | `tek@100.82.24.112` | PostgreSQL/Redis/Qdrant (Docker), всі order-агенти, tg-dispatcher, cron |
| Ноутбук | `100.126.131.55` | RTX 4050 → Ollama, `embedding_service.py`, `katran_xml_generator.py` (AVX) |

> ⚠️ Розбіжність у доках: `MASTER_CONTEXT.md` вказує LAN `192.168.3.28`/`192.168.3.24` — це застарілі адреси. Актуальні — Tailscale вище (як у `CLAUDE.md` і `FULL_ARCHITECTURE.md`). Шлях на сервері: `/home/tek/agent-system`.

### 2.2 Підключення
```bash
ssh tek@100.82.24.112
cd /home/tek/agent-system && source venv/bin/activate
docker exec -it agent_postgres psql -U agentadmin agentdb     # НЕ -U agent
```

### 2.3 Docker-сервіси (`docker-compose.yml`)
`agent_postgres` (postgres:16-alpine), `agent_redis` (redis:7), `agent_qdrant`, `agent_n8n`, `agent_prometheus`, `agent_grafana`, `agent_adminer`, `agent_redis_ui`.
Веб-інтерфейси: Dashboard `:8888`, Adminer `:8080`, n8n `:5678`, Grafana `:3000`, web_api_explorer `:5555`.

### 2.4 Постійні daemon-процеси (прив'язка до агента-чату)
| Процес | Агент-чат | Роль | Запуск (реальний стан) | Лог |
|--------|-----------|------|------------------------|-----|
| `agents/orders/rozetka_order_agent.py` | rozetka | poll нових замовлень кожні 300 с, confirm→Excel→TG Carvol | systemd `--user` `rozetka-order-agent` АБО `nohup` (мікс) | `logs/` / `/tmp` |
| `tg_dispatcher/main.py` | rozetka | aiogram 3.x polling: приймає PDF ТТН від Carvol, ставить ТТН | systemd `tg-dispatcher` / nohup | — |
| `agents/orders/epicentr_order_agent.py` | epicentr | poll замовлень Єпіцентру кожні 5 хв | systemd `epicentr-order-agent` | — |
| `agents/orders/order_agent_daemon.py` | prom | нескінченний цикл замовлень Prom | systemd | `logs/...` |
| feed-server | orchestrator | HTTP-роздача фідів | systemd `feed-server` | — |

> ⚠️ **Жоден надійний watchdog/systemd для критичних процесів зараз не налаштований** (задача ще відкрита в `TASKS.md`). На практиці процеси стартують через `nohup`, а `start_all.sh` піднімає шар B. Звідси інцидент із зомбі-ботом (розділ 9).

**Міжагентна залежність:** `tg_dispatcher/main.py` напряму `import`-ить функції з `agents/orders/rozetka_order_agent.py` (`set_ttn`, `change_status`) і з `np_api.py`, `ttn_pdf_parser.py`. Тобто rozetka-agent і tg-dispatcher не можна розглядати ізольовано.

### 2.5 Crontab (сервер)
```
0 * * * *    agents/orders/rozetka_github_sync.py     # Carvol XML → GitHub, щогодини
0 7 * * *    agents/orders/feed_sync.py               # синхр. Єпіцентр, щодня 07:00
0 8 * * *    agents/orders/price_updater.py           # ціни Prom, щодня 08:00
*/10 * * * * tools/watchdog.py                         # health + локальний авто-commit (БЕЗ push)
# планується:
0 * * * *    agents/orders/katran_github_sync.py      # Катран XML → GitHub
```
> ⚠️ Розбіжність: `docs/AGENT_RULES.md` вказує `feed_sync.py` як `0 */4`, а `CLAUDE.md`/`TASKS.md` — `0 7`. Актуальний — `0 7` (змінено навмисно).

---

## 3. ПОТОКИ ДАНИХ (реальні)

**Pipeline A — Carvol → Розетка (активний):**
```
Carvol Prom-feed (live) → rozetka_github_sync.py (1/год: оновлює лише <price>/<stock_quantity>/available)
  → git push → data/carvol_rozetka.xml → GitHub raw URL → Розетка тягне 1/год
Нове замовлення: rozetka_order_agent.py (poll 5хв) → confirm(status 2) → Excel(xlsxwriter)
  → Telegram Carvol(8035052611) → save_to_db('accepted')→rozetka_processed_orders
Carvol → PDF накладної НП → Telegram → tg_dispatcher/main.py:handle_document
  → ttn_pdf_parser.parse_ttn_pdf → np_api.get_ttn_info + match_order_by_np_data
  → set_ttn() → status 61 (auto) → change_status(3) → верифікація GET через 2с (ALARM якщо нема ТТН)
```

**Pipeline B — TOPTUL → Єпіцентр (XML, ручне завантаження):**
```
carvol_epicentr_generator.py → exports/carvol_epicentr_new.xml
  → epicentr_postprocess.py (фото-фільтр 8171→7081, дедуп→7075, 2883→2848, trim назв) → exports/carvol_epicentr.xml
  → (scp на ноут) → epicentr_xml_checker.py (exit 0 = OK / 1 = помилки)
  → ручне завантаження в merchant.epicentrk.ua → модерація менеджером
Замовлення: epicentr_order_agent.py (poll) → перевірка TOPTUL фіду → confirm → Excel → opt@grandinstrument.ua
```

**Pipeline C — Катран → Розетка (в процесі, ~40% товарів):**
```
KATRAN_FEED_URL_STOCK (ZIP→XML, формат <price><products><product>, НЕ yml_catalog!)
  → katran_xml_generator.py (на ноутбуці) → маппінг katran_categories → calc_price → data/katran_rozetka.xml
  → katran_github_sync.py → GitHub raw URL → Розетка (друге посилання в кабінеті — через менеджера)
```

**Pipeline D — TOPTUL → Prom (активний):** `price_updater.py`→`price_engine.py` (щодня 08:00) рахує ціни; `feed_sync.py` синхр. наявність; замовлення — `order_agent_daemon.py`.

---

## 4. ІНСТРУМЕНТИ ГЕНЕРАЦІЇ/ПЕРЕВІРКИ (`tools/` + `agents/orders/`)

| Файл | Чат | Що робить | Вхід → Вихід | Коли |
|------|-----|-----------|--------------|------|
| `tools/carvol_epicentr_generator.py` | epicentr | прайс Carvol (SpreadsheetML) → Єпіцентр XML, маппінг 5 категорій (`8743/3729/2821/2848/2866`; 4907 злито в 2866 — див. розділ 9 п.19), детект 394 марок авто (attr 4866) | `data/carvol_opt.xml` → `exports/carvol_epicentr_new.xml` | вручну на сервері |
| `epicentr_postprocess.py` (корінь) | epicentr | фото-фільтр + дедуп + 2883→2848 + обрізка назв | `_new.xml` → `exports/carvol_epicentr.xml` | вручну, після генератора |
| `tools/epicentr_xml_checker.py` | epicentr | повна валідація перед імпортом (структура/дублі/params/фото) | XML → exit 0/1 | вручну на ноуті |
| `tools/epicentr_quality_checker.py` | epicentr | SEO-скоринг (avg 73/100), `--enhance-names`, `--fix` | XML → звіт/виправлений XML | вручну |
| `tools/epicentr_pim_explorer.py` | epicentr | PIM API: бренди/країни/категорії (кеш 54370 брендів) | API → БД | вручну |
| `tools/epicentr_category_mapper.py` | epicentr | fuzzy-match категорій TOPTUL → Єпіцентр | XML+БД → маппінг | вручну |
| `tools/epicentr_fill_attributes.py` | epicentr | заповнює порожні `*` колонки xlsx-експорту | xlsx → xlsx | вручну |
| `agents/orders/carvol_epicentr_sync.py` | epicentr | оновлює лише ціни/наявність в `exports/carvol_epicentr.xml` з live-фіду | feed → XML | авто/вручну |
| `tools/prom_xml_generator.py` | prom | XLSX каталог Віктора → Prom XML (`--no-filter`) | `catalog.xlsx` → `exports/prom_*.xml` | вручну |
| `tools/prom_validator.py` | prom | валідація Prom XML/XLSX | XML → звіт | вручну |
| `tools/prom_tecdoc_splitter.py` / `prom_seo_optimizer.py` | prom | розподіл tecdoc/manual; SEO-аудит | xlsx → звіт | вручну |
| `tools/prom_feed_converter/` | prom | `analyze_feed.py`, `category_mapper.py`, `validator.py` | фід → аналіз | вручну |
| `agents/orders/katran_xml_generator.py` | katran | фід Катрана → Розетка XML, `calc_price` | ZIP → `data/katran_rozetka.xml` | ноутбук |
| `tools/katran_category_xml.py` | katran | XML по конкретних rz_id, 3 проходи + фільтри уцінок/б.в. | feed → XML | вручну |
| `tools/katran_pipeline.py` | katran | повний цикл generate→validate→merge→(push) | → `data/katran_rozetka.xml` | вручну |
| `tools/rozetka_xml_validator.py` | rozetka | універсальний валідатор YML-XML (ERR/WARN, json+xlsx звіт) | XML → звіти | вручну |
| `tools/fix_rozetka_xml.py` | rozetka | виправляє price.xml під вимоги Розетки | XML → XML | вручну |
| `tools/web_api_explorer.py` | orchestrator (спільне) | Flask веб-UI тесту API маркетплейсів (`:5555`) | — | daemon/вручну |
| `tools/ai_xml_generator.py` | orchestrator (спільне) | AI-генератор XML для будь-якого маркетплейсу/категорії | — | вручну |
| `tools/watchdog.py` | orchestrator | health + **локальний** git commit (НІКОЛИ push) | — | cron */10 |
| `tools/supplier_onboarding.py` | orchestrator | wizard підключення нового постачальника (`--resume`) | — | вручну |
| `tools/competitor_scraper.py` | (спільне) | парсинг товарів продавця на Rozetka | — | вручну |

> ⚠️ **Дубль:** `epicentr_postprocess.py` існує і в корені, і в `tools/`. У пайплайні (`CLAUDE.md`/`TASKS.md`) використовується **кореневий**. Версія в `tools/` — застаріла, не запускати.
> ⚠️ `.bak`/`.bak2` файли (`rozetka_order_agent.py.bak`, `.bak2`, `ttn_pdf_parser.py.bak`, `tg_dispatcher/main.py.bak`/`.bak2`, `tools/carvol_epicentr_generator.py.bak`) — резервні копії, **не актуальні**. Актуальна — версія без суфікса.

---

## 5. БАЗА ДАНИХ (PostgreSQL `agentdb`, ~40 таблиць)

Таблиці зі схеми/міграцій репо (`infrastructure/init.sql`, `migrate_*.sql`, `update_db_schema.py`) + згадані в доках. Частина таблиць існує лише в живій БД (не в DDL репо).

| Таблиця | Чат | Призначення |
|---------|-----|-------------|
| `agents`, `tasks`, `event_logs`, `alerts` | orchestrator | каркас шару B (init.sql) |
| `products`, `my_products` | prom | товари TOPTUL з цінами (~5908) |
| `carvol_products` | rozetka/epicentr | товари Carvol (~8304) |
| `orders` | prom | замовлення Prom |
| `rozetka_processed_orders` | rozetka | оброблені замовлення (phone/recipient/city для TTN-матчингу) |
| `price_history`, `price_engine_config` | prom | історія/конфіг цін |
| `prom_cpa_rates` (68), `epicentr_cpa_rates` (236), `rozetka_cpa_rates` (16, з діапазонами) | по чатах | комісії маркетплейсів |
| `epicentr_categories` (~4054), `rozetka_categories` (37) | epicentr/rozetka | довідники категорій |
| **`carvol_epicentr_cat_map`** | epicentr | маппінг категорій Carvol→Єпіцентр |
| **`epicentr_required_attrs`**, `epicentr_brand_cache` (54370), `epicentr_brand_map` (42), `epicentr_car_brands` (394), `epicentr_quality_log` (7081) | epicentr | атрибути/бренди/SEO — **критичні для генератора** |
| **`rozetka_category_mapping`**, `katran_categories` (~5124, rz_id) | rozetka/katran | маппінг категорій — критичні |
| **`toptul_epicentr_category_map`** | epicentr | маппінг TOPTUL→Єпіцентр |
| `supplier_category_mapping` (384) | спільна | узагальнений маппінг постачальник→категорія |
| `marketplace_api_methods` (123), `api_test_log` | orchestrator | реєстр API + лог тестів |
| `competitor_prices`, `market_prices`, `browser_sessions`, `browser_action_log`, `skill_updates`, `epicentr_sku_mapping` | scraper/спільні | конкуренти/браузер/скіли |

**Маппінг-таблиці критичні**, бо генератори без них кладуть товар у DEFAULT-категорію (Розетка) або «Інше»-бренд (Єпіцентр) → втрата видимості/модерація. Окремої таблиці під Khoroshop/«Секс Опт» **немає** — `supplier_category_mapping` можна перевикористати як основу.

### 5а. Khoroshop — статус нового напряму (НЕ РЕАЛІЗОВАНО)
- Пошук по репо за `khoroshop|хорошоп|секс опт|sexopt|інтим` → **жодного файлу коду.** Єдина згадка — placeholder-текст «інтимні товари» в UI `tools/ai_xml_generator.py:246`.
- Формат фіду постачальника «Секс Опт» **невідомий** → потребує дослідження (XML/YML/API?).
- **Шаблон для перенесення** (з наявних паттернів): `generator.py → postprocess.py → xml_checker.py → upload`, або фід через GitHub raw URL (як Carvol/Катран для Розетки).
- **MVP-план:** перевикористати `.env`-структуру, БД `agentdb`, git-workflow; додати `khoroshop_categories` + рядки в `supplier_category_mapping`; написати `tools/khoroshop_xml_generator.py` за зразком katran.
- **Рекомендація:** створити `.claude/agents/khoroshop-agent.md` і `shared/knowledge_base/khoroshop/` (навіть мінімально) за зразком `epicentr/`.

---

## 6. ДОКУМЕНТАЦІЯ — що читати на старті сесії
| Файл | Навіщо |
|------|--------|
| `CLAUDE.md` | головні правила, інфра, API, формули, валідні valuecodes, категорії |
| `TASKS.md` | живий список задач (читати ПЕРШИМ разом з CLAUDE.md) |
| `docs/AGENT_RULES.md` | що ЗАБОРОНЕНО без дозволу (агенти/cron/systemd/.env/БД) |
| `docs/FULL_ARCHITECTURE.md` | пофункційний розбір кожного файлу |
| `docs/PIPELINE.md` | покрокові пайплайни A–E + API endpoints |
| `shared/knowledge_base/{rozetka,epicentr,prom}/` | офіційні вимоги маркетплейсів, API-довідники |
| `data/carvol_rozetka.xml` | еталон XML-формату Розетки |

---

## 7. СЛУЖБОВІ БЛОКИ / КООРДИНАЦІЯ
Формального протоколу передачі блоків (TASK/SUMMARY/VERDICT) між агентами **немає** — це не multi-agent Claude Code сесії з обміном, а керування одним CLI-чатом + сервером. Координація:
- **`TASKS.md`** — єдине джерело правди про задачі (оператор оновлює вручну).
- Прямі команди оператора в Claude Code сесії кожного напрямку.
- Перевірка логів вручну (`logs/*.log`, `/tmp/*.log`) + `status.sh`.
- Передача стану між сесіями — `context_transfer.md`, `MASTER_CONTEXT.md`.

---

## 8. РОЗГОРТАННЯ З НУЛЯ

### 8.1 Ноутбук (розробка)
```bash
git clone https://github.com/klatch1shop-ai/affilate_aggent.git
cd affilate_aggent
ssh tek@100.82.24.112 "echo ok"          # перевірити Tailscale-доступ
# .env (значення не комітити). Реальний перелік ключів:
grep -rhoE "os\.getenv\(['\"][A-Z_]+" . --include=*.py | grep -oE "[A-Z_]{3,}" | sort -u
```
**ENV-змінні (без значень):** `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD`, `REDIS_HOST/REDIS_PORT`, `QDRANT_HOST/QDRANT_PORT`, `OLLAMA_BASE_URL/OLLAMA_URL/OLLAMA_MODEL*`, `ROZETKA_API_TOKEN/ROZETKA_LOGIN/ROZETKA_PASSWORD`, `EPICENTR_TOKEN/EPICENTR_API_URL/EPICENTR_LOGIN/EPICENTR_PASSWORD/EPICENTR_EMAIL`, `PROM_API_TOKEN`, `TOPTUL_FEED_URL`, `KATRAN_FEED_URL_STOCK`, `NP_API_KEY`, `TELEGRAM_BOT_TOKEN/TELEGRAM_ADMIN_ID/CARVOL_TG_CHAT_ID`, `CARVOL_SUPPLIER_EMAIL/CARVOL_SUPPLIER_CODE`, `SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS`, `ANTHROPIC_API_KEY`.
Потім: відкрити VS Code в корені → термінали по напрямках → `claude` (розділ 1.1).

### 8.2 Сервер (daemon-процеси)
```bash
# передумови: Docker (agent_postgres/redis/qdrant), Python venv
cd /home/tek/agent-system && python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt          # psycopg2-binary, requests, openpyxl, python-dotenv,
                                          # loguru, fastapi, uvicorn, aiogram/python-telegram-bot,
                                          # pdfplumber, playwright, mcp, anthropic, langchain*
docker compose up -d
# запуск критичних процесів (реальний стан — nohup):
nohup venv/bin/python3 agents/orders/rozetka_order_agent.py > logs/rozetka.log 2>&1 &
nohup venv/bin/python3 agents/orders/epicentr_order_agent.py > logs/epicentr.log 2>&1 &
nohup venv/bin/python3 tg_dispatcher/main.py > logs/tg.log 2>&1 &
# crontab — див. розділ 2.5
```
**Перевірка живучості:**
```bash
ps aux | grep -E "rozetka_order_agent|epicentr_order_agent|tg_dispatcher" | grep -v grep
docker exec agent_postgres psql -U agentadmin agentdb -c "SELECT count(*) FROM rozetka_processed_orders;"
tail -f /tmp/watchdog.log
```

### 8.3 Перша дія в новій сесії кожного чату
1. `git pull && cat TASKS.md` (свій розділ) + `cat CLAUDE.md`.
2. `git log --oneline -5` — що змінилось.
3. Повідомлення першим: «Прочитав CLAUDE.md і TASKS.md, чекаю задачі; перед commit роблю `git pull --rebase`».

---

## 9. ТИПОВІ ГРАБЛІ (з реальної історії)

1. **Git push race condition** — серверний `watchdog.py` авто-комітить, конфліктує з ручними push з ноутбука. Правило: **завжди `git pull --rebase` ПЕРЕД будь-яким commit+push** (а не лише при помилці). При кількох чатах над одним репо — частіше.
2. **Зомбі Telegram-бота** — два екземпляри з одним токеном → `TelegramConflictError`, `getUpdates` блокується. Реальний інцидент: PID 452258 висів **17 днів** (з 8 черв.) → жоден PDF з ТТН не доходив. Правило: `pkill -f tg_dispatcher` перед новим запуском.
3. **Єпіцентр: категорію опублікованого товару НЕ змінити через XML-імпорт** — тільки видалення+перестворення або запит менеджеру на «Чернетки».
4. **Неузгодженість шляхів generator↔postprocess** — генератор пише `carvol_epicentr_new.xml`, postprocess читає його і пише `carvol_epicentr.xml`. Назви фіксовані — не плутати.
5. **PIM API: `filter[ids][]` не працює** (повертає весь каталог) — перебирати всі сторінки (бренди: 544 стор. × 100 = 54370).
6. **Сервер без AVX (Celeron)** — `sentence-transformers` падає (exit 132). Embeddings рахуються на ноутбуці через `embedding_service.py` + Redis-черга. Скрипти з `openpyxl`/важким ML — теж на ноутбуці.
7. **SSL Rozetka** — `verify=False` обов'язково на всіх запитах (старий сертифікат), + `urllib3.disable_warnings`.
8. **Rozetka base URL** — тільки `https://api-seller.rozetka.com.ua` (з дефісом; без дефіса → 404).
9. **`waiting_payment` застрягав назавжди** в `rozetka_order_agent.py` — виправлено.
10. **Великі XML роздувають `.git`** (carvol_epicentr.xml ~42MB, фіди ~40MB) — тримати в `.gitignore` все крім явно потрібних `data/*.xml`/`exports`.
11. **Кирилиця у назвах файлів git** (екранування `\320\276`) — уникати кирилічних імен у репо.
12. **Розбіжність шляхів у скриптах:** `start_all.sh` → `/home/tek/agent-system`, але `status.sh`/`stop_all.sh` → `/home/tekken/agent-system`. Через це `status.sh` може нічого не показувати (різні `logs/*.pid`). Привести до одного шляху.
13. **`.env` проблеми:** логін/пароль Розетки невірні (`hyper_store`/`Tovarka2025Rivne` → incorrect_username_password); `NP_API_KEY` порожній; `ANTHROPIC_API_KEY` — placeholder. Заповнити перед роботою.
14. **QIV не зареєстрований в Єпіцентрі** → 6110 товарів з vendor=«Інше» (`827b4a70220f11ea918e001e67ecc97b`); реєстрація бренду підніме SEO-score 73→~93.
15. **Катран ~55% категорій не замаповано** → 4101 товар у DEFAULT. Після UPDATE батьків запускати SQL-пропагацію (`DO $$ ... katran_categories ... $$`).
16. **ДВІ різні формули ціни в репо — і одна з них помилкова (перевірено по коду, не докстрінгу):**
    - `shared/utils/pricing.py:calc_price()` (Prom/Rozetka через обгортки) — докстрінг бреше: декларує `РРЦ/(1-комісія)`, а код виконує `raw_price = rrс_price * (1.0 + commission_rate)` (**mark-up**).
    - `tools/carvol_epicentr_generator.py:316` (Єпіцентр) — код `math.ceil(rrc / (1 - comm/100) / 10) * 10` (**gross-up**).
    - `agents/orders/katran_xml_generator.py` — `ceil(price_rrc*(1+comm/100)/10)*10` (**mark-up**, навмисно).
    - **Числовий приклад rrc=1000, comm=15%:** mark-up → 1150; gross-up → 1000/0.85=1176.47 → 1180. Маркетплейс бере 15% з ціни продажу: при 1150 на руки лишається 1150×0.85=977.5 (< 1000, недобір); при 1180 → 1003 (≈ РРЦ збережено). **Математично правильний для збереження маржі — gross-up.** Тобто Єпіцентр-генератор рахує правильно, а `pricing.py` (Prom/Rozetka) — недозаряджає. Перед масовим перерахунком звірити й привести `pricing.py` до gross-up (і виправити докстрінг).
17. **Khoroshop:** НЕ копіювати epicentr-pipeline 1:1 без перевірки формату фіду «Секс Опт» — спочатку дослідити їх API/YML.
18. **README вводить в оману** — описує шар B (generic agents). Реальний бізнес — шар A (order-агенти). Орієнтуватись на `CLAUDE.md`/`TASKS.md`/`docs/PIPELINE.md`.
19. **Категорія 4907 «Магнітоли» видалена (2026-06-22, коміт `42f19ac`)** — менеджер Єпіцентру підтвердив, що штатні і звичайні магнітоли йдуть в одну категорію `2866 «Автомагнітоли»` (міграція `5f54745`: 1232 штатні + 53 regular). При оновленні вже **опублікованих** товарів через імпорт виникає помилка **«Оновлення товарів недоступне»** — потрібно просити менеджера перенести картки в «Чернетки», тоді імпорт проходить.

---

## 10. КЛЮЧОВІ КОНСТАНТИ (швидкий довідник)

**Rozetka API:** статуси `new(types=4) → 2(confirm) → set_ttn → 61(auto) → 3(доставка)`; cancel `6`; `FORBIDDEN_STATUSES={40,49,6}`. TTN: `POST /orders/add-ttn {order_id,ttn,delivery_service_id:1}` (primary) → `PATCH /orders/{id}{ttn}` (fallback).
**Nova Poshta:** `POST api.novaposhta.ua/v2.0/json/ TrackingDocument/getStatusDocuments`; TTN-формат `XX XXXX XXXX XXXX` (14 цифр).
**Єпіцентр:** `atset_code == category_code`; категорії Carvol: `8743, 3729, 2821, 2848, 2866` (4907 «Магнітоли» видалено 2026-06-22 → злито в 2866 «Автомагнітоли»; 2883 LED-світло опрацьовується в postprocess); бренд «Інше» = `827b4a70220f11ea918e001e67ecc97b`.
**Telegram:** ADMIN_ID `6762672351`; Carvol chat `8035052611` (може слати лише document); бот `@agent_system_TEKKEN_bot`.
**Постачальники:** TOPTUL код клієнта `000160594`; Carvol TG `8035052611`, `carvolua@gmail.com`.

---

## 11. КОНТАКТИ ЄПІЦЕНТРУ (хронологія, без втрати інформації)

> ⚠️ Відповідальний з боку Єпіцентру з часом змінювався — це реальна ротація менеджерів, а не помилка. Жоден контакт не видалено; нижче — усі знайдені згадки з датами останньої появи в репо.

| Ім'я / роль | Email | Телефон | Остання згадка (джерело) |
|-------------|-------|---------|---------------------------|
| Євгеній Тамбовський (персональний менеджер) | `e.tambovskiy@epicentrk.ua` | — | `MASTER_CONTEXT.md`, `shared/knowledge_base/epicentr/index.md`, `docs/FULL_ARCHITECTURE.md` |
| Євгеній Тамбовський (автор шаблону `template (5).xml`) | `e.tambovskiy@epicentrk.ua` | — | `agents/orders/epicentr_xml_generator.py` (коміт 2026-05-24) |
| Менеджер Єпіцентру (ім'я не вказано) — підтвердив злиття 4907→2866 | — | — | git-коміт `42f19ac` (2026-06-22) |
| Загальна підтримка мерчантів | `merchant@epicentrk.ua` | — | `shared/knowledge_base/epicentr/merchant_api_swagger.yaml`, `epicentr_full_requirements.md` |
| (довідково) Реєстрація бренду QIV — через менеджера Єпіцентру | — | — | `TASKS.md` (2026-06-15) |

Кабінети: `merchant.epicentrk.ua` (мерчант), `admin.epicentrm.com.ua` (адмін/імпорт). Тариф: ~120 грн/міс (`MASTER_CONTEXT.md`).

---

_Версія документа: **1.1** · Дата: 2026-06-27 · Аналіз гілки `main`._
_Останній коміт на момент цієї ревізії — `2ef4fa3` (2026-06-27 10:01). Перша версія (1.0) писалась із `5c234f2` (09:01); відмінність — лише чергові авто-синки цін, на факти документа не впливає._

**Що перевірено проти ЖИВОГО коду (через Read/Grep/git show origin/main):** структура репо й перелік файлів; видалення 4907 (`carvol_epicentr_generator.py`, `EPICENTR_COMMISSION` dict, коміти `42f19ac`/`5f54745`); обидві формули ціни (`pricing.py:calc_price` = mark-up попри докстрінг; `carvol_epicentr_generator.py:316` = gross-up); `FORBIDDEN_STATUSES={40,49,6}`, `ROZETKA_BASE='https://api-seller.rozetka.com.ua'`, `POLL_INTERVAL` sleep; імпорт `set_ttn/change_status` у `tg_dispatcher/main.py`; відсутність `.claude/agents/`; дубль `epicentr_postprocess.py` (корінь vs `tools/`); розбіжність шляхів `start_all.sh` vs `status.sh`; контакти Єпіцентру.

**Що взято з ДОКУМЕНТАЦІЇ репо (НЕ з живого `SELECT`/БД, може бути застарілим):** кількості товарів і рядків таблиць (~5908 Prom, ~8304 Carvol, 54370 брендів, ~40 таблиць тощо) — цифри з `CLAUDE.md`/`MASTER_CONTEXT.md`/`TASKS.md` станом на 2026-06-07…06-15; перелік daemon/systemd-сервісів і crontab — з доків і коментарів коду, не з живого `ps aux`/`crontab -l` на сервері; стан модерації товарів на маркетплейсах.
