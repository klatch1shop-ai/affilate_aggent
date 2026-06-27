# Prom Skills — покрокові інструкції

## SKILL-01: Щоденне оновлення цін (Pipeline D)

Cron запускає о 08:00 автоматично. Ручний запуск або перевірка:

```bash
ssh tek@100.82.24.112
cd /home/tek/agent-system && source venv/bin/activate

# Крок 0 — аудит ПЕРЕД оновленням (опціонально, але рекомендовано)
python3 agents/orders/price_audit.py
# Покаже: поточні ціни в БД vs нові розраховані. Перевірити аномалії.

# Крок 1 — оновлення цін
python3 agents/orders/price_updater.py
# Що робить: фід TOPTUL → calc_price(rrc, cpa) → price_history → Prom API
# Лог: logs/price_alerts_YYYYMMDD_HHMMSS.csv, logs/price_audit_YYYYMMDD_HHMMSS.csv

# Перевірити результат
ls -lt logs/price_alerts_*.csv | head -3
```

---

## SKILL-02: Перевірка конфігу ціноутворення

```bash
docker exec agent_postgres psql -U agentadmin agentdb -c "SELECT * FROM price_engine_config;"

# Ключові параметри:
# alert_threshold_pct=20   → алерт при зміні > 20%
# min_price=40             → мінімальна ціна продажу (грн)
# round_to=10              → крок округлення (грн)

# Поточні ціни (view)
docker exec agent_postgres psql -U agentadmin agentdb -c "
  SELECT sku, feed_price, our_price, cpa_rate, is_alert
  FROM v_current_prices
  WHERE is_alert = TRUE
  ORDER BY feed_diff_pct DESC LIMIT 20;"

# Тижневі зміни
docker exec agent_postgres psql -U agentadmin agentdb -c "
  SELECT sku, change_count, alert_count, unavailable_days
  FROM v_weekly_changes
  ORDER BY change_count DESC LIMIT 20;"
```

---

## SKILL-03: Зміна параметра ціноутворення

```bash
# Наприклад, змінити мінімальну ціну з 40 на 50 грн:
docker exec agent_postgres psql -U agentadmin agentdb -c "
  UPDATE price_engine_config SET value='50' WHERE key='min_price';"

# Або змінити поріг алерту:
docker exec agent_postgres psql -U agentadmin agentdb -c "
  UPDATE price_engine_config SET value='15' WHERE key='alert_threshold_pct';"
```

---

## SKILL-04: Перевірка і перезапуск daemon замовлень Prom

```bash
ssh tek@100.82.24.112

# Перевірити
ps aux | grep order_agent_daemon | grep -v grep

# Перезапуск (СПОЧАТКУ pkill!)
pkill -f order_agent_daemon.py
sleep 3
cd /home/tek/agent-system && source venv/bin/activate
nohup python3 agents/orders/order_agent_daemon.py > logs/prom_daemon.log 2>&1 &
echo "PID: $!"

sleep 2 && ps aux | grep order_agent_daemon | grep -v grep
tail -20 logs/prom_daemon.log
```

---

## SKILL-05: Генерація XML каталогу Віктора (авто-запчастини)

```bash
# Потрібен файл catalog.xlsx (від Віктора)
python3 tools/prom_xml_generator.py --no-filter
# → exports/prom_*.xml

# Валідація
python3 tools/prom_validator.py exports/prom_*.xml

# Розподіл tecdoc/manual
python3 tools/prom_tecdoc_splitter.py exports/prom_*.xml

# SEO-аудит
python3 tools/prom_seo_optimizer.py
```

---

## SKILL-06: Аналіз фіду Prom

```bash
# Аналіз структури фіду (що прийшло від постачальника)
python3 tools/prom_feed_converter/scripts/analyze_feed.py

# Маппінг категорій фіду
python3 tools/prom_feed_converter/scripts/category_mapper.py

# Валідатор фіду
python3 tools/prom_feed_converter/scripts/validator.py
```

---

## SKILL-07: Перегляд замовлень Prom у БД

```bash
docker exec agent_postgres psql -U agentadmin agentdb -c "
  SELECT id, status, total_price, created_at
  FROM orders
  ORDER BY created_at DESC LIMIT 10;"

# Статистика по статусах
docker exec agent_postgres psql -U agentadmin agentdb -c "
  SELECT status, count(*), sum(total_price)
  FROM orders
  GROUP BY status;"
```

---

## SKILL-08: Перевірка CPA-ставок Prom

```bash
# Список ставок по категоріях
docker exec agent_postgres psql -U agentadmin agentdb -c "
  SELECT category, cpa_rate FROM prom_cpa_rates
  ORDER BY cpa_rate DESC LIMIT 20;"

# Ставка для конкретної категорії
docker exec agent_postgres psql -U agentadmin agentdb -c "
  SELECT * FROM prom_cpa_rates
  WHERE category ILIKE '%інструмент%';"
```

---

## SKILL-09: Ручний розрахунок ціни

```bash
python3 -c "
from shared.utils.pricing import calc_price, get_prom_cpa

rrc = 1000.0
category = 'ключі та набори ключів'

cpa = get_prom_cpa(category)
price = calc_price(rrc, cpa)
print(f'РРЦ={rrc}, CPA={cpa*100:.1f}%, ціна={price}')
# Формула: mark-up → rrc * (1 + cpa), округлити до 10
# УВАГА: docstring в pricing.py бреше (пише gross-up), але код робить mark-up.
# Рішення: залишити mark-up, не змінювати.
"
```

---

## SKILL-10: Синхронізація категорій Prom API

Якщо `prom_category_name` порожній у `my_products`:
```bash
python3 agents/orders/fetch_prom_categories.py
# Проходить товари через Prom API, заповнює prom_category_name в my_products
# Запускати раз на тиждень або після великого оновлення каталогу
```
