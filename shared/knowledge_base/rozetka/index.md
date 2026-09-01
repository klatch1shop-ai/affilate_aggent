# Розетка Маркетплейс — База знань

## Офіційна документація (sellerhelp.rozetka.com.ua)

### Товари
- Вимоги до інформації: https://sellerhelp.rozetka.com.ua/p204-product-requirements.html
- Ціна: https://sellerhelp.rozetka.com.ua/p214-price-and-stock.html
- Назва: https://sellerhelp.rozetka.com.ua/p217-product-title.html
- Бренд: https://sellerhelp.rozetka.com.ua/p213-product-producer.html
- Фото: https://sellerhelp.rozetka.com.ua/p216-product-images.html
- Опис: https://sellerhelp.rozetka.com.ua/p212-product-description.html
- Характеристики: https://sellerhelp.rozetka.com.ua/p210-product-characteristics.html
- Різновиди: https://sellerhelp.rozetka.com.ua/p205-product-variety.html
- Артикул: https://sellerhelp.rozetka.com.ua/p211-product-article.html
- Штрихкод: https://sellerhelp.rozetka.com.ua/p215-product-barcode.html
- Гарантія: https://sellerhelp.rozetka.com.ua/p640-warranty-information.html

### XML прайс-лист
- Загальне: https://sellerhelp.rozetka.com.ua/p177-xml-price-list.html
- Вимоги до XML: https://sellerhelp.rozetka.com.ua/p185-pricelist-requirements.html
- Характеристики в XML: https://sellerhelp.rozetka.com.ua/p210-product-characteristics.html
- Pricecreator: https://sellerhelp.rozetka.com.ua/p362-rozetka-pricecreator.html

### Seller API
- **[api_auth.md](api_auth.md) — авторизація: пароль ОБОВʼЯЗКОВО в Base64.**
  Без кодування сервер відповідає `incorrect_username_password` (код 1004),
  хоча логін і пароль правильні. Саме через це API вважалося непрацездатним.

### Реклама та продажі
- Реклама: https://sellerhelp.rozetka.com.ua/p324-advertising-and-promotion.html

### API
- Документація: https://api-seller.rozetka.com.ua/apidoc/

### Доступи
- Кабінет: https://seller.rozetka.com.ua/
- Pricecreator: https://pricecreator.rozetka.com.ua/
- Контакт: ivanovskaya@rozetka.ua (Софія Івановська)
- Магазин seller id: gomer

### API (детально)
- stock_api.txt — оновлення наявності в реальному часі
- api_full.txt — повна документація всіх endpoints

### Ключові endpoints
- Категорії: GET /market-categories/search
- Дерево категорій: GET /market-categories/get-categories-by-parent?expand=parents,children
- Пошук товару: GET /items/search?article={артикул}
- Оновлення наявності: PUT /items/update-price-stock/{id}
- Завантаження фіду: POST /item-price-updates/create
- Статус модерації: GET /items/{id} (поле moderation_status)
