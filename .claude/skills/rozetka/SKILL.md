# Rozetka Skills — покрокові інструкції

## SKILL-01: Перевірка стану daemon-процесів (Rozetka + Telegram)

```bash
ssh tek@100.82.24.112

# Перевірити обидва процеси одночасно
ps aux | grep -E 'rozetka_order_agent|tg_dispatcher' | grep -v grep

# Очікуваний вивід — два рядки:
# tek  XXXXX  ... python3 agents/orders/rozetka_order_agent.py
# tek  XXXXX  ... python3 tg_dispatcher/main.py
```

Якщо одного або обох немає — перейти до SKILL-02 або SKILL-03.

---

## SKILL-02: Перезапуск rozetka_order_agent.py

> ⚠️ СПОЧАТКУ pkill — зомбі-процес може висіти тижнями! (Реальний інцидент 17 днів.)

```bash
ssh tek@100.82.24.112
cd /home/tek/agent-system && source venv/bin/activate

pkill -f rozetka_order_agent.py
sleep 3

# Перевірити що зупинився
ps aux | grep rozetka_order_agent | grep -v grep   # має бути порожньо

nohup python3 agents/orders/rozetka_order_agent.py > /tmp/rozetka_order_agent.log 2>&1 &
echo "rozetka_order_agent PID: $!"

# Перевірити що стартував
sleep 2 && ps aux | grep rozetka_order_agent | grep -v grep
tail -20 /tmp/rozetka_order_agent.log
```

---

## SKILL-03: Перезапуск tg_dispatcher/main.py

> ⚠️ Два екземпляри з одним токеном → TelegramConflictError → жоден PDF не доходить.

```bash
ssh tek@100.82.24.112
cd /home/tek/agent-system && source venv/bin/activate

pkill -f tg_dispatcher
sleep 3

# Перевірити що зупинився
ps aux | grep tg_dispatcher | grep -v grep   # має бути порожньо

nohup python3 tg_dispatcher/main.py > /tmp/tg_dispatcher.log 2>&1 &
echo "tg_dispatcher PID: $!"

sleep 2 && ps aux | grep tg_dispatcher | grep -v grep
tail -20 /tmp/tg_dispatcher.log
```

---

## SKILL-04: Pipeline A — оновлення фіду Carvol→Розетка (вручну)

Cron робить це щогодини автоматично. Якщо потрібно запустити вручну:

```bash
ssh tek@100.82.24.112
cd /home/tek/agent-system && source venv/bin/activate

# Обов'язково перед push!
git pull --rebase

python3 agents/orders/rozetka_github_sync.py
# Що робить: читає Carvol live-фід → оновлює ТІЛЬКИ price/stock_quantity/available
#             у data/carvol_rozetka.xml → git commit + push
# Розетка тягне XML сама кожну годину через GitHub raw URL

# Перевірити що закомітилось
git log --oneline -3
```

---

## SKILL-05: Pipeline C — генерація XML Катрана (ноутбук)

> ⚠️ ТІЛЬКИ на ноутбуці `100.126.131.55` — сервер без AVX → exit 132.

```bash
# Підключитись до ноутбука
ssh tekken@100.126.131.55
cd ~/agent-system && source venv/bin/activate

# Варіант 1 — тільки генерація
python3 agents/orders/katran_xml_generator.py
# → data/katran_rozetka.xml

# Варіант 2 — повний пайплайн (generate→validate→merge→push)
python3 tools/katran_pipeline.py

# Перевірити результат
ls -lh data/katran_rozetka.xml
python3 tools/rozetka_xml_validator.py data/katran_rozetka.xml
```

---

## SKILL-06: Валідація XML-фіду Розетки

```bash
# Основний валідатор (ERR/WARN + json+xlsx звіт)
python3 tools/rozetka_xml_validator.py data/carvol_rozetka.xml

# Перевірити конкретне поле
grep -c "<offer " data/carvol_rozetka.xml        # кількість товарів
grep -c "available=\"true\"" data/carvol_rozetka.xml  # в наявності
```

---

## SKILL-07: Перегляд замовлень у БД

```bash
ssh tek@100.82.24.112

# Останні 10 замовлень
docker exec agent_postgres psql -U agentadmin agentdb -c "
  SELECT id, status, recipient_name, city, created_at
  FROM rozetka_processed_orders
  ORDER BY created_at DESC LIMIT 10;"

# Замовлення без ТТН
docker exec agent_postgres psql -U agentadmin agentdb -c "
  SELECT id, recipient_name, created_at
  FROM rozetka_processed_orders
  WHERE ttn IS NULL OR ttn = ''
  ORDER BY created_at DESC LIMIT 20;"

# Статистика по статусах
docker exec agent_postgres psql -U agentadmin agentdb -c "
  SELECT status, count(*) FROM rozetka_processed_orders GROUP BY status;"
```

---

## SKILL-08: Ручне встановлення ТТН через API

Якщо автоматичний tg_dispatcher не спрацював:
```bash
ssh tek@100.82.24.112
cd /home/tek/agent-system && source venv/bin/activate

python3 -c "
from agents.orders.rozetka_order_agent import set_ttn, change_status
order_id = 123456789   # замінити на реальний
ttn = '20 4444 5555 6666'  # замінити на реальний ТТН
result = set_ttn(order_id, ttn)
print('set_ttn:', result)
# Якщо успішно — перевести в доставку
change_status(order_id, 3)
"
```

---

## SKILL-09: Маппінг категорій Катрана

Коли ~55% товарів у DEFAULT (4101 товар без категорії):
```bash
# Перевірити покриття
docker exec agent_postgres psql -U agentadmin agentdb -c "
  SELECT rz_id, count(*) as cnt
  FROM katran_categories
  GROUP BY rz_id
  ORDER BY cnt DESC LIMIT 20;"

# Після UPDATE батьківських категорій — запустити SQL-пропагацію
# (деталі в CLAUDE.md або TASKS.md розділ Катран)
```

---

## SKILL-10: Перевірка логів помилок

```bash
ssh tek@100.82.24.112

# Rozetka order agent
tail -50 /tmp/rozetka_order_agent.log | grep -E "ERROR|WARN|Exception"

# Telegram dispatcher
tail -50 /tmp/tg_dispatcher.log | grep -E "ERROR|WARN|Conflict|Exception"

# Watchdog (загальний health)
tail -30 /tmp/watchdog.log
```
