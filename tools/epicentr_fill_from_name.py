"""Заповнює порожню обовʼязкову характеристику, визначаючи її з НАЗВИ товару.

Правило, на яке вказали обидва консультанти 27.09.2026: модель має **обирати
з дозволених варіантів**, а не вигадувати значення, яке потім намагаються
втиснути в довідник. Тому список варіантів іде в питання, а все, чого в
ньому немає, відкидається.

Модель має право відповісти НЕ ЗНАЮ — і це краще за здогад: 21.09 на
модерацію пішли 59 карток із вгаданими значеннями, і жодна не пройшла.

    venv/bin/python tools/epicentr_fill_from_name.py --skus exports/noire_left.json \\
        --attr Стать --set 7216
    ... --apply
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

_spec = importlib.util.spec_from_file_location(
    'afm', os.path.join(BASE, 'tools', 'epicentr_attr_fill_multi.py'))
afm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(afm)

from shared.utils.llm_router import call_gemini                     # noqa: E402

API = 'https://core-api.epicentrm.com.ua'
PRODUCTS = os.path.join(BASE, 'data', 'epicentr_products.json')
SETS = os.path.join(BASE, 'data', 'epicentr_attribute_sets.json')
SENT = os.path.join(BASE, 'exports', 'epicentr_sent_moderation.json')


def login(session):
    r = session.post(f'{API}/v2/users/login',
                     json={'login': os.getenv('EPICENTR_EMAIL'),
                           'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    session.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def ask(name, attr, allowed, photo_url=None):
    """Один із `allowed` або None. Список у питанні — щоб не було що вигадувати.

    `photo_url` потрібен там, де характеристики в назві немає взагалі: 27.09
    усі 69 карток із порожнім «Кольором виробника» дали «не визначила», бо в
    назві на кшталт «Кріплення для мастурбатора Otouch INSCUP, присоска»
    кольору не існує — він лише на зображенні.
    """
    source = 'назви та фото' if photo_url else 'назви'
    q = (f'Товар: «{name}»\n\n'
         f'Характеристика «{attr}». Дозволені значення, інших не існує:\n'
         f'{json.dumps(allowed, ensure_ascii=False)}\n\n'
         f'Обери РІВНО ОДНЕ зі списку на основі {source}. Якщо визначити '
         'неможливо — відповідай НЕ ЗНАЮ. Нічого не вигадуй і не пояснюй. '
         'Відповідь — лише значення або НЕ ЗНАЮ.')
    try:
        image_bytes = None
        if photo_url:
            from shared.utils.vendor_pool import _fetch
            image_bytes = _fetch(photo_url)[0]
        text, _model, _tok = call_gemini(q, timeout=90, max_tokens=60,
                                         image_bytes=image_bytes,
                                         image_mime='image/jpeg' if image_bytes else None)
    except Exception:
        return None
    answer = (text or '').strip().strip('."\'«»')
    if answer in allowed:
        return answer
    lowered = {a.casefold(): a for a in allowed}
    return lowered.get(answer.casefold())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skus', required=True)
    ap.add_argument('--attr', required=True)
    ap.add_argument('--set', required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--use-photo', action='store_true', help='показати моделі головне фото картки')
    ap.add_argument('--options-from', help='файл зразків: звузити довідник до значень, що реально вживають опубліковані картки')
    a = ap.parse_args()

    sets = json.load(open(SETS, encoding='utf-8'))
    spec = sets.get(a.set)
    attribute = next((x for x in (spec or {}).get('attributes', [])
                      if afm.ua(x) == a.attr), None)
    if not attribute:
        sys.exit(f'у наборі {a.set} немає характеристики «{a.attr}»')
    code = str(attribute['code'])
    options = afm.options(a.set, code)
    if not options:
        sys.exit('довідник значень порожній')

    if a.options_from:
        # Звуження за зразками опублікованих карток. Причина (27.09): довідник
        # «Колір виробника» має 8468 варіантів — меблеві відтінки, камуфляж,
        # артикули, — і модель у ньому тоне: 146 карток поспіль дали «не
        # визначила». Опубліковані картки цього ж набору вживають 6–9 значень,
        # і це саме ті, що проходять модерацію.
        templates = json.load(open(a.options_from, encoding='utf-8'))
        tpl = (templates.get(a.set) or {})
        seen = (tpl.get('змінні', {}).get(code) or {}).get('варіанти')
        const = (tpl.get('сталі', {}).get(code) or {}).get('значення')
        allowed_values = {v for v, _ in seen} if seen else ({const} if const else set())
        if not allowed_values:
            sys.exit(f'у зразках набору {a.set} немає значень для «{a.attr}»')
        options = {name: value for name, value in options.items()
                   if value in allowed_values}
        if not options:
            sys.exit('після звуження не лишилось жодного варіанта')
    print(f'«{a.attr}» код {code}, дозволено: {list(options)}')

    wanted = set(json.load(open(a.skus, encoding='utf-8')))
    if os.path.exists(SENT):
        wanted -= set(json.load(open(SENT, encoding='utf-8')))
    products = [x for x in json.load(open(PRODUCTS, encoding='utf-8'))
                if x['sku'] in wanted and str(x.get('attributeSetCode')) == a.set]
    if a.limit:
        products = products[:a.limit]

    session = requests.Session()
    session.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                            'Accept-Language': 'uk-UA'})
    login(session)
    form = session.get(
        f'{API}/v2/pim/products/forms/attribute-set/by-code/{a.set}/attributes',
        timeout=40).json()
    items = form.get('items', form if isinstance(form, list) else [])
    field_id = next((x.get('id') for x in items if str(x['code']) == code), None)
    if not field_id:
        sys.exit('не знайдено id поля у формі')

    def work(product):
        try:
            r = session.get(f"{API}/v2/pim/products/{product['id']}", timeout=45)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            return product['sku'], 'помилка читання', str(e)[:80], None
        current = [{'id': v['id'], 'code': v['code'], 'value': v['value']}
                   for v in (data.get('attributeValues') or [])]
        if code in {str(v['code']) for v in current}:
            return product['sku'], 'вже було', None, None
        photo = None
        if a.use_photo:
            media = [m for m in (data.get('media') or []) if m.get('source')]
            main = next((m for m in media if m.get('isMain')), media[0] if media else None)
            photo = (main or {}).get('source')
        answer = ask(product.get('name') or '', a.attr, list(options), photo)
        if not answer:
            return product['sku'], 'модель не визначила', None, None
        if not a.apply:
            return product['sku'], 'знайдено', answer, None
        # code — РЯДОК: 27.09 int давав 400 validation.type на полі code
        current.append({'id': field_id, 'code': code, 'value': options[answer]})
        body = {'attributeValues': current, 'categories': data.get('categories'),
                'isPrepayment': data.get('isPrepayment'), 'media': data.get('media'),
                'productInPromotion': data.get('productInPromotion'),
                'attributeSetCode': data.get('attributeSetCode'),
                'companyId': data.get('companyId'), 'sku': data.get('sku'),
                'translations': data.get('translations')}
        r2 = session.put(f"{API}/v4/pim/products/common/{product['id']}", json=body, timeout=60)
        tries = 0
        while r2.status_code == 400 and tries < 2:
            bad = set(re.findall(r'attributeValues\[(\d+)\]', r2.text))
            if not bad:
                break
            # ЗНАЙДЕНО 27.09: якщо API відхиляє саме той атрибут, який ми
            # додаємо, прибирання робить запит «успішним» БЕЗ нього — і
            # лічильник каже «записано», хоча в картці нічого не змінилось.
            if code in bad:
                return product['sku'], 'значення відхилено довідником', answer, None
            body['attributeValues'] = [v for v in body['attributeValues']
                                       if str(v['code']) not in bad]
            tries += 1
            r2 = session.put(f"{API}/v4/pim/products/common/{product['id']}",
                             json=body, timeout=60)
        if r2.status_code not in (200, 201, 204):
            return product['sku'], 'відмова API', f'{r2.status_code} {r2.text[:110]}', None
        # Успіхом вважаємо лише те, що СПРАВДІ стоїть у картці.
        check = session.get(f"{API}/v2/pim/products/{product['id']}", timeout=45)
        if check.status_code == 200:
            now = {str(v['code']) for v in (check.json().get('attributeValues') or [])
                   if str(v.get('value') or '').strip()}
            if code not in now:
                return product['sku'], 'записалось, але в картці немає', answer, None
        return product['sku'], 'записано', answer, None

    print(f'карток: {len(products)}' + ('' if a.apply else '  (ПОКАЗ, без --apply)'))
    stats = {}
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for i, (sku, status, detail, _) in enumerate(pool.map(work, products), 1):
            stats[status] = stats.get(status, 0) + 1
            if i <= 10 or status in ('відмова API', 'помилка читання'):
                print(f'  {sku}: {status} {detail or ""}', flush=True)
            if i % 100 == 0:
                print(f'  {i}/{len(products)} {stats}', flush=True)
    print(f'\nпідсумок: {stats}')


if __name__ == '__main__':
    main()
