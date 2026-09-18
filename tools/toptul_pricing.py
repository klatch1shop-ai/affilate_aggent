#!/usr/bin/env python3
"""Формування цін TOPTUL для Rozetka: прайс постачальника → ціна → звіт по категоріях.

Задача власника (17.09.2026): взяти з прайсу оптову ціну, звірити з РРЦ
(мінімальна ціна продажу), додати комісію Rozetka, порахувати маржу, знайти
ціни конкурентів **за точним артикулом** і не допустити збитку. Прохід —
по категоріях, щоб кожну можна було переглянути окремо.

Математика — у `tools/price_engine_toptul.py` (27 тестів). Тут лише дані:

  * прайс «Гранд Інструмент» (xlsx): артикул, бренд і категорія з рядків-груп,
    «Великий опт», «Опт безготівка з ПДВ», «Ціна РРЦ»;
  * наш фід TOPTUL для Rozetka: які артикули ми продаємо, у якій категорії
    Rozetka і за скільки зараз;
  * комісія: розділ тарифу знаходиться за НАЗВОЮ предка категорії в каталозі
    Rozetka (номери в таблиці тарифів і в каталозі — з різних систем:
    «Інструменти й обладнання» це 4628758 у тарифі й 2577232 у каталозі);
  * конкуренти: `tools/rozetka_competitors.find` — лише картки з ТИМ САМИМ
    артикулом, у наявності, поштучні, не наші.

**Нічого не публікує й фід не змінює** (власник: TOPTUL-фід Rozetka не
оновлювати). Результат — звіти для рішення.

Звіти — у `data/toptul/private/reports/<дата>/` (поза git: оптові ціни —
комерційна таємниця, а репозиторій публічний).

    venv/bin/python tools/toptul_pricing.py --category "Імбусові ключі"
    venv/bin/python tools/toptul_pricing.py --all --min-profit 30
    venv/bin/python tools/toptul_pricing.py --all --discount 0.20      # опт = РРЦ − 20 %, де опту немає
    venv/bin/python tools/toptul_pricing.py --category "Набори" --competitors 20
"""
import argparse
import collections
import csv
import datetime
import os
import re
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'tools'))
import price_engine_toptul as E  # noqa: E402

PRIVATE = os.path.join(BASE, 'data', 'toptul', 'private')
FEED = os.path.join(BASE, 'output', 'toptul_rozetka.xml')
OUR_SELLERS = {'klatch1 shop', 'klatch1', 'noire'}


def norm_art(a):
    return re.sub(r'[\s\-_.]', '', str(a or '')).upper()


# ── прайс постачальника ───────────────────────────────────────────────
def load_price_list(paths, brand='TOPTUL'):
    """{АРТИКУЛ: {...}} для одного бренду. Бренд і категорія — з рядків-груп."""
    import openpyxl
    out = {}
    for path in paths:
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
        cur_brand = cur_cat = None
        for r in ws.iter_rows(min_row=4, values_only=True):
            r = list(r) + [None] * 9
            art, name = r[1], r[2]
            if not art and name:                  # рядок-група: бренд великими або категорія
                s = str(name).strip()
                if s.isupper() and len(s.split()) <= 3:
                    cur_brand, cur_cat = s, None
                else:
                    cur_cat = s
                continue
            if not (art and name) or (brand and cur_brand != brand):
                continue
            num = lambda v: float(v) if isinstance(v, (int, float)) and v > 0 else None
            out[norm_art(art)] = {'article': str(art).strip(), 'name': str(name).strip(),
                                  'supplier_cat': cur_cat, 'big': num(r[3]), 'opt': num(r[4]),
                                  'rrp': num(r[5]), 'stock': r[6] or '', 'file': os.path.basename(path)}
    return out


# ── наш фід ───────────────────────────────────────────────────────────
def load_feed(path=FEED):
    cats, offers = {}, []
    for _, el in ET.iterparse(path, events=('end',)):
        if el.tag == 'category':
            cats[el.get('id')] = (int(el.get('rz_id') or 0), (el.text or '').strip())
        elif el.tag == 'offer':
            cid = el.findtext('categoryId')
            rz, cname = cats.get(cid, (0, ''))
            offers.append({'offer_id': el.get('id'), 'article': (el.findtext('article') or '').strip(),
                           'name': (el.findtext('name_ua') or el.findtext('name') or '').strip(),
                           'price_now': float(el.findtext('price') or 0), 'rz_id': rz,
                           'category': cname, 'available': el.get('available') == 'true'})
            el.clear()
    return offers


# ── комісія за назвою предка ─────────────────────────────────────────
class Commission:
    def __init__(self):
        from shared.utils.db import get_connection
        from rozetka_category_find import load
        cur = get_connection().cursor()
        cur.execute('select category_name, base_commission, price_ranges from rozetka_cpa_rates')
        self.groups = {}
        for r in cur.fetchall():
            name = re.sub(r'^[\d.]+\s*', '', r['category_name']).strip().lower()   # «1.5 Інструменти…» → «інструменти…»
            ranges = r['price_ranges'] or [[0, 999999999, float(r['base_commission'])]]
            self.groups[name] = (r['category_name'], [[a, b, float(c)] for a, b, c in ranges])
        self.worst = max(self.groups.values(), key=lambda g: max(x[2] for x in g[1]))
        _, self.by_id, _ = load()
        self.cache = {}

    def resolve(self, rz_id):
        """→ (назва розділу тарифу, смуги, точно?). Найглибший предок з назвою розділу."""
        if rz_id in self.cache:
            return self.cache[rz_id]
        chain, cur, seen = [], rz_id, set()
        while cur in self.by_id and cur not in seen:
            seen.add(cur)
            chain.append(self.by_id[cur]['rz_name'].strip().lower())
            cur = self.by_id[cur]['parent_id']
        for name in chain:                          # від листа до кореня: перший збіг — найглибший
            if name in self.groups:
                res = (*self.groups[name], True)
                break
        else:                                       # розділ не знайдено — найвища ставка, щоб не піти в мінус
            res = (f'НЕВІДОМО → найвища ставка ({self.worst[0]})', self.worst[1], False)
        self.cache[rz_id] = res
        return res


# ── конкуренти за точним артикулом ───────────────────────────────────
def competitor_prices(http, art, sellers):
    import rozetka_competitors as RC
    found, _ = RC.find(http, art, sellers)
    prices = []
    for c in found or []:
        if (c.get('seller') or '').strip().lower() in OUR_SELLERS:
            continue                                # наша власна картка — не конкурент
        if c.get('pack', 1) != 1 or c.get('status') not in ('available', 'limited'):
            continue                                # набір із кількох штук або немає в наявності
        if c.get('price'):
            prices.append(float(c['price']))
    return prices


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--price', nargs='*', default=None, help='xlsx прайсу (за замовчуванням усі в data/toptul/private)')
    ap.add_argument('--feed', default=FEED)
    ap.add_argument('--category', help='одна категорія фіду (назва, як у звіті)')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--cost', choices=('big', 'opt', 'max'), default='max',
                    help='яку оптову колонку вважати закупівлею; max — обережніше, вища з двох')
    ap.add_argument('--discount', type=float, default=None,
                    help='де опту в прайсі немає: опт = РРЦ × (1 − знижка). Позначається у звіті')
    ap.add_argument('--min-profit', type=float, default=0.0)
    ap.add_argument('--fixed-costs', type=float, default=0.0)
    ap.add_argument('--undercut', type=int, default=0)
    ap.add_argument('--competitors', type=int, default=0, help='скільки товарів на категорію звірити з конкурентами')
    ap.add_argument('--rrp-round', choices=('ceil', 'nearest'), default='ceil',
                    help='РРЦ з копійками (2482,48): ceil — 2483, суворо не нижче; nearest — 2482, '
                         'як тримає ринок (18.09 усі 10 перевірених конкурентів округлювали вниз)')
    a = ap.parse_args()
    if not (a.category or a.all):
        sys.exit('вкажіть --category "<назва>" або --all')

    files = a.price or sorted(os.path.join(PRIVATE, f) for f in os.listdir(PRIVATE) if f.endswith('.xlsx'))
    plist = load_price_list(files)
    offers = load_feed(a.feed)
    comm = Commission()
    print(f'прайс: {len(plist)} артикулів TOPTUL з {len(files)} файлів · фід: {len(offers)} офферів')

    by_cat = collections.defaultdict(list)
    for o in offers:
        by_cat[o['category']].append(o)
    cats = [a.category] if a.category else sorted(by_cat, key=lambda c: -len(by_cat[c]))
    if a.category and a.category not in by_cat:
        near = [c for c in by_cat if a.category.lower() in c.lower()][:8]
        sys.exit(f'категорії «{a.category}» у фіді немає. Схожі: {near}')

    http = sellers = None
    if a.competitors:
        import rozetka_competitors as RC
        http, sellers = RC.Http(RC.CACHE, 24), {}

    day = datetime.date.today().isoformat()
    outdir = os.path.join(PRIVATE, 'reports', day)
    os.makedirs(outdir, exist_ok=True)
    summary_rows = []
    cols = ['article', 'name', 'price_now', 'price', 'status', 'rrp', 'cost', 'cost_source',
            'commission_group', 'commission_pct', 'commission', 'profit', 'margin_pct',
            'competitor_min', 'competitors_n', 'change_pct', 'reason']
    for cat in cats:
        rows, results = [], []
        checked = 0
        for o in by_cat[cat]:
            p = plist.get(norm_art(o['article']))
            group, ranges, exact = comm.resolve(o['rz_id'])
            cost = src = rrp = None
            if p:
                rrp = p['rrp']
                if rrp and a.rrp_round == 'nearest':
                    rrp = float(round(rrp))
                big, opt = p['big'], p['opt']
                cost = {'big': big, 'opt': opt, 'max': max([x for x in (big, opt) if x] or [0]) or None}[a.cost]
                src = f'прайс ({a.cost})' if cost else None
                if cost is None and a.discount is not None and rrp:
                    cost, src = round(rrp * (1 - a.discount), 2), f'ОЦІНКА: РРЦ − {a.discount:.0%}'
            comps = []
            if a.competitors and checked < a.competitors and p and cost:
                comps = competitor_prices(http, o['article'], sellers)
                checked += 1
            r = E.price_item(cost, rrp, ranges, competitors=comps, min_profit=a.min_profit,
                             fixed_costs=a.fixed_costs, undercut=a.undercut)
            if not p:
                r['reason'] = 'артикула немає в прайсі постачальника'
            if not exact and r['price'] is not None:
                r['reason'] += ' · розділ тарифу не знайдено — взято найвищу ставку'
            results.append(r)
            rows.append({'article': o['article'], 'name': o['name'][:90], 'price_now': o['price_now'],
                         'price': r['price'], 'status': r['status'], 'rrp': rrp, 'cost': cost,
                         'cost_source': src or '', 'commission_group': group,
                         'commission_pct': r['commission_pct'], 'commission': r['commission'],
                         'profit': r['profit'], 'margin_pct': r['margin_pct'],
                         'competitor_min': r['competitor_min'], 'competitors_n': len(comps),
                         'change_pct': (round((r['price'] - o['price_now']) / o['price_now'] * 100, 1)
                                        if r['price'] and o['price_now'] else ''),
                         'reason': r['reason']})
        s = E.summarize(results)
        est = sum(1 for x in rows if x['cost_source'].startswith('ОЦІНКА'))
        fname = re.sub(r'[^\w\-]+', '_', cat)[:60] or 'без_категорії'
        with open(os.path.join(outdir, f'{fname}.csv'), 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter=';')
            w.writeheader()
            w.writerows(rows)
        summary_rows.append((cat, s, est, rows[0]['commission_group'] if rows else ''))
        print(f"{cat[:40]:40} {s['total']:4} · з ціною {s['priced']:4} · збиткових {s['losses']} · "
              f"маржа {s['avg_margin_pct'] if s['avg_margin_pct'] is not None else '—':>5} % · {s['by_status']}")

    # зведення
    lines = [f'# Ціни TOPTUL для Rozetka — {day}', '',
             f'Прайс: {", ".join(os.path.basename(x) for x in files)}. Закупівля: `{a.cost}`'
             + (f', де опту немає — оцінка РРЦ − {a.discount:.0%}' if a.discount is not None else '')
             + f'. Мінімальний прибуток {a.min_profit:g} грн.', '',
             '| категорія | товарів | з ціною | збиткових | середня маржа, % | оцінений опт | статуси | розділ тарифу |',
             '|---|---|---|---|---|---|---|---|']
    for cat, s, est, grp in summary_rows:
        st = ', '.join(f'{k} {v}' for k, v in sorted(s['by_status'].items()))
        lines.append(f"| {cat} | {s['total']} | {s['priced']} | {s['losses']} | "
                     f"{s['avg_margin_pct'] if s['avg_margin_pct'] is not None else '—'} | {est} | {st} | {grp} |")
    tot = collections.Counter()
    for _, s, est, _ in summary_rows:
        tot['total'] += s['total']; tot['priced'] += s['priced']; tot['losses'] += s['losses']; tot['est'] += est
    lines += ['', f"**Разом:** {tot['total']} товарів, з ціною {tot['priced']}, "
              f"збиткових {tot['losses']}, з оціненим оптом {tot['est']}."]
    open(os.path.join(outdir, 'SUMMARY.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print(f"\nразом: {tot['total']} · з ціною {tot['priced']} · збиткових {tot['losses']} · "
          f"оцінений опт {tot['est']}\nзвіти: {os.path.relpath(outdir, BASE)}/")


if __name__ == '__main__':
    main()
