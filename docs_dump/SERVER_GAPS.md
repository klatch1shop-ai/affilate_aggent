# SERVER_GAPS.md — чого немає в git (заповнюється вручну з сервера)

> Це чек-ліст того, що існує лише на сервері `tek@100.82.24.112` (`/home/tek/agent-system`) і НЕ потрапило в git.
> Користувач копіює реальні дані з сервера у порожні code-блоки нижче. Документ — для перенесення повного контексту в інший чат/ПК.

---

## 1. Файли на сервері, яких немає в git (.gitignore або не закомічені)
- [ ] `/home/tek/agent-system/.env` — реальні значення всіх ключів (список ключів — у DUMP_ENV_TEMPLATE.md)
- [ ] `/home/tek/agent-system/exports/carvol_epicentr.xml` — поточна жива версія (у git є, але оновлюється авто-синком; звірити mtime)
- [ ] `/home/tek/agent-system/logs/*.log` та `logs/*.pid` — поточні логи/піди
- [ ] лог-файли в `/tmp` (повний перелік output-шляхів, знайдених у коді, — нижче)

### Output-шляхи, що згадані в коді як місця запису (кандидати на «є лише на сервері»):
```
/tmp/ai_xml_gen.log
/tmp/carvol_epicentr_sync.log
/tmp/embedding_service.log
/tmp/epicentr_order_agent.log
/tmp/feed_sync.log
/tmp/katran_github_sync.log
/tmp/katran_sync_cron.log
/tmp/ollama_worker.log
/tmp/rozetka_feed_sync.log
/tmp/rozetka_github_sync.log
/tmp/rozetka_order_agent.log
/tmp/rozetka_sync_cron.log
/tmp/validation_report.json
/tmp/watchdog.log
/tmp/web_explorer.log
logs/checker.log  logs/checker.pid
logs/dashboard.log  logs/dashboard.pid
logs/developer.log  logs/developer.pid
logs/efficiency.log  logs/efficiency.pid
logs/finance.log  logs/finance.pid
logs/marketing.log  logs/marketing.pid
logs/ollama_worker.log  logs/ollama_worker.pid
logs/orchestrator.log  logs/orchestrator.pid
logs/telegram_bot.log
logs/price_alerts_YYYYMMDD_HHMMSS.csv
logs/price_audit_YYYYMMDD_HHMMSS.csv
```
Вивід `ls -la` цих файлів на сервері:
```bash

```

---

## 2. Живий стан БД (PostgreSQL agentdb), якого немає в DDL
- [ ] `SELECT COUNT(*)` по кожній таблиці (реальна кількість рядків)
```bash
# docker exec agent_postgres psql -U agentadmin agentdb -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC;"

```
- [ ] Повний вміст `carvol_epicentr_cat_map`
```bash

```
- [ ] Повний вміст `epicentr_required_attrs`
```bash

```
- [ ] Повний вміст `rozetka_category_mapping`
```bash

```
- [ ] `katran_categories` — статистика покриття rz_id та DEFAULT
```bash

```

---

## 3. Процеси, що зараз реально запущені (миттєвий стан)
- [ ] `ps aux | grep python3`
```bash

```
- [ ] `crontab -l`
```bash

```
- [ ] `docker ps`
```bash

```

---

## 4. Конфігурація, що існує лише на сервері
- [ ] systemd unit-файли проєкту (`/etc/systemd/system/*.service` або `~/.config/systemd/user/*.service`: rozetka-order-agent, epicentr-order-agent, tg-dispatcher, feed-server)
```bash
# systemctl --user list-units | grep -E 'rozetka|epicentr|tg|feed'; cat ~/.config/systemd/user/*.service

```
- [ ] nginx/reverse-proxy конфіги для web_api_explorer (:5555) / ai_xml_generator (:5556) / dashboard (:8888)
```bash

```
- [ ] crontab повний дамп з коментарями
```bash

```

---

## 5. Контент knowledge_base — чи повний у git
- [ ] Звірити `shared/knowledge_base/{epicentr,rozetka,prom}/` git vs сервер (чи є файли поза трекінгом)
```bash
# diff <(git ls-files shared/knowledge_base/) <(cd /home/tek/agent-system && find shared/knowledge_base -type f | sort)

```

---
_Усі code-блоки навмисно порожні — заповнити вручну з сервера._
