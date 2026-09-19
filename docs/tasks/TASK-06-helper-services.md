# ЗАВДАННЯ 06: сервісний шар бота-помічника @NOIRE_helper_Bot

**Виконавець:** Codex. **Приймає:** рецензент (Claude) за `tests/test_helper.py` і читанням коду.
**Дата:** 19.09.2026. **Спирається на:** TASK-01 `intents.py`, TASK-02 `commands.py`,
TASK-03 `inbox/`, TASK-05 `integrations/`.

## 1. Навіщо

Власник 19.09 створив окремого бота-помічника (чат покупців + текстові команди),
щоб не чіпати робочого бота замовлень. Оболонку Telegram (aiogram, служба systemd)
пише рецензент. Тут — **уся логіка між Telegram і адаптерами**, чиста й перевірена
тестами: хто має доступ, як команда стає відповіддю, як нові повідомлення покупців
стають картками й **не губляться**, коли Telegram недоступний, як не спамити тривогами.

Перший етап — **лише читання**: бот нічого не пише в майданчики.

## 2. Файли

Створити:
```
helper/__init__.py          (порожній)
helper/access.py
helper/services.py
helper/feeds.py
helper/inbox_cycle.py
```
Змінити `tg_dispatcher/ai_brain/commands.py` — **лише** гілку обробки винятку в
`dispatch` (§4.2). Тести `tests/test_bot_commands.py` мають лишитись зеленими.

## 3. `helper/access.py`

```python
def parse_ids(value: str | None) -> frozenset[int]
def is_allowed(user_id, allowed: frozenset[int]) -> bool
```
- `parse_ids('123, 456 ,789')` → `{123, 456, 789}`; `None`/`''`/пробіли → `frozenset()`.
  Нечисловий елемент → `ValueError` (помилка налаштування має бути видно одразу).
- `is_allowed`: `True` лише якщо `user_id` (int або рядок цифр) є в `allowed`.
  **Порожній `allowed` → завжди `False`** (закрито за замовчуванням). `None` → `False`.

## 4. `helper/services.py`

```python
def build_fetchers(rozetka=None, novaposhta=None, stock_lookup=None,
                   feeds_status=None, system_status=None) -> dict
def answer(text: str, fetchers: dict) -> str
```

### 4.1. `build_fetchers`
Повертає словник для `commands.dispatch`. **Ключ з'являється лише тоді, коли передано
відповідну залежність** (нема `novaposhta` → нема `'ttn_status'` → `dispatch` сам скаже
«Команда ще не підключена»). Кожна функція приймає `**kwargs` і ігнорує зайві.

| ключ | залежність | що робить |
|---|---|---|
| `orders_new` | `rozetka` | `marketplace` `None` або `'rozetka'` → `rozetka.active_orders()`; інший майданчик → `ApiError('helper', 'майданчик <назва> ще не підключено')` |
| `order_details` | `rozetka` | `rozetka.order(order_id)` |
| `ttn_status` | `novaposhta` | `novaposhta.ttn_status(ttn)` |
| `stock` | `stock_lookup` | `stock_lookup(sku)` |
| `feeds` | `feeds_status` | `feeds_status()` |
| `system` | `system_status` | `system_status()` |

`ApiError` — з `integrations.errors`.

### 4.2. Зміна в `commands.dispatch`
Зараз будь-який виняток fetcher'а дає `⚠️ Не вдалося виконати дію: <title>` без причини.
Для **`integrations.errors.ApiError`** (і нащадків) додати причину: `… : <title> — <str(e)>`
(текст `ApiError` уже замаскований і без токенів). Для **інших** винятків — як було,
**без** тексту винятку (він може містити дані покупця). Імпорт `ApiError` — усередині
функції або на рівні модуля, як зручніше; `commands.py` не повинен падати, якщо пакет
`integrations` недоступний (тоді поводитись як для звичайного винятку).

### 4.3. `answer(text, fetchers)`
`commands.dispatch(intents.parse(text), fetchers)`. Порожній текст → `commands.fmt_help()`.

## 5. `helper/feeds.py`

```python
def count_offers(path: str) -> int
def feeds_status(paths: dict, now: float, max_age_min: int = 180, stat=os.stat, counter=count_offers) -> dict
```
- `count_offers` — кількість входжень `<offer ` (з пробілом) у файлі, **читаючи шматками**
  (файли до сотень МБ; не читати цілим у пам'ять). Врахувати, що `<offer ` може
  розірватися між шматками.
- `feeds_status({'rozetka': '/шлях/a.xml', ...}, now)` → для кожного майданчика
  `{'ok': bool, 'age_min': int | None, 'offers': int}`:
  - файлу нема (`stat` кидає `FileNotFoundError`/`OSError`) → `{'ok': False, 'age_min': None, 'offers': 0}`;
  - `age_min = int((now - st_mtime) // 60)`;
  - `ok` — `age_min <= max_age_min` **і** `offers > 0`.
  - Порядок ключів — як у `paths`.

## 6. `helper/inbox_cycle.py`

```python
class DeliveryQueue:
    def __init__(self, path: str = ':memory:')
    def push(self, key: str, text: str, marketplace: str, chat_id: str) -> None
    def pending(self) -> list[dict]        # [{'key','text','marketplace','chat_id'}] у порядку push
    def done(self, key: str) -> None

class InboxCycle:
    def __init__(self, store, queue, list_page, get_chat, send, clock,
                 remind_after_min: int = 30, remind_every_min: int = 60)
    def poll(self) -> dict
    def remind(self) -> str | None
```

### 6.1. `DeliveryQueue` (SQLite)
Черга карток, **ще не доставлених у Telegram**. `push` з уже наявним `key` — нічого не
робить (ідемпотентно). `done` прибирає. Дані переживають перевідкриття файлу.
Ключ картки — `f'{marketplace}:{msg_id}'`.

### 6.2. `InboxCycle.poll()`
1. `res = inbox.collect.collect_rozetka(list_page, get_chat, store, now=clock())`.
2. Кожне `msg` з `res['new']` → `queue.push(key, inbox.render.card(msg), msg.marketplace, msg.chat_id)`
   — **спершу в чергу, потім надсилання** (повідомлення вже позначене в `store` як побачене;
   якщо Telegram упаде між цими кроками, картка лишиться в черзі).
3. Для кожної картки з `queue.pending()` по порядку: `tg_id = send(text)`; успіх →
   `store.link_tg(tg_id, marketplace, chat_id)` і `queue.done(key)`. Виняток `send` →
   **зупинити доставку в цьому циклі** (решта лишається в черзі), записати помилку.
4. **Тривога без спаму.** Набір помилок циклу = помилки `res['errors']` + помилка доставки
   (якщо була). Якщо набір **непорожній і відрізняється** від попереднього надісланого —
   надіслати один текст, що починається з `⚠️ Чат покупців:` і містить помилки (кожна з
   нового рядка). Якщо набір став порожнім після непорожнього — надіслати один раз
   `✅ Чат покупців знову працює`. Тривоги надсилаються тим самим `send`; якщо `send` падає
   і на тривозі — не пробрасувати.
   *(Тривога про збій доставки може сама не дійти — це нормально, вона повториться
   наступного циклу, бо набір не був «надісланий».)* Вважати тривогу надісланою лише
   якщо `send` не кинув виняток.
5. Повертає `{'new': int (скільки нових з collect), 'delivered': int, 'queued': int
   (лишилось у черзі), 'errors': list[str], 'alert': str | None (текст надісланої тривоги
   або відновлення, якщо було)}`.

### 6.3. `InboxCycle.remind()`
`items = store.unanswered(clock(), remind_after_min)`. Нічого → `None`. Інакше надіслати
`inbox.render.reminder(items)` через `send`, **але не частіше ніж раз на
`remind_every_min` хвилин** — за винятком випадку, коли з'явився чат, якого не було в
попередньому надісланому нагадуванні (тоді одразу). Повертає надісланий текст або `None`.
Виняток `send` → `None`, стан «останнього нагадування» не змінюється.

## 7. Обмеження

- Лише файли з §2. Стандартна бібліотека + модулі репозиторію. Без мережі, `.env`, aiogram.
- `clock()` повертає aware `datetime` (UTC); `feeds_status` отримує `now` як число секунд.
- Коментарі й docstring — українською.

## 8. Приймання

```
venv/bin/python -m pytest tests/test_helper.py -q          → усі зелені
venv/bin/python -m pytest tests/ -q -k "not helper"        → усі зелені
```
Звіт `docs/reports/TASK-06-report.md` з розділом «Самостійні рішення».
