#!/usr/bin/env python3
"""Мертві рядки зіставлення категорій Prom — рішення, які не діють.

Навіщо (AGENT_RULES 11.8): у `prom_category_mapping` рядок 78 для олій
(«→ Масажні косметичні засоби», 09.08.2026) місяць не діяв — генератор
брав старший рядок 25. Запис існував, і його існування приймали за дію.

Інструмент проганяє ті самі функції, що й генератор (`load_mapping`,
`resolve_category`), по живих товарах і для кожного рядка рахує, скільки
товарів він ВИГРАВ. Рядок коду, для якого є товари, але який не виграв жодного
разу, — мертвий: або дубль, або правило за назвою, що нічого не ловить, або
перекритий іншим рядком. Порожні коди (товарів немає зараз) — окремо.

Лише читання БД.

    python3 tools/prom_mapping_audit.py
"""
import collections
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'tools'))
sys.path.append(BASE)

import psycopg2.extras  # noqa: E402
import noire_prom_generator as G  # noqa: E402


def main():
    conn = G.get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    mapping = G.load_mapping(cur)
    products = G.load_products(cur)
    cur.execute("""SELECT id, epicentr_code, prom_category_id, name_rule, confidence
                   FROM prom_category_mapping WHERE source='noire'""")
    rows = {(r['epicentr_code'], r['prom_category_id'], r['name_rule']): r for r in cur.fetchall()}

    wins, per_code = collections.Counter(), collections.Counter()
    for p in products:
        per_code[p['ec']] += 1
        for pid, rule, excluded in mapping.get(p['ec'], []):
            if rule and not G.re.search(rule, p['name'] or '', G.re.I):
                continue
            wins[(p['ec'], pid, rule)] += 1
            break

    dead, idle = [], []
    for key, r in sorted(rows.items(), key=lambda kv: kv[1]['id']):
        if wins[key]:
            continue
        (dead if per_code[key[0]] else idle).append(r)
    print(f'рядків: {len(rows)} · товарів: {len(products)} · '
          f'мертвих (товари коду є, рядок не виграв жодного): {len(dead)} · '
          f'кодів без товарів зараз: {len(idle)}')
    for r in dead:
        rule = f" правило «{r['name_rule']}»" if r['name_rule'] else ''
        print(f"  ✗ id {r['id']}: {r['epicentr_code']} → {r['prom_category_id']}"
              f"{rule}, впевненість {r['confidence']} — товарів коду {per_code[r['epicentr_code']]}")


if __name__ == '__main__':
    main()
