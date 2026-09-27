"""Відправка готових карток Єпіцентру на модерацію.

ПЕРЕХІД ОДНОСТОРОННІЙ (SKILL-20 §3b): назад картку повертає лише модератор,
і `availabilityTransitions` одразу стає порожнім. Тому:

  * сюди подається ЛИШЕ те, що вже пройшло `epicentr_ready_check.py`,
    тобто має всі обовʼязкові атрибути заповненими й статус `enrich`;
  * за замовчуванням нічого не робить — потрібен явний `--apply`;
  * `--limit` існує, щоб спершу відправити кілька й подивитись на результат.

21.09.2026 на модерацію пішли 59 карток лише тому, що в них не лишилось
порожніх обовʼязкових полів, і жодна не пройшла. «Немає порожніх» і
«готова» — різні твердження.

    venv/bin/python tools/epicentr_send_moderation.py --map exports/epicentr_ready_to_send.json
    venv/bin/python tools/epicentr_send_moderation.py --map ... --apply --limit 3
"""
import argparse
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

API = 'https://core-api.epicentrm.com.ua'
BATCH = 50                      # скільки карток в одному PATCH
DONE_LOG = os.path.join(BASE, 'exports', 'epicentr_sent_moderation.json')


def login(session):
    r = session.post(f'{API}/v2/users/login',
                     json={'login': os.getenv('EPICENTR_EMAIL'),
                           'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    session.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def send(session, pairs):
    """pairs: [(sku, productId)]. Повертає (код, текст)."""
    body = {'collection': [{'productId': pid, 'statusCode': 'moderating'}
                           for _, pid in pairs]}
    r = session.patch(f'{API}/v2/pim/products/common/status/batch', json=body, timeout=90)
    if r.status_code == 401:
        login(session)
        r = session.patch(f'{API}/v2/pim/products/common/status/batch', json=body, timeout=90)
    return r.status_code, r.text[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--map', required=True, help='{sku: productId} від epicentr_ready_check')
    ap.add_argument('--apply', action='store_true', help='без цього — лише показує')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    with open(a.map, encoding='utf-8') as f:
        ready = json.load(f)
    already = {}
    if os.path.exists(DONE_LOG):
        with open(DONE_LOG, encoding='utf-8') as f:
            already = json.load(f)
    pairs = [(s, p) for s, p in ready.items() if s not in already]
    if a.limit:
        pairs = pairs[:a.limit]

    print(f'готових у файлі: {len(ready)} | уже відправлено раніше: {len(already)}')
    print(f'до відправки зараз: {len(pairs)}')
    if not a.apply:
        print('\nце ПОКАЗ. Щоб відправити насправді — додайте --apply')
        print('перші:', [s for s, _ in pairs[:10]])
        return
    if not pairs:
        return

    session = requests.Session()
    session.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                            'Accept-Language': 'uk-UA'})
    login(session)

    sent, failed = 0, 0
    for i in range(0, len(pairs), BATCH):
        chunk = pairs[i:i + BATCH]
        code, text = send(session, chunk)
        if code in (200, 201, 204):
            sent += len(chunk)
            for sku, pid in chunk:
                already[sku] = {'productId': pid, 'ts': time.strftime('%Y-%m-%d %H:%M:%S')}
            with open(DONE_LOG, 'w', encoding='utf-8') as f:
                json.dump(already, f, ensure_ascii=False, indent=1)
        else:
            failed += len(chunk)
            print(f'  партія {i // BATCH + 1}: {code} {text}', file=sys.stderr)
        print(f'  {min(i + BATCH, len(pairs))}/{len(pairs)}', flush=True)
        time.sleep(0.5)

    print(f'\nвідправлено: {sent} | не вдалось: {failed}')
    print(f'журнал: {DONE_LOG}')


if __name__ == '__main__':
    main()
