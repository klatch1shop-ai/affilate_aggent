"""
tools/epicentr_category_mapper.py
Fuzzy-match TOPTUL XML categories → Epicentr DB categories.
"""
import os, sys, re, requests
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

TOPTUL_FEED_URL = os.getenv('TOPTUL_FEED_URL', '')


# ── helpers ──────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Lowercase + collapse whitespace. Works across Cyrillic dialects."""
    return re.sub(r'\s+', ' ', (text or '').lower().strip())


def best_match(query: str, candidates: list[tuple]) -> tuple:
    """Return (score, code, name) with highest SequenceMatcher ratio."""
    q = normalize(query)
    best_score, best_code, best_name = 0.0, '', ''
    for code, name in candidates:
        score = SequenceMatcher(None, q, normalize(name)).ratio()
        if score > best_score:
            best_score, best_code, best_name = score, code, name
    return best_score, best_code, best_name


# ── fetch TOPTUL categories ───────────────────────────────────────────────────

def fetch_toptul_categories() -> list[tuple]:
    """Return list of (id, name) from TOPTUL XML feed."""
    print('Завантажуємо TOPTUL фід…', flush=True)
    r = requests.get(TOPTUL_FEED_URL, timeout=120)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    cats = root.find('shop').find('categories')
    if cats is None:
        return []
    result = []
    for c in cats.findall('category'):
        cid  = c.get('id', '')
        name = (c.text or '').strip()
        if cid and name:
            result.append((cid, name))
    print(f'TOPTUL: {len(result)} категорій', flush=True)
    return result


# ── fetch Epicentr categories from DB ────────────────────────────────────────

def fetch_epicentr_categories() -> list[tuple]:
    """Return list of (code, name_ua) from epicentr_categories."""
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT code, name_ua FROM epicentr_categories WHERE name_ua IS NOT NULL AND name_ua != ''")
    rows = cur.fetchall()
    cur.close(); conn.close()
    result = [(r['code'], r['name_ua']) for r in rows]
    print(f'Єпіцентр: {len(result)} категорій', flush=True)
    return result


# ── create / populate mapping table ──────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS toptul_epicentr_category_map (
    toptul_id      VARCHAR(50)   PRIMARY KEY,
    toptul_name    VARCHAR(500),
    epicentr_code  VARCHAR(50),
    epicentr_name  VARCHAR(500),
    score          NUMERIC(5,4),
    confirmed      BOOLEAN       DEFAULT FALSE
);
"""

def save_mapping(rows: list[dict]):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(DDL)
    for row in rows:
        cur.execute("""
            INSERT INTO toptul_epicentr_category_map
                (toptul_id, toptul_name, epicentr_code, epicentr_name, score, confirmed)
            VALUES (%(toptul_id)s, %(toptul_name)s, %(epicentr_code)s, %(epicentr_name)s,
                    %(score)s, FALSE)
            ON CONFLICT (toptul_id) DO UPDATE
            SET toptul_name   = EXCLUDED.toptul_name,
                epicentr_code = EXCLUDED.epicentr_code,
                epicentr_name = EXCLUDED.epicentr_name,
                score         = EXCLUDED.score
        """, row)
    conn.commit()
    cur.close(); conn.close()
    print(f'Збережено {len(rows)} записів у toptul_epicentr_category_map', flush=True)


# ── display ───────────────────────────────────────────────────────────────────

def print_table(rows: list[dict]):
    sep = '+' + '-'*14 + '+' + '-'*42 + '+' + '-'*7 + '+' + '-'*42 + '+'
    hdr = '| {:<12} | {:<40} | {:<5} | {:<40} |'.format(
        'TOPTUL ID', 'TOPTUL назва', 'Score', 'Єпіцентр назва'
    )
    print(sep)
    print(hdr)
    print(sep)
    for r in rows:
        tname = r['toptul_name'][:40]
        ename = r['epicentr_name'][:40]
        score = f"{float(r['score']):.3f}"
        print('| {:<12} | {:<40} | {:<5} | {:<40} |'.format(
            r['toptul_id'], tname, score, ename
        ))
    print(sep)
    print(f'Всього: {len(rows)} рядків')


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    toptul  = fetch_toptul_categories()
    epicentr = fetch_epicentr_categories()

    print('Матчимо категорії…', flush=True)
    mapping = []
    for i, (tid, tname) in enumerate(toptul, 1):
        score, ecode, ename = best_match(tname, epicentr)
        mapping.append({
            'toptul_id':    tid,
            'toptul_name':  tname,
            'epicentr_code': ecode,
            'epicentr_name': ename,
            'score':         round(score, 4),
        })
        if i % 50 == 0:
            print(f'  {i}/{len(toptul)}…', flush=True)

    mapping.sort(key=lambda r: r['score'], reverse=True)
    save_mapping(mapping)
    print()
    print_table(mapping)


if __name__ == '__main__':
    main()
