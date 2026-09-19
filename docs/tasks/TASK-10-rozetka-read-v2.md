# ЗАВДАННЯ 10: адаптер Rozetka — нові методи читання (фаза A2 матриці)

**Виконавець:** Codex. **Приймає:** рецензент за `tests/test_rozetka_read_v2.py` і читанням коду.
**Дата:** 20.09.2026. **План:** `docs/COMMAND_MATRIX.md`, фаза A2. **Спирається на:** TASK-05
(`integrations/rozetka.py` — конверт, помилки, білий список), TASK-09 (наміри).

## 1. Навіщо

Нові команди читання (лічильники, повернення, відгуки, баланс, модерація за джерелом, лічильники
чатів) потребують методів адаптера. **Лише читання.** Відповіді майданчика містять персональні
дані покупців (ПІБ, телефон, останні цифри картки, IBAN) — адаптер віддає **лише білий список**
полів (як `clean_order` у TASK-05).

## 2. Що відомо (перевірено 20.09 запитами лише на читання; документація — `shared/knowledge_base/rozetka/apidoc/`)

| метод API | живий результат |
|---|---|
| `GET /orders/counts` | `content = {'unwatched', 'new', 'inNotDone', 'delivering', 'inDone'}` — **не** як у документації |
| `GET /order-refund/search?page=` | `{'orderRefunds': [...], '_meta'}`; запис (документація): `id` (str), `status_title`, `reason_title`, `order_id`, `item_name`, `item_id`, `datetime`, `read`, `delivery_id`, **`buyer_surname`, `buyer_name`, `buyer_patronymic`, `buyer_phone`** |
| `GET /order-refund/detail/{id}` | як вище + `order_date`, `chat_id`, `sub_reason_title`, `sub_reason_comment`, `decision_title`, `sub_decision_title`, **`card_last_digits`**, **`iban`…** |
| `GET /item-return/ticket/search?page=` | `{'tickets': [{'id', 'order_id', 'carrier', 'ttn', 'status', 'expires_at', 'items': [{'name', 'qty_expected', 'qty_received', 'status', ...}]}], '_meta'}` |
| `GET /item-comments/search?page=` | `{'itemComments': [...]}`; запис: `id`, `type` (`question`/`comment`), `created`, `status`, `text`, `mark`, `is_reade` (sic), `has_children`, `is_un_reade_child`, `record: {'title'}`, `item: {'article', 'name_ua', 'name'}`, **`name`, `email`, `user_id`** |
| `GET /market-reviews/search?page=` | `{'marketReviews': [...]}`; запис: `id`, `order_id`, `vote`, `status`, `created_at`, `read`, `comment`, `reply`, `problem_solved`, **`user`** |
| `GET /balances/total` | `{'totalBalance': [{'balance', 'sumInGray', 'subscription_balance'}]}` (рядки) |
| `GET /goods/{tab}?sync_source_id=&page=1` | `{'count', 'items', '_meta': {'totalCount', ...}}`; `tab` ∈ `moderation`, `errors`, `hidden`, `on-sale`, `new` |
| `GET /messages/counts` | `{'ordersChatUnread', 'ordersChatAll', 'itemsChatUnread', 'itemsChatAll', 'sellerChatUnread', 'sellerChatAll', ...}` |
| `GET /invoices/search` | **`access_denied`** — ключ не має прав; методу не робити |

Джерела (`sync_source_id`): `dropoffice` 55861, `toptul` 55634, `noire` 54788, `carvol` 51949.

## 3. Файли

Змінити лише `integrations/rozetka.py` (додати методи й константи; наявні не змінювати).

## 4. Інтерфейс (додати в `RozetkaClient` і модуль)

```python
SOURCES = {'dropoffice': 55861, 'toptul': 55634, 'noire': 54788, 'carvol': 51949}
GOODS_TABS = ('moderation', 'errors', 'hidden', 'on-sale', 'new')
REFUND_FIELDS = ('id', 'status_title', 'reason_title', 'order_id', 'item_name', 'item_id', 'datetime', 'read')
REFUND_DETAIL_FIELDS = REFUND_FIELDS + ('order_date', 'chat_id', 'sub_reason_title', 'sub_reason_comment',
                                        'decision_title', 'sub_decision_title')

def clean_refund(r: dict, detail: bool = False) -> dict
def clean_comment(c: dict) -> dict
def clean_review(r: dict) -> dict

class RozetkaClient:
    def order_counts(self) -> dict
    def refunds(self) -> list[dict]
    def refund_detail(self, refund_id) -> dict
    def refund_for_order(self, order_id) -> list[dict]
    def return_tickets(self) -> list[dict]
    def item_comments(self) -> list[dict]
    def shop_reviews(self) -> list[dict]
    def balance(self) -> dict
    def goods_count(self, tab: str, source: str | None = None) -> int
    def messages_counts(self) -> dict
```

- **Конверт і помилки** — через наявний `_request` (AuthError / NotFound / ApiError як у TASK-05).
- **Списки** (`refunds`, `return_tickets`, `item_comments`, `shop_reviews`): сторінки 1…`pageCount`
  (≤ `max_pages`, інакше `ApiError` «неповний список», як `orders`); `pageCount == 0` → `[]`
  після першої сторінки.
- `order_counts()` → рівно ключі `new`, `in_work` (= `inNotDone`), `delivering`, `done` (= `inDone`),
  `unwatched`; відсутній ключ → `None`. Значення — `int`.
- `clean_refund(r, detail)` — лише `REFUND_FIELDS` (або `REFUND_DETAIL_FIELDS`); відсутні → `None`.
  **Жодних** `buyer_*`, `card_*`, `iban*`. Текстові поля (`sub_reason_comment`) — через
  `tg_dispatcher.privacy.mask_private`.
- `refund_detail(refund_id)` — `GET /order-refund/detail/{id}` → `clean_refund(..., detail=True)`.
  `refund_id` — непорожній рядок/число, інакше `ValueError`.
- `refund_for_order(order_id)` — `order_id` 9 цифр (інакше `ValueError`); `GET /order-refund/search`
  з `params={'order_id': id, 'page': 1}` → список `clean_refund`.
- `return_tickets()` → кожен: `{'id', 'order_id', 'carrier', 'ttn', 'status', 'expires_at',
  'items': [{'name', 'qty_expected', 'qty_received', 'status'}]}`.
- `clean_comment(c)` → `{'id', 'type', 'created', 'status', 'read': bool(is_reade), 'mark',
  'has_answer': bool(has_children), 'title': record.title, 'article': item.article,
  'item_name': item.name_ua або item.name, 'text': mask_private(text)}`. **Без** `name`, `email`, `user_id`.
- `clean_review(r)` → `{'id', 'order_id', 'vote', 'status', 'created_at', 'read', 'problem_solved',
  'comment': mask_private(str) або None, 'reply': mask_private(str) або None}`. **Без** `user`.
  (`comment`/`reply` можуть бути рядком, числом-ознакою або `None`: рядок — маскувати; інше → `None`.)
- `balance()` → `{'balance': str, 'sum_in_gray': str, 'subscription_balance': str}` з першого
  елемента `totalBalance`; порожній список → `ApiError`.
- `goods_count(tab, source)` — `tab` з `GOODS_TABS`, `source` з `SOURCES` або `None` (інакше
  `ValueError`); `GET /goods/{tab}` з `params={'page': 1}` (+ `'sync_source_id': id`) →
  `int(_meta.totalCount)`; нема `_meta.totalCount` → `ApiError`.
- `messages_counts()` → словник як є (лише цілі значення верхнього рівня, вкладені словники — пропустити).

## 5. Приймання

```
venv/bin/python -m pytest tests/test_rozetka_read_v2.py -q      → зелені
venv/bin/python -m pytest tests/ -q -k "not rozetka_read_v2"    → зелені
```
Звіт `docs/reports/TASK-10-report.md` з «Самостійними рішеннями».
