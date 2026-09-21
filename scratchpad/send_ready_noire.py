"""Відправка на модерацію ЛИШЕ готових карток noire (enrich → moderating).

Кожну картку перевіряємо наживо: статус enrich, усі обовʼязкові атрибути мають непорожнє значення.
    python3 scratchpad/send_ready_noire.py --plan
    python3 scratchpad/send_ready_noire.py
"""
import json, os, sys, time, requests
sys.path.insert(0, os.path.expanduser('~/agent-system'))
from dotenv import load_dotenv; load_dotenv(os.path.expanduser('~/agent-system/.env'))
from shared.utils.consent import require as consent_require
SP = os.path.dirname(os.path.abspath(__file__))
API = 'https://core-api.epicentrm.com.ua'
s = requests.Session()
def login():
    r = s.post(f'{API}/v2/users/login', json={'login': os.getenv('EPICENTR_EMAIL'),
               'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40); r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"
login()
cands = [g for g in json.load(open(f'{SP}/gaps_enrich.json', encoding='utf-8')) if not g['missing']]
forms = {}
ready, skipped = [], []
for g in cands:
    d = s.get(f"{API}/v2/pim/products/{g['id']}", timeout=60)
    if d.status_code == 401: login(); d = s.get(f"{API}/v2/pim/products/{g['id']}", timeout=60)
    d = d.json()
    if d.get('status') != 'enrich' or 'moderating' not in (d.get('availabilityTransitions') or []):
        skipped.append((g['sku'], f"статус {d.get('status')}, переходи {d.get('availabilityTransitions')}")); continue
    code = d.get('attributeSetCode')
    if code not in forms:
        f = s.get(f'{API}/v2/pim/products/forms/attribute-set/by-code/{code}/attributes', timeout=60).json()
        forms[code] = f.get('items') or []
    req = [str(x['code']) for x in forms[code] if x.get('isRequired')]
    have = {str(v['code']) for v in (d.get('attributeValues') or []) if v.get('value') not in (None, '', [])}
    miss = [c for c in req if c not in have]
    if miss:
        skipped.append((g['sku'], f'порожні обовʼязкові {miss}')); continue
    ready.append({'id': g['id'], 'sku': g['sku'], 'name': g['name'], 'cat': g['cat']})
print(f'кандидатів {len(cands)} · готових {len(ready)} · пропущено {len(skipped)}')
for k in skipped[:8]: print('  пропущено:', k)
json.dump(ready, open(f'{SP}/sent_to_moderation.json', 'w', encoding='utf-8'), ensure_ascii=False)
if '--plan' in sys.argv or not ready:
    print('[plan] нічого не надсилаю'); sys.exit(0)
consent_require('epicentr_moderate', f'{len(ready)} карток noire → moderating')
ok = fail = 0
for i in range(0, len(ready), 50):
    part = ready[i:i+50]
    r = s.patch(f'{API}/v2/pim/products/common/status/batch',
                json={'collection': [{'productId': x['id'], 'statusCode': 'moderating'} for x in part]}, timeout=90)
    if r.status_code in (200, 202, 204): ok += len(part)
    else: fail += len(part); print('  партія', i//50+1, r.status_code, r.text[:200])
    time.sleep(1)
print(f'переведено: {ok} · не вдалось: {fail}')
