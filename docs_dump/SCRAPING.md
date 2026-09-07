# SCRAPING.md — скрейпінг та парсинг зовнішніх сайтів

> Репо: `klatch1shop-ai/affilate_aggent`, гілка `main` (`2ef4fa3`, 2026-06-27).
> Тут описано **браузерний/HTTP-скрейпінг** (Playwright, requests+BeautifulSoup) зовнішніх сайтів — конкуренти, картки товарів, ціни, кабінети.
> Прямі **API-інтеграції** з маркетплейсами (Rozetka/Prom/Єпіцентр Seller API) сюди НЕ входять — вони в `docs/PIPELINE.md`/`SYSTEM.md`.
> Знайдено грепом `grep -rl "playwright\|selenium\|BeautifulSoup\|sync_playwright\|async_playwright" --include=*.py`. `selenium` у репо не використовується.

---

## 0. Карта скрейперів

| Скрипт | Цільовий сайт | Метод | Self-healing | Куди пише | Запуск |
|--------|---------------|-------|--------------|-----------|--------|
| `agents/scraper/playwright_base.py` | — (базовий клас) | Playwright async | **так** (вбудовано) | `browser_sessions`, `browser_action_log` | імпорт |
| `agents/scraper/epicentr_cabinet.py` | `admin.epicentrm.com.ua` (наш кабінет) | Playwright async (через base) | так (успадковано) | `epicentr_sku_mapping` | вручну / `browser_mcp` |
| `agents/scraper/scraper_agent.py` | `rozetka.com.ua`, `prom.ua` | Playwright async | **ні** | `scraped_products` | shar-B daemon (не в обороті) |
| `agents/scraper/market_price_analyzer.py` | `prom.ua/ua/search` | Playwright **sync** | **ні** | `market_prices` | вручну |
| `tools/competitor_scraper.py` | `rozetka.com.ua/ua/seller/` | Playwright async | **ні** | `competitor_products` | вручну CLI |
| `agents/scraper/debug_page.py` | `rozetka.com.ua` | Playwright async | ні | — (HTML у файл) | dev |
| `agents/scraper/find_url.py` | `rozetka.com.ua` | Playwright `headless=False` | ні | — (консоль) | dev |
| `enrich_with_ai.py` / `enrich_agent.py` / `mass_enrich.py` | `grandinstrument.ua/search/` | `requests` + BeautifulSoup | ні | `products` | one-off |
| `shared/mcp_servers/browser_mcp.py` | (обгортка над base/cabinet) | Playwright async | так (через base) | — | MCP on-demand |

> `agents/scraper/category_classifier.py` і `rozetka_card_agent.py` — **НЕ скрейпери**: працюють з уже збереженими даними БД + Ollama (класифікація категорій / переклад параметрів рос→укр). Живого парсингу сайтів у них немає.

---

## 1. `playwright_base.py` — базовий клас (фундамент)

Клас `PlaywrightBase(site, headless=True, proxy=None)`. Призначений як предок для всіх Playwright-агентів. **Реально успадковується лише** `epicentr_cabinet.py` (і через нього `browser_mcp.py`). Інші скрейпери його ігнорують — це головна проблема (розділ 4).

Фічі — по факту коду:

| Фіча | Реалізація | Реально працює? |
|------|-----------|-----------------|
| **Self-Healing клік/fill** | `resilient_click`/`resilient_fill`: пряма спроба → пошук по тексту → `_find_selector_by_description` (варіанти `[aria-label*=]`, `[placeholder*=]`, `[title*=]`, `button:has-text`, `a:has-text`, `[data-testid*=]`) → скріншот + TG-алерт | так |
| **Сесії** | `_load_session`/`save_session`: cookies+UA у `browser_sessions`, `valid_until` 23 год, `ON CONFLICT DO UPDATE` | так |
| **Anti-bot: UA** | 3 фіксовані desktop-UA; UA **фіксується на сесію** і зберігається в БД (`_get_or_create_ua`) | так, але пул лише 3 |
| **Anti-bot: webdriver mask** | `add_init_script`: `navigator.webdriver=undefined`, `plugins=[1,2,3]` | так |
| **Anti-bot: launch args** | `--no-sandbox`, `--disable-dev-shm-usage`, `--disable-blink-features=AutomationControlled` | так |
| **Random delays** | `random_delay(300,1200 ms)`, `navigate()` додає 500–1500 ms | так |
| **Viewport** | **фіксований 1280×800** (НЕ ротується) | ⚠️ фінгерпринт-ризик |
| **Proxy** | параметр `proxy` → один `proxy.server`; **ротації немає** | ⚠️ |
| **Retry/backoff** | докстрінг обіцяє «exponential backoff», але в коді **немає циклу ретраїв з backoff** — лише одна альтернативна спроба селектора | ❌ розбіжність докстрінга з кодом |
| **Скріншоти помилок** | `screenshot()` → `logs/screenshots/{site}_{name}_{ts}.png` | так |
| **TG-алерти** | `_telegram_alert` (text+photo) при невдачі self-healing | так |
| **Перехоплення XHR/fetch** | `intercept_start/stop`, `get_bearer_token` (з localStorage/cookies) | так |
| **Лог дій** | `_log_action` → `browser_action_log` | так |

---

## 2. Скрейпери конкурентів і карток

### 2.1 `tools/competitor_scraper.py` — продавці на Rozetka
- **Сайт:** `rozetka.com.ua/ua/seller/{seller}/` (+ `--seller`, `--pages`, `--no-save`).
- **Метод:** Playwright async, **standalone** (НЕ через `playwright_base`).
- **Anti-bot:** власний `user_agent`, `human_delay`, `random`, `time.sleep`. Без проксі, без ротації viewport.
- **Селектори:** `rz-product-tile` (плитка), `a.tile-title` (назва), `[class*='price']` (ціна), `.rating-block-rating` (рейтинг), `rz-paginator a.page` (пагінація). **Fallback-селекторів немає** — зміна верстки Rozetka зламає парсер.
- **Вихід:** `INSERT INTO competitor_products`.
- **Запуск:** вручну CLI. Стабільність: помилки ловляться, але self-healing немає.

### 2.2 `agents/scraper/scraper_agent.py` — shar-B скрейпер (Rozetka + Prom)
- **Сайти:** `rozetka.com.ua/ua/...` (категорії), `prom.ua/search`, `my.prom.ua/api/v1/products/list`.
- **Метод:** Playwright async, власний `build_stealth_context`. Працює через **Redis-чергу** (`pop_task`), це daemon шару B — **у щоденному обороті не використовується**.
- **Anti-bot (найсильніший у репо):** 5 UA **ротуються** (`random.choice`), 4 **viewports ротуються**, `human_delay(800–2800 ms)`, `human_scroll` (mouse.wheel), init-script ховає `webdriver`+`plugins`+`window.chrome`. Проксі немає.
- **Селектори (Rozetka):** `li.catalog-grid__cell`, `span.goods-tile__title`, `span.goods-tile__price-value`, `a.goods-tile__heading`; картка: `div[data-qaid='product_gallery_item']`, `span[data-qaid='product_name']`. **Хардкод, без self-healing.**
- **Вихід:** `INSERT INTO scraped_products`.

### 2.3 `agents/scraper/market_price_analyzer.py` — ціни конкурентів з Prom
- **Сайт:** `prom.ua/ua/search?search_term={sku}`.
- **Метод:** Playwright **sync**, `headless=True`. **Найслабший anti-bot:** немає підміни UA взагалі, лише дефолтний headless-контекст (легко детектується), `sleep`. Без self-healing.
- **Селектори:** `[data-qaid="product_price"]`, `[class*=price]`.
- **Вихід:** `UPDATE my_products`, `INSERT INTO market_prices` (читає `prom_cpa_rates`).
- **Запуск:** вручну (функція `get_competitor_prices(sku)`).

### 2.4 `agents/scraper/epicentr_cabinet.py` — наш кабінет Єпіцентру
- **Сайт:** `admin.epicentrm.com.ua` (`/login`, `/products`, `/orders`, `/import`) — це **наш** кабінет, не конкурент.
- **Метод:** Playwright async **через `PlaywrightBase`** → отримує self-healing, сесії, anti-bot, скріншоти безкоштовно.
- **Функції:** логін+збереження сесії, скачування XLS товарів → маппінг артикулів, завантаження XLS з цінами/наявністю, перехоплення API endpoints, підтвердження замовлень.
- **Вихід:** `INSERT/UPDATE epicentr_sku_mapping`.
- **Запуск:** вручну або через `browser_mcp.py`.

### 2.5 `enrich_with_ai.py` / `enrich_agent.py` / `mass_enrich.py` — HTTP-скрейп постачальника
- **Сайт:** `grandinstrument.ua/search/` (сайт постачальника TOPTUL).
- **Метод:** `requests` + **BeautifulSoup** (без Playwright). Без anti-bot. Далі — збагачення через Ollama (`OLLAMA_URL`/`OLLAMA_MODEL`).
- **Вихід:** `UPDATE products` (характеристики/описи).
- **Запуск:** one-off batch.

### 2.6 dev-артефакти
- `debug_page.py` — зберігає HTML сторінки Rozetka (`headless=True`) для аналізу селекторів. Селектори-зонди: `li`, `div[class*='product']`.
- `find_url.py` — `headless=False` (відкриває вікно), ручний підбір селекторів на `rozetka.com.ua/ua/`.

> **Стабільність:** живих логів (`logs/`, `logs/screenshots/`, `browser_action_log`) у репо немає, тож підтвердити частоту timeout/«selector not found» по факту не можна — перевіряти на сервері. Архітектурно ризик зламу високий скрізь, де немає self-healing (2.1–2.3).

---

## 3. Anti-bot: зведення по силі захисту

| Скрейпер | UA | Viewport | Delays | webdriver-mask | Proxy | Self-heal | Оцінка |
|----------|----|---------:|--------|----------------|-------|-----------|--------|
| `scraper_agent.py` | 5, ротація | 4, ротація | random | так | ні | ні | 🟢 найкращий, але без self-heal |
| `playwright_base` (+`epicentr_cabinet`) | 3, фікс/сесію | фікс 1280×800 | random | так | 1 (без ротації) | **так** | 🟡 |
| `competitor_scraper.py` | власний | — | random | (немає init-script) | ні | ні | 🟡 |
| `market_price_analyzer.py` | **немає** | дефолт | sleep | ні | ні | ні | 🔴 найслабший |
| `enrich_*` (requests/BS4) | дефолт requests | — | — | — | ні | — | 🔴 |

---

## 4. Рекомендації (дії над цим кодом)

### 4.1 Перевести на `playwright_base.PlaywrightBase` (немає self-healing зараз)
`scraper_agent.py`, `market_price_analyzer.py`, `competitor_scraper.py` (+`debug_page.py`/`find_url.py` як dev) — усі мають власні Playwright-обгортки з хардкод-селекторами. Перенести на `PlaywrightBase` (`resilient_click`/`wait_for`/`get_table`), щоб при зміні верстки Rozetka/Prom спрацьовувало self-healing і TG-алерт замість тихого 0 результатів.

### 4.2 Слабкий anti-bot → ризик блокування IP
- `market_price_analyzer.py` — додати підміну UA і init-script (зараз дефолтний headless детектується Prom миттєво).
- `playwright_base` — **ротувати viewport** (зараз фіксований 1280×800 = стабільний фінгерпринт) і взяти пул UA зі `scraper_agent` (5 замість 3).
- **Проксі-ротації немає ніде.** На обсягах (8k+ товарів, регулярний моніторинг) один IP → бан. Додати пул проксі + ротацію на рівні `PlaywrightBase.start()`.

### 4.3 Retry / captcha
- `PlaywrightBase` докстрінг обіцяє «exponential backoff», але в коді його **немає** — додати реальний цикл ретраїв з backoff навколо `navigate()`/`resilient_*`.
- Обробки CAPTCHA немає ніде. Мінімум — детект капчі (за селектором/текстом) → скріншот + TG-алерт + пауза, без автоматичного обходу.

### 4.4 Khoroshop — окреме дослідження (нова задача)
Для інтимних товарів сайти конкурентів часто мають **вікові гейти та cookie-стіни** перед контентом — стандартні селектори не спрацюють до проходження гейту. Потрібен окремий R&D: чи знадобиться спеціальний скрейпер конкурентів Khoroshop з обробкою age-gate/cookie-wall. Позначити як окрему задачу до старту напряму (не копіювати наявні Rozetka-скрейпери 1:1).

### 4.5 Уніфікація в один `competitor_scraper.py --marketplace`
Зараз логіка конкурентів розпорошена: `competitor_scraper.py` (Rozetka), `market_price_analyzer.py` (Prom), `scraper_agent.py` (обидва). **Доцільно** звести в один параметризований скрейпер на базі `PlaywrightBase` з профілями селекторів на маркетплейс (dict `{marketplace: {tile, title, price, ...}}`). Складність — середня: селектори вже відомі (розділ 2), основна робота — спільний раннер + перенос трьох наборів селекторів у конфіг і єдина таблиця-вихід.

### 4.6 Найвищий пріоритет (1 крок зараз)
**Додати проксі-ротацію + реальний retry/backoff у `PlaywrightBase`, і перевести `competitor_scraper.py` і `market_price_analyzer.py` на цей клас.** Це закриває одразу два найбільші ризики (блок IP і тихий злам при зміні верстки) для скрейперів, які реально запускаються вручну для моніторингу цін.

---

_Версія: 1.0 · 2026-06-27 · гілка `main` (`2ef4fa3`). Факти — з читання коду; runtime-стабільність потребує перевірки логів на сервері._
