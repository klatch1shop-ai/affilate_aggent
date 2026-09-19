# ЗАВДАННЯ 03: єдиний чат покупців — ядро (Rozetka, Prom, Епіцентр → один Telegram)

**Виконавець:** Codex (`scripts/codex_task.py`, робітник з лімітами).
**Приймає:** рецензент (сесія Claude) за тестами `tests/test_privacy.py`,
`tests/test_inbox.py` і читанням коду.
**Дата:** 19.09.2026. **Попереднє:** TASK-01 (`intents.py`), TASK-02 (`commands.py`) — прийняті.

## 1. Навіщо

Власник 19.09: «треба за переписку з клієнтами подумати, аби з усіх
маркетплейсів усе зводилось в один чат». Зараз повідомлення покупців лежать у
кабінетах трьох майданчиків, і власник їх перевіряє вручну. Потрібно: кожне нове
повідомлення покупця → картка в одному Telegram-чаті; власник відповідає
реплаєм на картку → відповідь іде в потрібний чат майданчика.

Це завдання — **ядро без мережі**: розбір даних майданчиків, база без дублів,
збирання нових повідомлень без втрат, картки, правила відповіді. Справжні
HTTP-запити й підключення до бота робить рецензент окремо, з дозволу власника.

## 2. Що відомо про дані (перевірено 19.09.2026 запитами лише на читання)

**Rozetka.** `GET /messages/search?page=N` → `content = {'chats': [...], '_meta': {'pageCount': 2, ...}}`.
Чат: `{'id': int, 'created': str, 'updated': str, 'subject': str,
'user': {'id', 'contact_fio', 'email', 'has_email'}, 'order_id': int|None,
'item_id': int|None, 'type': int, 'unread_messages_count': int, ...}`.
`GET /messages/{id}?expand=messages` → той самий чат плюс
`'messages': [{'id': int, 'chat_id': int, 'body': str, 'created': str,
'sender': int, 'receiver_id': int, 'seller_id': int|None, 'files': list, 'status': int}]`.
**`sender == 3` — покупець, `sender == 2` — продавець (ми).** Час — рядок
`'YYYY-MM-DD HH:MM:SS'` за Києвом (Europe/Kyiv), без зони.

**Prom** (за документацією; живої перевірки нема — ключ API зараз 401).
`GET /messages/list` → `{'messages': [{'id': int, 'date_created': str ISO 8601,
'client_full_name': str, 'phone': str, 'message': str, 'subject': str,
'status': 'unread'|'read'|'deleted', 'product_id': int|None}]}`.
Кожне повідомлення Prom — окремий «чат» (його `id`), відповідь — на нього.

**Епіцентр.** Методів чату в Merchant API нема. У ядрі лише назва майданчика в
переліку; нормалізатора не треба.

## 3. Файли

Створити:

```
tg_dispatcher/privacy.py
tg_dispatcher/inbox/__init__.py        (може бути порожнім)
tg_dispatcher/inbox/model.py
tg_dispatcher/inbox/normalize.py
tg_dispatcher/inbox/store.py
tg_dispatcher/inbox/collect.py
tg_dispatcher/inbox/render.py
tg_dispatcher/inbox/reply.py
```

Змінити: `tg_dispatcher/ai_brain/commands.py` — **лише** функцію `_safe`:
вона має викликати `privacy.mask_private` (§4.1). Решту файлу не чіпати;
тести `tests/test_bot_commands.py` мають лишитися зеленими.

Тести вже написані й **не змінюються**: `tests/test_privacy.py`, `tests/test_inbox.py`.

## 4. Інтерфейс

### 4.1. `tg_dispatcher/privacy.py`

```python
def mask_private(text: str) -> str
```

- Телефони → `[телефон приховано]`. Телефон — послідовність цифр, між якими
  можуть бути пробіли, `-`, `(`, `)`, з необов'язковим `+` на початку; якщо
  прибрати роздільники, лишається **рівно 10 цифр, що починаються з `0`**, або
  **рівно 12 цифр, що починаються з `380`**. Приклади, які мають маскуватись:
  `0671234567`, `+380671234567`, `380671234567`, `+38 (067) 123-45-67`,
  `067 123 45 67`, `067-123-45-67`, `(067)1234567`, `+38 067 123 45 67`.
- Email → `[email приховано]`.
- **Не чіпати:** номер замовлення (9 цифр), ТТН (14 цифр), дати
  (`2026-09-19`, `19.09.2026`), ціни (`1 250 грн`, `12500`), 10 цифр, що
  починаються не з 0 (`1234567890`), і суміжні числа, розділені лише пробілом,
  з яких жодне окремо не телефон (`906298386 20451538685877` — лишити як є).
- Кілька телефонів у тексті — маскуються всі. Порожній рядок → порожній.

### 4.2. `inbox/model.py`

```python
MARKETPLACES = ('rozetka', 'prom', 'epicentr')

@dataclass(frozen=True)
class BuyerMessage:
    marketplace: str          # з MARKETPLACES
    chat_id: str              # непорожній рядок
    msg_id: str               # непорожній рядок
    direction: str            # 'in' (від покупця) | 'out' (від нас)
    body: str
    created: datetime         # лише з зоною (aware); зберігається в UTC
    buyer_name: str = ''
    subject: str = ''
    order_id: str | None = None
    item_id: str | None = None
    has_files: bool = False

def kyiv_to_utc(value: str) -> datetime
```

- Некоректні `marketplace`, `direction`, порожні `chat_id`/`msg_id`, `created` без
  зони → `ValueError` у `__post_init__`. `created` з іншою зоною переводиться в UTC
  (`object.__setattr__`).
- `kyiv_to_utc('2026-07-01 12:00:00')` → `2026-07-01 09:00 UTC` (літній час),
  `kyiv_to_utc('2026-01-15 12:00:00')` → `10:00 UTC`. Використати `zoneinfo`.
  Некоректний рядок → `ValueError`.
- **Полів телефону й email у моделі немає** — навмисно.

### 4.3. `inbox/normalize.py`

```python
def from_rozetka(chat: dict) -> list[BuyerMessage]
def from_prom(msg: dict) -> BuyerMessage | None
```

`from_rozetka` — чат з `messages` (§2) → повідомлення в порядку `created`.
`sender == 3` → `'in'`, `sender == 2` → `'out'`, **будь-яке інше значення →
`'in'`** (краще зайва картка, ніж втрачене повідомлення покупця). `chat_id`,
`msg_id`, `order_id`, `item_id` — рядками (`None` лишається `None`).
`buyer_name` — `user.contact_fio` (відсутній `user` → `''`). `body` — `body` або `''`.
`has_files` — непорожній `files`. Чат без ключа `messages` → `[]`.

`from_prom` — одне повідомлення Prom → `BuyerMessage` з `chat_id == msg_id ==
str(id)`, `direction='in'`, `body=message`, `buyer_name=client_full_name`,
`item_id=str(product_id)` або `None`. `date_created` — ISO 8601; якщо без зони —
вважати Київ. `status == 'deleted'` → `None` (перевіряти першим). Відсутні необов'язкові
поля (`subject`, `client_full_name`, `product_id`) — порожні / `None`.
Поле `phone` **нікуди не переноситься**.

### 4.4. `inbox/store.py`

```python
class InboxStore:
    def __init__(self, path: str = ':memory:')
    def add_new(self, messages: list[BuyerMessage]) -> list[BuyerMessage]
    def link_tg(self, tg_message_id: int, marketplace: str, chat_id: str) -> None
    def chat_for_tg(self, tg_message_id: int) -> tuple[str, str] | None
    def get_cursor(self, marketplace: str) -> str | None
    def set_cursor(self, marketplace: str, value: str) -> None
    def unanswered(self, now: datetime, older_than_min: int) -> list[dict]
```

- `sqlite3`, таблиці створюються в `__init__`. Унікальність — пара
  `(marketplace, msg_id)`. `add_new` повертає **лише вперше записані**
  повідомлення, відсортовані за `created`; повтор того самого набору → `[]`.
  Дублікати всередині одного виклику — теж один запис.
- `created` зберігати ISO-рядком в UTC; читати назад як aware `datetime`.
- `link_tg` для того самого `tg_message_id` вдруге — перезаписує.
- `unanswered(now, N)` — чати, де **останнє** повідомлення (за `created`) має
  `direction == 'in'` і старше за `N` хвилин відносно `now`. Елемент:
  `{'marketplace', 'chat_id', 'buyer_name', 'waiting_min': int}`, сортування — довше
  чекають першими. Чат, де після покупця відповіли ми, — не потрапляє.

### 4.5. `inbox/collect.py`

```python
def collect_rozetka(list_page, get_chat, store, now: datetime,
                    first_run_hours: int = 24, max_pages: int = 20) -> dict
```

- `list_page(page: int) -> dict` — `content` з `/messages/search` (§2);
  `get_chat(chat_id: int) -> dict` — чат з `messages`. Обидві передаються ззовні.
- Курсор — `store.get_cursor('rozetka')`: рядок `updated` найсвіжішого вже
  обробленого чату. Обходити сторінки `1 … min(pageCount, max_pages)`
  (порядок чатів **не припускати**). `get_chat` — лише для чатів з
  `updated > cursor` (без курсора — для всіх).
- Результат: `{'new': [...], 'cursor': str|None, 'errors': [str, ...], 'chats_checked': int}`,
  де `new` — **лише вхідні** (`'in'`) повідомлення з `store.add_new(...)`, а
  `chats_checked` — скільки чатів отримано зі сторінок списку (у межах `max_pages`).
- **Перший запуск** (курсора нема): усе записується в базу, але в `new` — лише
  вхідні, створені не раніше ніж `now − first_run_hours` (щоб не засипати
  власника старими розмовами).
- **Жодних втрат:** якщо `get_chat` для будь-якого чату кинув виняток —
  інші чати все одно обробляються, помилка йде в `errors` (текст містить `chat_id`),
  а **курсор не зсувається** (лишається попереднім; `result['cursor']` — теж
  попередній). Без помилок — курсор = максимальний `updated` серед побачених чатів
  і зберігається через `store.set_cursor`.
- Помилка `list_page` → курсор не зсувається, `errors` не порожній, виняток **не**
  пробрасується.

### 4.6. `inbox/render.py`

```python
LABELS = {'rozetka': '🟢 Rozetka', 'prom': '🟣 Prom', 'epicentr': '🟠 Епіцентр'}
MAX_BODY = 3000
def card(msg: BuyerMessage) -> str
def reminder(items: list[dict]) -> str
```

`card` — HTML для Telegram. Перший рядок: `LABELS[...]` і `чат <chat_id>`.
Далі: ім'я покупця й тема (якщо є), `Замовлення: <id>` / `Товар: <id>` (якщо є),
порожній рядок, текст. Текст і всі поля від покупця — через
`html.escape` **і** `privacy.mask_private`. Текст довший за `MAX_BODY` обрізається
до `MAX_BODY` символів + `…`. `has_files` → рядок з `📎`. Останній рядок містить
`реплаєм` (підказка: «Відповідайте реплаєм на це повідомлення»).

`reminder([])` → `''`. Інакше перший рядок містить `⏰` і кількість, далі по
рядку на чат: мітка майданчика, `чат <id>`, скільки хвилин чекає.

### 4.7. `inbox/reply.py`

```python
REPLY_MODES = ('off', 'draft', 'live')
MAX_REPLY = 2000
def plan_reply(reply_to_tg_id: int | None, text: str, store: InboxStore, mode: str) -> dict
```

Результат: `{'ok': bool, 'action': 'send'|'none', 'marketplace': str|None,
'chat_id': str|None, 'body': str, 'message': str}` (`message` — пояснення власнику
українською). Правила **по черзі**:

1. `mode` не з `REPLY_MODES` → `ValueError`.
2. `reply_to_tg_id` `None` або не пов'язаний (`chat_for_tg` → `None`) → `ok=False`.
3. Текст порожній після `strip()` → `ok=False`.
4. Довший за `MAX_REPLY` → `ok=False`, у `message` є число `2000`.
5. **Контакти й посилання заборонені** (майданчики блокують продавців, що
   виводять покупця за межі платформи): якщо в тексті телефон (за правилом §4.1),
   email, `http://`, `https://`, `www.`, `t.me/`, `viber`, `telegram`, `whatsapp`
   (без урахування регістру) → `ok=False`, `action='none'`.
6. `mode == 'off'` → `ok=False`, `action='none'`, `message` містить `вимкнено`.
7. `mode == 'draft'` → `ok=True`, `action='none'`, `body` = текст після `strip()`,
   `message` містить `чернетка`.
8. `mode == 'live'` → `ok=True`, `action='send'`.

`marketplace` і `chat_id` заповнюються, щойно чат знайдено (з п. 3 і далі).

## 5. Обмеження

- Стандартна бібліотека Python 3.13 (`sqlite3`, `zoneinfo`, `html`, `re`,
  `dataclasses`, `datetime`). Без мережі, без `requests`.
- Не чіпати `tg_dispatcher/main.py`, `agents/`, `tools/`, `shared/`, тести.
- Жодних справжніх даних покупців у коді, коментарях чи звіті.
- Коментарі й docstring — українською.

## 6. Приймання

```
venv/bin/python -m pytest tests/test_privacy.py tests/test_inbox.py -q      → усі зелені
venv/bin/python -m pytest tests/test_bot_commands.py tests/test_voice_intents.py -q → усі зелені
```

Звіт — `docs/reports/TASK-03-report.md`: файли, дослівний вивід обох команд,
що вирішено самостійно там, де завдання мовчить, і чого не вдалося.
