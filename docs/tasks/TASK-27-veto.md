# ЗАВДАННЯ 27: ризик-вето — правила власника як перевірки над планом дії

**Виконавець:** Codex. **Приймає:** рецензент за `tests/test_veto.py`. **Дата:** 20.09.2026.
**Навіщо:** `docs/research/AUTONOMOUS_RESEARCH_LOOP.md`, крок 5. Правила власника поки живуть
у голові й у скілах. Вони мають стати **детермінованим шаром**, який дивиться на план дії
**до** підтвердження й каже: зупинити, спитати чи можна.

## Файли
Створити `research/veto.py`. Лише стандартна бібліотека + наш `tg_dispatcher.privacy.mask_private`
(імпортувати, не переписувати). Без мережі, без запису на диск.

## Інтерфейс
```python
FROZEN_FEEDS = ('rozetka', 'epicentr')        # зміст фіду після модерації не чіпаємо
READ_ONLY_SOURCES = ('carvol',)
PROTECTED_FILES = ('output/noire_epicentr_phase1.xml',)
AVAILABILITY = ('in_stock', 'under_the_order', 'not_available')
RULES = ('price_floor', 'frozen_content', 'read_only_source', 'protected_file',
         'availability', 'live_without_approval', 'personal_data')

def check(action: dict, context: dict) -> list[dict]
def verdict(problems: list[dict]) -> str
def report(action: dict, problems: list[dict]) -> str
```

`action`: `{'kind', 'sku', 'marketplace', 'source', 'mode', 'fields', 'files', 'text'}` —
будь-який ключ може бути відсутній. `context`: `{'floor': {sku: число}, 'approved': bool,
'evidence': list}`.

### `check(action, context)`
Повертає список `{'rule', 'level', 'message'}` **у порядку `RULES`**. `level` ∈ `('stop', 'ask')`.

| правило | коли | level | message |
|---|---|---|---|
| `price_floor` | `fields['price']` є і менша за `context['floor'][sku]` | `stop` | `'ціна 100.00 нижча за поріг 120.00'` (два знаки) |
| `price_floor` | `fields['price']` є, але порога для `sku` нема | `ask` | `'поріг ціни невідомий'` |
| `frozen_content` | `kind == 'feed_content'` і `marketplace` у `FROZEN_FEEDS` | `stop` | `'зміст фіду rozetka заморожений після модерації'` |
| `read_only_source` | `source` у `READ_ONLY_SOURCES` | `stop` | `'carvol — тільки читання'` |
| `protected_file` | якийсь із `files` у `PROTECTED_FILES` | `stop` | `'файл під забороною: <шлях>'` |
| `availability` | `fields['availability']` не з `AVAILABILITY` | `stop` | `'невідомий стан наявності: <значення>'` |
| `availability` | `fields['availability'] == 'not_available'` і `context['evidence']` порожній | `ask` | `'нема доказу відсутності'` |
| `live_without_approval` | `mode == 'live'` і `context['approved']` не `True` | `ask` | `'режим live без підтвердження власника'` |
| `personal_data` | `mask_private(text) != text` | `stop` | `'у тексті особисті дані покупця'` |

- `fields['price']` нечислова → `stop`, `'ціна не число: <значення>'` (правило `price_floor`).
- Одне правило дає **не більше одного** запису.
- Порожній `action` → порожній список.

### `verdict(problems)`
Є хоч один `stop` → `'stop'`; інакше є `ask` → `'ask'`; інакше → `'ok'`.

### `report(action, problems)`
- перший рядок: `'🛑 Зупинено'` / `'❓ Потрібне підтвердження'` / `'✅ Перешкод немає'`;
- другий рядок: `'<kind> · <sku> · <marketplace>'` — лише наявні частини, через `' · '`;
  якщо всі три відсутні — рядка нема;
- далі на кожну проблему: `'• <rule>: <message>'` у порядку `check`.

## Правила
- Нічого не друкувати в stdout, нічого не писати на диск, без мережі.
- Не чіпати `tests/`, `tg_dispatcher/privacy.py`, `.env`, інші модулі.
- **Нічого не пом'якшувати**: якщо правило спрацювало — воно у списку, навіть якщо `mode == 'test'`.

## Приймання
```
venv/bin/python -m pytest tests/test_veto.py -q      → зелені
venv/bin/python -m pytest tests/ -q -k 'not veto'    → зелені
```
Звіт `docs/reports/TASK-27-report.md`.

## Відповіді на можливі питання
1. **`price` дорівнює порогу** — це не порушення (заборонено «нижче»).
2. **`marketplace` не з `FROZEN_FEEDS`** (напр. `prom`) — правило `frozen_content` мовчить.
3. **`kind != 'feed_content'`, але майданчик заморожений** — теж мовчить: заморожений **зміст фіду**,
   а не ціна й наявність.
4. **`text` порожній або відсутній** — `personal_data` мовчить.
