"""Експеримент власника: дати моделі ВСЮ картку одразу, а не одне питання.

Ідея (27.09.2026): досі ми питали про ОДНУ характеристику й показували лише
назву та перше фото. Якщо потрібного в назві не було — модель казала «не
знаю». Тут навпаки: усі фото, опис, уже відомі характеристики, і прохання
заповнити всі порожні одним заходом.

Чому це може бути краще:
  * модель бачить товар цілком і може вивести одне з іншого
    (бачить мереживо на фото → матеріал «тканина»);
  * один запит замість восьми — дешевше й зв'язніше.

Рахує СПРАВЖНІ токени з відповіді API, не оцінку, і окремо — ціну одного
заповненого поля. Саме це число потрібне для рішення про масштаб.

    venv/bin/python tools/epicentr_full_context_fill.py --limit 10
    venv/bin/python tools/epicentr_full_context_fill.py --limit 10 --codex
"""
import argparse
import collections
import importlib.util
import json
import os
import re
import sys
import time

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

_spec = importlib.util.spec_from_file_location(
    'afm', os.path.join(BASE, 'tools', 'epicentr_attr_fill_multi.py'))
afm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(afm)

from shared.utils.llm_router import call_codex, call_gemini            # noqa: E402
from shared.utils.vendor_pool import _fetch                            # noqa: E402

API = 'https://core-api.epicentrm.com.ua'
DICTS = os.path.join(BASE, 'exports', 'epicentr_dicts.json')
# Ціни Gemini flash-lite, оплачений тариф, за 1М токенів (перевірено 26.09).
PRICE_IN, PRICE_OUT = 0.10, 0.40


def login(session):
    r = session.post(f'{API}/v2/users/login',
                     json={'login': os.getenv('EPICENTR_EMAIL'),
                           'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    session.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def ua(obj):
    for t in (obj or {}).get('translations', []):
        if t.get('languageCode') == 'ua':
            return t.get('value') or t.get('title')
    return None


def build_prompt(name, description, known, gaps):
    plain = re.sub(r'<[^>]+>|&lt;[^&]*?&gt;|&[a-z]+;', ' ', description or '')
    return (f'ТОВАР: {name}\n\n'
            f'ОПИС ВІД ПОСТАЧАЛЬНИКА: {plain[:1400]}\n\n'
            f'ВЖЕ ВІДОМО:\n' + ('\n'.join(f'  {k}: {v}' for k, v in known.items()) or '  —')
            + '\n\nТРЕБА ВИЗНАЧИТИ. Для кожної характеристики обери значення '
              'ЛИШЕ зі свого списку:\n'
            + '\n'.join(f'  «{attr}»: {json.dumps(options, ensure_ascii=False)}'
                        for attr, options in gaps.items())
            + '\n\nДивись на фото і на все, що знаєш про товар; одне можна вивести '
              'з іншого. Якщо чогось визначити неможливо — постав null, не вигадуй.\n'
              'Відповідь СТРОГО JSON: {"характеристика": "значення або null"}. Без пояснень.')


def parse(text):
    if not text:
        return {}
    m = re.search(r'\{.*\}', text, re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def write_values(session, data, set_code, spec, values, dicts):
    """Записує знайдені значення в картку й ПЕРЕВІРЯЄ читанням.

    Три пастки, на яких уже наступили 27.09: код атрибута має бути рядком;
    частина атрибутів багатозначні (рядок дає 400, список 200); відповідь
    API про успіх нічого не означає, поки не перечитаєш картку.
    """
    pid = data['id']
    by_name = {}
    for attribute in spec.get('attributes', []):
        name = ua(attribute)
        if name:
            by_name[name] = str(attribute['code'])
    form = session.get(f'{API}/v2/pim/products/forms/attribute-set/by-code/{set_code}/attributes',
                       timeout=40).json()
    items = form.get('items', form if isinstance(form, list) else [])
    field_id = {str(x['code']): x.get('id') for x in items}

    current = [{'id': v['id'], 'code': v['code'], 'value': v['value']}
               for v in (data.get('attributeValues') or [])]
    added = []
    for attr_name, value in values.items():
        code = by_name.get(attr_name)
        options = dicts.get(f'{set_code}|{code}') or {}
        if not code or not field_id.get(code) or value not in options:
            continue
        current.append({'id': field_id[code], 'code': code, 'value': options[value]})
        added.append(code)
    if not added:
        return 0

    body = {'attributeValues': current, 'categories': data.get('categories'),
            'isPrepayment': data.get('isPrepayment'), 'media': data.get('media'),
            'productInPromotion': data.get('productInPromotion'),
            'attributeSetCode': data.get('attributeSetCode'),
            'companyId': data.get('companyId'), 'sku': data.get('sku'),
            'translations': data.get('translations')}
    r = session.put(f'{API}/v4/pim/products/common/{pid}', json=body, timeout=60)
    if r.status_code == 400:
        # Багатозначні атрибути приймають лише список.
        bad = set(re.findall(r'attributeValues\[(\d+)\]', r.text))
        if bad:
            body['attributeValues'] = [dict(v, value=[v['value']])
                                       if str(v['code']) in bad and not isinstance(v['value'], list)
                                       else v for v in body['attributeValues']]
            r = session.put(f'{API}/v4/pim/products/common/{pid}', json=body, timeout=60)
    if r.status_code not in (200, 201, 204):
        return 0
    check = session.get(f'{API}/v2/pim/products/{pid}', timeout=45)
    if check.status_code != 200:
        return 0
    now = {str(v['code']) for v in (check.json().get('attributeValues') or [])
           if str(v.get('value') or '').strip()}
    return sum(1 for code in added if code in now)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=10)
    ap.add_argument('--codex', action='store_true', help='дублювати запит на Codex')
    ap.add_argument('--photos', type=int, default=3)
    ap.add_argument('--apply', action='store_true', help='записувати знайдене в картки')
    ap.add_argument('--workers', type=int, default=5)
    a = ap.parse_args()

    sets = json.load(open(os.path.join(BASE, 'data', 'epicentr_attribute_sets.json'),
                          encoding='utf-8'))
    products = json.load(open(os.path.join(BASE, 'data', 'epicentr_products.json'),
                              encoding='utf-8'))
    dicts = json.load(open(DICTS, encoding='utf-8'))

    session = requests.Session()
    session.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                            'Accept-Language': 'uk-UA'})
    login(session)

    pool = [p for p in products if p.get('status') in ('enrich', 'draft', 'new')
            and (p.get('sku') or '').upper().startswith(('SO', 'SX', 'EL', 'PS', 'PJ'))]
    stats = collections.Counter()
    tokens = collections.Counter()
    seconds = collections.Counter()
    rows = []

    done = 0
    for product in pool:
        if done >= a.limit:
            break
        data = session.get(f"{API}/v2/pim/products/{product['id']}", timeout=45).json()
        set_code = str(data.get('attributeSetCode'))
        spec = sets.get(set_code) or {}
        required = {str(x['code']): ua(x) for x in spec.get('attributes', [])
                    if x.get('isRequired')}
        filled = {str(v['code']) for v in (data.get('attributeValues') or [])
                  if str(v.get('value') or '').strip()}
        gaps = {}
        for code, attr_name in required.items():
            if code in filled or not attr_name:
                continue
            options = dicts.get(f'{set_code}|{code}') or {}
            if options:
                gaps[attr_name] = list(options)
        if not gaps:
            continue

        known = {}
        for v in (data.get('attributeValues') or []):
            attr_name = next((ua(x) for x in spec.get('attributes', [])
                              if str(x['code']) == str(v['code'])), None)
            values = [ua(o) for o in (v.get('options') or []) if ua(o)]
            if attr_name and values:
                known[attr_name] = ', '.join(values)

        description = ''
        for t in (data.get('translations') or []):
            if t.get('languageCode') == 'ua' and t.get('description'):
                description = t['description']
                break
        photos = [m.get('source') for m in (data.get('media') or []) if m.get('source')]
        images = []
        for url in photos[:a.photos]:
            try:
                images.append(_fetch(url)[0])
            except Exception:
                pass

        prompt = build_prompt(product.get('name') or '', description, known, gaps)
        done += 1
        print(f"\n=== {product['sku']} [{set_code}] {(product.get('name') or '')[:54]} ===")
        print(f"    фото {len(images)} · відомо {len(known)} · бракує {len(gaps)}: {list(gaps)}")

        t0 = time.time()
        try:
            text, _model, usage = call_gemini(
                prompt, timeout=180, max_tokens=700,
                image_bytes=images[0] if images else None,
                image_mime='image/jpeg' if images else None)
            answer = parse(text)
            got = {k: v for k, v in answer.items() if v and k in gaps and v in gaps[k]}
            stats['gemini полів'] += len(got)
            stats['gemini прогалин'] += len(gaps)
            seconds['gemini'] += time.time() - t0
            if usage:
                tokens['in'] += usage.get('in') or 0
                tokens['out'] += usage.get('out') or 0
            print(f"    GEMINI: {len(got)}/{len(gaps)} · {json.dumps(got, ensure_ascii=False)[:150]}")
            if a.apply and got:
                written = write_values(session, data, set_code, spec, got, dicts)
                stats['записано'] += written
                print(f'    записано в картку: {written}')
            rows.append({'sku': product['sku'], 'вендор': 'gemini',
                         'прогалин': len(gaps), 'заповнено': len(got)})
        except Exception as e:
            print(f'    GEMINI ✗ {type(e).__name__}: {str(e)[:80]}')

        if a.codex:
            t0 = time.time()
            try:
                text, _ = call_codex(prompt, timeout=400)
                answer = parse(text)
                got = {k: v for k, v in answer.items() if v and k in gaps and v in gaps[k]}
                stats['codex полів'] += len(got)
                stats['codex прогалин'] += len(gaps)
                seconds['codex'] += time.time() - t0
                print(f"    CODEX:  {len(got)}/{len(gaps)} · {json.dumps(got, ensure_ascii=False)[:150]}")
                rows.append({'sku': product['sku'], 'вендор': 'codex',
                             'прогалин': len(gaps), 'заповнено': len(got)})
            except Exception as e:
                print(f'    CODEX ✗ {type(e).__name__}: {str(e)[:80]}')

    cost = tokens['in'] / 1e6 * PRICE_IN + tokens['out'] / 1e6 * PRICE_OUT
    print('\n' + '=' * 56)
    print(f"карток: {done}")
    print(f"GEMINI: заповнено {stats['gemini полів']} із {stats['gemini прогалин']} прогалин"
          f" · {seconds['gemini'] / max(done, 1):.1f} с на картку")
    if a.codex:
        print(f"CODEX:  заповнено {stats['codex полів']} із {stats['codex прогалин']} прогалин"
              f" · {seconds['codex'] / max(done, 1):.1f} с на картку")
    print(f"\nТОКЕНИ Gemini (справжні, з відповіді API): вхід {tokens['in']}, вихід {tokens['out']}")
    print(f"ВАРТІСТЬ партії: ${cost:.4f}  ·  на картку ${cost / max(done, 1):.5f}")
    if stats['gemini полів']:
        print(f"на ОДНЕ заповнене поле: ${cost / stats['gemini полів']:.5f}")
        print(f"прогноз на 1000 карток: ${cost / max(done, 1) * 1000:.2f}")


if __name__ == '__main__':
    main()
