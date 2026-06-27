# Khoroshop Skills — покрокові інструкції

> ⚠️ Напрямок **НЕ РЕАЛІЗОВАНО**. Цей файл — шаблон, який заповнюється в процесі розробки MVP.
> Поки немає коду — поточна задача: **дослідити формат фіду «Секс Опт»**.

---

## SKILL-01: Дослідження фіду постачальника (ПЕРШИЙ КРОК)

Перш за все — отримати зразок фіду від менеджера постачальника і визначити формат.

### Кроки дослідження
```bash
# 1. Завантажити зразок фіду (URL від постачальника)
# ПОТРЕБУЄ УТОЧНЕННЯ: URL фіду «Секс Опт»
wget -O /tmp/sexopt_sample.xml "FEED_URL_HERE"
# або
curl -o /tmp/sexopt_sample.zip "FEED_URL_HERE"

# 2. Якщо ZIP — розпакувати
cd /tmp && unzip sexopt_sample.zip

# 3. Визначити формат
head -50 /tmp/sexopt_sample.xml   # XML? YML? Інше?

# 4. Порахувати товари
grep -c "<offer\|<product\|<item" /tmp/sexopt_sample.xml

# 5. Переглянути структуру
python3 -c "
import xml.etree.ElementTree as ET
tree = ET.parse('/tmp/sexopt_sample.xml')
root = tree.getroot()
# Вивести першу гілку
def show(el, depth=0):
    print('  ' * depth + el.tag + (' attrs:' + str(el.attrib) if el.attrib else ''))
    for child in list(el)[:3]:
        show(child, depth+1)
show(root)
"
```

### Питання для визначення шаблону генератора
- Формат фіду: `yml_catalog` (як TOPTUL) / `<price><products>` (як Катран) / інший?
- Є ZIP чи пряме URL?
- Є API для замовлень чи тільки XML-фід?
- Яка частота оновлення фіду?

---

## SKILL-02: Шаблон генератора (після отримання фіду)

Залежно від формату — вибрати зразок:

### Якщо формат схожий на Катран (`<price><products><product>`)
```bash
cp agents/orders/katran_xml_generator.py tools/khoroshop_xml_generator.py
# Адаптувати: назву файлу-виходу, парсинг категорій, calc_price
```

### Якщо формат SpreadsheetML/XLSX (як Carvol для Єпіцентру)
```bash
cp tools/carvol_epicentr_generator.py tools/khoroshop_xml_generator.py
# Адаптувати: маппінг колонок, категорії Khoroshop
```

### Структура нового генератора
```python
# tools/khoroshop_xml_generator.py — скелет
import os, sys, math
from loguru import logger

# 1. Завантажити фід (URL або ZIP)
# 2. Розпарсити товари
# 3. Маппінг категорій (нова таблиця khoroshop_categories або supplier_category_mapping)
# 4. calc_price: mark-up (як катран) або gross-up (як єпіцентр)
#    ПОТРЕБУЄ УТОЧНЕННЯ: яка комісія Khoroshop?
# 5. Зібрати XML у форматі який приймає Khoroshop
# 6. Записати у data/khoroshop_*.xml
```

---

## SKILL-03: Додавання категорій в БД

```bash
# Варіант 1 — нова таблиця (рекомендовано для ізоляції)
docker exec agent_postgres psql -U agentadmin agentdb -c "
  CREATE TABLE IF NOT EXISTS khoroshop_categories (
    id SERIAL PRIMARY KEY,
    supplier_category VARCHAR(255),
    khoroshop_category_id VARCHAR(50),
    khoroshop_category_name VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
  );"

# Варіант 2 — розширити існуючу таблицю supplier_category_mapping
docker exec agent_postgres psql -U agentadmin agentdb -c "
  SELECT DISTINCT supplier FROM supplier_category_mapping LIMIT 5;"
# Якщо підходить структура — додати рядки з supplier='khoroshop'
```

---

## SKILL-04: Перевірка age-gate конкурентів (R&D)

> ⚠️ Сайти інтимних товарів часто мають вікові гейти та cookie-стіни.
> Стандартні Playwright-селектори не спрацюють без обробки гейту.

```python
# Тест наявності age-gate (запустити вручну, headless=False для перевірки)
import asyncio
from playwright.async_api import async_playwright

async def check_age_gate(url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(url, wait_until='networkidle', timeout=30000)
        # Перевірити наявність age-gate елементів
        age_gate = await page.query_selector_all(
            '[class*="age"], [id*="age"], button:has-text("18"), '
            'button:has-text("Мені є 18"), [class*="gate"]'
        )
        print(f'Age-gate елементів: {len(age_gate)}')
        cookie_wall = await page.query_selector_all('[class*="cookie"], [id*="cookie"]')
        print(f'Cookie-wall елементів: {len(cookie_wall)}')
        await browser.close()

asyncio.run(check_age_gate('COMPETITOR_URL_HERE'))
```

---

## SKILL-05: Додавання нових ENV-змінних

Коли отримані credentials постачальника — додати в `.env` і `.env.example`:

```bash
# Додати в .env (на сервері)
echo "KHOROSHOP_FEED_URL=URL_ТУТ" >> /home/tek/agent-system/.env
echo "KHOROSHOP_API_TOKEN=TOKEN_ТУТ" >> /home/tek/agent-system/.env

# Додати в .env.example (в репо, без реальних значень)
echo "" >> .env.example
echo "# ── Khoroshop ────────────────────────────────────────────" >> .env.example
echo "KHOROSHOP_FEED_URL=" >> .env.example
echo "KHOROSHOP_API_TOKEN=" >> .env.example
git add .env.example && git commit -m "feat: add khoroshop env template vars"
```

---

## TODO (заповнювати в процесі розробки)

- [ ] Отримати формат фіду «Секс Опт»
- [ ] Отримати документацію API Khoroshop
- [ ] Визначити список категорій Khoroshop
- [ ] Написати `tools/khoroshop_xml_generator.py`
- [ ] Додати `khoroshop_categories` в БД
- [ ] Написати `tools/khoroshop_xml_checker.py`
- [ ] Налаштувати cron або GitHub-синхронізацію
- [ ] Дослідити age-gate конкурентів (окремий R&D)
- [ ] Підключити замовлення (якщо є API)
