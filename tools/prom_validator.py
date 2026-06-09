#!/usr/bin/env python3
"""
tools/prom_validator.py — валідатор XML/XLSX для Prom.ua

Usage:
  python3 tools/prom_validator.py feed.xml
  python3 tools/prom_validator.py feed.xml --no-warn
  python3 tools/prom_validator.py feed.xml --out report.txt
"""

import argparse
import os
import re
import sys
from collections import Counter
from xml.etree import ElementTree as ET


PROMO_WORDS = ["акція", "знижка", "знижк", "безкоштовн", "найкраща ціна"]
NAME_MAX    = 110
NAME_WARN   = 80

AVAILABLE_TRUE  = {"true", "1", "yes", "так", "+", "в наявності"}
AVAILABLE_KNOWN = AVAILABLE_TRUE | {"false", "0", "no", "ні", "-", "немає", "під замовлення"}


# ─── parsers ──────────────────────────────────────────────────────────────────

def parse_xml(path: str) -> list:
    tree = ET.parse(path)
    root = tree.getroot()
    items = []
    for o in root.findall(".//offer"):
        pics = [p.text or "" for p in o.findall("picture") if p.text]
        items.append({
            "id":                 o.get("id") or o.findtext("id") or "",
            "name":               o.findtext("name") or o.findtext("name_ua") or "",
            "available":          o.get("available") or o.findtext("available") or "",
            "price":              o.findtext("price") or "",
            "portal_category_id": o.findtext("portal_category_id") or "",
            "vendor":             o.findtext("vendor") or "",
            "description":        o.findtext("description") or o.findtext("description_ua") or "",
            "picture":            ",".join(pics),
        })
    return items


def parse_xlsx(path: str) -> list:
    try:
        import openpyxl
    except ImportError:
        print("ERROR: openpyxl не встановлено. pip install openpyxl", file=sys.stderr)
        sys.exit(1)

    ALIASES = {
        "id":                 ["id", "ід", "код", "external_id"],
        "name":               ["назва", "name", "назва товару", "найменування"],
        "available":          ["наявність", "available", "доступність"],
        "price":              ["ціна", "price", "ціна, грн", "ціна грн"],
        "portal_category_id": ["портал категорія", "portal_category_id", "категорія порталу"],
        "vendor":             ["виробник", "vendor", "бренд", "brand"],
        "description":        ["опис", "description", "опис товару"],
        "picture":            ["зображення", "picture", "фото"],
    }

    wb   = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [str(h).strip().lower() if h else "" for h in rows[0]]
    col_map = {}
    for field, aliases in ALIASES.items():
        for i, h in enumerate(headers):
            if any(a in h for a in aliases):
                col_map[field] = i
                break

    items = []
    for row in rows[1:]:
        if all(c is None for c in row):
            continue
        def get(f):
            i = col_map.get(f)
            return str(row[i]).strip() if i is not None and row[i] is not None else ""
        items.append({f: get(f) for f in ALIASES})
    return items


# ─── validation ───────────────────────────────────────────────────────────────

def _is_all_caps(name: str) -> bool:
    words = name.split()
    if len(words) <= 3:
        return False
    upper = [w for w in words
             if re.search(r'[А-ЯЁІЇЄA-Z]', w) and not re.search(r'[а-яёіїєa-z]', w)]
    return len(upper) > 3


def validate(item: dict) -> tuple:
    errors   = []
    warnings = []
    name      = item["name"].strip()
    name_low  = name.lower()
    available = item["available"].strip().lower()

    # ── ERR ──────────────────────────────────────────────────────────────────
    if not item["id"].strip():
        errors.append("відсутній id")

    if not name:
        errors.append("відсутня назва")
    else:
        if not re.search(r'[А-ЯҐЄІЇа-яґєіїA-Za-z]', name):
            errors.append("назва без літер (тільки цифри/спецсимволи)")
        if _is_all_caps(name):
            errors.append("назва ALL CAPS (більше 3 слів)")
        if len(name) > NAME_MAX:
            errors.append(f"назва {len(name)} символів (макс {NAME_MAX})")
        for pw in PROMO_WORDS:
            if pw in name_low:
                errors.append(f"рекламне слово: «{pw}»")
                break

    if not item["portal_category_id"].strip():
        errors.append("відсутній portal_category_id")

    if available in AVAILABLE_TRUE:
        price_str = item["price"].strip()
        try:
            if not price_str or float(price_str.replace(",", ".")) <= 0:
                errors.append("ціна = 0 або відсутня при available=true")
        except ValueError:
            errors.append(f"ціна не є числом: «{price_str[:20]}»")

    # ── WARN ─────────────────────────────────────────────────────────────────
    if not item["vendor"].strip():
        warnings.append("відсутній vendor/brand")
    if not item["description"].strip():
        warnings.append("відсутній опис")
    if not item["picture"].strip():
        warnings.append("відсутні фото")
    if name and NAME_WARN < len(name) <= NAME_MAX:
        warnings.append(f"назва {len(name)} символів (ліміт {NAME_MAX})")
    if available and available not in AVAILABLE_KNOWN:
        warnings.append(f"незрозуміле available: «{available[:20]}»")

    return errors, warnings


# ─── report ───────────────────────────────────────────────────────────────────

def build_report(items: list, no_warn: bool) -> tuple:
    # pre-scan duplicate ids
    id_counts = Counter(i["id"].strip() for i in items if i["id"].strip())
    dup_ids   = {oid for oid, n in id_counts.items() if n > 1}

    results = []
    for item in items:
        errors, warnings = validate(item)
        oid = item["id"].strip()
        if oid in dup_ids:
            errors.insert(0, f"дублікат id «{oid}»")
        results.append({
            "id":    oid or "(немає)",
            "name":  (item["name"].strip() or "(немає)")[:60],
            "errs":  errors,
            "warns": warnings,
        })

    total     = len(results)
    err_items = [r for r in results if r["errs"]]
    wrn_items = [r for r in results if r["warns"]]
    n_errs    = sum(len(r["errs"])  for r in results)
    n_warns   = sum(len(r["warns"]) for r in results)
    valid_pct = round((total - len(err_items)) / total * 100) if total else 0

    lines = []
    SEP   = "=" * 64

    lines += [
        SEP,
        "  Prom.ua Validator",
        SEP,
        f"  Товарів        : {total}",
        f"  ERR            : {n_errs}  ({len(err_items)} товарів з помилками)",
    ]
    if not no_warn:
        lines.append(f"  WARN           : {n_warns}  ({len(wrn_items)} товарів з попередженнями)")
    lines += [
        f"  Валідних       : {total - len(err_items)} / {total}  ({valid_pct}%)",
        SEP,
    ]

    # errors
    if err_items:
        lines.append(f"\n  ПОМИЛКИ (перші 20 з {len(err_items)}):\n")
        for r in err_items[:20]:
            lines.append(f"  [{r['id']}] {r['name']}")
            for e in r["errs"]:
                lines.append(f"    ERR  {e}")

    # warnings
    if not no_warn and wrn_items:
        lines.append(f"\n  ПОПЕРЕДЖЕННЯ (перші 20 з {len(wrn_items)}):\n")
        for r in wrn_items[:20]:
            lines.append(f"  [{r['id']}] {r['name']}")
            for w in r["warns"]:
                lines.append(f"    WARN {w}")

    # top-10 most problematic
    top10 = sorted(
        [r for r in results if r["errs"] or r["warns"]],
        key=lambda r: len(r["errs"]) * 10 + len(r["warns"]),
        reverse=True,
    )[:10]
    if top10:
        lines.append(f"\n  ТОП-10 ПРОБЛЕМНИХ:\n")
        for r in top10:
            lines.append(
                f"  ERR={len(r['errs'])} WARN={len(r['warns'])}  [{r['id']}] {r['name']}"
            )

    lines += [
        f"\n{SEP}",
        "  ✗  ФАЙЛ МАЄ ПОМИЛКИ — потребує виправлення" if err_items
        else "  ✅  СТРУКТУРНИХ ПОМИЛОК НЕМАЄ",
        SEP,
    ]

    return "\n".join(lines), bool(err_items)


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Prom.ua XML/XLSX validator")
    ap.add_argument("file",      help="XML або XLSX файл")
    ap.add_argument("--no-warn", action="store_true", help="показувати тільки ERR")
    ap.add_argument("--out",     metavar="FILE",       help="зберегти звіт у файл")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print(f"Файл не знайдено: {args.file}", file=sys.stderr)
        sys.exit(1)

    ext = os.path.splitext(args.file)[1].lower()
    if ext in (".xlsx", ".xls"):
        items = parse_xlsx(args.file)
    elif ext in (".xml", ".yml"):
        items = parse_xml(args.file)
    else:
        print(f"Непідтримуваний формат: {ext}. Використовуйте .xml/.yml/.xlsx",
              file=sys.stderr)
        sys.exit(1)

    if not items:
        print("Товарів не знайдено у файлі.")
        sys.exit(0)

    report, has_errors = build_report(items, no_warn=args.no_warn)
    print(report)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nЗвіт збережено: {args.out}")

    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
