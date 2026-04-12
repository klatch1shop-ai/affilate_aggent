# Rozetka Seller API — повна документація

## API токен
- URL: https://api-seller.rozetka.com.ua/apidoc/
- Авторизація: POST логін+пароль → Bearer token (живе 24 години)
- Також: окремий API-токен в Налаштування → Безпека API

## Авторизація
```python
import requests, base64

def get_rozetka_token(login: str, password: str) -> str:
    url = "https://api-seller.rozetka.com.ua/sites"
    data = {"username": login, "password": password}
    resp = requests.post(url, json=data)
    return resp.json().get("content", {}).get("access_token", "")

headers = {"Authorization": f"Bearer {token}"}
```

## Що можна через API
- Замовлення: отримати, змінити статус, ТТН
- Товари: отримати інформацію
- Повідомлення з покупцями
- Відгуки
- Служби доставки
- Комплекти товарів

## Замовлення — основний workflow
1. GET замовлення в обробці: /orders?expand=status_available
2. GET деталі замовлення: /orders/{id}?expand=status_available
3. POST змінити статус + ТТН: /orders/{id}/status

## XML прайс — вимоги (повні)

### Обов'язкові теги offer:
- id — латиниця+цифри, НІКОЛИ не змінювати після публікації
- available — true/false
- price — число в UAH
- currencyId — UAH
- categoryId — id з блоку categories
- picture — мін.1 макс.15, тільки https, мін.400x400px
- vendor — бренд (= бренд в name_ua)
- stock_quantity — ціле число, 0=немає
- name_ua — назва українською
- description_ua — опис українською в CDATA
- param name — характеристики

### Назва (name_ua) — формат:
Тип товару Бренд Модель Характеристики (Артикул)
- Макс 255 символів, оптимально до 60
- БЕЗ ком, крапок, тире (крім назви моделі)
- БЕЗ реклами: "акція", "знижка", "топ", "новинка"
- Починається з великої літери
- Унікальна назва в прайсі

### Опис (description_ua):
- Тільки про конкретний товар
- БЕЗ фото, відео, посилань, цін
- БЕЗ інформації про магазин/доставку
- Максимум 50000 символів
- HTML в CDATA

### Фото:
- Мін 400x400px, оптимально 1000x1000px
- Тільки https, без кирилиці в URL
- Перше фото — фронтальний вид
- БЕЗ рук, сторонніх предметів на першому фото
- БЕЗ написів російською
- Не дублювати фото

### Категорії:
- rz_id = ID категорії на сайті Розетки
- Один тип товару = одна категорія
- ID ніколи не змінювати після публікації

### Параметри (param):
- Назва і значення — ТІЛЬКИ УКРАЇНСЬКОЮ
- Відповідають фільтрам категорії на сайті Розетки
- Порожній param — заборонено

### Заборонені категорії без узгодження:
- Зарядні станції

## Валідатор XML:
https://seller.rozetka.com.ua/gomer/pricevalidate/check/index

## Корисні посилання:
- Вимоги до товарів: https://sellerhelp.rozetka.com.ua/st/ua/items
- Назви: https://sellerhelp.rozetka.com.ua/p217-product-title.html
- Фото: https://sellerhelp.rozetka.com.ua/p216-product-images.html
- Параметри: https://sellerhelp.rozetka.com.ua/p210-product-characteristics.html
- Опис: https://sellerhelp.rozetka.com.ua/p212-product-description.html
- Категорії: https://sellerhelp.rozetka.com.ua/p179-correct-categories.html
