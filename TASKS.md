# TASKS.md — живий список задач
Оновлено: 2026-06-28. Читати на початку кожної сесії разом з CLAUDE.md.

---

## ПОТОЧНИЙ СТАН НАПРЯМКІВ (2026-06-28)

| Напрямок | Статус | Деталі |
|---|---|---|
| **Rozetka — Carvol** | ✅ АКТИВНИЙ | XML-фід живий, cron щогодини, замовлення обробляються |
| **Rozetka — Катран** | ⛔ ПРИЗУПИНЕНО | Постачальник не пройшов перевірку |
| **Prom.ua — TOPTUL** | ⛔ ПРИЗУПИНЕНО | Підтримка Prom: погане SEO → весь товар видалено з платформи |
| **Єпіцентр — Carvol XML** | ⚠️ НЕ ГОТОВО | Pipeline потребує перегляду (плутанина категорій 4907/2866/2848/2874) |
| **Єпіцентр — TOPTUL** | ⚠️ ПРИБРАТИ | ~90% не пройшло модерацію → задача: видалити з платформи |
| **Єпіцентр — Секс Опт** | 🔜 ПЛАНУЄТЬСЯ | Є СТОП-категорії від постачальника (список — у власника) |
| **Khoroshop — Секс Опт** | ✅ АКТИВНИЙ | Магазин живий, весь асортимент доданий, фокус: донастроювання |

---

## ЗРОБЛЕНО ✅

### Єпіцентр — Carvol
- [x] `tools/carvol_epicentr_generator.py` — SpreadsheetML прайс → Єпіцентр XML (7075 офер)
- [x] `tools/epicentr_pim_explorer.py` — PIM API explorer, кеш 54370 брендів в БД
- [x] `tools/epicentr_quality_checker.py` — SEO скоринг XML (avg 73/100)
- [x] `tools/epicentr_xml_checker.py` — повна перевірка XML перед імпортом (структура/дублі/params/фото)
- [x] Params для всіх 6 категорій: 8743, 2866, 3729, 4907, 2848, 2821
- [x] Car brand detection (394 марки, attr 4866) з epicentr_car_brands БД
- [x] Бренди в XML: валідні valuecodes з epicentr_brand_map + fallback "Інше" (827b4a70...)
- [x] Постобробка: фото фільтр (8171→7081), дедуп (→7075), 2883→2848, trim назв
- [x] Виправлено pipeline: generator → `_new.xml` → postprocess → `carvol_epicentr.xml`
- [x] Опис з Rozetka фіду (7011 real + 1160 auto-generated)

### Інфраструктура
- [x] `infrastructure/api_methods.sql` — 123 API методи в БД (marketplace_api_methods)
- [x] `shared/knowledge_base/api_reference.md` — markdown довідник
- [x] `tools/watchdog.py` — виправлено: більше не робить git push (тільки локальний commit)
- [x] Crontab: feed_sync змінено з `0 */4` → `0 7` (щодня о 7:00)
- [x] DB: таблиці epicentr_brand_cache, epicentr_brand_map, epicentr_quality_log

---

## В ПРОЦЕСІ / АКТИВНІ ЗАДАЧІ 🔄

### ЄПІЦЕНТР — пріоритет 1: TOPTUL прибрати
- [ ] **Видалити TOPTUL з Єпіцентру** (~90% не пройшло модерацію)
      Зайти в merchant.epicentrk.ua → Товари → фільтр: відхилені → масове видалення
      Або через API: `epicentr_mcp.py` → метод delete_products
      > Поки менеджери не відповідають — уточнити процедуру при контакті

### ЄПІЦЕНТР — пріоритет 2: Carvol XML pipeline переглянути
- [ ] **Аудит і фікс Carvol→Єпіцентр pipeline** (НЕ готовий до production)
      Проблема: 3 версії категорій в коді і history (4907→видалено, 2866, 2848, плутанина 2874)
      Крок 1: знайти де в поточному коді ще є 4907 → замінити на 2866
      Крок 2: перевірити 2883→2848 в epicentr_postprocess.py (кореневий, не tools/)
      Крок 3: тест-генерація 5 товарів → перевірка xml_checker → тест-завантаження 1 товар
      Задача для: `claude --agent epicentr-agent`

### ЄПІЦЕНТР — пріоритет 3: Секс Опт (чекаємо список стоп-категорій)
- [ ] **Отримати від власника список СТОП-категорій** для Єпіцентр+Секс Опт
      До отримання: нічого не запускати. Після: додати фільтр у генератор.

### KHOROSHOP — донастроювання
- [ ] **Ціни** — перевірити актуальність (синхронізація з фідом Секс Опт)
- [ ] **Замовлення** — налаштувати автоматичну обробку (daemon або API polling)
- [ ] **Оновлення наявності** — автосинхронізація з фідом постачальника
      Власник додасть конкретний список пріоритетів

### PROM.UA — ⛔ ПРИЗУПИНЕНО (підтримка: погане SEO)
- [ ] **SEO аудит** — перед поновленням вирішити проблему SEO (назви, описи, характеристики)
      Інструменти: `tools/prom_seo_optimizer.py`, `tools/prom_tecdoc_splitter.py`
      Після SEO-фіксу: повторно завантажити товари

### ROZETKA — Катран — ⛔ ПРИЗУПИНЕНО (постачальник не пройшов перевірку)
- [ ] При поновленні: завершити маппінг 55% незамапованих категорій Катрана

### ІНФРАСТРУКТУРА
- [ ] **Скрейпінг конкурентів Rozetka** — Cloudflare блокує сервер
      Тест задокументований: `docs/SCRAPE_TEST_2026-06-27.md`
      Рішення: запускати з ноутбука або написати `tools/rozetka_search_scraper.py` з `--query`
      Задача для: `claude --agent rozetka-agent`

---

## НАСТУПНІ ЗАДАЧІ 📋

### Висока пріоритетність (блокують продажі)
- [ ] **Реєстрація бренду QIV через менеджера Єпіцентру**
      → підніме score з 73 → ~93, зачіпає 6110 офер  
      *(Поки менеджери не відповідають — заблоковано)*
- [ ] **Логін/пароль Розетки в .env виправити**
      (`hyper_store`/`Tovarka2025Rivne` → неправильні). Уточнити у власника.
- [ ] **Список СТОП-категорій від постачальника «Секс Опт»** для Єпіцентру
      → отримати від власника → додати фільтр у генератор

### Rozetka — активний напрямок
- [ ] `rozetka_price_corrector.py` — ✅ ГОТОВО, потребує `ROZETKA_API_TOKEN` в .env
      Команда: `python3 agents/orders/rozetka_price_corrector.py --dry-run`
- [ ] Інтеграція скрапера конкурентів в `price_manager` (після вирішення CF-блоку)
- [ ] ~~Налаштувати GitHub посилання для Катрана~~ — ⛔ ПРИЗУПИНЕНО разом з Катраном

### Prom.ua — SEO (перед поновленням)
- [ ] ~~`agents/orders/prom_order_agent.py`~~ — ⛔ ПРИЗУПИНЕНО (платформа неактивна)
- [ ] SEO аудит перед поновленням: `python3 tools/prom_seo_optimizer.py`
- [ ] AI Enrich pipeline для TOPTUL (товари без характеристик) — актуально після SEO-фіксу

### Катран — ⛔ ПРИЗУПИНЕНО (задачі на майбутнє)
- [ ] ~~Маппінг ~55% категорій~~ — відкладено до поновлення постачальника
      *(Смартфони, Планшети, Кабелі(80329), USB(80333), Картриджі(80296),*
      *Корпуси ПК(80038), Кулери(80049), Чорнила(73126), Чохли(4638562),*
      *LED лампи(4638153), USB Hub(80339), Контролери PCI(80052))*

### SEO та якість контенту (Єпіцентр)
- [ ] SEO покращення назв через Claude API (haiku-4-5)
      `python3 tools/epicentr_quality_checker.py --enhance-names --limit 500`
- [ ] Видалити "телефон" зі 1276 описів
      `python3 tools/epicentr_quality_checker.py --fix --output exports/carvol_epicentr_fixed.xml`

### Інфраструктура
- [ ] Watchdog/systemd для критичних процесів (tg_dispatcher, rozetka_order_agent, epicentr_order_agent)
- [ ] NotebookLM бази знань SEO для кожного маркетплейсу

---

## EPICENTR PIPELINE (поточний стан)

### Зроблено
- [x] Генератор `carvol_epicentr_generator.py` з маппінгом 8 категорій
- [x] Params для 8743, 2866, 3729, 4907, 2848, 2821
- [x] Car brand detection (394 марки, attr 4866)
- [x] Постобробка (фото фільтр, дедуп, 2883→2848, обрізка назв)
- [x] `epicentr_xml_checker.py` — повна перевірка перед імпортом (exit 0/1)

### В роботі
- [ ] Модерація 7075 товарів Carvol на Єпіцентрі

### Наступні задачі
- [ ] `epicentr_category_builder.py` — автодискавері attrs+valuecodes з PIM API + генерація `elif` блоку
- [ ] Таблиця `epicentr_attr_options` в БД (category_code, attr_code, valuecode, name_ua, regex_patterns)
- [ ] AI mapping: назва товару → valuecode через Claude API з кешем в БД
- [ ] Гібридний маппінг: regex → якщо не знайдено → Claude API → кеш

---

## ROZETKA PRICE MANAGER

### Зроблено
- [x] `rozetka_price_manager.py` (--generate / --apply)
- [x] `rozetka_price_corrector.py`
- [x] Виправлена формула `calc_price` (gross-up)

### Наступні задачі
- [ ] Інтеграція скрапера конкурентів в `price_manager`
- [ ] Автоматичне оновлення цін на основі цін конкурентів (-X% від конкурента)
- [ ] Мінімальна маржа як захист (не нижче собівартості + N%)

---

## COMPETITOR SCRAPER + SEO (НОВА ІДЕЯ)

### Концепція
Парсер конкурентів → аналіз цін → автоматична корекція наших цін.
+ Аналіз SEO конкурентів → переробка описів під наш магазин.

### Задачі
- [ ] Доробити `agents/scraper/` — додати підтримку URL магазину конкурента
- [ ] Вигружати: назва, ціна, артикул, опис, характеристики
- [ ] `price_sync_agent.py` — порівнює ціни конкурента з нашими → генерує CSV корекцій
- [ ] Правила ціноутворення: якщо конкурент дешевше → ми на N% дешевше (але не нижче мін. маржі)
- [ ] `seo_rewriter.py` — бере опис конкурента → Claude API → переписує унікальний текст
- [ ] Інтеграція з Rozetka/Prom/Єпіцентр через існуючі агенти

### Технічний стек
- Playwright (вже є в `agents/scraper/playwright_base.py`)
- Claude API (claude-haiku-4-5) для SEO переписування
- PostgreSQL для кешу цін конкурентів
- Порівняльна таблиця: наша ціна vs конкурент vs рекомендована

---

## АРХІТЕКТУРА АГЕНТІВ (загальна)
- Оркестратор → Redis → агенти
- Всі нові агенти підключати через Redis queue
- Логи в PostgreSQL таблицю `agent_logs`

---

## КОРИСНІ КОМАНДИ

```bash
# Повний пайплайн Єпіцентр (на сервері)
python3 tools/carvol_epicentr_generator.py   # → exports/carvol_epicentr_new.xml
python3 epicentr_postprocess.py              # → exports/carvol_epicentr.xml
# scp і перевірка (на ноутбуці)
scp tek@100.82.24.112:/home/tek/agent-system/exports/carvol_epicentr.xml ~/Downloads/
python3 tools/epicentr_xml_checker.py ~/Downloads/carvol_epicentr.xml

# Генерація Єпіцентр XML з кастомним прайсом (на сервері)
python3 tools/carvol_epicentr_generator.py --input data/carvol_opt_YYYYMMDD.xml

# SEO звіт
ssh tek@100.82.24.112 "cd /home/tek/agent-system && source venv/bin/activate && python3 tools/epicentr_quality_checker.py --xml exports/carvol_epicentr.xml --report"

# Пошук бренду в Єпіцентрі
ssh tek@100.82.24.112 "cd /home/tek/agent-system && source venv/bin/activate && EPICENTR_TOKEN=$(grep EPICENTR_TOKEN .env | cut -d= -f2) python3 tools/epicentr_pim_explorer.py find-brand 'QIV'"

# БД — стан брендів
docker exec agent_postgres psql -U agentadmin agentdb -c "SELECT DISTINCT brand_name, value_ua FROM epicentr_brand_map ORDER BY brand_name;"

# Перевірка API методів що не реалізовані
docker exec agent_postgres psql -U agentadmin agentdb -c "SELECT marketplace, method_name, endpoint, priority FROM marketplace_api_methods WHERE NOT is_implemented ORDER BY priority, marketplace;"
```

## EPICENTR XML CHECKER — доробити
- [ ] Перевірка valuecodes через PIM API (чи існують реально)
- [ ] dims > 0 для кожного офера (не тільки наявність)
- [ ] HEAD запит на фото URL (чи реально відкривається)
- [ ] Ціна в розумному діапазоні (не < 100 і не > 500000)
- [ ] Дублікати назв між різними артикулами
- [ ] Перевірка country_of_origin valuecode
- [ ] Порівняння з попереднім імпортом (diff)

## API COMMAND CENTER (новий великий проект)

### Концепція
Єдиний інструмент керування всіма маркетплейсами через текстові/голосові команди.
Еволюція: Web UI → Telegram бот → Голосові команди

### Стадія 1 — Web API Explorer (в роботі)
- [x] Виправити баг URL формування в web_api_explorer.py
- [x] Виправити відображення відповіді у браузері (textarea#response-body)
- [x] Таблиця api_test_log в БД (логування всіх запитів)
- [x] Пошук по командах (текстове поле зліва)
- [x] Pretty JSON відповідь (права панель 70vh)
- [x] Вкладки: Body | Headers | Запит | Час

### Стадія 2 — База текстових команд
- [ ] Кожен API метод отримує текстову команду (slug)
  Приклади:
  - "замовлення" → GET /v3/oms/orders
  - "замовлення 123" → GET /v3/oms/orders/123
  - "підтвердити 123" → POST /v3/oms/orders/123/change-status/to/confirmed_by_merchant
  - "ттн 123 1234567890123 нп" → POST /v3/oms/orders/123/shipping/nova_poshta
  - "категорії" → GET /v2/pim/categories
  - "ціни rozetka" → GET /orders/search
- [ ] Таблиця api_command_map (command_text, marketplace, endpoint, method, param_template)
- [ ] Parser команд: розбирає текст → знаходить метод → підставляє параметри
- [ ] Тестування через веб-інтерфейс

### Стадія 3 — Telegram бот інтеграція
- [ ] Підключити command parser до існуючого tg-dispatcher
- [ ] Бот приймає текстову команду → виконує API запит → повертає відформатовану відповідь
- [ ] Форматування відповіді: коротке резюме (не сирий JSON)
  Приклад: "✅ Замовлення #123 підтверджено. Клієнт: Іван, товар: Рамка VW Golf, сума: 1610 грн"
- [ ] Inline кнопки для частих дій (підтвердити / скасувати / ТТН)
- [ ] Сповіщення про нові замовлення автоматично

### Стадія 4 — Карта відповідей (Response Map)
- [ ] Для кожного endpoint зберігати структуру реальних відповідей в БД
- [ ] api_response_schema (endpoint, field_path, field_type, example_value)
- [ ] Автогенерація форматтерів на основі схеми
- [ ] Валідація відповідей (якщо структура змінилась — алерт)

### Стадія 5 — Голосові команди (фінальна)

#### Архітектура
Голос → STT → Текст → Command Parser → API → Response Formatter → TTS → Голос

#### Компоненти
- [ ] STT (Speech-to-Text):
  - Варіант А: Whisper локально на ноутбуці (RTX 4050, безкоштовно)
  - Варіант Б: OpenAI Whisper API ($0.006/хв)
  - Рекомендація: Whisper medium локально — якість 95%+ для укр/рос мови

- [ ] TTS (Text-to-Speech):
  - Варіант А: pyttsx3 локально (безкоштовно, якість середня)
  - Варіант Б: ElevenLabs API (висока якість, платно)
  - Варіант В: Google TTS (безкоштовно до ліміту)
  - Рекомендація: спочатку Google TTS, потім ElevenLabs

- [ ] Voice Bot Pipeline:
  - Telegram Voice Message → завантажити .ogg файл
  - Конвертувати ogg → wav (ffmpeg)
  - Whisper → текст
  - Command Parser → API запит
  - Відповідь → форматування
  - Google TTS → .mp3
  - Відправити Voice Message назад в Telegram

- [ ] Мовні моделі для розуміння намірів:
  - Простий intent classifier (regex + keywords) — для стандартних команд
  - LLM fallback (ollama qwen2.5:7b) — для складних/нестандартних запитів
  - Приклад: "покажи мені що там з замовленням від Олени" → знайти замовлення по імені клієнта

#### Інтеграція з ноутбуком
- [ ] voice_agent.py на ноутбуці (Whisper + мікрофон)
- [ ] Або через Telegram (голосове повідомлення → бот обробляє на сервері)

### Технічний стек всього проекту
| Компонент | Технологія | Де |
|-----------|-----------|-----|
| Web UI | Flask + vanilla JS | сервер :5555 |
| API proxy | Flask /api/proxy | сервер |
| Command parser | Python regex + LLM | сервер |
| Telegram bot | python-telegram-bot | сервер (tg-dispatcher) |
| STT | Whisper medium | ноутбук або сервер |
| TTS | Google TTS / ElevenLabs | API |
| БД | PostgreSQL (agentdb) | сервер |
| Черга | Redis | сервер |

### Пріоритет виконання
1. Спочатку: виправити Web UI (стадія 1) — тестовий інструмент
2. Потім: база команд (стадія 2) — фундамент для всього
3. Далі: Telegram текст (стадія 3) — практичне використання
4. Пізніше: карта відповідей (стадія 4) — надійність
5. Фінал: голос (стадія 5) — wow-ефект

---

## EPICENTR PRODUCT INTELLIGENCE MODULE (новий модуль)

### Концепція
Повний цикл: Конкурент → Парсинг → Аналіз → Генерація → Перевірка → Імпорт

### Архітектура модуля
tools/epicentr_intelligence/

├── 01_category_mapper.py      # Маппінг наших категорій → Єпіцентр категорії

├── 02_competitor_finder.py    # Пошук конкурентів по категорії/артикулу

├── 03_card_parser.py          # Парсинг картки товару конкурента

├── 04_attr_analyzer.py        # Аналіз характеристик конкурента

├── 05_content_generator.py    # Генерація назви/опису через Claude API

├── 06_xml_builder.py          # Збірка XML офера з усіх даних

├── 07_xml_checker.py          # Перевірка (існуючий epicentr_xml_checker.py)

└── pipeline.py                # Оркестратор всього процесу

### Стадія 1 — Category Intelligence
- [ ] Для кожної нашої категорії знайти 3-5 товарів конкурентів на Єпіцентрі
- [ ] Зберігати еталонні URL по категоріях в БД таблиця `epicentr_category_samples`
- [ ] `category_samples (category_code, url, parsed_at, attrs_json)`
- [ ] Автоматично витягувати required attrs з реальних карток (не тільки з API)

### Стадія 2 — Competitor Intelligence
- [ ] `competitor_finder.py` — пошук конкурентів:
  - Пошук на epicentrk.ua по артикулу/назві
  - Пошук по категорії (топ продавці)
  - Збереження в `competitor_products (article, epicentr_url, competitor_price, our_price, diff_pct)`
- [ ] Порівняльна таблиця: наша ціна vs конкурент
- [ ] Алерт якщо конкурент дешевше на >10%

### Стадія 3 — Card Parser
- [ ] `card_parser.py` — парсинг картки товару Єпіцентру:
  - Назва (ua/ru)
  - Опис (ua/ru)
  - Всі характеристики з valuecodes
  - Фото URLs
  - Ціна конкурента
  - Категорія і attribute_set
  - Бренд valuecode
- [ ] Зберігати в `parsed_cards (url, article, data_json, parsed_at)`
- [ ] Playwright (headless) або requests + BeautifulSoup

### Стадія 4 — Attribute Analyzer
- [ ] `attr_analyzer.py` — аналіз зібраних карток:
  - Які valuecodes використовують конкуренти для кожного attr
  - Найпопулярніші значення по категорії
  - Автоматичний маппінг: наш товар → valuecode конкурента
  - Детектування марки авто, кольору, розміру з назви

### Стадія 5 — Content Generator
- [ ] `content_generator.py` — генерація контенту через Claude API:
  - Вхід: назва товару + характеристики + опис конкурента
  - Вихід: унікальна назва (≤150 символів) + SEO опис
  - Переписування опису конкурента (не копіювання)
  - Додавання ключових слів для пошуку
  - Мова: ua (основна) + ru (опційно)

### Стадія 6 — XML Builder
- [ ] `xml_builder.py` — збірка повного XML офера:
  - Всі required params з правильними valuecodes
  - Перевірка розміру (<50MB)
  - Виправлення битих фото URL
  - name lang="ua" обов'язково, lang="ru" опційно

### Стадія 7 — Pipeline Orchestrator
- [ ] `pipeline.py --category 8743 --input data/carvol_opt.xml`:
  1. Знайти еталонні картки конкурентів для категорії
  2. Розпарсити їх атрибути
  3. Згенерувати XML з правильними valuecodes
  4. Перевірити через xml_checker
  5. Вивести звіт готовності

### БД таблиці
```sql
CREATE TABLE epicentr_category_samples (
    category_code TEXT,
    url TEXT PRIMARY KEY,
    parsed_at TIMESTAMPTZ,
    attrs_json JSONB
);

CREATE TABLE competitor_products (
    article TEXT,
    category_code TEXT,
    epicentr_url TEXT,
    competitor_price FLOAT,
    our_price FLOAT,
    scraped_at TIMESTAMPTZ
);

CREATE TABLE parsed_cards (
    url TEXT PRIMARY KEY,
    article TEXT,
    data_json JSONB,
    parsed_at TIMESTAMPTZ
);

CREATE TABLE epicentr_attr_options (
    category_code TEXT,
    attr_code TEXT,
    valuecode TEXT,
    name_ua TEXT,
    usage_count INT DEFAULT 0,
    PRIMARY KEY (category_code, attr_code, valuecode)
);
```

### Методика перевірки (чеклист перед імпортом)
□ 1. Структура XML валідна

□ 2. yml_catalog/offers закриті по 1 разу

□ 3. Дублікати артикулів = 0

□ 4. Всі назви ≤ 150 символів

□ 5. Всі фото: JPEG, https://, розмір >30 символів

□ 6. Всі ціни > 0

□ 7. Категорії тільки з активованих (зелених в кабінеті)

□ 8. vendor з valuecode (не пустий)

□ 9. country_of_origin є

□ 10. weight/width/height/length > 0 (числа, не букви)

□ 11. Всі required params присутні по категорії

□ 12. Всі valuecodes існують в PIM API довіднику

□ 13. Розмір файлу < 50MB (для ручного завантаження)

□ 14. description lang="ua" є у кожного товару

□ 15. Мінімум 1 фото на товар (рекомендовано 3+)

### Пріоритет виконання
1. Створити БД таблиці (швидко)
2. card_parser.py — парсинг еталонних карток (основа)
3. attr_analyzer.py — маппінг valuecodes
4. xml_checker.py — додати перевірку valuecodes через API
5. pipeline.py — зібрати все разом
6. content_generator.py — SEO через Claude API

### Команди CLI
```bash
# Знайти еталонні картки для категорії
python3 tools/epicentr_intelligence/competitor_finder.py --category 8743

# Розпарсити картку конкурента
python3 tools/epicentr_intelligence/card_parser.py --url "https://epicentrk.ua/..."

# Проаналізувати valuecodes категорії
python3 tools/epicentr_intelligence/attr_analyzer.py --category 8743

# Повний pipeline для категорії
python3 tools/epicentr_intelligence/pipeline.py --category 8743 --input data/carvol_opt.xml

# Перевірка XML перед імпортом (розширена)
python3 tools/epicentr_xml_checker.py ~/Downloads/carvol_epicentr.xml --validate-valuecodes
```

---

## UNIVERSAL CATEGORY BUILDER (будь-яка категорія)

### Концепція
Система яка може підготувати валідний XML для БУДЬ-ЯКОЇ категорії Єпіцентру
без хардкоду — повністю через API + парсинг + AI.

### Проблема яку вирішуємо
Зараз кожна нова категорія = ручна робота:
1. Знайти required attrs через PIM API
2. Знайти valuecodes для кожного attr
3. Написати elif в генераторі
4. Протестувати

Ціль: цей процес має бути повністю автоматичним.

### Модуль: tools/epicentr_category_builder.py

#### Крок 1 — Discover (автовідкриття категорії)
Вхід: category_code (напр. "2874")

→ GET /v2/pim/attribute-sets/{code}

→ Список всіх required attrs з типами

→ Для кожного select/multiselect attr:

GET /v2/pim/attribute-sets/{code}/attributes/{attr}/options

→ Зберегти в epicentr_attr_options БД

#### Крок 2 — Sample (знайти еталон)
→ Парсинг epicentrk.ua/ua/shop/{category_slug}/

→ Взяти перші 5 товарів

→ Розпарсити їх картки (всі attrs + valuecodes)

→ Зберегти як еталони в epicentr_category_samples

#### Крок 3 — Map (маппінг наших полів)
Для кожного required attr:

IF тип float/integer:

→ взяти дефолтне значення з еталону або 0

IF тип select/multiselect:

→ спробувати regex match по назві товару

IF не знайшло:

→ Claude API: "який valuecode підходить для цього товару?"

→ зберегти результат в кеш

#### Крок 4 — Generate (генерація elif блоку)
```python
# Автоматично генерується код:
elif cat_code == '2874':
    # Автосвітло — згенеровано автоматично {date}
    params += [
        _p('Тип лампи', '1234', 'led_code', 'LED'),
        _p('Цоколь', '5678', 'h4_code', 'H4'),
        _pf('Потужність', '103', 55),
    ]
```

#### Крок 5 — Validate (перевірка)
→ Тест-генерація 1 офера в новій категорії

→ Перевірка через epicentr_xml_checker

→ Тест-імпорт (1 товар) в кабінет

→ Якщо OK → додати в генератор

### Universal Attribute Handler
```python
class UniversalAttrHandler:
    """
    Обробляє будь-який атрибут будь-якої категорії.
    Не потребує хардкоду.
    """
    
    def resolve(self, attr_code, attr_type, name, category_code):
        # 1. Перевірити кеш в БД
        # 2. Спробувати regex по назві
        # 3. Спробувати Claude API
        # 4. Повернути дефолт якщо нічого не знайшло
        pass
    
    def learn(self, attr_code, name_fragment, valuecode):
        # Зберегти успішний маппінг для майбутнього
        pass
```

### БД таблиці для Universal Builder
```sql
-- Кеш маппінгу: фраза → valuecode
CREATE TABLE attr_mapping_cache (
    category_code TEXT,
    attr_code     TEXT,
    name_fragment TEXT,  -- "volkswagen", "h4", "led"
    valuecode     TEXT,
    confidence    FLOAT, -- 0.0-1.0
    source        TEXT,  -- 'regex'|'claude'|'manual'|'sample'
    used_count    INT DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (category_code, attr_code, name_fragment)
);

-- Еталонні картки по категоріях
CREATE TABLE epicentr_category_samples (
    id            SERIAL PRIMARY KEY,
    category_code TEXT,
    url           TEXT UNIQUE,
    title         TEXT,
    attrs_json    JSONB,  -- {attr_code: valuecode}
    parsed_at     TIMESTAMPTZ DEFAULT NOW()
);

-- Статус категорій: чи готова до використання
CREATE TABLE epicentr_category_status (
    category_code TEXT PRIMARY KEY,
    name_ua       TEXT,
    is_discovered BOOLEAN DEFAULT FALSE,  -- attrs отримані з API
    is_sampled    BOOLEAN DEFAULT FALSE,  -- еталони розпарсені
    is_mapped     BOOLEAN DEFAULT FALSE,  -- маппінг готовий
    is_tested     BOOLEAN DEFAULT FALSE,  -- тест-імпорт успішний
    is_active     BOOLEAN DEFAULT FALSE,  -- використовується в генераторі
    attrs_count   INT,
    samples_count INT,
    last_updated  TIMESTAMPTZ DEFAULT NOW()
);
```

### Команди CLI
```bash
# Повний цикл для нової категорії
python3 tools/epicentr_category_builder.py --category 2874 --full

# Тільки отримати attrs з API
python3 tools/epicentr_category_builder.py --category 2874 --discover

# Тільки знайти еталони
python3 tools/epicentr_category_builder.py --category 2874 --sample

# Згенерувати elif блок для генератора
python3 tools/epicentr_category_builder.py --category 2874 --generate-code

# Статус всіх категорій
python3 tools/epicentr_category_builder.py --status

# Додати нову категорію в активні
python3 tools/epicentr_category_builder.py --category 2874 --activate
```

### Сценарій додавання НОВОЇ категорії (покроково)

Знайти category_code на epicentrk.ua або через PIM API

→ python3 tools/epicentr_category_builder.py --search "відеореєстратор"
Запустити discover

→ python3 tools/epicentr_category_builder.py --category 2855 --discover

Результат: всі required attrs збережені в БД
Знайти еталони конкурентів

→ python3 tools/epicentr_category_builder.py --category 2855 --sample

Результат: 5 реальних карток з valuecodes в БД
Побудувати маппінг

→ python3 tools/epicentr_category_builder.py --category 2855 --map

Результат: attr_mapping_cache заповнений
Згенерувати код для генератора

→ python3 tools/epicentr_category_builder.py --category 2855 --generate-code

Результат: готовий elif блок для вставки в carvol_epicentr_generator.py
Протестувати на 1 товарі

→ python3 tools/epicentr_category_builder.py --category 2855 --test
Активувати

→ python3 tools/epicentr_category_builder.py --category 2855 --activate


### Генератор стає Universal
```python
def get_category_params(cat_code, name, car_brand_map=None):
    # Спочатку перевіряємо хардкодні (швидко, перевірені)
    if cat_code == '8743':
        return _params_8743(name, car_brand_map)
    elif cat_code == '4907':
        return _params_4907(name)
    # ... інші перевірені категорії ...
    
    # Fallback: Universal Handler для всього іншого
    else:
        handler = UniversalAttrHandler(db_conn)
        return handler.resolve_all(cat_code, name)
```

### Пріоритет реалізації
1. БД таблиці (15 хв)
2. --discover (отримати attrs з API) (1 год)
3. --sample (парсинг еталонів) (2 год)
4. --generate-code (генерація elif) (1 год)
5. UniversalAttrHandler з кешем (3 год)
6. --map через Claude API (2 год)
7. Інтеграція в генератор як fallback (1 год)

---

## ROZETKA AUTOMATION AUDIT (25.06.2026) — ВИРІШЕНО ✅

### Корінь проблеми (знайдено)
Старий процес `tg_dispatcher/main.py` (PID 452258) висів з **8 червня** (17 днів) і
блокував `getUpdates` для Telegram API — новий запуск бота завжди отримував
`TelegramConflictError`. Через це жодні вхідні PDF з ТТН не доходили до бота,
весь цикл ТТН доводилось робити вручну.

### Виправлення
1. [x] Знайдено і вбито старий зомбі-процес (PID 452258, запущений 8 черв.)
2. [x] Запущено новий tg_dispatcher/main.py → Connection established без конфліктів
3. [x] Виправлено rozetka_order_agent.py — статус waiting_payment більше не застрягає назавжди
4. [x] Перезапущено rozetka_order_agent.py (PID 1818677)

### Архітектура (підтверджено робочою)
rozetka_order_agent.py (poll 5 хв) → нове замовлення → confirm_order() → Excel → Telegram Carvol
Carvol → PDF з ТТН → Telegram
tg_dispatcher/main.py (слухає Telegram) → ttn_pdf_parser.parse_ttn_pdf() → np_api.get_ttn_info() + match_order_by_np_data() → rozetka_order_agent.set_ttn() + change_status(3)

### Залишилось зробити
- [ ] Watchdog/systemd для критичних процесів (tg_dispatcher, rozetka_order_agent, epicentr_order_agent) — перевірка ps aux кожні 10 хв, pkill старих дублів перед запуском нового, Telegram-алерт при перезапуску
- [ ] Перевірити epicentr_order_agent.py на аналогічні зомбі-дублікати
- [ ] CLAUDE.md: додати розділ "Критичні daemon-процеси"
