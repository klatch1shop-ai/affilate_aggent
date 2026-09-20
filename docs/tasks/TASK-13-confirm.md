# ЗАВДАННЯ 13: механізм підтвердження дій (фаза B — межа перед будь-яким записом)

**Виконавець:** Codex. **Приймає:** рецензент за `tests/test_confirm.py` і читанням коду.
**Дата:** 20.09.2026. **План:** `docs/COMMAND_MATRIX.md` §2, `docs/tasks/QUEUE-12-17.md`.

## 1. Навіщо

Усе, що бот уміє зараз, — лише читання. Перш ніж дозволити **будь-який запис** (ТТН, лист
постачальнику, відповідь покупцю, зміна статусу), потрібен єдиний механізм: дія **зберігається**
зі статусом «очікує підтвердження», власник бачить, **що саме** буде зроблено, і підтверджує
кнопкою. Це вимога власника (§2 матриці) і стандарт 2026 для агентів («людина в контурі»).

## 2. Файли

Створити: `helper/confirm.py`. Інших файлів не чіпати. Стандартна бібліотека (`sqlite3`,
`json`, `datetime`, `uuid`, `hashlib`).

## 3. Модель

```python
RISKS = ('R0', 'R1', 'R2', 'R3')
STATUSES = ('pending', 'approved', 'done', 'failed', 'rejected', 'expired')
TTL_MIN = {'R2': 10, 'R3': 5}          # скільки живе пропозиція
MODES = ('off', 'test', 'live')

class ConfirmStore:
    def __init__(self, path: str = ':memory:')
    def create(self, *, intent, params, risk, preview, requested_by, now, ttl_min=None) -> dict
    def get(self, action_id) -> dict | None
    def pending(self, now) -> list[dict]
    def approve(self, action_id, *, user_id, now) -> dict
    def reject(self, action_id, *, user_id, now) -> dict
    def finish(self, action_id, *, ok: bool, result: str, now) -> dict
    def log(self, limit: int = 50) -> list[dict]
```
Запис дії: `{'id', 'intent', 'params' (dict), 'risk', 'preview', 'status', 'requested_by',
'created_at', 'expires_at', 'decided_by', 'decided_at', 'result'}`; час — aware UTC.

Правила:
- `create` — `risk` лише `'R2'`/`'R3'` (інакше `ValueError`: R0/R1 не потребують підтвердження);
  `id` — 12 шістнадцяткових символів; `expires_at = now + ttl_min або TTL_MIN[risk]`;
  `params` серіалізуються в JSON; статус `pending`.
- **Ідемпотентність за змістом:** якщо вже є `pending` дія з тим самим `intent` і тими самими
  `params` — `create` повертає **її**, а не нову (щоб подвійне натискання команди не створило дві).
- `approve`/`reject`: дія має бути `pending` і не простроченою (`now <= expires_at`), інакше
  запис переходить у `expired` і повертається з цим статусом, а `approve` **не** дозволяється.
  Повторний `approve` уже `approved`/`done` — повертає наявний запис **без зміни** (ідемпотентно).
- `finish(ok=True/False)` — лише з `approved`; статус `done`/`failed`, `result` — короткий текст.
- `pending(now)` — усі ще живі `pending` (прострочені позначити `expired` і не повертати).
- `log(limit)` — останні записи (будь-який статус), найновіші першими; **лише читання**.
- Дані переживають перевідкриття файлу.

## 4. Режими виконання

```python
def mode_of(intent: str, modes: dict, default: str = 'off') -> str
def gate(intent: str, risk: str, modes: dict) -> str
```
- `modes` — `{intent: 'off'|'test'|'live'}`; `mode_of` повертає режим команди або `default`.
- `gate` — що робити з дією: `'skip'` (режим `off`), `'dry'` (`test`), `'run'` (`live`);
  для `risk == 'R0'`/`'R1'` — завжди `'run'` (читання й чернетки режимів не потребують).
  Невідомий режим → `ValueError`.

## 5. Текст підтвердження

```python
def confirm_text(action: dict) -> str
```
- Перший рядок: `⚠️ Підтвердіть дію` для `R3`, `❓ Підтвердіть дію` для `R2`.
- Далі: назва дії (`intent`), **усі** параметри по рядку `<ключ>: <значення>` (порядок — як у
  `params`), потім `preview`, і останній рядок — скільки лишилось часу: `Діє ще N хв`.
- Увесь текст — через `tg_dispatcher.privacy.mask_private`. Значення довші за 200 символів —
  обрізати з `…`.

## 6. Виконання під контролем

```python
def run_action(store, action_id, executor, *, user_id, now, modes, dry_result='') -> dict
```
1. Дія має бути `approved` (інакше `{'ok': False, 'status': <статус>, 'message': …}` без виклику).
2. `gate(intent, risk, modes)`: `'skip'` → `finish(ok=False, result='режим off')`;
   `'dry'` → `executor(**params, dry_run=True)`; `'run'` → `executor(**params)`.
3. Виняток виконавця → `finish(ok=False, result=<тип винятку + текст через mask_private, 200 симв.>)`;
   успіх → `finish(ok=True, result=str(результат)[:200])`.
4. Повертає `{'ok': bool, 'status': 'done'|'failed', 'result': str, 'mode': 'skip'|'dry'|'run'}`.
5. **Повторний виклик для вже завершеної дії** — `{'ok': False, 'status': 'done'|'failed', …}`
   і виконавець **не** викликається (захист від подвійного натискання).

## 7. Приймання

```
venv/bin/python -m pytest tests/test_confirm.py -q     → зелені
venv/bin/python -m pytest tests/ -q -k "not confirm"   → зелені
```
Звіт `docs/reports/TASK-13-report.md` з «Самостійними рішеннями».

## 8. «Я прочитав» — щоб сповіщення не повторювалось (запит власника 20.09)

Окремий модуль `helper/ack.py` (створити разом із `confirm.py`).

```python
DEFAULT_HOURS = 24

class AckStore:
    def __init__(self, path: str = ':memory:')
    def ack(self, marketplace, chat_id, *, now, last_msg_id, hours=DEFAULT_HOURS, user_id=None) -> dict
    def is_acked(self, marketplace, chat_id, *, now, last_msg_id) -> bool
    def clear(self, marketplace, chat_id) -> None
    def acked(self, now) -> list[dict]
```
- `ack` запам'ятовує чат, `last_msg_id` (ідентифікатор останнього **вхідного** повідомлення на
  момент натискання), `until = now + hours` і хто натиснув; повторний `ack` того самого чату —
  оновлює запис.
- `is_acked` → `True`, **тільки якщо** запис є, `now < until` **і** `last_msg_id` збігається з
  тим, що було при натисканні. Тобто:
  * час вийшов → `False` (нагадування повертається);
  * **покупець написав нове повідомлення** (інший `last_msg_id`) → `False` одразу, навіть якщо
    час іще не вийшов — нове питання завжди пробиває «прочитано».
- `clear` — прибрати позначку (напр. власник передумав).
- `acked(now)` — чинні позначки, для довідки «що я відклав»: `{'marketplace', 'chat_id',
  'until', 'user_id'}`, найближчі до завершення першими.
- Дані переживають перевідкриття файлу.

Кнопки в Telegram і фільтрацію нагадувань підключає рецензент в оболонці бота.
