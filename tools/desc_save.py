# -*- coding: utf-8 -*-
"""Збереження вручну написаних описів + лог прогресу."""
import re, sys, psycopg2
LOG = '/home/tekken/agent-system/output/description_writing_progress.log'
TOTAL = 487

def save(items):
    """items: {sku: (name, text)} або {sku: (name, None)} для needs_review"""
    c = psycopg2.connect(host='192.168.3.28', dbname='agentdb',
                         user='agentadmin', password='1')
    c.autocommit = True
    cur = c.cursor()
    bad = []
    for sku, (name, txt) in items.items():
        if txt is None:
            cur.execute("""INSERT INTO sexopt_generated_descriptions
                (sku, description_text, source, model, char_len, needs_review)
                VALUES (%s,NULL,'claude_manual','claude',0,TRUE)
                ON CONFLICT (sku) DO UPDATE SET needs_review=TRUE,
                  source='claude_manual', generated_at=NOW()""", (sku,))
            continue
        n = len(txt)
        key = re.split(r' - | – ', name)[0][:40]
        prob = []
        if not (400 <= n <= 800): prob.append(f'довжина {n}')
        if '!' in txt: prob.append('оклик')
        if len(re.findall(re.escape(key), txt)) > 1: prob.append('назва 2+')
        if re.findall(r'\b\w*(?:[а-яїієґ][a-z]|[a-z][а-яїієґ])\w*\b', txt, re.I):
            prob.append('латиниця')
        if prob: bad.append((sku, prob))
        cur.execute("""INSERT INTO sexopt_generated_descriptions
            (sku, description_text, source, model, char_len, needs_review)
            VALUES (%s,%s,'claude_manual','claude',%s,FALSE)
            ON CONFLICT (sku) DO UPDATE SET description_text=EXCLUDED.description_text,
              source='claude_manual', char_len=EXCLUDED.char_len,
              needs_review=FALSE, generated_at=NOW()""", (sku, txt, n))
    cur.execute("SELECT count(*), count(*) FILTER (WHERE needs_review) "
                "FROM sexopt_generated_descriptions WHERE source='claude_manual'")
    done, nr = cur.fetchone()
    if bad:
        print('ПРОБЛЕМИ:', bad)
    print(f'збережено пачку: {len(items)} | всього {done}/{TOTAL} | needs_review {nr}')
    if done % 20 < len(items):
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(f'готово {done} / залишилось {TOTAL-done} / needs_review {nr}\n')
    return done
