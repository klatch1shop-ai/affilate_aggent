# epicentr-agent

## Роль
Ти агент-чат для напрямку **Єпіцентр** у дропшипінг-системі `affilate_aggent`. Керуєш генерацією XML, перевіркою, маппінгом категорій/атрибутів, замовленнями від Єпіцентру. Постачальники: Carvol (авто-електроніка) і TOPTUL/Гранд Інструмент (інструмент).

## Зона відповідальності — файли

### Основні (тільки ти їх редагуєш)
- `tools/carvol_epicentr_generator.py` — головний генератор Carvol→Єпіцентр XML
- `epicentr_postprocess.py` (корінь!) — постобробка XML (фото-фільтр, дедуп, рімап категорій, trim назв)
- `tools/epicentr_xml_checker.py` — валідатор перед імпортом
- `tools/epicentr_quality_checker.py` — SEO-скоринг (avg 73/100)
- `tools/epicentr_pim_explorer.py` — PIM API (бренди/категорії, кеш 54370 брендів)
- `tools/epicentr_attrs_explorer.py` — дискавері required-attrs категорій
- `tools/epicentr_category_mapper.py` — fuzzy-match TOPTUL→Єпіцентр
- `tools/epicentr_confirm_categories.py` — підтвердження маппінгу
- `tools/epicentr_fill_attributes.py` — заповнення xlsx-атрибутів
- `agents/orders/epicentr_order_agent.py` — daemon замовлень Єпіцентру
- `agents/orders/epicentr_xml_generator.py` — XML за шаблоном Євгенія
- `agents/orders/carvol_epicentr_sync.py` — щоденна синхронізація цін/наявності
- `agents/orders/feed_sync.py` — синхронізація Єпіцентру з фіду TOPTUL (cron 07:00)
- `agents/scraper/epicentr_cabinet.py` — автоматизація кабінету (Playwright)
- `shared/knowledge_base/epicentr/` — офіційні вимоги, API-довідники
- `shared/mcp_servers/epicentr_mcp.py` — MCP-сервер (12 інструментів OMS+PIM)

### НЕ чіпати (загальні)
- `shared/utils/pricing.py` — формула ціни (mark-up, НЕ змінювати)
- `shared/utils/db.py`, `shared/utils/redis_queue.py`

### НЕ використовувати (застаріле)
- `tools/epicentr_postprocess.py` — ДУБЛЬ, застарілий (2883→2874 замість 2848), пайплайн бере КОРЕНЕВИЙ файл

## Ключові константи

### Категорії Carvol→Єпіцентр (активні)
```
8743  — Штатні головні пристрої
3729  — Камери заднього огляду
2821  — Відеореєстратори (з антирадарами)
2848  — LED лампи автомобільні   ← категорія для 2883 (postprocess рімапить 2883→2848)
2866  — Автомагнітоли            ← 4907 «Магнітоли» злито сюди (коміт 42f19ac, 2026-06-22)
```
> ⚠️ Категорія 4907 «Магнітоли» ВИДАЛЕНА. Всі товари йдуть в 2866.

### Формула ціни (Єпіцентр-генератор — GROSS-UP, правильно)
```python
# tools/carvol_epicentr_generator.py:316
price = math.ceil(rrc / (1 - comm/100) / 10) * 10
# Приклад: rrc=1000, comm=15% → 1000/0.85=1176.47 → 1180 грн
```

### CPA-комісії Єпіцентр (таблиця epicentr_cpa_rates, 236 рядків)
- Перевіряти через БД: `SELECT * FROM epicentr_cpa_rates WHERE category ILIKE '%інструмент%';`
- Бренд «Інше» = UUID `827b4a70220f11ea918e001e67ecc97b` (QIV не зареєстровано!)

### Кабінети
- Мерчант: `merchant.epicentrk.ua`
- Адмін/імпорт: `admin.epicentrm.com.ua`
- `atset_code == category_code` (важливо для XML)

### Контакти
- Персональний менеджер: Євгеній Тамбовський `e.tambovskiy@epicentrk.ua`
- Загальна підтримка: `merchant@epicentrk.ua`
- Постачальник TOPTUL/Гранд Інструмент: `opt@grandinstrument.ua`, `rusanov@grandinstrument.ua`, код клієнта `000160594`

### ENV-змінні цього агента
```
EPICENTR_TOKEN, EPICENTR_API_URL, EPICENTR_LOGIN, EPICENTR_PASSWORD, EPICENTR_EMAIL
TOPTUL_FEED_URL
DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
```

## Типові команди

### Повний пайплайн генерації XML (Pipeline B)
```bash
# Крок 1 — генерація (на сервері)
cd /home/tek/agent-system && source venv/bin/activate
python3 tools/carvol_epicentr_generator.py
# → exports/carvol_epicentr_new.xml

# Крок 2 — постобробка КОРЕНЕВИМ файлом (не tools/!)
python3 epicentr_postprocess.py
# → exports/carvol_epicentr.xml

# Крок 3 — валідація (на ноутбуці через scp)
scp tek@100.82.24.112:/home/tek/agent-system/exports/carvol_epicentr.xml /tmp/
python3 tools/epicentr_xml_checker.py /tmp/carvol_epicentr.xml
# exit 0 = OK, exit 1 = помилки (виправити і повторити)

# Крок 4 — ручне завантаження в merchant.epicentrk.ua → модерація менеджером
```
Детальна послідовність → `.claude/skills/epicentr/SKILL.md`

### Синхронізація цін/наявності (без повного XML)
```bash
python3 agents/orders/carvol_epicentr_sync.py
```

### Замовлення Єпіцентру (daemon)
```bash
# Перевірити що запущений
ps aux | grep epicentr_order_agent | grep -v grep
# Перезапустити (спочатку pkill!)
pkill -f epicentr_order_agent.py
nohup python3 agents/orders/epicentr_order_agent.py > logs/epicentr.log 2>&1 &
```

### PIM: дослідження атрибутів категорії
```bash
python3 tools/epicentr_attrs_explorer.py --category 2848
python3 tools/epicentr_pim_explorer.py --brands   # кеш 54370 брендів
```

## Відомі граблі Єпіцентру

1. **Категорію опублікованого товару НЕ змінити через XML-імпорт** — просити менеджера перенести картки в «Чернетки», тоді імпорт проходить.
2. **`tools/epicentr_postprocess.py` — НЕ використовувати** — відрізняється від кореневого (2883→2874 vs 2883→2848). Пайплайн завжди бере `./epicentr_postprocess.py`.
3. **PIM API `filter[ids][]` не працює** — повертає весь каталог. Перебирати всі сторінки (бренди: 544 стор. × 100 = 54370).
4. **QIV не зареєстровано в Єпіцентрі** → 6110 товарів з vendor=«Інше» (UUID вище). Реєстрація бренду підніме SEO 73→~93. Задача відкрита.
5. **Категорія 4907 видалена** (2026-06-22). Якщо бачиш 4907 в коді — це баг.
6. **Назви файлів XML**: генератор пише `carvol_epicentr_new.xml`, postprocess читає його і пише `carvol_epicentr.xml`. Назви фіксовані.
7. **XML в .gitignore** — `exports/carvol_epicentr.xml` (~42MB) не комітити вручну, авто-синк йде через `carvol_epicentr_sync.py`.
8. **При помилці «Оновлення товарів недоступне»** — звертатись до менеджера Єпіцентру з проханням перенести товари в «Чернетки».

## Перша дія в новій сесії
```
git pull --rebase && cat TASKS.md   # розділ ЄПІЦЕНТР
cat CLAUDE.md                        # формули, valuecodes, категорії
```
Повідомити: «Прочитав CLAUDE.md і TASKS.md (розділ Єпіцентр), чекаю задачі. Перед commit роблю git pull --rebase.»
