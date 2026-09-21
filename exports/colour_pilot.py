"""Пілот: Gemini визначає колір товару з фото. ЛИШЕ ЧИТАННЯ, нічого не записуємо."""
import base64, json, os, sys, requests
sys.path.insert(0, os.path.expanduser('~/agent-system'))
from dotenv import load_dotenv; load_dotenv(os.path.expanduser('~/agent-system/.env'))
SP = os.path.dirname(os.path.abspath(__file__))
API = 'https://core-api.epicentrm.com.ua'
GEM = 'https://generativelanguage.googleapis.com/v1beta/models'
MODEL = 'gemini-3-flash-preview'
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5

s = requests.Session()
r = s.post(f'{API}/v2/users/login', json={'login': os.getenv('EPICENTR_EMAIL'),
           'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40); r.raise_for_status()
s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"

gaps = json.load(open(f'{SP}/gaps_enrich.json', encoding='utf-8'))
cards = [g for g in gaps if g['missing'] and all('Колір' in m[1] for m in g['missing'])
         and g['media'] >= 1][:N]

QUESTION = ('На фото — товар. Назви ОДНИМ словом основний колір самого виробу українською '
            '(не упаковки, не фону). Якщо на фото кілька кольорів — назви домінуючий. '
            'Якщо виріб не видно або колір визначити неможливо — відповідай точно: НЕ ВИДНО. '
            'Не пояснюй, не вигадуй, поверни лише одне слово.')

print(f'{"SKU":<10} {"з фото":<16} {"з назви":<16} назва')
rows = []
for c in cards:
    d = s.get(f"{API}/v2/pim/products/{c['id']}", timeout=60).json()
    media = [m for m in (d.get('media') or []) if m.get('source')]
    if not media:
        continue
    url = (next((m for m in media if m.get('isMain')), media[0]))['source']
    img = requests.get(url, timeout=60)
    if img.status_code != 200:
        print(f"{c['sku']:<10} фото не завантажилось ({img.status_code})"); continue
    body = {'contents': [{'parts': [
        {'text': QUESTION},
        {'inlineData': {'mimeType': img.headers.get('Content-Type', 'image/jpeg'),
                        'data': base64.b64encode(img.content).decode()}}]}],
        'generationConfig': {'temperature': 0.0, 'maxOutputTokens': 200}}
    g = requests.post(f'{GEM}/{MODEL}:generateContent', timeout=180,
                      headers={'x-goog-api-key': os.getenv('GEMINI_API_KEY')}, json=body)
    if g.status_code != 200:
        print(f"{c['sku']:<10} Gemini HTTP {g.status_code} {g.text[:90]}"); continue
    j = g.json()
    parts = ((j.get('candidates') or [{}])[0].get('content') or {}).get('parts') or []
    ans = ''.join(p.get('text', '') for p in parts if not p.get('thought')).strip()
    usage = j.get('usageMetadata') or {}
    # колір із назви — детерміновано, для звірки
    WORDS = ('чорн', 'біл', 'червон', 'рожев', 'синь', 'блакитн', 'зелен', 'фіолетов', 'бузков',
             'жовт', 'помаранчев', 'сріб', 'золот', 'прозор', 'тілесн', 'бежев', 'сір', 'корич',
             'black', 'white', 'red', 'pink', 'blue', 'green', 'purple', 'violet', 'clear')
    low = (c['name'] or '').lower()
    from_name = next((w for w in WORDS if w in low), '—')
    print(f"{c['sku']:<10} {ans[:15]:<16} {from_name:<16} {c['name'][:46]}")
    rows.append({'sku': c['sku'], 'photo': ans, 'name_hint': from_name, 'name': c['name'],
                 'url': url, 'tokens': usage.get('totalTokenCount')})
json.dump(rows, open(f'{SP}/colour_pilot.json', 'w', encoding='utf-8'), ensure_ascii=False)
print('\nтокенів разом:', sum(r['tokens'] or 0 for r in rows), '· карток:', len(rows))
