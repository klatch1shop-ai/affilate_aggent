# ЗАВДАННЯ 05: адаптери API лише для читання — Rozetka, Нова Пошта, Prom

**Виконавець:** Codex. **Приймає:** рецензент (Claude) за `tests/test_integrations.py`
і читанням коду. **Дата:** 19.09.2026.
**Попереднє:** TASK-02 (`commands.py` чекає `fetchers`), TASK-03 (`inbox/collect.py`
чекає `list_page`/`get_chat`), TASK-04 (зразок клієнта з підставленим транспортом).

## 1. Навіщо

Єдиний чат покупців і текстові/голосові команди бота мають готову логіку, але не
мають живих даних. Потрібні тонкі клієнти, які **лише читають** і приводять
відповіді майданчиків до форми, яку чекають TASK-02 і TASK-03. Головна вимога
власника: **збій ≠ «нічого нема»** (на Prom прострочений ключ кілька днів виглядав
як «нових замовлень немає»).

## 2. Що відомо (перевірено 19.09.2026 запитами лише на читання, якщо не сказано інше)

**Rozetka** `https://api-seller.rozetka.com.ua`, заголовки `Authorization: Bearer <token>`,
`Content-Language: uk`. Конверт: `{'success': bool, 'content': {...}}` або
`{'success': false, 'errors': {'message': str, 'code': int, 'description': str}}`.
- **Невірний токен → HTTP 200** з `success: false`, `code 1020`, `incorrect_access_token`
  (перевірено). За документацією також `1004`, `6001` (`session_expired`, з HTTP 401),
  `5401`. `1010` `access_denied` — токен дійсний, бракує прав (перевірено на `/messages`).
- `GET /orders/search?types=N&page=P&expand=purchases&sort=-id` → `content = {'orders': [...],
  '_meta': {'totalCount', 'pageCount', 'currentPage', 'perPage': 20}}`. **Порожній результат
  має `pageCount: 0`.** `types`: `1` — усі, `2` — в обробці, `3` — завершені, `4` — нові.
- Замовлення (поля, які є): `id` int, `created` str `'YYYY-MM-DD HH:MM:SS'` (Київ),
  `status` int, `status_group`, `amount` **str**, `cost`, `ttn` str|None, `total_quantity`,
  `comment`, **`user_phone`, `recipient_phone`, `user_title`, `recipient_title`** (персональні),
  `purchases[]: {'item': {'article', 'name', 'name_ua', ...}, 'item_name', 'quantity', 'price', 'cost', 'ttn', ...}`.
- `GET /orders/{id}?expand=purchases,delivery,payment` → `content` — одне замовлення.
- Чати: `GET /messages/search?page=P` → `content = {'chats': [...], '_meta': {...}}`;
  `GET /messages/{id}?expand=messages` → `content` — чат із `messages` (див. TASK-03 §2).

**Нова Пошта** `POST https://api.novaposhta.ua/v2.0/json/` з тілом
`{'apiKey', 'modelName': 'TrackingDocument', 'calledMethod': 'getStatusDocuments',
'methodProperties': {'Documents': [{'DocumentNumber': ttn, 'Phone': phone}]}}`.
Відповідь: `{'success': bool, 'data': [doc], 'errors': [str], 'warnings': [...]}`.
`doc` містить, серед іншого, `Number`, `Status`, `StatusCode`, `CityRecipient`,
`WarehouseRecipient`, `ScheduledDeliveryDate`, `ActualDeliveryDate`,
`RecipientDateTime`, а також **персональні** `PhoneRecipient`, `RecipientFullName`,
`PhoneSender`, `SenderFullNameEW` тощо. Відомі збої: у `errors` текст
**`To many requests`** (саме так, з помилкою) — тимчасовий ліміт; `success: true` з
порожнім `data` — траплялось, лікується повтором.

**Prom** `https://my.prom.ua/api/v1`, `Authorization: Bearer <token>` — **за
документацією, живої перевірки нема** (ключ зараз дає HTTP 401).
`GET /messages/list?limit=N[&last_id=ID]` → `{'messages': [...]}` (поля — TASK-03 §2);
`GET /orders/list?limit=N[&status=S]` → `{'orders': [...]}`. Помилка — HTTP-код ≠ 200.

## 3. Файли

```
integrations/__init__.py        (порожній)
integrations/errors.py
integrations/retry.py
integrations/rozetka.py
integrations/novaposhta.py
integrations/prom.py
```

## 4. Спільне

### 4.1. `integrations/errors.py`
```python
class ApiError(Exception):
    def __init__(self, service: str, message: str, code=None): ...
    service: str; code: int | str | None
class AuthError(ApiError): ...        # ключ відсутній / невірний / протух
class NotFound(ApiError): ...         # запитаного об'єкта нема
```
`str(e)` — `'<service>: <message>'` (+ ` (код <code>)`, якщо код є). Текст **завжди**
проходить через `tg_dispatcher.privacy.mask_private`. Токен/ключ у текст не
потрапляє ніколи (клієнти його туди не передають).

### 4.2. `integrations/retry.py`
```python
def call_with_retry(fn, *, sleep, delays=(1, 2, 4), retry_on=(ConnectionError, TimeoutError))
```
Викликає `fn()`; якщо виняток — екземпляр `retry_on`, чекає `sleep(delays[i])` і
повторює; спроб усього `len(delays) + 1`; після останньої — пробрасує **останній**
виняток. Інші винятки пробрасуються одразу, без `sleep`.

### 4.3. Транспорт
Кожен клієнт отримує ззовні функції:
`get(url, params: dict, headers: dict) -> (status: int, body: dict | None)`,
`post(url, json: dict, headers: dict) -> (status, body)` (лише НП), і `sleep(seconds)`.
Виняток транспорту `ConnectionError`/`TimeoutError` — повторюється через `call_with_retry`
з типовими затримками; якщо не минув — `ApiError(service, 'немає зв’язку')`.
**Жодних `requests`, мережі, `.env`.** Порожній токен/ключ → `AuthError` у конструкторі.

## 5. `integrations/rozetka.py`

```python
BASE = 'https://api-seller.rozetka.com.ua'
AUTH_CODES = {1004, 1020, 5401, 6001}
ORDER_FIELDS = ('id', 'created', 'status', 'status_group', 'amount', 'cost', 'ttn', 'total_quantity')
PURCHASE_FIELDS = ('quantity', 'price', 'cost', 'ttn')

def clean_order(order: dict) -> dict
class RozetkaClient:
    def __init__(self, get, token, sleep, max_pages=10)
    def orders(self, types: int) -> list[dict]
    def active_orders(self) -> list[dict]
    def order(self, order_id) -> dict
    def chats_page(self, page: int) -> dict
    def chat(self, chat_id) -> dict
```

- **Розбір конверта** (одна приватна функція для всіх методів), по черзі:
  HTTP 401 або `errors.code` з `AUTH_CODES` → `AuthError`; HTTP ≠ 200 → `ApiError` з
  HTTP-кодом; `success` не `True` → `errors.code == 5404` або `message == 'not_found'`
  → `NotFound`, інакше `ApiError(code=errors.code, message=errors.message)`; нема
  `content` → `ApiError`. Інакше — `content`.
- `clean_order(order)` — **білий список**: лише `ORDER_FIELDS` (відсутні → `None`) і
  `purchases`: кожна позиція — `PURCHASE_FIELDS` плюс `'item': {'article', 'name'}`,
  де `name` = `item.name_ua`, якщо непорожнє, інакше `item.name`, інакше `item_name`
  позиції. Нема `purchases` → `[]`. `amount` — лишити як є (рядок). **Жодних телефонів, імен покупця й
  отримувача, коментарів** у результаті — навіть якщо вони є на вході.
- `orders(types)` — `GET /orders/search` з `params = {'types': types, 'page': P,
  'expand': 'purchases', 'sort': '-id'}`; сторінки від 1 до `min(pageCount, max_pages)`
  (`pageCount == 0` → одна сторінка вже прочитана, більше не питати). Якщо
  `pageCount > max_pages` → `ApiError` (`'неповний список: N сторінок'`), **а не**
  обрізаний список. Результат — `clean_order` кожного.
- `active_orders()` — `orders(4)` + `orders(2)`, без дублів за `id`, сортування за `id`
  спаданням.
- `order(order_id)` — `order_id` має бути 9 цифр (int або str) → інакше `ValueError`;
  `GET /orders/{id}` з `params={'expand': 'purchases,delivery,payment'}` → `clean_order`.
- `chats_page(page)` — `GET /messages/search`, `params={'page': page}` → `content` як є
  (для `inbox.collect.collect_rozetka`). `chat(chat_id)` — `GET /messages/{id}`,
  `params={'expand': 'messages'}` → `content` як є.
- Заголовки кожного запиту: `Authorization: Bearer <token>`, `Content-Language: uk`.

## 6. `integrations/novaposhta.py`

```python
URL = 'https://api.novaposhta.ua/v2.0/json/'
SAFE_FIELDS = ('Number', 'Status', 'StatusCode', 'CityRecipient', 'WarehouseRecipient',
               'ScheduledDeliveryDate', 'ActualDeliveryDate', 'RecipientDateTime')
RATE_LIMIT_TEXT = 'To many requests'
class NovaPoshtaClient:
    def __init__(self, post, api_key, sleep, delays=(5, 15, 30))
    def ttn_status(self, ttn: str, phone: str = '') -> dict
```
- `ttn` після видалення пробілів — рівно 14 цифр, інакше `ValueError`.
- Тіло запиту — як у §2 (`apiKey` — лише в тілі, `Phone` — переданий `phone` або `''`).
- Повтори (затримки `delays`, спроб `len(delays)+1`) — коли `errors` містить рядок, у
  якому є `RATE_LIMIT_TEXT` (без урахування регістру), **або** `success: true` з
  порожнім `data`. Вичерпано на ліміті → `ApiError(code='rate_limit')`; вичерпано на
  порожньому `data` → `NotFound`.
- HTTP ≠ 200 → `ApiError`. `success: false` з іншими помилками → `ApiError`, текст —
  помилки через `; ` (маскування — §4.1).
- Результат — **лише** `SAFE_FIELDS` з `data[0]` (відсутні — пропустити ключ).

## 7. `integrations/prom.py`

```python
BASE = 'https://my.prom.ua/api/v1'
class PromClient:
    def __init__(self, get, token, sleep)
    def messages(self, limit: int = 100, last_id=None) -> list[dict]
    def orders(self, limit: int = 50, status: str | None = None) -> list[dict]
```
- HTTP 401/403 → `AuthError`; інший ≠ 200 → `ApiError`; тіло без списку `messages` /
  `orders` → `ApiError` (**а не** порожній список).
- `limit` 1…100, інакше `ValueError` — **до** будь-якого запиту. `last_id`/`status` — лише коли передані.
- `messages` — як є (поле `phone` прибирає `inbox.normalize.from_prom`); `orders` — як є.

## 8. Обмеження

- Лише файли з §3. Стандартна бібліотека + `tg_dispatcher.privacy`. Без мережі.
- Не чіпати `agents/`, `tools/`, `shared/`, `tg_dispatcher/`, `sync/`, тести.
- Коментарі й docstring — українською.

## 9. Приймання

```
venv/bin/python -m pytest tests/test_integrations.py -q                    → усі зелені
venv/bin/python -m pytest tests/ -q -k "not integrations"                  → усі зелені (нічого не зламано)
```
Звіт `docs/reports/TASK-05-report.md` з розділом «Самостійні рішення».
