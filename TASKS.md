# TASKS.md — живий список задач
Оновлено: 2026-06-15. Читати на початку кожної сесії разом з CLAUDE.md.

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

## В ПРОЦЕСІ 🔄

- [ ] **Завантажити `exports/carvol_epicentr.xml` в кабінет Єпіцентру**
      Файл готовий: 7075 офер, 42MB, ГОТОВИЙ ДО ІМПОРТУ ✅ (перевірено xml_checker)
      URL кабінету: merchant.epicentrk.ua

- [ ] **Модерація 7075 товарів Carvol на Єпіцентрі**
      Після завантаження відстежити які не пройшли модерацію → виправити

- [ ] **Перевірити TOPTUL чернетки в Єпіцентрі** (~5893)
      Які не пройшли модерацію? Які потрібно виправити?

- [ ] **Налаштувати авто-оновлення наявності Carvol для Єпіцентру**
      Зараз XML генерується вручну. Потрібен cron аналогічно Rozetka.

---

## НАСТУПНІ ЗАДАЧІ 📋

### Висока пріоритетність (блокують продажі)
- [ ] Реєстрація бренду QIV через менеджера Єпіцентру
      → підніме score з 73 → ~93, зачіпає 6110 офер
- [ ] Логін/пароль Розетки в .env виправити
      (hyper_store/Tovarka2025Rivne → incorrect_username_password)
- [ ] Налаштувати друге GitHub посилання для Катрана в кабінеті Розетки
      (через менеджера Софію Івановську)

### SEO та якість контенту
- [ ] SEO покращення назв через Claude API (haiku-4-5)
      `python3 tools/epicentr_quality_checker.py --enhance-names --limit 500`
- [ ] Видалити "телефон" зі 1276 описів
      `python3 tools/epicentr_quality_checker.py --fix --output exports/carvol_epicentr_fixed.xml`
- [ ] AI Enrich pipeline для TOPTUL (товари без характеристик)

### Нові агенти
- [ ] `agents/orders/rozetka_price_corrector.py` ✅ ГОТОВО — оновлює ціни ≥6000 грн через API
      Команда: `python3 agents/orders/rozetka_price_corrector.py --dry-run`
      Потребує: `ROZETKA_API_TOKEN` в .env, `data/margin_analysis_6k.csv`
- [ ] `agents/orders/prom_order_agent.py` — агент замовлень Prom.ua (не існує)
- [ ] `agents/orders/katran_order_agent.py` — агент замовлень Катран (пізніше)
- [ ] `agents/orders/katran_xml_generator.py` — Катран → Розетка XML

### Катран — маппінг категорій (~55% залишилось)
- [ ] Підтвердити в PriceCreator або через bt.rozetka.com.ua/c{id}/:
      Смартфони, Планшети, Кабелі(80329), USB(80333), Картриджі(80296),
      Корпуси ПК(80038), Кулери(80049), Чорнила(73126), Чохли(4638562),
      LED лампи(4638153), USB Hub(80339), Контролери PCI(80052)
- [ ] Виправити Молотки/Біти/Набори пневмо/Мультиметри для Єпіцентру

### Інфраструктура
- [ ] Перевірити XML katran_rozetka.xml через валідатор Розетки
      URL: seller.rozetka.com.ua/gomer/pricevalidate/check/index
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
