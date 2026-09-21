"""Чого бракує карткам noire у статусі enrich. ЛИШЕ ЧИТАННЯ."""
import os, sys, json, time, collections, requests
sys.path.insert(0, os.path.expanduser('~/agent-system'))
from dotenv import load_dotenv; load_dotenv(os.path.expanduser('~/agent-system/.env'))
SP = os.path.dirname(os.path.abspath(__file__))
API = 'https://core-api.epicentrm.com.ua'
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 120
STATUS = sys.argv[2] if len(sys.argv) > 2 else 'enrich'

s = requests.Session()


def login():
    r = s.post(f'{API}/v2/users/login', json={'login': os.getenv('EPICENTR_EMAIL'),
               'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def ua(o):
    for t in (o or {}).get('translations', []):
        if t.get('languageCode') == 'ua':
            return t.get('value') or t.get('title')
    return None


def get(url, **kw):
    for _ in range(3):
        r = s.get(url, timeout=90, **kw)
        if r.status_code == 401:
            login(); continue
        if r.status_code == 200:
            return r.json()
        time.sleep(2)
    return None


login()
noire = json.load(open(f'{SP}/noire_all.json', encoding='utf-8'))
cards = [x for x in noire if x['status'] == STATUS][:LIMIT]
forms, gaps, per_card, no_desc, few_media = {}, collections.Counter(), [], 0, 0
for i, c in enumerate(cards, 1):
    d = get(f"{API}/v2/pim/products/{c['id']}")
    if not d:
        continue
    code = d.get('attributeSetCode')
    if code not in forms:
        f = get(f'{API}/v2/pim/products/forms/attribute-set/by-code/{code}/attributes') or {}
        forms[code] = f.get('items') or f.get('data') or (f if isinstance(f, list) else [])
    filled = {a['code'] for a in (d.get('attributeValues') or [])}
    req = [x for x in forms[code] if x.get('isRequired') or x.get('required')]
    miss = [(x.get('code'), ua(x) or x.get('code'), x.get('type')) for x in req if x.get('code') not in filled]
    for m in miss:
        gaps[f'{m[1]} [{m[0]}]'] += 1
    tr = [t for t in d.get('translations', []) if t.get('languageCode') == 'ua']
    has_desc = bool((tr[0].get('description') if tr else None) or d.get('description'))
    if not has_desc:
        no_desc += 1
    media = len(d.get('media') or [])
    if media < 2:
        few_media += 1
    per_card.append({'sku': c['our_sku'], 'id': c['id'], 'cat': c['cat'], 'set': code,
                     'completeness': c['completeness'], 'missing': miss,
                     'media': media, 'has_desc': has_desc, 'name': c['name']})
    if i % 30 == 0:
        print(f'  {i}/{len(cards)}', flush=True)

json.dump(per_card, open(f'{SP}/gaps_{STATUS}.json', 'w', encoding='utf-8'), ensure_ascii=False)
n = len(per_card)
counts = collections.Counter(len(p['missing']) for p in per_card)
print(f'\nперевірено карток: {n} (статус {STATUS})')
print('скільки обовʼязкових бракує:', dict(sorted(counts.items())))
print(f'без опису ua: {no_desc} · менше 2 фото: {few_media}')
print('\nнайчастіші порожні обовʼязкові:')
for name, k in gaps.most_common(15):
    print(f'  {k:>4}  {name}')
