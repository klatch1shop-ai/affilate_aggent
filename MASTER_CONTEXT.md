# Agent System — Повний контекст проекту

## Інфраструктура
- Сервер: 192.168.3.28 (PostgreSQL, Redis, Qdrant, Docker)
- Ноутбук: 192.168.3.24 (Ollama GPU RTX 4050 6GB, Open WebUI)
- Репозиторій: https://github.com/klatch1shop-ai/affilate_aggent
- Сервер шлях: /home/tek/agent-system

## Постачальники
- TOPTUL (Гранд Інструмент): 6871 товарів, знижка 12%, РРЦ ціни
  - Email: rusanov@grandinstrument.ua, opt@grandinstrument.ua
  - Код клієнта: 000160594
  - Фід: оновлення щогодини, SKU в тегу vendorCode
- Carvol: 8244 товарів автоелектроніки
  - XML: https://raw.githubusercontent.com/klatch1shop-ai/affilate_aggent/main/data/carvol_rozetka.xml

## Маркетплейси
### Prom.ua
- Магазин ID: 4053918
- Товарів: 5908 (активні), 12176 відображається з 17703
- ProSale: CPA модель, середня комісія 14.1%
- Автооновлення: кожні 4 год (наявність, без ціни!)
- Баланс: ~325 грн (поповнити!)
- API token: в .env

### Розетка
- Магазин: gomer (seller id)
- Контакт: ivanovskaya@rozetka.ua (Софія)
- Carvol XML: відправлено, очікуємо активацію (2 тижні)
- TOPTUL XML: потрібно генерувати

### Єпіцентр
- 5893 товари в чернетках без категорій
- Контакт: e.tambovskiy@epicentrk.ua (Євгеній)
- Тариф: 120 грн/місяць

## Активні агенти
1. order_agent_daemon.py — systemd, кожні 5 хв
   - Prom нові замовлення → перевірка наявності у фіді
   - підтвердження → Excel → email постачальнику
   - Telegram сповіщення
2. price_updater.py — cron 08:00 щодня
   - Фід → порівняння цін → оновлення БД → Prom API

## Ціноутворення
- Закупка = price_supplier × 0.88 (знижка 12%)
- УВАГА: TOPTUL дає РРЦ в фіді, маржа різна по категоріях
- Формула: min_price = (zakupka + 20) / (1 - CPA) × 1.12
- Очікуємо таблицю маржі від TOPTUL

## БД Таблиці (16)
- my_products — 5908 товарів TOPTUL з цінами
- carvol_products — 8304 товарів
- market_prices — ціни конкурентів
- prom_cpa_rates — 68 категорій Prom
- epicentr_cpa_rates — 236 категорій Єпіцентру
- rozetka_cpa_rates — 16 категорій Розетки (з діапазонами)
- epicentr_categories — 4054 категорії
- rozetka_categories — 37 категорій
- supplier_category_mapping — 384 маппінги
- orders — замовлення з Prom

## Pending задачі
- [ ] Отримати комісії від Prom/Єпіцентру
- [ ] Отримати таблицю маржі від TOPTUL
- [ ] Генерувати TOPTUL XML для Розетки
- [ ] Автоматизація категорій Єпіцентру
- [ ] Price updater для Розетки/Єпіцентру
- [ ] Поповнити баланс Prom!
- [ ] Підключити ТТН до замовлень

## Telegram Bot
- @agent_system_TEKKEN_bot
- TELEGRAM_BOT_TOKEN в .env
- TELEGRAM_ADMIN_ID в .env

## Важливі файли
- agents/orders/order_agent.py — основний агент
- agents/orders/order_agent_daemon.py — daemon
- agents/orders/price_updater.py — оновлення цін
- agents/scraper/category_classifier.py — AI класифікатор категорій
- data/carvol_rozetka.xml — XML для Розетки
- shared/skills/ — 35 skills файлів
- shared/knowledge_base/ — документація маркетплейсів
