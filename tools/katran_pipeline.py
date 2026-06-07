#!/usr/bin/env python3
"""
tools/katran_pipeline.py — Автоматичний pipeline генерації XML фіду Катрана.

Usage:
  python3 tools/katran_pipeline.py --categories ALL
  python3 tools/katran_pipeline.py --categories 80158,237815,80011
  python3 tools/katran_pipeline.py --categories ALL --push
  python3 tools/katran_pipeline.py --categories ALL --output-dir /tmp/katran_pipeline/
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from xml.etree import ElementTree as ET

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
from loguru import logger

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

# import shared logic from katran_category_xml
from tools.katran_category_xml import (
    SKIP_CATEGORIES,
    generate_category_xml,
    get_category_map,
    get_katran_feed,
)

REPO_ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR   = os.path.join(REPO_ROOT, "tools", "rozetka_xml_validator.py")
OUTPUT_XML  = os.path.join(REPO_ROOT, "data", "katran_rozetka.xml")


# ─── validation helpers ───────────────────────────────────────────────────────

def run_validator(xml_path: str) -> dict:
    result = subprocess.run(
        [sys.executable, VALIDATOR, "--no-xlsx", xml_path],
        capture_output=True, text=True
    )
    errors   = result.stdout.count("ERR=") and _extract_count(result.stdout, "ERR")
    warnings = _extract_count(result.stdout, "WARN")
    ok = result.returncode == 0
    return {"ok": ok, "errors": errors, "warnings": warnings, "output": result.stdout}


def _extract_count(text: str, label: str) -> int:
    import re
    m = re.search(rf"Помилок:\s+(\d+)", text)
    if label == "ERR" and m:
        return int(m.group(1))
    m2 = re.search(rf"Попереджень:\s+(\d+)", text)
    if label == "WARN" and m2:
        return int(m2.group(1))
    return 0


# ─── merge ────────────────────────────────────────────────────────────────────

def merge_xmls(xml_files: list, output_path: str) -> int:
    cats: dict   = {}
    offers: list = []
    seen: set    = set()

    for f in sorted(xml_files):
        tree = ET.parse(f)
        for cat in tree.findall(".//category"):
            cid = cat.get("id")
            if cid not in cats:
                cats[cid] = ET.tostring(cat, encoding="unicode")
        for offer in tree.findall(".//offer"):
            oid = offer.get("id")
            if oid not in seen:
                seen.add(oid)
                offers.append(ET.tostring(offer, encoding="unicode"))

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{now}">',
        "  <shop>",
        "    <name>HYPER_STORE</name>",
        "    <company>3721108</company>",
        "    <url>https://seller.rozetka.com.ua/</url>",
        "    <currencies><currency id=\"UAH\" rate=\"1\"/></currencies>",
        "    <categories>",
    ] + ["      " + c for c in cats.values()] + [
        "    </categories>",
        "    <offers>",
    ] + ["      " + o for o in offers] + [
        "    </offers>",
        "  </shop>",
        "</yml_catalog>",
    ]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return len(offers)


# ─── git push ─────────────────────────────────────────────────────────────────

def git_push(message: str) -> bool:
    for cmd in [
        ["git", "-C", REPO_ROOT, "add", "-f", OUTPUT_XML],
        ["git", "-C", REPO_ROOT, "commit", "-m", message],
        ["git", "-C", REPO_ROOT, "pull", "--rebase"],
        ["git", "-C", REPO_ROOT, "push"],
    ]:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            logger.error(f"git error: {result.stderr.strip()}")
            return False
    return True


# ─── main pipeline ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Автоматичний pipeline генерації XML фіду Катрана для Розетки"
    )
    parser.add_argument(
        "--categories", default="ALL",
        help="rz_ids через кому або ALL (default: ALL)"
    )
    parser.add_argument(
        "--output-dir", default="/tmp/katran_pipeline/",
        help="Директорія для окремих XML файлів категорій"
    )
    parser.add_argument(
        "--feed-url", default=None,
        help="URL фіду (default: KATRAN_FEED_URL_STOCK з .env)"
    )
    parser.add_argument(
        "--push", action="store_true",
        help="Запушити data/katran_rozetka.xml на GitHub після генерації"
    )
    args = parser.parse_args()

    if args.feed_url:
        os.environ["KATRAN_FEED_URL_STOCK"] = args.feed_url

    os.makedirs(args.output_dir, exist_ok=True)

    # ── step 1: отримати список категорій ────────────────────────────────────
    logger.info("[Pipeline] Крок 1: Отримую список категорій...")
    if args.categories.upper() == "ALL":
        cat_map = get_category_map()
        all_rz_ids = list({v["rz_id"] for v in cat_map.values()} - SKIP_CATEGORIES)
        if not all_rz_ids:
            logger.error("Жодної категорії не знайдено в БД")
            sys.exit(1)
        logger.info(f"[Pipeline] Категорій з БД: {len(all_rz_ids)}")
    else:
        all_rz_ids = [r.strip() for r in args.categories.split(",") if r.strip()]
        logger.info(f"[Pipeline] Категорії з аргументу: {all_rz_ids}")

    # ── step 2: завантажити фід один раз ─────────────────────────────────────
    logger.info("[Pipeline] Крок 2: Завантажую фід Катрана...")
    feed_root = get_katran_feed()
    logger.success(f"[Pipeline] Фід завантажено")

    # ── step 3: генерувати XML для кожної категорії ───────────────────────────
    logger.info(f"[Pipeline] Крок 3: Генерую XML для {len(all_rz_ids)} категорій...")
    results  = []
    xml_files = []

    for rz_id in sorted(all_rz_ids):
        out_file = os.path.join(args.output_dir, f"katran_cat_{rz_id}.xml")
        try:
            stats = generate_category_xml([rz_id], out_file)
            # ── step 4: валідатор на кожному файлі ───────────────────────────
            val = run_validator(out_file)
            status = "ok" if val["ok"] and val["errors"] == 0 else (
                "warn" if val["errors"] == 0 else "error"
            )
            rec = {
                "rz_id":        rz_id,
                "name":         list(stats["cat_names"].values())[0] if stats["cat_names"] else "?",
                "offers_count": stats["total"],
                "errors":       val["errors"],
                "warnings":     val["warnings"],
                "status":       status,
                "skipped_sale": stats.get("skipped_sale", 0),
                "skipped_acc":  stats.get("skipped_accessory", 0),
            }
            results.append(rec)
            if stats["total"] > 0:
                xml_files.append(out_file)
            logger.info(
                f"[Pipeline] {rz_id:12} | {stats['total']:4d} офферів | "
                f"ERR={val['errors']} WARN={val['warnings']} | {status}"
            )
        except Exception as e:
            logger.error(f"[Pipeline] {rz_id} — помилка: {e}")
            results.append({
                "rz_id": rz_id, "name": "?", "offers_count": 0,
                "errors": 1, "warnings": 0, "status": "error",
                "skipped_sale": 0, "skipped_acc": 0,
            })

    # ── step 5: зберегти JSON звіт ────────────────────────────────────────────
    report_path = os.path.join(args.output_dir, "pipeline_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"[Pipeline] JSON звіт: {report_path}")

    # ── step 6: зведена таблиця ───────────────────────────────────────────────
    total_offers = sum(r["offers_count"] for r in results)
    total_errors = sum(r["errors"] for r in results)
    total_warns  = sum(r["warnings"] for r in results)
    ok_cats      = sum(1 for r in results if r["status"] == "ok")
    warn_cats    = sum(1 for r in results if r["status"] == "warn")
    err_cats     = sum(1 for r in results if r["status"] == "error")

    print(f"\n{'='*72}")
    print(f"  KATRAN PIPELINE — Зведена таблиця  ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"{'='*72}")
    print(f"  {'rz_id':<12} {'Категорія':<30} {'Офф':>5} {'ERR':>4} {'WARN':>5}  Статус")
    print(f"  {'-'*12} {'-'*30} {'-'*5} {'-'*4} {'-'*5}  {'------'}")
    for r in sorted(results, key=lambda x: -x["offers_count"]):
        status_icon = "✅" if r["status"] == "ok" else ("⚠️ " if r["status"] == "warn" else "❌")
        print(
            f"  {r['rz_id']:<12} {r['name'][:30]:<30} {r['offers_count']:>5} "
            f"{r['errors']:>4} {r['warnings']:>5}  {status_icon}"
        )
    print(f"{'─'*72}")
    print(f"  РАЗОМ: {len(results)} категорій | {total_offers} офферів | "
          f"ERR={total_errors} WARN={total_warns}")
    print(f"  ✅ OK: {ok_cats}  ⚠️  WARN: {warn_cats}  ❌ ERR: {err_cats}")

    # ── step 7: merge ─────────────────────────────────────────────────────────
    if not xml_files:
        logger.error("[Pipeline] Немає файлів для merge")
        sys.exit(1)

    logger.info(f"\n[Pipeline] Крок 7: Merge {len(xml_files)} файлів → {OUTPUT_XML}...")
    merged_count = merge_xmls(xml_files, OUTPUT_XML)
    print(f"\n  Merged XML: {OUTPUT_XML}")
    print(f"  Категорій: {len(xml_files)} | Офферів: {merged_count}")

    # ── step 8: валідатор на merged ───────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  Крок 8: Валідатор на merged XML...")
    print(f"{'─'*72}\n")
    sys.stdout.flush()
    val_final = subprocess.run(
        [sys.executable, VALIDATOR, "--no-xlsx", OUTPUT_XML]
    )

    # ── step 9: git push ──────────────────────────────────────────────────────
    if args.push:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = f"sync: katran pipeline {now_str} ({merged_count} offers, {len(xml_files)} cats)"
        print(f"\n[Pipeline] Крок 9: git push...")
        if git_push(msg):
            print("  PUSH_OK ✅")
        else:
            print("  PUSH_FAILED ❌")
            sys.exit(1)

    sys.exit(val_final.returncode)


if __name__ == "__main__":
    main()
