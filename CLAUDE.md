# Dropshipping Agent System — Інструкції для Claude Code

## Правила нової сесії (читати ПЕРШИМ)
```
git pull && cat TASKS.md
```
Після сесії: оновити TASKS.md і зробити git push вручну.

## ⛔ Правило «готово» для генераторів і фідів (обовʼязкове)

Жодна зміна генератора чи фіду **не вважається завершеною**, поки не виконані
всі три перевірки. Доти статус — «в процесі», і треба називати, якого кроку
бракує. Стосується **Rozetka, Prom і Єпіцентру однаково**.

1. **Розгорнуто на сервері публікації**, а не лише згенеровано локально.
   Реальна публікація йде з `tek@100.82.24.112:~/agent-system` за crontab.
2. **Збіг MD5 генератора** на ноутбуці й на сервері:
   ```bash
   md5sum tools/<generator>.py
   ssh tek@100.82.24.112 'cd ~/agent-system && md5sum tools/<generator>.py'
   ```
3. **Опублікований URL звірено з локальним файлом** — завантажити фід і
   порівняти хеш, а не покладатись на дату в шапці.
   ```bash
   ssh tek@100.82.24.112 'cd ~/agent-system && sha256sum output/<feed>.xml'
   curl -s <raw-url> | sha256sum
   # хеш, незалежний від CDN-кешу:
   curl -s https://api.github.com/repos/klatch1shop-ai/noire-feed/contents/<feed>.xml \
     | python3 -c "import json,sys; print(json.load(sys.stdin)['sha'])"
   ```

**Чому це правило існує.** 10.08.2026 менеджеру Rozetka написали «усі
зауваження виправили» й дали посилання, за яким лежав невиправлений файл:
локально все було зроблено, а на usa1 стояв генератор від 08.08, і щогодинний
cron перезбирав фід старим кодом. **Дата в шапці оновлювалась щогодини — саме
це маскувало проблему майже добу.** «Фід зібрано» ≠ «фід опубліковано».

`raw.githubusercontent.com` віддає `cache-control: max-age=300`, тому одразу
після публікації можна завантажити попередню версію. Для беззаперечного доказу
використовувати `git blob sha1` через GitHub API — він рахується з вмісту.

У кожного маркетплейсу **свій генератор, свій вихідний файл і свій запис
у crontab**: оновлення одного не впливає на інші, перевіряти треба кожен окремо.

## ⛔ Два незалежні шари перевірки перед публікацією

Технічна коректність і якість контенту — **різні речі, і жодна не замінює
іншу**. Перед кожною публікацією Rozetka проходять обидва:

1. **Наш валідатор** — `tools/noire_rozetka_validator.py` (структура, ліміти,
   довідники) плюс скорери й дослідження SEO. Ловить те, що знаємо ми.
2. **Офіційний валідатор Rozetka** —
   `https://seller.rozetka.com.ua/gomer/pricevalidate/check/index`.
   Ловить те, чого ми не знаємо: правила майданчика змінюються без
   попередження, і наш валідатор про зміну дізнається лише з листа модератора.

**Крок 2: капчу проходить власник, решту робить агент.** Валідатор НЕ
потребує входу в кабінет — лише посилання на фід, email і капчу. Звіт
приходить листом від `gomer_services@rozetka.com.ua` на
klatch1.shop@gmail.com, а детальний звіт відкривається за хешем із листа
**без авторизації**, тобто читається й розбирається автоматично.

Порядок: опублікувати фід → власник подає
`https://raw.githubusercontent.com/klatch1shop-ai/noire-feed/main/noire_rozetka.xml`
у валідатор → агент читає лист, відкриває звіт за хешем і розбирає XLSX із
переліком проблемних позицій. Попередження не роблять файл невалідним, але
зменшують кількість валідних товарів — 15.08.2026 з 4147 до 2744.

## ⛔ Правило позитивного контролю (обовʼязкове)

**«Нічого не знайдено» — це не результат, доки не доведено, що перевірка
взагалі здатна щось знайти.** Перш ніж повідомляти про чистий результат
(0 помилок, 0 дублів, «нас немає у видачі», «поле порожнє»), треба зробити
так, щоб перевірка спрацювала хоча б раз на випадку, де дефект точно є.

Порядок для будь-якої нової перевірки:

1. **Перелічити реальні назви полів** у самому артефакті, а не за памʼяттю:
   ```bash
   python3 tools/feed_fields.py output/<feed>.xml --params
   ```
   Різні майданчики й різні ітерації називають те саме по-різному
   (`description` / `description_ua`, `name` / `name_ua`,
   `keywords` / `keywords_ua`), а в назвах характеристик трапляються різні
   апострофи. Запит із неправильною назвою дає нуль, не помиляючись.
2. **Взяти відомий позитивний випадок** — SKU зі скріншота менеджера, рядок
   із чужою мовою, картку з дублем — і переконатись, що перевірка його
   ловить. Якщо відомого немає, зібрати синтетичний і прогнати перевірку на
   парі «зіпсоване / правильне»: обидва результати мають відрізнятись.
3. **Пояснити нуль механічно.** Якщо перевірка нічого не знайшла, треба
   вміти сказати, ЧОМУ даних такого роду не мало бути. «Схоже, все добре» —
   не пояснення.
4. **Перед зміною порога, фільтра чи параметра — прочитати коментар біля
   нього.** У коді вже записано, чому число саме таке (`WORKERS = 3` — бо
   12 потоків дали 429 на 40% запитів). Зміна без читання повертає вже
   розвʼязану проблему.
5. **Для парних гілок (укр/рос, два фіди, дві мови) — міряти обидві** й
   порівнювати числа між собою. Розбіжність у рази — ознака дефекту
   інструмента, а не даних.

**Чому це правило існує.** 15.08.2026 за один день той самий клас помилки
спрацював шість разів. Перевірка узгодженості обʼєму дала «0 розбіжностей»,
бо читала тег `description`, якого у фіді Rozetka немає (описи в
`description_ua`); справжніх розбіжностей було 7, і першу з них менеджер
Rozetka вже показала на скріншоті. Перевірка видимості в пошуку Prom
відповіла «нас немає», бо шукала імʼя продавця в сирому HTML, тоді як воно
рендериться в DOM. Пошук дублікатів фото дав нуль, бо порівнював URL, а
дублі перцептивні. Збір російських тегів дав нуль, бо власний regex вимагав
префікс `/ru/`, якого в російській версії Prom немає. Після виправлення збір
«вдався» — і приніс 105 українських фраз під міткою «російські», бо мовне
куки Prom підмінило видачу. А скорер фіду цього не побачив і показав ті самі
76.8 бала, бо рахував кількість фраз, не мову.

Спільне в усіх шести: **нуль або «чисто» прочитано як факт про дані, хоча це
був факт про інструмент.** Ціна помилки несиметрична: хибна тривога
коштує кількох хвилин перевірки, хибний спокій — місяця, як з пунктами 4 і 7
Ольги, які «виправляли» двічі й не виправили жодного разу.

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

## Активні магазини і стан (2026-06-15)
| Магазин | Постачальник | Товарів | Статус | XML/Sync |
|---------|-------------|---------|--------|---------|
| Prom.ua | TOPTUL | ~5908 | активний | GitHub, щодня |
| Rozetka | Carvol | ~8244 | активний | GitHub, о 7:00 |
| Єпіцентр | TOPTUL | ~5893 | чернетки | ручне завант. |
| Єпіцентр | Carvol | 7075 | **готовий до завантаження** | exports/carvol_epicentr.xml |

## Ключові інструменти (tools/)
| Файл | Призначення |
|------|------------|
| `carvol_epicentr_generator.py` | Carvol прайс (SpreadsheetML) → `carvol_epicentr_new.xml` |
| `epicentr_postprocess.py` | Фільтр фото + дедуп + 2883→2848 → `carvol_epicentr.xml` |
| `epicentr_xml_checker.py` | Повна перевірка XML перед імпортом (exit 0=OK, 1=помилки) |
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
| 3729 | Камери заднього огляду | 3729 |
| 2821 | Кабелі та перехідники | 2821 |
| 2848 | Аксесуари для автосигналізацій (+ колишній 2883) | 2848 |
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

## Єпіцентр — пайплайн генерації XML

**Послідовність (на сервері):**
```bash
python3 tools/carvol_epicentr_generator.py          # → exports/carvol_epicentr_new.xml
python3 epicentr_postprocess.py                      # → exports/carvol_epicentr.xml
```
**Перевірка (на ноутбуці):**
```bash
scp tek@100.82.24.112:/home/tek/agent-system/exports/carvol_epicentr.xml ~/Downloads/
python3 tools/epicentr_xml_checker.py ~/Downloads/carvol_epicentr.xml
# exit 0 = готовий до імпорту, exit 1 = є помилки
```

### Додавання нової категорії Єпіцентр

1. Знайти attrs через `epicentr_pim_explorer.py` або `epicentr_attrs_explorer.py`
2. Додати константи в `carvol_epicentr_generator.py` після секції `# attr NNN`
3. Додати `elif cat_code == 'XXXX'` в `get_category_params()`
4. Додати `_pf()` для числових атрибутів (без valuecode), `_p()` для select
5. Додати `'XXXX': [...]` в `REQUIRED_PARAMS` в `epicentr_xml_checker.py`
6. Запустити повний пайплайн + перевірити `xml_checker`

Планується: `epicentr_category_builder.py` — автодискавері attrs з PIM API → генерація `elif` блоку.

## Competitor Scraper + Price Rules

### Додавання конкурента для моніторингу
```
agents/scraper/ — Playwright-based
```
Новий магазин: успадковувати від `playwright_base.py`, реалізувати метод `scrape_product(url)`.
Результат → PostgreSQL таблиця `competitor_prices(article, competitor, price, scraped_at)`.

### Формули ціноутворення
| Маркетплейс | Формула | Примітка |
|-------------|---------|----------|
| Єпіцентр | `ceil(rrc / (1 - comm/100) / 10) * 10` | gross-up на комісію |
| Розетка | `ceil(rrc * (1 + comm/100) / 10) * 10` | mark-up на комісію |
| Катран | `ceil(price_rrc * (1 + comm/100) / 10) * 10` | аналог Розетки |

Конкурентне коригування (майбутнє): `if competitor_price < our_price → our_price = ceil(competitor_price * 0.97 / 10) * 10`, але не нижче `cost * 1.10`.

## Відомі проблеми
- Логін/пароль Розетки в .env неправильні (hyper_store/Tovarka2025Rivne → incorrect_username_password)
- QIV не зареєстрований в Єпіцентрі → 6110 товарів з vendor='Інше'
- Катран: ~55% категорій не замапповано (4101 товарів у DEFAULT)
