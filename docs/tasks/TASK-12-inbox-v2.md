# ЗАВДАННЯ 12: чати покупців v2 — окремі курсори, давні розмови, розумні нагадування

**Виконавець:** Codex. **Приймає:** рецензент за `tests/test_inbox_v2.py` і читанням коду.
**Дата:** 20.09.2026. **План:** `docs/COMMAND_MATRIX.md`, фаза A3; `docs/tasks/QUEUE-12-17.md`.

## 1. Навіщо (з живої роботи бота 19.09)

1. Питання по замовленню не приходило: чати Rozetka бувають двох типів (`msgType=items` і
   `msgType=orders`), а курсор у нас один на все.
2. Давня відкрита розмова (покупець написав 18.09, відповіді нема) не прийшла карткою —
   перший запуск бере лише останню добу. Власник бачив нагадування, але не саме питання.
3. Нагадування — голий номер чату щогодини («2075 хв», «2135 хв»…), без теми й тексту.

## 2. Файли

Змінити: `tg_dispatcher/inbox/collect.py`, `tg_dispatcher/inbox/store.py`,
`tg_dispatcher/inbox/render.py`, `helper/inbox_cycle.py`.
**Старі тести (`tests/test_inbox.py`, `test_helper.py`, `test_helper_v2.py`) мають лишитись
зеленими** — тому всі зміни сумісні: старі виклики працюють як раніше.

## 3. `collect.collect_rozetka(...)` — тип чату й окремий курсор

```python
def collect_rozetka(list_page, get_chat, store, now, first_run_hours=24, max_pages=20, msg_type=None)
```
- `msg_type is None` — **як зараз**: `list_page(page)`, курсор `'rozetka'`.
- `msg_type` задано (`'items'` / `'orders'`) — `list_page(page, msg_type)`, курсор
  `f'rozetka:{msg_type}'`. Решта правил (сторінки, помилки не зсувають курсор, перший запуск)
  — без змін.

## 4. `InboxStore` — нові можливості

```python
def linked_chats(self) -> set[tuple[str, str]]      # (marketplace, chat_id) з tg_links
def open_chats(self, now, max_age_days=7) -> list[dict]
```
- `open_chats` — чати, де **останнє** повідомлення `direction='in'` і воно молодше за
  `max_age_days` діб від `now`. Елемент: `{'marketplace', 'chat_id', 'subject', 'buyer_name',
  'waiting_min', 'last_text'}` (`last_text` — тіло останнього вхідного, через `mask_private`,
  до 200 символів). Сортування — довше чекають першими.
- `unanswered(...)` — додати в кожен елемент ключі `'subject'` і `'last_text'` (як вище).
  Наявні ключі й поведінка — без змін.

## 5. `render` — картка-нитка й нагадування з контекстом

```python
def thread_card(messages: list[BuyerMessage], limit: int = 3) -> str
def reminder_detail(items: list[dict]) -> str
def human_duration(minutes: int) -> str
```
- `human_duration`: `<60` → `'45 хв'`; `<24 год` → `'2 год 5 хв'`; інакше `'1 д 13 год'`.
- `thread_card` — останні `limit` повідомлень однієї розмови (у порядку часу): перший рядок як у
  `card` (мітка майданчика, чат, тема, замовлення/товар), далі рядки
  `👤 <час> <текст>` для `in` і `🏪 <час> <текст>` для `out`; час — `HH:MM DD.MM` за Києвом;
  текст — маскування, екранування, обрізання до 600 символів на повідомлення; останній рядок —
  підказка про реплай. Порожній список → `''`.
- `reminder_detail(items)` — як `reminder`, але: перший рядок `⏰ Чекають відповіді: N`, далі на
  кожен чат **два** рядки: `<мітка> · чат <id> · <human_duration>` і `<тема або ''> — <last_text до 120>`
  (другий рядок пропускати, якщо і тема, і текст порожні). Маскування — обов'язкове.
  **Стару `reminder` не чіпати** (її перевіряють наявні тести).

## 6. `InboxCycle` — дозавантаження й наростаючі нагадування

```python
class InboxCycle:
    def __init__(self, store, queue, list_page, get_chat, send, clock,
                 remind_after_min=30, remind_every_min=60, backfill_days=7,
                 remind_schedule=(60, 180, 360, 1440))
    def backfill(self) -> int
    def poll(self) -> dict          # без змін
    def remind(self) -> str | None
```
- `backfill()` — для кожного чату з `store.open_chats(clock(), backfill_days)`, якого **немає** в
  `store.linked_chats()`: скласти `render.thread_card` з останніх 3 повідомлень цього чату
  (`store` має віддати їх — додай приватний метод читання останніх повідомлень чату) і покласти
  в чергу `queue.push(f'{marketplace}:thread:{chat_id}', text, marketplace, chat_id)`.
  Повертає кількість доданих. Доставку робить наступний `poll()`.
- `remind()` — **наростаючі паузи на кожен чат окремо**: чат нагадується, якщо від останнього
  нагадування минуло `remind_schedule[min(k, len-1)]` хвилин, де `k` — скільки разів про цей чат
  уже нагадували; чат, про який ще не нагадували, — одразу. У текст іде `reminder_detail` **лише з
  тих чатів, яким час**. Нічого не час → `None`. Виняток `send` → `None`, лічильники не рухаються.
  Джерело чатів — `store.unanswered(clock(), remind_after_min)` (як зараз).

## 7. Приймання

```
venv/bin/python -m pytest tests/test_inbox_v2.py -q        → зелені
venv/bin/python -m pytest tests/ -q -k "not inbox_v2"      → зелені
```
Звіт `docs/reports/TASK-12-report.md` з «Самостійними рішеннями».

## 8. Відповіді на питання виконавця (20.09.2026, план Codex)

1. **Індекс паузи.** Рахуємо **успішно надіслані** нагадування про цей чат. Перше — одразу
   (жодної паузи). Перед `n`-м (`n ≥ 2`) чекати `schedule[min(n - 2, len(schedule) - 1)]`:
   тобто 2-ге через 60 хв після 1-го, 3-тє через 180 після 2-го, 4-те через 360, далі 1440.
2. **`backfill()`** повертає кількість **придатних чатів**, переданих у `queue.push()` (як у
   тесті), а не кількість нових рядків у черзі. `push` ідемпотентний — це його робота.
3. **`remind_every_min` vs `remind_schedule`.** Якщо `remind_schedule` передано явно — діє він.
   Якщо ні — розклад `(remind_every_min, 180, 360, 1440)`. Так старий виклик із
   `remind_every_min=15` дає першу паузу 15 хв, а далі наростання; типовий виклик без параметрів —
   `(60, 180, 360, 1440)`.
