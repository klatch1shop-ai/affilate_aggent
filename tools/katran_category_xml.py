#!/usr/bin/env python3
"""
tools/katran_category_xml.py — XML для конкретних категорій з фіду Катрана.

Usage:
  python3 tools/katran_category_xml.py 80158,237815
  python3 tools/katran_category_xml.py 80158,237815 --output /tmp/my.xml

Фіксить:
  - URL в description (видаляє)
  - Дублі URL фото (унікальні)
  - Дублі назв (додає артикул)
  - vendor порожній / "no name" → "Без бренду"
"""

import math
import os
import re
import subprocess
import sys
import zipfile
import io
from collections import Counter
from datetime import datetime
from xml.etree import ElementTree as ET

import requests
from dotenv import load_dotenv
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

SHOP_NAME        = "HYPER_STORE"
SHOP_URL         = "https://seller.rozetka.com.ua/"
DEFAULT_COMMISSION = 7.0
DEFAULT_RZ_ID    = "25636737"
DEFAULT_CAT_NAME = "Інструменти"
URL_RE           = re.compile(r"https?://\S+")
VENDOR_BAD       = {"no name", "noname", "no-name", "unknown", ""}


# ─── helpers (mirrors katran_xml_generator) ───────────────────────────────────

def get_katran_feed() -> ET.Element:
    url = os.getenv("KATRAN_FEED_URL_STOCK")
    if not url:
        raise ValueError("KATRAN_FEED_URL_STOCK не встановлено в .env")
    logger.info(f"[KatranCat] Завантажую фід...")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not xml_names:
            raise ValueError("XML не знайдено в ZIP архіві")
        with zf.open(xml_names[0]) as f:
            return ET.parse(f).getroot()


def get_category_map() -> dict:
    try:
        from shared.utils.db import get_connection
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT id, rozetka_category, rozetka_rz_id, commission_pct
            FROM katran_categories WHERE rozetka_rz_id IS NOT NULL
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = {}
        for r in rows:
            result[str(r["id"])] = {
                "rz_id":      str(r["rozetka_rz_id"]),
                "name":       r["rozetka_category"] or DEFAULT_CAT_NAME,
                "commission": float(r["commission_pct"]),
            }
        logger.info(f"[KatranCat] Категорій з БД: {len(result)}")
        return result
    except Exception as e:
        logger.warning(f"[KatranCat] БД недоступна: {e}")
        return {}


def parse_float(text: str) -> float:
    try:
        return float((text or "0").replace(",", ".").strip())
    except ValueError:
        return 0.0


def clean_text(text: str) -> str:
    return (text or "").strip()


def calc_price(price_rrc: float, commission_pct: float) -> int:
    if price_rrc <= 0:
        return 0
    return int(math.ceil(price_rrc * (1 + commission_pct / 100) / 10) * 10)


def is_in_stock(stock_str: str) -> bool:
    s = (stock_str or "").lower().strip()
    return s.startswith("е") or s.startswith("є")


def fix_name(name: str, artikul: str) -> str:
    if not name:
        return artikul
    name = re.sub(r'^[!@#$%^&*()\[\]{}\-_=+|\\/<>\'"`~]+\s*', '', name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:255] if name else artikul


def strip_urls(text: str) -> str:
    cleaned = URL_RE.sub("", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def xml_escape(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def fix_vendor(raw: str) -> str:
    v = raw.strip()
    return "Без бренду" if v.lower() in VENDOR_BAD else v


# ─── core ─────────────────────────────────────────────────────────────────────

def generate_category_xml(rz_ids: list, output_file: str) -> dict:
    target_rz_ids = set(rz_ids)
    logger.info(f"[KatranCat] Цільові rz_id: {target_rz_ids}")

    root     = get_katran_feed()
    cat_map  = get_category_map()

    products_el  = root.find("products")
    if products_el is None:
        products_el = root
    all_products = products_el.findall("product")
    logger.info(f"[KatranCat] Товарів у фіді: {len(all_products)}")

    # ── pass 1: filter qualifying products ────────────────────────────────
    qualified = []
    seen_artikuls: set = set()

    for p in all_products:
        code        = clean_text(p.findtext("code") or "")
        artikul     = clean_text(p.findtext("artikul") or code)
        stock_str   = clean_text(p.findtext("stock") or "")
        category_id = clean_text(p.findtext("categoryId") or "")
        cat_info    = cat_map.get(category_id, {})
        rz_id       = cat_info.get("rz_id", DEFAULT_RZ_ID)

        if rz_id not in target_rz_ids:
            continue
        if not is_in_stock(stock_str):
            continue
        if artikul in seen_artikuls:
            continue

        seen_artikuls.add(artikul)
        qualified.append((p, cat_info, rz_id, artikul))

    logger.info(f"[KatranCat] Відповідають фільтру: {len(qualified)}")

    # ── pass 2: count names to detect duplicates ──────────────────────────
    name_counter: Counter = Counter()
    for p, _, _, artikul in qualified:
        name_counter[fix_name(p.findtext("name") or "", artikul)] += 1

    # ── pass 3: build offers ──────────────────────────────────────────────
    categories_used: dict = {}
    offers_data: list = []
    brands: set = set()
    skipped_price = 0
    skipped_sale  = 0

    for p, cat_info, rz_id, artikul in qualified:
        raw_name    = fix_name(p.findtext("name") or "", artikul)
        name        = f"{raw_name} ({artikul})" if name_counter[raw_name] > 1 else raw_name
        description = strip_urls(clean_text(p.findtext("description") or ""))
        vendor      = fix_vendor(clean_text(p.findtext("vendor") or ""))
        warranty    = clean_text(p.findtext("warranty") or "")
        stock_qty   = max(int(parse_float(p.findtext("stock_quantity") or "0")), 1)
        price_rrc   = parse_float(p.findtext("price_rrc") or "0")
        commission  = cat_info.get("commission", DEFAULT_COMMISSION)
        cat_name    = cat_info.get("name", DEFAULT_CAT_NAME)

        # фільтр уцінок (після парсингу vendor)
        if vendor and ("уцін" in vendor.lower() or vendor.startswith("!")):
            skipped_sale += 1
            continue
        if "_У" in artikul and artikul.endswith("_У"):
            skipped_sale += 1
            continue

        price = calc_price(price_rrc, commission)
        if price <= 0:
            skipped_price += 1
            continue

        # deduplicate photo URLs
        pictures: list = []
        seen_pics: set = set()
        images_el = p.find("images")
        if images_el is not None:
            for img in images_el.findall("image"):
                url = (img.text or img.get("url") or "").strip()
                if url.startswith("http") and len(url) < 500 and url not in seen_pics:
                    seen_pics.add(url)
                    pictures.append(url)

        if rz_id not in categories_used:
            categories_used[rz_id] = cat_name
        brands.add(vendor)

        offers_data.append({
            "artikul":     artikul,
            "name":        name,
            "description": description,
            "rz_id":       rz_id,
            "vendor":      vendor,
            "warranty":    warranty,
            "stock_qty":   stock_qty,
            "price":       price,
            "pictures":    pictures,
        })

    # ── build XML ─────────────────────────────────────────────────────────
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
    for cat_rz_id, cat_name in categories_used.items():
        lines.append(f'      <category id="{cat_rz_id}">{xml_escape(cat_name)}</category>')
    lines.extend(["    </categories>", "    <offers>"])

    for o in offers_data:
        oid   = xml_escape(o["artikul"])
        offer = [f'      <offer id="{oid}" available="true">']
        offer.append(f'        <price>{o["price"]}</price>')
        offer.append("        <currencyId>UAH</currencyId>")
        offer.append(f'        <categoryId>{o["rz_id"]}</categoryId>')
        for pic in o["pictures"][:10]:
            offer.append(f"        <picture>{pic}</picture>")
        offer.append(f'        <vendor>{xml_escape(o["vendor"])}</vendor>')
        offer.append(f'        <article>{xml_escape(o["artikul"])}</article>')
        offer.append(f'        <stock_quantity>{o["stock_qty"]}</stock_quantity>')
        offer.append(f'        <name_ua>{xml_escape(o["name"])}</name_ua>')
        if o["description"]:
            offer.append(
                f'        <description_ua><![CDATA[<p>{xml_escape(o["description"])}</p>]]></description_ua>'
            )
        offer.append(f'        <param name="Бренд">{xml_escape(o["vendor"])}</param>')
        if o["warranty"] and o["warranty"] != "0":
            offer.append(f'        <param name="Гарантія">{xml_escape(o["warranty"])} міс</param>')
        offer.append(f'        <param name="Артикул">{xml_escape(o["artikul"])}</param>')
        offer.append("      </offer>")
        lines.extend(offer)

    lines.extend(["    </offers>", "  </shop>", "</yml_catalog>"])

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.success(f"[KatranCat] XML збережено: {output_file} ({len(offers_data)} офферів)")
    return {
        "output":        output_file,
        "total":         len(offers_data),
        "categories":    len(categories_used),
        "cat_names":     categories_used,
        "brands":        sorted(brands),
        "skipped_price": skipped_price,
        "skipped_sale":  skipped_sale,
    }


# ─── entry point ──────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Генерація XML Розетки по конкретних категоріях Катрана"
    )
    parser.add_argument("rz_ids", help="rz_id через кому: 80158,237815")
    parser.add_argument("--output", default=None, help="Вихідний XML (default: /tmp/katran_cat_{ids}.xml)")
    args = parser.parse_args()

    rz_ids = [r.strip() for r in args.rz_ids.split(",") if r.strip()]
    if not rz_ids:
        print("Помилка: порожній список rz_id")
        sys.exit(1)

    filename_part = "_".join(rz_ids)
    output_file   = args.output or f"/tmp/katran_cat_{filename_part}.xml"

    stats = generate_category_xml(rz_ids, output_file)

    print(f"\n{'='*62}")
    print(f"  Категорії rz_id: {', '.join(rz_ids)}")
    print(f"{'='*62}")
    print(f"  Офферів    : {stats['total']}")
    print(f"  Категорій  : {stats['categories']}")
    print(f"  Збережено  : {stats['output']}")
    if stats["skipped_price"]:
        print(f"  Пропущено (ціна=0)  : {stats['skipped_price']}")
    if stats["skipped_sale"]:
        print(f"  Пропущено (уцінки)  : {stats['skipped_sale']}")

    print(f"\n  Бренди ({len(stats['brands'])}):")
    for b in stats["brands"]:
        print(f"    - {b}")

    # ── show first 3 offers ───────────────────────────────────────────────
    print(f"\n  Перші 3 оффери:")
    try:
        tree      = ET.parse(output_file)
        offers_el = tree.getroot().find("shop").find("offers")
        for i, offer in enumerate(offers_el.findall("offer")[:3], 1):
            oid    = offer.get("id", "?")
            name   = (offer.findtext("name_ua") or "")[:65]
            cat    = offer.findtext("categoryId") or "?"
            price  = offer.findtext("price") or "?"
            vendor = offer.findtext("vendor") or "?"
            pics   = len(offer.findall("picture"))
            desc_raw = offer.findtext("description_ua") or ""
            desc   = desc_raw[:60].replace("\n", " ") if desc_raw else "(без опису)"
            print(f"\n  [{i}] id       = {oid}")
            print(f"       name_ua  = {name}")
            print(f"       category = {cat}  price = {price} UAH  vendor = {vendor}")
            print(f"       photos   = {pics}  desc  = {desc}...")
    except Exception as e:
        print(f"  (помилка при читанні XML: {e})")

    # ── run validator ─────────────────────────────────────────────────────
    print(f"\n{'─'*62}")
    print("  Запускаю валідатор...")
    print(f"{'─'*62}\n")
    sys.stdout.flush()  # flush before subprocess to preserve output order
    script_dir = os.path.dirname(os.path.abspath(__file__))
    validator  = os.path.join(script_dir, "rozetka_xml_validator.py")
    result = subprocess.run(
        [sys.executable, validator, "--no-xlsx", output_file],
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
