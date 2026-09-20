# ЗАВДАННЯ 34: відбір TOPTUL для доставки в магазини ROZETKA (габарити + гроші)

**Виконавець:** Codex. **Приймає:** рецензент за `tests/test_rz_delivery_fit.py`. **Дата:** 20.09.2026.
**Запит власника:** відібрати з фіду TOPTUL товари, які проходять **за габаритами** для доставки
в магазини Rozetka, і при цьому **не з'їдають прибуток**: продавець платить **35 грн** за кожне
відправлення, плюс ступінчаста комісія Rozetka. «Не можна допустити втрати грошей».

## Перевірені факти (джерела в репозиторії, не вигадувати свої)

| Факт | Значення | Джерело |
|---|---|---|
| найдовша сторона | ≤ **120 см** | `shared/knowledge_base/rozetka/sellerhelp/p787-volumetric-weight-calculator.txt:28` |
| фактична вага | ≤ **15 кг** | те саме, `:30` |
| об'ємна вага | ≤ **30 кг** | те саме, `:32` |
| формула об'ємної ваги | `Д×Ш×В / 4000` (см → кг) | `shared/knowledge_base/rozetka/rozetka_delivery.md:46` |
| доставка коштує продавцю | **35 грн** з 07.08.2026 | `.../sellerhelp/p826-meest-rozetka-delivery.txt:30` |
| комісія Rozetka | ступінчаста, таблиця в БД `rozetka_cpa_rates.price_ranges` | напр. «1.5 Інструменти»: `[[0,4999,18],[5000,9999,10],[10000,19999,7],[20000,999999999,5]]` |

**Розбіжність, яку не можна згладжувати:** наш конспект `rozetka_delivery.md:46` каже «вага 0,1–30 кг»
(це межі поля API), офіційна сторінка p787 — «вага не більше 15 кг». Беремо **суворіше (15 кг)**
і пишемо це в коментарі модуля.

**Відомий брак даних:** у фіді TOPTUL вага є лише у 422 з 5 783 товарів
(`shared/knowledge_base/rozetka/rozetka_delivery.md`). Тому потрібні **три стани**, як із наявністю:
проходить / не проходить / **даних нема** — «нема даних» ніколи не вважати «проходить».

## Файли
Створити `tools/rz_delivery_fit.py`. Лише стандартна бібліотека **плюс** уже перевірений
`tools/price_engine_toptul.py` — `price_item`, `commission_pct` **імпортувати, не переписувати**.
Без мережі, без бази, без файлів: дані передає викликач.

## Інтерфейс
```python
LIMITS = {'max_side_cm': 120.0, 'max_weight_kg': 15.0, 'max_volumetric_kg': 30.0, 'divisor': 4000.0}
DELIVERY_FEE = 35.0
STATES = ('fits', 'too_big', 'unknown')
SIDES = ('length', 'width', 'height')

def volumetric_weight(length, width, height, *, divisor=LIMITS['divisor']) -> float | None
def fit(dims: dict) -> dict
def evaluate(item: dict, ranges, *, fee=DELIVERY_FEE, min_profit=0.0) -> dict
def select(items, ranges_by_category, *, fee=DELIVERY_FEE, min_profit=0.0) -> dict
def report(selection: dict) -> str
```

### `volumetric_weight(length, width, height, *, divisor)`
`round(Д×Ш×В / divisor, 2)`. Будь-яка сторона `None` або ≤ 0 → `None`. Не число → `None`.

### `fit(dims)`
`dims` — `{'length', 'width', 'height', 'weight'}` у сантиметрах і кілограмах, будь-який ключ
може бути відсутній або `None`. Повертає `{'state', 'reasons', 'volumetric', 'missing'}`:
- `reasons` — рядки про **перевищення**, у порядку: сторони (у порядку `SIDES`), вага, об'ємна вага:
  `'сторона length 130.0 см > 120 см'`, `'вага 18.0 кг > 15 кг'`, `'об’ємна вага 32.5 кг > 30 кг'`;
  числа друкувати як `float` без зайвих нулів (`130.0`, `18.5`);
- `missing` — відсутні або `None`/непридатні ключі у порядку `SIDES + ('weight',)`;
- `state`: `'too_big'`, якщо `reasons` непорожні (**навіть якщо частина даних відсутня** —
  одного доведеного перевищення досить); інакше `'fits'`, якщо `missing` порожній;
  інакше `'unknown'`;
- `volumetric` — число або `None`.

### `evaluate(item, ranges, *, fee, min_profit)`
`item` — `{'sku', 'name', 'wholesale', 'rrp', 'competitors', 'dims', 'category_id'}`
(зайві ключі ігнорувати, `competitors` за замовчуванням порожній; `category_id` потрібен
лише `select`, сама `evaluate` отримує `ranges` готовими). Рахує ціну через
`price_item(wholesale, rrp, ranges, competitors, min_profit=min_profit, fixed_costs=fee)`.
Повертає `{'sku', 'name', 'fit', 'price', 'profit', 'status', 'commission', 'ok', 'why'}`:
- `fit` — результат `fit(item['dims'])`;
- `price`, `profit`, `status`, `commission` — з `price_item` (`None`, коли `status == 'no_data'`);
- `ok is True` лише коли **всі** умови: `fit['state'] == 'fits'`, `price` не `None`,
  `profit >= min_profit`, `status != 'uncompetitive'`;
- `why` — **перша** причина відмови, у цьому порядку перевірок:
  `'габарити: <перша причина або «нема даних про …»>'` → `'ціна: <reason з price_item>'` →
  `'прибуток <X> ₴ менший за мінімум <Y> ₴'` → `'дорожче за конкурента: <reason>'`;
  коли `ok` — `why` порожній рядок.
  Для `state == 'unknown'` текст габаритів: `'габарити: нема даних про '` і `missing` через `', '`.

### `select(items, ranges_by_category, *, fee, min_profit)`
`ranges_by_category` — `{category_id: ranges}`; ключ `None` (якщо є) — запасна таблиця.
Повертає:
```python
{'ready': [...], 'too_big': [...], 'unknown_dims': [...], 'no_price': [...],
 'overpriced': [...], 'low_margin': [...], 'totals': {...}, 'profit_sum': <float>}
```
- кожен елемент списків — результат `evaluate`;
- **кошик — перший, що підійшов**, саме в цьому порядку:
  1. `too_big` — `fit['state'] == 'too_big'`;
  2. `unknown_dims` — `fit['state'] == 'unknown'`;
  3. `no_price` — `status == 'no_data'` або нема ставки комісії для категорії;
  4. `overpriced` — `status == 'uncompetitive'`;
  5. `low_margin` — `profit < min_profit`;
  6. `ready` — решта (у них `ok is True`).
- товар із категорією, якої нема в `ranges_by_category` і без запасної під ключем `None`,
  потрапляє в `no_price` з `why == 'ціна: нема ставки комісії'` і **не викликає** `price_item`;
  його `price`, `profit`, `status`, `commission` — `None`;
- `totals` — `{назва кошика: кількість}` по шести кошиках плюс `'all'`;
- `profit_sum` — сума `profit` по `ready`, округлена до 2 знаків (порожній `ready` → `0.0`);
- порядок усередині кошиків — порядок вхідних даних.

### `report(selection)`
```
📦 Доставка в магазини ROZETKA: підходить 2 з 6
Прохідні: очікуваний прибуток 468.32 ₴ (доставка 35 ₴ уже врахована)
Завеликі: 1 · Дорожчі за конкурентів: 1 · Без ціни: 1 · Мала маржа: 0 · Без габаритів: 1
⚠️ Без габаритів не можна вважати прохідними — це 1 товар
• GAAR1002 — 976 ₴, прибуток 265.32 ₴
• T825051 — 1141 ₴, прибуток 203.00 ₴
```
- другий рядок лише якщо `ready` непорожній; рядок `⚠️` лише якщо `unknown_dims` непорожній;
- перелік — лише `ready`, максимум 20 рядків, далі `'… і ще N'`;
- порожній вхід → `'Нема даних'`.

## Правила
- Нічого не друкувати в stdout, не писати на диск, не ходити в мережу й БД.
- **Не змінювати** `tools/price_engine_toptul.py` і його тести.
- Не чіпати `tests/`, `.env`, фіди.
- Жодного «припустимо, вага 1 кг»: відсутні дані лишаються відсутніми.

## Приймання
```
venv/bin/python -m pytest tests/test_rz_delivery_fit.py -q       → зелені
venv/bin/python -m pytest tests/ -q -k 'not rz_delivery_fit'     → зелені
```
Звіт `docs/reports/TASK-34-report.md`.

## Відповіді на можливі питання
1. **Чому 15 кг, а не 30** — див. розбіжність вище; беремо суворіше й пишемо чому.
2. **Вага відома й завелика, сторони невідомі** — це `too_big`: доведене перевищення сильніше
   за брак решти даних.
3. **`competitors` порожній** — товар не може стати `overpriced`, бо порівнювати нема з чим.
4. **`min_profit`** за замовчуванням 0: беззбитковість. Від'ємний `min_profit` → `ValueError`.
5. **Округлення** — усі гроші через `round(..., 2)`, ціна ціла (так робить `price_item`).
