# ЗАВДАННЯ 11: нові команди читання в боті — виконавці й відповіді (фаза A2, частина 2)

**Виконавець:** Codex. **Приймає:** рецензент за `tests/test_commands_v2.py` і читанням коду.
**Дата:** 20.09.2026. **Спирається на:** TASK-09 (`intents`, `catalog`), TASK-10 (методи адаптера),
TASK-02/06 (`commands.dispatch`, `helper/services.build_fetchers`).

## 1. Навіщо

Наміри (TASK-09) і методи API (TASK-10) є, але бот на них не відповідає. Потрібно:
1. реєстр `commands.ALL_COMMANDS` для всіх намірів каталогу (`label`, `buyer_rating` — без виконавця, див. §5);
2. форматування відповідей — окремий модуль `views.py`;
3. `build_fetchers` — нові ключі з переданих залежностей.

## 2. Файли

Змінити: `tg_dispatcher/ai_brain/commands.py`, `helper/services.py`.
Створити: `tg_dispatcher/ai_brain/views.py`. Інших файлів не чіпати.

## 3. `commands.py`

- **`COMMANDS` не змінювати**: старий тест `test_registry` перевіряє, що в ньому рівно 8 старих
  команд. Натомість новий реєстр `ALL_COMMANDS = {**COMMANDS, <нові>}`, де кожен новий запис —
  `{'needs': catalog.CATALOG[i]['needs'], 'fetcher': i, 'title': catalog.CATALOG[i]['title']}`
  (ключ fetcher'а = назва наміру). `dispatch` і `missing_params` працюють з `ALL_COMMANDS`.
- `_PROMPTS` — підказки для нових обов'язкових параметрів: `status` («Уточніть: скасовані,
  виконані чи в дорозі»), `article` («Вкажіть артикул постачальника»).
- `dispatch` — для нових намірів викликати форматувальник із `views.FORMATTERS[intent]`;
  передавати fetcher'у **лише** параметри з `needs` плюс `marketplace`, `period`, `status`,
  `source`, `goods_tab`, якщо вони є. Для `supplier_stock` параметр `sku` передається як
  `article`, якщо `article` нема.
- `fmt_help()` — тепер `catalog.help_text()` (усі команди). Старі тести мають лишитись зеленими;
  якщо старий тест перевіряє інший формат довідки — **не змінюй тест**, опиши розбіжність у звіті
  й залиш сумісну поведінку.

## 4. `views.py` — відповіді (звичайний текст, усе через `privacy.mask_private`)

```python
FORMATTERS: dict[str, callable]    # намір → функція(result, params) -> str
```
| намір | результат fetcher'а | вимоги до тексту |
|---|---|---|
| `orders_counts` | `{'new','in_work','delivering','done','unwatched'}` | рядки «Нових: N», «У роботі: N», «В дорозі: N», «Виконано: N»; `None` → «—» |
| `orders_search` | список замовлень (як `clean_order`) | заголовок зі станом («Скасовані замовлення: N»); по рядку `№id — amount грн`; порожньо → «Замовлень немає» |
| `orders_without_ttn` | список `{'id','created','source'}` | «Без ТТН: N» + рядки `№id (source) з created`; порожньо → «✅ Усі замовлення мають ТТН» |
| `ttn_stuck` | список `{'ttn','order_id','status','days'}` | «Без руху: N» + рядки `ttn — status, days дн.`; порожньо → «✅ Посилок без руху немає» |
| `refunds` | список `clean_refund` з `kind` і квитків `return_tickets` з `kind='ticket'` | «Повернення: N» + для `refund`: `№order_id — item_name — status_title`; для `ticket`: `№order_id — повернення товару, ТТН ttn`; порожньо → «Повернень немає» |
| `refund_detail` | список `clean_refund(detail)` | для кожного: замовлення, товар, статус, причина, рішення; порожньо → «Повернень по цьому замовленню немає» |
| `item_comments` | список `clean_comment` | «Питання й відгуки: N (нових: K)» + рядки `❓/⭐ title — text[:120]`; непрочитані позначати `🆕` |
| `shop_reviews` | список `clean_review` | «Відгуки про магазин: N» + `👍/👎 №order_id: comment[:120]`; `vote=='like'` → 👍 |
| `unanswered_chats` | список з `unanswered()` | «Без відповіді: N» + `мітка · чат id: <тривалість>` (`1 д 13 год` / `45 хв`); порожньо → «✅ Усім покупцям відповіли» |
| `moderation` | `{джерело: {вкладка: int}}` | рядок на джерело: `toptul: модерація 5917, помилки 0, приховані 3` |
| `supplier_stock` | `{'article','state','qty','price'}`; `state` ∈ `in_stock`,`out`,`unknown` | «є», «немає», «**невідомо**» (три стани — правило власника; невідомо ≠ немає) |
| `supplier_ttn` | список `{'order_id','ttn','supplier'}` | «ТТН від постачальників: N» + рядки; порожньо → «ТТН сьогодні ще не надходили» |
| `balance` | `{'balance','sum_in_gray','subscription_balance'}` | «Баланс: X грн», «Заблоковано: Y грн», «Підписка: Z грн» |
| `backup_status` | `{'last': str|None, 'size_mb': float|None, 'age_h': float|None, 'ok': bool}` | ✅/❌, дата, розмір, «N год тому»; `last=None` → «❌ Бекапів не знайдено» |

Тривалість: `< 60` хв → `N хв`; `< 24` год → `N год M хв`; інакше `N д M год`.

## 5. `helper/services.build_fetchers` — нові ключі

```python
def build_fetchers(rozetka=None, novaposhta=None, stock_lookup=None, feeds_status=None,
                   system_status=None, unanswered=None, backup_status=None,
                   supplier_stock=None, supplier_ttn=None, orders_without_ttn=None,
                   ttn_stuck=None) -> dict
```
- з `rozetka`: `orders_counts` → `order_counts()`;
  `orders_search(status)` → `orders(1)` (усі замовлення), відфільтровані за `status_group`
  (перевірено 19.09 наживо: 2 — виконані/отримані, 3 — скасовані/повернуті, 1 — у роботі):
  `completed` → група 2; `cancelled` → група 3; `delivering` → група 1 **і** непорожня `ttn`;
  `refunds` → `refunds()` + `return_tickets()` одним списком, у кожного елемента поле
  `kind` = `'refund'` / `'ticket'`; `refund_detail(order_id)` → `refund_for_order(order_id)`;
  `item_comments` → `item_comments()`; `shop_reviews` → `shop_reviews()`; `balance` → `balance()`;
  `moderation(source, goods_tab)` → `{src: {tab: goods_count(tab, src)}}` для заданого джерела
  (або всіх з модуля `integrations.rozetka.SOURCES`) і вкладки (або всіх трьох: `moderation`, `errors`, `hidden`).
- решта ключів — з однойменних переданих функцій (без параметрів або з `article`).
- `label`, `buyer_rating` у цьому завданні **не** підключаються (друк файлу — окремо; значення
  рейтингу ще не підтверджене власником) → `dispatch` скаже «Команда ще не підключена».

## 6. Приймання

```
venv/bin/python -m pytest tests/test_commands_v2.py -q        → зелені
venv/bin/python -m pytest tests/ -q -k "not commands_v2"      → зелені
```
Звіт `docs/reports/TASK-11-report.md` з «Самостійними рішеннями».
