"""Знімок кабінету Епіцентру з countComments. ЛИШЕ ЧИТАННЯ."""
import os, sys, json, time, requests
sys.path.insert(0, os.path.expanduser('~/agent-system'))
from dotenv import load_dotenv; load_dotenv(os.path.expanduser('~/agent-system/.env'))
API = 'https://core-api.epicentrm.com.ua'
OUT = sys.argv[1]
s = requests.Session()
def login():
    r = s.post(f'{API}/v2/users/login', json={'login': os.getenv('EPICENTR_EMAIL'),
               'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40); r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"
login()
noire = {x['id'] for x in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'noire_all.json'), encoding='utf-8'))}
rows, nxt, page = [], None, 0
while True:
    p = {'limit': 100}
    if nxt: p['cursor'] = nxt
    for attempt in range(4):
        try: r = s.get(f'{API}/v2/pim/products', params=p, timeout=90)
        except requests.RequestException: time.sleep(5); continue
        if r.status_code == 401: login(); continue
        if r.status_code == 200: break
        time.sleep(3 * (attempt + 1))
    if r.status_code != 200: print('стоп', r.status_code); break
    d = r.json(); items = d.get('items') or []
    for it in items:
        if it.get('id') in noire:
            rows.append({'id': it['id'], 'sku': it.get('sku'), 'status': it.get('status'),
                         'comments': it.get('countComments'), 'completeness': it.get('completeness')})
    page += 1; nxt = d.get('next')
    if page % 40 == 0: print(f'  сторінка {page}, noire {len(rows)}', flush=True)
    if not nxt or not items: break
json.dump(rows, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
print('noire у знімку:', len(rows), '→', OUT)
