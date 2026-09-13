#!/usr/bin/env python3
"""Зняти мішане написання зі словників перекладу TOPTUL — один раз і назавжди.

Навіщо. `toptul_rozetka_generator.py` виправляє мішане написання в тексті
фіду ДО пошуку в словнику. Ключі ж словників збиралися з сирого тексту
постачальника, а він мішаний: `Вороток 1/2" Г-образный большой (Мотор Сiч)
В12ГМС` — з латинською `i`. Виправлений текст такого ключа не знаходить.

Це не здогад: на першому прогоні 01.09.2026 саме цей рядок повернувся у фід
російським — «Г-образный большой» замість «Г-образний великий», — і жоден
лічильник про втрату не сказав. Переклад не зник, він просто перестав
збігатися.

Генератор тримає запобіжник (`_hg()` при завантаженні словників), тож фід
правильний і без цієї міграції. Але `toptul_desc_translate.py` відрізняє
перекладене від неперекладеного за САМИМ РЯДКОМ, і доки в базі лежить
мішаний ключ, а `collect()` віддає виправлений, усі 728 речень виглядають
неперекладеними — це кілька годин запитів до NVIDIA за вже зроблену роботу.

Виправляються ОБИДВІ половини пари. У 46 випадках мішане написання лежить у
самому перекладі — модель скопіювала зіпсовану літеру з оригіналу.

Скрипт ідемпотентний: другий прогін не змінює нічого. Зіткнення ключів
(два різні `src` після виправлення стають одним) — відмова, а не мовчазне
перезаписування: за таким зіткненням стоять два різні переклади, і вибір між
ними скрипт зробити не може.

    python3 tools/toptul_homoglyph_normalize.py            # лише замір
    python3 tools/toptul_homoglyph_normalize.py --apply
"""
import argparse
import collections
import hashlib
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))

import psycopg2.extras  # noqa: E402
from loguru import logger  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402
from homoglyph import fix_text  # noqa: E402


def _n(s):
    return fix_text(s or '')[0]


def _h(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    stats = collections.Counter()
    clashes = []

    # ── toptul_translation: PRIMARY KEY (kind, src) ────────────────────────
    cur.execute('SELECT kind, src, dst FROM toptul_translation')
    rows = cur.fetchall()
    seen = collections.defaultdict(dict)
    plan1 = []
    for r in rows:
        seen[r['kind']].setdefault(_n(r['src']), []).append(r)
    for kind, groups in seen.items():
        for key, group in groups.items():
            if len(group) > 1:
                dsts = {g['dst'] for g in group}
                if len(dsts) > 1:
                    clashes.append((kind, key, sorted(dsts)))
                    continue
    for r in rows:
        ns, nd = _n(r['src']), _n(r['dst'])
        if (ns, nd) == (r['src'], r['dst']):
            continue
        if any(c[0] == r['kind'] and c[1] == ns for c in clashes):
            continue
        plan1.append((r['kind'], r['src'], ns, nd))
        stats[f'toptul_translation/{r["kind"]}'] += 1

    # ── toptul_desc_translation: PRIMARY KEY src_hash ──────────────────────
    cur.execute('SELECT src_hash, src, dst FROM toptul_desc_translation')
    drows = cur.fetchall()
    by_new = collections.defaultdict(list)
    for r in drows:
        by_new[_n(r['src'])].append(r)
    plan2 = []
    for key, group in by_new.items():
        if len(group) > 1 and len({g['dst'] for g in group}) > 1:
            clashes.append(('desc', key, sorted({g['dst'] for g in group})))
            continue
        for r in group:
            ns, nd = key, _n(r['dst'])
            if (ns, nd) == (r['src'], r['dst']):
                continue
            plan2.append((r['src_hash'], ns, _h(ns), nd))
            stats['toptul_desc_translation'] += 1

    logger.info('Рядків зі мішаним написанням у ключі або перекладі:')
    for k, v in sorted(stats.items()):
        logger.info(f'   {k}: {v}')
    logger.info(f'   разом: {sum(stats.values())}')
    if clashes:
        logger.error(f'ЗІТКНЕННЯ КЛЮЧІВ: {len(clashes)} — не чіпаю їх')
        for kind, key, dsts in clashes[:10]:
            logger.error(f'   {kind}: {key[:70]!r} → {dsts}')

    if not a.apply:
        logger.info('Це лише замір. Записати: --apply')
        return 1 if clashes else 0

    for kind, old, ns, nd in plan1:
        cur.execute('UPDATE toptul_translation SET src=%s, dst=%s '
                    'WHERE kind=%s AND src=%s', (ns, nd, kind, old))
    for old_hash, ns, nh, nd in plan2:
        cur.execute('UPDATE toptul_desc_translation '
                    'SET src=%s, src_hash=%s, dst=%s WHERE src_hash=%s',
                    (ns, nh, nd, old_hash))
    conn.commit()
    logger.success(f'Оновлено: {len(plan1)} + {len(plan2)} рядків')

    # Контроль після запису: другий прохід мусить не знайти нічого.
    cur.execute('SELECT src, dst FROM toptul_translation')
    left = sum(1 for r in cur.fetchall()
               if _n(r['src']) != r['src'] or _n(r['dst']) != r['dst'])
    cur.execute('SELECT src, dst FROM toptul_desc_translation')
    left += sum(1 for r in cur.fetchall()
                if _n(r['src']) != r['src'] or _n(r['dst']) != r['dst'])
    logger.info(f'Контроль ідемпотентності: лишилось {left} '
                f'(мусить бути 0, крім зіткнень: {len(clashes)})')
    return 0 if left == len(clashes) else 1


if __name__ == '__main__':
    sys.exit(main())
