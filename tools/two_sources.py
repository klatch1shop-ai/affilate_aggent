"""Два незалежні джерела на ту саму характеристику: ФОТО і ОПИС. Звіряємо їх між собою.

Ідея: людина дивиться не все, а лише РОЗБІЖНОСТІ. Збіг двох джерел — кандидат на запис,
розбіжність або «не видно» — у чергу до власника. Нічого не записуємо.
"""
import base64, collections, json, os, re, sys, requests
sys.path.insert(0, os.path.expanduser('~/agent-system'))
from dotenv import load_dotenv; load_dotenv(os.path.expanduser('~/agent-system/.env'))
from shared.utils.db import get_connection
SP = os.path.dirname(os.path.abspath(__file__))
API = 'https://core-api.epicentrm.com.ua'
GEM = 'https://generativelanguage.googleapis.com/v1beta/models'
MODEL = os.getenv('PILOT_MODEL', 'gemini-flash-lite-latest')
N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
KEY = os.getenv('GEMINI_API_KEY')

s = requests.Session()
r = s.post(f'{API}/v2/users/login', json={'login': os.getenv('EPICENTR_EMAIL'),
           'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40); r.raise_for_status()
s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"

NOT_SEEN = ('НЕ ВИДНО', 'НЕ ВКАЗАНО')


def gemini(parts):
    body = {'contents': [{'parts': parts}],
            'generationConfig': {'temperature': 0.0, 'maxOutputTokens': 300}}
    g = requests.post(f'{GEM}/{MODEL}:generateContent', timeout=180,
                      headers={'x-goog-api-key': KEY}, json=body)
    if g.status_code != 200:
        return f'HTTP{g.status_code}', 0
    j = g.json()
    p = ((j.get('candidates') or [{}])[0].get('content') or {}).get('parts') or []
    txt = ''.join(x.get('text', '') for x in p if not x.get('thought')).strip()
    return txt, (j.get('usageMetadata') or {}).get('totalTokenCount', 0)


def ask_photo(img_bytes, mime, attr):
    q = (f'На фото — товар. Визнач характеристику «{attr}» САМОГО ВИРОБУ (не упаковки, не фону). '
         f'Відповідай коротко, українською, лише значення — без пояснень і без одиниць у дужках. '
         f'Якщо з фото це визначити неможливо — відповідай точно: НЕ ВИДНО.')
    return gemini([{'text': q}, {'inlineData': {'mimeType': mime,
                   'data': base64.b64encode(img_bytes).decode()}}])


def ask_text(desc, name, attr):
    q = (f'Ось назва та опис товару від постачальника.\n\nНАЗВА: {name}\n\nОПИС: {desc[:4000]}\n\n'
         f'Визнач характеристику «{attr}». Бери ЛИШЕ те, що прямо написано в тексті — '
         f'не здогадуйся, не виводь із бренду чи категорії. Відповідай коротко, українською, '
         f'лише значення. Якщо в тексті цього нема — відповідай точно: НЕ ВКАЗАНО.')
    return gemini([{'text': q}])


clean = lambda t: re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', t or '')).strip()
same = lambda a, b: re.sub(r'[^0-9a-zа-яіїєґ]', '', a.lower())[:12] == \
                    re.sub(r'[^0-9a-zа-яіїєґ]', '', b.lower())[:12]

gaps = json.load(open(f'{SP}/gaps_enrich.json', encoding='utf-8'))
cards = [g for g in gaps if g['missing'] and g['media'] >= 1][:N]
cur = get_connection().cursor()
cur.execute('select sku, description_html, name from sexopt_products where sku = any(%s)',
            ([c['sku'] for c in cards],))
db = {r['sku']: r for r in cur.fetchall()}

tally, rows, tok = collections.Counter(), [], 0
print(f'{"SKU":<9} {"характеристика":<22} {"з ФОТО":<18} {"з ОПИСУ":<18} вердикт')
for c in cards:
    d = s.get(f"{API}/v2/pim/products/{c['id']}", timeout=60).json()
    media = [m for m in (d.get('media') or []) if m.get('source')]
    if not media or c['sku'] not in db:
        continue
    url = (next((m for m in media if m.get('isMain')), media[0]))['source']
    img = requests.get(url, timeout=60)
    if img.status_code != 200:
        continue
    desc = clean(db[c['sku']]['description_html'])
    for code, attr, typ in c['missing'][:2]:                 # не більше 2 на картку
        a, t1 = ask_photo(img.content, img.headers.get('Content-Type', 'image/jpeg'), attr)
        b, t2 = ask_text(desc, db[c['sku']]['name'], attr)
        tok += t1 + t2
        # Помилка транспорту — це НЕ відповідь. Інакше «HTTP429 == HTTP429» рахувалось
        # як збіг і роздувало точність (спіймано на першому ж прогоні 21.09).
        if a.startswith('HTTP') or b.startswith('HTTP'):
            tally['помилка запиту'] += 1
            rows.append({'sku': c['sku'], 'attr': attr, 'code': code, 'photo': a, 'text': b,
                         'verdict': 'помилка запиту', 'url': url})
            print(f"{c['sku']:<9} {attr[:21]:<22} {a[:17]:<18} {b[:17]:<18} помилка запиту")
            continue
        a_un, b_un = any(x in a.upper() for x in NOT_SEEN), any(x in b.upper() for x in NOT_SEEN)
        if a_un and b_un:
            v = 'обидва не знають'
        elif a_un or b_un:
            v = 'лише одне джерело'
        elif same(a, b):
            v = 'ЗБІГ'
        else:
            v = 'РОЗБІЖНІСТЬ'
        tally[v] += 1
        rows.append({'sku': c['sku'], 'attr': attr, 'code': code, 'photo': a, 'text': b,
                     'verdict': v, 'url': url})
        print(f"{c['sku']:<9} {attr[:21]:<22} {a[:17]:<18} {b[:17]:<18} {v}")
json.dump(rows, open(f'{SP}/two_sources.json', 'w', encoding='utf-8'), ensure_ascii=False)
print('\nпідсумок:', dict(tally), '· токенів:', tok, '· модель:', MODEL)
