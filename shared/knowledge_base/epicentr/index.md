# Єпіцентр Маркетплейс — База знань

## Офіційна документація (supportm.epicentrk.ua)

### Товари та контент
- Загальні вимоги: https://supportm.epicentrk.ua/zagalnivymogydokontentu/
- Фото: https://supportm.epicentrk.ua/vymogydovizualnogokontentuyakpravylnoobratyzobrazhennyavashogotovaru/
- Категорії та бренди: https://supportm.epicentrk.ua/categoriitabrendytovariv/
- Дерево категорій (4054 в БД): SELECT * FROM epicentr_categories
- Стоп-категорії: https://docs.google.com/spreadsheets/d/1noX89UVVWcTaQ4ve89ybUKcxwWaPVcjqu1ErbY_yqNE/

### Імпорт/Експорт
- Імпорт з Prom: https://supportm.epicentrk.ua/importprom/
- Експорт товарів: https://supportm.epicentrk.ua/eksporttovariv/
- Комісії публічно: https://admin.epicentrm.com.ua/public/commissions

### Замовлення
- Оплата Monobank: https://supportm.epicentrk.ua/opratsiuvannia-zamovlen-zi-sposobom-oplaty-Monobank/

### Доступи
- Кабінет: https://admin.epicentrm.com.ua
- Контакт: e.tambovskiy@epicentrk.ua (Євгеній Тамбовський)
- Тариф: 120 грн/місяць з БАЛАНСУ ПОСЛУГ (не основного!)

### CPA ставки (таблиця epicentr_cpa_rates, 236 категорій)
- Інструменти та обладнання: 10%
- Ручний інструмент: 15%
- Електроінструменти: 15%
- Станки та промислове обладнання: 10%
- Мотобури: 18%

## API оновлення цін і наявності — `POST /v1/offers` (з'явилось 09.2026)

Повний текст: [api_offers_update.txt](api_offers_update.txt) (збережено 19.09.2026).
Джерело: https://supportm.epicentrk.ua/robota-z-endpointamy-api-onovlennia-tsin-ta-naiavnosti/

**Перевірено 19.09.2026 (лише читання):** `GET /v1/offers/update-results/<вигаданий id>` з нашим
`EPICENTR_TOKEN` → 404 `batch_update_request.request_id.invalid`, не 401/403. Тобто метод
існує і ключ його приймає. **Запис (`POST /v1/offers`) не пробували.**

Головне з довідки:
- `POST /v1/offers` `{"items": [{"productId"|"sku", "prices": {"price", "oldPrice"?}, "availability"?}]}`;
  від 1 до 1000 записів; ліміт — 120 запитів / 120 с. Обробка асинхронна → `requestId`.
- `GET /v1/offers/update-results/{requestId}` — статус КОЖНОГО запису, зберігається 14 діб
  (404 — застарілий/невідомий, 403 — чужий, 429 — ліміт).
- Статуси: `enqueued`, `processed`, `skipped` (дубль або значення вже актуальне), `forbidden`
  (помилка в даних або чужий артикул).
- `sku` має **повністю** збігатися з полем «Артикул» у кабінеті; якщо передано й `productId`,
  `sku` ігнорується.
- Наявність — лише `in_stock` / `under_the_order` / `not_available`.
- Ціна > 0, до 2 знаків; `oldPrice` лише разом з `price` і більша за неї. Ціну товару в
  акції змінити не можна (`batch_update.price.product_in_promotion`).
- Надсилати лише ЗМІНИ: незмінені записи «затримують обробку коректних».

**Розбіжності й застереження:**
1. Довідка суперечить сама собі: «до 1000 у списку», але помилка `validation.count.max`
   описана як «більше 200». Доки не підтверджено — пачки по **200**.
2. У XML-фіді наявності (`tools/noire_epicentr_stock_feed.py`) ми пишемо `out_of_stock` разом з
   `available="false"`. В API такого значення нема (там `not_available`). Для XML-імпорту це
   не означає помилку, але при переході на API — лише `not_available`.
3. Правило власника про ціну діє і тут: не нижче роздрібної ціни постачальника (`price-floor-no-dumping`).

**Чим API краще за наш фід наявності (зараз: `noire_stock_sync.py --publish-epicentr-stock`,
кожні 2 год, 13 054 офферів у GitHub `noire-feed`, Епіцентр забирає за власним розкладом):**
- видно результат по кожному артикулу (`forbidden`/`skipped`), а з фідом ми сліпі;
- зміна потрапляє в чергу одразу, а не коли Епіцентр прочитає файл;
- дельта замість 13 тис. записів щоразу.

Перехід — лише з дозволу власника: це запис у кабінет (правило AGENT_RULES і
`feedback-epicentr-validation`). Спершу пробна пачка з 1–3 артикулів і перевірка через
`update-results`, потім порівняння з кабінетом.
