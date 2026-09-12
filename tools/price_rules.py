#!/usr/bin/env python3
"""Масова зміна цін у фідах: правила націнки, перегляд, історія, відкат.

Ціна в наших XML-фідах = РРЦ постачальника × множник. Множник береться з
правил `data/price_rules.json` за пріоритетом:

    артикул  >  категорія Rozetka (rz_id)  >  типовий для фіду

Інструмент ЛИШЕ змінює правила й показує наслідки. Сам фід перезбирає
генератор (`dropoffice_rozetka_generator.py` читає `markup_for()` звідси), а
публікує — окремий крок. Так зроблено свідомо: під час перевірки фіду
Rozetka (правило 12) правила можна готувати, не чіпаючи опублікованого файлу.

Що взято зі старого `agents/orders/price_engine.py` / `price_updater.py`:
  * поріг «підозріло велика зміна» — там 20 %; тут множник поза 0.80–1.50
    або зміна ціни понад 20 % вимагає `--force`;
  * попередній перегляд без запису (`preview`);
  * історія кожної зміни — тут `data/price_rules_history.jsonl`, з неї ж відкат.
Що НЕ взято: формулу `calc_price()` із `shared/utils/pricing.py` — її опис
каже «РРЦ / (1 − комісія)», а код рахує «РРЦ × (1 + комісія)»; для 18 %
це 1.22 проти 1.18. Тут множник задається явно, без формули.

    python3 tools/price_rules.py show    --feed dropoffice
    python3 tools/price_rules.py set     --feed dropoffice --default 1.10 --reason "..."
    python3 tools/price_rules.py set     --feed dropoffice --category 4629548 --markup 1.15
    python3 tools/price_rules.py set     --feed dropoffice --article SW-00000350 --markup 1.00
    python3 tools/price_rules.py unset   --feed dropoffice --category 4629548
    python3 tools/price_rules.py preview --feed dropoffice [--competitors docs/…sample.tsv]
    python3 tools/price_rules.py history --feed dropoffice
    python3 tools/price_rules.py undo    --feed dropoffice
"""
import argparse
import collections
import copy
import csv
import getpass
import json
import math
import os
import statistics
import sys
import xml.etree.ElementTree as ET
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(BASE_DIR, 'data', 'price_rules.json')
HISTORY = os.path.join(BASE_DIR, 'data', 'price_rules_history.jsonl')

SANE = (0.80, 1.50)        # множник поза цим — лише з --force
JUMP_ALERT = 0.20          # зміна ціни понад 20 % — лише з --force (як у price_engine)

# Звідки preview бере наші товари: джерело постачальника (РРЦ) і наш фід
# (категорія Rozetka + поточна опублікована ціна). Новий фід — новий рядок.
FEEDS = {
    'dropoffice': {
        'source': os.path.join(BASE_DIR, 'data', 'dropoffice', 'source.xml'),
        'feed': os.path.join(BASE_DIR, 'output', 'dropoffice_rozetka.xml'),
    },
}


# ── Читання правил: цим користуються генератори ────────────────────────────
def load_rules() -> dict:
    try:
        with open(RULES, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def markup_for(feed: str, rz_id: str = '', article: str = '', rules: dict = None) -> float:
    """Множник для товару. Немає правил для фіду — помилка, а не мовчазне ×1.0:
    продаж за РРЦ «випадково» на 18-відсотковій комісії — це збиток."""
    r = (rules if rules is not None else load_rules()).get(feed)
    if not r or 'default' not in r:
        raise KeyError(f'немає правил цін для фіду «{feed}» у {RULES}')
    if article and article in r.get('article', {}):
        return float(r['article'][article])
    if rz_id and str(rz_id) in r.get('category', {}):
        return float(r['category'][str(rz_id)])
    return float(r['default'])


def price_for(rrp: float, markup: float) -> int:
    """Округлення вгору до гривні — те саме, що генератор робив до правил."""
    return max(1, math.ceil(rrp * markup - 1e-9))


# ── Запис: лише через цей інструмент, з історією ───────────────────────────
def _save(rules: dict, feed: str, before: dict, action: str, reason: str) -> None:
    os.makedirs(os.path.dirname(RULES), exist_ok=True)
    tmp = RULES + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rules, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, RULES)
    with open(HISTORY, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'at': datetime.now().isoformat(timespec='seconds'), 'by': getpass.getuser(),
            'feed': feed, 'action': action, 'reason': reason,
            'before': before, 'after': rules.get(feed)}, ensure_ascii=False) + '\n')


def _load_items(feed: str) -> list:
    """(article, rz_id, category, rrp, current_price, available) для кожного оффера фіду."""
    cfg = FEEDS.get(feed)
    if not cfg:
        sys.exit(f'невідомий фід «{feed}»; відомі: {", ".join(FEEDS)}')
    rrp = {o.get('id'): float(o.findtext('price') or 0)
           for o in ET.parse(cfg['source']).getroot().iter('offer')}
    root = ET.parse(cfg['feed']).getroot()
    cats = {c.get('id'): (c.get('rz_id'), c.text) for c in root.iter('category')}
    out = []
    for o in root.iter('offer'):
        rz, cname = cats.get(o.findtext('categoryId'), ('', ''))
        out.append({'id': o.get('id'), 'article': (o.findtext('article') or '').strip(),
                    'rz_id': rz, 'category': cname, 'rrp': rrp.get(o.get('id'), 0.0),
                    'current': float(o.findtext('price') or 0),
                    'available': o.get('available') == 'true'})
    return out


def _diff(items: list, old: dict, new: dict, feed: str) -> list:
    rows = []
    for it in items:
        if not it['rrp']:
            continue
        a = price_for(it['rrp'], markup_for(feed, it['rz_id'], it['article'], old)) if old.get(feed) else it['current']
        b = price_for(it['rrp'], markup_for(feed, it['rz_id'], it['article'], new))
        rows.append({**it, 'old': a, 'new': b})
    return rows


def _check(rows: list, markups: list, force: bool) -> None:
    bad = [m for m in markups if not SANE[0] <= m <= SANE[1]]
    jumps = [r for r in rows if r['old'] and abs(r['new'] / r['old'] - 1) > JUMP_ALERT]
    msgs = []
    if bad:
        msgs.append(f'множник {bad} поза межами {SANE}')
    if jumps:
        msgs.append(f'{len(jumps)} цін змінюються більш ніж на {JUMP_ALERT:.0%}')
    if msgs and not force:
        sys.exit('ЗУПИНЕНО: ' + '; '.join(msgs) + '. Перевірте preview; свідомо — --force.')


def _summary(rows: list, title: str) -> None:
    ch = [r for r in rows if r['new'] != r['old']]
    print(f'{title}: товарів {len(rows)}, ціна зміниться у {len(ch)}')
    if not ch:
        return
    d = [r['new'] / r['old'] - 1 for r in ch if r['old']]
    up, down = sum(x > 0 for x in d), sum(x < 0 for x in d)
    print(f'  дорожче {up} · дешевше {down} · зміна: медіана {statistics.median(d):+.1%}, '
          f'від {min(d):+.1%} до {max(d):+.1%}')
    by = collections.defaultdict(list)
    for r in ch:
        by[r['category']].append(r['new'] / r['old'] - 1 if r['old'] else 0)
    for c, v in sorted(by.items(), key=lambda x: -len(x[1]))[:12]:
        print(f'    {c[:32]:32} {len(v):4}  {statistics.median(v):+.1%}')


def _competitors(rows: list, path: str) -> None:
    """Наша нова ціна проти конкурентів із заміру SKILL-30 (tools/rozetka_competitors.py)."""
    det = path.replace('.tsv', '_detail.tsv')
    if not (os.path.exists(path) and os.path.exists(det)):
        print(f'  (немає заміру конкурентів {path} — пропущено)')
        return
    best = collections.defaultdict(dict)
    with open(det, encoding='utf-8') as f:
        for d in csv.DictReader(f, delimiter='\t'):
            if d['status'] == 'available' and d['price']:
                s, p = d['seller_id'], float(d['price'])
                best[d['article']][s] = min(p, best[d['article']].get(s, 1e12))
    got = [(r, list(best[r['article']].values())) for r in rows if r['article'] in best]
    if not got:
        print('  (жоден наш артикул не збігся з заміром конкурентів)')
        return
    for label, key in (('зараз', 'old'), ('після', 'new')):
        cheaper = [sum(x < r[key] for x in b) for r, b in got]
        top3 = sum(c <= 2 for c in cheaper)
        print(f'  конкуренти ({len(got)} арт. із заміру), {label}: дешевших продавців '
              f'медіана {statistics.median(cheaper)}, у топ-3 за ціною {top3}/{len(got)}')


# ── Команди ────────────────────────────────────────────────────────────────
def cmd_show(a):
    r = load_rules().get(a.feed)
    if not r:
        print(f'правил для «{a.feed}» немає')
        return
    print(f'фід {a.feed}: типовий множник ×{r["default"]}')
    for k in ('category', 'article'):
        for key, m in sorted(r.get(k, {}).items()):
            print(f'  {k:8} {key:>12}  ×{m}')


def cmd_set(a, unset=False):
    rules = load_rules()
    before = copy.deepcopy(rules.get(a.feed))
    new = copy.deepcopy(rules)
    r = new.setdefault(a.feed, {})
    touched = []
    if a.default is not None and not unset:
        r['default'] = a.default
        touched.append(a.default)
    for kind, keys in (('category', a.category or []), ('article', a.article or [])):
        for k in keys:
            if unset:
                r.get(kind, {}).pop(str(k), None)
            else:
                if a.markup is None:
                    sys.exit('для --category/--article потрібен --markup')
                r.setdefault(kind, {})[str(k)] = a.markup
                touched.append(a.markup)
    if 'default' not in r:
        sys.exit('у фіду ще немає типового множника: спершу --default')
    rows = _diff(_load_items(a.feed), rules, new, a.feed)
    _summary(rows, 'перегляд')
    _check(rows, touched, a.force)
    if a.dry_run:
        print('--dry-run: правила НЕ записано')
        return
    action = ('unset ' if unset else 'set ') + ' '.join(
        [f'default={a.default}'] * (a.default is not None and not unset)
        + [f'category={c}' for c in a.category or []] + [f'article={x}' for x in a.article or []]
        + ([f'markup={a.markup}'] if a.markup is not None and not unset else []))
    _save(new, a.feed, before, action.strip(), a.reason or '')
    print(f'записано в {RULES}. Далі: перезібрати фід генератором і опублікувати.')


def cmd_preview(a):
    rows = _diff(_load_items(a.feed), {}, load_rules(), a.feed)
    # «old» тут — ціна в поточному зібраному фіді, «new» — за чинними правилами
    _summary(rows, 'поточний фід → за правилами')
    if a.competitors:
        _competitors(rows, a.competitors)


def cmd_history(a):
    try:
        with open(HISTORY, encoding='utf-8') as f:
            lines = [json.loads(x) for x in f if x.strip()]
    except FileNotFoundError:
        lines = []
    for h in [x for x in lines if x['feed'] == a.feed][-a.n:]:
        print(f"{h['at']}  {h['by']:8}  {h['action']}  {('— ' + h['reason']) if h['reason'] else ''}")


def cmd_undo(a):
    try:
        with open(HISTORY, encoding='utf-8') as f:
            lines = [json.loads(x) for x in f if x.strip()]
    except FileNotFoundError:
        sys.exit('історії немає')
    mine = [x for x in lines if x['feed'] == a.feed and not x['action'].startswith('undo')]
    if not mine:
        sys.exit('немає чого відкочувати')
    last = mine[-1]
    rules = load_rules()
    cur = copy.deepcopy(rules.get(a.feed))
    if last['before'] is None:
        rules.pop(a.feed, None)
    else:
        rules[a.feed] = last['before']
    print(f"відкочую: {last['at']} {last['action']}")
    if a.dry_run:
        print('--dry-run: нічого не записано')
        return
    _save(rules, a.feed, cur, f"undo ({last['at']} {last['action']})", a.reason or '')
    print('готово. Далі: перезібрати фід генератором і опублікувати.')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)

    def feed_arg(p):
        p.add_argument('--feed', required=True)
    p = sub.add_parser('show'); feed_arg(p)
    for name in ('set', 'unset'):
        p = sub.add_parser(name); feed_arg(p)
        p.add_argument('--default', type=float)
        p.add_argument('--category', nargs='+', help='rz_id категорій Rozetka')
        p.add_argument('--article', nargs='+')
        p.add_argument('--markup', type=float)
        p.add_argument('--reason', default='')
        p.add_argument('--force', action='store_true')
        p.add_argument('--dry-run', action='store_true')
    p = sub.add_parser('preview'); feed_arg(p)
    p.add_argument('--competitors', help='замір SKILL-30, напр. docs/rozetka_competitors_dropoffice_sample.tsv')
    p = sub.add_parser('history'); feed_arg(p); p.add_argument('-n', type=int, default=20)
    p = sub.add_parser('undo'); feed_arg(p)
    p.add_argument('--reason', default=''); p.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    {'show': cmd_show, 'set': cmd_set, 'unset': lambda x: cmd_set(x, unset=True),
     'preview': cmd_preview, 'history': cmd_history, 'undo': cmd_undo}[a.cmd](a)


if __name__ == '__main__':
    main()
