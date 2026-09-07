# TOOLS_CATALOG.md — повний реєстр скриптів репозиторію

> Репо: `github.com/klatch1shop-ai/affilate_aggent`, гілка `main`, аналіз станом на коміт `2ef4fa3` (2026-06-27).
> Включено **кожен** виконуваний `.py`/`.sh` (крім `__pycache__`, `*.bak`/`*.bak2`, venv, `__init__.py`).
> Колонки: **Шлях · Категорія · Що робить (з реального коду) · Останній коміт (дата · автор · subject) · Запуск зараз · Імпортує (внутрішні модулі)**.
> Категорії: `generator` (будує XML/фіди), `checker` (валідація), `daemon` (постійний цикл), `cron`, `scraper`, `utility`, `library` (тільки імпортується), `migration`, `one-off`, `test`.

---

## agents/orders/ — операційне ядро

### Активно працює (daemon / cron / регулярно вручну)
| Шлях | Кат. | Що робить | Останній коміт | Запуск | Імпортує |
|------|------|-----------|----------------|--------|----------|
| `rozetka_order_agent.py` | daemon | poll замовлень Розетки кожні 300 с; `confirm_order`→Excel(xlsxwriter)→TG Carvol→`save_to_db`; `set_ttn`/`change_status`/`cancel_order`; `verify=False` | 2026-06-25 · klatch1shop-ai · fix waiting_payment retry | daemon (systemd/nohup) | `shared.utils.db` |
| `epicentr_order_agent.py` | daemon | poll OMS Єпіцентру; перевірка наявності у фіді TOPTUL; confirm→Excel→`opt@grandinstrument.ua` | 2026-05-26 · Tekken | daemon | `shared.utils.db` |
| `order_agent_daemon.py` | daemon | нескінченний цикл обробки замовлень Prom з watchdog-перезапуском | 2026-05-16 · Tekken | daemon (systemd) | — (логіка `order_agent`) |
| `rozetka_github_sync.py` | cron | оновлює ЛИШЕ `<price>`/`<stock_quantity>`/`available` у `data/carvol_rozetka.xml`, git commit+push | 2026-06-14 · Tekken · auto watchdog sync | cron `0 * * * *` | — |
| `feed_sync.py` | cron | синхр. наявності/цін Єпіцентру з фіду TOPTUL, генерує XML | 2026-06-11 · Tekken · simplify git push | cron `0 7 * * *` | `shared.utils.db` |
| `price_updater.py` | cron | щоденне оновлення цін Prom: фід→`calc`→`price_history`→Prom API | 2026-06-09 · klatch1shop-ai | cron `0 8 * * *` | `shared.utils.db`, `shared.utils.pricing` |
| `carvol_epicentr_sync.py` | cron/daemon | оновлює лише ціни/наявність у `exports/carvol_epicentr.xml` з live-фіду Carvol | 2026-06-14 · klatch1shop-ai · daily sync | daily | — |
| `katran_github_sync.py` | cron | `katran_xml_generator.main()`→git push `data/katran_rozetka.xml` (з `git pull --rebase`) | 2026-06-07 · klatch1shop-ai | cron (план), **ноутбук** | — |
| `price_engine.py` | library/cli | головний двигун ціноутворення (РРЦ→ціна по CPA); викликається `price_updater`/`price_audit` | 2026-05-23 · Tekken | імпорт + CLI | `shared.utils.db`, `shared.utils.pricing` |
| `np_api.py` | library | Nova Poshta API: `get_ttn_info`, `match_order_by_np_data` (3-рівневий матчинг) | 2026-05-29 · Tekken | імпорт (tg_dispatcher) | `shared.utils.db` |
| `ttn_pdf_parser.py` | library | парсинг PDF накладних НП (regex ТТН, ім'я, місто), fuzzy-матчинг | 2026-05-29 · Tekken | імпорт (tg_dispatcher) | `shared.utils.db` |
| `order_agent.py` | library | логіка замовлень Prom (підтвердження, Excel, email) | 2026-05-25 · Tekken · fix parse_price 1000грн | імпорт (daemon) | `shared.utils.db` |
| `katran_xml_generator.py` | generator | фід Катрана (ZIP→XML `<price><products>`) → Розетка YML; `calc_price` mark-up | 2026-06-07 · klatch1shop-ai · vendor 'Без бренду' | вручну (ноутбук) | — |

### Вручну / періодично
| Шлях | Кат. | Що робить | Останній коміт | Запуск | Імпортує |
|------|------|-----------|----------------|--------|----------|
| `rozetka_price_manager.py` | utility | `--generate`/`--apply`: корекція % від РРЦ, XML+CSV | 2026-06-14 · klatch1shop-ai | вручну CLI | — |
| `rozetka_price_corrector.py` | utility | читає `data/margin_analysis_6k.csv` → оновлює ціни ≥6000 грн через API (`--dry-run`) | 2026-06-14 · klatch1shop-ai | вручну CLI | — |
| `price_audit.py` | utility | аудит: поточні ціни БД vs нові розраховані | 2026-05-23 · Tekken | вручну CLI | `shared.utils.db`, `shared.utils.pricing` |
| `fetch_prom_categories.py` | one-off | проходить товари через Prom API, зберігає `prom_category_name` в `my_products` | 2026-05-23 · Tekken | разово + щотижня | `shared.utils.db` |
| `rozetka_feed_sync.py` | generator | альт. генератор Розетка-XML (структура з `carvol_rozetka.xml` + live-ціни) | 2026-05-26 · Tekken | вручну | `shared.utils.db` |
| `epicentr_xml_generator.py` | generator | TOPTUL→Єпіцентр XML за шаблоном `template (5).xml` (формат `yml_catalog`) | 2026-05-24 · Tekken | вручну | `shared.utils.db` |

---

## tools/ — інструменти генерації/перевірки

### Активно (актуальні пайплайни)
| Шлях | Кат. | Що робить | Останній коміт | Запуск | Імпортує |
|------|------|-----------|----------------|--------|----------|
| `carvol_epicentr_generator.py` | generator | прайс Carvol (SpreadsheetML)→Єпіцентр XML; 5 категорій; детект 394 марок авто; ціна **gross-up** | 2026-06-22 · klatch1shop-ai · merge 4907→2866 | вручну (сервер) | `shared.utils.db` |
| `epicentr_xml_checker.py` | checker | повна валідація XML перед імпортом (структура/дублі/params/фото), exit 0/1 | 2026-06-22 · klatch1shop-ai · merge 4907→2866 | вручну (ноут) | — |
| `epicentr_quality_checker.py` | checker | SEO-скоринг (avg 73/100), `--enhance-names`, `--fix` | 2026-06-13 · Tekken · auto sync | вручну | `shared.utils.db` |
| `epicentr_pim_explorer.py` | utility | PIM API: бренди/країни/категорії, кеш 54370 брендів | 2026-06-13 · Tekken · auto sync | вручну | — |
| `epicentr_attrs_explorer.py` | utility | дискавері required-attrs категорій з PIM API | 2026-06-14 · klatch1shop-ai | вручну | — |
| `epicentr_category_mapper.py` | utility | fuzzy-match категорій TOPTUL→Єпіцентр (404/404) | 2026-06-03 · Tekken | вручну | `shared.utils.db` |
| `epicentr_confirm_categories.py` | utility | підтвердження маппінгу категорій (ANSI-кольори) | 2026-06-03 · Tekken | вручну | `shared.utils.db` |
| `epicentr_fill_attributes.py` | utility | заповнює порожні `*`-колонки xlsx-експорту (EAN-13 та ін.) | 2026-06-07 · Tekken | вручну | — |
| `prom_xml_generator.py` | generator | XLSX каталог Віктора→Prom XML (`--no-filter`, OEM-код у назві) | 2026-06-18 · klatch1shop-ai | вручну | — |
| `prom_validator.py` | checker | валідація Prom XML/XLSX | 2026-06-09 · klatch1shop-ai | вручну | — |
| `prom_tecdoc_splitter.py` | utility | розподіл товарів Prom на tecdoc/manual | 2026-06-09 · klatch1shop-ai | вручну | — |
| `prom_seo_optimizer.py` | utility | SEO-аудит товарів Prom | 2026-04-05 · klatch1shop-ai | вручну | — |
| `katran_category_xml.py` | generator | XML по конкретних rz_id, 3 проходи + фільтри уцінок/б.в./аксесуарів | 2026-06-08 · klatch1shop-ai · VAL-67764 | вручну | — |
| `katran_pipeline.py` | generator | повний цикл generate→validate→merge→(push) | 2026-06-07 · klatch1shop-ai | вручну | — |
| `rozetka_xml_validator.py` | checker | універсальний валідатор YML-XML (ERR/WARN, json+xlsx звіт) | 2026-06-07 · klatch1shop-ai | вручну | — |
| `supplier_onboarding.py` | utility | інтерактивний wizard підключення постачальника (7 кроків, `--resume`) | 2026-06-07 · klatch1shop-ai | вручну CLI | — |
| `watchdog.py` | cron | health-моніторинг + **локальний** git commit (без push) | 2026-06-13 · klatch1shop-ai · no git push | cron `*/10` | — |
| `web_api_explorer.py` | daemon | Flask веб-UI тесту API маркетплейсів (порт **5555**) | 2026-06-16 · klatch1shop-ai | daemon (nohup) | — |
| `ai_xml_generator.py` | daemon | Flask AI-генератор XML для будь-якого маркетплейсу (порт **5556**) | 2026-06-14 · klatch1shop-ai | daemon (nohup) | — |
| `competitor_scraper.py` | scraper | парсинг товарів продавця на Rozetka (Playwright)→`competitor_products` | 2026-04-05 · klatch1shop-ai | вручну CLI | `shared.utils.db` |
| `prom_feed_converter/scripts/analyze_feed.py` | utility | аналіз структури Prom-фіду | 2026-06-11 · klatch1shop-ai | вручну | — |
| `prom_feed_converter/scripts/category_mapper.py` | utility | маппінг категорій Prom | 2026-06-02 · Tekken | вручну | `shared.utils.db` |
| `prom_feed_converter/scripts/validator.py` | utility | валідатор у складі prom_feed_converter | 2026-06-02 · Tekken | вручну | `shared.utils.db` |

### Дубль / legacy
| Шлях | Кат. | Що робить | Останній коміт | Запуск | Примітка |
|------|------|-----------|----------------|--------|----------|
| `epicentr_postprocess.py` (tools/) | generator | **ДУБЛЬ** кореневого; тут `2883→2874` (Автосвітло) | 2026-06-16 · klatch1shop-ai | НЕ використовується пайплайном | пайплайн бере кореневий `epicentr_postprocess.py` (`2883→2848`) — версії розійшлись |
| `fix_rozetka_xml.py` | utility | виправляє `price.xml` під вимоги Розетки (стара чистка 3124 товарів) | 2026-04-05 · klatch1shop-ai | вручну/legacy | імовірно витіснений `rozetka_xml_validator.py` |

---

## agents/scraper/ — скрейпінг і імпорт (деталі див. `docs/SCRAPING.md`)

### Активно / періодично
| Шлях | Кат. | Що робить | Останній коміт | Запуск | Імпортує |
|------|------|-----------|----------------|--------|----------|
| `playwright_base.py` | library | базовий клас Playwright: self-healing, сесії в `browser_sessions`, скріншоти, TG-алерти, anti-bot | 2026-05-23 · Tekken | імпорт (`epicentr_cabinet`, `browser_mcp`) | `shared.utils.db` |
| `epicentr_cabinet.py` | scraper | кабінет Єпіцентру (`admin.epicentrm.com.ua`): логін, скачування/завантаження XLS, перехоплення API→`epicentr_sku_mapping` | 2026-05-23 · Tekken | вручну/MCP | `playwright_base`, `shared.utils.db` |
| `market_price_analyzer.py` | scraper | ціни конкурентів з `prom.ua/ua/search` (Playwright sync)→`market_prices` | 2026-05-09 · Tekken | вручну | `shared.utils.db` |
| `category_classifier.py` | utility | AI-класифікатор категорій (Ollama `qwen2.5:7b` + DIRECT_MAP + БД), оновлює `my_products` | 2026-05-24 · Tekken | вручну | `shared.utils.db` |
| `carvol_category_map.py` | library | статичний словник маппінгу категорій Prom→Розетка | 2026-05-09 · Tekken | імпорт | — |

### Legacy / one-off / dev
| Шлях | Кат. | Що робить | Останній коміт | Запуск | Примітка |
|------|------|-----------|----------------|--------|----------|
| `scraper_agent.py` | daemon | shar-B скрейпер через Redis-чергу (Rozetka/Prom), anti-bot fingerprint→`scraped_products` | 2026-04-12 · klatch1shop-ai | НЕ запускається регулярно | каркас, не в обороті |
| `rozetka_card_agent.py` | utility | парсинг карток Rozetka, переклад параметрів рос→укр (словник) | 2026-04-12 · Tekken | вручну/legacy | `shared.utils.db`, `ollama_worker` |
| `run_night_processing.py` | one-off | нічна пакетна обробка карток (aya-expanse:8b) | 2026-04-12 · Tekken | разово | `rozetka_card_agent`, db |
| `import_carvol.py` | one-off | первинний імпорт каталогу Carvol (8244) | 2026-05-09 · Tekken | разово (виконано) | `shared.utils.db` |
| `import_from_prom.py` | one-off | імпорт товарів з Prom API за SKU | 2026-04-12 · klatch1shop-ai | разово | `shared.utils.db` |
| `import_from_prom_xml.py` | one-off | імпорт з Prom XML-фіду (ціни/фото) | 2026-04-12 · klatch1shop-ai | разово | `shared.utils.db` |
| `import_supplier_feed.py` | one-off | узагальнений імпорт фіду постачальника | 2026-04-12 · klatch1shop-ai | разово | `shared.utils.db` |
| `generate_carvol_xml.py` | generator | старий генератор Carvol XML (8244, категорії+params) | 2026-05-09 · Tekken | legacy | `carvol_category_map`, db |
| `generate_params_from_name.py` | library | словник тип товару/марка авто з назви → params | 2026-05-09 · Tekken | імпорт | `shared.utils.db` |
| `xml_generator.py` | generator | старий генератор Розетка-XML (маппінг→rz_id) | 2026-04-12 · klatch1shop-ai | legacy | `shared.utils.db`, `ollama_worker` |
| `debug_page.py` | dev/one-off | зберігає HTML сторінки Rozetka для дебагу селекторів | 2026-03-30 · klatch1shop-ai | dev | — |
| `find_url.py` | dev/one-off | `headless=False`, ручний пошук селекторів на rozetka | 2026-03-30 · klatch1shop-ai | dev | — |

---

## tg_dispatcher/
| Шлях | Кат. | Що робить | Останній коміт | Запуск | Імпортує |
|------|------|-----------|----------------|--------|----------|
| `main.py` | daemon | Telegram-бот (aiogram 3.x polling): приймає PDF ТТН від Carvol→`parse_ttn_pdf`→`get_ttn_info`→`match`→`set_ttn`+`change_status(3)`; команди/голос | 2026-06-08 · klatch1shop-ai · PDF link in TTN | daemon (systemd `tg-dispatcher`) | `agents.orders.ttn_pdf_parser`, `np_api`, `rozetka_order_agent` |
| `ai_brain/voice_handler.py` | library | STT (faster-whisper) для голосових повідомлень | 2026-05-24 · Tekken | імпорт | — |

---

## orchestrator/ (шар B)
| Шлях | Кат. | Що робить | Останній коміт | Запуск | Імпортує |
|------|------|-----------|----------------|--------|----------|
| `orchestrator.py` | daemon | LLM-маршрутизатор задач (Ollama), Redis-черги, генерація skills, Qdrant-пам'ять | 2026-05-27 · Tekken | daemon (`start_all.sh`) | `shared.utils.db/ollama_worker/redis_queue/skill_loader/skills_indexer` |
| `telegram_bot.py` | daemon | **legacy** Telegram-бот шару B | 2026-03-30 · klatch1shop-ai | НЕ використовується | витіснений `tg_dispatcher/main.py` |

---

## agents/{marketing,finance,efficiency,dev,checker,interfaces}/ (шар B)
| Шлях | Кат. | Що робить | Останній коміт | Запуск |
|------|------|-----------|----------------|--------|
| `marketing/marketing_agent.py` | daemon | LLM marketing-агент (Redis listen) | 2026-04-12 · klatch1shop-ai | `start_all.sh`, рідко |
| `marketing/card_optimizer.py` | utility | оптимізація карток товарів | 2026-05-10 · Tekken | вручну |
| `finance/finance_agent.py` | daemon | LLM finance-агент | 2026-04-12 · klatch1shop-ai | `start_all.sh`, рідко |
| `efficiency/efficiency_agent.py` | daemon | LLM efficiency/моніторинг | 2026-04-12 · klatch1shop-ai | `start_all.sh`, рідко |
| `dev/dev_agent.py` | daemon | LLM developer-агент (генерація коду) | 2026-05-29 · Tekken | `start_all.sh`, рідко |
| `checker/acceptance_checker.py` | daemon | self-improvement loop, auto skills index | 2026-04-12 · klatch1shop-ai | `start_all.sh`, рідко |
| `interfaces/instruction_parser.py` | library | `/learn`: розбір інструкцій→Qdrant | 2026-05-27 · Tekken | імпорт |
| `interfaces/telegram_gateway.py` | library | шлюз TG для шару B | 2026-05-23 · Tekken | імпорт |

---

## shared/mcp_servers/ — MCP-сервери (запуск on-demand з Claude Code)
| Шлях | Кат. | Що робить | Останній коміт |
|------|------|-----------|----------------|
| `epicentr_mcp.py` | utility | MCP для Єпіцентр Merchant API (12 семантичних інструментів OMS+PIM+Delivery) | 2026-05-24 · Tekken |
| `rozetka_mcp.py` | utility | MCP для Rozetka Seller API | 2026-05-23 · Tekken |
| `prom_mcp.py` | utility | MCP для Prom.ua Seller API | 2026-05-23 · Tekken |
| `browser_mcp.py` | utility | MCP браузер-автоматизації (мегапарсер на `playwright_base`) | 2026-05-24 · Tekken |
| `filesystem_mcp.py` | utility | MCP доступу агентів до документації (JSON/MD) | 2026-04-04 · klatch1shop-ai |
| `agent_mcp_server.py` | utility | загальний MCP-сервер агентів | 2026-04-12 · klatch1shop-ai |

---

## shared/utils/ — бібліотеки
| Шлях | Кат. | Що робить | Останній коміт |
|------|------|-----------|----------------|
| `db.py` | library | psycopg2 RealDictCursor обгортка; `log_event`, `create_alert`, `update_agent_status` | 2026-04-12 · klatch1shop-ai |
| `pricing.py` | library | ціноутворення; `calc_price` (**факт: mark-up, попри докстрінг**), CPA-функції | 2026-05-23 · Tekken |
| `redis_queue.py` | library | `push_task`/`pop_task`/`get_queue_length` | 2026-04-12 · klatch1shop-ai |
| `memory.py` | library | векторна пам'ять через Redis→embedding_service→Qdrant | 2026-05-28 · Tekken |
| `model_selector.py` | library | вибір Ollama-моделі за типом задачі | 2026-05-28 · Tekken |
| `ollama_worker.py` | daemon | воркер черги Ollama (`while True`) | 2026-04-12 · klatch1shop-ai |
| `skill_loader.py` | library | завантаження skill-файлів | 2026-03-30 · klatch1shop-ai |
| `skills_indexer.py` | library | індексація skills у Qdrant | 2026-05-28 · Tekken |

---

## Корінь репо
| Шлях | Кат. | Що робить | Останній коміт | Запуск |
|------|------|-----------|----------------|--------|
| `epicentr_postprocess.py` | generator | постобробка Єпіцентр XML (фото-фільтр, дедуп, `2883→2848`, trim) — **актуальна версія пайплайну** | 2026-06-14 · Tekken · auto sync | вручну |
| `cli.py` | utility | CLI керування (`status`, `cmd`) — шар B | 2026-04-12 · klatch1shop-ai | вручну |
| `dashboard/api.py` | daemon | FastAPI веб-дашборд (порт **8888**, WebSocket) | 2026-04-12 · klatch1shop-ai | daemon |
| `embedding_service.py` | daemon | sentence-transformers embeddings (**тільки ноутбук**, AVX) | 2026-06-11 · klatch1shop-ai | daemon (ноут) |
| `enrich_with_ai.py` | one-off | збагачення товарів: scrape `grandinstrument.ua` (BeautifulSoup) + Ollama | 2026-04-12 · klatch1shop-ai | разово |
| `enrich_agent.py` | one-off | агент збагачення (BeautifulSoup grandinstrument) | 2026-04-12 · klatch1shop-ai | разово |
| `mass_enrich.py` | one-off | масове збагачення (BeautifulSoup + Ollama) | 2026-04-12 · klatch1shop-ai | разово |
| `ingest_prices.py` | one-off | завантаження цін у БД | 2026-04-12 · klatch1shop-ai | разово |
| `update_db_schema.py` | migration | ALTER `products` (title_epicentr, specs_json тощо) | 2026-04-12 · klatch1shop-ai | разово |
| `test_agent.py` | test | smoke-тест агентів | 2026-04-12 · klatch1shop-ai | вручну |
| `test_epicentr.py` | test | тест Єпіцентр-логіки | 2026-05-19 · Tekken | вручну |

### Shell-скрипти
| Шлях | Що робить | Останній коміт | Примітка |
|------|-----------|----------------|----------|
| `start_all.sh` | піднімає шар B (orchestrator + 5 агентів + ollama_worker + dashboard) через nohup | 2026-04-12 · Tekken | шлях `/home/tek/agent-system` |
| `stop_all.sh` | зупиняє за `logs/*.pid` | 2026-03-30 · klatch1shop-ai | ⚠️ шлях `/home/tekken/agent-system` — не збігається зі `start_all.sh` |
| `status.sh` | статус процесів + `docker compose ps` | 2026-03-30 · klatch1shop-ai | ⚠️ шлях `/home/tekken/agent-system` |
| `start_laptop_services.sh` | запуск сервісів ноутбука (Ollama/embedding) | 2026-06-11 · klatch1shop-ai | ноутбук |
| `stop_laptop_services.sh` | зупинка сервісів ноутбука | 2026-06-11 · klatch1shop-ai | ноутбук |

---

## Зведена статистика

- **Усього скриптів** у каталозі (без `__init__.py`/`.bak`): **~95** (`.py` ≈ 90, `.sh` = 5).
- **Реально активні** (daemon/cron/регулярно вручну): **~35** — операційне ядро `agents/orders/` (13), ключові `tools/` (≈22 генератори/чекери/утиліти/2 Flask-daemon/watchdog), `tg_dispatcher/main.py`, dashboard, embedding_service, активні скрейпери (4).
- **Бібліотеки** (тільки імпорт): `shared/utils/*` (8), `np_api`, `ttn_pdf_parser`, `order_agent`, `price_engine`, `playwright_base`, `generate_params_from_name`, `carvol_category_map`, `voice_handler`, MCP-сервери (6).
- **Шар B (каркас, у щоденному обороті майже не використовується):** `orchestrator/orchestrator.py`, `agents/{marketing,finance,efficiency,dev,checker}/*`, `cli.py`, `ollama_worker.py`.

### Кандидати на видалення / консолідацію
1. **`*.bak`/`*.bak2`** (поза каталогом, але в репо): `agents/orders/rozetka_order_agent.py.bak`, `.bak2`; `agents/orders/ttn_pdf_parser.py.bak`; `tg_dispatcher/main.py.bak`, `.bak2`; `tools/carvol_epicentr_generator.py.bak`. → видалити, історія є в git.
2. **Дубль `epicentr_postprocess.py`** — корінь vs `tools/` розійшлись (`2883→2848` vs `2883→2874`). Лишити один (кореневий — пайплайновий), інший видалити, щоб не плутати.
3. **`orchestrator/telegram_bot.py`** — legacy-бот, витіснений `tg_dispatcher/main.py`. → видалити.
4. **dev-артефакти скрейпінгу:** `agents/scraper/debug_page.py`, `find_url.py` (`headless=False`). → видалити або винести в `scratch/`.
5. **one-off імпорти** (виконані одноразово): `import_carvol.py`, `import_from_prom.py`, `import_from_prom_xml.py`, `import_supplier_feed.py`, `ingest_prices.py`, `update_db_schema.py`, `run_night_processing.py`. → перенести в `scripts/oneoff/` (не видаляти — можуть знадобитись для нового постачальника).
6. **Старі генератори:** `agents/scraper/generate_carvol_xml.py`, `agents/scraper/xml_generator.py`, `tools/fix_rozetka_xml.py` — витіснені актуальними генераторами/валідаторами. → перевірити й позначити legacy.
7. **Шар B** (`marketing/finance/efficiency/dev/checker` + `orchestrator` + `cli.py`): якщо стратегічно не розвивається — заархівувати в окрему гілку, щоб корінь репо відображав лише реальний операційний шар.

> Дати/автори — з `git log -1 --date=short` по кожному файлу проти `origin/main`. «Запуск зараз» для daemon/cron частково з доків (`CLAUDE.md`/`AGENT_RULES.md`), бо `crontab -l`/`ps aux` на живому сервері не перевірялись.

_Версія: 1.0 · 2026-06-27 · гілка `main` (`2ef4fa3`)._
