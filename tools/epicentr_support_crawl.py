"""
tools/epicentr_support_crawl.py
================================
Зберігає довідку Єпіцентру (supportm.epicentrk.ua) локально в docs/epicentr_support/.

Кожна сторінка лягає окремим .md із заголовком-джерелом:
    url, назва, sha256 тексту, дата зняття.

Навіщо sha256: довідка постачальника змінюється без попередження, і ми
про це дізнаємось тільки з наслідків. Хеш дозволяє наступним запуском
показати «ця сторінка змінилась із часу, коли ми на неї спиралися».

Запуск:  venv/bin/python3 tools/epicentr_support_crawl.py [--refresh]
"""
import os, re, sys, time, json, hashlib
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

BASE   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(BASE, 'docs', 'epicentr_support')
INDEX  = os.path.join(OUTDIR, 'index.json')
ROOT   = 'https://supportm.epicentrk.ua/'
HOST   = 'supportm.epicentrk.ua'
UA     = 'Mozilla/5.0 (compatible; noire-feed-docs/1.0)'
PAUSE  = 1.5          # сайт чужий — не тиснемо
SKIP   = re.compile(r'\.(css|js|png|jpe?g|gif|svg|woff2?|ico|pdf|zip)(\?|$)', re.I)


def clean_url(u):
    u = urljoin(ROOT, u.split('#')[0])
    p = urlparse(u)
    if p.netloc != HOST:
        return None
    if SKIP.search(p.path) or p.path.startswith('/bitrix/') or p.path.startswith('/local/'):
        return None
    return f'https://{HOST}{p.path}'          # без query: ?q=... це пошуковий шум


def slug(url):
    s = urlparse(url).path.strip('/') or 'index'
    return re.sub(r'[^a-z0-9_-]+', '_', s.lower())[:80]


def extract(html):
    soup = BeautifulSoup(html, 'html.parser')
    for bad in soup(['script', 'style', 'noscript']):
        bad.decompose()
    title = (soup.title.get_text(strip=True) if soup.title else '')
    parts = []
    for el in soup.find_all(['h1', 'h2', 'h3', 'h4', 'li', 'p', 'td', 'th']):
        t = el.get_text(' ', strip=True)
        if not t or len(t) < 2:
            continue
        if el.name.startswith('h'):
            parts.append('\n' + '#' * int(el.name[1]) + ' ' + t)
        elif el.name == 'li':
            parts.append('- ' + t)
        else:
            parts.append(t)
    # прибираємо повтори підряд (у Bitrix багато дублів у меню)
    out, prev = [], None
    for p in parts:
        if p != prev:
            out.append(p)
        prev = p
    return title, '\n'.join(out)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    old = json.load(open(INDEX, encoding='utf-8')) if os.path.exists(INDEX) else {}
    s = requests.Session()
    s.headers.update({'User-Agent': UA})

    seen, queue, index, changed = set(), [ROOT.rstrip('/') + '/'], {}, []
    queue = [clean_url(ROOT)]
    while queue:
        url = queue.pop(0)
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            r = s.get(url, timeout=45)
            if r.status_code != 200:
                print(f'  {r.status_code}  {url}', file=sys.stderr)
                continue
        except Exception as e:
            print(f'  ERR {url}: {e}', file=sys.stderr)
            continue

        title, text = extract(r.text)
        if len(text) < 200:                    # порожня/технічна сторінка
            continue
        h = hashlib.sha256(text.encode()).hexdigest()
        name = slug(url) + '.md'
        prev = old.get(url, {}).get('sha256')
        if prev and prev != h:
            changed.append(url)

        with open(os.path.join(OUTDIR, name), 'w', encoding='utf-8') as f:
            f.write(f'<!-- url: {url}\n'
                    f'     назва: {title}\n'
                    f'     sha256: {h}\n'
                    f'     знято: {time.strftime("%Y-%m-%d %H:%M")} -->\n\n')
            f.write(f'# {title}\n\n{text}\n')
        index[url] = {'file': name, 'title': title, 'sha256': h,
                      'fetched': time.strftime('%Y-%m-%d %H:%M'), 'chars': len(text)}
        print(f'  {len(text):6}  {name}')

        for a in BeautifulSoup(r.text, 'html.parser').find_all('a', href=True):
            u = clean_url(a['href'])
            if u and u not in seen:
                queue.append(u)
        time.sleep(PAUSE)

    with open(INDEX, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print(f'\nсторінок збережено: {len(index)} → {OUTDIR}')
    if changed:
        print(f'ЗМІНИЛОСЬ із минулого разу: {len(changed)}')
        for u in changed:
            print('  ', u)


if __name__ == '__main__':
    main()
