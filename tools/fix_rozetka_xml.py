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

import html as _html_module

# Видаляє будь-які HTML-теги, залишає лише текстовий вміст
_HTML_TAG_RE = re.compile(r"<[^>]+>")

def decode_html_entities(text: str) -> str:
    """&mdash; → —, &rsquo; → ', &nbsp; → ' ', тощо."""
    return _html_module.unescape(text or "")

def strip_html(text: str) -> str:
    """<a href="...">текст</a>  →  текст; також декодує HTML-ентіті."""
    clean = _HTML_TAG_RE.sub("", text)
    clean = decode_html_entities(clean)
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    return clean


# ── Видалення рекламних фраз ─────────────────────────────

AD_PHRASES = [
    "почуваєшся майстром",
    "почувствуешь себя мастером",
    "профессионалами для профессионалов",
    "професіоналами для професіоналів",
    "гарантія успіху",
    "гарантия успеха",
    "незамінний помічник",
    "незаменимый помощник",
    "широкий термін служби",
    "широкий срок службы",
    "використовуючи інструменти toptul",
    "используя инструменты toptul",
    "створені професіоналами",
    "созданы профессионалами",
]

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

def remove_ad_phrases(text: str) -> tuple[str, int]:
    """Видаляє речення що містять рекламні фрази.
    Повертає (очищений текст, кількість видалених речень)."""
    if not text:
        return text, 0
    sentences = _SENTENCE_RE.split(text)
    clean = []
    removed = 0
    lower_phrases = AD_PHRASES  # вже в нижньому регістрі
    for s in sentences:
        s_lower = s.lower()
        if any(ph in s_lower for ph in lower_phrases):
            removed += 1
        else:
            clean.append(s)
    return " ".join(clean).strip(), removed


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


# ── Видалення категорій ───────────────────────────────────

REMOVE_CATEGORY_KEYWORDS = [
    "зарядные станции",
    "пусковые и зарядные",
]

def remove_categories(root, keywords: list[str]) -> int:
    """Видаляє offers чиї категорії містять будь-яке з ключових слів (без урахування регістру).
    Повертає кількість видалених offers."""
    # Будуємо карту categoryId → назва
    cat_names: dict[str, str] = {}
    for cat in root.iter("category"):
        cid = cat.get("id")
        if cid:
            cat_names[cid] = (cat.text or "").lower()

    # Знаходимо id категорій що підпадають під видалення
    blocked_ids: set[str] = set()
    for cid, name in cat_names.items():
        if any(kw in name for kw in keywords):
            blocked_ids.add(cid)

    # Видаляємо offers
    removed = 0
    for offers_parent in root.iter():
        to_remove = []
        for child in list(offers_parent):
            if child.tag == "offer":
                cat_el = child.find("categoryId")
                if cat_el is not None and cat_el.text in blocked_ids:
                    to_remove.append(child)
        for child in to_remove:
            offers_parent.remove(child)
            removed += 1

    return removed


# ── Переклад категорій ────────────────────────────────────

CATEGORY_TRANSLATIONS = {
    "Головки торцевые": "Головки торцеві",
    "Форсунки и ремкомплекты для краскопультов": "Форсунки та ремкомплекти для фарбопультів",
    "Головки торцевые ударные": "Головки торцеві ударні",
    "Краскопульты пневматические": "Фарбопульти пневматичні",
    "Цанговые соединения": "Цангові з'єднання",
    "Ключи комбинированные": "Ключі комбіновані",
    "Трещотки, воротки": "Тріскачки воротки",
    "Наборы инструмента в ложементах": "Набори інструменту в ложементах",
    "Отвертки": "Викрутки",
    "Плоскогубцы": "Плоскогубці",
    "Головки с насадкой": "Головки з насадкою",
    "Биты, насадки": "Біти насадки",
    "Переходники, удлинители, карданы": "Перехідники подовжувачі кардани",
    "Съемники подшипников": "Знімачі підшипників",
    "Наборы головок с трещоткой": "Набори головок з тріскачкою",
    "Развертки": "Розвертки",
    "Гайковерты пневматические": "Гайковерти пневматичні",
    "Зубила, пробойники, выколотки": "Зубила пробійники виколотки",
    "Ключи торцевые": "Ключі торцеві",
    "Наборы торцевых головок на планках": "Набори торцевих головок на планках",
    "Шарниры, карданы": "Шарніри кардани",
    "Съемники масляных фильтров": "Знімачі масляних фільтрів",
    "Ключи разрезные": "Ключі розрізні",
    "Метчики, плашки": "Мітчики плашки",
    "Пресс-клещи, обжимной инструмент": "Прес-кліщі обтискний інструмент",
    "Инструмент для тормозной системы": "Інструмент для гальмівної системи",
    "Воротки": "Воротки",
    "Захваты, зажимы": "Захвати затискачі",
    "Ключи трубные": "Ключі трубні",
    "Монтажный инструмент для сальников": "Монтажний інструмент для сальників",
    "Инструмент для работы с крепежом": "Інструмент для роботи з кріпленням",
    "Наборы ключей": "Набори ключів",
    "Динамометрические ключи": "Динамометричні ключі",
    "Ключи накидные": "Ключі накидні",
    "Наборы инструментов": "Набори інструментів",
    "Длинногубцы": "Довгогубці",
    "Кусачки, бокорезы": "Кусачки бокорізи",
    "Съемники ступиц": "Знімачі маточин",
    "Инструмент для сжатия пружин": "Інструмент для стиснення пружин",
    "Гидроцилиндры": "Гідроциліндри",
    "Станки для проточки тормозных дисков": "Верстати для проточування гальмівних дисків",
    "Маслозаправщики": "Маслозаправники",
    "Домкраты": "Домкрати",
    "Съемники рулевых наконечников": "Знімачі рульових наконечників",
    "Стенды для развала-схождения": "Стенди для розвалу сходження",
    "Прессы гидравлические": "Преси гідравлічні",
    "Стойки, подставки": "Стійки підставки",
    "Подъемники": "Підйомники",
    "Инструмент для двигателя": "Інструмент для двигуна",
    "Инструмент для КПП": "Інструмент для КПП",
    "Тиски": "Лещата",
    "Шуруповерт аккумуляторный": "Шуруповерт акумуляторний",
    "Отвертки аккумуляторные": "Викрутки акумуляторні",
    "Тестеры, диагностика": "Тестери діагностика",
    "Измерительные инструменты": "Вимірювальні інструменти",
    "Краскопульты безвоздушные": "Фарбопульти безповітряні",
    "Компрессоры": "Компресори",
    "Пневматические инструменты": "Пневматичні інструменти",
    "Ключи с трещоткой": "Ключі з тріскачкою",
    "Ключи рожковые": "Ключі ріжкові",
    "Ключи динамометрические": "Ключі динамометричні",
    "Ключи шестигранные": "Ключі шестигранні",
    "Наборы шестигранников": "Набори шестигранників",
    "Съемники рулевых тяг": "Знімачі рульових тяг",
    "Пневмопистолеты для подкачки колес": "Пневмопістолети для підкачування коліс",
    "Пневматические инструменты, аксессуары": "Пневматичні інструменти аксесуари",
    "Шланги, фитинги": "Шланги фітинги",
    "Аксессуары для компрессоров": "Аксесуари для компресорів",
    "Масленки, смазочный инструмент": "Маслянки мастильний інструмент",
    "Молотки": "Молотки",
    "Напильники": "Напилки",
    "Ножи монтажные": "Ножі монтажні",
    "Наборы инструмента": "Набори інструменту",
    "Наборы для авто": "Набори для авто",
    "Инструмент для рулевого управления": "Інструмент для рульового управління",
    "Инструмент для электрики": "Інструмент для електрики",
    "Съемники стопорных колец": "Знімачі стопорних кілець",
    "Зажимы, струбцины": "Затискачі струбцини",
    "Инструмент для кузовных работ": "Інструмент для кузовних робіт",
    "Пинцеты": "Пінцети",
    "Скребки": "Скребки",
    "Приспособления для снятия фаски": "Пристосування для зняття фаски",
    "Инструмент для радиаторов": "Інструмент для радіаторів",
    "Инструмент для подвески": "Інструмент для підвіски",
    "Ключи ударные": "Ключі ударні",
    "Наборы гаечных ключей": "Набори гайкових ключів",
    "Измерители температуры": "Вимірювачі температури",
    "Автосканеры": "Автосканери",
    "Наборы бит": "Набори біт",
    "Ключи (головки) ступичные": "Ключі головки ступичні",
    "Ящики, сумки для инструментов": "Ящики сумки для інструментів",
    "Подъемники автомобильные": "Підйомники автомобільні",
    "Отвертки крестовые, TORX": "Викрутки хрестові TORX",
    "Прокачка тормозов": "Прокачка гальм",
    "Стяжки пружин": "Стяжки пружин",
    "Съемники шаровых опор": "Знімачі кульових опор",
    "Нутромеры": "Нутроміри",
    "Микрометры": "Мікрометри",
    "Штангенциркули": "Штангенциркулі",
    "Индикаторы часового типа": "Індикатори годинникового типу",
    "Наборы метчиков и плашек": "Набори мітчиків та плашок",
    "Наборы напильников": "Набори напилків",
    "Ключи свечные": "Ключі свічні",
    "Съемники форсунок": "Знімачі форсунок",
    "Инструмент для сайлентблоков": "Інструмент для сайлентблоків",
    "Обжимной инструмент для шлангов": "Обтискний інструмент для шлангів",
    "Скобы, крюки, крепеж": "Скоби гачки кріплення",
    "Фонари, освещение": "Ліхтарі освітлення",
    "Рукоятки, ворота": "Рукоятки ворота",
    "Угольники": "Кутники",
    "Отвертки шлицевые": "Викрутки шліцеві",
    "Наборы инструмента комбинированные": "Набори інструменту комбіновані",
    "Съемники рулевых тяг и шаровых опор": "Знімачі рульових тяг та кульових опор",
    "Зенкеры": "Зенкери",
    "Головки специальные": "Головки спеціальні",
    "Тележки для инструментов": "Візки для інструментів",
    "Ключи специальные": "Ключі спеціальні",
    "Захваты для труб": "Захвати для труб",
    "Степперы, ступенчатые сверла": "Степпери ступінчасті свердла",
    "Наборы отверток": "Набори викруток",
    "Сверла": "Свердла",
    "Щупы": "Щупи",
    "Съемники клапанов": "Знімачі клапанів",
    "Хомуты": "Хомути",
    "Торцевые ключи": "Торцеві ключі",
    "Плоскогубцы переставные": "Плоскогубці переставні",
    "Ключи г-образные": "Ключі Г-подібні",
    "Магниты": "Магніти",
    "Кернеры": "Кернери",
    "Уровни": "Рівні",
    "Фонари и прожекторы": "Ліхтарі та прожектори",
    "Ключи, съемники специальные": "Ключі знімачі спеціальні",
    "Бокорезы, кусачки": "Бокорізи кусачки",
    "Шприцы для смазки": "Шприци для змащування",
    "Наборы торцевых головок": "Набори торцевих головок",
    "Круглогубцы для снятия стопорных колец": "Круглогубці для зняття стопорних кілець",
    "Безвоздушные распылители краски": "Безповітряні розпилювачі фарби",
    "Ремкомплекты для трещеток": "Ремкомплекти для тріскачок",
    "Струбцины": "Струбцини",
    "Кольца стопорные": "Кільця стопорні",
    "Насосы гидравлические": "Насоси гідравлічні",
}

def translate_categories(root) -> int:
    """Перекладає назви категорій за словником. Повертає кількість перекладених."""
    translated = 0
    for cat in root.iter("category"):
        original = (cat.text or "").strip()
        if original in CATEGORY_TRANSLATIONS:
            cat.text = CATEGORY_TRANSLATIONS[original]
            translated += 1
    return translated


# ── Видалення малих фото ──────────────────────────────────

def remove_offers_without_photos(root) -> int:
    """Видаляє всі offer що не мають жодного тегу <picture>.
    Повертає кількість видалених."""
    removed = 0
    for offers_parent in root.iter():
        to_remove = []
        for child in list(offers_parent):
            if child.tag == "offer" and not child.findall("picture"):
                to_remove.append(child)
        for child in to_remove:
            offers_parent.remove(child)
            removed += 1
    return removed


def remove_small_pictures(root, xlsx_path: str) -> int:
    """Читає Toptul_Image_Check.xlsx і видаляє <picture> з малим розміром.

    Структура XLSX: ID | ImageURL | Width | Height | Status
    Рядки де Status != 'OK' — малі фото, їх видаляємо.
    Повертає кількість видалених фото.
    """
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    bad_urls: set[str] = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] and row[4] != "OK":
            bad_urls.add(row[1])
    wb.close()

    removed = 0
    no_photo_offers = 0
    for offer in root.iter("offer"):
        pics = offer.findall("picture")
        for pic in pics:
            url = (pic.text or "").strip()
            if url in bad_urls:
                offer.remove(pic)
                removed += 1
        if not offer.findall("picture"):
            no_photo_offers += 1

    print(f"[INFO] Видалено малих фото: {removed}")
    print(f"[INFO] Офферів без фото після видалення: {no_photo_offers}")
    return removed


# ── Основна обробка ───────────────────────────────────────

def process(input_path: Path, output_path: Path, errors_path: Path, images_check: str | None = None):
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
    fixed_ad_offers = 0
    fixed_ad_sentences = 0
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
        offer_ad_sentences = 0
        for field in ("description", "description_ua"):
            el = offer.find(field)
            if el is not None and el.text:
                original = el.text
                if "<" in original:
                    el.text = strip_html(el.text)
                    fixed_html += 1
                else:
                    el.text = decode_html_entities(el.text)
                # Видалення рекламних фраз
                el.text, removed = remove_ad_phrases(el.text)
                offer_ad_sentences += removed
        if offer_ad_sentences:
            fixed_ad_offers += 1
            fixed_ad_sentences += offer_ad_sentences

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

    # 6. Видалення заборонених категорій ────────────────────
    removed_offers = remove_categories(root, REMOVE_CATEGORY_KEYWORDS)

    # 7. Переклад категорій ─────────────────────────────────
    translated_cats = translate_categories(root)

    # 8. Видалення малих фото (якщо передано xlsx) ──────────
    removed_small_pics = 0
    if images_check:
        if Path(images_check).exists():
            removed_small_pics = remove_small_pictures(root, images_check)
        else:
            print(f"[WARN] Файл не знайдено: {images_check}")

    # 9. Видалення офферів без фото ─────────────────────────
    removed_no_photo = remove_offers_without_photos(root)

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
    print(f"  Видалено офферів   : {removed_offers} (заборонені категорії)")
    print(f"  Перекладено кат.   : {translated_cats}")
    print(f"  Офферів з рекламою : {fixed_ad_offers}")
    print(f"  Рекламних речень   : {fixed_ad_sentences} видалено")
    print(f"  Малих фото видалено: {removed_small_pics}")
    print(f"  Офферів без фото видалено: {removed_no_photo}")
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
    parser.add_argument(
        "--images-check", type=str, default=None,
        help="Шлях до Toptul_Image_Check.xlsx для видалення малих фото",
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
        process(input_path, output, args.errors, images_check=args.images_check)
    finally:
        if tmp:
            Path(tmp.name).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
