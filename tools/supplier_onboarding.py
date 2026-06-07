#!/usr/bin/env python3
"""
tools/supplier_onboarding.py — Інтерактивний wizard для підключення нового постачальника.

Usage:
  python3 tools/supplier_onboarding.py
  python3 tools/supplier_onboarding.py --resume katran
  python3 tools/supplier_onboarding.py --resume katran --step 3
  python3 tools/supplier_onboarding.py --no-color
"""

import argparse
import io
import json
import math
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from difflib import SequenceMatcher
from xml.etree import ElementTree as ET

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

PROGRESS_DIR = "/tmp"
REPO_ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR    = os.path.join(REPO_ROOT, "tools", "rozetka_xml_validator.py")


# ─── Colors ───────────────────────────────────────────────────────────────────

try:
    from rich.console import Console
    from rich.table import Table
    from rich import print as rprint
    _console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

class C:
    BLUE   = "\033[94m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"

    @classmethod
    def disable(cls):
        for attr in ("BLUE","GREEN","YELLOW","RED","CYAN","BOLD","DIM","RESET"):
            setattr(cls, attr, "")


def ok(msg):   print(f"  {C.GREEN}✓{C.RESET}  {msg}")
def warn(msg): print(f"  {C.YELLOW}⚠{C.RESET}  {msg}")
def err(msg):  print(f"  {C.RED}✗{C.RESET}  {msg}")
def info(msg): print(f"  {C.DIM}→{C.RESET}  {msg}")


# ─── DB ───────────────────────────────────────────────────────────────────────

def get_db():
    from shared.utils.db import get_connection
    return get_connection()


def ensure_tables():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            code        VARCHAR(50) PRIMARY KEY,
            name        VARCHAR(200),
            feed_url    TEXT,
            feed_format VARCHAR(20),
            marketplace VARCHAR(20),
            status      VARCHAR(20) DEFAULT 'active',
            created_at  TIMESTAMP DEFAULT now()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS supplier_category_map (
            id                     SERIAL PRIMARY KEY,
            supplier_code          VARCHAR(50),
            supplier_category_id   VARCHAR(100),
            supplier_category_name VARCHAR(200),
            rz_id                  VARCHAR(50),
            rz_name                VARCHAR(200),
            commission_pct         NUMERIC(5,2) DEFAULT 7.0,
            created_at             TIMESTAMP DEFAULT now(),
            UNIQUE (supplier_code, supplier_category_id)
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


def get_rozetka_categories():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT ON (rozetka_rz_id)
                rozetka_rz_id, rozetka_category, commission_pct
            FROM katran_categories
            WHERE rozetka_rz_id IS NOT NULL AND rozetka_category IS NOT NULL
            ORDER BY rozetka_rz_id, rozetka_category
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            (str(r["rozetka_rz_id"]), r["rozetka_category"], float(r["commission_pct"]))
            for r in rows
        ]
    except Exception as e:
        warn(f"БД недоступна (категорії Розетки): {e}")
        return []


# ─── Feed loading ──────────────────────────────────────────────────────────────

def load_feed_bytes(url_or_path, fmt):
    if url_or_path.startswith("http"):
        import requests
        info("Завантажую з URL...")
        r = requests.get(url_or_path, timeout=120)
        r.raise_for_status()
        return r.content
    else:
        with open(url_or_path, "rb") as f:
            return f.read()


def parse_xml_bytes(content, fmt):
    if fmt == "zip_xml":
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            if not xml_names:
                raise ValueError("Не знайдено XML у ZIP-архіві")
            with zf.open(xml_names[0]) as f:
                return ET.parse(f).getroot()
    elif fmt == "xml":
        return ET.fromstring(content)
    else:
        raise NotImplementedError(f"Формат {fmt} потребує openpyxl — запустіть на ноутбуці")


def detect_structure(root):
    """Повертає dict з метаінформацією про структуру XML."""
    # Katran / generic <products><product>
    products_el = root.find("products")
    if products_el is None and root.tag in ("products", "price"):
        products_el = root
    if products_el is not None:
        products = products_el.findall("product")
        if products:
            sample = products[0]
            fields = sorted({c.tag for c in sample})
            cats = {}
            for p in products[:300]:
                cid   = (p.findtext("categoryId") or p.findtext("category_id") or "").strip()
                cname = cid
                if cid and cid not in cats:
                    cats[cid] = cname
            # Try to get category names from <categories> block
            cats_el = root.find("categories")
            if cats_el is None and products_el is not None:
                cats_el = root.find(".//categories")
            if cats_el is not None:
                for c in cats_el.findall("category"):
                    cid = c.get("id", "")
                    if cid:
                        cats[cid] = c.text or cid
            return {
                "style": "katran",
                "product_tag": "product",
                "count": len(products),
                "fields": fields,
                "categories": cats,
                "sample": sample,
            }

    # YML catalog (Prom / Rozetka)
    offers_el = root.find(".//offers")
    if offers_el is not None:
        offers = offers_el.findall("offer")
        cats = {}
        cats_el = root.find(".//categories")
        if cats_el is not None:
            for c in cats_el.findall("category"):
                cats[c.get("id", "")] = c.text or ""
        sample = offers[0] if offers else None
        fields = sorted({c.tag for c in sample}) if sample else []
        return {
            "style": "yml",
            "product_tag": "offer",
            "count": len(offers),
            "fields": fields,
            "categories": cats,
            "sample": sample,
        }

    # Generic fallback
    first_tag = next((c.tag for c in root), None)
    if first_tag:
        items = root.findall(first_tag)
        sample = items[0] if items else None
        fields = sorted({c.tag for c in sample}) if sample else []
        return {
            "style": "generic",
            "product_tag": first_tag,
            "count": len(items),
            "fields": fields,
            "categories": {},
            "sample": sample,
        }

    raise ValueError(f"Не вдалося визначити структуру XML (root: <{root.tag}>)")


# ─── XML generator ─────────────────────────────────────────────────────────────

def xml_escape(text):
    return (str(text)
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def parse_float(text):
    try:
        return float(str(text or "0").replace(",", ".").strip())
    except (ValueError, TypeError):
        return 0.0


def calc_price(price_rrc, commission_pct):
    if price_rrc <= 0:
        return 0
    return int(math.ceil(price_rrc * (1 + commission_pct / 100) / 10) * 10)


def is_in_stock(s):
    s = (s or "").lower().strip()
    return s.startswith("е") or s.startswith("є") or s in ("true", "1", "yes", "in stock")


def generate_xml(root, struct, mappings, field_map, output_file, supplier_name):
    """Генерує YML-XML з довільного XML фіду."""
    DEFAULT_RZ_ID = "25636737"

    # collect products
    if struct["style"] == "katran":
        products_el = root.find("products")
        products = (products_el if products_el is not None else root).findall("product")
    elif struct["style"] == "yml":
        products = root.findall(".//offer")
    else:
        products = root.findall(struct["product_tag"])

    cats_used = {}
    offers_out = []
    seen_ids = set()
    skipped = 0

    for p in products:
        code    = (p.findtext(field_map.get("code", "code")) or
                   p.findtext("artikul") or p.findtext("id") or "").strip()
        name    = (p.findtext(field_map.get("name", "name")) or "").strip()
        vendor  = (p.findtext(field_map.get("vendor", "vendor")) or "").strip()
        stock_s = (p.findtext(field_map.get("stock", "stock")) or "").strip()
        cat_id  = (p.findtext(field_map.get("category_id", "categoryId")) or "").strip()

        price_field = field_map.get("price", "price_rrc")
        price_rrc   = parse_float(p.findtext(price_field) or p.findtext("price_rrc") or "0")

        if not code or not name or not is_in_stock(stock_s):
            skipped += 1
            continue
        if code in seen_ids:
            skipped += 1
            continue
        seen_ids.add(code)

        mapping    = mappings.get(cat_id, {})
        rz_id      = mapping.get("rz_id", DEFAULT_RZ_ID)
        commission = mapping.get("commission", 7.0)
        rz_name    = mapping.get("rz_name", "Ручний інструмент")

        price = calc_price(price_rrc, commission)
        if price <= 0:
            skipped += 1
            continue

        if not vendor or vendor.lower() in ("no name", "noname", "no-name", "unknown"):
            vendor = "Без бренду"

        # photos
        pics = []
        imgs_el = p.find(field_map.get("images", "images"))
        if imgs_el is not None:
            for img in imgs_el:
                url = (img.text or img.get("url") or "").strip()
                if url.startswith("http"):
                    pics.append(url)
        elif p.findtext("image"):
            url = p.findtext("image").strip()
            if url.startswith("http"):
                pics.append(url)

        desc = re.sub(r"https?://\S+", "", (p.findtext(field_map.get("description", "description")) or "")).strip()
        warranty = (p.findtext(field_map.get("warranty", "warranty")) or "").strip()
        stock_qty = max(int(parse_float(p.findtext("stock_quantity") or "1")), 1)

        if rz_id not in cats_used:
            cats_used[rz_id] = rz_name

        lines = [f'      <offer id="{xml_escape(code)}" available="true">']
        lines.append(f"        <price>{price}</price>")
        lines.append("        <currencyId>UAH</currencyId>")
        lines.append(f"        <categoryId>{rz_id}</categoryId>")
        for pic in pics[:10]:
            lines.append(f"        <picture>{pic}</picture>")
        lines.append(f"        <vendor>{xml_escape(vendor)}</vendor>")
        lines.append(f"        <article>{xml_escape(code)}</article>")
        lines.append(f"        <stock_quantity>{stock_qty}</stock_quantity>")
        lines.append(f"        <name_ua>{xml_escape(name[:255])}</name_ua>")
        if desc:
            lines.append(f"        <description_ua><![CDATA[<p>{xml_escape(desc[:2000])}</p>]]></description_ua>")
        lines.append(f'        <param name="Бренд">{xml_escape(vendor)}</param>')
        if warranty and warranty != "0":
            lines.append(f'        <param name="Гарантія">{xml_escape(warranty)} міс</param>')
        lines.append(f'        <param name="Артикул">{xml_escape(code)}</param>')
        lines.append("      </offer>")
        offers_out.append("\n".join(lines))

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{now}">',
        "  <shop>",
        f"    <name>{xml_escape(supplier_name)}</name>",
        "    <company>FOP Oliinyk Serhii</company>",
        "    <url>https://seller.rozetka.com.ua/</url>",
        "    <currencies><currency id=\"UAH\" rate=\"1\"/></currencies>",
        "    <categories>",
    ] + [
        f'      <category id="{rid}">{xml_escape(rname)}</category>'
        for rid, rname in cats_used.items()
    ] + [
        "    </categories>",
        "    <offers>",
    ] + offers_out + [
        "    </offers>",
        "  </shop>",
        "</yml_catalog>",
    ]

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(xml_lines))

    return {"total": len(offers_out), "skipped": skipped, "categories": len(cats_used)}


# ─── Wizard ────────────────────────────────────────────────────────────────────

class SupplierOnboarding:

    def __init__(self, supplier_code=None, no_color=False):
        if no_color or not sys.stdout.isatty():
            C.disable()
        self.state = {}
        self.progress_file = None
        if supplier_code:
            self.progress_file = f"{PROGRESS_DIR}/onboarding_{supplier_code}.json"
            self._load_progress()

    # ── persistence ──────────────────────────────────────────────────────────────

    def _load_progress(self):
        if self.progress_file and os.path.exists(self.progress_file):
            with open(self.progress_file) as f:
                self.state = json.load(f)
            done = self.state.get("completed_steps", [])
            if done:
                warn(f"Знайдено прогрес — завершено кроки: {done}")

    def _save(self):
        if not self.progress_file:
            self.progress_file = f"{PROGRESS_DIR}/onboarding_{self.state.get('code','unknown')}.json"
        with open(self.progress_file, "w") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def _done(self, step):
        return step in self.state.get("completed_steps", [])

    def _mark_done(self, step):
        done = self.state.setdefault("completed_steps", [])
        if step not in done:
            done.append(step)
        self._save()

    # ── UI ───────────────────────────────────────────────────────────────────────

    def header(self, step, title):
        bar = "─" * 56
        print(f"\n{C.BOLD}{C.BLUE}┌{bar}┐{C.RESET}")
        label = f"  КРОК {step}: {title}"
        print(f"{C.BOLD}{C.BLUE}│{label:<56}│{C.RESET}")
        print(f"{C.BOLD}{C.BLUE}└{bar}┘{C.RESET}\n")

    def prompt(self, text, default=None, required=True):
        hint = f" [{C.DIM}{default}{C.RESET}]" if default is not None else ""
        while True:
            val = input(f"  {C.CYAN}?{C.RESET} {text}{hint}: ").strip()
            if not val and default is not None:
                return default
            if val or not required:
                return val
            warn("Обов'язкове поле")

    def choose(self, text, options, default=None):
        opts_str = "/".join(
            f"{C.BOLD}{o.upper()}{C.RESET}" if o == default else o
            for o in options
        )
        while True:
            val = input(f"  {C.CYAN}?{C.RESET} {text} [{opts_str}]: ").strip().lower()
            if not val and default:
                return default
            if val in options:
                return val
            warn(f"Введіть одне з: {', '.join(options)}")

    def confirm(self, text, default="y"):
        hint = "Y/n" if default == "y" else "y/N"
        val = input(f"  {C.CYAN}?{C.RESET} {text} [{hint}]: ").strip().lower()
        return (val in ("y", "yes", "т", "так")) if val else (default == "y")

    # ── STEP 1: Basic info ──────────────────────────────────────────────────────

    def step1_basic_info(self):
        if self._done(1):
            ok(f"Крок 1 пропущено: {self.state.get('name')} ({self.state.get('code')})")
            return

        self.header(1, "Базова інформація")

        name    = self.prompt("Назва постачальника (напр. Катран)",   self.state.get("name"))
        code    = self.prompt("Код (латиниця, без пробілів)",         self.state.get("code"))
        code    = re.sub(r"[^a-z0-9_]", "_", code.lower())
        feed    = self.prompt("URL фіду або шлях до файлу",           self.state.get("feed_url"))
        fmt     = self.choose("Формат фіду", ["xml","zip_xml","xls","xlsx"],
                              default=self.state.get("feed_format", "xml"))
        market  = self.choose("Маркетплейс", ["rozetka","epicentr","prom","all"],
                              default=self.state.get("marketplace", "rozetka"))

        self.state.update({
            "name": name, "code": code,
            "feed_url": feed, "feed_format": fmt, "marketplace": market,
        })
        self.progress_file = f"{PROGRESS_DIR}/onboarding_{code}.json"
        self._mark_done(1)
        ok(f"Збережено: {name} ({code}), формат={fmt}, маркетплейс={market}")

    # ── STEP 2: Analyze feed ────────────────────────────────────────────────────

    def step2_analyze_feed(self):
        if self._done(2):
            ok(f"Крок 2 пропущено — {self.state.get('products_count','?')} товарів, "
               f"{len(self.state.get('categories',{}))} категорій")
            return

        self.header(2, "Аналіз фіду")

        fmt = self.state["feed_format"]
        if fmt in ("xls", "xlsx"):
            warn(f"Формат {fmt} потребує openpyxl (тільки на ноутбуці з AVX).")
            if not self.confirm("Продовжити без автоматичного аналізу?", default="n"):
                sys.exit(0)
            self.state.update({"products_count": 0, "categories": {}, "field_map": {}})
            self._mark_done(2)
            return

        info(f"Завантажую фід...")
        try:
            content = load_feed_bytes(self.state["feed_url"], fmt)
            ok(f"Завантажено {len(content):,} байт")
        except Exception as e:
            err(f"Помилка завантаження: {e}")
            sys.exit(1)

        info("Аналізую структуру XML...")
        try:
            root   = parse_xml_bytes(content, fmt)
            struct = detect_structure(root)
        except Exception as e:
            err(f"Помилка парсингу: {e}")
            sys.exit(1)

        print(f"\n  {C.BOLD}Виявлена структура:{C.RESET}")
        print(f"    Стиль    : {C.GREEN}{struct['style']}{C.RESET}")
        print(f"    Товарів  : {C.GREEN}{struct['count']:,}{C.RESET}")
        print(f"    Поля     : {', '.join(struct['fields'][:15])}")
        print(f"    Категорій: {len(struct['categories'])}")

        if struct["categories"]:
            print(f"\n  {C.BOLD}Перші 10 категорій постачальника:{C.RESET}")
            for i, (cid, cname) in enumerate(list(struct["categories"].items())[:10]):
                print(f"    {C.DIM}{cid:>10}{C.RESET}  {cname}")

        if struct["sample"] is not None:
            print(f"\n  {C.BOLD}Приклад товару (перші поля):{C.RESET}")
            for child in list(struct["sample"])[:10]:
                val = (child.text or "").strip()[:70]
                if val:
                    print(f"    {C.DIM}{child.tag:<22}{C.RESET} {val}")

        if not self.confirm("\n  Структура розпізнана правильно?"):
            warn("Перевірте URL / формат і запустіть знову")
            sys.exit(0)

        # Field mapping
        print(f"\n  {C.BOLD}Маппінг полів (Enter = залишити пропозицію):{C.RESET}")
        fields = struct["fields"]

        def auto(candidates, fallback):
            return next((f for f in candidates if f in fields), fallback)

        field_map = {
            "code":        self.prompt("  Артикул/code",     auto(["artikul","article","code","id","sku"], "code"), required=False) or "code",
            "name":        self.prompt("  Назва/name",       auto(["name","title","name_ua"], "name"), required=False) or "name",
            "vendor":      self.prompt("  Бренд/vendor",     auto(["vendor","brand","manufacturer"], "vendor"), required=False) or "vendor",
            "stock":       self.prompt("  Наявність/stock",  auto(["stock","availability","instock"], "stock"), required=False) or "stock",
            "category_id": self.prompt("  Категорія ID",     auto(["categoryId","category_id","category"], "categoryId"), required=False) or "categoryId",
            "price":       self.prompt("  Ціна RRC",         auto(["price_rrc","rrc","price","price_pdv"], "price_rrc"), required=False) or "price_rrc",
            "images":      self.prompt("  Фото/images",      auto(["images","photos","pictures"], "images"), required=False) or "images",
            "description": self.prompt("  Опис",             auto(["description","desc"], "description"), required=False) or "description",
            "warranty":    self.prompt("  Гарантія",         auto(["warranty","guarantee"], "warranty"), required=False) or "warranty",
        }

        self.state.update({
            "products_count": struct["count"],
            "categories":     struct["categories"],
            "field_map":      field_map,
            "feed_style":     struct["style"],
        })
        self._mark_done(2)
        ok(f"Аналіз завершено: {struct['count']:,} товарів, {len(struct['categories'])} категорій")

    # ── STEP 3: Category mapping ────────────────────────────────────────────────

    def step3_category_mapping(self):
        if self._done(3):
            mapped = sum(1 for v in self.state.get("mappings", {}).values() if v.get("rz_id") != "25636737")
            ok(f"Крок 3 пропущено — {mapped} категорій змапповано в реальні rz_id")
            return

        self.header(3, "Маппінг категорій")

        supplier_cats = self.state.get("categories", {})
        if not supplier_cats:
            warn("Немає категорій — пропускаю")
            self.state["mappings"] = {}
            self._mark_done(3)
            return

        info("Завантажую категорії Розетки з БД...")
        rz_cats = get_rozetka_categories()
        if not rz_cats:
            warn("Категорії Розетки не знайдені — використовуватиму DEFAULT (25636737)")
            rz_cats = [("25636737", "Ручний інструмент", 7.0)]
        else:
            ok(f"Знайдено {len(rz_cats)} унікальних категорій Розетки в БД")

        def best_matches(query):
            q = query.lower()
            q_words = set(q.split())
            scored = []
            for rz_id, rz_name, commission in rz_cats:
                n = rz_name.lower()
                n_words = set(n.split())
                seq_score  = SequenceMatcher(None, q, n).ratio()
                word_score = len(q_words & n_words) / max(len(q_words), 1)
                scored.append((rz_id, rz_name, max(seq_score, word_score * 0.85), commission))
            scored.sort(key=lambda x: -x[2])
            return scored[:3]

        mappings  = self.state.get("mappings", {})
        remaining = [(cid, cn) for cid, cn in supplier_cats.items() if cid not in mappings]
        total     = len(supplier_cats)

        print(f"\n  {C.BOLD}Маппінг {total} категорій постачальника → Розетка:{C.RESET}")
        if total > len(remaining):
            info(f"Вже змапповано: {total - len(remaining)}, залишилось: {len(remaining)}")
        print(f"  {C.DIM}Enter=#1  2/3=варіант  0=DEFAULT  числовий rz_id=вручну{C.RESET}\n")

        auto_threshold = 0.0
        if len(remaining) > 20:
            if self.confirm(f"  Категорій багато ({len(remaining)}). Авто-приймати оцінку ≥ 0.7?"):
                auto_threshold = 0.7

        for i, (cat_id, cat_name) in enumerate(remaining, 1):
            matches = best_matches(cat_name)
            b_id, b_name, b_score, b_comm = matches[0]

            print(f"  [{i}/{len(remaining)}] {C.BOLD}{cat_name}{C.RESET}  (id={cat_id})")

            if auto_threshold and b_score >= auto_threshold:
                print(f"    {C.GREEN}→ авто: {b_name} ({b_id}) [{b_score:.2f}]{C.RESET}")
                mappings[cat_id] = {
                    "supplier_name": cat_name,
                    "rz_id": b_id, "rz_name": b_name, "commission": b_comm,
                }
                if i % 15 == 0:
                    self.state["mappings"] = mappings
                    self._save()
                continue

            for j, (rid, rname, score, comm) in enumerate(matches, 1):
                sc = C.GREEN if score >= 0.6 else (C.YELLOW if score >= 0.3 else C.RED)
                print(f"    {j}. {rname} ({rid}) {sc}[{score:.2f}]{C.RESET} комісія={comm}%")

            val = input(f"    {C.CYAN}→{C.RESET} [Enter/2/3/0/rz_id]: ").strip()

            if val in ("", "1"):
                ch_id, ch_name, ch_comm = b_id, b_name, b_comm
            elif val == "2" and len(matches) >= 2:
                ch_id, ch_name, ch_comm = matches[1][0], matches[1][1], matches[1][3]
            elif val == "3" and len(matches) >= 3:
                ch_id, ch_name, ch_comm = matches[2][0], matches[2][1], matches[2][3]
            elif val == "0":
                ch_id, ch_name, ch_comm = "25636737", "Ручний інструмент", 7.0
            elif re.match(r"^\d{5,}$", val):
                ch_id    = val
                found    = next(((n, c) for rid, n, c in rz_cats if rid == val), None)
                ch_name  = found[0] if found else val
                ch_comm  = found[1] if found else 7.0
            else:
                ch_id, ch_name, ch_comm = b_id, b_name, b_comm

            comm_in = input(f"    {C.CYAN}?{C.RESET} Комісія [{C.DIM}{ch_comm}%{C.RESET}]: ").strip()
            if comm_in:
                try:
                    ch_comm = float(comm_in)
                except ValueError:
                    pass

            mappings[cat_id] = {
                "supplier_name": cat_name,
                "rz_id": ch_id, "rz_name": ch_name, "commission": ch_comm,
            }

            if i % 5 == 0:
                self.state["mappings"] = mappings
                self._save()

        self.state["mappings"] = mappings
        mapped_real = sum(1 for v in mappings.values() if v.get("rz_id") != "25636737")
        self._mark_done(3)
        ok(f"Маппінг завершено: {mapped_real}/{total} категорій в реальних rz_id")

    # ── STEP 4: Generate XML ────────────────────────────────────────────────────

    def step4_generate_xml(self):
        if self._done(4):
            ok(f"Крок 4 пропущено — XML: {self.state.get('output_xml')}")
            return

        self.header(4, "Генерація XML")

        fmt       = self.state["feed_format"]
        code      = self.state["code"]
        mappings  = self.state.get("mappings", {})
        field_map = self.state.get("field_map", {})
        out_file  = os.path.join(REPO_ROOT, "data", f"{code}_rozetka.xml")

        info("Завантажую фід для генерації XML...")
        content = load_feed_bytes(self.state["feed_url"], fmt)
        root    = parse_xml_bytes(content, fmt)
        struct  = detect_structure(root)

        info(f"Генерую {out_file}...")
        stats = generate_xml(root, struct, mappings, field_map, out_file, self.state["name"])

        print(f"\n  {C.BOLD}Результат:{C.RESET}")
        ok(f"Офферів:   {stats['total']}")
        ok(f"Категорій: {stats['categories']}")
        info(f"Пропущено: {stats['skipped']} (немає в наявності / ціна=0 / дублі)")
        ok(f"Збережено: {out_file}")

        self.state["output_xml"]  = out_file
        self.state["xml_stats"]   = stats
        self._mark_done(4)

    # ── STEP 5: Validate ────────────────────────────────────────────────────────

    def step5_validate(self):
        if self._done(5):
            ok("Крок 5 пропущено — валідація вже виконана")
            return

        self.header(5, "Валідація XML")

        xml_path = self.state.get("output_xml")
        if not xml_path or not os.path.exists(xml_path):
            err("XML файл не знайдено. Спочатку виконайте крок 4.")
            sys.exit(1)

        info("Запускаю tools/rozetka_xml_validator.py...")
        print()
        result = subprocess.run([sys.executable, VALIDATOR, "--no-xlsx", xml_path])
        print()

        self.state["validation_ok"] = result.returncode == 0
        self._mark_done(5)

        if result.returncode == 0:
            ok("Валідація успішна — немає структурних помилок")
        else:
            warn("Є структурні помилки (деталі вище)")

    # ── STEP 6: Save to DB ──────────────────────────────────────────────────────

    def step6_save_to_db(self):
        if self._done(6):
            ok("Крок 6 пропущено — дані вже в БД")
            return

        self.header(6, "Збереження в базу даних")

        try:
            ensure_tables()
        except Exception as e:
            warn(f"БД недоступна: {e}. Пропускаю крок 6.")
            self._mark_done(6)
            return

        code     = self.state["code"]
        mappings = self.state.get("mappings", {})

        try:
            conn = get_db()
            cur  = conn.cursor()

            cur.execute("""
                INSERT INTO suppliers (code, name, feed_url, feed_format, marketplace, status)
                VALUES (%s, %s, %s, %s, %s, 'active')
                ON CONFLICT (code) DO UPDATE SET
                    name=EXCLUDED.name, feed_url=EXCLUDED.feed_url,
                    feed_format=EXCLUDED.feed_format, marketplace=EXCLUDED.marketplace
            """, (code, self.state["name"], self.state["feed_url"],
                  self.state["feed_format"], self.state["marketplace"]))
            ok(f"suppliers: '{self.state['name']}' ({code}) збережено")

            saved = 0
            for cat_id, m in mappings.items():
                cur.execute("""
                    INSERT INTO supplier_category_map
                        (supplier_code, supplier_category_id, supplier_category_name,
                         rz_id, rz_name, commission_pct)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (supplier_code, supplier_category_id) DO UPDATE SET
                        rz_id=EXCLUDED.rz_id, rz_name=EXCLUDED.rz_name,
                        commission_pct=EXCLUDED.commission_pct
                """, (code, cat_id, m.get("supplier_name",""),
                      m.get("rz_id","25636737"), m.get("rz_name",""),
                      m.get("commission", 7.0)))
                saved += 1

            conn.commit()
            cur.close()
            conn.close()
            ok(f"supplier_category_map: {saved} маппінгів збережено")

        except Exception as e:
            err(f"Помилка запису в БД: {e}")

        self._mark_done(6)

    # ── STEP 7: Report ──────────────────────────────────────────────────────────

    def step7_report(self):
        self.header(7, "Підсумковий звіт")

        code      = self.state.get("code", "?")
        name      = self.state.get("name", "?")
        products  = self.state.get("products_count", 0)
        mappings  = self.state.get("mappings", {})
        xml_stats = self.state.get("xml_stats", {})
        out_xml   = self.state.get("output_xml", "?")
        val_ok    = self.state.get("validation_ok", False)

        mapped_real  = sum(1 for v in mappings.values() if v.get("rz_id") != "25636737")
        mapped_total = len(mappings)

        val_str = f"{C.GREEN}✓ OK{C.RESET}" if val_ok else f"{C.YELLOW}⚠ є попередження{C.RESET}"

        print(f"  {'─'*54}")
        print(f"  {C.BOLD}Постачальник   :{C.RESET} {name} ({code})")
        print(f"  {C.BOLD}Фід            :{C.RESET} {self.state.get('feed_url','?')[:52]}")
        print(f"  {C.BOLD}Товарів у фіді :{C.RESET} {products:,}")
        print(f"  {C.BOLD}Категорій      :{C.RESET} {mapped_real}/{mapped_total} в реальних rz_id")
        print(f"  {C.BOLD}Офферів у XML  :{C.RESET} {xml_stats.get('total','?')}")
        print(f"  {C.BOLD}XML файл       :{C.RESET} {out_xml}")
        print(f"  {C.BOLD}Валідація      :{C.RESET} {val_str}")
        print(f"  {'─'*54}")

        print(f"\n  {C.BOLD}{C.CYAN}Команди для подальшої роботи:{C.RESET}")
        print(f"  {C.DIM}# Продовжити onboarding з будь-якого кроку:{C.RESET}")
        print(f"    python3 tools/supplier_onboarding.py --resume {code} --step 3")
        print(f"\n  {C.DIM}# Запустити валідатор:{C.RESET}")
        print(f"    python3 tools/rozetka_xml_validator.py {out_xml}")
        print(f"\n  {C.DIM}# Повний pipeline Катрана (якщо постачальник = katran):{C.RESET}")
        print(f"    python3 tools/katran_pipeline.py --categories ALL --push")

        print(f"\n  {C.DIM}Прогрес збережено: {self.progress_file}{C.RESET}\n")

        self._mark_done(7)
        self._save()

    # ── Run ──────────────────────────────────────────────────────────────────────

    def run(self, start_from=1):
        steps = [
            self.step1_basic_info,
            self.step2_analyze_feed,
            self.step3_category_mapping,
            self.step4_generate_xml,
            self.step5_validate,
            self.step6_save_to_db,
            self.step7_report,
        ]
        for i, fn in enumerate(steps, 1):
            if i < start_from:
                continue
            fn()


# ─── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Wizard для підключення нового постачальника в дропшипінг-систему"
    )
    parser.add_argument(
        "--resume", metavar="CODE",
        help="Продовжити онбординг по коду постачальника (напр. katran)"
    )
    parser.add_argument(
        "--step", type=int, default=1, choices=range(1, 8),
        help="Почати з конкретного кроку 1-7"
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Вимкнути кольоровий вивід (ANSI)"
    )
    args = parser.parse_args()

    print(f"\n{C.BOLD}{C.BLUE}{'='*58}{C.RESET}")
    print(f"{C.BOLD}{C.BLUE}  Supplier Onboarding Wizard — Dropshipping Agent System{C.RESET}")
    print(f"{C.BOLD}{C.BLUE}  Версія: 2026-06-07{C.RESET}")
    print(f"{C.BOLD}{C.BLUE}{'='*58}{C.RESET}")

    wizard = SupplierOnboarding(
        supplier_code=args.resume,
        no_color=args.no_color,
    )
    wizard.run(start_from=args.step)


if __name__ == "__main__":
    main()
