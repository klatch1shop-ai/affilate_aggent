# DUMP_ENV_TEMPLATE.md — змінні оточення

> Репо `affilate_aggent`, гілка `main`, коміт `03da6e8` (2026-06-27).

## 1. Реальний `.env.example` з репо

```bash
# ── База даних (PostgreSQL у Docker на сервері) ───────────
DB_HOST=192.168.x.x
DB_PORT=5432
DB_NAME=agentdb
DB_USER=agentadmin
DB_PASSWORD=

# ── Redis (на сервері) ────────────────────────────────────
REDIS_HOST=192.168.x.x
REDIS_PORT=6379

# ── Qdrant (векторна БД на сервері) ──────────────────────
QDRANT_HOST=192.168.x.x
QDRANT_PORT=6333

# ── Ollama (локально на ноутбуці) ────────────────────────
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=llama3.2:3b
OLLAMA_DEV_MODEL=deepseek-coder:6.7b-instruct-q4_K_M

# ── Епіцентр API ─────────────────────────────────────────
EPICENTR_TOKEN=
EPICENTR_API_URL=https://epicentrk.ua/api/v2

# ── Toptul XML фід ────────────────────────────────────────
TOPTUL_FEED_URL=

# ── Telegram ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_ID=

# ── Prometheus / Моніторинг ───────────────────────────────
PROM_API_TOKEN=

# ── Claude / Anthropic API ────────────────────────────────
ANTHROPIC_API_KEY=

# ── Загальні налаштування ─────────────────────────────────
APP_ENV=development
LOG_LEVEL=INFO
```

## 2. УСІ ключі `os.getenv`/`os.environ`, знайдені в коді (key :: перший файл)

> ⚠️ `.env.example` **НЕПОВНИЙ** — нижче повний список ключів, що реально читаються кодом. Багатьох (ROZETKA_API_TOKEN, NP_API_KEY, KATRAN_FEED_URL_STOCK, CARVOL_*, SMTP_*, EPICENTR_LOGIN/PASSWORD/EMAIL, TG_*, OLLAMA_MODEL_*) у `.env.example` немає.

```bash
ANTHROPIC_API_KEY         =    # tools/ai_xml_generator.py
CARD_MODEL                =    # agents/scraper/run_night_processing.py
CARVOL_SUPPLIER_CODE      =    # agents/orders/rozetka_order_agent.py
CARVOL_SUPPLIER_EMAIL     =    # agents/orders/rozetka_order_agent.py
CARVOL_TG_CHAT_ID         =    # tg_dispatcher/main.py
DB_HOST                   =    # enrich_agent.py
DB_NAME                   =    # enrich_agent.py
DB_PASSWORD               =    # enrich_agent.py
DB_PORT                   =    # enrich_agent.py
DB_USER                   =    # enrich_agent.py
DEV_OLLAMA_MODEL          =    # agents/dev/dev_agent.py
EPICENTR_API_URL          =    # shared/mcp_servers/epicentr_mcp.py
EPICENTR_EMAIL            =    # agents/scraper/epicentr_cabinet.py
EPICENTR_LOGIN            =    # dashboard/api.py
EPICENTR_PASSWORD         =    # dashboard/api.py
EPICENTR_TOKEN            =    # test_epicentr.py
KATRAN_FEED_URL_STOCK     =    # tools/katran_category_xml.py
NP_API_KEY                =    # tools/web_api_explorer.py
OLLAMA_BASE_URL           =    # shared/utils/ollama_worker.py
OLLAMA_DEV_MODEL          =    # agents/dev/dev_agent.py
OLLAMA_MODEL              =    # mass_enrich.py
OLLAMA_MODEL_ANALYSIS     =    # shared/utils/model_selector.py
OLLAMA_MODEL_CODE         =    # shared/utils/model_selector.py
OLLAMA_MODEL_DEFAULT      =    # shared/utils/model_selector.py
OLLAMA_MODEL_ROUTING      =    # shared/utils/model_selector.py
OLLAMA_MODEL_TEXT         =    # shared/utils/model_selector.py
OLLAMA_URL                =    # mass_enrich.py
PROM_API_TOKEN            =    # tools/web_api_explorer.py
REDIS_HOST                =    # shared/utils/memory.py
REDIS_PORT                =    # shared/utils/memory.py
ROZETKA_API_TOKEN         =    # tools/web_api_explorer.py
ROZETKA_LOGIN             =    # shared/mcp_servers/rozetka_mcp.py
ROZETKA_PASSWORD          =    # shared/mcp_servers/rozetka_mcp.py
SERVER_IP                 =    # embedding_service.py
SMTP_HOST                 =    # agents/orders/order_agent.py
SMTP_PASS                 =    # agents/orders/order_agent.py
SMTP_PORT                 =    # agents/orders/order_agent.py
SMTP_USER                 =    # agents/orders/order_agent.py
TELEGRAM_ADMIN_ID         =    # tg_dispatcher/main.py
TELEGRAM_BOT_TOKEN        =    # tg_dispatcher/main.py
TELEGRAM_CHAT_ID          =    # tools/watchdog.py
TG_BOT_TOKEN              =    # tools/watchdog.py
TG_CHAT_ID                =    # tools/watchdog.py
TOPTUL_FEED_URL           =    # tools/epicentr_category_mapper.py
```

> Примітка: `tools/watchdog.py` читає `TG_BOT_TOKEN`/`TG_CHAT_ID`/`TELEGRAM_CHAT_ID` — інші назви, ніж `TELEGRAM_BOT_TOKEN`/`TELEGRAM_ADMIN_ID` решти коду. Перевірити, чи це не баг конфігурації (watchdog може не слати алерти, якщо в .env лише канонічні назви).
