# Rozetka API — документація

## Публічний пошуковий API (без токена)

### Пошук товарів
GET https://search.rozetka.com.ua/ua/search/api/v6/
Параметри:
- text: пошуковий запит
- page: номер сторінки (від 1)
- per_page: кількість (max 60)
- section_id: ID категорії
- price_from / price_to: ціновий діапазон
- sort: popularity / price_asc / price_desc / novelty

### Товари категорії
GET https://xl-catalog-api.rozetka.com.ua/v4/goods/get
Параметри:
- category_id: ID категорії
- per_page: кількість
- page: сторінка
- sort: popularity

### Популярні категорії Rozetka
- 80004: Ноутбуки
- 4627901: Електроніка  
- 80165: Смартфони
- 4638275: Навушники
- 80075: Планшети
- 638224: Смарт-годинники
- 4638591: Павербанки
- 80397: Телевізори

### Формат відповіді товару
```json
{
  "id": 123456,
  "title": "Назва товару",
  "price": 9999,
  "old_price": 12999,
  "href": "smartfon-apple-iphone-15-128gb-black-mqhp3",
  "sell_status": "available",
  "category_id": 80165,
  "images": ["https://..."],
  "producer": {"title": "Apple"}
}
```

## Партнерський API (потрібна реєстрація)
URL: https://partner.rozetka.com.ua
- Завантаження товарів через XML/YML прайс-лист
- Формат: Rozetka YML (схожий на Яндекс.Маркет)
- Оновлення цін: через FTP або API

### YML формат для завантаження
```xml
<offer id="123" available="true">
  <url>https://your-site.com/product/123</url>
  <price>999</price>
  <currencyId>UAH</currencyId>
  <categoryId>80165</categoryId>
  <name>Назва товару</name>
  <description>Опис</description>
</offer>
```

## Важливо для дропшипінгу
- Комісія Rozetka: 12-15% залежно від категорії
- Електроніка: 12%
- Одяг/взуття: 15%
- Час обробки замовлення: 24-48 годин
- Обов'язкова наявність фото на білому фоні

## Захист від парсингу
- CloudFlare захист на всіх сторінках
- Rate limiting: ~30 запитів/хвилину
- Потрібен User-Agent браузера
- CAPTCHA при підозрілій активності
