# ЗАВДАННЯ 19: пакетний розбір відео конкурентів — зведення форматів і тем

**Виконавець:** Codex. **Приймає:** рецензент за `tests/test_competitors.py` і читанням коду.
**Дата:** 20.09.2026. **Спирається на:** скіл `video-analysis` (Gemini — перший прохід),
`docs/research/SOCIAL_CONTENT_2026.md`, TASK-18 (`content/`).

## 1. Навіщо

Перш ніж знімати власні ролики, треба знати, **що працює в ніші**: які гачки, яка довжина, які
теми, чи є обличчя в кадрі. Робимо це пакетно: посилання → Gemini (він дивиться відео сам) →
однакова структура відповіді → зведення. Мережі в цьому завданні немає: аналізатор передається
ззовні, як `fetchers` у TASK-02.

## 2. Файли

Створити: `content/competitors.py`. Стандартна бібліотека.

## 3. Інтерфейс

```python
QUESTION = ...          # текст запиту до моделі (українською, вимагає JSON)
FIELDS = ('hook', 'hook_type', 'length_sec', 'format', 'topic', 'has_face', 'cta', 'claims')
HOOK_TYPES = ('питання', 'цифра', 'проблема', 'демонстрація', 'контраргумент', 'історія', 'інше')

def parse_analysis(text: str) -> dict
def analyze_batch(urls: list[str], analyzer, *, limit: int = 20) -> dict
def summarize(items: list[dict]) -> dict
def report(summary: dict) -> str
```

### 3.1. `parse_analysis(text)`
Витягує JSON (зокрема з ```-огорожі) і **нормалізує**:
- усі ключі з `FIELDS`; відсутні → `None`;
- `hook_type` — лише з `HOOK_TYPES`, інакше `'інше'`;
- `length_sec` — число (рядок «45 с» → `45`); недоступне → `None`;
- `has_face` — `bool` (рядки «так/ні/true/false» теж);
- `claims` — список рядків (рядок → список з одного елемента; `None` → `[]`).
Некоректний JSON → `ValueError`.

### 3.2. `analyze_batch(urls, analyzer, limit)`
- `analyzer(url, question) -> str` передається ззовні (це виклик Gemini).
- Дублікати посилань прибрати, зберігши порядок; більше за `limit` — обрізати.
- Для кожного: виняток аналізатора або `ValueError` розбору → в `errors` рядок
  `'<url>: <тип помилки>'`, **інші продовжуються** (збій одного відео не валить пакет).
- Повертає `{'items': [ {**розбір, 'url': url} ], 'errors': [...], 'asked': int}`.

### 3.3. `summarize(items)`
`{'total': int, 'hook_types': {тип: кількість}, 'median_length': float | None,
'formats': {формат: кількість}, 'with_face': int, 'topics': [(тема, кількість)],
'claims_top': [(твердження, кількість)]}`
- `hook_types`, `formats` — від найчастішого; `topics` і `claims_top` — до 10, порівняння
  без урахування регістру й зайвих пробілів; `median_length` — медіана відомих значень.

### 3.4. `report(summary)` — текст українською
Рядки: `Розібрано: N`, `Медіана довжини: X с`, `Гачки: <тип> — N (…)`, `Формати: …`,
`З обличчям: N з M`, `Теми: …`, `Часті твердження: …`. Порожнє зведення → `'Нема даних'`.

### 3.5. `QUESTION`
Текст запиту має вимагати **JSON** з ключами `FIELDS`, українською, і містити пряму заборону
вигадувати: якщо чогось у відео нема — `null`.

## 4. Приймання

```
venv/bin/python -m pytest tests/test_competitors.py -q      → зелені
venv/bin/python -m pytest tests/ -q -k "not competitors"    → зелені
```
Звіт `docs/reports/TASK-19-report.md` з «Самостійними рішеннями».
