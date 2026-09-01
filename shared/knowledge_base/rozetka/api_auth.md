# Seller API: авторизація — пароль ОБОВʼЯЗКОВО в Base64

Перевірено практикою 09.08.2026 на акаунті `hyper_store`.

## Суть

`POST https://api-seller.rozetka.com.ua/sites` вимагає пароль, **закодований
у Base64**. З паролем у відкритому вигляді сервер відповідає так, ніби
облікові дані неправильні — і саме через це API Rozetka вважалося
непрацездатним від початку проєкту.

```
пароль як є     → HTTP 200, success=false
                  {"message":"incorrect_username_password","code":1004,
                   "description":"Неправильний логін або пароль"}

пароль у Base64 → HTTP 200, success=true
                  content.access_token: R5Dupi6j8ds412lqT8zkwRlh…
```

> ⚠️ Повідомлення «Неправильний логін або пароль» тут **оманливе**: логін і
> пароль були правильні весь час, некоректним було лише кодування. Не
> витрачай час на перевірку креденшелів, поки не переконався, що пароль
> кодується.

## Робочий приклад

```python
import base64, requests

B = 'https://api-seller.rozetka.com.ua'
r = requests.post(f'{B}/sites', json={
    'username': LOGIN,
    'password': base64.b64encode(PASSWORD.encode()).decode(),
}, timeout=45)
token = r.json()['content']['access_token']      # діє 24 години
```

```bash
curl -X GET "https://api-seller.rozetka.com.ua/items/counts" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json"
```

## Два способи отримати токен — обидва працюють

| Спосіб | Термін дії | Перевірено |
|---|---|---|
| `POST /sites` (логін + пароль у Base64) | 24 години | ✅ HTTP 200 |
| Статичний рольовий токен з кабінету | згасає після 24 год без використання | ✅ HTTP 200 |

Статичний генерується в кабінеті: «Налаштування → Безпека API» →
«Генерувати API токен», з привʼязкою до ролі. До 10 токенів на менеджера.

## Health check

Спеціального `ping` немає. Найдешевша перевірка:

```
GET /items/counts    → {"active":…, "inactive":…, "moderation":…, "promo":…}
GET /orders/counts   → {"new":…, "inProgress":…, "inDone":…, …}
```

## Коди помилок (формат `{"success":false,"errors":{"message","code"}}`)

| Код | Значення |
|---|---|
| **1004** / 1020 | `incorrect_username_password` — **найчастіше це відсутній Base64** |
| 6001 | `session_expired` — токен протух, разом з HTTP 401 |
| 1010 | `access_denied` — токен валідний, але роль не має прав |
| 5401 | `invalid_credentials` — звернення до захищеного методу без даних |

## Чого тут ще НЕ перевірено

Нижче — з документації, практикою на наших товарах **не підтверджено**
(акаунт NOIRE ще не активований менеджером Rozetka, у `hyper_store` лежить
лише Carvol на 8244 позиції):

- права та поведінка `PUT /items/update-price-stock/{id}`
- реальні коди 6001 / 1010 / 5401
- ліміти частоти й поведінка при HTTP 429
- баг `HeaderParsingError` (пробіл перед двокрапкою в заголовках)

Повний SKILL по Rozetka API писати передчасно, доки це не перевірене на
живих даних. Що вже точно відомо з документації й не потребує перевірки:
**категорію опублікованого товару через API змінити не можна**, лише через
фід з подальшою повторною модерацією.

## Облікові дані

Лежать у `.env` **на сервері usa1** (не на ноутбуці):
`ROZETKA_LOGIN`, `ROZETKA_PASSWORD`, `ROZETKA_API_TOKEN`.

Належать акаунту `hyper_store` — це **Carvol**, не NOIRE. Наші SKU
(`SO7368`, `SX3271`, `SO6194`) там не знаходяться, і це очікувано.
