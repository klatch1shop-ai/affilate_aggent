# Скіл обходу захисту від парсингу

## Загальні правила
1. Завжди використовувати реальний User-Agent браузера
2. Додавати рандомну затримку між запитами (1-5 секунд)
3. Імітувати людську поведінку (скролінг, затримки кліків)
4. Ротувати IP при блокуванні

## User-Agent ротація
```python
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121.0.0.0",
]
import random
ua = random.choice(USER_AGENTS)
```

## Затримки між запитами
```python
import asyncio, random
await asyncio.sleep(random.uniform(1.5, 4.0))
```

## Обробка блокувань
- 403 Forbidden: змінити IP і User-Agent
- 429 Too Many Requests: пауза 60 секунд
- 503 Service Unavailable: пауза 30 секунд
- CAPTCHA: використати 2captcha API

## Playwright stealth режим
```python
await context.add_init_script(
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)
```

## Ознаки що нас блокують
- Порожній HTML (менше 10KB)
- Redirect на сторінку перевірки
- CAPTCHA в HTML
- HTTP статус 403/429/503
