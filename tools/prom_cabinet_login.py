#!/usr/bin/env python3
"""Вхід у кабінет Prom власника й збереження сесії.

Навіщо: потрібен перелік пошукових запитів, за якими покупці знаходять наші
товари. Це власні дані магазину й єдине санкціоноване джерело таких
формулювань — сторінки пошуку Prom закриті в `robots.txt`, а в API Prom
статистики запитів немає (перевірено: 21 метод, жодного аналітичного).

Кожен крок тут — наслідок конкретного збою:

* `my.prom.ua` віддає 302 на публічну головну, `prom.ua/login` — 404.
  Форма входу існує лише як бічна панель: «Кабінет» → «Увійти».
* Віджет («Єдиний обліковий запис Rozetka») живе в крос-доменному iframe
  `connect-rid.prom.ua/frame/authorize`. Обхід `page.frames` +
  `query_selector` його не брав — потрібен `frame_locator`.
* Відкрити той iframe напряму не вийде: без `redirect_url` і `state` від
  батьківської сторінки він вантажиться порожнім.
* Поле телефону — `input[type=text]` БЕЗ name, id і placeholder, з маскою
  «+38». `fill()` маску ламає, тому `type()` посимвольно і лише цифри без
  коду країни — «+38» підставляє сама маска.
* Звичайний `click()` по «Кабінет» одного разу завис на 30 с, хоча елемент
  був видимий і стабільний. Тому клік по батьківській сторінці — через JS.

Одноразовий код приходить власнику: скрипт зупиняється і чекає, поки код
з'явиться у файлі `--otp-file`.

Доступи — лише з `.env` (`PROM_CABINET_LOGIN`).
"""
import argparse
import os
import re
import time

from camoufox.sync_api import Camoufox
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME_URL = 'https://prom.ua/'
FRAME_SELECTOR = "iframe[src*='connect-rid.prom.ua']"

CABINET_TEXTS = ('Кабінет', 'Кабинет')
ENTER_TEXTS = ('Увійти або зареєструватись', 'Войти или зарегистрироваться', 'Увійти')
CONTINUE_TEXTS = ('Продовжити', 'Продолжить')

# Точний збіг тексту не спрацював на «Увійти або зареєструватись»: у кнопці
# трапляються нерозривні пробіли й вкладені елементи. Тому шукаємо входження
# підрядка і беремо НАЙГЛИБШИЙ відповідний елемент — інакше клік прилітає в
# обгортку, яка обробника не має.
JS_CLICK = """
(texts) => {
    const norm = s => s.replace(/\\s+/g, ' ').trim().toLowerCase();
    const all = [...document.querySelectorAll('a,button,div,span,li')]
        .filter(e => e.offsetParent !== null);
    for (const t of texts) {
        const want = norm(t);
        const hits = all.filter(e => norm(e.textContent).includes(want));
        if (!hits.length) continue;
        // найглибший = той, що не містить інших кандидатів
        const el = hits.find(e => !hits.some(o => o !== e && e.contains(o))) || hits[0];
        el.click();
        return `${t} <${el.tagName.toLowerCase()}>`;
    }
    return null;
}
"""


def shot(page, path, label):
    try:
        page.screenshot(path=path)
        print(f'[знімок] {label}: {path}', flush=True)
    except Exception as exc:
        print(f'[знімок не вдався] {label}: {exc}', flush=True)


def wait_for_otp(path, timeout=900):
    """Чекає код від власника. Порожній файл означає, що коду ще немає."""
    end = time.time() + timeout
    said = 0
    while time.time() < end:
        if os.path.exists(path):
            code = re.sub(r'\D', '', open(path, encoding='utf-8').read())
            if code:
                return code
        if time.time() - said > 60:
            print(f'[чекаю код] лишилось {int(end - time.time())} с', flush=True)
            said = time.time()
        time.sleep(3)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--otp-file', required=True)
    ap.add_argument('--state', default=os.path.join(BASE, 'data', 'prom_session.json'))
    ap.add_argument('--shots', default='/tmp/prom_login')
    args = ap.parse_args()

    load_dotenv(os.path.join(BASE, '.env'), override=True)
    login = os.getenv('PROM_CABINET_LOGIN')
    if not login:
        raise SystemExit('немає PROM_CABINET_LOGIN у .env')
    digits = re.sub(r'\D', '', login)
    local = digits[2:] if digits.startswith('380') else digits   # маска дає «+38»
    print(f'номер із .env: …{digits[-4:]}, у поле піде {local!r}', flush=True)

    os.makedirs(args.shots, exist_ok=True)
    open(args.otp_file, 'w').close()

    with Camoufox(headless=True, humanize=True, locale='uk-UA') as browser:
        page = browser.new_page()
        page.set_default_timeout(20000)
        page.goto(HOME_URL, wait_until='domcontentloaded', timeout=90000)
        page.wait_for_selector('header, [data-qaid]', timeout=30000)
        print('сторінка:', page.title(), flush=True)

        print('клік «Кабінет»:', page.evaluate(JS_CLICK, list(CABINET_TEXTS)), flush=True)
        page.wait_for_timeout(4000)
        shot(page, f'{args.shots}/1_sidebar.png', 'бічна панель')

        print('клік «Увійти»:', page.evaluate(JS_CLICK, list(ENTER_TEXTS)), flush=True)

        # чекаємо появи саме віджета авторизації, а не фіксовану паузу
        page.wait_for_selector(FRAME_SELECTOR, state='attached', timeout=30000)
        print('фрейм авторизації з’явився', flush=True)
        shot(page, f'{args.shots}/2_frame.png', 'фрейм')

        frame = page.frame_locator(FRAME_SELECTOR)
        phone = frame.locator("input[type='text']").first
        phone.wait_for(state='visible', timeout=30000)
        before = phone.input_value()
        print(f'поле знайдено, у ньому {before!r}', flush=True)

        phone.click()
        phone.type(local, delay=90)          # fill() ламає маску
        page.wait_for_timeout(1200)
        after = phone.input_value()
        print(f'після введення: {after!r}', flush=True)
        shot(page, f'{args.shots}/3_phone.png', 'номер введено')

        if len(re.sub(r'\D', '', after)) < 10:
            print('ПОМИЛКА: маска затерла введення, у полі замало цифр', flush=True)
            return

        pressed = None
        for text in CONTINUE_TEXTS:
            btn = frame.locator(f'button:has-text("{text}")')
            if btn.count():
                btn.first.click()
                pressed = text
                break
        if not pressed:
            phone.press('Enter')
            pressed = 'Enter'
        print(f'натиснуто «{pressed}»', flush=True)

        page.wait_for_timeout(8000)
        shot(page, f'{args.shots}/4_after_submit.png', 'після відправки')
        try:
            print('текст віджета:', frame.locator('body').inner_text()[:400], flush=True)
        except Exception:
            pass

        print(f'\n>>> Якщо надійшов код — запиши його у {args.otp_file}\n', flush=True)
        code = wait_for_otp(args.otp_file)
        if not code:
            print('код не надійшов', flush=True)
            return
        print(f'отримано код із {len(code)} цифр', flush=True)

        boxes = frame.locator("input[type='text'], input[type='tel']")
        n = boxes.count()
        if n > 1:                             # код буває розбитий по клітинках
            for i, ch in enumerate(code[:n]):
                boxes.nth(i).type(ch, delay=80)
        else:
            boxes.first.click()
            boxes.first.type(code, delay=80)
        page.wait_for_timeout(2000)

        for text in CONTINUE_TEXTS + ('Підтвердити',):
            btn = frame.locator(f'button:has-text("{text}")')
            if btn.count():
                btn.first.click()
                break
        page.wait_for_timeout(10000)
        shot(page, f'{args.shots}/5_after_code.png', 'після коду')

        os.makedirs(os.path.dirname(args.state), exist_ok=True)
        page.context.storage_state(path=args.state)
        print('сесію збережено:', args.state, flush=True)
        print('URL:', page.url, '| заголовок:', page.title(), flush=True)


if __name__ == '__main__':
    main()
