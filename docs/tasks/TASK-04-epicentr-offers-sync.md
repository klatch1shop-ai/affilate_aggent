# ЗАВДАННЯ 04: синхронізація цін і наявності з Епіцентром через API `/v1/offers` — ядро

**Виконавець:** Codex (`scripts/codex_task.py`). **Приймає:** рецензент (Claude)
за тестами `tests/test_epicentr_offers.py` і читанням коду.
**Дата:** 19.09.2026. **Довідка:** `shared/knowledge_base/epicentr/api_offers_update.txt`
(прочитай розділи про статуси, помилки й правила ціни).

## 1. Навіщо

Зараз ціни й наявність NOIRE на Епіцентрі оновлюються XML-файлом на 13 054 оффери
кожні 2 години, і ми не бачимо, що Епіцентр з ним зробив. Новий API приймає
**лише зміни**, пачками, і повертає результат по кожному артикулу. Потрібне ядро,
яке вирішує, **що** надіслати, **як** надіслати без порушення лімітів і **що сталося**.

Модуль сам у мережу не ходить: HTTP-функції, час і сон передаються ззовні.
Живий запуск — окремий крок рецензента з дозволу власника.

## 2. Незмінні правила власника

1. **Ціна ніколи не нижче порогу** (роздрібна ціна постачальника). Рядок, де ціна
   менша за поріг, **не надсилається взагалі** й потрапляє в `blocked`.
2. **Наявність — три стани.** `available` `True` → `in_stock`, `False` →
   `not_available`, `None` (невідомо) → **наявність не надсилається** (ціна —
   надсилається, якщо коректна).
3. Режими: `off` (лише розрахунок), `dry` (пачки формуються, HTTP не викликається),
   `live`. За замовчуванням у коді — `off`.

## 3. Файли

Створити: `sync/__init__.py` (порожній), `sync/epicentr_offers.py`.
Лише стандартна бібліотека (`sqlite3`, `decimal`, `dataclasses`, `datetime`, `json`).

## 4. Інтерфейс `sync/epicentr_offers.py`

```python
BATCH_SIZE = 200              # довідка суперечлива (1000 vs «більше 200») — беремо 200
RATE_LIMIT = 120              # запитів
RATE_WINDOW = 120.0           # секунд
AVAILABILITY = ('in_stock', 'under_the_order', 'not_available')
MODES = ('off', 'dry', 'live')

class EpicentrError(Exception): ...          # 401/403/5xx/некоректна відповідь
class EpicentrAuthError(EpicentrError): ...  # саме 401 або 403

def to_price(value) -> Decimal | None
def desired_state(rows: list[dict]) -> tuple[dict, list[dict]]
def diff(desired: dict, sent: dict) -> list[dict]
def batches(items: list[dict], size: int = BATCH_SIZE) -> list[list[dict]]
def build_payload(batch: list[dict]) -> dict
def parse_results(resp: dict) -> dict

class SentStore: ...
class OffersClient: ...
def run(rows, store, client, mode: str) -> dict
```

### 4.1. `to_price(value)`
`Decimal`, округлений до 2 знаків (`ROUND_HALF_UP`). Приймає `int`, `float`, `str`
(кома як десятковий роздільник теж: `'163,50'`), `Decimal`. `None`, порожнє,
нечислове, ≤ 0 → `None`. `1499` → `Decimal('1499.00')`; `163.555` → `Decimal('163.56')`.

### 4.2. `desired_state(rows)`
Рядок: `{'sku': str, 'price': число|None, 'floor': число|None, 'available': bool|None}`.
Повертає `(desired, blocked)`:
- `desired[sku] = {'price': Decimal|None, 'availability': str|None}`;
- `sku` обрізається (`strip()`); порожній → у `blocked` з `reason='no_sku'`;
- `price` через `to_price`; некоректна → ціна `None` (рядок не блокується, якщо є наявність);
- **`floor` задано, ціна коректна і ціна < floor → увесь рядок у `blocked`,
  `reason='below_floor'`** (у `desired` його нема); `floor` `None` або ціна `None` →
  поріг не перевіряється; ціна, рівна порогу, — дозволена;
- `availability` за правилом §2.2;
- ціна `None` **і** наявність `None` → `blocked`, `reason='nothing_to_send'`;
- той самий `sku` двічі → лишається **останній** рядок;
- елемент `blocked`: `{'sku': str, 'reason': str}`.

### 4.3. `diff(desired, sent)`
`sent[sku] = {'price': Decimal|None, 'availability': str|None}` — останні
**підтверджені** значення. Повертає список змін, **відсортований за `sku`**:
`{'sku', 'price'?: Decimal, 'availability'?: str}` — лише поля, які відрізняються від
`sent` (поле `None` у `desired` не надсилається ніколи). Артикул без жодної зміни — не
потрапляє. Артикула нема в `sent` → надсилаються всі не-`None` поля.

### 4.4. `batches` і `build_payload`
`batches` ріже по `size` (`size < 1` → `ValueError`), порожній вхід → `[]`.
`build_payload(batch)` → `{'items': [...]}`, кожен: `{'sku': ..., 'prices': {'price': float}}`
і/або `'availability': ...`. Ціна в JSON — `float` з 2 знаками (`1499.0`, `163.56`).
`oldPrice` не надсилається ніколи.

### 4.5. `parse_results(resp)`
Вхід — відповідь `POST /v1/offers` або `GET /v1/offers/update-results/{id}`:
`{'total': int, 'items': [{'id', 'idType', 'status', 'errors', 'sku'}], 'requestId': str}`.
Повертає `{'request_id': str, 'by_status': {'enqueued': [...], 'processed': [...],
'skipped': [...], 'forbidden': [...]}, 'errors': {sku: errors}, 'unknown': [...]}`,
де списки — артикули (`sku`; якщо `sku` `None` — `str(id)`). Невідомий статус → у
`unknown`. `errors` — лише для записів з непорожнім `errors`. Нема `items` чи
`requestId` → `EpicentrError`.

### 4.6. `SentStore(path=':memory:')` — SQLite
```python
def get_all(self) -> dict                          # sku → {'price': Decimal|None, 'availability': str|None}
def mark_pending(self, request_id: str, items: list[dict], at: datetime) -> None
def pending_requests(self) -> list[str]            # requestId, у яких ще є незавершені записи
def apply_results(self, parsed: dict) -> None
```
- `mark_pending` запам'ятовує, **що саме** надіслано в запиті (`sku`, `price`,
  `availability`, `request_id`, `at`).
- `apply_results(parsed)` для записів цього `request_id`:
  `processed` і `skipped` → значення з надісланого переходять у підтверджені
  (`get_all`), запис завершено; `forbidden` → підтверджене **не змінюється**, запис
  завершено з помилкою (зберегти текст `errors`); `enqueued` → лишається незавершеним.
  Підтверджується лише те поле, яке було надіслане (надіслали лише ціну — наявність
  у `get_all` лишається попередньою).
- `pending_requests` — унікальні `request_id` з незавершеними записами, у порядку надсилання.
- Дані переживають перевідкриття файлу.

### 4.7. `OffersClient(post, get, token, clock, sleep, max_retries=3)`
- `post(url, json, headers) -> (status: int, body: dict|None)`,
  `get(url, headers) -> (status, body)` — передаються ззовні; `clock() -> float` (секунди),
  `sleep(seconds)`.
- Базова адреса `https://merchant-api.epicentrm.com.ua`; заголовок
  `Authorization: Bearer <token>`. Токена нема (порожній/`None`) → `EpicentrAuthError`
  ще в конструкторі.
- `submit(payload) -> dict` — `POST /v1/offers`; `results(request_id) -> dict` —
  `GET /v1/offers/update-results/{request_id}`.
- **Ліміт:** не більше `RATE_LIMIT` запитів за будь-які `RATE_WINDOW` секунд
  (ковзне вікно за `clock()`); якщо наступний запит перевищив би — `sleep` рівно
  стільки, щоб найстаріший запит вийшов з вікна.
- `200` → `body`. `429` і `5xx` → повтор після `sleep(2 ** спроба)` (1, 2, 4 …),
  не більше `max_retries` повторів, далі `EpicentrError`. `401`/`403` →
  `EpicentrAuthError` **без повторів**. Інший код (`400`, `404`, …) → `EpicentrError`
  з кодом у тексті. Токен **ніколи** не потрапляє в текст винятку.

### 4.8. `run(rows, store, client, mode)`
1. `mode` не з `MODES` → `ValueError`.
2. Спершу — дозбір результатів: для кожного `store.pending_requests()` у режимі `live`
   викликати `client.results(id)` → `parse_results` → `store.apply_results`. Помилка
   одного запиту → у `errors`, інші продовжуються.
3. `desired_state(rows)` → `diff(desired, store.get_all())` → `batches`.
4. `off` → нічого не викликати. `dry` → сформувати `payloads` (через `build_payload`),
   HTTP не викликати, `store` не змінювати. `live` → для кожної пачки
   `client.submit(payload)` → `parse_results` → `store.mark_pending(...)` →
   `store.apply_results(...)`. `EpicentrAuthError` → **зупинити всю синхронізацію**
   (решту пачок не слати), записати в `errors`. Інша `EpicentrError` на пачці → у
   `errors`, наступні пачки продовжуються.
5. Результат: `{'mode', 'changes': int, 'batches': int, 'payloads': list (лише dry),
   'blocked': list, 'sent': int (записів відправлено), 'by_status': {статус: кількість},
   'errors': list[str], 'stopped': bool}`. `sent` рахує записи лише з пачок, які
   `submit` прийняв без винятку.

## 5. Обмеження

- Лише `sync/`. Не чіпати `tools/`, `agents/`, `shared/`, `output/`, тести.
- Без мережі, без `requests`, без читання `.env`.
- Коментарі й docstring українською.

## 6. Приймання

```
venv/bin/python -m pytest tests/test_epicentr_offers.py -q     → усі зелені
```
Звіт `docs/reports/TASK-04-report.md` — як у `AGENTS.md`, з розділом «Самостійні рішення».

## 7. Відповіді на питання виконавця (19.09.2026, план Codex)

1. **`EpicentrAuthError` під час дозбору старих результатів (§4.8 п. 2) теж зупиняє
   всю синхронізацію**: решту `results` не питати, пачки не надсилати, `stopped=True`,
   помилка — в `errors`. Невірний ключ не має давати «часткову» роботу. Інші
   `EpicentrError` у п. 2 — як і було: записати й продовжити.
