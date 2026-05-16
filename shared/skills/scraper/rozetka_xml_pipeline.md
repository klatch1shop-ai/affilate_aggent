# Carvol XML для Розетки — пайплайн виправлень

## Розташування
- XML файл: data/carvol_rozetka.xml
- GitHub URL: https://raw.githubusercontent.com/klatch1shop-ai/affilate_aggent/main/data/carvol_rozetka.xml
- Контакт Розетки: ivanovskaya@rozetka.ua (Софія Івановська)

## Заборонено в описах (офіційна документація Розетки):
- Посилання на сторонні ресурси
- Ціни та інформація про інші товари
- Інформація про доставку та оплату
- Контактні дані та інформація про магазин
- Додаткові послуги
- Кольоровий текст
- Emoji
- Інформація про імпортера

## Виправлення що зроблені:
1. Видалено 1753 фрази "наш менеджер допоможе з підбором"
2. Vendor QIV → QIV Multimedia (6303 товари)
3. Vendor ABS → Incar (50 товарів)

## Перевірка XML перед відправкою:
```python
import re
with open('data/carvol_rozetka.xml') as f:
    content = f.read()

# Стоп-фрази
bad = re.findall(r'наш менеджер[^<]{0,100}', content, re.I)
print(f'Проблем: {len(bad)}')

# URL в описах (норма тільки в picture)
from xml.etree import ElementTree as ET
tree = ET.parse('data/carvol_rozetka.xml')
for offer in tree.getroot().find('shop').find('offers').findall('offer'):
    desc = offer.find('description_ua')
    if desc is not None and desc.text and 'http' in desc.text:
        print(f'URL в описі: {offer.get("id")}')
```

## Формат назви (вимога Розетки):
Тип товару → Виробник → Модель → Характеристики
Приклад: "Камера заднього огляду QIV QCV-1058D 800TVL"
