# Конкурентний скрейпінг — спільна можливість

> Файл: `shared/knowledge_base/competitor_scraping.md`
> Оновлено: 2026-06-28

## Інструмент

**`tools/epicentr_competitor_scraper.py`** — HTTP-парсер карток конкурентів.

- Тестовано на `epicentrk.ua` — HTTP 200 без Cloudflare з нашого серверного IP (2026-06-28)
- Базовий клас `BaseHttpScraper` реюзабельний для будь-якого SSR-сайту без Cloudflare
- Для Rozetka / Prom / Khoroshop (Cloudflare) потрібен Playwright — використовуй `playwright_base.py`

## Використання

```bash
cd /home/tek/agent-system && source venv/bin/activate

# Пошук за назвою
python3 tools/epicentr_competitor_scraper.py --query "Teyes CC3"

# Пошук + повні картки (ціна, specs, фото)
python3 tools/epicentr_competitor_scraper.py --query "Автомагнітола" --limit 10 --parse-cards

# Парсинг конкретної картки
python3 tools/epicentr_competitor_scraper.py --url "https://epicentrk.ua/ua/shop/....html"

# Без збереження в БД (тест)
python3 tools/epicentr_competitor_scraper.py --query "Carav рамка" --no-save
```

## Що повертає parse_card()

| Поле | Звідки | Приклад |
|------|--------|---------|
| `title` | `<h1>` | "Автомагнітола штатна Teyes CC3 2К..." |
| `price` | `window.dataLayer.push({productPrice:...})` | 26950.0 |
| `vendor` | `dataLayer.vendorName` | "Teyes" |
| `category_id` | `dataLayer.categoryId` | 2866 |
| `category_name` | `dataLayer.categoryName` | "Автомагнітоли" |
| `in_stock` | `dataLayer.productAvailable` | false |
| `external_id` | `dataLayer.productId` | "MP12648297" |
| `specs` | `dl > div > dt + dd` | {"Бренд": "Teyes", "Монтажний розмір": "штатний"...} (19 полів) |
| `photos` | `img[src*="cdn.27.ua"]` | ["https://cdn.27.ua/...jpg", ...] (5-20 фото) |

## Де зберігаються результати

Таблиця `competitor_prices` (PostgreSQL, 2026-06-28 розширена):

```sql
SELECT title, price, vendor, category_name, url, checked_at
FROM competitor_prices
WHERE marketplace = 'epicentr'
ORDER BY checked_at DESC LIMIT 20;
```

| Колонка | Тип | Опис |
|---------|-----|------|
| `marketplace` | varchar(20) | 'epicentr', 'rozetka', 'prom'... |
| `title` | text | Назва товару у конкурента |
| `price` | numeric | Ціна |
| `vendor` | varchar | Бренд |
| `specs_json` | text | JSON з усіма характеристиками |
| `photos_json` | text | JSON-масив URL фото |
| `category_id` | integer | ID категорії маркетплейсу |
| `search_query` | varchar | Пошуковий запит |
| `external_id` | varchar | ID товару на маркетплейсі |

## Адаптація під інший сайт

Для нового HTTP-доступного сайту — успадкуй `BaseHttpScraper` і перевизнач два методи:

```python
class MyMarketplaceScraper(BaseHttpScraper):
    MARKETPLACE = "mymarket"
    SEARCH_URL = "https://mysite.ua/search/?q={query}"

    def search(self, query, max_results=20) -> list[dict]:
        soup = self._get(self.SEARCH_URL.format(query=query))
        # ... твої селектори для пошукових карток
        return results

    def parse_card(self, url) -> dict:
        soup = self._get(url)
        # ... твої селектори для картки товару
        return {...}
```

## Технічні особливості epicentrk.ua

- **SSR:** Nuxt.js server-side render — повний HTML без виконання JS
- **Ціна/бренд:** `window.dataLayer.push({...})` inline JSON в `<script>` — найнадійніше джерело
- **Характеристики:** `dl > div > dt + dd` (не `li`, не `table`)
- **Фото:** `img[src*="cdn.27.ua"]`
- **Пошук:** 40 карток на сторінку, SSR-rendered, `button[data-product-card-action="favorite"]` + `a[data-product-picture]`
- **URL продуктів:** `/ua/shop/mplc-{slug}-{UUID}.html` (штатні) або `/ua/shop/{slug}.html` (звичайні)
- **Увага:** Кирилиця в search query → іноді timeout при першому запиті (retry вбудовано)
