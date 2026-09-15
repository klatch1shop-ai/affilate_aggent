#!/usr/bin/env python3
"""CRM постачальника SexOpt (new.smtm.com.ua): вхід, кошик — з перевірених кроків (15.09.2026).

Скіл: .claude/skills/skill-32-supplier-crm-smtm/SKILL.md

    python3 tools/smtm_crm.py login              # увійти, зберегти сесію
    python3 tools/smtm_crm.py cart               # вміст кошика (з /inner/cart)
    python3 tools/smtm_crm.py add SX2730 2       # у кошику має стати рівно 2 шт

`add` задає КІНЦЕВУ кількість, а не додає. Якщо артикула ще немає в кошику,
скрипт натискає кнопку кошика в картці один раз (+1 шт) і не чіпає поле
кількості в картці: зміна цього поля сама додає товар (15.09 так вийшло
3 шт замість 2). Потім у кошику ставить потрібну кількість з клавіатури
(`fill()` сайт на React не помічає) і звіряє результат з `/inner/cart`.

Дані для входу — лише в .env (SMTM_URL, SMTM_LOGIN, SMTM_PASSWORD);
сесія — ~/.smtm/state.json (поза git, 600).
"""
import os
import sys

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'))
BASE = os.getenv('SMTM_URL', 'https://new.smtm.com.ua')
STATE = os.path.expanduser('~/.smtm/state.json')


class Crm:
    def __init__(self, p):
        self.b = p.chromium.launch()
        kw = {'storage_state': STATE} if os.path.exists(STATE) else {}
        self.ctx = self.b.new_context(viewport={'width': 1600, 'height': 1000}, locale='uk-UA', **kw)
        self.pg = self.ctx.new_page()

    def api(self, path):
        """GET внутрішнього API сайту. Потрібен заголовок x-auth-token = localStorage['token']
        (без нього сервер віддає HTML). Перехоплення відповідей було ненадійним (15.09)."""
        if not self.pg.url.startswith(BASE):
            self.open('/uk/catalog')
        return self.pg.evaluate("""async (path) => {
          const r = await fetch(path, {headers: {'x-auth-token': localStorage.getItem('token') || '',
                                                 'accept': 'application/json, text/plain, */*'}});
          if (!(r.headers.get('content-type') || '').includes('json')) return {__error: r.status};
          return await r.json();
        }""", path)

    def open(self, path):
        self.pg.goto(f'{BASE}{path}', wait_until='networkidle', timeout=60000)
        if '/login' in self.pg.url:
            self.login()
            self.pg.goto(f'{BASE}{path}', wait_until='networkidle', timeout=60000)
        self.pg.wait_for_timeout(1500)

    def login(self):
        pg = self.pg
        if '/login' not in pg.url:
            pg.goto(f'{BASE}/uk/login', wait_until='networkidle', timeout=60000)
        pg.fill('input[type=text]', os.getenv('SMTM_LOGIN', ''))
        pg.fill('input[type=password]', os.getenv('SMTM_PASSWORD', ''))
        pg.click('button[type=submit]')
        pg.wait_for_url(lambda u: '/login' not in u, timeout=30000)
        self.save()

    def save(self):
        os.makedirs(os.path.dirname(STATE), mode=0o700, exist_ok=True)
        self.ctx.storage_state(path=STATE)
        os.chmod(STATE, 0o600)

    def cart_items(self):
        """{артикул: (кількість, сума, agreement кошика)} з /inner/cart.

        agreement кошика — НЕ валюта товару (15.09: кошик «EUR», товар у USD).
        Суму до сплати брати з «Історії замовлень» / листа."""
        data = self.api('/uk/inner/cart?id=0&{}')
        if not isinstance(data, dict) or '__error' in data or 'cart' not in data:
            sys.exit(f'кошик не прочитано: {data if isinstance(data, dict) else type(data)}')
        out = {}
        for c in data['cart']:
            for it in c.get('cartItems') or []:
                out[it['product']['article']] = (float(it['amount']), it['sum'], c['agreement']['name'])
        return out

    def click_cart_button(self, sku):
        """Пошук за адресою → картка з точним артикулом → кнопка кошика один раз (+1 шт)."""
        pg = self.pg
        self.open(f'/uk/catalog?search-keyword={sku}')
        # до завантаження результатів лічильник показує весь каталог («24 з 13985»)
        pg.wait_for_function("() => { const m = document.body.innerText.match(/(\\d+) з (\\d+) товар/);"
                             " return m && m[1] === m[2]; }", timeout=45000)
        found = pg.evaluate("""(sku) => {
          const isLeaf = (e, t) => e.children.length === 0 && e.textContent.trim() === t;
          const cards = [];
          for (const leaf of [...document.querySelectorAll('body *')].filter(e => isLeaf(e, 'Ваша ціна'))) {
            let n = leaf;
            while (n && !(n.querySelectorAll('button').length >= 3 && n.querySelector('input')
                          && n.textContent.includes('Артикул'))) n = n.parentElement;
            if (n && n.innerText.length < 2500 && [...n.querySelectorAll('*')].some(e => e.textContent.trim() === sku))
              cards.push(n);
          }
          if (cards.length === 1) cards[0].setAttribute('data-crm-card', '1');
          return cards.length;
        }""", sku)
        if found != 1:
            sys.exit(f'{sku}: карток з точним артикулом {found}, очікувалась 1 — зупиняюсь')
        btns = self.pg.locator('[data-crm-card="1"] button')
        btns.nth(btns.count() - 1).click()        # остання кнопка в картці — «у кошик»
        pg.wait_for_load_state('networkidle', timeout=30000)
        pg.wait_for_timeout(1500)

    def set_cart_qty(self, sku, qty):
        """Кількість у рядку кошика — з клавіатури (поле number; поруч прапорець «вибраний»)."""
        pg = self.pg
        self.open('/uk/cart')
        row = pg.locator('tr').filter(has_text=sku)
        if row.count() != 1:
            sys.exit(f'{sku}: рядків у кошику {row.count()}, очікувався 1')
        q = row.locator('input[type=number]')
        if q.input_value() == str(qty):
            return
        q.click()
        pg.keyboard.press('Control+A')
        pg.keyboard.type(str(qty), delay=80)
        pg.keyboard.press('Tab')
        pg.wait_for_load_state('networkidle', timeout=30000)
        pg.wait_for_timeout(1500)

    def add(self, sku, qty):
        items = self.cart_items()
        if sku not in items:
            self.click_cart_button(sku)
            items = self.cart_items()
            if sku not in items:
                sys.exit(f'{sku}: після кнопки кошика товару в кошику немає')
        if items[sku][0] != qty:
            self.set_cart_qty(sku, qty)
            items = self.cart_items()
        got = items.get(sku, (0,))[0]
        print(f'{sku}: у кошику {got:g} шт (потрібно {qty})' + ('' if got == qty else ' — НЕ ЗБІГАЄТЬСЯ'))
        return got == qty

    def close(self):
        self.save()
        self.b.close()


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('login', 'cart', 'add'):
        sys.exit(__doc__)
    with sync_playwright() as p:
        crm = Crm(p)
        try:
            if sys.argv[1] == 'login':
                crm.login()
                print('вхід ok:', crm.pg.url)
            elif sys.argv[1] == 'cart':
                items = crm.cart_items()
                for sku, (amt, s, cur) in items.items():
                    print(f'{sku} × {amt:g} = {s} (валюта — у рядку замовлення; agreement кошика {cur})')
                print(f'позицій: {len(items)}')
            else:
                ok = crm.add(sys.argv[2], int(sys.argv[3]))
                if not ok:
                    sys.exit(1)
        finally:
            crm.close()


if __name__ == '__main__':
    main()
