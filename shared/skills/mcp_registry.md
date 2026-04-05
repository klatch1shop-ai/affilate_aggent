# MCP сервери для нашої системи

## Підключені
- Gmail MCP → читання листів маркетплейсів
- GitHub MCP → контроль версій коду

## Пріоритет підключення
### 1. Bright Data MCP (brightdata.com)
- Навіщо: обхід Cloudflare на Розетці, збір даних конкурентів
- Безплатно: 5000 запитів/місяць
- Підключення: API ключ → .env BRIGHTDATA_API_KEY

### 2. Apify MCP (apify.com)
- Навіщо: готові скрапери Prom, Розетки, моніторинг цін
- Безплатно: 5$/місяць credits стартовий пакет
- Підключення: APIFY_TOKEN → .env

### 3. Zapier MCP (zapier.com)
- Навіщо: автоматичні звіти в Google Sheets, Telegram алерти
- Безплатно: 100 завдань/місяць
- Підключення: через Zapier account

### 4. Google Sheets MCP (офіційний)
- Навіщо: живий dashboard продажів, моніторинг цін
- Безплатно: через Google API
- Підключення: service account JSON → .env

## Як підключити MCP до системи
У файлі orchestrator/orchestrator.py додати секцію mcp_servers
аналогічно до agent_mcp_server.py
