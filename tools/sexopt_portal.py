#!/usr/bin/env python3
"""Кабінет постачальника SexOpt: вхід, пошук, ціни дропшипера.

Навіщо. Пошук на sexopt.com.ua доступний **лише після входу** («поиск по
сайту доступен после регистрации»), і саме там видно наші закупівельні
ціни, яких немає у вивантаженні. Без цього інструмента власник лишається
вузьким місцем: питання на кшталт «яка маржа в цієї позиції» вимагають
ручного перегляду сотень карток.

Пароль у коді не зберігається — читається з .env (SEXOPT_LOGIN,
SEXOPT_PASSWORD, SEXOPT_URL). Файл у .gitignore, перевірено.

Сесія зберігається у профілі Camoufox між запусками, тому повторний вхід
не потрібен на кожен запит — сайт не має причин бачити нас як бота.

Запуск:
    python3 tools/sexopt_portal.py --login          # перевірити вхід
    python3 tools/sexopt_portal.py --search "tenga egg"
    python3 tools/sexopt_portal.py --sku SO1446
"""
import argparse
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)

URL = os.getenv('SEXOPT_URL', 'https://sexopt.com.ua')
LOGIN = os.getenv('SEXOPT_LOGIN', '')
PASSWORD = os.getenv('SEXOPT_PASSWORD', '')
PROFILE = os.path.join(BASE_DIR, '.cache', 'sexopt_profile')


def open_browser():
    """Звичайний, НЕ постійний контекст.

    З persistent_context клік по «Вход / Регистрация» стабільно давав
    TimeoutError, тоді як у тому самому коді без профілю він працює.
    Вхід займає близько десяти секунд на запуск — прийнятна ціна за те,
    що інструмент взагалі працює.
    """
    from camoufox.sync_api import Camoufox
    return Camoufox(headless=True, humanize=True, geoip=True, locale='uk-UA')


def logged_in(page) -> bool:
    """Ознака входу — зник напис «поиск доступен после регистрации»."""
    html = page.content().lower()
    return 'доступен после регистрации' not in html


def do_login(page) -> bool:
    if not LOGIN or not PASSWORD:
        sys.exit('SEXOPT_LOGIN / SEXOPT_PASSWORD не задані в .env')
    page.goto(URL, wait_until='domcontentloaded')
    page.wait_for_timeout(3500)
    if logged_in(page):
        return True
    # Форма входу вже в DOM (модальне вікно), клікати посилання не треба.
    # Поля звуться user[email] / user[pass]; та сама пара імен є й у формі
    # РЕЄСТРАЦІЇ нижче, тому беремо саме перше входження — форму входу.
    # Звичайний клік по посиланню падав із TimeoutError: на головній його
    # перекриває банер-карусель, і Playwright не вважає елемент придатним
    # для кліку. Тому по черзі: звичайний клік, примусовий, і нарешті
    # прямий виклик через DOM — він не залежить від перекриття.
    opened = False
    for how in ('normal', 'force', 'js'):
        try:
            link = page.locator('text=Вход / Регистрация').first
            if how == 'normal':
                link.click(timeout=6000)
            elif how == 'force':
                link.click(timeout=6000, force=True)
            else:
                page.evaluate(
                    "[...document.querySelectorAll('a')]"
                    ".find(a => a.textContent.includes('Вход'))?.click()")
            page.wait_for_timeout(2500)
            if page.locator('input[name="user[pass]"]').first.is_visible() or \
                    any(page.locator('input[name="user[pass]"]').nth(i).is_visible()
                        for i in range(page.locator('input[name="user[pass]"]').count())):
                opened = True
                break
        except Exception:
            continue
    if not opened:
        print('вікно входу не відкрилось')
        return False
    # На сторінці ТРИ поля user[email] (вхід, реєстрація, відновлення) і всі
    # приховані до кліку. Після відкриття видиме рівно одне — беремо його за
    # видимістю, а не за порядком: `.first` цілив у приховане поле форми
    # реєстрації й давав TimeoutError.
    def visible(name):
        loc = page.locator(f'input[name="{name}"]')
        for i in range(loc.count()):
            if loc.nth(i).is_visible():
                return loc.nth(i)
        return None

    email, pwd = visible('user[email]'), visible('user[pass]')
    if not email or not pwd:
        print('видимих полів входу немає')
        return False
    email.fill(LOGIN)
    pwd.fill(PASSWORD)
    pwd.press('Enter')
    page.wait_for_timeout(6000)
    return logged_in(page)


def search(page, query: str, limit=12) -> list:
    page.goto(f'{URL}/catalog/search/?q=' + query.replace(' ', '%20'),
              wait_until='domcontentloaded')
    page.wait_for_timeout(4000)
    page.mouse.wheel(0, 6000)
    page.wait_for_timeout(2000)
    html = page.content()
    # Структура карток невідома наперед — витягаємо пари «назва + ціна»
    items = re.findall(
        r'<a[^>]*href="(/[^"]+)"[^>]*>\s*([^<]{12,90})</a>.{0,400}?([\d\s]{2,9})\s*(?:грн|₴)',
        html, re.S)
    out = []
    for href, name, price in items[:limit]:
        out.append({'url': URL + href, 'name': re.sub(r'\s+', ' ', name).strip(),
                    'price': re.sub(r'\D', '', price)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--login', action='store_true')
    ap.add_argument('--search')
    ap.add_argument('--sku')
    a = ap.parse_args()

    with open_browser() as br:
        page = br.new_page()
        page.set_default_timeout(60000)
        ok = do_login(page)
        print('вхід:', 'успішно' if ok else 'НЕ ВДАЛОСЯ')
        if not ok or a.login:
            print('title:', page.title()[:70])
            return
        q = a.search or a.sku
        if not q:
            return
        rows = search(page, q)
        print(f'знайдено: {len(rows)}')
        for r in rows:
            print(f"   {r['price']:>7} грн  {r['name'][:60]}")
            print(f"            {r['url'][:88]}")


if __name__ == '__main__':
    main()
