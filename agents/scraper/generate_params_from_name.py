import os, sys, json, re
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# Словник типів товарів з назви → параметри
TYPE_PARAMS = {
    'камера': {'Тип': 'Камера заднього огляду', 'Призначення': 'Відеоспостереження'},
    'кріплення': {'Тип': 'Кріплення'},
    'монітор': {'Тип': 'Монітор'},
    'реєстратор': {'Тип': 'Відеореєстратор'},
    'магнітола': {'Тип': 'Автомагнітола'},
    'адаптер': {'Тип': 'Адаптер'},
    'кабель': {'Тип': 'Кабель'},
    'антена': {'Тип': 'Антена'},
    'динамік': {'Тип': 'Динамік'},
    'сенсор': {'Тип': 'Сенсор'},
}

# Бренди автомобілів для параметра Сумісність
CAR_BRANDS = [
    'Audi', 'BMW', 'Mercedes', 'Toyota', 'Volkswagen', 'VW',
    'Ford', 'Hyundai', 'Kia', 'Nissan', 'Honda', 'Mazda',
    'Subaru', 'Mitsubishi', 'Volvo', 'Skoda', 'Renault',
    'Peugeot', 'Citroen', 'Opel', 'Chevrolet', 'Jeep',
    'Land Rover', 'Range Rover', 'Porsche', 'Lexus', 'Infiniti',
    'Acura', 'Cadillac', 'Lincoln', 'Buick', 'GMC',
    'Dodge', 'Chrysler', 'Jeep', 'RAM', 'Tesla',
    'Lada', 'ВАЗ', 'УАЗ', 'ГАЗ', 'МАЗ', 'КамАЗ',
    'truck', 'Truck', 'universal', 'Universal',
]

def extract_params_from_name(name: str, vendor: str, article: str) -> dict:
    """Витягує параметри з назви товару"""
    params = {}
    name_lower = name.lower()

    # 1. Бренд (vendor)
    if vendor:
        params['Бренд'] = vendor

    # 2. Тип товару з назви
    for keyword, type_params in TYPE_PARAMS.items():
        if keyword in name_lower:
            params.update(type_params)
            break

    # 3. Сумісність (марка авто)
    compat = []
    for brand in CAR_BRANDS:
        if brand.lower() in name_lower or brand in name:
            compat.append(brand)
    if compat:
        params['Сумісність'] = ', '.join(compat[:3])

    # 4. Артикул
    if article and article not in name:
        params['Артикул'] = article
    else:
        # Витягуємо артикул з дужок в назві
        match = re.search(r'\(([A-Z0-9\-\.\/]+)\)', name)
        if match:
            params['Артикул'] = match.group(1)

    # 5. Колір
    colors = {
        'чорн': 'Чорний', 'білий': 'Білий', 'срібн': 'Срібний',
        'сірий': 'Сірий', 'червон': 'Червоний', 'синій': 'Синій',
    }
    for color_key, color_val in colors.items():
        if color_key in name_lower:
            params['Колір'] = color_val
            break

    # 6. Розмір/діагональ
    size_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:дюйм|"|inch|\'\')', name_lower)
    if size_match:
        params['Діагональ'] = f'{size_match.group(1)}"'

    # 7. Роздільна здатність
    res_match = re.search(r'(\d{3,4}[xXх×]\d{3,4})', name)
    if res_match:
        params['Роздільна здатність'] = res_match.group(1)

    # 8. Країна виробник
    params['Країна-виробник'] = 'Китай'

    return params

def process_without_params(limit: int = None):
    """Обробляє товари без параметрів"""
    conn = get_connection()
    cur = conn.cursor()

    query = """SELECT id, article, name_ua, vendor 
               FROM carvol_products 
               WHERE has_params = false"""
    if limit:
        query += f" LIMIT {limit}"

    cur.execute(query)
    rows = cur.fetchall()
    logger.info(f"[PARAMS] Processing {len(rows)} products without params")

    updated = 0
    for row in rows:
        params = extract_params_from_name(
            row['name_ua'] or '',
            row['vendor'] or '',
            row['article'] or ''
        )

        has_params = len(params) >= 3

        cur.execute("""
            UPDATE carvol_products SET
                params = %s,
                has_params = %s,
                status = 'params_generated'
            WHERE id = %s
        """, (json.dumps(params, ensure_ascii=False), has_params, row['id']))
        updated += 1

    conn.commit()

    # Статистика після обробки
    cur.execute("SELECT has_params, COUNT(*) FROM carvol_products GROUP BY has_params")
    logger.info("[PARAMS] Result:")
    for r in cur.fetchall():
        logger.info(f"  has_params={r['has_params']}: {r['count']}")

    cur.close()
    conn.close()
    logger.success(f"[PARAMS] Done: {updated} updated")
    return updated

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.test:
        # Тест на кількох прикладах
        test_cases = [
            ("Кріплення під камеру заднього огляду для Audi QAU027B", "QIV", "QAU027B"),
            ("Камера заднього огляду QIV QCV-1058D для BMW X5", "QIV", "QCV-1058D"),
            ("Автомагнітола Teyes CC3 2K 9 дюймів для Toyota Camry", "Teyes", "CC3-2K-9"),
            ("Адаптер CAN шини для Volkswagen Golf VII Mekede", "Mekede", "CAN-VW-07"),
        ]
        for name, vendor, article in test_cases:
            params = extract_params_from_name(name, vendor, article)
            print(f"\nНазва: {name[:60]}")
            print(f"Параметри ({len(params)}): {json.dumps(params, ensure_ascii=False)}")
    else:
        count = process_without_params(args.limit)
        print(f"✅ Оновлено: {count} товарів")
