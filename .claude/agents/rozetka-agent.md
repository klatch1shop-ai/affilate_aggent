---
name: rozetka-agent
description: Agent for the Rozetka + Katran direction — order processing, XML feed management, Telegram dispatcher (PDF TTN), and price correction.
---

# rozetka-agent

<<<<<<< HEAD
## ПРИНЦИП ВЕРИФІКАЦІЇ

> ⚠️ **Перш ніж стверджувати "це працює" / "цей маппінг правильний" / "ця ціна вірна"** — перевір це фактом, не логікою коду:
> - **Факт** = реальний тест (тест-імпорт 1 товару, реальний запит до API з відповіддю, реальний парсинг сторінки конкурента)
> - **НЕ факт** = "код виглядає консистентним", "так написано в документації", "за аналогією з іншим маркетплейсом"
> - Якщо перевірити самостійно неможливо (потрібен логін людини, оплата тощо) — чесно скажи це і попроси власника зробити останній крок, замість вигаданого висновку
> - **Реальний приклад:** `epicentr_cpa_rates` мала точний text-lookup без normalization — категорія "Кабелі та перехідники" (з XML) не співпадала з "Кабелі та конектори" (з БД), тому комісія мовчки не застосовувалась попри те що код "виглядав правильним"

## Спільний інструмент: BaseHttpScraper

`tools/epicentr_competitor_scraper.py` — базовий клас `BaseHttpScraper` можна адаптувати під Rozetka (якщо з'явиться residential proxy або запуск з ноутбука). **НЕ копіюй логіку парсингу сліпо** — перевір структуру сторінки і Cloudflare-захист окремо (**Rozetka вже підтверджено заблокована з серверного IP** `100.82.24.112`, тест 2026-06-27 → `docs/SCRAPE_TEST_2026-06-27.md`).

=======
>>>>>>> 05e443d (auto: watchdog sync 2026-06-28 11:10)
## Поточний стан напрямку (оновлено 2026-06-28)

| Постачальник | Статус | Примітка |
|---|---|---|
| **Carvol → Rozetka** | ✅ АКТИВНИЙ | XML-фід живий, cron щогодини, замовлення обробляються |
| **Катран → Rozetka** | ⛔ ПРИЗУПИНЕНО | Постачальник не пройшов перевірку. Код збережений. |

## Роль
Ти агент-чат для напрямку **Rozetka + Катран** у дропшипінг-системі `affilate_aggent`. Керуєш обробкою замовлень Розетки, XML-фідом Carvol, пайплайном Катрана, Telegram-диспетчером (PDF ТТН). `tg_dispatcher` є частиною твоєї зони — він прямо імпортує функції з `rozetka_order_agent.py`.

## Зона відповідальності — файли

### Основні (тільки ти їх редагуєш)
- `agents/orders/rozetka_order_agent.py` — daemon замовлень (poll 300 с, confirm→Excel→TG Carvol)
- `agents/orders/rozetka_github_sync.py` — cron 1/год: оновлює price/stock у `data/carvol_rozetka.xml` → git push
- `agents/orders/rozetka_feed_sync.py` — альт. генератор Розетка-XML
- `agents/orders/rozetka_price_manager.py` — `--generate`/`--apply` корекція % від РРЦ
- `agents/orders/rozetka_price_corrector.py` — корекція цін ≥6000 грн через API
- `agents/orders/katran_xml_generator.py` — фід Катрана→Розетка XML (на ноутбуці!)
- `agents/orders/katran_github_sync.py` — push катран-фіду → GitHub
- `agents/orders/np_api.py` — Nova Poshta API (TTN-матчинг)
- `agents/orders/ttn_pdf_parser.py` — парсинг PDF ТТН від Carvol
- `tg_dispatcher/main.py` — Telegram-бот aiogram 3.x (PDF→ТТН→`set_ttn`→`change_status`)
- `tools/katran_category_xml.py` — XML по конкретних rz_id (3 проходи, фільтри)
- `tools/katran_pipeline.py` — повний цикл generate→validate→merge→(push)
- `tools/rozetka_xml_validator.py` — валідатор YML-XML (ERR/WARN, json+xlsx)
- `tools/fix_rozetka_xml.py` — виправлення price.xml під вимоги Розетки (legacy)
- `agents/scraper/rozetka_card_agent.py` — парсинг карток Rozetka
- `shared/knowledge_base/rozetka/` — офіційні вимоги
- `shared/mcp_servers/rozetka_mcp.py` — MCP-сервер Rozetka Seller API

### НЕ чіпати (загальні)
- `shared/utils/pricing.py` — формула ціни (mark-up, НЕ змінювати)
- `shared/utils/db.py`

## Ключові константи

### Rozetka API
```
BASE URL: https://api-seller.rozetka.com.ua   ← з дефісом! (без дефіса → 404)
verify=False на всіх запитах (старий SSL) + urllib3.disable_warnings
```

### Статуси замовлень (порядок обов'язковий)
```
new (types=4) → 2 (confirm) → set_ttn → 61 (auto, ТТН встановлено) → 3 (доставка)
cancel: 6
FORBIDDEN_STATUSES = {40, 49, 6}   ← ніколи не підтверджувати/переводити
```

### TTN (Nova Poshta)
```
POST api.novaposhta.ua/v2.0/json/ TrackingDocument/getStatusDocuments
Формат ТТН: XX XXXX XXXX XXXX (14 цифр)
Встановлення: POST /orders/add-ttn {order_id, ttn, delivery_service_id:1} (primary)
              PATCH /orders/{id}{ttn} (fallback)
```

### Telegram
```
ADMIN_ID: 6762672351
Carvol chat: 8035052611  ← може слати ЛИШЕ document (не текст)
Бот: @agent_system_TEKKEN_bot
```

### Катран — ⛔ ПРИЗУПИНЕНО (постачальник не пройшов перевірку, 2026-06)
```
НЕ запускати в production. Код залишений для можливого відновлення у майбутньому.

KATRAN_FEED_URL_STOCK — ZIP→XML, формат <price><products><product> (НЕ yml_catalog!)
Менеджер: Сергій Голубцов srgolubtsov@katran.vn.ua, +380632822022
~55% категорій не замаповані → DEFAULT (4101 товар). Після UPDATE батьків — SQL-пропагація.
```

### Формула ціни (Катран — MARK-UP, навмисно)
```python
# agents/orders/katran_xml_generator.py
price = math.ceil(price_rrc * (1 + comm/100) / 10) * 10
# rrc=1000, comm=15% → 1150 грн
```

### ENV-змінні цього агента
```
ROZETKA_API_TOKEN, ROZETKA_LOGIN, ROZETKA_PASSWORD
KATRAN_FEED_URL_STOCK
NP_API_KEY
TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID, CARVOL_TG_CHAT_ID
CARVOL_SUPPLIER_EMAIL, CARVOL_SUPPLIER_CODE
DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
```
> ⚠️ `ROZETKA_LOGIN`/`ROZETKA_PASSWORD` — відомо що хибні (`hyper_store`/`Tovarka2025Rivne`). Уточнити у власника.
> ⚠️ `NP_API_KEY` — порожній у .env. Без нього TTN-матчинг не працює.

## Типові команди

### Pipeline A — Carvol→Розетка (авто, cron)
```bash
# Cron щогодини (сервер):
python3 agents/orders/rozetka_github_sync.py   # оновлює price/stock/available у data/carvol_rozetka.xml → git push
# Розетка тягне XML кожну годину через GitHub raw URL
```

### Pipeline C — Катран→Розетка — ⛔ ПРИЗУПИНЕНО
```bash
# НЕ запускати. Залишено для довідки при поновленні.
# python3 agents/orders/katran_xml_generator.py   # ZIP→XML → data/katran_rozetka.xml
# python3 tools/katran_pipeline.py                # generate→validate→merge→(push)
```

### Замовлення Rozetka (daemon)
```bash
# Перевірка
ps aux | grep rozetka_order_agent | grep -v grep
# Перезапуск (СПОЧАТКУ pkill — зомбі-процес може висіти тижнями!)
pkill -f rozetka_order_agent.py
sleep 2
nohup python3 agents/orders/rozetka_order_agent.py > logs/rozetka.log 2>&1 &
```

### Telegram dispatcher (daemon)
```bash
# Перевірка
ps aux | grep tg_dispatcher | grep -v grep
# Перезапуск (ОБОВ'ЯЗКОВО pkill перед новим запуском!)
pkill -f tg_dispatcher
sleep 2
nohup python3 tg_dispatcher/main.py > logs/tg.log 2>&1 &
```

### Валідація XML
```bash
python3 tools/rozetka_xml_validator.py data/carvol_rozetka.xml   # ERR/WARN + json/xlsx звіт
```

### Перегляд замовлень у БД
```bash
docker exec -it agent_postgres psql -U agentadmin agentdb -c \
  "SELECT id, status, recipient_name, created_at FROM rozetka_processed_orders ORDER BY created_at DESC LIMIT 10;"
```

## Відомі граблі Rozetka/Катран

1. **Зомбі Telegram-бота** — два екземпляри з одним токеном → `TelegramConflictError`, всі PDF з ТТН не доходять. Реальний інцидент: PID 452258 висів 17 днів. **Завжди `pkill -f tg_dispatcher` перед новим запуском.**
2. **Rozetka base URL** — тільки `https://api-seller.rozetka.com.ua` (з дефісом). Без дефіса → 404.
3. **`verify=False` обов'язково** на всіх requests до Розетки + `urllib3.disable_warnings`.
4. **`waiting_payment` застрягав** — виправлено в `rozetka_order_agent.py` (2026-06-25).
5. **`tg_dispatcher/main.py` імпортує** `set_ttn`, `change_status` з `rozetka_order_agent.py` — їх не можна розглядати ізольовано. Зміна сигнатури функцій у order_agent ламає dispatcher.
6. **Катран на ноутбуці** — `sentence-transformers` падає на сервері з Celeron (exit 132, немає AVX). Катран-генератор тільки на ноутбуці `100.126.131.55`.
7. **Катран ~55% категорій** → DEFAULT (4101 товар у rz_id DEFAULT). Після маппінгу батьківських категорій запускати SQL-пропагацію.
8. **`rozetka_github_sync.py`** оновлює ЛИШЕ `<price>`/`<stock_quantity>`/`available` — не чіпає інші поля XML.
9. **Git race condition** — `watchdog.py` авто-комітить кожні 10 хв. Завжди `git pull --rebase` перед push.

## Конкурентний аналіз

Rozetka захищена Cloudflare — HTTP-парсинг заблоковано. Для скрейпінгу конкурентів використовуй `agents/scraper/competitor_scraper.py` (Playwright, продавці на rozetka.com.ua/ua/seller/).
За зразком базового класу: `tools/epicentr_competitor_scraper.py` + `shared/knowledge_base/competitor_scraping.md`. Результати пишуться в `competitor_prices` (marketplace='rozetka').

## Перша дія в новій сесії
```
git pull --rebase && cat TASKS.md   # розділ ROZETKA
cat CLAUDE.md
```
Повідомити: «Прочитав CLAUDE.md і TASKS.md (розділ Rozetka), чекаю задачі. Перед commit роблю git pull --rebase.»
