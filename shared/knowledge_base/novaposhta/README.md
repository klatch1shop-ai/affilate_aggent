# Нова Пошта: API для створення накладних (ТТН)

Зібрано 13.09.2026 для задачі: створювати ТТН для замовлень NOIRE, почати з
Rozetka (дані для ТТН — із замовлення Rozetka). Кроки створення — за
покроковими інструкціями власника; нижче — довідка, що є і як влаштовано.

## 0. Що лежить у цій теці

| Шлях | Що це |
|---|---|
| `README.md` | цей довідник: методи, сценарій, відповідність полів Rozetka → НП |
| `reference/*.json` | довідники, взяті з живого API 13.09 (типи вантажу, послуг, платників, форм оплати, пакування 86, форм власності 107, описів вантажу 500, типів відділень, приклад пошуку міста) |
| `api_v2_reference/` | вихідний код і README відкритої бібліотеки `lis-dev/nova-poshta-api-2` (PHP) — найповніша доступна копія класичного API 2.0: точні `modelName`/`calledMethod`, параметри, повний сценарій створення ТТН, друк |
| `portal_novapost/llms-full.md` | ПОВНИЙ вміст нового порталу `api-portal.novapost.com` (1,5 МБ, markdown): новий міжнародний Nova Post API (JWT), чеклісти COD / безготівка / адреса / поштомат, готові інтеграції |
| `portal_novapost/llms.txt`, `sitemap.xml` | зміст і карта того порталу |

Класичний портал `developers.novaposhta.ua` / `devcenter.novaposhta.ua`
13.09.2026 для автоматичного завантаження недоступний (403 / помилка SSL
навіть із сервера) — тому класичний API задокументовано через код
бібліотеки й перевірено запитами до живого API.

## 1. Два різні API — який нам

| | **Класичний API 2.0** — наш | Новий Nova Post API |
|---|---|---|
| Адреса | `POST https://api.novaposhta.ua/v2.0/json/` | `api-portal.novapost.com` (кілька endpoint-ів) |
| Автентифікація | `apiKey` у тілі запиту (ключ з кабінету НП → Налаштування) | JWT-токен, згенерований з ключа |
| Для чого | ТТН по Україні, відділення/поштомати, зворотна доставка (післяплата), друк | переважно міжнародні відправлення |
| Хто ним користується | модуль «Нова Пошта» в кабінеті Rozetka (той самий API-ключ) | — |

Ключ класичного API вже є: `NP_API_KEY` у `.env` на сервері; на ньому
`agents/orders/np_api.py` (лише відстеження ТТН). Перевірено 13.09: ключ
робочий, в акаунті **1 відправник, тип «Приватна особа»**.

## 2. Формат запиту

```json
POST https://api.novaposhta.ua/v2.0/json/
{
  "apiKey": "<NP_API_KEY>",
  "modelName": "InternetDocument",
  "calledMethod": "save",
  "methodProperties": { ... }
}
```

Відповідь: `{"success": true|false, "data": [...], "errors": [...],
"warnings": [...], "info": {...}, "errorCodes": [...]}`. Помилка — не HTTP-код,
а `success: false` + текст у `errors`. Код `20000401501` — перевищено
частоту запитів (повторити з паузою).

## 3. Методи класичного API 2.0

| Модель | Методи | Навіщо нам |
|---|---|---|
| `Address` | `searchSettlements`, `getCities`, `getSettlements`, `getWarehouses`, `getWarehouseTypes`, `searchSettlementStreets`, `getStreet`, `getAreas`, `save`/`update`/`delete` (адреса контрагента) | місто й відділення одержувача (якщо Rozetka не дала `ref_id`) |
| `Counterparty` | `getCounterparties` (`CounterpartyProperty`: `Sender`/`Recipient`), `getCounterpartyContactPersons`, `getCounterpartyAddresses`, `getCounterpartyOptions`, `save`, `update`, `delete` | наш відправник (Ref, контактна особа, адреса); створення одержувача |
| `ContactPerson` | `save`, `update`, `delete` | контактна особа контрагента |
| `InternetDocument` | `getDocumentPrice`, `getDocumentDeliveryDate`, **`save`**, `update`, `delete`, `getDocument`, `getDocumentList`, `printDocument`, `printMarking85x85` / `printMarking100x100`, `generateReport` | розрахунок, **створення ТТН**, виправлення, видалення, друк |
| `ScanSheet` | `insertDocuments`, `getScanSheetList`, `getScanSheet`, `removeDocuments`, `deleteScanSheet` | реєстри (кілька ТТН в одну передачу) |
| `TrackingDocument` | `getStatusDocuments` (до 100 ТТН, для деталей — `Phone`) | відстеження (вже в `np_api.py`) |
| `Common` | `getCargoTypes`, `getServiceTypes`, `getTypesOfPayers`, `getPaymentForms`, `getTypesOfCounterparties`, `getBackwardDeliveryCargoTypes`, `getTypesOfPayersForRedelivery`, `getPackList`, `getTiresWheelsList`, `getPalletsList`, `getOwnershipFormsList`, `getCargoDescriptionList`, `getTimeIntervals`, `getMessageCodeText` | довідники (збережено в `reference/`) |
| `AdditionalService` | повернення, переадресація, зміна даних ТТН (`checkPossibility*`, `save`, `delete`, `get*OrdersList`) | після відправлення |

Довідники (з живого API 13.09):

* `CargoType`: `Parcel` Посилка · `Cargo` Вантаж · `Documents` Документи · `TiresWheels` · `Pallet`
* `ServiceType`: `WarehouseWarehouse` Відділення-Відділення · `WarehouseDoors` · `DoorsWarehouse` · `DoorsDoors` · `WarehousePostomat` · `DoorsPostomat`
* `PayerType` (хто платить за доставку): `Sender` · `Recipient` · `ThirdPerson`
* `PaymentMethod`: `Cash` · `NonCash`
* `CounterpartyType`: `PrivatePerson` · `Organization`
* зворотна доставка `BackwardDeliveryData[].CargoType`: `Money` (грошовий переказ = післяплата) · `Documents`; платник — `Sender`/`Recipient`/`ThirdPerson`
* типи відділень: Поштове, Вантажне, Поштомат, Поштомат ПриватБанку, Поштове з обмеженнями

## 4. Сценарій створення ТТН (відділення → відділення)

1. **Відправник (один раз, можна кешувати):**
   `Counterparty.getCounterparties {CounterpartyProperty: "Sender"}` → `Sender` (Ref);
   `Counterparty.getCounterpartyContactPersons {Ref}` → `ContactSender` + телефон;
   місто й відділення відправлення → `CitySender`, `SenderAddress` (Ref відділення).
2. **Одержувач:**
   місто й відділення — з Rozetka (див. §5) або через `Address.searchSettlements` +
   `Address.getWarehouses`; контрагент — `Counterparty.save
   {CounterpartyType: "PrivatePerson", CounterpartyProperty: "Recipient",
   FirstName, LastName, MiddleName, Phone}` → `Recipient` і
   `ContactPerson.data[0].Ref` → `ContactRecipient`.
3. **(рекомендовано) розрахунок:** `InternetDocument.getDocumentPrice`,
   `getDocumentDeliveryDate` — перевірка параметрів без створення.
4. **Створення:** `InternetDocument.save` з полями:
   `PayerType`, `PaymentMethod`, `DateTime` (`дд.мм.рррр`), `CargoType`,
   `Weight`, `ServiceType`, `SeatsAmount`, `Description`, `Cost` (оголошена
   вартість), `CitySender`, `Sender`, `SenderAddress`, `ContactSender`,
   `SendersPhone`, `CityRecipient`, `Recipient`, `RecipientAddress`,
   `ContactRecipient`, `RecipientsPhone`; для не-документів — `VolumeGeneral`
   (м³) або `OptionsSeat` (габарити місць; для поштомата обов'язково:
   до 20 кг, до 40×60×30 см на місце). Післяплата — `BackwardDeliveryData:
   [{PayerType: "Recipient", CargoType: "Money", RedeliveryString: "<сума>"}]`
   (для юросіб є альтернатива «контроль оплати» `AfterpaymentOnGoodsCost`).
   Відповідь: `Ref`, **`IntDocNumber`** (номер ТТН), `CostOnSite`,
   `EstimatedDeliveryDate`.
5. **Друк:** посилання без запиту —
   `https://my.novaposhta.ua/orders/printDocument/orders[]/<Ref>/type/pdf/apiKey/<key>`,
   маркування — `.../printMarking100x100/orders[]/<Ref>/type/pdf/apiKey/<key>`.
6. **ТТН у Rozetka:** у агента вже є `set_ttn(order_id, ttn)`
   (`agents/orders/rozetka_order_agent.py`) — ставить ТТН у замовлення.
7. **Помилилися:** до сканування у відділенні — `InternetDocument.update`
   (з `Ref`) або `InternetDocument.delete {DocumentRefs: [Ref]}`.

Створення ТТН — реальна дія: номер резервується, у кабінеті НП і в Rozetka
видно. Перший прогін — лише розрахунок (`getDocumentPrice`), створення — за
рішенням власника на конкретному замовленні.

### Наш відправник (власник, 13.09.2026: «всі посилки відправляються з Дніпра, відділення 1»)

| Поле ТТН | Значення | Звідки |
|---|---|---|
| `CitySender` | `db5c88f0-391c-11dd-90d9-001a92567626` | `Address.getCities {FindByString: "Дніпро"}` |
| `SenderAddress` | `0d545f59-e1c2-11e3-8c4a-0050568002cf` — Відділення №1: вул. Повітряна, 2 | `Address.getWarehouses {CityRef, WarehouseId: "1"}` |
| `Sender` | `ab677114-0b71-11ef-bcd0-48df37b921da` (приватна особа, єдиний відправник в акаунті) | `Counterparty.getCounterparties {CounterpartyProperty: "Sender"}` |
| `ContactSender` | `ab67fc77-0b71-11ef-bcd0-48df37b921da` (телефон — з цієї ж відповіді, `Phones`) | `Counterparty.getCounterpartyContactPersons {Ref: Sender}` |

Збережених адрес у відправника в акаунті немає — відділення передається
в `SenderAddress` напряму.

**Перший розрахунок (лише читання, 13.09):** Дніпро №1 → Київ №391,
посилка 0,5 кг, оголошена вартість 2879 грн, відділення-відділення:
`getDocumentPrice` → **104,40 грн**; `getDocumentDeliveryDate` → **15.09.2026 18:00**.

**Пастка:** `Address.getWarehouses {Ref}` один раз повернув порожній
`data` при `success: true`, повтор за 2 с — нормальна відповідь.
Порожня відповідь ≠ «відділення немає»: повторювати з паузою, лише потім
переходити на запасний пошук.

### Інструмент і перша ТТН (13.09.2026)

`tools/np_create_ttn.py <order_id>` — розрахунок; `--create` — створити ТТН,
зберегти наклейку 100×100 (PDF у `shared/feeds/orders/np_ttn/`) і надіслати
в Telegram. Параметри за вказівками власника: платник — одержувач, готівка;
посилка 2 кг («до 2 кг»), `VolumeGeneral` 0.002; оголошена вартість = сума
замовлення; опис «Косметика»; післяплата лише для оплати при отриманні;
`InfoRegClientBarcodes` = номер замовлення Rozetka. Зупиняється ДО
створення, якщо: доставка не НП, у замовленні вже є ТТН, невідомий спосіб
оплати, відділення не знайшлось чи номер не збігся, немає ПІБ/телефону.
ТТН у замовлення Rozetka НЕ ставить (статус → 61) — окремий крок.

Перша ТТН: **20451535086672** для Rozetka #905931436 (Apple Pay, без
післяплати) — перевірено через `getStatusDocuments`: Дніпро №1 → Київ №391,
платник одержувач, 2 кг, оголошена 2879, доставка 104,40 грн, опис
«Косметика», статус 1 «створена, ще не передана до відправки».

### Порівняння з ТТН, які власник створює вручну в кабінеті НП (13.09.2026)

`InternetDocument.getDocumentList` (45 днів, 12 ТТН); 6 NOIRE-ТТН власника
(9–11.09, канал `PA 3.0`/`NPEU` — кабінет/сайт НП) проти моєї (`API2`).

Однаково: вага 2 кг, 1 місце, `Parcel`, `WarehouseWarehouse`, платник
одержувач готівкою, відправник Дніпро №1, оголошена вартість = сума
замовлення, післяплата «Гроші» лише при оплаті при отриманні (2 з 6).

Відрізняється:
* **опис**: у власника — коротка назва товару («Satisfyer Juicy», «Pjur
  Woman», «Тренажер», «Гартери», «Подарунковий набір»); у мене —
  «Косметика» (за вказівкою «нейтрально») — уточнити, що бажано;
* **номер замовлення** (`InfoRegClientBarcodes`): у мене — № Rozetka, у
  власника порожньо;
* **куди**: 4 з 6 у власника — поштомати, 1 — пункт приймання-видачі
  (`DeliveryTo: Store`), 1 — відділення; у мене — відділення. Для поштомата
  API вимагає `OptionsSeat` (габарити, ≤20 кг, ≤40×60×30 см) — у
  `np_create_ttn.py` ще немає, потрібен стандартний розмір коробки.

**Повне порівняння всіх полів (13.09, 2-й прохід).** Крім опису, номера
замовлення, типу точки й каналу створення, є ще дві відмінності:
* **габарити**: у всіх 6 ТТН власника `OptionsSeat` 30×20×10 см
  (0,006 м³, об'ємна вага 1,5 кг, вага 2); у моїй лише `VolumeGeneral`
  0,002 → у `np_create_ttn.py` тепер `OptionsSeat` з цією коробкою (він же
  потрібен для поштоматів);
* **післяплата на карту**: у обох ТТН власника з післяплатою гроші йдуть на
  карту (`RedeliveryPaymentCard.CardMaskedNumber`), причому на **різні**:
  `432334xxxxxx6356` (20451533331993, `RedeliveryPaymentCardRef`
  `e8774818-7332-4b64-9dc2-6ed312386d59`) і `432334xxxxxx7406`
  (20451531603272, `a706760f-8aa8-416f-ad82-269a724ac3e5`). Видно в
  `getDocumentList` (`RedeliveryPaymentCard`) і в
  `TrackingDocument.getStatusDocuments` з телефоном відправника
  (`CardMaskedNumber`, `RedeliveryPaymentCardRef`).
  **Як задати карту через API — не підтверджено:** офіційна сторінка
  `InternetDocument.save` за Cloudflare (403 і з ноутбука, і з сервера);
  список карт `Payment.getCards` є, але відповідає «Please update the
  application» (лише для застосунку НП). Єдиний знайдений приклад
  (GitHub vladyslav-yarko/bloom-art) — `BackwardDeliveryData[].RecipientBankCard`
  = повний номер карти. Коди помилок НП підтверджують, що карта в
  зворотній доставці через API існує: 20000201486 «BackwardDelivery Money
  with PaymentCard is too high» (ліміт 14 999 грн), 20000201487 «PayerType
  with PaymentCard must be Recipient». Проба `save` без одержувача нічого не
  дала — НП зупиняє перевірку на `Recipient not selected` раніше, ніж
  доходить до зворотної доставки. Перевірити можна лише справжньою ТТН.

  **Перевірено справжньою ТТН (13.09, з дозволу власника):** тестова ТТН
  20451535093446 з післяплатою 100 грн на власника (Дніпро №1 → №2):
  1. без поля карти НП карту **не** ставить (`CardMaskedNumber` порожній) —
     «перша карта за замовчуванням» не спрацьовує;
  2. через `InternetDocument.update` перебрано 9 назв поля з Ref карти:
     8 НП мовчки ігнорує, **лише `BackwardDeliveryData[].PaymentCard`**
     розпізнано — помилка `20000201794` «BackwardDeliveryMoney to payment
     card is temporary blocked»;
  3. `save` з `PaymentCard` — та сама помилка для обох справжніх Ref карт
     і для вигаданих значень → блок **не залежить від карти**, це
     обмеження НП для нашого API-ключа (у кабінеті `PA 3.0`/`NPEU` карта
     ставиться). ТТН не створювались;
  4. тестову ТТН видалено `InternetDocument.delete` — success.
  Висновок: поле — `BackwardDeliveryData[].PaymentCard` = Ref карти
  (`RedeliveryPaymentCardRef` з трекінгу); доки НП не зніме блок,
  ТТН з післяплатою на карту через API не створити.

  **Повний номер карти (власник дав 13.09, збережено лише в `.env` як
  `NP_COD_CARD`):** тестова ТТН 20451535095094 (видалена): `save` з
  `PaymentCard` = повний номер → та сама 20000201794; `update` з повним
  номером у `RecipientBankCard`, `CardNumber`, `Card`, `BankCard`,
  `RedeliveryPaymentCard` (у `BackwardDeliveryData` і на верхньому рівні) —
  НП мовчки ігнорує, карта не з'являється. `np_create_ttn.py` передає
  `PaymentCard` = `NP_COD_CARD`; поки блок діє, `save` відхиляється і ТТН
  не створюється (скрипт пише «створіть вручну»); коли НП зніме блок —
  запрацює без змін коду.

  Довідник кодів помилок порталу (власник, 13.09): `20000201794` —
  «Зворотня доставка грошей на карту, тимчасово заблокована». Умов зняття
  блоку там немає — питання до підтримки НП (support@novaposhta.ua,
  067-535-59-84).

  **Рішення власника (13.09):** поки блок — створювати ТТН **без
  післяплати**, а в Telegram писати «додайте післяплату N грн» (власник
  додає в кабінеті до відправки й передруковує наклейку). Скрипт спершу
  пробує з карткою; на 20000201794 — повторює без `BackwardDeliveryData`.
  Далі власник реєструється як ФОП, говорить з менеджером НП і **змінить
  API-ключ** — тоді перевірити блок заново.

Закрито: `ref_id` «1 (АО7507НН)» (#905699729) — справжній Ref пункту
приймання-видачі (ТТН власника 20451533331993 йде саме туди); порожня
відповідь `getWarehouses` була тимчасовою.

## 5. Звідки брати дані з замовлення Rozetka

`GET /orders/{id}?expand=delivery,purchases,payment` (перевірено 13.09 на
двох замовленнях NOIRE, лише читанням):

| Поле ТТН | Rozetka | Примітка |
|---|---|---|
| `RecipientAddress` (Ref відділення НП) | `delivery.ref_id` | **перевірено**: для відділення 391 (Київ) `ref_id` = Ref відділення в НП, номер збігся |
| `CityRecipient` | `Address.getWarehouses {Ref: ref_id}` → `CityRef` | місто береться з відділення |
| номер відділення | `delivery.place_number` | для звірки |
| прізвище / ім'я / по батькові | `delivery.recipient_last_name` / `recipient_first_name` / `recipient_second_name` | |
| `RecipientsPhone` | `delivery.recipient_phone` (або `recipient_phone`) | |
| перевізник | `delivery.delivery_service_id` = 5 (Нова Пошта в обох замовленнях) | |
| `Weight` | `purchases[].item.weight` × `quantity` | 0,5 кг і 0,15 кг у прикладах |
| `Cost` (оголошена вартість) | `amount` / `cost_with_discount` | |
| `Description` | `purchases[].item_name` | |
| післяплата | `payment` (`payment_type`: `cash` = післяплата; `apple_pay`/картка — оплачено онлайн) | див. агент: `payment_paid()` |

### Правило власника: післяплата (13.09.2026)

* замовлення **оплачене** (картка / Apple Pay / Google Pay — Rozetka віддає
  `payment.payment_status.name == "paid"`) → ТТН **без** післяплати;
* **оплата при отриманні** (`payment_type` = `cash` / `cod`) → ТТН **з**
  післяплатою: `BackwardDeliveryData: [{PayerType: "Recipient",
  CargoType: "Money", RedeliveryString: "<сума замовлення>"}]`;
* «оплата на рахунок продавця» (`no_cash`) — Rozetka оплату не бачить;
  як оформлювати — уточнити у власника (відкрите).

Перший кандидат (13.09): #905931436 — Apple Pay, оплачено → без
післяплати; відділення НП №391 Київ (`ref_id` перевірено), SX3638 × 1,
0,5 кг, 2879 грн.

**Закрито (див. порівняння вище):** у другому замовленні (`place_number` «1 (АО7507НН)»)
`ref_id` у НП не знайшовся — потрібен запасний шлях: місто
(`delivery.city.name_ua` → `Address.searchSettlements`) + номер відділення
(`Address.getWarehouses {CityRef, WarehouseId}`) і з'ясувати, що означає
позначка в дужках.

## 6. Джерела

* Бібліотека `lis-dev/nova-poshta-api-2` (MIT) — https://github.com/lis-dev/nova-poshta-api-2 (збережено в `api_v2_reference/`)
* Go SDK — https://pkg.go.dev/github.com/platx/go-nova-poshta/api/internetdocument (поля `Save`/`SaveWarehouse`, відповідь `IntDocNumber`, `CostOnSite`)
* MCP-сервер НП (перелік операцій і обмежень: поштомат 20 кг / 40×60×30, код частоти `20000401501`) — https://github.com/shopanaio/carrier-api/tree/main/packages/novaposhta-mcp-server
* Новий портал Nova Post — https://api-portal.novapost.com/ (збережено повністю в `portal_novapost/`)
* Довідка Rozetka «Модуль Нова Пошта» — `shared/knowledge_base/rozetka/sellerhelp/p314-module-novaposhta.txt`
* Живий API, 13.09.2026: довідники `Common.*`, `Address.getWarehouses {Ref}` для `ref_id` з Rozetka
