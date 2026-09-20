# ЗАВДАННЯ 25: пам'ять гіпотез і звірка з фактом

**Виконавець:** Codex. **Приймає:** рецензент за `tests/test_hypotheses.py`. **Дата:** 20.09.2026.
**Навіщо:** `docs/research/AUTONOMOUS_RESEARCH_LOOP.md` — «без звірки з фактом система не вчиться».
Кожне припущення («ціна зависока», «питання про сумісність б'є по конверсії») має зберігатись
із доказами, а через 7/14/30 днів — звірятися з тим, що сталось насправді.

## Файли
Створити `research/__init__.py` (порожній) і `research/hypotheses.py`. Лише стандартна
бібліотека (`sqlite3`, `json`, `hashlib`, `datetime`). Зразок стилю — `helper/confirm.py`.

## Інтерфейс
```python
STAGES = (7, 14, 30)                       # дні до звірок
VERDICTS = ('confirmed', 'rejected', 'unclear')

class HypothesisStore:
    def __init__(self, path: str | None = None)      # None → у пам'яті
    def create(self, *, trigger, subject, text, evidence, decision, now, stages=STAGES) -> dict
    def get(self, hid) -> dict | None
    def due(self, now) -> list[dict]
    def record(self, hid, stage, *, fact, verdict, now) -> dict
    def open_items(self) -> list[dict]
    def summary(self, now) -> dict

def render(h: dict) -> str
```

### `create`
- `evidence` — список рядків. **Порожній список або не список → `ValueError`** (правило власника:
  без доказу теза не зараховується). Порожній `text` або `subject` → `ValueError`.
- `id` — 12 hex-символів, **детермінований від змісту** (`subject` + `text` + `decision`):
  повторний `create` з тим самим змістом повертає той самий запис і **не створює другого**
  (як `ConfirmStore.create`); інший `text` → інший `id`.
- Поля запису: `id, trigger, subject, text, evidence (list), decision, created_at, status, checks`.
- `status` при створенні — `'open'`.
- `checks` — по одному на кожен елемент `stages`: `{'stage': N, 'due': created_at + N днів,
  'fact': None, 'verdict': None, 'recorded_at': None}`, у порядку зростання `stage`.
- Усі дати — `datetime` з `timezone.utc`; при читанні з бази вони мають повертатися такими ж.

### `due(now)`
Звірки, час яких настав (`due <= now`) і які ще не записані, по всіх відкритих гіпотезах.
Повертає `[{'id', 'stage', 'due', 'subject', 'text'}]`, відсортовані за `due` (раніші вище),
при рівній даті — за `id`. Гіпотези зі `status != 'open'` **не потрапляють**.

### `record(hid, stage, *, fact, verdict, now)`
- `hid` невідомий або `stage` не з `checks` → `ValueError`.
- `verdict` не з `VERDICTS` → `ValueError`. Порожній `fact` → `ValueError`.
- Повторний запис тієї самої `stage` → `ValueError` (факт не переписуємо).
- Записує `fact`, `verdict`, `recorded_at = now`.
- `status` гіпотези стає `verdict` **останньої записаної за `stage`** звірки; тобто запис
  пізнішої стадії перекриває ранішу, запис ранішої стадії після пізнішої статус **не змінює**.
- Повертає оновлений запис.

### `open_items()` — гіпотези зі `status == 'open'`, новіші вище.

### `summary(now)`
`{'open': N, 'confirmed': N, 'rejected': N, 'unclear': N, 'due': N}`, де `due` — кількість
звірок із `due(now)`.

### `render(h)`
Картка для власника:
```
🔎 <subject>: <text>
Привід: <trigger>
Докази: • <d1> • <d2>
Рішення: <decision>
Звірки: 7 — ✅ <fact> · 14 — ⏳ 27.09 · 30 — ⏳ 13.10
```
- позначки: `confirmed` → `✅`, `rejected` → `❌`, `unclear` → `🤔`, ще не записана → `⏳ DD.MM`;
- `trigger` порожній → рядок «Привід» не виводиться;
- `fact` довший за 120 символів обрізається до 120 і `…`.

## Правила
- Нічого не друкувати в stdout. База — лише за переданим шляхом (за замовчуванням у пам'яті).
- Не чіпати `tests/`, `.env`, інші модулі, схему Postgres.

## Приймання
```
venv/bin/python -m pytest tests/test_hypotheses.py -q        → зелені
venv/bin/python -m pytest tests/ -q -k 'not hypotheses'      → зелені
```
Звіт `docs/reports/TASK-25-report.md`.

## Відповіді на можливі питання
1. **`stages` порожній** — `ValueError`: гіпотеза без жодної звірки не має сенсу.
2. **Два різні `trigger` при однаковому змісті** — запис один (перший), `trigger` не переписується.
3. **Часовий пояс** — усе в UTC; `render` показує дати в UTC, без перетворення.
4. **Сортування `open_items`** — за `created_at` спадно, при рівності — за `id`.
