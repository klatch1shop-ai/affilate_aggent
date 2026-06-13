# Dropshipping Agent System — Інструкції для Claude Code

## Правила нової сесії (читати ПЕРШИМ)
```
git pull && cat TASKS.md
```
Після сесії: оновити TASKS.md і зробити git push вручну.

## Про проект
Автоматизація дропшипінг-бізнесу на маркетплейсах Prom.ua, Розетка, Єпіцентр.
Постачальники: TOPTUL/Гранд Інструмент (Prom+Єпіцентр), Carvol (Розетка+Єпіцентр).

## Інфраструктура
- Сервер tek@100.82.24.112 (Tailscale) — PostgreSQL, Redis, Qdrant, всі агенти
- Ноутбук 100.126.131.55 — Ollama (RTX 4050), embedding_service.py
- З'єднання — Tailscale VPN між всіма машинами
- GitHub — github.com/klatch1shop-ai/affilate_aggent

## Підключення до сервера
```
ssh tek@100.82.24.112
cd /home/tek/agent-system && source venv/bin/activate
```

## База даних
```
docker exec -it agent_postgres psql -U agentadmin agentdb
```
(НЕ `-U agent` — правильно `-U agentadmin`)

## Активні магазини і стан (2026-06-13)
| Магазин | Постачальник | Товарів | Статус | XML/Sync |
|---------|-------------|---------|--------|---------|
| Prom.ua | TOPTUL | ~5908 | активний | GitHub, щодня |
| Rozetka | Carvol | ~8244 | активний | GitHub, о 7:00 |
| Єпіцентр | TOPTUL | ~5893 | чернетки | ручне завант. |
| Єпіцентр | Carvol | 7081 | **готовий до завантаження** | exports/carvol_epicentr.xml |

## Ключові інструменти (tools/)
| Файл | Призначення |
|------|------------|
| `carvol_epicentr_generator.py` | Carvol прайс (SpreadsheetML) → Єпіцентр XML |
| `epicentr_pim_explorer.py` | Пошук брендів/країн в PIM API (кеш 54370 брендів) |
| `epicentr_quality_checker.py` | SEO скоринг XML (score 0-100, avg 73/100) |
| `prom_xml_generator.py` | XLSX → Prom XML (опція --no-filter) |
| `prom_validator.py` | Валідація Prom XML |
| `watchdog.py` | Моніторинг сервісів + авто-коміт (БЕЗ push) |

## Важливі факти Єпіцентр PIM API
- atset_code == category_code (завжди, для всіх категорій)
- Бренд "Інше": valuecode = `827b4a70220f11ea918e001e67ecc97b`
- Фільтр `filter[ids][]` для /v2/pim/attribute-sets НЕ працює — сканувати всі сторінки
- Brand options: 544 сторінки × 100 = 54370 брендів (кешовано в epicentr_brand_cache)
- Country options: 50 сторінок, Китай → code='chn'

## Наші категорії Єпіцентр (автотовари Carvol)
| code | Назва | atset |
|------|-------|-------|
| 8743 | Перехідні рамки для автомагнітол | 8743 |
| 4907 | Магнітоли | 4907 |
| 3729 | Камери заднього огляду | 3729 |
| 2821 | Кабелі та перехідники | 2821 |
| 2848 | Аксесуари для автосигналізацій | 2848 |
| 2883 | LED-світло для автомобіля | 2883 |
| 2866 | Автомагнітоли | 2866 |

## Бренди Єпіцентр — валідні valuecodes
| Бренд | valuecode |
|-------|-----------|
| Carav | `5d7771be904849b4b37fd59dd61c3c2e` |
| Teyes | `c6c87e174180490d9b8683a63f5fe5b2` |
| Pioneer | `pioneer` |
| Alpine | `v5synp4i6qqfbgme` |
| Sony | `4whmcgge` |
| Toyota | `64lxcpbn` |
| **Інше (QIV/невідомі)** | `827b4a70220f11ea918e001e67ecc97b` |

## БД таблиці (критичні)
| Таблиця | Опис | Рядків |
|---------|------|--------|
| `carvol_products` | товари Carvol | ~8304 |
| `epicentr_brand_cache` | всі бренди Єпіцентру | 54370 |
| `epicentr_brand_map` | валідні бренди наших категорій | 42 |
| `epicentr_quality_log` | SEO scores по офферах | 7081 |
| `marketplace_api_methods` | 123 API методи | 123 |
| `carvol_epicentr_cat_map` | маппінг категорій Carvol → Єпіцентр | ~15 |
| `katran_categories` | категорії Катрана з Rozetka ID | ~5124 |

## Розетка API
Base URL: `https://api-seller.rozetka.com.ua` (з дефісом — без дефісу дає 404)
Auth: Bearer ROZETKA_API_TOKEN з .env
SSL: verify=False обов'язково (старий сервер Celeron з протухлим сертом)

```
PATCH /orders/{id}  {"status": 2}  — підтвердити замовлення
PATCH /orders/{id}  {"status": 3}  — передано в доставку
PATCH /orders/{id}  {"status": 6}  — скасувати
POST  /orders/add-ttn  {"order_id", "ttn", "delivery_service_id": 1}  — ТТН (primary)
PATCH /orders/{id}  {"ttn": "номер"}  — ТТН (fallback)
GET   /orders/search?types=4  — нові замовлення
GET   /orders/{id}  — деталі замовлення
```

Послідовність статусів: new → status 2 → set_ttn → status 61 → status 3
Скасування: status 6

## Nova Poshta API
URL: `https://api.novaposhta.ua/v2.0/json/`
Key: NP_API_KEY в .env
Method: POST `TrackingDocument/getStatusDocuments`

## Постачальник Carvol (Розетка + Єпіцентр)
- Telegram ID: 8035052611 (CARVOL_TG_CHAT_ID в .env)
- Telegram: +380971574150
- Email: carvolua@gmail.com
- Цикл Розетка: Excel → Carvol → PDF накладної НП → ТТН
- Прайс: SpreadsheetML Excel (не xlsx), заголовки з рядка 4, колонки: артикул/бренд/модель/категорія/найменування/залишок/ціна опт(usd)/роздріб(uah)

## Постачальник Катран (Розетка — новий)
URL: https://katran.vn.ua/b2b
Менеджер: Сергій Голубцов srgolubtsov@katran.vn.ua +380632822022
Формат фіду: `<price><products><product>` (НЕ yml_catalog!)
Формула ціни: `ceil(price_rrc * (1 + commission_pct/100) / 10) * 10`
Маппінг: таблиця katran_categories в БД (~45% покриття, 55% у DEFAULT)

Підтверджені rz_id (перевірено через bt.rozetka.com.ua/c{id}/):
Пральні(80124,7.56), Холодильники(80125,7.56), Плити(80137,7.56),
Витяжки(80140,14.04), Мультипечі(81089,19.44), Мультиварки(112986,19.44),
Телевізори(80011,12.96), Обігрівачі(80192,14.04) — та ін.

Пропагація категорій (після UPDATE батьків):
```sql
DO $$ DECLARE r INT; p INT := 0; BEGIN LOOP p := p+1;
  UPDATE katran_categories c SET rozetka_rz_id=pr.rozetka_rz_id,
    rozetka_category=pr.rozetka_category, commission_pct=pr.commission_pct
  FROM katran_categories pr WHERE c.parent_id=pr.id
    AND c.rozetka_rz_id IS NULL AND pr.rozetka_rz_id IS NOT NULL;
  GET DIAGNOSTICS r = ROW_COUNT; EXIT WHEN r=0 OR p>=5; END LOOP; END $$;
```

## Автоматизація ТТН — реалізовано (2026-05-29)
1. Нове замовлення → підтверджуємо → Excel → Telegram Carvol → save_to_db('accepted')
2. Carvol скидає PDF → бот отримує від chat ID 8035052611
3. parse_ttn_pdf → ТТН + телефон/ім'я/місто
4. NP API → уточнює дані + cod_sum
5. match_order_by_np_data: phone → name+price (fuzzy) → price (±5%)
6. Один збіг → set_ttn() + change_status(3) автоматично
7. Верифікація GET /orders/{id} через 2с → ALARM якщо ТТН не збереглось

## Ключові файли агентів
- `agents/orders/ttn_pdf_parser.py` — парсинг PDF накладних НП
- `agents/orders/np_api.py` — NP API (get_ttn_info, match_order_by_np_data)
- `agents/orders/rozetka_order_agent.py` — Розетка агент (set_ttn, change_status)
- `tg_dispatcher/main.py` — Telegram бот (aiogram 3.x)

## Активні сервіси
```
systemctl --user status epicentr-order-agent rozetka-order-agent tg-dispatcher feed-server
```

## Crontab (сервер)
```
0 * * * *    rozetka_github_sync.py   (щогодини)
0 7 * * *    feed_sync.py             (щодня о 7:00)
0 8 * * *    price_updater.py         (щодня о 8:00)
*/10 * * * * watchdog.py              (кожні 10 хв)
```

## Git правила
- **Ноутбук**: розробка → `git push` вручну
- **Сервер watchdog**: тільки `git add -A && git commit` локально — **НЕ push**
- XML файли в `exports/` — в репо, не конфліктують (сервер не пушить)

## Правила розробки (завжди!)
1. Перевіряти синтаксис: `python3 -c "import ast; ast.parse(open('file.py').read())"`
2. Перед змінами backup: `cp file.py file.py.bak`
3. SSL verify=False для Розетки API
4. НЕ запускати sentence-transformers на сервері (немає AVX — exit code 132)
5. Патч-скрипти: НЕ використовувати `r"""..."""` якщо всередині docstrings з `"""` — окремий файл
6. Скрипти з openpyxl/sentence-transformers → запускати на ноутбуці
7. Скрипти без AVX → можна на сервері через `venv/bin/python3`

## Telegram бот
- Token: TELEGRAM_BOT_TOKEN в .env
- Admin ID: 6762672351
- Carvol Chat ID: 8035052611
- security_middleware: ADMIN_ID — повний доступ; CARVOL_TG_CHAT_ID — тільки document

## Файли що треба читати перед розробкою
- `CLAUDE.md` (цей файл) + `TASKS.md`
- `shared/knowledge_base/rozetka/xml_requirements.txt`
- `shared/knowledge_base/rozetka/api_full.txt`
- `shared/knowledge_base/api_reference.md` — 123 API методи
- `data/carvol_rozetka.xml` — еталон XML формату Розетки

## Відомі проблеми
- Логін/пароль Розетки в .env неправильні (hyper_store/Tovarka2025Rivne → incorrect_username_password)
- QIV не зареєстрований в Єпіцентрі → 6110 товарів з vendor='Інше'
- Катран: ~55% категорій не замапповано (4101 товарів у DEFAULT)
