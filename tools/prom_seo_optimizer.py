#!/usr/bin/env python3
"""
prom_seo_optimizer.py — SEO-аудит товарів на Prom.ua.

Використання:
    python3 tools/prom_seo_optimizer.py
    python3 tools/prom_seo_optimizer.py --limit 500 --out my_report.csv
    python3 tools/prom_seo_optimizer.py --top 30
"""

import argparse
import csv
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

# ── Константи ─────────────────────────────────────────────

PROM_BASE_URL = "https://my.prom.ua/api/v1"
PROM_TOKEN    = os.getenv("PROM_API_TOKEN", "")
PAGE_LIMIT    = 100          # максимум для Prom API

NAME_MIN  = 50
NAME_MAX  = 150
DESC_MIN  = 300
PHOTO_MIN = 3

PRIORITY_WEIGHTS = {"high": 3, "medium": 2, "low": 1}


# ── Структури ─────────────────────────────────────────────

@dataclass
class Problem:
    issue: str
    priority: str  # high | medium | low


@dataclass
class ProductReport:
    product_id: int
    name: str
    problems: list[Problem] = field(default_factory=list)

    @property
    def score(self) -> int:
        """Загальна вага проблем (чим більше — тим гірше)."""
        return sum(PRIORITY_WEIGHTS[p.priority] for p in self.problems)

    @property
    def worst_priority(self) -> str:
        if any(p.priority == "high" for p in self.problems):
            return "high"
        if any(p.priority == "medium" for p in self.problems):
            return "medium"
        return "low"


# ── Prom API ──────────────────────────────────────────────

def prom_client() -> httpx.Client:
    if not PROM_TOKEN:
        logger.error("PROM_API_TOKEN не встановлено в .env")
        sys.exit(1)
    return httpx.Client(
        base_url=PROM_BASE_URL,
        headers={"Authorization": f"Bearer {PROM_TOKEN}"},
        timeout=30,
    )


def fetch_all_products(client: httpx.Client, max_products: int | None = None) -> list[dict]:
    """Завантажує всі товари через пагінацію page_from_id."""
    all_products: list[dict] = []
    last_id = 0

    while True:
        params: dict = {"limit": PAGE_LIMIT}
        if last_id:
            params["page_from_id"] = last_id

        resp = client.get("/products/list", params=params)
        if resp.status_code != 200:
            logger.error(f"Prom API error {resp.status_code}: {resp.text[:200]}")
            break

        data = resp.json()
        products = data.get("products", [])
        if not products:
            break

        all_products.extend(products)
        logger.info(f"  Завантажено {len(all_products)} товарів...")

        if len(products) < PAGE_LIMIT:
            break  # остання сторінка

        last_id = products[-1]["id"]

        if max_products and len(all_products) >= max_products:
            all_products = all_products[:max_products]
            break

    return all_products


# ── SEO-перевірки ─────────────────────────────────────────

def audit_product(product: dict) -> ProductReport:
    """Перевіряє один товар і повертає список проблем."""
    pid   = product.get("id", 0)
    name  = (product.get("name") or "").strip()
    desc  = (product.get("description") or "").strip()
    photos: list = product.get("images", []) or []
    attrs: list  = product.get("attributes", []) or []

    report = ProductReport(product_id=pid, name=name[:80] or f"<id={pid}>")

    # ── Назва ──────────────────────────────────────────────
    if not name:
        report.problems.append(Problem("Назва відсутня", "high"))
    elif len(name) < NAME_MIN:
        report.problems.append(Problem(
            f"Назва коротка ({len(name)} симв., мін. {NAME_MIN})", "high"
        ))
    elif len(name) > NAME_MAX:
        report.problems.append(Problem(
            f"Назва задовга ({len(name)} симв., макс. {NAME_MAX})", "medium"
        ))

    # ── Опис ───────────────────────────────────────────────
    if not desc:
        report.problems.append(Problem("Опис відсутній", "high"))
    elif len(desc) < DESC_MIN:
        report.problems.append(Problem(
            f"Опис короткий ({len(desc)} симв., мін. {DESC_MIN})", "high"
        ))

    # ── Фото ───────────────────────────────────────────────
    n_photos = len(photos)
    if n_photos == 0:
        report.problems.append(Problem("Фото відсутні", "high"))
    elif n_photos < PHOTO_MIN:
        report.problems.append(Problem(
            f"Мало фото ({n_photos}, мін. {PHOTO_MIN})", "medium"
        ))

    # ── Характеристики ─────────────────────────────────────
    if not attrs:
        report.problems.append(Problem("Характеристики не заповнені", "medium"))
    else:
        empty = sum(1 for a in attrs if not (a.get("value") or "").strip())
        if empty:
            report.problems.append(Problem(
                f"{empty} характеристик без значення", "low"
            ))

    return report


# ── Звіт ──────────────────────────────────────────────────

def write_csv(reports: list[ProductReport], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "назва", "проблема", "пріоритет"])
        for r in reports:
            if not r.problems:
                writer.writerow([r.product_id, r.name, "—", "ok"])
            else:
                for p in r.problems:
                    writer.writerow([r.product_id, r.name, p.issue, p.priority])


def print_top(reports: list[ProductReport], top_n: int) -> None:
    with_problems = [r for r in reports if r.problems]
    ranked = sorted(with_problems, key=lambda r: r.score, reverse=True)[:top_n]

    print(f"\n{'='*65}")
    print(f"  ТОП-{top_n} товарів що найбільше потребують покращення")
    print(f"{'='*65}")
    print(f"{'ID':>8}  {'Балів':>6}  {'Пріор.':>7}  Проблеми / Назва")
    print(f"{'-'*65}")
    for r in ranked:
        issues = ", ".join(p.issue for p in r.problems)
        print(f"{r.product_id:>8}  {r.score:>6}  {r.worst_priority:>7}  {issues}")
        print(f"{'':>8}  {'':>6}  {'':>7}  ↳ {r.name[:55]}")
    print(f"{'='*65}\n")


# ── CLI ───────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="SEO-аудит товарів Prom.ua")
    parser.add_argument("--limit", type=int, default=None,
                        help="Максимальна кількість товарів (за замовч.: всі)")
    parser.add_argument("--out", type=Path, default=Path("problems_report.csv"),
                        help="Шлях до вихідного CSV (за замовч.: problems_report.csv)")
    parser.add_argument("--top", type=int, default=20,
                        help="Кількість товарів у топ-списку (за замовч.: 20)")
    args = parser.parse_args()

    logger.info("Підключення до Prom API...")
    client = prom_client()

    logger.info("Завантаження товарів...")
    products = fetch_all_products(client, max_products=args.limit)
    logger.info(f"Завантажено {len(products)} товарів")

    if not products:
        logger.warning("Товарів не знайдено. Перевір PROM_API_TOKEN.")
        sys.exit(1)

    # Аудит
    logger.info("Аналіз SEO-якості...")
    reports = [audit_product(p) for p in products]

    ok      = sum(1 for r in reports if not r.problems)
    high    = sum(1 for r in reports if r.worst_priority == "high" and r.problems)
    medium  = sum(1 for r in reports if r.worst_priority == "medium" and r.problems)
    low     = sum(1 for r in reports if r.worst_priority == "low" and r.problems)

    # Запис CSV
    write_csv(reports, args.out)
    logger.success(f"Звіт збережено: {args.out}")

    # Топ-список
    print_top(reports, args.top)

    # Підсумок
    print(f"{'='*50}")
    print(f"  Всього товарів  : {len(reports)}")
    print(f"  Без проблем     : {ok}")
    print(f"  Критичні (high) : {high}")
    print(f"  Середні (medium): {medium}")
    print(f"  Незначні (low)  : {low}")
    print(f"  Звіт            : {args.out}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
