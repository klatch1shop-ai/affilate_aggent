# Що ми ще не беремо з API майданчиків
Замір 09.10.2026

## Метод заміру і чому перші числа були хибні
Рахував тричі, перші два рази неправильно:

1. **Шукав шляхи з коду в доці.** Проґавив `orders/add-ttn`, бо він
   склеюється з `{ROZETKA_BASE}` і регулярка не бачила початок рядка.
2. **Шукав шляхи з доки в коді.** Порахував `content/prom_api_registry.py`
   як використання — а це *реєстр* методів, не їх вжиток.
3. Робоче: шукати задокументований шлях як рядок у коді, **виключивши
   реєстр і тести**.

Тому нижче — числа з третього заходу.

## Prom: 10 із 35
Джерело істини тепер у нас: `shared/knowledge_base/prom/openapi/`
(знято з `public-api.docs.prom.ua/documentation/index.yaml`). Ознака, що
джерело справжнє, — у ньому є `delivery/save_declaration_id`, якого немає
ні в чужих бібліотеках, ні у видачі пошуку.

**Родина `chat/*` — 7 методів, яких ми не знали.** Вона скасовує те, що я
записав 04.10 як неможливе:

| метод | що дає |
|---|---|
| `POST /chat/send_message` | **написати покупцю ПЕРШИМ** — по `user_id` або `room_ident` |
| `POST /chat/send_order_context` | те саме, але разом із карточкою замовлення |
| `GET /chat/messages_history` | історія з фільтром `status=new/read` і за датою |
| `GET /chat/rooms` | перелік кімнат, `buyer_client_id`, `last_message_id` |
| `chat/send_file`, `send_attachments`, `mark_message_read` | файли й позначки |

Читання `chat/rooms` і `chat/messages_history` перевірено живими викликами.
**Запис не перевірявся**: будь-яка проба — це повідомлення живій людині.

Решта нереалізованого: `orders/refund`, `orders/{id}/attach_receipt`,
`products/translation` (українська версія картки!), `groups/translation`,
`payment_options/list`, `delivery_options/list`, `order_status_options/list`,
`products/import_url` / `import_file` / `import/status`.

`content/prom_api_registry.py` складено 26.09 зі старішої специфікації і
знає 21 метод — застарів на 14, зокрема на весь чат. Його читає генератор
команд Telegram, тому СУПЕРБОТ про чат не знає.

## Rozetka: 24 шляхи з 340
Джерело істини — жива офіційна дока
`https://api-seller.rozetka.com.ua/apidoc/api_data.json`, копія в
`shared/knowledge_base/rozetka/apidoc/`. 340 унікальних шляхів, 356 пар
метод+шлях. З 19.09 додався один метод (`item-return/ticket/history`).

**Виправлення мого попереднього висновку.** Я писав, що дока неповна, бо в
ній немає нашого `orders/add-ttn`. Насправді **цього методу не існує**:
Rozetka віддає `5404 not_found` — той самий код, що на вигаданий шлях. У
логах 1 спроба, 0 успіхів. `rozetka_order_agent.set_ttn` щоразу марно стукає
туди й падає на fallback `PATCH /orders/{id}` з `{status: 61, ttn}`, який і
працює. Тобто на кожен запис ТТН ми робимо один завідомо провальний запит.

**Ще три мертвих шляхи** — у `shared/mcp_servers/rozetka_mcp.py`:
`/prices`, `/sites/current` (обидва `5404`) і `POST /orders/{id}/status`
(у доці немає). Плюс `GET /orders` існує, але віддає
`access_denied 1010` — нашому токену не дано цього права. Тобто цей
MCP-сервер здебільшого неробочий.

Розрізнення перевірено негативним контролем: `5404 not_found` = методу
немає, будь-яка інша помилка = метод є.

### Що варте уваги з невикористаного
* **`Ttn` + `TtnSetting`, 22 методи — не беремо жодного.** Серед них
  `POST /ttns/create-ttn`: Rozetka створює накладну сама. Перевірив живим
  викликом — `ttns/common-data` відповідає `error_nova_poshta 1101`, тобто
  метод працює, просто в кабінеті не заведено ключ НП
  (`ttn-settings/create-ttn-key`). Є й друк наклейок:
  `ttn-print/stickers`, `ttn-print/zebra`.
  Чи переходити — окреме питання: наша пряма інтеграція з НП дає контроль
  оплати, а чи дає його метод Rozetka, з доки не видно.
* **Відгуки й коментарі — 23 методи, не чіпаємо.** `market-reviews/*` з
  відповідями (`market-review-replies/reply`) та `item-comments/*`.
  Перевірив: `market-reviews/counts` і `item-comments/counts` відповідають
  `success=true` просто зараз. Це прямо впливає на рейтинг магазину.
* `Messages` — з 12 маємо лише пошук, лічильник і відкриття; немає
  `messages/create` (відповідь), `{id}/order-chat`, масових позначок.
* `Orders` — з 29 невикористаних цінні `prolong/{id}` (продовжити резерв),
  `update-delivery`, `update-receiver`, `generate-pdf/{id}`.
* `FeedbackController` (11) — звернення в підтримку Rozetka з коду.
* `Balances` (23) + `BalanceConsolidated` (11) + `BalanceLogistic` (10) —
  фінанси: взаєморозрахунки, логістичні списання. Не читаємо нічого, крім
  `balances/total`.
* `PrroModule` (16), `Ukrposhta` (25), `Meest` (9), `Octopus` (17) —
  фіскалізація й інші перевізники, нам поки не потрібні.

## Єпіцентр: 261 шлях у core-api
Публічної специфікації немає. Перелік витягнув з JS-бандла кабінету
`admin.epicentrm.com.ua/main.*.js` — фронтенд знає кожен метод, який кличе.
Копія: `shared/knowledge_base/epicentr/discovered/`.

Перехоплення XHR (`epicentr_cabinet.py --action intercept_api`) для цього не
годиться: воно жодного разу не доїхало до кінця, браузер падає з core dump.

Родини: pim 52 · mas 36 · oms 25 · deliveries 22 · billing 19 · users 16 ·
import 14 · payments 10 · checkbox 9 · решта по дрібному.

**Виправлення мого попереднього висновку.** Я писав, що довідник атрибутів
потребує токена merchant-api, якого в нас немає. Це хибно — він лежить на
**core-api**, куди наша сесія ходить щодня. Перевірено живими викликами:

| метод | відповідь |
|---|---|
| `GET /v2/pim/attribute-sets` | 200, **total 5521** |
| `GET /v2/pim/categories` | 200, total 4721 |
| `GET /v2/pim/categories/public` | 200 **без авторизації** |
| `GET /v4/oms/orders` | 200 |
| `GET /v4/oms/orders/total` | 200, `{"total":13}` |

Це безпосередньо стосується строку 31.12: ~1000 карток блокують атрибути, а
офіційний довідник допустимих значень нам доступний уже зараз.

### Інше цінне з невикористаного
* **`/v4/oms/orders` новіша за нашу `/v3`.** Ми беремо v3 для переліку і v5
  для одного замовлення (v6 втрачає `office.externalId`). v4 ще не звіряв —
  треба порівняти поля, перш ніж переходити.
* `/v2/oms/orders/{id}/comments`, `/call-status`, `/call-client`,
  `/call-company`, `/assignee`, `/cancel-payment`,
  `/v1/oms/orders/{number}/feedback`.
* `/v2/oms/orders/{id}/history` **недоступна нам**: відповідь
  `No route found for "GET https://em--oms--order-service…"` — метод є в
  кабінеті, але не в нашому сервісі.
* `import` (14) — програмне завантаження фідів замість ручного.
* `billing` (19) + `payments` (10) — взаєморозрахунки.

### merchant-api — окремо
Наша копія swagger має 25 шляхів / 27 операцій, але вона **неповна**: у
довідці постачальника описані `POST /v1/offers` і
`GET /v1/offers/update-results/{requestId}`, яких у ній немає. Токена до
merchant-api в нас немає; повну специфікацію дають за запитом на
`merchant@epicentrk.ua`.

## Що з цього роблю далі
За ціною результату:

1. **Атрибути Єпіцентру з `/v2/pim/attribute-sets`** — єдине, що прямо
   працює на строк 31.12. Доступ є вже зараз.
2. Прибрати три мертвих виклики (`orders/add-ttn`, `/prices`,
   `/sites/current`) — зайві запити й хибні попередження в логах.
   Це зміна в `rozetka_order_agent.py`, тобто в NOIRE: чекає дозволу.
3. Перенести реєстр Prom на свіжу специфікацію (21 → 35), щоб СУПЕРБОТ
   побачив чат.
4. Команда «написати покупцю» через `chat/send_message` — з перевіркою на
   безпечній кімнаті, не на випадковому покупці.
5. Відгуки й коментарі Rozetka — 23 методи, які впливають на рейтинг.
6. Порівняти `/v4/oms/orders` з нашою v3, перш ніж переходити.

## Чого я НЕ знаю
* Чи дає `POST /ttns/create-ttn` Rozetka контроль оплати — з доки не видно.
* Чи `/v4/oms/orders` Єпіцентру віддає `office.externalId` (v6 втрачає).
* Повний перелік merchant-api Єпіцентру — потрібен запит у підтримку.
* Що саме віддають 36 методів родини `mas` Єпіцентру — з назв не ясно.
