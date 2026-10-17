#!/usr/bin/env python3
"""B2B-портал Юг-Контракт: вхід із SMS і розвідка того, що можна автоматизувати.

ЧОМУ ТАК СКЛАДНО. Портал вимагає SMS-підтвердження при кожному новому
вході, і там стоїть recaptcha. Тому: входимо один раз, зберігаємо сесію
у файл, далі працюємо нею — без SMS і без повторного логіна.

Код із SMS скрипт НЕ вигадує і не чекає з консолі: власник кладе його у
файл `/tmp/yug_sms.txt`, скрипт бачить і продовжує. Так код не потрапляє
ні в історію команд, ні в логи.

    venv/bin/python tools/yug_portal.py --вхід      # перший раз, з SMS
    venv/bin/python tools/yug_portal.py --огляд     # далі, збереженою сесією
"""
import argparse
import json
import os
import re
import sys
import time

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
СЕСІЯ = os.path.join(BASE, 'data', 'yug_session.json')
SMS = '/tmp/yug_sms.txt'
ПОРТАЛ = 'https://b2b.yugcontract.ua'


def чекати_код(хв=10):
    """Код із SMS — з файлу. Повертає рядок або None."""
    кінець = time.time() + хв * 60
    print(f'чекаю код у {SMS} (до {хв} хв)…', flush=True)
    while time.time() < кінець:
        if os.path.exists(SMS):
            код = re.sub(r'\D', '', open(SMS, encoding='utf-8').read())
            if len(код) >= 4:
                os.remove(SMS)
                return код
        time.sleep(3)
    return None


def вхід(page):
    page.goto(f'{ПОРТАЛ}/', wait_until='domcontentloaded', timeout=60000)
    page.wait_for_timeout(3000)
    page.locator('input[name="login"]').first.fill(os.environ['YUG_LOGIN'])
    page.locator('input[name="password"]').first.fill(os.environ['YUG_PASS'])
    page.locator('button:has-text("УВІЙТИ"), button[type="submit"]').first.click()
    page.wait_for_timeout(6000)
    if 'SMS' in page.inner_text('body') or 'смс' in page.inner_text('body').lower():
        код = чекати_код()
        if not код:
            sys.exit('коду так і не було — вхід не завершено')
        page.locator('input[type="text"], input[type="tel"]').first.fill(код)
        page.locator('button:has-text("УВІЙТИ"), button[type="submit"]').first.click()
        page.wait_for_timeout(8000)
    return 'login' not in page.url


def огляд(page):
    print('URL:', page.url)
    текст = re.sub(r'\n{2,}', '\n', page.inner_text('body')[:1200])
    print('--- головна ---'); print(текст)
    посилання = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(a => a.href)")
    цікаві = sorted({u for u in посилання
                     if re.search(r'price|прайс|export|xml|csv|yml|api|order|catalog|zamov', u, re.I)})
    print('--- розділи, цікаві для автоматизації ---')
    for u in цікаві[:25]:
        print('  ', u)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--вхід', action='store_true', dest='вхід')
    ap.add_argument('--огляд', action='store_true', dest='огляд')
    a = ap.parse_args()
    if not (os.getenv('YUG_LOGIN') and os.getenv('YUG_PASS')):
        sys.exit('немає YUG_LOGIN / YUG_PASS у .env')
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        є_сесія = os.path.exists(СЕСІЯ)
        ctx = b.new_context(locale='uk-UA',
                            storage_state=СЕСІЯ if є_сесія and not a.вхід else None)
        page = ctx.new_page()
        апі = []
        page.on('request', lambda r: апі.append(r.url)
                if re.search(r'/api/', r.url) and 'recaptcha' not in r.url else None)
        if a.вхід or not є_сесія:
            if not вхід(page):
                sys.exit('вхід не вдався')
            ctx.storage_state(path=СЕСІЯ)
            print('сесію збережено →', СЕСІЯ)
        else:
            page.goto(f'{ПОРТАЛ}/', wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(5000)
        огляд(page)
        print('--- звернення порталу до власного API ---')
        for u in sorted(set(апі))[:20]:
            print('  ', u)
        b.close()


if __name__ == '__main__':
    main()
