# Agent System — Автономна мережа ШІ агентів

## Що це
Мультиагентна система автоматизації дропшипінг-бізнесу на маркетплейсах України.
Керується через Telegram або веб-дашборд. Працює локально на Ubuntu.

## Архітектура
- **Оркестратор** — приймає команди, розподіляє задачі між агентами через LLM
- **Marketing агент** — Google Trends, аналіз конкурентів, пошук товарів
- **Finance агент** — розрахунок маржі, курс USD, тижневі звіти
- **Efficiency агент** — моніторинг системи, виявлення аномалій
- **Developer агент** — генерація коду під задачі системи
- **Scraper агент** — підготовлений під Prom/Rozetka API

## Технічний стек
Python 3.12 · LangChain · Ollama (LLM локально) · FastAPI
PostgreSQL · Redis · Qdrant · Docker · Telegram Bot API · MCP Protocol

## Запуск
```bash
# 1. Встановити залежності
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Запустити Docker сервіси
docker compose up -d

# 3. Встановити Ollama + модель
ollama pull dolphin-llama3

# 4. Налаштувати .env (токени Telegram, API ключі)
nano .env

# 5. Запустити всіх агентів
./start_all.sh
```

## Інтерфейси
| Сервіс | Адреса |
|--------|--------|
| Web Dashboard | http://localhost:8888 |
| Telegram Bot | @agent_system_TEKKEN_bot |
| Adminer (БД) | http://localhost:8080 |
| n8n автоматизація | http://localhost:5678 |
| Grafana моніторинг | http://localhost:3000 |

## Статус розробки
✅ Інфраструктура · ✅ Оркестратор · ✅ 5 агентів
✅ Telegram бот · ✅ Web Dashboard · ✅ MCP сервер
🔜 Google API · 🔜 n8n workflows · 🔜 Scraper API
