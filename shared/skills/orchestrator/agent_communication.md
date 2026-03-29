# Скіл комунікації між агентами

## Протокол передачі задач (через Redis)

### Формат задачі
```json
{
  "type": "task_type",
  "description": "детальний опис що зробити",
  "priority": 8,
  "source": "orchestrator",
  "context": {
    "related_products": [],
    "marketplace": "rozetka",
    "budget": 10000
  },
  "timestamp": "2024-01-01T00:00:00"
}
```

### Черги агентів
- queue:orchestrator — команди від адміна
- queue:scraper — задачі парсингу
- queue:marketing — аналіз і тренди
- queue:finance — фінансові розрахунки
- queue:developer — написання коду
- queue:efficiency — моніторинг

## Правила комунікації
1. Оркестратор НІКОЛИ не виконує задачі сам
2. Кожна задача має чіткий тип і опис
3. Результат повертається через event_logs і alerts
4. При помилці агент створює alert і повертає статус idle
5. Пріоритет 10 = критично, 1 = низький

## A2A протокол (Agent-to-Agent)
Агенти можуть запитувати допомогу один в одного:
- Marketing → Finance: перевірити маржу знайденого товару
- Scraper → Developer: потрібен новий парсер для сайту
- Efficiency → Orchestrator: агент не відповідає

## Snapshot стану системи
Оркестратор зберігає в Redis ключ "system:snapshot":
```json
{
  "goal": "поточна ціль",
  "agents": {"marketing": "idle", "scraper": "busy"},
  "last_update": "timestamp",
  "active_tasks": 2,
  "today_completed": 15
}
```
