"""Збір товарів, брендів і продавців із категорій EVA.

Джерело URL — публічний sitemap (`eva_sitemap_fetch.py`). Сторінки категорій
і товарів не підпадають під заборони robots.txt EVA (`/catalog/`, `/*?`):
пошук і фільтри ми не чіпаємо, ходимо лише прямими адресами категорій.
"""
import json, re, sys, time
from pathlib import Path
from camoufox.sync_api import Camoufox

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "exports" / "eva_competitors.json"


def harvest(cat_urls, sellers_per_cat=8, pause=1.5):
    result = {}
    with Camoufox(headless=True, humanize=True, locale="uk-UA") as b:
        p = b.new_page()
        for cat in cat_urls:
            p.goto(cat, wait_until="domcontentloaded", timeout=90000)
            for _ in range(30):
                if "Just a moment" not in p.content():
                    break
                time.sleep(2)
            p.wait_for_timeout(6000)
            text = p.inner_text("body")
            hrefs = p.eval_on_selector_all("a[href]", "e => e.map(x => x.href)")
            prods = sorted({h for h in hrefs if re.search(r"/pr\d+/?$", h)})
            prices = [int(re.sub(r"\D", "", x)) for x in re.findall(r"(\d[\d\s ]{2,7})\s*₴", text)]
            sellers = {}
            for u in prods[:sellers_per_cat]:
                p.goto(u, wait_until="domcontentloaded", timeout=90000)
                p.wait_for_timeout(4000)
                t = p.inner_text("body")
                m = re.search(r"(?:Продавець|Продавец)[:\s]*([^\n]{2,50})", t)
                sellers[u] = (m.group(1).strip() if m else "?")
                time.sleep(pause)
            result[cat] = {
                "products_on_page": len(prods),
                "price_min": min(prices) if prices else None,
                "price_max": max(prices) if prices else None,
                "sellers": sellers,
            }
            print(f"[ok] {cat} товарів={len(prods)} продавці={set(sellers.values())}")
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("→", OUT)
    return result


if __name__ == "__main__":
    harvest(sys.argv[1:])
