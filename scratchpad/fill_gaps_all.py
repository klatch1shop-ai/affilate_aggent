"""Прогін «два джерела» по ВСІХ картках noire у enrich. ЛИШЕ ЧИТАННЯ, нічого не записуємо.

Розширення two_sources.py на весь бэклог (1849 карток) з:
  - контрольним переривником: N підряд провалів ОБОХ джерел → стоп, а не мовчазне марнування;
  - контрольними точками кожні 25 карток (не втратити прогрес при перериванні);
  - обліком, скільки разів довелось ескалювати на Codex (`llm-escalation`).
"""
import base64, collections, json, os, re, sys, tempfile, time, requests
sys.path.insert(0, os.path.expanduser('~/agent-system'))
from dotenv import load_dotenv; load_dotenv(os.path.expanduser('~/agent-system/.env'))
from shared.utils.db import get_connection
from shared.utils.llm_router import call_codex, CodexLimitError

SP = os.path.dirname(os.path.abspath(__file__))
API = 'https://core-api.epicentrm.com.ua'
GEM = 'https://generativelanguage.googleapis.com/v1beta/models'
MODEL = os.getenv('PILOT_MODEL', 'gemini-flash-lite-latest')
KEY = os.getenv('GEMINI_API_KEY')
CHECKPOINT = f'{SP}/fill_gaps_all_progress.json'
BREAKER_LIMIT = 20          # підряд провалів обох джерел — стоп
MAX_ATTRS_PER_CARD = 2
MAX_CODEX_CALLS = int(os.getenv('MAX_CODEX_CALLS', '60'))   # бюджет ескалацій за прогін (спільна квота Codex)
codex_calls = 0

s = requests.Session()
def login():
    r = s.post(f'{API}/v2/users/login', json={'login': os.getenv('EPICENTR_EMAIL'),
               'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40); r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"
login()

NOT_SEEN = ('НЕ ВИДНО', 'НЕ ВКАЗАНО')
clean = lambda t: re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', t or '')).strip()
same = lambda a, b: re.sub(r'[^0-9a-zа-яіїєґ]', '', a.lower())[:12] == \
                    re.sub(r'[^0-9a-zа-яіїєґ]', '', b.lower())[:12]
is_fail = lambda t: t.startswith('HTTP') or t.startswith('CODEX_FAIL')


def gemini(parts, escalation_prompt=None, image_bytes=None):
    body = {'contents': [{'parts': parts}], 'generationConfig': {'temperature': 0.0, 'maxOutputTokens': 300}}
    for attempt in range(2):
        try:
            g = requests.post(f'{GEM}/{MODEL}:generateContent', timeout=180,
                              headers={'x-goog-api-key': KEY}, json=body)
        except requests.RequestException as e:
            g = None
            last_err = str(e)[:120]
            break
        if g.status_code == 200:
            j = g.json()
            p = ((j.get('candidates') or [{}])[0].get('content') or {}).get('parts') or []
            txt = ''.join(x.get('text', '') for x in p if not x.get('thought')).strip()
            if txt:
                return txt, (j.get('usageMetadata') or {}).get('totalTokenCount', 0), 'gemini'
            last_err = 'порожня відповідь'
        elif g.status_code == 503:
            time.sleep(3); continue
        else:
            last_err = f'HTTP{g.status_code}'
        break
    if not escalation_prompt:
        return f'HTTP{"?" if g is None else g.status_code}', 0, 'gemini'
    global codex_calls
    if codex_calls >= MAX_CODEX_CALLS:
        return 'CODEX_FAIL:бюджет ескалацій вичерпано', 0, 'codex'
    codex_calls += 1
    img_path = None
    try:
        if image_bytes:
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                f.write(image_bytes); img_path = f.name
        txt, _ = call_codex(escalation_prompt, image_path=img_path, timeout=180)
        return txt, 0, 'codex'
    except CodexLimitError as e:
        print(f'\nСТОП: вичерпано ліміт Codex — {e}', flush=True)
        save_checkpoint(state)
        sys.exit(3)
    except Exception as e:
        return f'CODEX_FAIL:{type(e).__name__}:{str(e)[:80]}', 0, 'codex'
    finally:
        if img_path:
            try: os.unlink(img_path)
            except OSError: pass


def ask_photo(img_bytes, mime, attr):
    q = (f'На фото — товар. Визнач характеристику «{attr}» САМОГО ВИРОБУ (не упаковки, не фону). '
         f'Відповідай коротко, українською, лише значення. Якщо визначити неможливо — НЕ ВИДНО.')
    return gemini([{'text': q}, {'inlineData': {'mimeType': mime,
                   'data': base64.b64encode(img_bytes).decode()}}],
                   escalation_prompt=q, image_bytes=img_bytes), q


def ask_text(desc, name, attr):
    q = (f'Ось назва та опис товару від постачальника.\n\nНАЗВА: {name}\n\nОПИС: {desc[:4000]}\n\n'
         f'Визнач характеристику «{attr}». Бери ЛИШЕ те, що прямо написано в тексті — не здогадуйся. '
         f'Відповідай коротко, українською, лише значення. Якщо в тексті цього нема — НЕ ВКАЗАНО.')
    return gemini([{'text': q}], escalation_prompt=q), q


def load_checkpoint():
    if os.path.exists(CHECKPOINT):
        return json.load(open(CHECKPOINT, encoding='utf-8'))
    return {'done_skus': [], 'rows': [], 'tally': {}}


def save_checkpoint(state):
    json.dump(state, open(CHECKPOINT, 'w', encoding='utf-8'), ensure_ascii=False)


gaps = json.load(open(f'{SP}/gaps_enrich.json', encoding='utf-8'))
cards = [g for g in gaps if g['missing'] and g['media'] >= 1]
print(f'усього карток із прогалинами й фото: {len(cards)} із {len(gaps)}')

state = load_checkpoint()
done = set(state['done_skus'])
cur = get_connection().cursor()

streak_fail = 0
t_start = time.time()
processed = 0
for i, c in enumerate(cards, 1):
    if c['sku'] in done:
        continue
    cur.execute('select description_html, name from sexopt_products where sku = %s', (c['sku'],))
    row = cur.fetchone()
    if not row:
        state['done_skus'].append(c['sku']); continue
    desc, name = clean(row['description_html']), row['name']

    d = None
    for _ in range(2):
        r = s.get(f"{API}/v2/pim/products/{c['id']}", timeout=60)
        if r.status_code == 401:
            login(); continue
        if r.status_code == 200:
            d = r.json(); break
    if not d:
        state['done_skus'].append(c['sku']); processed += 1; continue
    media = [m for m in (d.get('media') or []) if m.get('source')]
    if not media:
        state['done_skus'].append(c['sku']); processed += 1; continue
    url = (next((m for m in media if m.get('isMain')), media[0]))['source']
    img = requests.get(url, timeout=60)
    if img.status_code != 200:
        state['done_skus'].append(c['sku']); processed += 1; continue
    mime = img.headers.get('Content-Type', 'image/jpeg')

    for code, attr, typ in c['missing'][:MAX_ATTRS_PER_CARD]:
        (a, t1, src_a), qa = ask_photo(img.content, mime, attr)
        (b, t2, src_b), qb = ask_text(desc, name, attr)

        if is_fail(a) or is_fail(b):
            streak_fail += 1
            verdict = 'помилка запиту'
        else:
            streak_fail = 0
            a_un, b_un = any(x in a.upper() for x in NOT_SEEN), any(x in b.upper() for x in NOT_SEEN)
            if a_un and b_un: verdict = 'обидва не знають'
            elif a_un or b_un: verdict = 'лише одне джерело'
            elif same(a, b): verdict = 'ЗБІГ'
            else: verdict = 'РОЗБІЖНІСТЬ'
        state['tally'][verdict] = state['tally'].get(verdict, 0) + 1
        state['rows'].append({'sku': c['sku'], 'attr': attr, 'code': code, 'photo': a, 'text': b,
                              'verdict': verdict, 'url': url, 'src_photo': src_a, 'src_text': src_b})
        if streak_fail >= BREAKER_LIMIT:
            print(f'\nСТОП: {BREAKER_LIMIT} підряд провалів обох джерел — щось зламалось, не продовжую.')
            save_checkpoint(state)
            sys.exit(2)

    state['done_skus'].append(c['sku'])
    processed += 1
    if processed % 25 == 0:
        save_checkpoint(state)
        el = time.time() - t_start
        print(f'  {len(done) + processed}/{len(cards)} · {el:.0f}с · тальї {state["tally"]}', flush=True)

save_checkpoint(state)
print(f'\nГОТОВО. Оброблено карток: {len(state["done_skus"])} із {len(cards)}')
print('підсумок:', state['tally'])
codex_used = sum(1 for r in state['rows'] if 'codex' in (r['src_photo'], r['src_text']))
print(f'з ескалацією на Codex: {codex_used} із {len(state["rows"])} перевірок характеристик')
