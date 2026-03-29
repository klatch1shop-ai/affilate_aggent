# Скіл інтеграції з маркетплейсами

## Prom.ua інтеграція

### Завантаження товару
```python
async def upload_product_to_prom(product: dict) -> dict:
    url = "https://my.prom.ua/api/v1/products/import"
    headers = {"Authorization": f"Bearer {PROM_TOKEN}"}
    body = {"products": [{
        "name": product["title"],
        "price": product["sell_price"],
        "description": product["description"],
        "category": {"id": product["category_id"]},
        "presence": "available" if product["in_stock"] else "not_available"
    }]}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=body, headers=headers)
        return resp.json()
```

### Оновлення ціни
```python
async def update_prom_price(product_id: int, new_price: float):
    url = "https://my.prom.ua/api/v1/products/edit"
    body = {"id": product_id, "price": str(new_price)}
    # ... запит
```

## Rozetka інтеграція

### YML прайс-лист генерація
```python
def generate_yml(products: list) -> str:
    items = []
    for p in products:
        items.append(f"""
        <offer id="{p['id']}" available="{'true' if p['in_stock'] else 'false'}">
            <url>{p['url']}</url>
            <price>{p['sell_price']}</price>
            <currencyId>UAH</currencyId>
            <categoryId>{p['category_id']}</categoryId>
            <name>{p['title']}</name>
        </offer>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <yml_catalog>
        <shop><offers>{''.join(items)}</offers></shop>
    </yml_catalog>"""
```

## Загальний workflow дропшипінгу
1. Scraper знаходить товар у постачальника
2. Finance розраховує ціну продажу
3. Developer завантажує товар на маркетплейс
4. Scraper моніторить ціну конкурентів
5. Finance сигналізує якщо маржа падає нижче мінімуму
6. Orchestrator приймає рішення про зміну ціни
