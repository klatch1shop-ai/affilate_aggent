# Browser Automation — Мега-парсер та автоматизація дій

## Концепція
Агент отримує текстову команду → перетворює на послідовність browser дій → 
Playwright виконує в headless браузері → повертає результат + скріншот.

## MCP сервер
`shared/mcp_servers/browser_mcp.py`

## Доступні інструменти (tools)

### Навігація
```
browser_open(url)                    # відкрити URL в новій вкладці
browser_navigate(url)                # перейти на сторінку
browser_back()                       # назад
browser_screenshot(name)             # скріншот → зберегти в logs/
browser_wait(selector, timeout=30)   # чекати появи елемента
```

### Взаємодія з елементами
```
browser_click(selector_or_text)      # клік по CSS селектору або тексту кнопки
browser_fill(selector, value)        # заповнити поле вводу
browser_select(selector, value)      # вибрати значення з dropdown
browser_hover(selector)              # навести мишу
browser_scroll(direction, amount)    # прокрутити сторінку
browser_press(key)                   # натиснути клавішу (Enter, Tab, Escape)
```

### Файли
```
browser_upload(selector, filepath)   # завантажити файл на сервер
browser_download(click_selector)     # скачати файл, повернути шлях
browser_save_page(filepath)          # зберегти HTML сторінки
```

### Читання даних
```
browser_get_text(selector)           # текст елемента
browser_get_value(selector)          # значення input поля
browser_get_table(selector)          # таблиця → list of dicts
browser_get_all_links()              # всі посилання на сторінці
browser_get_html(selector)           # HTML фрагменту
browser_find_elements(selector)      # знайти всі елементи
browser_execute_js(script)           # виконати JS, повернути результат
```

### Перехоплення мережі (найпотужніше!)
```
browser_intercept_start()            # почати запис XHR/fetch запитів
browser_intercept_stop()             # зупинити, повернути всі перехоплені
browser_intercept_filter(pattern)    # фільтр по URL патерну
browser_mock_response(url, data)     # підмінити відповідь API
browser_get_websocket_messages()     # повідомлення WebSocket
```

### Сесії та авторизація
```
browser_login(site)                  # логін (epicentr/rozetka/prom/grandinstrument)
browser_session_save(site)           # зберегти cookies/localStorage в БД
browser_session_load(site)           # відновити сесію з БД
browser_session_check(site)         # перевірити чи сесія активна
browser_get_token(site)              # витягти Bearer token зі storage
```

### Управління браузером
```
browser_new_tab()                    # нова вкладка
browser_close_tab()                  # закрити вкладку
browser_set_viewport(width, height)  # розмір вікна
browser_set_user_agent(ua)           # підмінити User-Agent
browser_clear_cookies()              # очистити cookies
```

---

## Приклади команд (природна мова)

### Єпіцентр кабінет
```
"Зайди в кабінет Єпіцентру і скачай XLS всіх товарів"
→ login epicentr → navigate /products → click Export → download → parse xlsx

"Завантаж XLS з оновленими цінами в Єпіцентр"
→ login epicentr → navigate /import → upload file.xlsx → submit → check result

"Знайди внутрішні артикули для SKU: BAEA1217, KR1012, E102-7-3"
→ login epicentr → search each SKU → extract article ID → return mapping

"Підтвердь замовлення #67890 в Єпіцентрі"
→ login epicentr → navigate /orders/67890 → click Підтвердити → screenshot

"Знайди всі API endpoints кабінету Єпіцентру"
→ login epicentr → intercept_start → browse all pages → intercept_stop → analyze
```

### Моніторинг конкурентів
```
"Знайди ціни TOPTUL BAEA1217 у конкурентів на Prom"
→ navigate prom.ua/search → parse top 10 results → extract prices → compare

"Моніторинг цін топ-20 SKU на Розетці щодня"
→ scheduled task → для кожного SKU → search rozetka → extract min price → save to DB

"Хто продає TOPTUL дешевше за нас?"
→ query price_history → compare with competitor_prices table → alert
```

### Постачальники
```
"Скачай актуальний прайс з grandinstrument.ua"
→ login grandinstrument → navigate /price → download xlsx → parse → update DB

"Перевір наявність товару BCRA1613 у Грандінструмент"
→ login → search SKU → extract availability → return status
```

### Розетка
```
"Перевір статус XML синхронізації на Розетці"
→ login rozetka seller → navigate /prices → extract status → return

"Скачай звіт замовлень Розетки за тиждень"
→ login → navigate /orders → set date filter → download report
```

---

## Алгоритм виконання команди

```python
async def execute_command(command: str) -> dict:
    # 1. Перевірити збережену сесію
    session = await browser_session_load(detect_site(command))
    
    # 2. Якщо сесії немає або протухла — логінитись
    if not session or session.expired:
        await browser_login(site)
        await browser_session_save(site)
    
    # 3. LLM розбиває команду на кроки
    steps = await llm_plan_steps(command, available_tools)
    
    # 4. Виконуємо кроки послідовно
    for step in steps:
        result = await execute_step(step)
        if result.error:
            # retry або повідомлення про помилку
            break
    
    # 5. Повертаємо результат + скріншот
    return {
        'success': True,
        'result': final_result,
        'screenshot': screenshot_path,
        'steps_executed': len(steps)
    }
```

---

## Таблиця `browser_sessions` в БД

```sql
CREATE TABLE browser_sessions (
    id          SERIAL PRIMARY KEY,
    site        VARCHAR(50) UNIQUE,   -- epicentr/rozetka/prom/grandinstrument
    cookies     JSONB,                -- всі cookies
    local_storage JSONB,              -- localStorage (токени)
    headers     JSONB,                -- збережені headers (Bearer token)
    valid_until TIMESTAMP,            -- коли протухає (автовизначення)
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
```

---

## Таблиця `competitor_prices` в БД

```sql
CREATE TABLE competitor_prices (
    id              SERIAL PRIMARY KEY,
    sku             VARCHAR(50),
    marketplace     VARCHAR(20),     -- prom/rozetka/epicentr
    competitor_name VARCHAR(100),
    competitor_url  VARCHAR(500),
    price           NUMERIC(12,2),
    in_stock        BOOLEAN,
    checked_at      TIMESTAMP DEFAULT NOW()
);
```

---

## Технічна архітектура

```
shared/
├── mcp_servers/
│   └── browser_mcp.py           # MCP сервер (всі tools)
├── skills/
│   └── scraper/
│       └── browser_automation.md  # цей файл
└── utils/
    └── browser_session.py       # управління сесіями

agents/scraper/
├── playwright_base.py           # базовий клас
│   ├── retry logic              # автоповтор при помилці
│   ├── proxy rotation           # ротація проксі
│   ├── captcha detection        # виявлення капчі
│   └── screenshot on error      # скріншот при помилці
│
├── epicentr_cabinet.py          # Єпіцентр кабінет
│   ├── login()
│   ├── export_products_xls()    # скачати всі товари
│   ├── import_prices_xls()      # завантажити ціни
│   ├── confirm_order(id)        # підтвердити замовлення
│   ├── get_order_details(id)    # деталі замовлення
│   └── intercept_api()          # знайти API endpoints
│
├── rozetka_cabinet.py           # Розетка seller cabinet
│   ├── login()
│   ├── get_xml_status()
│   └── download_orders_report()
│
├── competitor_monitor.py        # моніторинг конкурентів
│   ├── search_prom(sku)
│   ├── search_rozetka(sku)
│   └── save_to_db(results)
│
└── grandinstrument_parser.py    # постачальник
    ├── login()
    ├── download_pricelist()
    └── check_availability(sku)
```

---

## Пріоритет розробки

### Фаза 1 (наступний тиждень) — Єпіцентр
1. `playwright_base.py` — базовий клас
2. `epicentr_cabinet.py` — логін + скачування XLS
3. Маппінг їхній_ID ↔ наш_SKU → таблиця в БД
4. Автозавантаження XLS з цінами/наявністю
5. `browser_mcp.py` — базові tools

### Фаза 2 (2 тижні) — Перехоплення API
1. Intercept всіх XHR запитів кабінету Єпіцентру
2. Автоматично знайти OMS endpoints
3. Документувати і додати в epicentr_mcp.py

### Фаза 3 (3 тижні) — Конкуренти
1. `competitor_monitor.py` — щоденний парсинг
2. Таблиця competitor_prices
3. Алерти якщо хтось продає дешевше

### Фаза 4 (місяць) — Повна автономія
1. Агент отримує текстову команду
2. LLM планує кроки
3. Playwright виконує
4. Результат в Telegram
