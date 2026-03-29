# Скіл пошуку в інтернеті

## Коли використовувати
- Потрібна актуальна інформація про ціни конкурентів
- Пошук нових постачальників або товарів
- Дослідження трендів ринку
- Перевірка наявності товару
- Пошук технічної документації API

## Інструменти пошуку

### httpx запити до пошукових API
```python
import httpx, asyncio

async def web_search(query: str, num_results: int = 10) -> list:
    # DuckDuckGo Instant Answer API (безкоштовно)
    url = "https://api.duckduckgo.com/"
    params = {
        "q": query,
        "format": "json",
        "no_html": 1,
        "skip_disambig": 1
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        data = resp.json()
        results = []
        for r in data.get("RelatedTopics", [])[:num_results]:
            if "Text" in r:
                results.append({
                    "title": r.get("Text","")[:100],
                    "url": r.get("FirstURL",""),
                    "snippet": r.get("Text","")
                })
        return results

async def fetch_page(url: str) -> str:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 Chrome/122.0.0.0"}) as client:
        resp = await client.get(url)
        return resp.text[:5000]  # перші 5000 символів
```

### SerpAPI (якщо є ключ)
```python
async def serpapi_search(query: str) -> list:
    url = "https://serpapi.com/search"
    params = {
        "q": query,
        "api_key": os.getenv("SERPAPI_KEY",""),
        "gl": "ua",
        "hl": "uk",
        "num": 10
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        results = resp.json().get("organic_results", [])
        return [{"title": r.get("title"), "url": r.get("link"),
                 "snippet": r.get("snippet")} for r in results]
```

## Стратегія пошуку

### Пошук цін конкурентів
1. Запит: "{товар} ціна {маркетплейс} {рік}"
2. Зібрати топ-5 результатів
3. Завантажити сторінки і витягнути ціни
4. Порівняти з нашою ціною

### Пошук постачальників
1. Запит: "{товар} оптом Україна постачальник"
2. Запит: "{товар} dropshipping supplier Ukraine"
3. Зібрати контакти і умови

### Пошук трендів
1. Запит: "{товар} тренд 2025 Україна"
2. Google Trends через pytrends
3. Аналіз частоти пошуку

## Обробка результатів
Завжди:
1. Перевіряти актуальність (дата публікації)
2. Зберігати джерело посилання
3. Логувати в event_logs
4. При знаходженні важливого — створити alert

## Заборонено
- Парсити сайти з captcha без solver
- Робити більше 30 запитів/хвилину
- Зберігати персональні дані користувачів
