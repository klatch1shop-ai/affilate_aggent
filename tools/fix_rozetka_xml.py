#!/usr/bin/env python3
"""
fix_rozetka_xml.py — виправляє price.xml за вимогами Розетки.

Використання:
    python tools/fix_rozetka_xml.py price.xml
    python tools/fix_rozetka_xml.py price.xml --out fixed_price.xml --errors errors.txt
    python tools/fix_rozetka_xml.py --url https://... --out fixed.xml
"""

import argparse
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

import requests

try:
    from lxml import etree as ET
    LXML = True
except ImportError:
    import xml.etree.ElementTree as ET
    LXML = False


# ── Очищення HTML ────────────────────────────────────────

# Видаляє будь-які HTML-теги, залишає лише текстовий вміст
_HTML_TAG_RE = re.compile(r"<[^>]+>")

def strip_html(text: str) -> str:
    """<a href="...">текст</a>  →  текст"""
    clean = _HTML_TAG_RE.sub("", text)
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    return clean


# ── Форматування назви ────────────────────────────────────

def format_name(raw: str) -> str:
    """
    Схема: Тип Бренд Модель (Артикул)
    - Видаляє зайві дефіси між словами та коми між частинами назви
    - Нормалізує пробіли
    """
    # Видаляємо коми (розділювачі між частинами)
    name = raw.replace(",", " ")
    # Видаляємо дефіси що стоять між словами (тобто оточені пробілами)
    name = re.sub(r"\s+-\s+", " ", name)
    # Нормалізуємо пробіли
    name = re.sub(r"\s{2,}", " ", name).strip()
    return name


# ── Основна обробка ───────────────────────────────────────

def process(input_path: Path, output_path: Path, errors_path: Path):
    # Парсимо з збереженням оригінального форматування якщо lxml
    if LXML:
        parser = ET.XMLParser(remove_blank_text=False)
        tree = ET.parse(str(input_path), parser)
        root = tree.getroot()
    else:
        tree = ET.parse(str(input_path))
        root = tree.getroot()

    # Знаходимо всі offer-елементи незалежно від структури документа
    offers = root.findall(".//offer")
    if not offers:
        print("[WARN] Не знайдено жодного <offer> в файлі.")

    fixed_stock = 0
    fixed_photos = 0
    fixed_html = 0
    name_counts: Counter = Counter()
    name_to_ids: dict[str, list] = {}

    for offer in offers:
        offer_id = offer.get("id", "<no id>")

        # 1. stock_quantity ─────────────────────────────────
        if offer.find("stock_quantity") is None:
            sq = ET.SubElement(offer, "stock_quantity")
            sq.text = "10"
            fixed_stock += 1

        # 2. Форматування назви ─────────────────────────────
        name_el = offer.find("name")
        if name_el is not None and name_el.text:
            name_el.text = format_name(name_el.text)

        # 3. Очищення HTML з description / description_ua ───
        for field in ("description", "description_ua"):
            el = offer.find(field)
            if el is not None and el.text and "<" in el.text:
                el.text = strip_html(el.text)
                fixed_html += 1

        # 4. Дублі фото ─────────────────────────────────────
        pictures = offer.findall("picture")
        seen_urls: set[str] = set()
        for pic in pictures:
            url = (pic.text or "").strip()
            if url in seen_urls:
                offer.remove(pic)
                fixed_photos += 1
            else:
                seen_urls.add(url)

        # 5. Збираємо назви для перевірки унікальності ──────
        name_el = offer.find("name")
        if name_el is not None and name_el.text:
            title = name_el.text.strip()
            name_counts[title] += 1
            name_to_ids.setdefault(title, []).append(offer_id)

    # 5. Визначаємо неунікальні назви
    duplicated_names = {n: ids for n, ids in name_to_ids.items() if name_counts[n] > 1}

    # ── Запис errors.txt ─────────────────────────────────
    with errors_path.open("w", encoding="utf-8") as ef:
        if duplicated_names:
            ef.write("=== Неунікальні назви товарів ===\n\n")
            for name, ids in sorted(duplicated_names.items()):
                ef.write(f"[{len(ids)}x] {name}\n")
                ef.write(f"      offer id: {', '.join(ids)}\n\n")
        else:
            ef.write("Неунікальних назв не знайдено.\n")

    # ── Запис fixed_price.xml ────────────────────────────
    if LXML:
        tree.write(
            str(output_path),
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8",
        )
    else:
        ET.indent(tree)   # Python 3.9+
        tree.write(
            str(output_path),
            encoding="unicode",
            xml_declaration=False,
        )
        # Додаємо xml-декларацію вручну для ElementTree
        content = output_path.read_text(encoding="utf-8")
        output_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n' + content,
            encoding="utf-8",
        )

    # ── Звіт ─────────────────────────────────────────────
    print("=" * 50)
    print("Звіт fix_rozetka_xml")
    print("=" * 50)
    print(f"  Оброблено офферів  : {len(offers)}")
    print(f"  Додано stock_qty   : {fixed_stock}")
    print(f"  Очищено HTML опис  : {fixed_html}")
    print(f"  Видалено дублів фото: {fixed_photos}")
    print(f"  Неунікальних назв  : {len(duplicated_names)}")
    print("-" * 50)
    print(f"  Вихідний файл      : {output_path}")
    print(f"  Файл помилок       : {errors_path}")
    print("=" * 50)

    if duplicated_names:
        sys.exit(1)   # Ненульовий код щоб CI міг відловити


# ── CLI ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Виправляє price.xml за вимогами Розетки"
    )
    parser.add_argument(
        "input", type=str, nargs="?", default=None,
        help="Локальний XML-файл або URL (позиційний)",
    )
    parser.add_argument(
        "--url", type=str, default=None,
        help="URL фіду — альтернатива позиційному аргументу",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Вихідний файл (за замовчуванням: fixed_price.xml)",
    )
    parser.add_argument(
        "--errors", type=Path, default=Path("errors.txt"),
        help="Файл для списку неунікальних назв (за замовчуванням: errors.txt)",
    )
    args = parser.parse_args()

    src = args.url or args.input
    if not src:
        parser.error("Вкажи файл або --url <URL>")
    tmp = None

    if src.startswith("http://") or src.startswith("https://"):
        print(f"[INFO] Завантажую {src[:80]}...")
        try:
            resp = requests.get(src, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[ERROR] Не вдалось завантажити URL: {e}", file=sys.stderr)
            sys.exit(2)
        tmp = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
        tmp.write(resp.content)
        tmp.flush()
        input_path = Path(tmp.name)
        output = args.out or Path("fixed_price.xml")
    else:
        input_path = Path(src)
        if not input_path.exists():
            print(f"[ERROR] Файл не знайдено: {input_path}", file=sys.stderr)
            sys.exit(2)
        output = args.out or input_path.parent / f"fixed_{input_path.name}"

    try:
        process(input_path, output, args.errors)
    finally:
        if tmp:
            Path(tmp.name).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
