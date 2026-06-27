# Epicentr Skills — покрокові інструкції

## SKILL-01: Генерація і перевірка XML перед імпортом (Pipeline B)

Повна послідовність від прайсу до готового файлу для завантаження в merchant.epicentrk.ua.

### Крок 1 — Генерація (на сервері)
```bash
ssh tek@100.82.24.112
cd /home/tek/agent-system && source venv/bin/activate

# Запустити генератор (читає data/carvol_opt.xml, пише exports/carvol_epicentr_new.xml)
python3 tools/carvol_epicentr_generator.py

# Перевірити вихід
ls -lh exports/carvol_epicentr_new.xml
```
Очікуваний розмір: ~40–45MB. Якщо менший — перевірити кількість товарів у фіді.

### Крок 2 — Постобробка (КОРЕНЕВИЙ файл, не tools/!)
```bash
# На сервері, та ж сесія
python3 epicentr_postprocess.py
# Читає: exports/carvol_epicentr_new.xml
# Пише:  exports/carvol_epicentr.xml
# Що робить: фото-фільтр (8171→7081), дедуп (→7075), рімап 2883→2848, trim назв

ls -lh exports/carvol_epicentr.xml
```
> ⚠️ НЕ запускати `tools/epicentr_postprocess.py` — там 2883→2874 (застаріле).

### Крок 3 — Валідація (на ноутбуці або де є доступ до checker)
```bash
# Скопіювати XML на ноутбук
scp tek@100.82.24.112:/home/tek/agent-system/exports/carvol_epicentr.xml /tmp/carvol_epicentr.xml

# Запустити повний валідатор
python3 tools/epicentr_xml_checker.py /tmp/carvol_epicentr.xml

# exit 0 = OK (готово до завантаження)
# exit 1 = помилки (читати вивід, виправляти і повторювати з кроку 1)
```

### Крок 4 — SEO-скоринг (опціонально, але корисно)
```bash
python3 tools/epicentr_quality_checker.py /tmp/carvol_epicentr.xml
# Очікуваний avg score: 73/100 (поки QIV не зареєстрований)
# --enhance-names   → автоматичне покращення назв
# --fix             → застосувати виправлення
```

### Крок 5 — Ручне завантаження
1. Відкрити `merchant.epicentrk.ua` → Імпорт товарів
2. Завантажити `carvol_epicentr.xml`
3. Дочекатися модерації від менеджера Євгенія Тамбовського (`e.tambovskiy@epicentrk.ua`)

---

## SKILL-02: Синхронізація цін/наявності (без повного XML)

Коли потрібно лише оновити ціни і наявність без повної регенерації:
```bash
ssh tek@100.82.24.112
cd /home/tek/agent-system && source venv/bin/activate
python3 agents/orders/carvol_epicentr_sync.py
# Читає live-фід Carvol → оновлює ЛИШЕ ціни/наявність у exports/carvol_epicentr.xml
```
> Cron щодня 07:00 запускає `feed_sync.py` — перевіряти що він живий.

---

## SKILL-03: Маппінг категорій TOPTUL→Єпіцентр

Коли в `carvol_epicentr_cat_map` не вистачає категорій:
```bash
# Крок 1 — fuzzy-match нових категорій
python3 tools/epicentr_category_mapper.py

# Крок 2 — підтвердити запропоновані маппінги (інтерактивний ANSI UI)
python3 tools/epicentr_confirm_categories.py

# Крок 3 — перевірити таблицю
docker exec agent_postgres psql -U agentadmin agentdb \
  -c "SELECT * FROM carvol_epicentr_cat_map ORDER BY carvol_category;"
```

---

## SKILL-04: Дослідження required-attrs категорії

Коли Єпіцентр відхиляє товари через брак атрибутів:
```bash
# Отримати required attrs для категорії (наприклад 2848 — LED лампи)
python3 tools/epicentr_attrs_explorer.py --category 2848

# Переглянути з БД
docker exec agent_postgres psql -U agentadmin agentdb \
  -c "SELECT * FROM epicentr_required_attrs WHERE category_id = 2848;"

# Заповнити порожні атрибути в xlsx-експорті
python3 tools/epicentr_fill_attributes.py --file /tmp/epicentr_export.xlsx
```

---

## SKILL-05: Перевірка і перезапуск daemon замовлень

```bash
ssh tek@100.82.24.112

# Перевірити що daemon живий
ps aux | grep epicentr_order_agent | grep -v grep

# Якщо не запущений або зависший — перезапустити
pkill -f epicentr_order_agent.py
sleep 3
cd /home/tek/agent-system && source venv/bin/activate
nohup python3 agents/orders/epicentr_order_agent.py > /tmp/epicentr_order_agent.log 2>&1 &
echo "PID: $!"

# Перевірити лог
tail -f /tmp/epicentr_order_agent.log
```

---

## SKILL-06: Перевірка кількості товарів і якості XML

```bash
# Кількість офферів у XML
grep -c "<offer " exports/carvol_epicentr.xml

# Товари по категоріях
grep "<categoryId>" exports/carvol_epicentr.xml | sort | uniq -c | sort -rn

# Товари з фото
grep -c "<picture>" exports/carvol_epicentr.xml

# Товари без фото (офери без <picture>)
python3 -c "
import xml.etree.ElementTree as ET
tree = ET.parse('exports/carvol_epicentr.xml')
no_photo = [o.get('id') for o in tree.findall('.//offer') if not o.findall('picture')]
print(f'Без фото: {len(no_photo)} | Перші: {no_photo[:5]}')
"
```

---

## SKILL-07: Підготовка запиту менеджеру про перенос товарів в «Чернетки»

Потрібно при оновленні вже опублікованих товарів (помилка «Оновлення товарів недоступне»):

**Шаблон листа для `e.tambovskiy@epicentrk.ua`:**
```
Тема: Перенос карток в Чернетки для оновлення

Євгеній, добрий день!

Потрібно перенести товари в статус "Чернетки" для оновлення через імпорт.
Категорія: [назва категорії, наприклад "Автомагнітоли (2866)"]
Кількість товарів: [N]

Після переносу ми завантажимо оновлений XML і товари знову стануть активними.

Дякуємо!
```
