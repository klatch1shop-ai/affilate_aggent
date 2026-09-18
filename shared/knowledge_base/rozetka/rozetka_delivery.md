# ROZETKA Delivery (доставка в магазини ROZETKA) — дослідження 18.09.2026

Для TOPTUL: власник розглядає два варіанти — (1) доставка в точки видачі
ROZETKA, (2) звичайна Нова Пошта, ТТН робить постачальник («Гранд Інструмент»).

## Як працює (sellerhelp p732, p733)

- Продавець привозить посилку в магазин ROZETKA або у відділення **Meest Пошти**,
  що приймає відправлення продавців; покупець забирає в обраному магазині ROZETKA.
- Для продавця — від 35 грн; для покупця безкоштовно; повернення безкоштовне;
  часткова видача; примірочні.
- Статуси після створення ТТН ставляться автоматично («Запланована передача
  перевізнику» → … → «Замовлення виконано»).

## Як увімкнути ЛИШЕ для частини товарів (p732)

API для цього **немає** (перевірено за специфікацією 529 методів). Два шляхи:
1. підтримка, тема «Видача посилок у ROZETKA» + **Excel з ID товарів на сайті ROZETKA**;
2. після підключення — вручну для вибраних товарів у кабінеті.
Чи можна підключити конкретний товар — видно в модулі **ROZETKA Delivery → Товари**.

## API (https://api-seller.rozetka.com.ua/apidoc/api_data.json, група Octopus)

| Дія | Метод |
|---|---|
| створити ТТН із замовлення | `POST /delivery-rozetka/create-order-ttn` |
| друк ТТН (PDF) | `POST /delivery-rozetka/ttn-print-batch` {track_numbers: [..]} |
| відділення для здачі посилки | `GET /delivery-rozetka/find-sender-pickups?city_id=` |
| населені пункти | `GET /delivery-rozetka/find-pickup-cities` |
| дані одержувача з замовлення | `GET /delivery-rozetka/get-user-info/{orderId}` |
| передзаповнення відправника | `GET/POST /delivery-rozetka/settings` |
| список ТТН | `GET /delivery-rozetka/ttn-list` |
| реєстр приймання | `/delivery-rozetka/registry/...` |

`create-order-ttn`: order_id*, payer*, places*, params* {weight, length, width,
height, volume}, sender* {type natural/legal, city, address, department (UUID
відділення здачі), name, phones[], info}, description (≤100), has_paid,
cost (сума накладеного платежу, обов'язкова при has_paid=false), carrier
(1 — ROZETKA Delivery, 4 — Meest), страхування воєнних ризиків.
**Накладений платіж збирає ROZETKA Delivery**, не постачальник.

`/delivery-rozetka/label-files` — це наліпки «Верх» / «Крихке», НЕ етикетка ТТН.

## Обмеження посилки (модель RozetkaDeliveryParams)

Вага 0,1–30 кг; кожна сторона 1–120 см; об'ємна вага = Д×Ш×В / 4000.
Пакування суворе (p734): коробка з ребрами жорсткості, «Крихке»/«Верх» 10×10 см
на двох найбільших сторонах, надрукована експрес-накладна на найбільшій стороні;
невідповідні відправлення не приймаються.
У фіді TOPTUL вага є лише у 422 з 5 783 товарів — придатність рахувати за
модулем ROZETKA Delivery → Товари, а не за фідом.

## Служби доставки (GET /delivery-services/search, 18.09)

4 Meest ПОШТА · 5 Нова Пошта · 43660 НП поштомати · **49722 Rozetka Delivery + Meest**
· **56214 Rozetka Delivery (партнерські відділення)** · 2024 Укрпошта · 430 кур'єр.
