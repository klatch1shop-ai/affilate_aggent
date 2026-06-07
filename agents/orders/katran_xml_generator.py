import os, sys, re, math, requests, zipfile, io
from datetime import datetime
from xml.etree import ElementTree as ET
from dotenv import load_dotenv
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

SHOP_NAME = "HYPER_STORE"
SHOP_URL = "https://prom.ua/ua/c3882792-hyper-store.html"
DEFAULT_COMMISSION = 7.0
DEFAULT_RZ_ID = "25636737"  # Ручний інструмент
DEFAULT_CAT_NAME = "Інструменти"

OUTPUT_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../data/katran_rozetka.xml")
)


def get_katran_feed() -> ET.Element:
    url = os.getenv("KATRAN_FEED_URL_STOCK")
    if not url:
        raise ValueError("KATRAN_FEED_URL_STOCK не встановлено в .env")

    logger.info(f"[Katran] Завантажую фід: {url}")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not xml_names:
            raise ValueError("XML не знайдено в ZIP архіві")
        xml_name = xml_names[0]
        logger.info(f"[Katran] Файл в архіві: {xml_name}")
        with zf.open(xml_name) as f:
            return ET.parse(f).getroot()


def get_category_map() -> dict:
    """Повертає {katran_category_id: {rz_id, name, commission}}. При помилці — {}."""
    try:
        from shared.utils.db import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, rozetka_category, rozetka_rz_id, commission_pct
            FROM katran_categories
            WHERE rozetka_rz_id IS NOT NULL
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = {}
        for r in rows:
            result[str(r["id"])] = {
                "rz_id": str(r["rozetka_rz_id"]),
                "name": r["rozetka_category"] or DEFAULT_CAT_NAME,
                "commission": float(r["commission_pct"]),
            }
        logger.info(f"[Katran] Категорій з БД: {len(result)}")
        return result
    except Exception as e:
        logger.warning(f"[Katran] БД недоступна, використовую defaults: {e}")
        return {}


def calc_price(price_rrc: float, commission_pct: float) -> int:
    """ceil(price_rrc * (1 + commission_pct/100) / 10) * 10"""
    if price_rrc <= 0:
        return 0
    raw = price_rrc * (1 + commission_pct / 100)
    return int(math.ceil(raw / 10) * 10)


def is_in_stock(stock_str: str) -> bool:
    if not stock_str:
        return False
    s = stock_str.lower().strip()
    # "есть" / "є" — в наявності; "в резервах" — не включаємо
    return s.startswith("е") or s.startswith("є")


def parse_float(text: str) -> float:
    try:
        return float((text or "0").replace(",", ".").strip())
    except ValueError:
        return 0.0


def clean_text(text: str) -> str:
    return (text or "").strip()


def fix_name(name: str, artikul: str) -> str:
    if not name:
        return artikul
    name = re.sub(r"\s+", " ", name).strip()
    return name[:255]


def xml_escape(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def generate_xml(output_file: str = None) -> tuple:
    if not output_file:
        output_file = OUTPUT_FILE

    root = get_katran_feed()
    cat_map = get_category_map()

    # Структура фіду: <price><products><product>
    products_el = root.find("products")
    if products_el is None:
        products_el = root
    all_products = products_el.findall("product")
    logger.info(f"[Katran] Товарів у фіді: {len(all_products)}")

    categories_used = {}
    offers_data = []
    skipped_stock = 0
    skipped_price = 0
    skipped_name = 0

    for p in all_products:
        code = clean_text(p.findtext("code") or "")
        artikul = clean_text(p.findtext("artikul") or code)
        name = fix_name(p.findtext("name") or "", artikul)
        description = clean_text(p.findtext("description") or "")
        category_id = clean_text(p.findtext("categoryId") or "")
        vendor = clean_text(p.findtext("vendor") or "Katran")
        warranty = clean_text(p.findtext("warranty") or "")
        stock_str = clean_text(p.findtext("stock") or "")
        stock_qty = max(int(parse_float(p.findtext("stock_quantity") or "0")), 0)
        price_rrc = parse_float(p.findtext("price_rrc") or "0")

        if not name or len(name) < 3:
            skipped_name += 1
            continue

        if not is_in_stock(stock_str):
            skipped_stock += 1
            continue

        cat_info = cat_map.get(category_id, {})
        rz_id = cat_info.get("rz_id", DEFAULT_RZ_ID)
        cat_name = cat_info.get("name", DEFAULT_CAT_NAME)
        commission = cat_info.get("commission", DEFAULT_COMMISSION)

        price = calc_price(price_rrc, commission)
        if price <= 0:
            skipped_price += 1
            continue

        # Фото
        pictures = []
        images_el = p.find("images")
        if images_el is not None:
            for img in images_el.findall("image"):
                url = (img.text or img.get("url") or "").strip()
                if url.startswith("http") and len(url) < 500:
                    pictures.append(url)

        if rz_id not in categories_used:
            categories_used[rz_id] = cat_name

        offers_data.append({
            "artikul": artikul,
            "name": name,
            "description": description,
            "rz_id": rz_id,
            "vendor": vendor,
            "warranty": warranty,
            "stock_qty": max(stock_qty, 1),
            "price": price,
            "pictures": pictures,
        })

    logger.info(f"[Katran] Готово до XML: {len(offers_data)} товарів")
    logger.info(
        f"[Katran] Пропущено — без наявності: {skipped_stock}, "
        f"без ціни: {skipped_price}, без назви: {skipped_name}"
    )

    # Збираємо XML
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{datetime.now().strftime("%Y-%m-%d %H:%M")}">',
        "  <shop>",
        f"    <name>{SHOP_NAME}</name>",
        "    <company>FOP Oliinyk Serhii</company>",
        f"    <url>{SHOP_URL}</url>",
        "    <currencies>",
        '      <currency id="UAH" rate="1"/>',
        "    </currencies>",
        "    <categories>",
    ]

    for rz_id, cat_name in categories_used.items():
        lines.append(f'      <category id="{rz_id}">{cat_name}</category>')

    lines.extend(["    </categories>", "    <offers>"])

    for o in offers_data:
        offer_id = xml_escape(o["artikul"])
        desc_escaped = xml_escape(o["description"])

        offer = [f'      <offer id="{offer_id}" available="true">']
        offer.append(f'        <price>{o["price"]}</price>')
        offer.append("        <currencyId>UAH</currencyId>")
        offer.append(f'        <categoryId>{o["rz_id"]}</categoryId>')

        for pic_url in o["pictures"][:10]:
            offer.append(f"        <picture>{pic_url}</picture>")
        if not o["pictures"]:
            offer.append(f"        <!-- no pictures for {offer_id} -->")

        offer.append(f'        <vendor>{xml_escape(o["vendor"])}</vendor>')
        offer.append(f'        <article>{xml_escape(o["artikul"])}</article>')
        offer.append(f'        <stock_quantity>{o["stock_qty"]}</stock_quantity>')
        offer.append(f'        <name_ua>{xml_escape(o["name"])}</name_ua>')
        offer.append(
            f'        <description_ua><![CDATA[<p>{desc_escaped}</p>]]></description_ua>'
        )

        offer.append(f'        <param name="Бренд">{xml_escape(o["vendor"])}</param>')
        if o["warranty"]:
            offer.append(f'        <param name="Гарантія">{xml_escape(o["warranty"])} міс</param>')
        offer.append(f'        <param name="Артикул">{xml_escape(o["artikul"])}</param>')

        offer.append("      </offer>")
        lines.extend(offer)

    lines.extend(["    </offers>", "  </shop>", "</yml_catalog>"])

    xml_content = "\n".join(lines)
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(xml_content)

    logger.success(f"[Katran] XML збережено: {output_file}")
    stats = {
        "total": len(all_products),
        "in_stock": len(offers_data),
        "skipped_stock": skipped_stock,
        "skipped_price": skipped_price,
        "skipped_name": skipped_name,
        "categories": len(categories_used),
    }
    return output_file, len(offers_data), stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Генератор XML Розетки з фіду Катрана")
    parser.add_argument("--output", type=str, default=None, help="Вихідний XML файл")
    args = parser.parse_args()

    try:
        file, count, stats = generate_xml(output_file=args.output)
        print(f"\n✅ XML Катран готовий!")
        print(f"   Файл    : {file}")
        print(f"   Офферів : {count}")
        print(f"   ─────────────────────────────")
        print(f"   Всього в фіді     : {stats['total']}")
        print(f"   В наявності       : {stats['in_stock']}")
        print(f"   Немає в наявності : {stats['skipped_stock']}")
        print(f"   Без ціни          : {stats['skipped_price']}")
        print(f"   Без назви         : {stats['skipped_name']}")
        print(f"   Категорій         : {stats['categories']}")
    except Exception as e:
        logger.error(f"[Katran] Критична помилка: {e}")
        sys.exit(1)
