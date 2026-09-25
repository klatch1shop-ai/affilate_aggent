# ЗАВДАННЯ 04b: три прогалини `sync/epicentr_offers.py`, знайдені рецензією TASK-04

**Виконавець:** Codex. **Приймає:** рецензент за `tests/test_epicentr_offers_04b.py`.
**Дата:** 25.09.2026. **Файл:** лише `sync/epicentr_offers.py` (розширення, не переписування
наявних функцій без потреби — `desired_state`, `batches`, `build_payload`, `OffersClient`,
`run()` не чіпати, крім точок інтеграції нижче).

## Навіщо
Без цього перша ж жива синхронізація зациклиться: (1) запит про статус загубленого пакета
питатиметься вічно; (2) той самий «артикул не знайдено» шлеться щоразу й засмічує чергу
тисячами однакових записів; (3) артикул з пробілами в відповіді API не збігається з нашим
і трактується як новий.

## Прогалина 1: `pending` старше 14 діб → «застаріло»
`SentStore.pending_requests()` зараз повертає **усі** запити з незакритими (`enqueued`)
рядками — назавжди, навіть якщо Епіцентр про них уже забув.

- Додати `SentStore.pending_requests(now: datetime, stale_after_days: int = 14) -> list[str]`.
  `now` **обов'язковий** (без замовчування на `datetime.now()` — детермінізм тестів).
  `now` без часового поясу → `ValueError` (як у `mark_pending`).
- Для `request_id`, де **найраніший** `at` серед його `enqueued`-рядків старіший за
  `now - stale_after_days` днів — **не повертати** цей `request_id` у списку, і одразу
  позначити всі його `enqueued`-рядки статусом `'stale'`. Додати `'stale'` у кортеж
  `_STATUSES` (лише структурно: щоб `report['by_status']` у `run()` мав ключ `'stale'`
  зі значенням 0 за замовчуванням — **рахувати** в нього нічого не треба, підрахунок
  застарілих запитів у `run()` не входить у це завдання).
- Межа рівно 14 діб — ще `enqueued` (включно), 14 діб і трохи більше — вже `stale`.
- Виклик у `run()` — замінити `store.pending_requests()` на
  `store.pending_requests(datetime.now(timezone.utc))`. Більше нічого в `run()` не змінювати
  щодо цього пункту.

## Прогалина 2: `forbidden` — відкладати, не слати щоразу
`apply_results` уже пише статус `forbidden` у `pending`, але `diff()` про це не знає:
той самий SKU з тим самим значенням піде в наступну пачку знову й знову.

- Нова таблиця `forbidden(sku TEXT PRIMARY KEY, price TEXT, availability TEXT, at TEXT)`.
- У `apply_results`, коли `status == 'forbidden'` — окрім наявного оновлення `pending`,
  **upsert** у `forbidden` (`price`/`availability` — ті самі значення, що були в
  `pending`-рядку; `at` — час виклику `apply_results`, тому методу потрібен параметр
  `now: datetime`, з тією ж валідацією часового поясу, що в `mark_pending`).
- `SentStore.forbidden_map() -> dict` — `{sku: {'price': Decimal|None, 'availability': str|None}}`.
- `diff(desired, sent, forbidden=None)` — новий необов'язковий параметр (за замовчуванням
  `None` = `{}`, стара сигнатура й поведінка не ламаються). SKU пропускається (не йде в
  `changes`), якщо він є у `forbidden` **і** `forbidden[sku]['price'] == desired[sku]['price']`
  **і** `forbidden[sku]['availability'] == desired[sku]['availability']` — тобто те саме, що
  вже відхилили. Якщо бажане значення змінилося відтоді — пробуємо знову (не пропускаємо).
- У `run()` викликати `diff(desired, store.get_all(), store.forbidden_map())`.

## Прогалина 3: нормалізація `sku` у відповіді
`parse_results` бере `sku` з відповіді API як є — пробіли по краях (`" SKU1 "`) зроблять
його чужим для наших пошуків (`desired_state` уже нормалізує вхідні SKU через `.strip()`,
відповідь API — ні).

- У `parse_results`: `sku = str(item['sku']).strip() if item.get('sku') is not None else str(item['id']).strip()`.
- Порожній після `strip()` SKU (`"   "` → `""`) — поточна поведінка не змінюється
  (не викидати, це не частина цієї прогалини), просто йде далі як порожній рядок.

## Правила
- Не чіпати `tests/`, `.env`, інші модулі. Не робити мережевих викликів (їх тут і нема).
- Існуючі публічні сигнатури, які не згадані вище, **не міняти** (щоб не зламати виклики
  з інших модулів, яких ти не бачиш).
- `_STATUSES` лишається кортежем — просто додати `'stale'` в кінець.

## Приймання
```
venv/bin/python -m pytest tests/test_epicentr_offers_04b.py -q      → зелені
venv/bin/python -m pytest tests/ -q -k 'not epicentr_offers_04b'    → зелені
```
Звіт `docs/reports/TASK-04b-report.md`.

## Відповіді на можливі питання
1. **Кілька SKU в одному `request_id` — одні застарілі, інші ні** — рішення приймається на
   рівні `request_id` цілком (найраніший `at` визначає), не по SKU.
2. **`forbidden` після успішного `processed` того самого SKU пізніше** — `apply_results`
   для `processed`/`skipped` пише лише в `sent`, запис у `forbidden` не чіпає й не видаляє;
   наступний `diff()` порівнює нові `desired` з `forbidden` — якщо значення тепер інші,
   `forbidden` для цього SKU просто більше не збігається і не заважає.
3. **`stale_after_days=0`** — усе, що має хоч секунду віку, вважається застарілим; це
   коректний, хоч і крайній, режим — не забороняти.
