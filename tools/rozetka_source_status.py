#!/usr/bin/env python3
"""Стан фіду (джерела) на Rozetka: скільки товарів у продажу, на модерації, відхилено й чому.

Лише читання. SKILL-36. Перевірено 19.09.2026 на TOPTUL (джерело 55634).

Джерела магазину — GET /markets/sources-list (id + кількість товарів; URL фіду
API не віддає, тож джерело впізнається за кількістю офферів). Товари джерела за
вкладками — GET /goods/{вкладка}?sync_source_id=… (_meta.totalCount).
Модерація ділиться на upload_status 8 «підготовлені» (ще в черзі) і 16 «на
модерації». Відхилені — вкладка hidden, причина в blocked_reason.

    python3 tools/rozetka_source_status.py                 # усі джерела
    python3 tools/rozetka_source_status.py 55634           # одне джерело + причини відмов
"""
import collections
import os
import sys
import time

import requests
import urllib3

urllib3.disable_warnings()
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'agents', 'orders'))
import rozetka_order_agent as RZ  # noqa: E402

TABS = ('on-sale', 'new', 'moderation', 'hidden', 'errors', 'not-valid', 'not-available', 'quarantine', 'archive', 'all')


def get(path, **params):
    return requests.get(RZ.ROZETKA_BASE + path, headers=RZ.rz_headers(), params=params,
                        verify=False, timeout=60).json()


def total(path, **params):
    r = get(path, pageSize=1, **params)
    return ((r.get('content') or {}).get('_meta') or {}).get('totalCount') if r.get('success') else None


def sources():
    c = get('/markets/sources-list').get('content')
    return c if isinstance(c, list) else []


def status(sid):
    out = {}
    for tab in TABS:
        out[tab] = total(f'/goods/{tab}', sync_source_id=sid)
        time.sleep(0.3)
    out['moderation_queued'] = total('/goods/moderation', sync_source_id=sid, upload_status=8)
    out['moderation_review'] = total('/goods/moderation', sync_source_id=sid, upload_status=16)
    return out


def hidden_reasons(sid, limit=2000):
    """Причини відмов. Кожен товар рахується один раз: на неповних вибірках API
    повертає ту саму сторінку на page=2,3… (19.09: 5 товарів дали «50 відмов»)."""
    reasons, examples, seen, page = collections.Counter(), collections.defaultdict(list), set(), 1
    while len(seen) < limit:
        items = (get('/goods/hidden', sync_source_id=sid, pageSize=50, page=page).get('content') or {}).get('items') or []
        fresh = [x for x in items if (x.get('item_id') or x.get('article')) not in seen]
        for x in fresh:
            seen.add(x.get('item_id') or x.get('article'))
            for b in x.get('blocked_reason') or [{'title': 'без причини'}]:
                t = b.get('title') if isinstance(b, dict) else str(b)
                reasons[t] += 1
                if len(examples[t]) < 5:
                    examples[t].append(x.get('article'))
        if len(items) < 50 or not fresh:
            break
        page += 1
        time.sleep(0.3)
    return reasons, examples


def main():
    if len(sys.argv) < 2:
        for s in sources():
            print(f"джерело {s['id']}: {s.get('total_items_count')} товарів, синхронізація кожні {s.get('sync_period')} хв")
        print('\nподробиці: python3 tools/rozetka_source_status.py <id джерела>')
        return
    sid = int(sys.argv[1])
    st = status(sid)
    print(f'джерело {sid}:')
    for k, v in st.items():
        print(f'  {k:18} {v}')
    ok = (st['on-sale'] or 0) + (st['new'] or 0)
    print(f"\n  пройшли: {ok} · на модерації: {st['moderation']} "
          f"(у черзі {st['moderation_queued']}, перевіряються {st['moderation_review']}) · відхилено: {st['hidden']}")
    if st['hidden']:
        reasons, ex = hidden_reasons(sid)
        print('\n  причини відмов:')
        for t, n in reasons.most_common():
            print(f'    {n:4} · {t} · напр. {", ".join(map(str, ex[t]))}')


if __name__ == '__main__':
    main()
