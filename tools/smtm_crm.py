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
        """Вхід із ВВОДОМ З КЛАВІАТУРИ, а не fill().

        04.10.2026: сесія протермінувалась, і вхід упав — кнопка submit
        лишалась неактивною 30 секунд. Причина та сама, що записана в скілі
        для кошика: сайт на React НЕ ПОМІЧАЄ `fill()`. У полі значення
        видно, а форма вважає його порожнім і не вмикає кнопку. У кошику ми
        це вже обходили, у вході — ні.

        Кнопок submit на сторінці дві; беремо ту, що справді активна.
        """
        pg = self.pg
        if '/login' not in pg.url:
            pg.goto(f'{BASE}/uk/login', wait_until='networkidle', timeout=60000)
        email = pg.locator('input[type=text]').first
        email.click()
        email.type(os.getenv('SMTM_LOGIN', ''), delay=50)
        pwd = pg.locator('input[type=password]').first
        pwd.click()
        pwd.type(os.getenv('SMTM_PASSWORD', ''), delay=50)
        pg.wait_for_timeout(800)
        btns = pg.locator('button[type=submit]')
        clicked = False
        for i in range(btns.count()):
            b = btns.nth(i)
            if b.is_enabled():
                b.click()
                clicked = True
                break
        if not clicked:
            pwd.press('Enter')       # запасний шлях, якщо кнопка лишилась неактивною
        pg.wait_for_url(lambda u: '/login' not in u, timeout=40000)
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

    # ── оформлення й ТТН ──────────────────────────────────────────────
    #
    # КОШИК ОДИН НА ВЕСЬ АКАУНТ. Два замовлення, що обробляються одночасно,
    # змішають свої позиції в одному кошику, і постачальник отримає кашу.
    # Тому: обробка строго по одному (замок у виклику), кошик має бути
    # ПОРОЖНІЙ перед початком, а перед оформленням його склад звіряється з
    # очікуваним ТОЧНО — і за артикулами, і за кількостями.

    def cart_is_empty(self):
        return not self.cart_items()

    def clear_cart(self):
        """Прибрати все з кошика: ставимо 0 кожному рядку."""
        for sku in list(self.cart_items()):
            try:
                self.set_cart_qty(sku, 0)
            except Exception as exc:
                print(f'{sku}: не вдалось прибрати — {type(exc).__name__}')
        return self.cart_is_empty()

    def cart_matches(self, expected):
        """expected: {артикул: кількість}. Точний збіг складу й кількостей."""
        got = {k: v[0] for k, v in self.cart_items().items()}
        want = {k: float(v) for k, v in expected.items()}
        if got == want:
            return True, 'склад кошика збігається'
        return False, f'кошик {got} ≠ очікуване {want}'

    def checkout_open(self):
        """Кнопка «Оформити» в кошику → сторінка /uk/checkout/<id>.

        Нічого не замовляє: це лише перехід. Спосіб доставки «Нова пошта»
        там обраний за замовчуванням, і ми його НЕ чіпаємо.
        """
        self.open('/uk/cart')
        btn = self.pg.get_by_role('button', name='Оформити', exact=True)
        if not btn.count():
            btn = self.pg.locator('button:has-text("Оформити")').first
        btn.first.click()
        self.pg.wait_for_url('**/checkout/**', timeout=30000)
        return self.pg.url.rstrip('/').split('/')[-1]

    def place_order(self):
        """НЕЗВОРОТНЕ: натискає «Оформити замовлення». → ID замовлення в CRM."""
        btn = self.pg.locator('button:has-text("Оформити замовлення")').first
        btn.click()
        self.pg.wait_for_timeout(6000)
        import re as _re
        text = self.pg.locator('body').inner_text()
        m = _re.search(r'ID\s*(\d{6,})', text)
        if not m:
            raise RuntimeError(f'ID замовлення не знайдено. Сторінка: {text[:300]}')
        return m.group(1)

    def attach_ttn(self, ttn, pdf_path):
        """Прикріпити номер ТТН і PDF 100×100 до оформленого замовлення.

        Порядок із перевірених кроків 15.09: радіо «Прикріпити файл» →
        поле «Номер ТТН» з клавіатури (fill() React не помічає) →
        set_input_files → кнопка «Прикріпити».
        """
        pg = self.pg
        pg.locator('text=Прикріпити файл').first.click()
        pg.wait_for_timeout(2000)
        # Будова сторінки, зчитана 04.10: три radio name=ttnOrigin, ОДНЕ
        # текстове поле без placeholder (номер ТТН) і невидиме input[type=file].
        # Перше текстове поле на сторінці — це пошук по каталогу
        # (placeholder «Пошук по каталогу...»), його брати не можна.
        num = pg.locator('input[type=text]:not([placeholder])').first
        if not num.count():
            num = pg.locator('input[type=text]').nth(1)
        num.click()
        num.type(str(ttn), delay=60)          # fill() React не помічає
        # Поле файлу НЕВИДИМЕ — це норма, set_input_files із ним працює.
        pg.locator('input[type=file]').first.set_input_files(pdf_path)
        pg.wait_for_timeout(2500)
        btn = pg.locator('button:has-text("Прикріпити")').first
        if not btn.is_enabled():
            return False, 'кнопка «Прикріпити» лишилась неактивною — номер або файл не прийнялись'
        btn.click()
        pg.wait_for_timeout(5000)
        body = pg.locator('body').inner_text()
        ok = ('успішно прикріплений' in body) or (str(ttn) in body and 'надіслана' in body)
        return ok, body[:200]

    def order_info(self, crm_id):
        """Сума до сплати й стан замовлення з /inner/checkout/<id>."""
        d = self.api(f'/uk/inner/checkout/{crm_id}')
        if not isinstance(d, dict):
            return {}
        return {'сума': d.get('totalSum'), 'ттн': d.get('ttnNumber'),
                'джерело_ттн': d.get('ttnOrigin'), 'чекає_ттн': d.get('waitForTtn')}

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
