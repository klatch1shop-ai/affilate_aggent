"""Читання публічного sitemap EVA через справжній браузер.

Чому саме sitemap: robots.txt EVA забороняє `/catalog/` і будь-що з `?`
(тобто пошук), але sitemap оголошений там сам — він опублікований для машин.
Беремо лише його і лише файли під /media/, які під заборону не підпадають.
"""
import gzip, re, sys, time
from pathlib import Path
from camoufox.sync_api import Camoufox

OUT = Path(__file__).resolve().parent.parent / "exports" / "eva_sitemap"
DISALLOWED = ("/catalog/", "?")


def allowed(url: str) -> bool:
    return not any(d in url.split("eva.ua", 1)[-1] for d in DISALLOWED)


def fetch(urls, pause=2.0):
    OUT.mkdir(parents=True, exist_ok=True)
    saved = {}
    with Camoufox(headless=True, humanize=True, locale="uk-UA") as b:
        page = b.new_page()
        for url in urls:
            if not allowed(url):
                print(f"[skip robots] {url}")
                continue
            name = url.rsplit("/", 1)[-1]
            dest = OUT / name
            if dest.exists() and dest.stat().st_size > 0:
                saved[name] = dest
                print(f"[cache] {name}")
                continue
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            for _ in range(30):
                body = page.content()
                if "Just a moment" not in body:
                    break
                time.sleep(2)
            # браузер обгортає XML у HTML-переглядач — витягуємо сирий текст
            raw = page.evaluate("() => document.documentElement.outerHTML")
            dest.write_text(raw, encoding="utf-8")
            saved[name] = dest
            print(f"[ok] {name}  {len(raw)} байт")
            time.sleep(pause)
    return saved


if __name__ == "__main__":
    fetch(sys.argv[1:])
