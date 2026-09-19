# Rozetka Seller API — покажчик методів

Джерело: https://api-seller.rozetka.com.ua/apidoc/ (`api_data.json`, завантажено 19.09.2026).
Унікальних методів: 356 (з версіями — 529). Повні параметри — `api_data.json` (поле `parameter.fields`).

**Перевірені пастки (19.09):** `GET /messages/{id}` позначає чат ПРОЧИТАНИМ — читати лише `/messages/search?expand=messages`;
без `msgType` пошук віддає тільки чати по товарах — `msgType=orders` для питань по замовленнях, `deleted` для видалених.

## Модуль "Товари"

| метод | шлях | що робить |
|---|---|---|
| GET | `/goods/all` | 1.0 Всі товари |
| GET | `/goods/archive` | 1.9 Архівні товари |
| GET | `/goods/changes` | 1.7 Оновлені товари |
| GET | `/goods/changes-details` | 7.1 Деталі зміненого товару |
| GET | `/goods/counts` | 0.0 Лічильники товарів |
| GET | `/goods/details` | 7.0 Деталі товару |
| GET | `/goods/errors` | 1.3 Товари з помилками |
| GET | `/goods/hidden` | 1.5 Приховані товари |
| GET | `/goods/moderation` | 1.8 Товари на модерації |
| GET | `/goods/new` | 1.6 Нові товари |
| GET | `/goods/not-available` | 1.2 Неактивні товари |
| GET | `/goods/not-valid` | 1.4 Невалідні товари |
| GET | `/goods/on-sale` | 1.1 Активні товари |
| GET | `/goods/prices` | 1.7.1 Оновлені ціни |
| GET | `/goods/quarantine` | 1.7.2 Товари, що не потрапили в діапазон ціни |
| GET | `/goods/search-data` | 2.0 Дані для фільтрів |
| GET | `/goods/search-data/category` | 2.1.0 Дані для фільтрів: категорії продавця |
| GET | `/goods/search-data/producer` | 2.2.0 Дані для фільтрів: виробники продавця |
| GET | `/goods/search-data/rz-category` | 2.1.1 Дані для фільтрів: категорії в системі Розетка Маркетплейс |
| GET | `/goods/search-data/rz-producer` | 2.2.1 Дані для фільтрів: виробники в системі Розетка Маркетплейс |
| POST | `/items-file-import/create-items` | 9.2 Створити товари через файл |
| GET | `/items-file-import/import-status` | 9.4 Отримати статус імпорту товарів |
| GET | `/items-file-import/imports-list` | 9.5 Отримати список статусів імпорту товарів |
| GET | `/items-file-import/template` | 9.1 Отримати шаблон xls для імпортування товарів |
| POST | `/items-file-import/update-items` | 9.3 Змінити товари через файл |
| GET | `/items/default-item` | 6 Додатковий товар |
| GET | `/items/file` | 5.2 Отримання файлів для вивантаження |
| POST | `/items/file` | 5.0 Створення файлу експорту |
| POST | `/items/file/custom` | 5.1 Створення файлу експорту з кастомним набором полів |
| PUT | `/items/mass-update` | 4.0 Масова зміна ціни і наявності товарів |
| GET | `/v1/goods/counts` | 0.0 Лічильники товарів v1 |

## Авторизація

| метод | шлях | що робить |
|---|---|---|
| POST | `/sites` | 1 Логін |
| POST | `/sites/logout` | 3 Вихід з облікового запису |
| POST | `/sites/recover-password` | 2 Відновлення пароля |

## Єдиний баланс

| метод | шлях | що робить |
|---|---|---|
| GET | `/balance-consolidated/balance` | Єдиний баланс продавця |
| GET | `/balance-consolidated/download-invoice/{id}` | Файл рахунку єдиного балансу |
| POST | `/balance-consolidated/evo-payment` | Створення платежу єдиного балансу |
| GET | `/balance-consolidated/evo-payment-status` | Отримання статусу платежа єдиного балансу |
| GET | `/balance-consolidated/export` | Експорт у XLSX транзакцій єдиного балансу |
| POST | `/balance-consolidated/invoice` | Створення інвойсу єдиного балансу |
| GET | `/balance-consolidated/offer` | Файл оферти |
| GET | `/balance-consolidated/operation-types` | Фільтри для пошуку в розділі Історія транзакцій |
| GET | `/balance-consolidated/search` | Отримання операцій по єдиному балансу |
| GET | `/balance-consolidated/search-data` | Фільтри для пошуку інвойсів єдиного балансу |
| GET | `/balance-consolidated/search-invoices` | Рахунки на оплату єдиного балансу |

## Баланс логістики

| метод | шлях | що робить |
|---|---|---|
| GET | `/balance-logistic/balance` | Баланс логістики продавця |
| POST | `/balance-logistic/evo-payment` | Створення платежу логістики |
| GET | `/balance-logistic/evo-payment-status` | Отримання статусу платежа логістики |
| GET | `/balance-logistic/export` | Експорт у XLSX транзакцій логістики |
| POST | `/balance-logistic/invoice` | Створення інвойсу логістики |
| GET | `/balance-logistic/invoices/download-invoice/{id}` | Файл рахунку логістики |
| GET | `/balance-logistic/invoices/search` | Рахунки на оплату логістики |
| GET | `/balance-logistic/invoices/search-data` | Фільтри для пошуку інвойсів логістики |
| GET | `/balance-logistic/search` | Отримання операцій по балансу логістики |
| GET | `/balance-logistic/search-data` | Фільтри для пошуку операцій з балансу логістики |

## Баланс

| метод | шлях | що робить |
|---|---|---|
| GET | `/balances/balance` | 7.1 Поточний баланс (остання транзакція) |
| GET | `/balances/balance-ads` | 7.2 Рекламний бюджет продавця |
| POST | `/balances/evo-payment` | 9.1 Створення платежа |
| GET | `/balances/evo-payment-status` | 9.2 Отримання статуса платежа |
| GET | `/balances/export` | 8.1 Експорт в XLS |
| POST | `/balances/invoice` | 9 Створення інвойсу |
| GET | `/balances/prepayment` | 4 Аванс |
| GET | `/balances/search` | 8 Список транзакцій магазину |
| GET | `/balances/search-data` | 8.2 Фільтри для пошуку транзакцій магазину |
| GET | `/balances/total` | 7.1 Баланси |
| GET | `/balances/types` | 3 Типи транзакцій |
| GET | `/invoices/download-invoice/{id}` | 1 Файл рахунку |
| GET | `/invoices/invoice-file-tmp-url/{id}` | 1.1 Файл рахунку |
| GET | `/invoices/invoice-type-list` | 2.1 Типи рахунків на оплату |
| GET | `/invoices/search` | 2 Рахунки на оплату |
| GET | `/items-commissions/search` | 6.1 Комісії по товарам |
| PUT | `/reports/approve-report/{id}` | 5.1 Підтвердження звіту про продані товари |
| PUT | `/reports/disapprove-report/{id}` | 5.3 Несхвалення звіту про продані товари |
| POST | `/reports/disapprove/{id}` | 5.4 Несхвалення звіту про продані товари та завантаження файлу |
| GET | `/reports/download-report/{id}` | 5 Файл звіту про продані товари |
| GET | `/reports/report-file-tmp-url/{id}` | 5.2 Файл звіту про продані товари |
| POST | `/reports/save-disapprove-form` | 5.5 Завантаження файлу і додавання коментаря |
| GET | `/reports/search` | 6 Звіти про продані товари |
| GET | `/v1/balances/current` | 10 Поточний баланс (остання транзакція) |

## Бізнес моделі

| метод | шлях | що робить |
|---|---|---|
| GET | `/markets/business-types` | 1 Список бізнес-моделей |

## Звернення клієнтів в Call-центр

| метод | шлях | що робить |
|---|---|---|
| GET | `/calls/call-statuses-n-request-types` | 4 Статуси і типи звернень клієнта |
| PUT | `/calls/change-status` | 3 Зміна статусу звернення клієнта |
| GET | `/calls/search` | 1 Пошук звернень клієнтів |
| GET | `/calls/{id}` | 2 Деталі звернення клієнта |

## Управління службами доставки

| метод | шлях | що робить |
|---|---|---|
| GET | `/delivery-service-pickups/search` | 2 Фільтр по точках самовивозу |
| GET | `/delivery-services/label-files` | 5 Отримання файлів маркувань для посилок |
| GET | `/delivery-services/search` | 4 Фільтр по сервісам доставки |
| GET | `/localities/search` | 1 Фільтр по населеним пунктам |
| GET | `/streets/search` | 3 Вулиці (пошук вулиць по містах) |

## Тарифи доставки

| метод | шлях | що робить |
|---|---|---|
| GET | `/delivery-tariffs/has-special-tariff` | 1 Перевірити наявність спецтарифу для служби доставки |

## Контакти та зворотній зв'язок

| метод | шлях | що робить |
|---|---|---|
| GET | `/feedbacks/child-feedback-by-department` | 2.1 Вибір теми при зверненні до підрозділу |
| POST | `/feedbacks/create-opinion` | 7 Оцінити тікет з розділу Переписка з ROZETKA |
| GET | `/feedbacks/get-contact-departments` | 1 Отримання відділень |
| POST | `/feedbacks/mass-important` | Масово відмітити тікети як важливі/неважливі |
| POST | `/feedbacks/mass-read` | Масово відмітити тікети як прочитані/непрочитані |
| GET | `/feedbacks/parent-feedback-by-department` | 2 Отримання підрозділів |
| POST | `/feedbacks/save-form` | 4 Відправлення форми для зворотного зв'язку |
| GET | `/feedbacks/search` | 8 Пошук тікетів |
| GET | `/feedbacks/search-themes` | 3 Список батьківських та дочірніх тем |
| GET | `/feedbacks/theme-hints` | 2.2 Список підказок до теми звернення |
| GET | `/feedbacks/{id}` | 6 Отримання подробиць тікету |
| GET | `/markets/{id}` | 5 Отримання інформації про продавця |
| POST | `/v1/feedbacks/create-comment` | Створення коментаря |
| POST | `/v1/feedbacks/save-form` | Відправлення форми для зворотного зв'язку |

## Фулфілмент

| метод | шлях | що робить |
|---|---|---|
| GET | `/fulfillments/invoice/file/{id}` | 4 Завантажити файл заявки на зберігання |
| GET | `/fulfillments/invoice/search` | 3 Пошук (фільтрація, сортування) заявки на зберігання |
| GET | `/fulfillments/invoices/export` | 5 Вивантажити файл з товарами фулфілмент |
| GET | `/fulfillments/recipient-store/search` | 6 Список складів для відправки товарів по ФФ |
| POST | `/fulfillments/seller-settings` | 2 Збереження контактної особи для Fulfillment |
| POST | `/v1/fulfillments/create-invoice` | 1 Створення заявки на зберігання |

## Групування товарів

| метод | шлях | що робить |
|---|---|---|
| GET | `/grouping-service/group-strategy/export` | 2.2 Отримання файлу правил та параметрів для групування товарів |
| POST | `/grouping-service/group-strategy/export` | 2.1 Формування файлу правил та параметрів для групування товарів |
| GET | `/grouping-service/group-strategy/search` | 1.1 Отримання правил та параметрів для групування товарів |

## Відгуки про товари

| метод | шлях | що робить |
|---|---|---|
| PUT | `/item-comments/change-important/{id}` | 1 Позначки важливості |
| GET | `/item-comments/child-comments/{id}` | 6 Відповіді на коментар |
| GET | `/item-comments/counts` | 2 Кількість коментарів |
| POST | `/item-comments/create-comment` | 3 Створити коментар |
| PUT | `/item-comments/mark-as-read/{id}` | 4 Позначити як прочитане (Відкрити коментар) |
| POST | `/item-comments/mass/{state}` | 7 Зміна стану коментарів |
| GET | `/item-comments/search` | 5.1 Пошук по коментарях |
| GET | `/item-comments/{id}` | 5.2 Деталі коментаря |

## Товари для промо-розсилки

| метод | шлях | що робить |
|---|---|---|
| GET | `/item-promo-prices/search` | 1. Пошук товарів для промо-розсилки |

## Модуль ручних повернень товарів

| метод | шлях | що робить |
|---|---|---|
| PUT | `/item-return/item/update-status/{id}` | Оновлення статусу товару у заявці на повернення |
| POST | `/item-return/ticket/create` | Створення заявки на повернення товарів |
| GET | `/item-return/ticket/search` | Пошук заявок на повернення товарів |
| GET | `/item-return/ticket/search-data` | Дані для фільтрів заявок на повернення |
| PUT | `/item-return/ticket/update/{id}` | Редагування заявки на повернення товарів |

## Модуль створення товарів

| метод | шлях | що робить |
|---|---|---|
| GET | `/items-create/attributes` | 3 Пошук характеристик для створення товарів |
| GET | `/items-create/categories` | 1.0 Довідник: категорії для створення товарів |
| POST | `/items-create/create` | 5 Створення товару |
| PUT | `/items-create/mass-update-basic-data` | 6 Масове редагування основних даних товара |
| GET | `/items-create/producers` | 1.1 Довідник: виробники для створення товарів |
| GET | `/items-create/series` | 1.2 Довідник: серії для створення товарів |
| GET | `/items-create/values` | 4 Пошук значень для створення товарів |

## Комплекти

| метод | шлях | що робить |
|---|---|---|
| POST | `/kits/archive` | 6 Архівування комплектів |
| POST | `/kits/create` | 1 Створення комплекту |
| GET | `/kits/search` | 4 Пошук по комплектах |
| GET | `/kits/{id}` | 5 Перегляд комплекту |
| PUT | `/kits/{id}` | 3 Оновлення комплекту |
| PUT | `/kits/{id}/block` | 2 Зміна статусу комплекта |

## Категорії

| метод | шлях | що робить |
|---|---|---|
| GET | `/market-categories/download-options` | 2.1 Отримання файлу XLS з параметрами категорій |
| GET | `/market-categories/export-producers` | 6 Отримання списку виробників у вигляді Xls. |
| GET | `/market-categories/get-categories-by-parent` | 4 Список категорій, що належать до материнської |
| GET | `/market-categories/has-options` | 1 Атрибути |
| GET | `/market-categories/options-xls` | 2 Отримання посилання на XLS-файл з параметрами категорій |
| GET | `/market-categories/search` | 3 Список активних категорій / Пошук |
| GET | `/v1/market-categories/category-options` | 5 Отримання параметрів категорій в JSON |

## Платіжні методи продавця

| метод | шлях | що робить |
|---|---|---|
| PUT | `/market-payment-methods/activate/{paymentMethodId}` | 2 Активація методу оплати |
| PUT | `/market-payment-methods/deactivate/{paymentMethodId}` | 3 Деактивація методу оплати |
| GET | `/market-payment-methods/list` | 1 Список платіжних методів |
| PUT | `/market-payment-methods/set-auto-hold/{paymentMethodId}` | 5 Двостадійна оплата |
| GET | `/market-payment-methods/{paymentMethodId}` | 4 Перегляд методу оплати |

## Відгуки про магазин

| метод | шлях | що робить |
|---|---|---|
| POST | `/market-review-replies/reply` | 5 Створення відповіді на відгук |
| GET | `/market-review-replies/search` | 6 Отримати відповіді на відгук |
| POST | `/market-review-replies/update-reply` | 7 Оновлення відповіді на відгук |
| GET | `/market-reviews/counts` | 1 Кількість відгуків |
| GET | `/market-reviews/search` | 4 Пошук за відгуками про магазин |
| GET | `/market-reviews/search-data` | 8 Фільтри для пошуку відгуків про магазин |
| PUT | `/market-reviews/update-important` | 2.3 Відмітити відгуки як важливі |
| PUT | `/market-reviews/update-read` | 2.2 Відмітити відгуки як прочитані |
| POST | `/market-reviews/{id}/mark-as-read` | 2.1 Відмітити як прочитане |
| GET | `/markets/{id}/rating` | 3 Рейтинг магазину |

## Налаштування джерел магазину

| метод | шлях | що робить |
|---|---|---|
| GET | `/markets/sources-list` | 1 Отримання джерел магазину |

## Модуль Meest Express

| метод | шлях | що робить |
|---|---|---|
| POST | `/meests/calculate` | 2 Калькуляція вартості |
| POST | `/meests/create-ttn` | 1 Створення ТТН |
| POST | `/meests/create-ttn-settings` | 7 Ініціалізація налаштувань Meest |
| GET | `/meests/get-user-info/{orderId}` | 6 Отримання даних із замовлення |
| POST | `/meests/search-locality` | 4 Пошук територіальних одиниць |
| PUT | `/meests/selected-settings` | 9 Зміна додаткових налаштувань для ТТН Meest |
| GET | `/meests/ttn-list` | 3 Отримання списку ТТН |
| GET | `/meests/ttn-print/stickers` | 5 Друк ТТН |
| GET | `/meests/ttn-settings` | 8 Отримання налаштувань Meest |

## Переписка з покупцем

| метод | шлях | що робить |
|---|---|---|
| GET | `/messages/counts` | 1 Кількість чатів |
| POST | `/messages/create` | 7.4 Створити повідомлення (відповісти) |
| GET | `/messages/download-file/{id}` | 6 Завантажити файл |
| PUT | `/messages/mass-delete` | 3 Масово видалити |
| PUT | `/messages/mass-important` | 1 Масово відмітити як важливі |
| PUT | `/messages/mass-restore` | 4 Масово відновити |
| PUT | `/messages/mass-unread` | 2 Масово відмітити як непрочитані |
| GET | `/messages/search` | 6 Пошук чатів |
| GET | `/messages/{id}` | 3 Відкрити чат |
| PUT | `/messages/{id}` | 7.5 Редагувати чат |
| POST | `/messages/{id}/delete-chat` | 5 Видалити чат |
| GET | `/messages/{id}/order-chat` | 7.2 Переписка по замовленню |

## Довідник

| метод | шлях | що робить |
|---|---|---|
|  | `/` | [Створення замовлення] Обрана доставка |
| GET | `/items/sell-statuses` | Sell Статуси товарів |
| GET | `/items/statuses-moderation` | Список статусів модерації товарів |

## Заявки на модерацію

| метод | шлях | що робить |
|---|---|---|
| GET | `/moderation-request` | 1. Отримання списку заявок |
| GET | `/moderation-request/search-data` | 2. Пошук даних для фільтра заявок |
| GET | `/moderation-request/{id}` | 3. Отриманя деталей заявки |

## Модуль ROZETKA Delivery

| метод | шлях | що робить |
|---|---|---|
| POST | `/delivery-rozetka/create-order-ttn` | 3. Створення ТТН із замовлення |
| GET | `/delivery-rozetka/find-cities` | 1. Пошук населеного пункту за назвою |
| GET | `/delivery-rozetka/find-pickup-cities` | 1.1 Пошук населеного пункту для відправки/отримання |
| GET | `/delivery-rozetka/find-receiver-pickups` | 2.2 Отримання відділень за населеним пунктом для отримувача |
| GET | `/delivery-rozetka/find-sender-pickups` | 2.1 Отримання відділень за населеним пунктом для відправника |
| GET | `/delivery-rozetka/get-user-info/{orderId}` | 6. Отримання даних із замовлення |
| GET | `/delivery-rozetka/label-files` | 11 Отримання файлів маркувань для посилок |
| GET | `/delivery-rozetka/registry/info/{id}` | 12.2. Отримання детальної інформації про реєстр приймання |
| GET | `/delivery-rozetka/registry/print/{id}` | 12.3. Отримання друкованої форми реєстру |
| GET | `/delivery-rozetka/registry/track-list` | 12.7 Отримання списку ТТН, доступних для додавання в реєстри |
| DELETE | `/delivery-rozetka/registry/tracks/{id}` | 12.4. Видалення експрес-накладної з реєстру |
| DELETE | `/delivery-rozetka/registry/{id}` | 12.5. Видалення реєстру |
| GET | `/delivery-rozetka/search-data` | 9. Фільтри для пошуку ТТН |
| GET | `/delivery-rozetka/settings` | 8. Отримання налаштувань передзаповнення |
| POST | `/delivery-rozetka/settings` | 7. Додавання налаштувань передзаповнення |
| GET | `/delivery-rozetka/ttn-list` | 4. Отримання списку ТТН |
| POST | `/delivery-rozetka/ttn-print-batch` | 5.1. Масовий друк ТТН |

## Створення замовлення

| метод | шлях | що робить |
|---|---|---|
| POST | `/v1/order-create/calculate` | 2.Отримання даних про доступні доставки і оплати |
| POST | `/v1/order-create/create` | 3.Створення замовлення |
| POST | `/v1/order-create/split` | 1.Поділ товарів на замовлення |

## Модуль рахунків замовлення

| метод | шлях | що робить |
|---|---|---|
| GET | `/order-invoices/search` | 1 Отримання рахунків замовлення |

## Модуль повернень

| метод | шлях | що робить |
|---|---|---|
| GET | `/order-refund/card/{id}` | 6. Повний номер картки покупця |
| GET | `/order-refund/detail/{id}` | 2. Подробиці за заявкою на повернення |
| PUT | `/order-refund/mass-unread` | 7. Масово відзначити як непрочитані |
| POST | `/order-refund/save-ttn` | 3. Метод для збереження ТТН |
| GET | `/order-refund/search` | 1.0 Отримання списку повернень |
| GET | `/order-refund/search-data` | 5. Метод для отримання статусів заявок на повернення |
| PUT | `/order-refund/update-status` | 4. Метод для оновлення статусу |

## Управління замовленнями

| метод | шлях | що робить |
|---|---|---|
| GET | `/order-statuses/search` | 2 Пошук статусів |
| POST | `/orders/approve-ff-order/{id}` | 8.9.1 Підтвердження фулфілмент замовлення |
| GET | `/orders/available-deliveries` | 1.4.6 Отримання данних для редагування доставки в замовленні |
| GET | `/orders/available-payments` | 8.6.2 Доступні для замовлення методи оплати |
| GET | `/orders/counts` | 1 Кількість замовлень |
| GET | `/orders/counts-new` | 1.1 Кількість замовлень |
| GET | `/orders/create-export-file` | 6.1 Створити файл експорту замовлень |
| PUT | `/orders/credit-approved/{id}` | 1.4.4 Підтвердження кредиту |
| PUT | `/orders/credit-cancel/{id}` | 1.4.3 Відхилення кредиту |
| PUT | `/orders/credit-status/{id}` | 5 Зміна статусу кредиту |
| GET | `/orders/download-export-file` | 6.3 Завантажити файл експорту замовлень |
| GET | `/orders/export` | 6 Експорт в XLS |
| GET | `/orders/generate-pdf/{id}` | 3 Експорт замовлення в PDF |
| GET | `/orders/get-export-data` | 6.2 Отримати дані експорту замовлень |
| GET | `/orders/partial-return-data/{id}` | 1.4.9 Отримання даних про частково видані товари в замовленні |
| POST | `/orders/prolong/{id}` | 5.1 Продовжити резерв замовлення |
| POST | `/orders/restore` | 8 Відновлення замовлення |
| PUT | `/orders/return-money` | 7.1 Зміна ознаки зворотньої доставки коштів |
| PUT | `/orders/review-request-status` | 7.2 Встановити статус відправлено запит на відгук |
| GET | `/orders/search` | 1.3 Пошук по замовленням |
| GET | `/orders/search-data` | 1.3.1 Пошук даних для фільтра замовлень |
| GET | `/orders/search-delivers` | 9 Перелік доставок, що використовуються у замовленнях [DEPRECATED] |
| GET | `/orders/status-payment/{id}` | 1.5 Статус оплати замовлення |
| POST | `/orders/update-delivery` | 1.4.5 Зміна доставки замовлення |
| PUT | `/orders/update-payment` | 8.6.3 Зміна методу оплати замовлення |
| POST | `/orders/update-receiver` | 1.4.7 Зміна одержувача в замовленні |
| GET | `/orders/user-info` | 1.4.8 Отримання додаткових данних про покупця в замовленні |
| GET | `/orders/{id}` | 1.2 Деталі замовлення |
| PUT | `/orders/{id}` | 1.4.2 Редагування замовлення (товари, кількість) |
| GET | `/payments/payment-statuses` | 1.6 Статуси платежів |
| GET | `/status-availables/search` | 4 Фільтр по зв'язаних статусам |
| POST | `/users/create` | 1.7 Створення покупця (пошук по телефону і створення) |
| GET | `/v1/orders/search-data` | 1.3.2 Пошук даних для фільтра замовлень |

## Налаштування особистого кабінету

| метод | шлях | що робить |
|---|---|---|
| POST | `/personal-cabinets/refund-payment` | Запуск ручного повернення із замовлення |
| PUT | `/personal-cabinets/settings` | Створення налаштувань особистого кабінету |
| GET | `/personal-cabinets/settings` | Отримання налаштувань |

## Маппінг категорій

| метод | шлях | що робить |
|---|---|---|
| GET | `/price-markets/categories-by-price` | 2 Список категорій по прайсу |
| POST | `/price-markets/create-bindings-categories` | 3 Зв'язування категорій прайса з категоріями Розетки |
| GET | `/price-markets/params-for-category` | 4 Список параметрів по зв'язаним категоріям |
| GET | `/price-markets/price` | 1 Список всіх прайсів |

## Модуль ПРРО

| метод | шлях | що робить |
|---|---|---|
| PUT | `/prro/change-receipt/{order_id}` | 3.2 Зміни чека |
| PUT | `/prro/checkbox-tax-settings` | 4.3 Оновлення даних податкової групи для Чекбокс |
| POST | `/prro/checkbox/sign-in` | 1.1 Авторизація у Checkbox |
| POST | `/prro/close-shift` | 2.2 Закрити зміну |
| POST | `/prro/create-receipt` | 3.1 Додавання фіскального чеку |
| POST | `/prro/logout` | 1.3 Вихід із ПРРО |
| POST | `/prro/manual/sign-in` | 1.2.1 Авторизація ручного управління |
| POST | `/prro/open-shift` | 2.1 Відкрити зміну |
| GET | `/prro/receipt-status/{order_id}` | 3.3 Статус фіскалізації чека |
| GET | `/prro/receipt/{order_id}` | 3.4 Відображення чека |
| GET | `/prro/search-data` | 4.1 Отримання даних для пошуку |
| GET | `/prro/shift-status` | 2.3 Отримання статусу зміни |
| GET | `/prro/status` | 1.4 Отримання статусу підключення ПРРО |
| GET | `/prro/transaction-details` | 4. Відображення операцій з нац кешбеку |
| PUT | `/prro/vchasno-tax-settings` | 4.2 Оновлення даних податкової групи для Вчасно |
| POST | `/prro/vchasno/sign-in` | 1.2 Авторизація у Вчасно-Каса |

## Модуль RozetkaPay

| метод | шлях | що робить |
|---|---|---|
| GET | `/rozetka-pay-transactions/search` | 1.1 Пошук RozetkaPay транзакцій |
| GET | `/rozetka-pay-transactions/search-data` | 1.2 Отримати дані для пошука RozetkaPay транзакцій |

## Повідомлення

| метод | шлях | що робить |
|---|---|---|
| GET | `/seller-notify-options/{id}` | 2 Типи і періодичність повідомлень |
| PUT | `/seller-notify-options/{id}` | 1 Зміна повідомлень |
| PUT | `/seller-notify-options/{id}/channel` | 3 Встановлення/оновлення канала для сповіщень про нове замовлення |
| POST | `/sellers/inactive-telegram` | 4 Відключення телеграм канала |

## Продавці

| метод | шлях | що робить |
|---|---|---|
| GET | `/balances/status` | 5.2 Отримання статусу магазину |
| GET | `/market/status-history` | 5.1 Логи зміни статусів магазину |
| PUT | `/markets/auto-hold` | 6.1 Двостадійна оплата |
| GET | `/markets/auto-hold` | 6.2 Отримати статус двостадійної оплати |
| GET | `/markets/payment-identifier` | 3.2 Отримати платіжний ідентифікатор |
| POST | `/markets/payment-identifier` | 3.1 Зберегти платіжний ідентифікатор |
| GET | `/markets/rich-content-files` | 10 Отримання файлів Річ контенту |
| GET | `/markets/seller-rating` | 2.2 Отримати зовнішній рейтинг магазину |
| POST | `/markets/unblock` | 5.3 Розблокувати магазин |
| GET | `/markets/{id}/internal-rating` | 2.1 Отримати внутрішній рейтинг магазину |
| GET | `/markets/{id}/market-counters` | 8 Отримання каунтерів магазину |
| GET | `/roles/search` | 4 Перелік доступних ролей менеджера |
| POST | `/sellers` | 1.1 Створення менеджера |
| GET | `/sellers/search` | 1.4 Пошук менеджера |
| DELETE | `/sellers/{id}` | 1.2 Видалення менеджера |
| GET | `/sellers/{id}` | 1.3 Інформація про менеджера |
| PUT | `/sellers/{id}` | 1.5 Редагувати профіль менеджера |
| PUT | `/sellers/{id}/update-self` | 9 Редагувати особисту інформацію |

## Графіки роботи

| метод | шлях | що робить |
|---|---|---|
| DELETE | `/markets/excluded-date/{id}` | 2.2 Видалення періоду відсутності |
| PUT | `/markets/excluded-date/{id}` | 2.1 Редагування періоду відсутності |
| PUT | `/markets/excludeddates` | 2 Створення та редагування періодів відсутності (масове) |
| GET | `/markets/items-auto-block` | 4 Отримання стану автоблокування товарів на період відсутності |
| PUT | `/markets/items-auto-block` | 5 Зміна стану автоблокування товарів на період відсутності |
| PUT | `/markets/timetable` | 1 Редагування графіка роботи |
| PUT | `/markets/сertain-period-dates` | 3 Редагування графіка роботи для певного дня |

## Модуль Нової Пошти

| метод | шлях | що робить |
|---|---|---|
| GET | `/ttns/common-data` | 2 Отримання даних для створення ТТН |
| POST | `/ttns/create-ttn` | 6 Створення ТТН НП |
| GET | `/ttns/get-user-info/{orderId}` | 5 Дані про одержувача і посилці з замовлення |
| GET | `/ttns/param` | 4 Отримання параметрів з API НП |
| GET | `/ttns/persons` | 3 Отримання даних щодо контактної персони |
| GET | `/ttns/ttn-list` | 1 Отримання списку ТТН з API НП. |
| GET | `/ttns/ttn-print` | 7 Друк ТТН |
| GET | `/ttns/ttn-print/stickers` | 9 Друк маркувань ТТН 85*85 6 шт. А4 |
| GET | `/ttns/ttn-print/zebra` | 8 Друк маркування ТТН 100 * 100 типу "зебра" |

## Налаштування модуля Нової Пошти

| метод | шлях | що робить |
|---|---|---|
| POST | `/ttn-settings/add-expiration-date-key` | 10 Додати термін дії ключа НП |
| GET | `/ttn-settings/address` | 4.3 Отримання адрес контрагента |
| PUT | `/ttn-settings/change-setting-flags` | 6 Зміна налаштувань автозаповнення ТТН |
| POST | `/ttn-settings/create-address` | 4.1 Створення адреси контрагента |
| POST | `/ttn-settings/create-ttn-key` | 2 Запис ключа Нової Пошти в систему МаркетПлейс |
| POST | `/ttn-settings/delete-address` | 4.2 Видалення адреси контрагента |
| POST | `/ttn-settings/delete-ttn-key` | 3 Видалення ключа НП |
| GET | `/ttn-settings/expiration-date-key` | 9 Отримати термін дії АПІ ключа НП |
| GET | `/ttn-settings/has-key` | 1 Перевірка наявності ключа НП |
| POST | `/ttn-settings/selected-cargo` | 5 Створення обраного вантажу |
| POST | `/ttn-settings/selected-sender` | 4 Створення обраного відправника |
| GET | `/ttn-settings/setting` | 7 Отримання даних про налаштування |
| POST | `/ttns/ttns-details` | 8 Отримання детальних даних по ТТН |

## Модуль Ukrposhta

| метод | шлях | що робить |
|---|---|---|
| PUT | `/ukrposhta/change-setting-flags` | 6.6  Збереження додаткових дефолтних налаштувань для ТТН Укрпошти |
| POST | `/ukrposhta/create-ttn` | 1 Створення ТТН |
| POST | `/ukrposhta/create-ttn-settings` | 6 Ініціалізація налаштувань Укрпошти |
| GET | `/ukrposhta/get-city` | 3.3 Отримання інформації по місту |
| GET | `/ukrposhta/get-district` | 3.4 Отримання інформації по району |
| GET | `/ukrposhta/get-index` | 3.6 Отримання інформації за індексом |
| GET | `/ukrposhta/get-locality-by-index` | 3.1 Отримання адреси за індексом |
| GET | `/ukrposhta/get-postoffice-by-index` | 3.7 Отримання адреси відділення за індексом |
| GET | `/ukrposhta/get-region` | 3.5 Отримання інформації по області |
| GET | `/ukrposhta/get-street` | 3.2 Отримання інформації по вулиці |
| GET | `/ukrposhta/get-user-info/{orderId}` | 5 Отримання даних із замовлення |
| GET | `/ukrposhta/search-data` | 2.1 Отримання даних для фільтрів ТТН |
| GET | `/ukrposhta/selected-cargo` | 6.5 Отримання предзаповнених налаштувань посилки для ТТН |
| PUT | `/ukrposhta/selected-cargo` | 6.4 Оновлення предзаповнених налаштувань посилки для ТТН |
| GET | `/ukrposhta/selected-sender` | 6.3 Отримання предзаповнених налаштувань відправника для ТТН |
| PUT | `/ukrposhta/selected-sender` | 6.2 Створення предзаповнених налаштувань відправника для ТТН |
| GET | `/ukrposhta/senders` | 6.7 Список відправників Укрпошти (ФОП / Юр. Особа) |
| GET | `/ukrposhta/ttn-list` | 2 Список ТТН |
| GET | `/ukrposhta/ttn-print/sticker/{ttn}` | 4 Друк ТТН |
| GET | `/ukrposhta/ttn-settings` | 6.1 Отримання налаштувань Укрпошти |
| GET | `/v1/ukrposhta/get-city` | 3.3 Отримання інформації по місту |
| GET | `/v1/ukrposhta/get-district` | 3.4 Отримання інформації по району |
| GET | `/v1/ukrposhta/get-index` | 3.6 Отримання інформації за індексом |
| GET | `/v1/ukrposhta/get-locality-by-index` | 3.1 Отримання відділення за індексом |
| GET | `/v1/ukrposhta/get-region` | 3.5 Отримання інформації по області |
| GET | `/v1/ukrposhta/get-street` | 3.2 Отримання інформації по вулиці |
| PUT | `/v1/ukrposhta/selected-cargo` | 6.4 Оновлення предзаповнених налаштувань посилки для ТТН |

## Завантажувач прайсів

| метод | шлях | що робить |
|---|---|---|
| POST | `/item-price-updates/create` | 1 Завантажити файл |
| GET | `/item-price-updates/search` | 2 Список завантажених прайсів |
