# EPICENTR_AUDIT.md — Повна ревізія Єпіцентр-напрямку
Дата: 2026-06-28. Автор: claude-sonnet-4-6 (сесія аудиту).

---

## 1. ІНСТРУМЕНТИ — ТАБЛИЦЯ ГОТОВНОСТІ

| Інструмент | Статус | Призначення | Що не так / що зробити |
|---|---|---|---|
| `tools/carvol_epicentr_generator.py` | ✅ **Робочий** | Carvol прайс → Єпіцентр XML | 4907 прибрано ✅. Немає обробника для 2874 і 2865. |
| `epicentr_postprocess.py` (корінь) | ✅ **Робочий** | Фільтр фото + дедуп + 2883→2848 | Чистий. |
| `tools/epicentr_xml_checker.py` | ✅ **Робочий** | Валідація XML перед імпортом | 2874 в VALID_CATS, але немає REQUIRED_PARAMS[2874] — не перевіряє params. Не перевіряє JPEG, 500x500px. |
| `tools/epicentr_pim_explorer.py` | ✅ **Робочий** | PIM API: пошук брендів/країн, кеш 54370 | OUR_CATS містить застарілі 4907 і 2883 (тільки довідник, не впливає на XML). |
| `tools/epicentr_attrs_explorer.py` | ✅ **Робочий** | Сканує attribute-sets, кешує в epicentr_required_attrs | OUR_CATS містить 4907 (аналогічно). Скрипт-утиліта, не pipeline. |
| `tools/epicentr_quality_checker.py` | ✅ **Робочий** | SEO скоринг XML (avg 73/100) | Не запускався після останніх змін — потребує повторного запуску після фіксу pipeline. |
| `tools/ai_xml_generator.py` | ⚠️ **Частково** | Flask веб-інструмент (:5556) для генерації XML вручну | Запущено на сервері з Jun 14. Містить `<category code="4907">` в шаблоні. Не є частиною pipeline Carvol. |
| `tools/web_api_explorer.py` | ⛔ **Не запущено** | Flask веб-інтерфейс API (:5555) | Порт 5555 DOWN. 5556 (ai_xml_generator) живий. api_test_log — 0 записів, жодного API-дзвінка через UI не тестувалось. |
| `tools/epicentr_category_mapper.py` | 🗄️ **Застаріє** | Fuzzy-match TOPTUL категорій → Єпіцентр | TOPTUL видаляється з Єпіцентру. Інструмент залишається для нових постачальників, але зараз не потрібен. |
| `tools/epicentr_confirm_categories.py` | 🗄️ **Застаріє** | Інтерактивне підтвердження маппінгу TOPTUL | Те саме — TOPTUL-орієнтований. |
| `tools/epicentr_fill_attributes.py` | 🗄️ **Застаріє** | Заповнює атрибути в TOPTUL XLSX-експорті | 13 хендлерів для TOPTUL категорій (Воротки, Ключі, etc.). Нуль хендлерів для Carvol категорій. |
| `shared/mcp_servers/epicentr_mcp.py` | ✅ **Робочий** | MCP: управління OMS-замовленнями Єпіцентру | delete_products — НЕ існує і не може бути реалізовано (Merchant API не підтримує). |
| `agents/orders/epicentr_order_agent.py` | ✅ **Запущено** | Daemon: нові замовлення → підтвердження | Живий (PID 1006, з Jun 03). |

---

## 2. РОЗБІЖНОСТІ: knowledge_base vs реальний код

### import_rules.md → що не реалізовано в xml_checker

| Правило з import_rules.md | Перевіряється в xml_checker? | Проблема |
|---|---|---|
| name lang="ua" обов'язково | ✅ Так | — |
| description lang="ua" обов'язково | ✅ Так | — |
| price > 0 | ✅ Так | — |
| Мінімум 1 фото | ✅ Так | — |
| Фото тільки JPEG (.jpg/.jpeg) | ❌ НІ | Перевіряється тільки https://, не розширення |
| Фото мінімум 500×500 px | ❌ НІ | Взагалі не перевіряється |
| weight/width/height/length > 0 | ✅ Так (bad_dims) | — |
| XML через URL — можна дати менеджеру GitHub raw URL | ❌ НЕ РЕАЛІЗОВАНО | Поки тільки ручне завантаження. URL — наступний крок. |
| 2874 Автосвітло — треба активувати | ⚠️ Частково | VALID_CATS має 2874, але REQUIRED_PARAMS[2874] відсутній. Генератор теж не має elif 2874. |

### CLAUDE.md → застарілий запис

| Місце | Проблема | Що зробити |
|---|---|---|
| CLAUDE.md рядок 62 | `\| 4907 \| Магнітоли \| 4907 \|` в таблиці "Наші категорії Єпіцентр" | Видалити рядок з 4907, залишити 2866 |
| CLAUDE.md рядок 27 (TASKS.md аналог) | "Params для всіх 6 категорій: 8743, 2866, 3729, 4907, 2848, 2821" | Замінити 4907 → вже замінено в генераторі, але документація не оновлена |

---

## 3. ЄПІЦЕНТР API — СТАТУС РЕАЛІЗАЦІЇ (30 методів)

### Реалізовано в epicentr_mcp.py (16/30):
| Метод | Endpoint | Статус |
|---|---|---|
| get_orders_list | GET /v3/oms/orders | ✅ |
| get_orders_total | GET /v3/oms/orders/total | ✅ |
| get_order_details | GET /v5/oms/orders/{id} | ✅ |
| change_status | POST /v2/oms/orders/{id}/change-status/to/{status} | ✅ |
| get_allowed_statuses | GET /v2/oms/orders/{id}/allowed-statuses | ✅ |
| add_ttn | POST /v3/oms/orders/{id}/shipping/{provider} | ✅ |
| add_ttn_fallback | PATCH /v1/oms/orders/{id}/shipment-number | ✅ |
| get_cancel_reasons | GET /v2/oms/order-cancel-reasons/customer | ✅ |
| add_comment | POST /v2/oms/orders/{id}/comments | ✅ |
| update_client_data | POST /v3/oms/orders/{id}/client-data | ✅ |
| update_delivery | POST /v3/oms/orders/{id}/delivery-data/{provider} | ✅ |
| find_settlements | GET /v3/deliveries/.../settlements | ✅ |
| find_offices | GET /v3/deliveries/.../offices | ✅ |
| get_invoice | GET /v3/deliveries/{provider}/.../invoice/{number} | ✅ |
| get_categories | GET /v2/pim/categories | ✅ |
| get_attribute_options | GET /v2/pim/attribute-sets/{code}/attributes/{attr}/options | ✅ |

### НЕ реалізовано (14/30) — по пріоритету:
| Метод | Endpoint | Пріоритет | Коментар |
|---|---|---|---|
| Деталі відгуку | GET /v1/reviews/{reviewId} | 🔴 Середній | Важливо для репутації |
| Відповідь на відгук | PUT /v1/reviews/answer/{reviewId} | 🔴 Середній | Відповідати на відгуки через API |
| get_attribute_sets | GET /v2/pim/attribute-sets | ⚠️ Є в DB але false | epicentr_attrs_explorer вже робить це напряму |
| Посилання оплати | POST /v2/oms/orders/{orderId}/payment/generate-url | 🟡 Низький | |
| Список коментарів | GET /v2/oms/orders/{orderId}/comments | 🟡 Низький | |
| Статус дзвінка | POST /v2/oms/orders/{orderId}/call-status | 🟡 Низький | |
| Провайдери доставки | GET /v1/deliveries/shipments/.../providers | 🟡 Низький | |
| Способи оплати компанії | GET /v3/payments/companies/{companyId} | 🟡 Низький | |
| Видалити ТТН | DELETE /v1/oms/orders/{orderId}/shipment-number | 🟡 Низький | |
| Видалити товар із замовлення | DELETE /v2/oms/orders/{orderId}/items/{offerId} | 🟡 Низький | |
| Змінити кількість товару | PUT /v3/oms/orders/{orderId}/items/{offerId} | 🟡 Низький | |
| Додати товар до замовлення | POST /v3/oms/orders/{orderId}/items | 🔵 Дуже низький | API не підтримує |
| Реєстрація push-пристрою | POST /v1/device | 🔵 Дуже низький | Мобільні сповіщення |
| Видалити пристрій | DELETE /v1/device/{id} | 🔵 Дуже низький | |

> ⚠️ **api_test_log = 0 записів** — жодний Єпіцентр endpoint не тестувався через web_api_explorer. web_api_explorer (порт 5555) ВИМКНЕНИЙ.

---

## 4. АНОМАЛІЇ КАТЕГОРІЙ

| Категорія | В генераторі | В xml_checker VALID_CATS | В DB cat_map | Статус |
|---|---|---|---|---|
| 8743 Перехідні рамки | ✅ elif | ✅ | ✅ | Активна |
| 2866 Автомагнітоли | ✅ elif (+ штатна) | ✅ | ✅ | Активна |
| 3729 Камери | ✅ elif | ✅ | ✅ | Активна |
| 2821 Кабелі | ✅ elif | ✅ | ✅ | Активна |
| 2848 Аксесуари сигналізацій | ✅ (дефолт dims) | ✅ | ✅ | Активна |
| 2874 Автосвітло | ❌ немає elif | ✅ але без params | ❌ немає | **Незавершена** — потребує активації в кабінеті + elif в генераторі |
| 2865 Автоакустика | ❌ немає elif | ❌ | ✅ є в cat_map | **Невідповідність** — є в DB але не в коді |
| 4907 Магнітоли (стара) | ❌ прибрано ✅ | ⚠️ WARN_CATS | ❌ | Deprecated — WARN_CATS коректний |
| 2883 LED-світло (стара) | ❌ прибрано | ⚠️ WARN_CATS | ❌ | Deprecated → замінено на 2848 через postprocess |

---

## 5. ПРІОРИТИЗОВАНИЙ ПЛАН ДІЙ

### Швидко (1 файл, 15-30 хв)
| # | Завдання | Файл | Складність |
|---|---|---|---|
| A | Прибрати 4907 з OUR_CATS в epicentr_pim_explorer.py і epicentr_attrs_explorer.py | 2 файли | Тривіально |
| B | Виправити CLAUDE.md рядок 62 (видалити 4907 з таблиці "Наші категорії") | CLAUDE.md | Тривіально |
| C | Виправити ai_xml_generator.py рядки 50-51 (4907 → 2866 в шаблоні) | ai_xml_generator.py | Тривіально |
| D | Додати REQUIRED_PARAMS['2874'] в xml_checker (коли категорія буде активована) | epicentr_xml_checker.py | 30 хв |

### Середній пріоритет (2-4 год)
| # | Завдання | Файл | Складність |
|---|---|---|---|
| E | Запустити web_api_explorer.py на порту 5555 + переконатися що epicentr endpoints актуальні | tools/web_api_explorer.py | 1-2 год |
| F | Додати перевірку JPEG розширення в xml_checker | epicentr_xml_checker.py | 30 хв |
| G | Реалізувати "Відповідь на відгук" в epicentr_mcp.py | epicentr_mcp.py | 1 год |
| H | 2865 Автоакустика: або додати elif в генератор, або прибрати з DB cat_map — вирішити що робити | генератор + DB | 2 год |

### Потребує зовнішньої дії спочатку
| # | Завдання | Блокер |
|---|---|---|
| I | Активувати 2874 (Автосвітло) через Євгенія/Світлану → написати elif в генераторі | Менеджер Єпіцентру |
| J | Дати менеджеру GitHub raw URL для автоімпорту XML (не ручне завантаження) | Контакт зі Світланою |
| K | Реєстрація бренду QIV → підніме score з 73 → ~93 для 6110 офер | Менеджер Єпіцентру |

### Застарілий код (видалити або архівувати)
| Файл | Рекомендація |
|---|---|
| `tools/epicentr_category_mapper.py` | Залишити (корисний для нових постачальників), але позначити як "not for Carvol" |
| `tools/epicentr_confirm_categories.py` | Те саме |
| `tools/epicentr_fill_attributes.py` | Залишити (13 TOPTUL хендлерів можуть знадобитись знову), але позначити |

---

## 6. СТАН PIPELINE (summary)

```
Carvol прайс (SpreadsheetML)
    ↓ carvol_epicentr_generator.py  ← ✅ ГОТОВИЙ (після фіксу кат. плутанини)
exports/carvol_epicentr_new.xml
    ↓ epicentr_postprocess.py       ← ✅ ГОТОВИЙ
exports/carvol_epicentr.xml
    ↓ epicentr_xml_checker.py       ← ✅ ГОТОВИЙ (з вище описаними обмеженнями)
    ↓ [ручне завантаження кабінет]  ← ⚠️ НЕ АВТОМАТИЗОВАНО
Єпіцентр — 7075 товарів
```

**Головне що блокує production:** категорійна плутанина 4907/2866/2848/2874 (Крок 2 з TASKS.md — аудит показав що генератор вже чистий, але потребує тест-генерації + xml_checker + тест-завантаження 1 товару для підтвердження).
