# Що працює насправді

Карта запущеного. **Змінив щось — виправ тут же.** Рішення власника
07.10.2026: без цього логіка розходиться між двома місцями, і виправлення в
одному не доходить в інше.

Цей файл відповідає на «що зараз запущено». На «куди йдемо і що відкрито» —
[напрями](напрями/README.md). На «що в коді» — [АУДИТ_КОДУ](АУДИТ_КОДУ.md).

**Не переписувати руками те, що вміє порахувати машина:**

```
venv/bin/python tools/system_audit.py            # усе
venv/bin/python tools/system_audit.py --sync      # ноутбук ↔ сервер
venv/bin/python tools/system_audit.py --runtime   # що запущено
```

Останній прогін: 10.10.2026. Усе нижче **перевірено запуском**.

---

## 1. Де що живе
| | |
|---|---|
| сервер | `tek@192.168.3.28`, `/home/tek/agent-system` |
| ноутбук | `/home/tekken/agent-system` |
| історія | GitHub `klatch1shop-ai/affilate_aggent`, гілка `main` |

Сервер **сам комітить і сам пушить** (записи `sync: …`). Тому перед роботою
на ноутбуці — `git pull`, інакше історії розійдуться; 10.10 так назбиралось
32 коміти з одного боку і 21 з іншого.

Теки `exports/ data/ output/ logs/ scratchpad/` у git **не тримаємо** —
сервер їх перегенеровує (рішення власника 10.10).

## 2. Постійні служби (systemd --user на сервері)
| служба | що запускає | призначення |
|---|---|---|
| `rozetka-order-agent` | `agents/orders/rozetka_order_agent.py` | замовлення Rozetka: Carvol, NOIRE, TOPTUL |
| `helper-bot` | `helper_bot/main.py` | бот власника: чати покупців, команди, СУПЕРБОТ |
| `tg-dispatcher` | `tg_dispatcher/main.py` | канал VSCODE ↔ Telegram |
| `noire-notifier` | `agents/orders/noire_order_notifier.py` | сповіщення по замовленнях Єпіцентру |
| `feed-server` | `python -m http.server 8080` у `shared/feeds` | **віддає файли НАЗОВНІ** через tailscale funnel |
| `epicentr-order-agent` | `agents/orders/epicentr_order_agent.py` | **спірна** — дропшипінг TOPTUL на Єпіцентрі |

`epicentr-mcp.service` існує, але не запущена.

### Про `feed-server` і відкритий порт
`https://usa1.tail3a617f.ts.net` доступний з інтернету. Він **потрібен**:
`rozetka_order_agent.py:859` саме так віддає Carvol посилання на бланк
замовлення (`/orders/<файл>.xlsx`).

10.10 виявлено, що тека горталася — будь-хто бачив перелік усіх 87 бланків
із іменами, телефонами й адресами покупців, і в журналі вже є сканування
ботами (`wp-includes`, `xmlrpc.php`). Поставлено `index.html` у
`shared/feeds/`, `shared/feeds/orders/` і `orders/np_ttn/` — перелік
зник, прямі посилання для Carvol працюють (перевірено: 200).
**Лишається відкритим:** назви файлів угадувані (`rozetka_order_<id>_<дата>`).

### Про `epicentr-order-agent`
Працює 53 доби, кожні 5 хвилин: «OMS віддав 13 замовлень, справді нових 0».
Написаний під **дропшипінг TOPTUL на Єпіцентрі**, а TOPTUL там цього року не
активується і живе лише на Rozetka. Замовлення Єпіцентру веде
`tools/epicentr_order_pipeline.py` з cron. Тобто служба або нічого не
робить, або зробить не те. Такий самий випадок уже був на Prom
(`order_agent_daemon.py`, зупинено 07.10). **Чекає рішення власника.**

## 3. Розклад (cron, 21 запис)
**Замовлення**
| коли | що |
|---|---|
| `*/20` | `noire_order_pipeline.py --auto` — NOIRE на Rozetka |
| `10,30,50` | `epicentr_order_pipeline.py --auto` — Єпіцентр |
| `5,25,45` | `prom_order_pipeline.py --auto` — NOIRE на Prom |
| `0 21` | `toptul_ttn_reconcile.py --write` — звірка ТТН «Гранд Інструменту» |
| `5 10,16` | `orders_need_invoice.py --notify` — нагадування про рахунок |

Хвилини розведені навмисно: кошик у CRM постачальника **один на акаунт**.

**Фіди й наявність**
| коли | що |
|---|---|
| `20 * * * *` | `noire_stock_sync.py --publish-rozetka` |
| `25 */2` | `noire_stock_sync.py --publish-epicentr-stock` |
| `40 7,11,15,19` | `noire_stock_sync.py --publish-prom` |
| `5 */2` / `30 6` | `noire_stock_sync.py --quick` / `--full` |
| `35 * * * *` | `feed_stock_sync.py --profile toptul` |
| `45 * * * *` | `feed_stock_sync.py --profile dropoffice` |
| `25 */3` | `feed_freshness_watch.py --notify` — сторож свіжості |
| `0 7` / `0 8` / `15 7` / `30 7` | `feed_sync`, `price_updater`, `rozetka_github_sync`, `carvol_epicentr_sync` |

**Обслуговування**
`*/10` `watchdog.py` · `0 4` `ops/run_pg_backup.py` · `20 4 1 * *` `git gc`
· `15 4 3 10 *` `prom_marker_check.py --api`

## 4. Де лежить стан
| що | де |
|---|---|
| конвеєр NOIRE / Єпіцентр / Prom | `logs/*_pipeline_state.json` |
| замовлення Rozetka | таблиця `rozetka_processed_orders` |
| замовлення TOPTUL | таблиця `toptul_supplier_orders` |
| зіставлення з Єпіцентром | таблиця `epicentr_sku_mapping` (5020) |
| зріз карток Єпіцентру | `data/epicentr_products.json`, `tools/epicentr_products_dump.py` |
| бланки для Carvol | `shared/feeds/orders/` |

Замок на кошик CRM: `logs/smtm_cart.lock` — поки **лише** в
`prom_order_pipeline.py`. Щоб захищав, ті самі два рядки потрібні в
`noire_` та `epicentr_pipeline`; це зміна в NOIRE і чекає дозволу.

## 5. Постачальники за майданчиками
| майданчик | постачальники |
|---|---|
| Rozetka | NOIRE, Carvol, TOPTUL, KATRAN (фід не подано), dropoffice |
| Єпіцентр | лише NOIRE (TOPTUL і Carvol спять) |
| Prom | лише NOIRE |
| EVA | фіду ще немає |

Зіставляти товари Єпіцентру **тільки** через `epicentr_sku_mapping`.

## 6. Відоме несправне
| що | стан |
|---|---|
| `rozetka-order-agent` бачить замовлення 908328616 «новим» щоп'ять хвилин | оброблене (`accepted` 09.10), але поле `ttn` у нас порожнє, тому відбір не відпускає його |
| `epicentr-order-agent` | працює 53 доби вхолосту, написаний під інший сценарій |
| назви бланків у `shared/feeds/orders/` | угадувані |
| 81 файл покинутої архітектури | див. [АУДИТ_КОДУ](АУДИТ_КОДУ.md) |
