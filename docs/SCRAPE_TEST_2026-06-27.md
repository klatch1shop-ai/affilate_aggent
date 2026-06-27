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
