"""
tools/epicentr_mapping_review.py
=================================
Звіряє наш мапінг категорій (epicentr_category_mapping) з тим, що категорійний
менеджер Єпіцентру реально призначив карткам у кабінеті.

Менеджер — істина: категорію в кабінеті може змінити тільки він, і зміна
означає, що наш мапінг помилявся.

Джерела:
  data/epicentr_products.json      — стан кабінету (tools/epicentr_products_dump.py)
  sexopt_products                  — sku → sexopt_category_id
  epicentr_category_mapping        — наш мапінг

Тільки читання. Пропозиції друкує, нічого не змінює.
"""
import os, sys, json, collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.db import get_connection

MIN_CARDS = 5        # менше — статистики замало для висновку
MIN_SHARE = 0.60     # більшість, за якою визнаємо помилку мапінгу


def main():
    prods = [x for x in json.load(open(os.path.join(BASE, 'data', 'epicentr_products.json'),
                                       encoding='utf-8'))
             if (x.get('createdAt') or '')[:7] == '2026-07']
    cab = {(p.get('sku') or '').strip().upper():
           (str(p.get('attributeSetCode')), p.get('attributeSetName')) for p in prods}
    print(f'карток NOIRE у кабінеті: {len(cab)}')

    conn = get_connection(); cur = conn.cursor()
    cur.execute('SELECT sku, category_id FROM sexopt_products')
    sku_cat = {str(r['sku']).strip().upper(): r['category_id'] for r in cur.fetchall()}
    cur.execute('''SELECT m.sexopt_category_id, m.epicentr_category_code, e.name_ua
                   FROM epicentr_category_mapping m
                   JOIN epicentr_intimate_categories e ON e.code = m.epicentr_category_code''')
    ours = {r['sexopt_category_id']: (r['epicentr_category_code'], r['name_ua'])
            for r in cur.fetchall()}
    cur.execute('SELECT id, name FROM sexopt_categories')
    catname = {r['id']: r['name'] for r in cur.fetchall()}
    cur.close(); conn.close()
    print(f'записів мапінгу: {len(ours)} | категорій SexOpt: {len(catname)}')

    agg = collections.defaultdict(collections.Counter)
    for sku, (code, name) in cab.items():
        cid = sku_cat.get(sku)
        if cid is not None:
            agg[cid][(code, name)] += 1

    bad = []
    for cid, dist in agg.items():
        total = sum(dist.values())
        if total < MIN_CARDS:
            continue
        (top_code, top_name), n = dist.most_common(1)[0]
        our_code, our_name = ours.get(cid, ('—', '—'))
        if top_code != our_code and n / total >= MIN_SHARE:
            bad.append((total, n / total, cid, catname.get(cid, '?'),
                        our_code, our_name, top_code, top_name))

    bad.sort(key=lambda r: -r[0])
    print(f'\nкатегорій SexOpt із помилковим мапінгом: {len(bad)}\n')
    print(f"{'карток':>6} {'згода':>6}  {'категорія SexOpt':32} {'наше':22} → {'менеджер'}")
    for total, share, cid, cname, oc, on, tc, tn in bad:
        print(f'{total:6} {share*100:5.0f}%  {str(cname)[:30]:32} {str(on)[:20]:22} → {tn}')

    out = os.path.join(BASE, 'docs', 'epicentr_mapping_fixes.json')
    json.dump([{'sexopt_category_id': cid, 'sexopt_category': cname,
                'cards': total, 'agreement': round(share, 3),
                'ours': {'code': oc, 'name': on},
                'manager': {'code': tc, 'name': tn}}
               for total, share, cid, cname, oc, on, tc, tn in bad],
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n→ {out}')


if __name__ == '__main__':
    main()
