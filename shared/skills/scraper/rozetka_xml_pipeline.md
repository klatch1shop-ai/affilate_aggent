# Повний пайплайн підготовки XML для Розетки

## Коли використовувати
При отриманні нового посилання на фід постачальника. Агент виконує всі кроки автономно до отримання валідного XML (0 помилок, 0 попереджень у валідаторі Розетки).

## КРОК 1 — Завантаження та аналіз фіду

```python
# Завантажити фід
wget -q -O data/supplier_feed.xml "URL_ПОСТАЧАЛЬНИКА"

# Проаналізувати структуру
from xml.etree import ElementTree as ET
tree = ET.parse('data/supplier_feed.xml')
root = tree.getroot()
shop = root.find('shop')
offers = shop.find('offers').findall('offer')

# Обов'язково перевірити:
# 1. Кількість товарів
# 2. Наявність полів: price, pictures, vendor, stock_quantity, params
# 3. Унікальні категорії (categoryId)
# 4. Унікальні бренди (vendor)
# 5. Товари з нульовою ціною
# 6. Товари без фото
# 7. Товари без параметрів
```

## КРОК 2 — Імпорт в БД

Створити таблицю для постачальника:
```sql
CREATE TABLE IF NOT EXISTS supplier_products (
    id SERIAL PRIMARY KEY,
    external_id VARCHAR(255) UNIQUE,
    article VARCHAR(255),
    name_ua TEXT,
    description_ua TEXT,
    vendor VARCHAR(100),
    price DECIMAL(12,2),
    category_id VARCHAR(50),
    pictures JSONB,
    params JSONB,
    stock_quantity INTEGER DEFAULT 0,
    available BOOLEAN DEFAULT true,
    has_params BOOLEAN DEFAULT false,
    status VARCHAR(20) DEFAULT 'new',
    imported_at TIMESTAMP DEFAULT NOW()
);
```

### Правила імпорту:
- `vendorCode` або `article` → поле `article` (SKU)
- Виправляти URL фото: Prom CDN `images.prom.ua/XXXXX_k` → `images.prom.ua/XXXXX_b.jpg`
- Робити назви унікальними (додавати артикул якщо дублюється)
- Очищати описи від HTML тегів
- Параметри: `param name=` → dict {name: value}
- `has_params = len(params) >= 3`

## КРОК 3 — Перевірка якості даних

```python
# Обов'язкові перевірки після імпорту:
checks = {
    'без_ціни': 'SELECT COUNT(*) FROM t WHERE price = 0',
    'без_фото': 'SELECT COUNT(*) FROM t WHERE pictures = \'[]\' OR pictures IS NULL',
    'без_params': 'SELECT COUNT(*) FROM t WHERE has_params = false',
    'без_vendor': 'SELECT COUNT(*) FROM t WHERE vendor IS NULL OR vendor = \'\'',
    'без_name': 'SELECT COUNT(*) FROM t WHERE name_ua IS NULL OR name_ua = \'\'',
    'дублі_назв': 'SELECT COUNT(*) FROM (SELECT name_ua, COUNT(*) FROM t GROUP BY name_ua HAVING COUNT(*) > 1) x',
}
```

### Критичні проблеми (блокують публікацію):
- Ціна = 0 → вилучити або виправити
- Без фото → вилучити
- Без назви → генерувати з article
- Без vendor → визначити з назви або поставити дефолтний
- Дублі назв → додати артикул в кінець назви

## КРОК 4 — Виправлення назв

```python
import re

def fix_name(name: str, article: str) -> str:
    # Видалити "серії БРЕНД"
    name = re.sub(r'\s+серії\s+\w+', '', name)
    # (truck) → для вантажівок
    name = name.replace('(truck)', 'для вантажівок')
    # Прибрати розділові знаки (крім дужок і дефісів в моделях)
    name = re.sub(r'[,.](?!\d)', '', name)
    # Зайві пробіли
    name = re.sub(r'\s+', ' ', name).strip()
    # Перша велика
    name = name[0].upper() + name[1:] if name else name
    return name[:255]
```

### Правило унікальності:
```python
names_seen = set()
def make_unique(name: str, article: str) -> str:
    if name in names_seen:
        name = f"{name} ({article})"
    names_seen.add(name)
    return name
```

## КРОК 5 — Генерація параметрів з назви

Якщо товар має < 3 параметрів — генерувати з назви:

```python
# Обов'язкові параметри для будь-якого товару:
params = {
    'Бренд': vendor,
    'Країна-виробник': 'Китай',  # або з опису
}

# Додаткові з назви:
# Тип товару (перше слово або ключове слово)
# Сумісність (марка авто якщо є в назві)
# Діагональ (число + дюймів/")
# Роздільна здатність (NNNxNNN)
# Колір

# Якщо після regex < 3 параметрів → використати Ollama:
# model = "aya-expanse:8b"  ← краща для української мови
```

## КРОК 6 — Переклад параметрів рос→укр

```python
PARAM_TRANSLATIONS = {
    'Тип камеры': 'Тип',
    'Тип сигнала': 'Тип сигналу',
    'Розподільча здатність': 'Роздільна здатність',
    'Дополнительные функции': 'Додаткові функції',
    'Автономное питание': 'Автономне живлення',
    'Количество камер': 'Кількість камер',
    'Операционная система': 'Операційна система',
    'Совместимость с маркой': 'Сумісність з маркою',
    'Совместимость с моделью': 'Сумісність з моделлю',
    'Состояние': 'Стан',
    'Марка': 'Бренд',
    # Значення параметрів:
    'Реверсивная': 'Реверсивна',
    'Отвертка': 'Викрутка',
    'Универсальная': 'Універсальна',
    'Многокомпонентный': 'Багатокомпонентний',
    'Со сменными насадками': 'Зі змінними насадками',
}
```

## КРОК 7 — Маппінг категорій → Розетка

### Як знайти правильний rz_id:
1. Відкрити rozetka.com.ua
2. Знайти категорію для товару
3. ID в URL після `/c` → це і є rz_id

### Правила маппінгу:
- НЕ використовувати батьківські категорії (стоп-категорії)
- Перевірити чи категорія не є стоп-категорією через валідатор
- Якщо стоп-категорія → знайти підкатегорію
- Приклад: Автомагнітоли (275389) — СТОП → Штатні головні пристрої (166828)

### Відомі стоп-категорії:
- 275389 — Автомагнітоли (батьківська)

## КРОК 8 — Генерація XML

### Обов'язкові теги:
```xml
<offer id="SKU" available="true">
  <price>999</price>
  <currencyId>UAH</currencyId>
  <categoryId>1</categoryId>
  <picture>https://...</picture>      <!-- мін 1, макс 15 -->
  <vendor>Бренд</vendor>              <!-- ОБОВ'ЯЗКОВО -->
  <article>SKU</article>
  <stock_quantity>10</stock_quantity>
  <name>Назва товару</name>           <!-- ОБОВ'ЯЗКОВО -->
  <name_ua>Назва товару</name_ua>     <!-- ОБОВ'ЯЗКОВО -->
  <description_ua><![CDATA[<p>Опис</p>]]></description_ua>
  <param name="Бренд">QIV</param>
  <param name="Країна-виробник">Китай</param>
  <!-- мін 3 параметри -->
</offer>
```

### Обов'язкова обробка спецсимволів:
```python
def escape_xml(text: str) -> str:
    return (str(text)
        .replace('&', '&amp;')
        .replace('"', '&quot;')
        .replace("'", '&apos;')
        .replace('<', '&lt;')
        .replace('>', '&gt;'))
```

## КРОК 9 — Валідація

URL валідатора: https://seller.rozetka.com.ua/gomer/pricevalidate/check/index

### Критерії успіху:
- Товарів з помилками: 0
- Товарів з попередженнями: 0
- Категорій з помилками: 0
- Файл валідний: ТАК

### Якщо є помилки — повернутись до відповідного кроку:
- "Тег name обязателен" → Крок 8 (додати name)
- "Тег vendor обязателен" → Крок 6 (виправити vendor)
- "Категория в списке стоп-категорий" → Крок 7 (замінити rz_id)
- "Нет фото" → Крок 3 (вилучити товар)

## КРОК 10 — Публікація на GitHub

```bash
git add -f data/supplier_rozetka.xml
git commit -m "feat: supplier XML validated 0 errors"
git push origin main
```

Посилання для Розетки:
`https://raw.githubusercontent.com/klatch1shop-ai/affilate_aggent/main/data/supplier_rozetka.xml`

## ВАЖЛИВО — досвід з реальних перевірок

### Помилки що були в наших прайсах:
1. Спецсимволи не замінені → escape_xml() на всі поля
2. Фото Prom CDN не відкриваються → перетворювати URL
3. Ціна = 0 → вилучати такі товари
4. Всі товари в одній категорії → правильний маппінг
5. Відсутній vendor → визначати з назви
6. Дублі назв → робити унікальними
7. Тільки name_ua без name → додавати обидва теги
8. Параметри на рос. мові → перекладати

### Модель для генерації описів:
- `aya-expanse:8b` — найкраща для української мови
- `llama3.2:3b` — НЕ використовувати (змішує мови)

### Швидкість обробки:
- Regex параметри: миттєво (8000 товарів за 8 сек)
- Ollama описи: ~2 сек/товар (5000 товарів = ~3 год)
