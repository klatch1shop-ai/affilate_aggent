"""
tools/epicentr_enrich_audit.py
===============================
Для кожної картки в статусі «Наповнення контентом» (enrich) рахує, яких саме
обовʼязкових характеристик бракує, щоб її можна було віддати на модерацію.

Джерела:
  data/epicentr_products.json        — перелік карток (tools/epicentr_products_dump.py)
  data/epicentr_attribute_sets.json  — обовʼязкові атрибути (tools/epicentr_attrset_fetch.py)
  core-api /v2/pim/products/{id}     — заповнені значення картки

Перевірено на RO2286: розрахунок дав «Тип товару, Тип живлення, Форма» —
точно те, що показує кабінет на скриншоті власника (23.08.2026).

УВАГА: категорію картки призначає їхній менеджер, і вона може не збігатися з
нашим фідом. Тому категорія береться з кабінету (attributeSetCode), не з фіду.

Тільки читання. Деталі API — SKILL-20.
"""
import os, sys, json, time, base64
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
API   = 'https://core-api.epicentrm.com.ua'
OUT   = os.path.join(BASE, 'docs', 'epicentr_enrich_gaps.json')
PAUSE = 0.15


def ua(o):
    for t in (o or {}).get('translations', []):
        if t.get('languageCode') == 'ua':
            return t.get('title') or t.get('value')
    return (o or {}).get('code')


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def main():
    prods = {x['id']: x for x in json.load(
        open(os.path.join(BASE, 'data', 'epicentr_products.json'), encoding='utf-8'))}
    sets = json.load(open(os.path.join(BASE, 'data', 'epicentr_attribute_sets.json'),
                          encoding='utf-8'))
    targets = [p for p in prods.values() if p['status'] == 'enrich']
    if '--sample' in sys.argv:
        targets = targets[:40]
    print(f'карток у «Наповнення контентом»: {len(targets)}')

    done_ids = set()
    out = []
    if '--resume' in sys.argv and os.path.exists(OUT):
        out = json.load(open(OUT, encoding='utf-8'))
        done_ids = {x['id'] for x in out}
        targets = [t for t in targets if t['id'] not in done_ids]
        print(f'продовжую: вже розібрано {len(done_ids)}, лишилось {len(targets)}')

    s = requests.Session()
    s.headers.update({'Accept': 'application/json', 'Accept-Language': 'uk-UA'})
    login(s)

    done = 0
    for p in targets:
        for attempt in range(4):
            try:
                r = s.get(f"{API}/v2/pim/products/{p['id']}", timeout=45)
                if r.status_code == 401:
                    login(s)
                    continue
                r.raise_for_status()
                d = r.json()
                break
            except Exception as e:
                if attempt == 3:
                    print(f"  {p['id']}: {e}", file=sys.stderr)
                    d = None
                    break
                time.sleep(2 * (attempt + 1))
        if not d:
            continue

        cat = str(d.get('attributeSetCode'))
        spec = sets.get(cat) or {}
        req = [a for a in spec.get('attributes', []) if a.get('isRequired')]
        filled = {v.get('code') for v in (d.get('attributeValues') or [])
                  if v.get('value') not in (None, '', [])}
        missing = [{'code': a.get('code'), 'name': ua(a), 'type': a.get('type')}
                   for a in req if a.get('code') not in filled]
        out.append({'id': p['id'], 'sku': p['sku'], 'category': cat,
                    'categoryName': ua(spec), 'completeness': d.get('completeness'),
                    'createdAt': p.get('createdAt'),
                    'knownSpec': bool(req), 'missing': missing})
        done += 1
        if done % 250 == 0:
            print(f'  {done}/{len(targets)}', file=sys.stderr)
            json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        time.sleep(PAUSE)

    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'оброблено: {done} → {OUT}')


if __name__ == '__main__':
    main()
