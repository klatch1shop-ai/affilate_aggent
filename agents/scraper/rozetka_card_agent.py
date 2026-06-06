import os, sys, json, re
from loguru import logger
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
load_dotenv('/home/tek/agent-system/.env')

from shared.utils.db import get_connection
from shared.utils.ollama_worker import request_llm

# Словник перекладу параметрів рос→укр
PARAM_TRANSLATE = {
    "Тип": "Тип", "Вид": "Вид", "Категория": "Категорія",
    "Материал ручки": "Матеріал ручки", "Количество в наборе": "Кількість у наборі",
    "Реверсивная": "Реверсивна", "Отвертка": "Викрутка",
    "Универсальная": "Універсальна", "Многокомпонентный": "Багатокомпонентний",
    "Со сменными насадками": "Зі змінними насадками",
    "Односторонняя": "Одностороння", "Крестообразный": "Хрестоподібний",
    "Внешний": "Зовнішній", "Внутренний": "Внутрішній",
    "Длина": "Довжина", "Ширина": "Ширина", "Высота": "Висота",
    "Вес": "Вага", "Размер": "Розмір", "Цвет": "Колір",
    "Материал": "Матеріал", "Страна производитель": "Країна-виробник",
    "Тип привода": "Тип приводу", "Тип шлица": "Тип шліцу",
    "Исполнение биты": "Виконання біти", "Тип биты": "Тип біти",
}

def translate_params(params: dict) -> dict:
    """Перекладає параметри з російської на українську"""
    result = {}
    for key, val in params.items():
        if key == "_values":
            continue
        uk_key = PARAM_TRANSLATE.get(key, key)
        uk_val = PARAM_TRANSLATE.get(str(val), str(val))
        result[uk_key] = uk_val
    return result

def fix_name_ua(name: str, sku: str, vendor: str = "TOPTUL") -> str:
    """Виправляє назву за вимогами Розетки"""
    if not name:
        return f"Інструмент {vendor} {sku}"
    # Видалити заборонені символи
    name = re.sub(r'[,.](?!\d)', '', name)
    # Прибрати зайві пробіли
    name = re.sub(r'\s+', ' ', name).strip()
    # Перша літера велика
    name = name[0].upper() + name[1:] if name else name
    # Макс 255 символів
    return name[:255]

def generate_description_ua(sku: str, name: str, params: dict, raw_desc: str = "") -> str:
    """Генерує опис українською через Ollama"""
    model = "aya-expanse:8b"

    # Параметри для контексту
    params_text = "\n".join([f"- {k}: {v}" for k, v in params.items() if k != "_values"])

    # Очищаємо сирий опис від HTML і реклами
    clean_desc = re.sub(r'<[^>]+>', ' ', raw_desc or "")
    clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()[:1000]

    prompt = f"""Ти — копірайтер. Пиши ТІЛЬКИ українською мовою без жодних іноземних слів.

ПРИКЛАД ПРАВИЛЬНОГО ОПИСУ:
Ключ комбінований TOPTUL AAEB1010 — професійний інструмент для затягування та відкручування кріплення. Виготовлений зі сталі з хром-ванадієвим покриттям, забезпечує надійне зчеплення з гайками розміром 10 мм.

ПРИКЛАД НЕПРАВИЛЬНОГО (заборонено): "высококачественный инструмент", "professional tool", "незамінний помічник"

Напиши опис для цього товару:
Назва: {name}
Артикул: {sku}
Характеристики: {params_text}

ВИМОГИ:
- Максимум 250 символів
- ТІЛЬКИ українські слова (жодних російських, польських, англійських слів)
- Тільки факти про товар
- БЕЗ реклами, магазину, доставки, ціни
- 1-2 речення

Опис:"""

    try:
        result = request_llm(model, prompt, timeout=90)
        result = re.sub(r'<[^>]+>', '', result).strip()
        # Видалити лапки якщо LLM обгорнув відповідь
        result = result.strip('"\'')
        return result[:2000] if result else f"Професійний інструмент {vendor} {sku} (Тайвань)."
    except Exception as e:
        logger.error(f"[CARD AGENT] LLM error for {sku}: {e}")
        return f"Інструмент {name}. Виробник: TOPTUL (Тайвань). Артикул: {sku}."

def process_card(sku: str) -> dict:
    """Обробляє одну картку товару і повертає готовий offer"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT sku, name_uk, price_supplier, pictures, params,
               vendor, availability, description_raw, category_epicentr
        FROM my_products WHERE sku = %s
    """, (sku,))
    row = cur.fetchone()
    cur.close(); conn.close()

    if not row:
        logger.error(f"[CARD AGENT] SKU not found: {sku}")
        return None

    p = dict(row)
    vendor = p.get("vendor") or "TOPTUL"
    
    # Параметри
    raw_params = p.get("params") or {}
    if isinstance(raw_params, str):
        raw_params = json.loads(raw_params)
    
    # Перекладаємо параметри
    params_ua = translate_params(raw_params)
    
    # Базові параметри якщо порожньо
    if not params_ua:
        params_ua = {"Бренд": vendor, "Країна-виробник": "Тайвань"}

    # Виправляємо назву
    name_ua = fix_name_ua(p.get("name_uk", ""), sku, vendor)

    # Генеруємо опис через Ollama
    logger.info(f"[CARD AGENT] Generating description for {sku}...")
    desc_ua = generate_description_ua(
        sku, name_ua, params_ua, p.get("description_raw", "")
    )
    
    # Фото
    pictures = p.get("pictures") or []
    if isinstance(pictures, str):
        pictures = json.loads(pictures)
    pictures = [url for url in pictures if url and url.startswith("http")][:10]

    # Ціна
    price = float(p.get("price_supplier") or 0)
    available = p.get("availability", "true") == "true"
    stock = 10 if available and price > 0 else 0

    result = {
        "sku": sku,
        "name_ua": name_ua,
        "description_ua": desc_ua,
        "params": params_ua,
        "pictures": pictures,
        "price": price,
        "vendor": vendor,
        "stock": stock,
        "available": available and price > 0,
    }
    
    logger.success(f"[CARD AGENT] Done: {sku} | name: {name_ua[:50]} | desc: {desc_ua[:60]}")
    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sku", type=str, required=True)
    args = parser.parse_args()
    
    result = process_card(args.sku)
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
