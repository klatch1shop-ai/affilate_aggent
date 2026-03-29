# Скіл інтеграції API

## Обов'язкові елементи
- Timeout на всі HTTP запити (max 30s)
- Retry логіка (3 спроби з паузою)
- Логування запитів і відповідей
- Валідація відповіді перед обробкою

## Структура API клієнта
```python
async with httpx.AsyncClient(timeout=30) as client:
    for attempt in range(3):
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt == 2: raise
            await asyncio.sleep(2 ** attempt)
```
