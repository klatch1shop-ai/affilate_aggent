# Павутина команд: дії × канали × методи API

Складено 03.10.2026 за завданням TASK-37. **Кожен рядок підтверджений
справжнім викликом**, не документацією і не памʼяттю (скіл
`measuring-before-reporting`).

## Як відрізняли «метод є» від «методу немає»

Кожен канал відповідає по-своєму, тому для кожного знайдено **відʼємний
контроль** — свідомо вигаданий шлях, і все, що відповідає так само, як він,
вважається відсутнім.

| канал | відповідь на вигаданий шлях | що це означає |
|---|---|---|
| Rozetka | HTTP **200**, `{'code': 5404, 'message': 'not_found'}` | 200 ≠ метод існує; дивитись у `errors` |
| Єпіцентр | HTTP 404, `{"message":"No route configured"}` | а от `entity.not_found` означає, що метод Є |
| Нова Пошта | HTTP 200, `success: false`, текст у `errors` | розрізняти «немає методу» і «бракує параметра» |
| Prom | HTTP 404 | звичайна поведінка |

Без цього контролю Rozetka дала б «працюють 12 з 12», хоча насправді чотири.

## Нова Пошта — 11 методів підтверджено

| метод | що дає |
|---|---|
| `Address.getCities` | міста за назвою |
| `Address.getWarehouses` | відділення; **приймає `Ref` відділення напряму** |
| `Address.getAreas` | 25 областей |
| `Address.searchSettlements` | населені пункти |
| `Counterparty.getCounterparties` | наші контрагенти |
| `Common.getCargoTypes` | 5 типів вантажу |
| `Common.getPaymentForms` | 2 форми оплати |
| `Common.getServiceTypes` | 6 типів доставки |
| `Common.getTypesOfPayers` | 3 платники |
| `Common.getBackwardDeliveryCargoTypes` | **лише «Документи» і «Грошовий переказ»** |
| `TrackingDocument.getStatusDocuments` | статус за номером ТТН |
| `AdditionalService.getReturnReasons` | причини повернення |

`Common.getTimeIntervals` і `InternetDocument.getDocumentPrice` відповіли
помилкою через **порожні параметри в моєму запиті**, а не через відсутність —
це різні речі, і так це й записано.

### Контроль оплати (виправлено 03.10)

Картку вказувати **не треба**. Довідник знає лише «Документи» і «Грошовий
переказ», поля для карти немає. Код слав `PaymentCard`, і саме переказ на
карту блокувався помилкою 20000201794 — звідси пішов хибний висновок «НП
блокує післяплату через API», який коштував півтора місяця ручної роботи.
`tools/np_create_ttn.py` виправлено; **підтвердження потребує однієї
справжньої ТТН**.

## Rozetka — 4 методи з 30 перевірених

| метод | стан |
|---|---|
| `GET /orders/search` | працює, повертає замовлення з доставкою |
| `GET /goods/all` | працює |
| `GET /goods/prices` | працює |
| `GET /messages/search` | працює |
| `GET /messages` | **існує, але `1010 access_denied`** — токену бракує прав |
| `GET /promotions` | існує, доступ заборонено |
| решта 25 (`/categories`, `/comments`, `/orders/statuses`, `/goods/getstocks`, …) | `5404 not_found`, як у вигаданого шляху |

## Єпіцентр — дві бази й РІЗНІ версії шляхів

Логін: `POST core-api/v2/users/login` з email і паролем → `token.auth`.

| база | метод | стан |
|---|---|---|
| `core-api` | `/v2/pim/products` | працює; курсорна пагінація через `next`, `page` ігнорується |
| `core-api` | `/v2/pim/categories` | працює |
| `core-api` | `/v2/pim/attribute-sets` | працює |
| `core-api` | `/v2/pim/products/{id}/comments` | працює (на вигаданому id дає `entity.not_found` — ознака, що метод Є) |
| `core-api` | `/v3/oms/orders`, `/v4/oms/orders` | **працюють обидві версії** |
| `core-api` | `/v2/oms/orders`, `/v5/oms/orders` | немає |
| `merchant-api` | `/v3/oms/orders/{id}`, `/v5/oms/orders/{id}` | використовуються робочим кодом |
| `core-api` | `/v2/pim/attributes`, `/v2/pim/brands`, `/v2/users/me` | немає |

Версія шляху — не дрібниця: `/v2/oms/orders` не існує, `/v3` і `/v4` існують.

## Prom — 7 методів

`/products/list`, `/groups/list`, `/orders/list`, `/messages/list`,
`/clients/list`, `/delivery_options/list`, `/payment_options/list`.
Аналітики пошукових запитів **немає взагалі**.

`/products/list` віддає `keywords` (рос.), але **не віддає `keywords_ua`** —
замір «по API» дає хибний нуль українських ключів.

## Інтеграція маркетплейсів із Новою Поштою

**Rozetka → НП, підтверджено викликом:** у замовленні поле
`delivery.ref_id` — це **справжній `Ref` відділення Нової Пошти**. Перевірено:
`47402ea2-e1c2-11e3-8c4a-0050568002cf` → `Address.getWarehouses(Ref=…)` →
«Відділення №72 (до 30 кг): вул. Бульварно-Кудрявська, 72». Шукати відділення
за адресою не потрібно.

`delivery.pickup_rz_id` і `delivery.city.uuid` — внутрішні ідентифікатори
Rozetka, у довіднику НП їх немає.

Інші корисні поля замовлення Rozetka: `delivery_service_id` (5 = Нова Пошта),
`delivery_service_name`, `name_logo` (`nova-pochta`), `recipient_first_name`,
`recipient_last_name`, `recipient_second_name`, `recipient_phone`,
`place_street`, `place_number`, `pickup_type`.

## Дірки між каналами

| дія | Prom | Rozetka | Єпіцентр | НП |
|---|---|---|---|---|
| прочитати замовлення | `/orders/list` | `/orders/search` | `/v3/oms/orders` | — |
| змінити статус замовлення | не знайдено | не знайдено | `change-status/to/{status}` | — |
| прочитати чати покупців | `/messages/list` | `/messages/search` | — | — |
| оновити залишки | лише фідом | лише фідом | лише фідом | — |
| створити ТТН | — | — | — | `InternetDocument.save` |
| статус посилки | — | — | — | `TrackingDocument` |

**Головна дірка:** оновлення залишків ніде не робиться методом API — лише
фідом. Саме тому 02.10 TOPTUL і dropoffice місяць стояли без синхронізації:
для NOIRE фідову синхронізацію написали окремо, а для решти не написали.
Виправлено `tools/feed_stock_sync.py` з профілями.

## Що лишилось

- [ ] токен ФОП Нової Пошти від власника → перевірити контроль оплати справжньою ТТН
- [ ] підтвердити методи зміни статусу замовлень на Prom і Rozetka
- [ ] схема бекенду: один шар дій над каналами
