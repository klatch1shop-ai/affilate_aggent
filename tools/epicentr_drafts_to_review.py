#!/usr/bin/env python3
"""
tools/epicentr_drafts_to_review.py
===================================
Переводить нові чернетки в «На розгляді» (`draft → new`).

ЛАНЦЮЖОК СТАТУСІВ ЄПІЦЕНТРУ
    Чернетка → На розгляді → Наповнення контентом → На модерації → Опублікований

Після імпорту товар потрапляє в «Чернетку». Далі його має подивитись
категорійний менеджер — для цього картку переводять у «На розгляді»
(`statusCode: new`, id 6). Сам менеджер потім або поверне її в чернетку з
коментарем, або переведе в «Наповнення контентом».

ЧОМУ ПЕРЕВІРЯЄМО ВНУТРІШНІЙ РЕЗУЛЬТАТ, А НЕ HTTP-КОД. Ендпоінт відповідає
`200 OK` навіть тоді, коли не перевів жодної картки: невдача лежить усередині,
у `result.collection[].result = false`. Перевірка лише за кодом HTTP показала б
успіх там, де насправді нічого не сталось.

ФІЛЬТР ЗА ДАТОЮ обов'язковий: у кабінеті є старі чернетки, яких ця партія не
стосується, і відправляти їх на розгляд разом із новими не можна.

    python3 tools/epicentr_drafts_to_review.py --created 2026-09-04 --plan
    python3 tools/epicentr_drafts_to_review.py --created 2026-09-04
"""
import os, sys, time, argparse, collections
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.consent import require as consent_require
API = 'https://core-api.epicentrm.com.ua'
CHUNK = 50


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--created', required=True, help='YYYY-MM-DD — дата створення')
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    s = requests.Session()
    s.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                      'Accept-Language': 'uk-UA'})
    login(s)

    drafts, cur, seen = [], None, set()
    while True:
        p = {'limit': 100, 'sort[]': 'id'}
        if cur:
            p['cursor'] = cur
        d = s.get(f'{API}/v2/pim/products', params=p, timeout=60).json()
        items = d.get('items') or []
        for x in items:
            if x.get('status') == 'draft' and (x.get('createdAt') or '')[:10] == a.created:
                drafts.append(x)
        cur = d.get('next')
        if not items or not cur or cur in seen:
            break
        seen.add(cur)

    print(f'чернеток, створених {a.created}: {len(drafts)}')
    if a.limit:
        drafts = drafts[:a.limit]
    if not drafts:
        return
    if a.plan:
        cat = collections.Counter(x.get('attributeSetName') or '?' for x in drafts)
        for k, v in cat.most_common(8):
            print(f'  {v:5}  {k}')
        print(f'\n[plan] перевів би {len(drafts)} у «На розгляді»')
        return

    consent_require('epicentr_moderate', f'{len(drafts)} чернеток → На розгляді')
    ok = fail = 0
    reasons = collections.Counter()
    for i in range(0, len(drafts), CHUNK):
        part = drafts[i:i + CHUNK]
        body = {'collection': [{'productId': x['id'], 'statusCode': 'new'} for x in part]}
        try:
            r = s.patch(f'{API}/v2/pim/products/common/status/batch', json=body, timeout=90)
            if r.status_code == 401:
                login(s)
                r = s.patch(f'{API}/v2/pim/products/common/status/batch', json=body, timeout=90)
            j = r.json()
        except Exception as e:
            fail += len(part); reasons[f'запит впав: {e}'] += len(part); continue
        for row in (j.get('result') or {}).get('collection', []):
            if row.get('result'):
                ok += 1
            else:
                fail += 1
                reasons[(row.get('errorMessage') or row.get('reason') or 'без пояснення')[:90]] += 1
        time.sleep(0.3)
        if (i // CHUNK) % 10 == 0:
            print(f'  {i + len(part)}/{len(drafts)} — переведено {ok}', file=sys.stderr)

    print(f'\nпереведено: {ok} | не вдалось: {fail}')
    for k, v in reasons.most_common(6):
        print(f'  {v:5}  {k}')


if __name__ == '__main__':
    main()
