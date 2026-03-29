# Скіл роботи з картками товарів

## Структура картки товару
```python
product = {
    # Ідентифікація
    "external_id": "123456",
    "marketplace": "rozetka",  # rozetka/prom/epicentr
    
    # Основна інформація
    "title": "Назва товару",
    "description": "Повний опис",
    "brand": "Бренд",
    "model": "Модель",
    
    # Ціни
    "buy_price": 1000.0,      # ціна закупки
    "sell_price": 1350.0,     # ціна продажу
    "old_price": 1500.0,      # стара ціна (якщо є)
    "currency": "UAH",
    
    # Маржа (розраховується автоматично)
    "margin_prom": 282.5,     # прибуток на Prom
    "margin_rozetka": 188.0,  # прибуток на Rozetka
    
    # Наявність
    "in_stock": True,
    "quantity": None,         # якщо відомо
    
    # Медіа
    "images": ["https://..."],
    "main_image": "https://...",
    
    # Категоризація
    "category": "Електроніка",
    "category_id": "80165",
    "tags": ["навушники", "bluetooth"],
    
    # Характеристики
    "attributes": {
        "Колір": "Чорний",
        "Підключення": "Bluetooth 5.0",
        "Час роботи": "30 годин"
    },
    
    # Метадані
    "url": "https://...",
    "seller": "Назва продавця",
    "rating": 4.8,
    "reviews_count": 125,
    "scraped_at": "2025-01-01T00:00:00"
}
```

## Валідація картки товару
```python
def validate_product(p: dict) -> tuple[bool, list]:
    errors = []
    if not p.get("title"): errors.append("Відсутня назва")
    if not p.get("buy_price"): errors.append("Відсутня ціна закупки")
    if not p.get("marketplace"): errors.append("Відсутній маркетплейс")
    if not p.get("images"): errors.append("Відсутні фото")
    if p.get("buy_price", 0) <= 0: errors.append("Невірна ціна")
    return len(errors) == 0, errors
```

## Збагачення картки (enrichment)
```python
async def enrich_product(p: dict) -> dict:
    from shared.utils.skill_loader import load_skill
    
    # 1. Розрахунок маржі
    buy = p.get("buy_price", 0)
    sell = round(buy * 1.35, 2)
    p["sell_price"] = sell
    p["margin_prom"] = round(sell - buy - sell * 0.05, 2)
    p["margin_rozetka"] = round(sell - buy - sell * 0.12, 2)
    
    # 2. Генерація опису якщо відсутній
    if not p.get("description"):
        # LLM генерує опис на основі назви і характеристик
        pass
    
    # 3. Категоризація якщо відсутня
    if not p.get("category"):
        p["category"] = "Інше"
    
    return p
```

## Порівняння товарів між маркетплейсами
```python
def compare_prices(products: list) -> dict:
    by_title = {}
    for p in products:
        key = p["title"].lower()[:50]
        if key not in by_title:
            by_title[key] = []
        by_title[key].append(p)
    
    comparisons = []
    for title, items in by_title.items():
        if len(items) > 1:
            prices = {i["marketplace"]: i["buy_price"] for i in items}
            comparisons.append({
                "title": title,
                "prices": prices,
                "best_price": min(prices.values()),
                "best_marketplace": min(prices, key=prices.get)
            })
    return comparisons
```

## Формат для завантаження на Prom
```python
def to_prom_format(p: dict) -> dict:
    return {
        "name": p["title"],
        "price": str(p["sell_price"]),
        "description": p.get("description",""),
        "presence": "available" if p.get("in_stock") else "not_available",
        "images": [{"url": img} for img in p.get("images",[])[:20]],
        "attributes": [
            {"name": k, "value": v}
            for k, v in p.get("attributes",{}).items()
        ]
    }
```

## Формат для Rozetka YML
```python
def to_rozetka_yml(p: dict) -> str:
    imgs = "".join(f"<picture>{u}</picture>" for u in p.get("images",[])[:10])
    attrs = "".join(
        f"<param name='{k}'>{v}</param>"
        for k,v in p.get("attributes",{}).items()
    )
    return f"""<offer id="{p['external_id']}" available="{'true' if p.get('in_stock') else 'false'}">
    <url>{p.get('url','')}</url>
    <price>{p['sell_price']}</price>
    <currencyId>UAH</currencyId>
    <categoryId>{p.get('category_id','')}</categoryId>
    <name>{p['title']}</name>
    <description>{p.get('description','')}</description>
    {imgs}{attrs}
</offer>"""
```
