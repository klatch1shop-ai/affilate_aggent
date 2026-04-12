import os, sys, json, re, time
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

from shared.utils.db import get_connection
from shared.utils.ollama_worker import request_llm

SHOP_NAME = "HYPER_STORE"
SHOP_URL = "https://prom.ua/ua/c3882792-hyper-store.html"
STOCK_DEFAULT = 10

# Маппінг категорій постачальника → rz_id Розетки
CATEGORY_MAP = {
    "Ручний інструмент та набори": ("1", "Ручний інструмент", "25636737"),
    "Набори інструментів": ("2", "Набори інструментів", "298224"),
    "Ключі": ("3", "Ключі та знімачі", "2798782"),
    "Викрутки": ("4", "Викрутки", "73501273"),
    "Головки торцеві": ("5", "Головки торцеві", "71859137"),
    "Пневмоінструмент": ("6", "Пневмоінструмент", "71512022"),
    "Затискний інструмент": ("7", "Затискний інструмент", "73354825"),
    "Вимірювальний інструмент": ("8", "Вимірювальний інструмент", "73557186"),
    "Підйомне обладнання": ("9", "Підйомне обладнання", "73501745"),
    "Шиномонтажне обладнання": ("10", "Шиномонтажне обладнання", "73082368"),
    "": ("11", "Ручний інструмент та набори", "25636737"),
}

def clean_html(text: str) -> str:
    """Видаляє HTML теги, фото, рекламу"""
    if not text:
        return ""
    # Видалити img теги
    text = re.sub(r'<img[^>]+>', '', text)
    # Видалити теги з data-end/data-start атрибутами
    text = re.sub(r'<[^>]+data-(?:end|start)[^>]+>', '', text)
    # Залишити тільки дозволені HTML теги
    allowed = re.sub(r'<(?!/?(?:p|ul|li|strong|b|br|h2|h3)\b)[^>]+>', '', text)
    return allowed.strip()

def generate_description(sku: str, name: str, description_raw: str, model=None) -> str:
    """Генерує чистий опис українською через LLM"""
    if not model:
        model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

    # Спочатку очищаємо від сміття
    clean = clean_html(description_raw or "")
    # Прибираємо російський текст — беремо тільки речення без кирилічних слів на рос.
    clean = clean[:3000]  # обмежуємо контекст

    prompt = f"""Ти — копірайтер для інтернет-магазину інструментів. 
Твоє завдання — написати короткий технічний опис товару українською мовою.

Товар: {name}
Артикул: {sku}
Вихідні дані (можуть бути на різних мовах, з HTML):
{clean}

Правила:
1. Пиши ТІЛЬКИ українською мовою
2. Максимум 500 символів
3. Тільки технічні факти про конкретний товар
4. Без реклами: заборонені слова "акція", "знижка", "топ", "найкращий", "незамінний"
5. Без згадок магазину, доставки, гарантії
6. Без фото, посилань, цін
7. Структура: 1-2 речення про призначення + ключові характеристики

Напиши тільки текст опису, без заголовків і зайвих слів."""

    try:
        result = request_llm(model, prompt, timeout=60)
        # Очищуємо від можливих HTML тегів у відповіді LLM
        result = re.sub(r'<[^>]+>', '', result).strip()
        return result[:2000]
    except Exception as e:
        logger.error(f"[XML] LLM error for {sku}: {e}")
        return f"Професійний інструмент TOPTUL {sku}. Виробник: TOPTUL (Тайвань)."

def fix_name(name_uk: str, sku: str) -> str:
    """Виправляє назву за вимогами Розетки"""
    if not name_uk:
        return f"Інструмент TOPTUL {sku}"

    # Видалити заборонені символи
    name = re.sub(r'[,.]', '', name_uk)
    # Прибрати зайві пробіли
    name = re.sub(r'\s+', ' ', name).strip()
    # Перша літера велика
    name = name[0].upper() + name[1:] if name else name
    # Максимум 255 символів
    return name[:255]

def get_category_info(category_epicentr: str) -> tuple:
    """Повертає (cat_id, cat_name, rz_id) для категорії"""
    for key, val in CATEGORY_MAP.items():
        if key and key.lower() in (category_epicentr or "").lower():
            return val
    return CATEGORY_MAP[""]  # default

def generate_xml(limit: int = 100, use_llm: bool = True, output_file: str = None):
    """Генерує XML файл для Розетки"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT sku, name_uk, description_raw, description_epicentr,
               category_epicentr, attributes, specs_json, status,
               price_supplier, pictures, params, vendor, availability
        FROM my_products
        WHERE status IN ('new', 'processed', 'ready')
        AND sku IS NOT NULL
        AND name_uk IS NOT NULL
        LIMIT %s
    """, (limit,))

    products = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    logger.info(f"[XML] Generating XML for {len(products)} products")

    # Збираємо унікальні категорії
    categories_used = {}
    for p in products:
        cat = p.get("category_epicentr") or ""
        cat_id, cat_name, rz_id = get_category_info(cat)
        categories_used[cat_id] = (cat_name, rz_id)

    # Генеруємо XML
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{datetime.now().strftime("%Y-%m-%d %H:%M")}">',
        '  <shop>',
        f'    <name>{SHOP_NAME}</name>',
        f'    <company>FOP Oliinyk Serhii</company>',
        f'    <url>{SHOP_URL}</url>',
        '    <currencies>',
        '      <currency id="UAH" rate="1"/>',
        '    </currencies>',
        '    <categories>',
    ]

    for cat_id, (cat_name, rz_id) in categories_used.items():
        lines.append(f'      <category id="{cat_id}" rz_id="{rz_id}">{cat_name}</category>')

    lines.append('    </categories>')
    lines.append('    <offers>')

    processed = 0
    skipped = 0

    for p in products:
        sku = p["sku"]
        name_uk = fix_name(p.get("name_uk", ""), sku)

        if not name_uk or len(name_uk) < 5:
            skipped += 1
            continue

        cat = p.get("category_epicentr") or ""
        cat_id, cat_name, rz_id = get_category_info(cat)

        # Генеруємо опис
        if use_llm and p.get("description_raw"):
            description = generate_description(sku, name_uk, p["description_raw"])
        elif p.get("description_epicentr"):
            description = re.sub(r'<[^>]+>', '', p["description_epicentr"])[:500]
        else:
            description = f"Професійний інструмент TOPTUL {sku}. Бренд TOPTUL — провідний виробник інструментів (Тайвань). Артикул: {sku}."

        # Параметри з поля params (імпортовано з Prom)
        params = []
        import json as _json2
        params_data = p.get("params") or {}
        if isinstance(params_data, str):
            params_data = _json2.loads(params_data)
        for key, val in params_data.items():
            if key == "_values":
                continue
            if val and str(val).strip():
                clean_key = str(key).strip()[:100]
                clean_val = str(val).strip()[:500]
                clean_val = clean_val.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                params.append(f'        <param name="{clean_key}">{clean_val}</param>')
        # Базові параметри якщо немає
        if not params:
            vendor = p.get("vendor") or "TOPTUL"
            params.append(f'        <param name="Бренд">{vendor}</param>')
            params.append('        <param name="Країна виробник">Тайвань</param>')

        # Фото з поля pictures (імпортовано з Prom)
        pictures = []
        pics_data = p.get("pictures") or []
        if isinstance(pics_data, str):
            import json as _json
            pics_data = _json.loads(pics_data)
        for url in pics_data[:10]:
            if url and url.startswith("http") and len(url) < 500:
                pictures.append(f'        <picture>{url}</picture>')
        if not pictures:
            pictures.append(f'        <!-- no pictures for {sku} -->')

        # Очищаємо description від спецсимволів XML
        desc_clean = description.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        offer = [
            f'      <offer id="{sku}" available="true">',
            f'        <price>{int(p.get("price_supplier") or 0)}</price>',
            f'        <currencyId>UAH</currencyId>',
            f'        <categoryId>{cat_id}</categoryId>',
        ]
        offer.extend(pictures)
        offer.extend([
            f'        <vendor>TOPTUL</vendor>',
            f'        <article>{sku}</article>',
            f'        <stock_quantity>{STOCK_DEFAULT}</stock_quantity>',
            f'        <name_ua>{name_uk}</name_ua>',
            f'        <description_ua><![CDATA[<p>{desc_clean}</p>]]></description_ua>',
        ])
        offer.extend(params)
        offer.append('      </offer>')
        lines.extend(offer)

        processed += 1
        if processed % 10 == 0:
            logger.info(f"[XML] Processed {processed}/{len(products)}")

    lines.extend([
        '    </offers>',
        '  </shop>',
        '</yml_catalog>',
    ])

    xml_content = '\n'.join(lines)

    if not output_file:
        output_file = f"data/rozetka_feed_{datetime.now().strftime('%Y%m%d_%H%M')}.xml"

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(xml_content)

    logger.success(f"[XML] Done: {processed} offers, {skipped} skipped → {output_file}")
    return output_file, processed

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50, help="Кількість товарів")
    parser.add_argument("--no-llm", action="store_true", help="Без LLM генерації описів")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    file, count = generate_xml(
        limit=args.limit,
        use_llm=not args.no_llm,
        output_file=args.output
    )
    print(f"\n✅ XML готовий: {file}")
    print(f"   Товарів: {count}")
