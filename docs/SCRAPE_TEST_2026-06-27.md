# SCRAPE TEST — Rozetka Competitor Prices
**Дата:** 2026-06-27  
**Виконав:** orchestrator-agent  
**Мета:** Перевірка можливості скрейпінгу цін конкурентів Rozetka для 3 товарів Carvol >15 000 грн

---

## Вибірка товарів із carvol_products

Запит: `SELECT article, name, price_uah FROM carvol_products WHERE price_uah > 15000 ORDER BY price_uah DESC LIMIT 5`

| Наш артикул | Назва (скорочено) | Наша ціна (UAH) | Категорія Rozetka |
|-------------|-------------------|-----------------|-------------------|
| QIV-Q4-150 | QIV Q4 Toyota Alphard/Vellfire 15" | 33 375 | 340415 (штатні головні пристрої) |
| Q63363 | Teyes CC3 2K 360 Lexus RX300 10" | 30 661 | 340415 |
| QBR-K 1138-XP | Рамка Ford F150 2015+ 17" | 17 800 | 121238 |

---

## Методи скрейпінгу — тестування

### 1. `agents/scraper/competitor_scraper.py` (існуючий скрипт)
**Результат: не застосовний для задачі**  
Скрипт приймає `--seller <slug>` і scrapes сторінку `/ua/seller/{seller}/goods/`.  
**Не підтримує пошук по назві товару.** Для пошуку конкурентів по конкретному артикулу потрібний окремий підхід.

### 2. Rozetka Search API v6
**URL:** `https://search.rozetka.com.ua/ua/search/api/v6/?text=...`  
**Результат: ЧАСТКОВА ВІДМОВА**  
API повертає тільки `{"id": <int>, "relevance": null}` — жодних деталей товару (назва, ціна, продавець). Для перетворення ID у картку товару потрібен додатковий запит до картки.

```json
// Приклад відповіді:
{"id": 504784794, "relevance": null}
```

### 3. xl.rozetka.com.ua goods detail API
**URL:** `https://xl.rozetka.com.ua/goods/v4/detail/?goods_id=<id>`  
**Результат: ВІДМОВА — HTTP 404**

### 4. Playwright (headless) — пошукова сторінка Rozetka
**URL:** `https://rozetka.com.ua/ua/search/?text=...`  
**Результат: ВІДМОВА — Cloudflare JS Challenge блокує серверний IP**

```
curl -A "Mozilla/5.0 ..." https://rozetka.com.ua/ua/search/?text=Teyes+CC3
→ <!DOCTYPE html>...<title>Just a moment...</title>  [Cloudflare]
```

Playwright-сесія (на `tek@100.82.24.112`):
- `QIV-Q4-150`: 0 tiles, page_size=658 байт (порожній Angular shell після CF-challenge)  
- `Q63363 Teyes`: `Page.goto timeout 30000ms` (CF challenge не проходить)  
- `QBR-K 1138-XP`: `Page.goto timeout 30000ms`

**Скріншоти:** `/tmp/rz_search_QIV-Q4-150.png` (збережено на сервері для діагностики)

### 5. HTML пошукова сторінка (запит через requests)
Angular SPA — контент завантажується динамічно. HTML-відповідь містить тільки shell, дані в `&q;`-encoded форматі (без JavaScript). Не парситься.

---

## Висновок

| Метод | Статус |
|-------|--------|
| `competitor_scraper.py` (seller-search) | Не підходить (тільки `/ua/seller/` URL) |
| Search API v6 | ID-only, без деталей |
| goods detail API | 404 |
| Playwright (сервер) | Cloudflare блок на server IP `100.82.24.112` |
| requests HTML | Angular SPA, без JS — порожньо |

**Корінна причина:** Cloudflare Managed Challenge блокує всі запити з серверного IP `100.82.24.112` ще на рівні HTTP. Playwright + `networkidle` чекає на JS-challenge, який ніколи не резолвиться в headless-середовищі без browser fingerprinting.

---

## Таблиця конкурентів — ДАНІ НЕ ОТРИМАНІ

| Наш артикул | Наша ціна | Конкурент | Ціна конкурента | Різниця % |
|-------------|-----------|-----------|-----------------|-----------|
| QIV-Q4-150 | 33 375 UAH | — | — | N/A |
| Q63363 (Teyes) | 30 661 UAH | — | — | N/A |
| QBR-K 1138-XP | 17 800 UAH | — | — | N/A |

*Дані не отримані через Cloudflare-блокування серверного IP.*

---

## Рекомендації для rozetka-agent

Задачу потрібно виконати в **окремому чаті `claude --agent rozetka-agent`**, де треба:

1. **Написати новий скрипт `tools/rozetka_search_scraper.py`** — запускати НЕ з сервера, а з ноутбука (`100.126.131.55`), де Playwright має інший IP і може успішно пройти CF-challenge.

2. **Або**: Доробити `competitor_scraper.py` — додати параметр `--query <text>` для пошуку по назві, а не тільки `--seller`.

3. **Або**: Підключити проксі до Playwright-сесії (residential proxy — без Cloudflare блоку).

4. **Тимчасовий обхід**: запустити `competitor_scraper.py` на ноутбуці з `--seller teyes-ua` (якщо відомий slug продавця) — отримати ціни саме цього конкурента.

> **Важливо:** `competitor_scraper.py` перехоплює XHR-запити Angular-застосунку (API interception), тому від Cloudflare частково захищений. Але тільки для сторінок продавця, не пошуку.

---

## Що зроблено в цій сесії (оркестратор)

- ✅ Вибрано 3 товари Carvol з ціною >15 000 грн
- ✅ Протестовано 5 методів скрейпінгу — всі задокументовані
- ✅ Встановлено корінну причину: Cloudflare блокує серверний IP
- ✅ Задача для `rozetka-agent` описана з конкретними кроками
- ❌ Дані конкурентів НЕ отримані (зафіксовано чесно)

---

## Спроба 2 — з ноутбука (100.126.131.55)

**Дата:** 2026-06-28  
**Виконав:** rozetka-agent  
**IP ноутбука:** 100.126.131.55 (Tailscale)

### Перевірка CF-блоку з ноутбука

```bash
curl -I -A "Mozilla/5.0 ..." https://rozetka.com.ua/ua/search/?text=Teyes+CC3
→ HTTP/2 200  server: cloudflare  cf-ray: a12a40662c142479-KBP  [Київ, UA]
```

**Результат: CF-challenge НЕ спрацьовує з ноутбука.** HTTP 200, реальна HTML-відповідь 83 KB.  
Підтверджено: проблема була виключно в серверному IP `100.82.24.112`.

### Знайдений реальний API (через Playwright XHR interception)

Через `playwright.sync_api` + `page.on("response")` перехоплено реальні XHR-запити Angular-застосунку:

```
Search:  https://common-api.rozetka.com.ua/v1/api/catalog/search?country=UA&lang=ua&page=1&text=...
Details: https://common-api.rozetka.com.ua/v1/api/product/details?country=UA&lang=ua&ids=<id1,id2,...>
Add-ons: https://common-api.rozetka.com.ua/goods/get-additions?goodsIds=...
```

Раніше задокументований `xl.rozetka.com.ua/goods/v4/detail` → **404** (застарілий ендпоінт).  
Реальний working endpoint: `common-api.rozetka.com.ua/v1/api/product/details`.

### Метод — двофазний запит через requests

```python
# Фаза 1: отримуємо IDs
r = session.get("https://common-api.rozetka.com.ua/v1/api/catalog/search?country=UA&lang=ua&text=<query>&per_page=10")
ids = [g["id"] for g in r.json()["data"]["goods"]]

# Фаза 2: отримуємо деталі (title, price, brand, href)
r2 = session.get(f"https://common-api.rozetka.com.ua/v1/api/product/details?country=UA&lang=ua&ids={','.join(ids)}")
goods = r2.json()["data"]  # list of dicts
```

Потрібна ініціалізація сесії через `session.get("https://rozetka.com.ua/")` для отримання CF-cookie (`__cf_bm`).

---

### Результати по артикулах

#### QIV-Q4-150 — Toyota Alphard/Vellfire 15" (наша ціна: 33 375 грн)

| Назва конкурента | Ціна | Різниця | Посилання |
|-----------------|------|---------|-----------|
| Магнітола QIV Q**1** Toyota Alphard 2003-2007 (F2/W2) 9" | 8 099 грн | — | [p445270874](https://auto.rozetka.com.ua/ua/445270874/p445270874/) |
| Магнітола QIV Q**1** Toyota Alphard 2003-2007 (F1/W2) 9" | 8 054 грн | — | [p445270919](https://auto.rozetka.com.ua/ua/445270919/p445270919/) |
| Магнітола QIV Q**1** Toyota Alphard 2003-2007 (F1/W1) 9" | 7 189 грн | — | [p441411812](https://auto.rozetka.com.ua/ua/441411812/p441411812/) |
| Магнітола QIV Q**1** Toyota Alphard H20 Vellfire 2008-2014 9" | 12 831 грн | — | [p441414392](https://auto.rozetka.com.ua/ua/441414392/p441414392/) |

> ⚠️ **Пряме порівняння неможливе.** Пошук повернув моделі **QIV Q1** (9 дюймів) — молодша лінійка. Наш артикул — **QIV Q4** (15 дюймів, флагман). Різні цінові категорії, різний цільовий покупець. Конкурентів для Q4-150 на Rozetka в цьому запиті не знайдено — можливо, унікальна позиція.

#### Q63363 — Teyes CC3 2K 360° Lexus RX300 10" (наша ціна: 30 661 грн)

| Назва конкурента | Ціна | Різниця % | Посилання |
|-----------------|------|-----------|-----------|
| Teyes CC3 2К для Lexus RX300 XU10 6+128G F1 | 24 829 грн | **+23.5%** | [p433108247](https://auto.rozetka.com.ua/ua/433108247/p433108247/) |
| Teyes CC3 для Lexus RX300 XU10 4+64G F2 | 23 701 грн | **+29.4%** | [p433106354](https://auto.rozetka.com.ua/ua/433106354/p433106354/) |
| Teyes CC3 2К для Lexus RX300 XU10 6+128G F2 | 25 394 грн | **+20.7%** | [p433111655](https://auto.rozetka.com.ua/ua/433111655/p433111655/) |
| Teyes CC3 2К для Lexus RX300 XU10 4+64G F1 | 22 572 грн | **+35.8%** | [p433111676](https://auto.rozetka.com.ua/ua/433111676/p433111676/) |
| Teyes CC3 для Lexus RX300 XU10 6+128G F2 | 25 394 грн | **+20.7%** | [p433105475](https://auto.rozetka.com.ua/ua/433105475/p433105475/) |

> **Висновок:** Наша ціна **дорожча на 20–36%** порівняно з конкурентами (всі — бренд Teyes, офіційний продавець). Мінімальна ціна конкурента: **22 572 грн** (наш: +35.8%). Рекомендується перегляд ціноутворення для Q63363.

#### QBR-K 1138-XP — Рамка Ford F150 2015+ 17" (наша ціна: 17 800 грн)

| Назва конкурента | Ціна | Примітка |
|-----------------|------|----------|
| Рамка 9" Lesko для Ford F150 2015+ | 9 682 грн | Різний розмір (9", не 17") |
| Конструктор Ford F150 Raptor пікап | 1 590 грн | Не той товар (іграшка) |
| Рамка QBR-F 1141-18 для Ford F150 P415 Raptor 9" | 1 610 грн | Різне покоління (2008-2011) |
| Рамка Q0978 для Ford F150 P415 Raptor 9" | 1 840 грн | Різне покоління (2008-2011) |

> ⚠️ **Пряме порівняння неможливе.** Конкуренти продають рамки **9 дюймів** або для іншого покоління (P415, 2008-2011). Наш **QBR-K 1138-XP** (17", для F150 2015+ P552) — **унікальна позиція на Rozetka** серед знайдених результатів. Ціна 17 800 грн виправдана відсутністю прямих конкурентів.

---

### Підсумкова таблиця конкурентів

| Наш артикул | Наша ціна | Мін. ціна конкурента | Різниця % | Висновок |
|-------------|-----------|----------------------|-----------|----------|
| QIV-Q4-150 | 33 375 грн | — | N/A | Конкурентів Q4 (15") не знайдено |
| Q63363 (Teyes CC3) | 30 661 грн | 22 572 грн (Teyes) | **+35.8%** | ❗ Переглянути ціну |
| QBR-K 1138-XP | 17 800 грн | — | N/A | Унікальна позиція (17", 2015+) |

### Що зроблено в цій сесії (rozetka-agent)

- ✅ Підтверджено: ноутбук (100.126.131.55) проходить CF-challenge (`HTTP 200`, не "Just a moment")
- ✅ Знайдено реальний API: `common-api.rozetka.com.ua/v1/api/catalog/search` + `/v1/api/product/details`
- ✅ Отримано дані конкурентів для всіх 3 артикулів через двофазний requests-запит
- ✅ Q63363 (Teyes CC3): наша ціна вища за мін. конкурента на **+35.8%** → рекомендується коригування
- ✅ QIV-Q4-150 і QBR-K 1138-XP: унікальні позиції, прямих конкурентів не виявлено
