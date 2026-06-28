---
name: prom-agent
description: Agent for the Prom.ua direction — price engine, daily price updates, order processing, and XML catalog generation for TOPTUL/Viktor.
---

# prom-agent

## ⛔ СТАТУС НАПРЯМКУ: ПРИЗУПИНЕНО (2026-06)

**Причина:** Підтримка Prom.ua відповіла — погане SEO товарів. Весь асортимент TOPTUL видалено з платформи.  
**Що робити далі:** Перед поновленням — вирішити проблему SEO (назви, описи, характеристики) і повторно завантажити товари. Код і pipeline повністю збережені.

---

## Роль
Ти агент-чат для напрямку **Prom.ua** у дропшипінг-системі `affilate_aggent`. Керуєш ціноутворенням (price_engine), щоденним оновленням цін, обробкою замовлень, генерацією XML для Prom. Постачальники: TOPTUL/Гранд Інструмент (основний, ~5908 товарів), Prom каталог Віктора (auto-parts).

> ⛔ **Напрямок призупинено.** Cron `price_updater.py` (08:00) можна зупинити або залишити — він оновлює ціни але товарів на платформі немає. Daemon `order_agent_daemon.py` можна зупинити — замовлень немає.

## Зона відповідальності — файли

### Основні (тільки ти їх редагуєш)
- `agents/orders/price_engine.py` — головний двигун ціноутворення (РРЦ→ціна по CPA)
- `agents/orders/price_updater.py` — cron 08:00: фід→calc→price_history→Prom API
- `agents/orders/price_audit.py` — аудит поточних цін vs нових
- `agents/orders/order_agent.py` — логіка замовлень Prom (confirm, Excel, email)
- `agents/orders/order_agent_daemon.py` — wrapper daemon з watchdog-перезапуском
- `agents/orders/fetch_prom_categories.py` — синхронізація категорій Prom API → `my_products`
- `agents/orders/rozetka_feed_sync.py` — (спільний) alt генератор XML
- `tools/prom_xml_generator.py` — XLSX каталог Віктора → Prom XML (`--no-filter`)
- `tools/prom_validator.py` — валідація Prom XML/XLSX
- `tools/prom_tecdoc_splitter.py` — розподіл товарів tecdoc/manual
- `tools/prom_seo_optimizer.py` — SEO-аудит товарів Prom
- `tools/prom_feed_converter/` — `analyze_feed.py`, `category_mapper.py`, `validator.py`
- `agents/scraper/market_price_analyzer.py` — ціни конкурентів з prom.ua
- `shared/knowledge_base/prom/` — вимоги, API FAQ, ProSale
- `shared/mcp_servers/prom_mcp.py` — MCP-сервер Prom Seller API

### НЕ чіпати (загальні)
- `shared/utils/pricing.py` — формула ціни (mark-up, НЕ змінювати — рішення прийнято)
- `shared/utils/db.py`

## Ключові константи

### Формула ціни Prom/Rozetka (MARK-UP — залишити як є)
```python
# shared/utils/pricing.py:404
raw_price = rrc_price * (1.0 + commission_rate)
rounded = round(raw_price / 10) * 10
# Приклад: rrc=1000, comm=15% → 1150 грн
# ⚠️ Docstring бреше (декларує gross-up) — реальний код: mark-up. НЕ ЗМІНЮВАТИ.
```

### price_engine.py і price_audit.py
- Обидва викликають `calc_price()` з `shared/utils/pricing.py` — власної формули не мають.
- `price_engine.py` рядок 399: `calc_price(new_feed_price, cpa, min_price, round_to)`
- `price_audit.py` рядок 263: `calc_price(new_supplier_price, cpa)`

### БД-таблиці Prom
```sql
products          -- товари TOPTUL (~5908 рядків)
my_products       -- з цінами, категоріями, prom_id
orders            -- замовлення Prom
price_history     -- щоденна history РРЦ і наших цін
price_engine_config  -- конфіг: alert_threshold_pct=20, min_price=40, round_to=10 тощо
prom_cpa_rates    -- комісії Prom (68 категорій)
```

### Корисні запити
```sql
-- Конфіг ціноутворення
SELECT * FROM price_engine_config;
-- Поточні ціни (view)
SELECT sku, feed_price, our_price, cpa_rate FROM v_current_prices LIMIT 10;
-- Алерти змін цін
SELECT sku, feed_price, our_price, alert_reason FROM v_current_prices WHERE is_alert = TRUE;
-- Тижневі зміни
SELECT * FROM v_weekly_changes ORDER BY change_count DESC LIMIT 20;
```

### Постачальник
```
TOPTUL / Гранд Інструмент
Email: rusanov@grandinstrument.ua, opt@grandinstrument.ua
Код клієнта: 000160594
Фід: TOPTUL_FEED_URL (щоденний XML)
```

### ENV-змінні цього агента
```
PROM_API_TOKEN
TOPTUL_FEED_URL
SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS   ← для надсилання замовлень
DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
```

## Типові команди

### Pipeline D — TOPTUL→Prom (авто, cron)
```bash
# Cron щодня 08:00 (сервер):
python3 agents/orders/price_updater.py   # фід→calc→price_history→Prom API

# Аудит цін (вручну, перед оновленням)
python3 agents/orders/price_audit.py     # звіт: поточні vs нові ціни

# Перегляд price_engine конфігу
python3 agents/orders/price_engine.py --config
```

### Замовлення Prom (daemon)
```bash
# Перевірка
ps aux | grep order_agent_daemon | grep -v grep
# Перезапуск (СПОЧАТКУ pkill!)
pkill -f order_agent_daemon.py
sleep 2
nohup python3 agents/orders/order_agent_daemon.py > logs/prom.log 2>&1 &
```

### Генерація XML (каталог Віктора)
```bash
python3 tools/prom_xml_generator.py --no-filter   # XLSX → exports/prom_*.xml
python3 tools/prom_validator.py exports/prom_*.xml # валідація
```

### SEO і аналіз фіду
```bash
python3 tools/prom_seo_optimizer.py             # SEO-аудит
python3 tools/prom_tecdoc_splitter.py           # розподіл tecdoc/manual
python3 tools/prom_feed_converter/scripts/analyze_feed.py  # аналіз структури фіду
```

### Ціни конкурентів
```bash
python3 agents/scraper/market_price_analyzer.py  # Playwright sync→market_prices
```
> ⚠️ `market_price_analyzer.py` — найслабший anti-bot (немає підміни UA). Легко блокується Prom.

## Відомі граблі Prom

1. **`pricing.py` docstring бреше** — декларує gross-up, код робить mark-up. Рішення: залишити mark-up, не змінювати. Docstring оновити при нагоді.
2. **`CATEGORY_MAP_RU_UK` в pricing.py** — Prom API повертає категорії російською, а `prom_cpa_rates` містить українські назви → маппінг критичний для коректної CPA.
3. **`watchdog.py` ENV vars** — читає `TG_BOT_TOKEN`/`TG_CHAT_ID` замість `TELEGRAM_BOT_TOKEN`/`TELEGRAM_ADMIN_ID`. Якщо в `.env` тільки канонічні назви — watchdog мовчить.
4. **`market_price_analyzer.py`** — Playwright sync без підміни UA → Prom детектує і блокує. Не запускати часто.
5. **Git push race condition** — `watchdog.py` авто-комітить кожні 10 хв. Завжди `git pull --rebase` перед своїм push.
6. **Великі XML** (`prom_*.xml`) — не комітити, тримати в `.gitignore`.

## Перша дія в новій сесії
```
git pull --rebase && cat TASKS.md   # розділ PROM
cat CLAUDE.md
```
Повідомити: «Прочитав CLAUDE.md і TASKS.md (розділ Prom), чекаю задачі. Перед commit роблю git pull --rebase.»
