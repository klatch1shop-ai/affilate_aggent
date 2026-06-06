# Dropshipping Agent System — Інструкції для Claude Code

## Про проект
Автоматизація дропшипінг-бізнесу на маркетплейсах Prom.ua, Розетка, Єпіцентр.
Постачальники: TOPTUL/Гранд Інструмент (Prom+Єпіцентр), Carvol (Розетка).

## Інфраструктура
- Сервер tek@100.82.24.112 (Tailscale) — PostgreSQL, Redis, Qdrant, всі агенти
- Ноутбук 100.126.131.55 — Ollama (RTX 4050), embedding_service.py
- З'єднання — Tailscale VPN між всіма машинами
- GitHub — github.com/klatch1shop-ai/affilate_aggent

## Підключення до сервера
ssh tek@100.82.24.112
Всі команди на сервері: cd /home/tek/agent-system && source venv/bin/activate

## База даних
docker exec -it agent_postgres psql -U agent agentdb

## Розетка API
Base URL: https://api-seller.rozetka.com.ua
Auth: Bearer ROZETKA_API_TOKEN з .env
SSL: verify=False обов'язково (старий сервер Celeron з протухлим сертом)
PATCH /orders/{id} {"status": 2} — підтвердити замовлення
PATCH /orders/{id} {"status": 3} — передано в доставку
PATCH /orders/{id} {"status": 6} — скасувати
POST  /orders/add-ttn {"order_id", "ttn", "delivery_service_id": 1} — встановити ТТН (primary)
PATCH /orders/{id} {"ttn": "номер"} — встановити ТТН (fallback якщо add-ttn не спрацював)
GET /orders/search?types=4 — нові замовлення
GET /orders/search?status={status} — замовлення за статусом
GET /orders/{id} — деталі замовлення (для верифікації ТТН)

## Послідовність статусів Розетки
new (types=4) → confirm → status 2 (підтверджено)
→ set_ttn [POST /orders/add-ttn] → status 61 (TTN додано, автоматично Розеткою)
→ change_status(3) → status 3 (передано в доставку)
Скасування: status 6

Цикл TTN:
1. process_order підтверджує → Excel → Carvol Telegram → save_to_db('accepted')
2. PDF від Carvol → handle_document → parse → NP API → match → set_ttn → status 61 → change_status(3) → верифікація GET

## Nova Poshta API
URL: https://api.novaposhta.ua/v2.0/json/
Key: NP_API_KEY в .env (отримати на my.novaposhta.ua/settings/index#apikeys)
Method: POST TrackingDocument/getStatusDocuments
Повертає: RecipientFullName, PhoneRecipient, CityRecipient, WarehouseRecipient, CashPaymentAmount, StatusCode

## Постачальник Carvol (Розетка)
Telegram ID: 8035052611 (CARVOL_TG_CHAT_ID в .env)
Telegram: +380971574150
Email: carvolua@gmail.com
Цикл: ми відправляємо Excel → вони скидають PDF накладної НП з ТТН

## Автоматизація ТТН — РЕАЛІЗОВАНО (2026-05-29)
1. Нове замовлення → підтверджуємо (status 2) → Excel в Telegram Carvol → save_to_db('accepted')
2. Carvol скидає PDF накладної → бот отримує від chat ID 8035052611
3. handle_document: parse_ttn_pdf → витягує ТТН (формат "20 4514 5092 1650") + телефон/ім'я/місто
4. get_ttn_info (NP API) → уточнює дані отримувача та cod_sum
5. match_order_by_np_data: phone (score 1.0) → name+price (fuzzy 0.6+) → price (±5%)
   Fallback: match_order_by_ttn_data з PDF якщо NP API недоступний
6. Один збіг → set_ttn() + change_status(3) автоматично без підтверджень
7. Верифікація: GET /orders/{id} через 2с → ALARM якщо ТТН не збереглось
8. Кілька збігів → список адміну → ручне /ttn ORDER_ID TTN

## Ключові файли агентів
- agents/orders/ttn_pdf_parser.py — парсинг PDF накладних НП (parse_ttn_pdf, match_order_by_ttn_data)
- agents/orders/np_api.py — NP API інтеграція (get_ttn_info, match_order_by_np_data)
- agents/orders/rozetka_order_agent.py — Розетка агент (set_ttn з POST+fallback PATCH, change_status, get_order_details, process_order)
- tg_dispatcher/main.py — Telegram бот (handle_document, security_middleware, /ttn команда)

## Важливі правила
1. Завжди перевіряти синтаксис: python3 -c "import ast; ast.parse(open('file.py').read())"
2. Перед змінами робити backup: cp file.py file.py.bak
3. SSL verify=False для Розетки API (старий сервер Celeron)
4. НЕ запускати sentence-transformers на сервері (немає AVX — exit code 132)
5. Embeddings генеруються на ноутбуці через Redis queue:embeddings
6. Логи: /tmp/rozetka_order_agent.log, /tmp/epicentr_order_agent.log
7. Патч-скрипти — не використовувати r"""...""" якщо всередині є docstrings з """. Використовувати окремий файл + звичайний open().read()

## Telegram бот
Token: TELEGRAM_BOT_TOKEN в .env
Admin ID: 6762672351
Carvol Chat ID: 8035052611 (CARVOL_TG_CHAT_ID в .env)
Файл: tg_dispatcher/main.py (aiogram 3.x)
security_middleware: ADMIN_ID — повний доступ; CARVOL_TG_CHAT_ID — тільки document (PDF)

## Активні сервіси
systemctl --user: epicentr-order-agent, rozetka-order-agent, tg-dispatcher, feed-server

## Постачальник Катран (Розетка — новий)
URL: https://katran.vn.ua/b2b
Фід складу: KATRAN_FEED_URL_STOCK в .env (ZIP архів → katran.xml)
Менеджер: Сергій Голубцов srgolubtsov@katran.vn.ua +380632822022
Формат фіду: <price><products><product> (НЕ yml_catalog!)
Поля: code, artikul, name, description, images/image, categoryId, vendor,
      pricediler(USD гурт), price(USD опт), price_pdv(грн+ПДВ), price_rrc(RRC грн),
      control_rrc(Y/N), warranty(міс), stock_quantity, stock(есть/в резервах...)
Маппінг категорій: таблиця katran_categories в БД (rozetka_rz_id, commission_pct)
Формула ціни: ceil(price_rrc * (1 + commission_pct/100) / 10) * 10
Важливо: commission_pct вже включає ПДВ (напр. 7% → 7.56% реально)
AVX: скрипт запускати на ноутбуці (НЕ на сервері!)

## Маппінг категорій Катрана — статус (2026-06-06)
Схема таблиці: id, parent_id, name, rozetka_category, rozetka_rz_id, commission_pct, product_count
Запит до БД: SELECT id, rozetka_category, rozetka_rz_id, commission_pct FROM katran_categories WHERE rozetka_rz_id IS NOT NULL

Поточне покриття:
- Змаппованих категорій: 1449 з 5124 (27 батьківських + пропагація на дочірні)
- Покриття товарів: ~40% (3005 з 7441 в наявності)
- Незмаппованих залишається: ~60% (4436 товарів)

Підтверджені (27 батьківських, перевірені через seller API або наявні в БД):
Мишки(80100,19.44), Клавіатури(4628124,19.44), БЖ для ПК(80037,14.04),
Навушники(80105,14.04), Патчкорди(1230965,14.04), Wi-Fi роутери(80193,14.04),
Комутатори(80194,14.04), Пральні машини(80124,7.56), Холодильники(80125,7.56),
Плити(80137,7.56), Витяжки(80192,14.04), Праски(80161,19.44),
Пилососи(80158,19.44), Електрочайники(80160,19.44), Фени(81231,19.44),
Кавоварки(4674720,19.44), Мультипечі(112986,19.44), Зубні щітки(437994,19.44),
Телевізори(80011,12.96), Павербанки(4638591,19.44), Батарейки(80255,19.44),
Кріплення для ТВ(80071,23.76), Аксесуари ноутбук(80090,23.76)

НЕ підтверджені rz_id (потребують перевірки в PriceCreator):
Кабелі та перехідники(80329), Кабелі USB(80333), Картриджі(80296),
Корпуси ПК(80038), Кулери ПК(80049), Чорнила(73126), Чохли телефон(4638562),
Захисні плівки(4638563), LED лампи(4638153), Світильники(4638228),
ЗП мобільні(4638593), USB Hub(80339), Килимки(80097), Контролери PCI(80052),
Запчасти/ін.(80038)

Пропагація на дочірні — запускати після кожного UPDATE батьків:
DO $$ DECLARE r INT; p INT := 0; BEGIN LOOP p := p+1;
  UPDATE katran_categories c SET rozetka_rz_id=pr.rozetka_rz_id,
    rozetka_category=pr.rozetka_category, commission_pct=pr.commission_pct
  FROM katran_categories pr WHERE c.parent_id=pr.id
    AND c.rozetka_rz_id IS NULL AND pr.rozetka_rz_id IS NOT NULL;
  GET DIAGNOSTICS r = ROW_COUNT; EXIT WHEN r=0 OR p>=5; END LOOP; END $$;

## Нові завдання (Катран)
1. agents/orders/katran_xml_generator.py — генерує XML фід Розетки з фіду Катрана
2. data/katran_rozetka.xml — вихідний XML (пушити на GitHub окреме посилання)
3. agents/orders/katran_github_sync.py — щогодинна синхронізація (як rozetka_github_sync.py)
4. agents/orders/katran_order_agent.py — агент замовлень (пізніше)

## Розетка — важливо
- api-seller.rozetka.com.ua (з дефісом) — правильний base URL
- api.seller.rozetka.com.ua (без дефісу) — повертає 404
- Статичний API токен gapi_... діє поки є активність раз на добу
- Фід оновлюється Розеткою раз на годину автоматично
- Для реального часу: PUT /items/update-price-stock/{owox_id} {"stock_quantity": 0}
- owox_id отримати: GET /items/search?article={артикул}

## Правила роботи Claude Code (завжди читати!)
1. На початку кожної сесії прочитати цей файл повністю
2. Перед роботою з файлами перевірити: cat shared/knowledge_base/rozetka/index.md
3. Скрипти що потребують openpyxl/sentence-transformers — запускати на ноутбуці
4. Скрипти без AVX залежностей — можна на сервері через venv/bin/python3
5. Після написання скрипту — перевірити синтаксис: python3 -c "import ast; ast.parse(open('file.py').read())"
6. Перед git push — переконатись що скрипт протестований
7. Нові постачальники додаються в shared/knowledge_base/supplier/
8. Маппінг категорій зберігається в БД таблиці katran_categories

## Файли що треба читати перед розробкою
- CLAUDE.md (цей файл)
- shared/knowledge_base/rozetka/xml_requirements.txt
- shared/knowledge_base/rozetka/api_full.txt
- shared/knowledge_base/supplier/katran_rozetka_mapping.txt
- data/carvol_rozetka.xml (еталон XML формату)

## TODO (наступна сесія)
- Підтвердити ~ категорії через PriceCreator і зробити UPDATE + пропагацію (закриє ~60% товарів)
  URL: seller.rozetka.com.ua/gomer/pricevalidate/check/index
  Категорії для перевірки rz_id: Кабелі(80329), USB(80333), Картриджі(80296),
  Корпуси ПК(80038), Кулери(80049), Чорнила(73126), Чохли(4638562),
  Захисні плівки(4638563), LED лампи(4638153), Світильники(4638228),
  ЗП мобільні(4638593), USB Hub(80339), Килимки(80097), Контролери PCI(80052)
- Перевірити XML katran_rozetka.xml через валідатор Розетки
- Налаштувати друге GitHub посилання для Катрана в кабінеті Розетки (через менеджера Софію Івановську)
- Написати менеджеру Розетки про нове посилання на фід Катрана
- Виправити Молотки/Біти/Набори пневмо/Мультиметри для Єпіцентру
