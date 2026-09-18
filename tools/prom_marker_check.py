#!/usr/bin/env python3
"""Перевірка маркер-експерименту ключів Prom (протокол docs/prom_marker_experiment_20260915.md).

Для кожної групи: маркер шукається справжнім браузером (обидва блоки видачі —
основний і «частковий збіг»), в українському і російському пошуку, по 2 прогони.
Рахується, скільки карток групи знайдено і в якому блоці.

    venv/bin/python tools/prom_marker_check.py                  # ноутбук (Camoufox)
    venv/bin/python tools/prom_marker_check.py --api            # сервер: чи імпортовано маркер (API)
    venv/bin/python tools/prom_marker_check.py --compare        # склад знахідок між днями (з журналу)

`--compare` відповідає на питання чату 16.09: частка може лишатись тією самою,
але склад — мінятись. Стабільний перелік = поріг потрапляння у видачу;
змінний перелік = ротація видимості. Це різні механізми.

API віддає лише рос. `keywords` — тож --api підтверджує імпорт лише для групи RU;
для групи UA ознака імпорту — `date_modified` після публікації.
"""
import argparse
import csv
import datetime
import json
import os
import sys
import time
import urllib.parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
CONFS = [os.path.join(BASE_DIR, 'data', 'prom', f)
         for f in ('marker_experiment.json', 'price_marker_experiment.json')]
LOG = os.path.join(BASE_DIR, 'docs', 'prom_marker_experiment_log.tsv')


def load_conf():
    """Активні експерименти в один перелік груп; мітка групи — name або lang."""
    groups, ids = [], {}
    for path in CONFS:
        if not os.path.exists(path):
            continue
        c = json.load(open(path, encoding='utf-8'))
        if not c.get('active'):
            continue
        ids.update(c.get('prom_ids', {}))
        for g in c['groups']:
            groups.append({**g, 'label': g.get('name') or g['lang']})
    return {'groups': groups, 'prom_ids': ids}


def api_check(conf):
    from prom_api import call
    for g in conf['groups']:
        ok = 0
        for s in g['skus']:
            r = call('GET', f"/products/{conf['prom_ids'][s]}", None)
            p = (r.json() or {}).get('product', {}) if r.status_code == 200 else {}
            has = g['marker'] in (p.get('keywords') or '')
            ok += has
            print(f"  {g['label']} {s:8} {p.get('status')} {p.get('presence')} змінено {p.get('date_modified')} "
                  f"| маркер у keywords (рос.): {has}")
            time.sleep(0.3)
        print(f"група {g['label']}: маркер у рос. keywords API — {ok}/{len(g['skus'])}")


def browser_check(conf):
    import prom_search_browser as B
    from camoufox.sync_api import Camoufox
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    rows = []
    with Camoufox(headless=True, humanize=True, geoip=True, locale='uk-UA') as br:
        page = br.new_page()
        page.set_default_timeout(45000)
        # контроль теж мигає (43 % видимих карток) — до 3 спроб, як у prom_search.control();
        # 17.09 одна невдала спроба зупинила всю перевірку дня
        for attempt in range(1, 4):
            ctl = B.search_both(page, B.PS.control_name())
            if B.where(ctl, B.PS.CONTROL[1]).startswith('main'):
                break
            print(f'контроль: спроба {attempt} — картки немає, повтор', flush=True)
            page.wait_for_timeout(5000 * attempt)
        else:
            sys.exit('КОНТРОЛЬ SO5178 НЕ ПРОЙДЕНО за 3 спроби — перевірка не будується')
        for g in conf['groups']:
            pids = {conf['prom_ids'][s]: s for s in g['skus']}
            for lang, root in (('ua', 'https://prom.ua/ua/search'), ('ru', 'https://prom.ua/search')):
                for run in (1, 2):
                    hits, total = {'main': set(), 'partial': set()}, 0
                    for pg in range(1, 8):          # група до 50 карток — не вміщається на 1 сторінку
                        page.goto(root + '?search_term=' + urllib.parse.quote(g['marker'])
                                  + (f'&page={pg}' if pg > 1 else ''), wait_until='domcontentloaded')
                        page.wait_for_timeout(3500)
                        for _ in range(8):
                            page.mouse.wheel(0, 2500)
                            page.wait_for_timeout(900)
                        page.wait_for_timeout(2500)
                        r = page.evaluate(B.JS)
                        for it in r['items']:
                            if it['pid'] in pids:
                                hits[it['block']].add(pids[it['pid']])
                        total += len(r['items'])
                        if len(r['items']) < 10:
                            break
                    rows.append((now, g['label'], g['marker'], lang, run, len(hits['main']), len(hits['partial']), total,
                                 ','.join(sorted(hits['main'] | hits['partial']))))
                    print(f"група {g['label']} «{g['marker']}» · пошук {lang} · прогін {run}: "
                          f"основний {len(hits['main'])}/{len(pids)}, частковий {len(hits['partial'])}/{len(pids)}, усього блоків {total}",
                          flush=True)
    new = not os.path.exists(LOG)
    with open(LOG, 'a', encoding='utf-8') as f:
        if new:
            f.write('checked\tgroup\tmarker\tsearch\trun\tmain\tpartial\tblocks\tskus\n')
        for r in rows:
            f.write('\t'.join(map(str, r)) + '\n')
    print(f'→ {LOG}')


def compare():
    """Склад знахідок по днях: той самий перелік чи ротація."""
    import collections
    days = collections.defaultdict(lambda: collections.defaultdict(set))
    with open(LOG, encoding='utf-8') as f:
        rd = csv.DictReader(f, delimiter='\t')
        for r in rd:
            # ключ — повна мітка часу, а не дата: за день буває кілька заходів,
            # і різниця між ними так само важлива (ротація чи поріг)
            skus = {s for s in r['skus'].split(',') if s}
            days[r['group']][r['checked']] |= skus
    for grp in sorted(days):
        seq = sorted(days[grp])
        print(f'\n=== група {grp}')
        prev = None
        for day in seq:
            cur = days[grp][day]
            line = f'  {day}: знайдено {len(cur):2}'
            if prev is not None:
                new, lost = cur - prev, prev - cur
                kept = len(cur & prev)
                line += f' | той самий {kept}, нових {len(new)}, зникло {len(lost)}'
                if new:
                    line += f'\n      нові:   {",".join(sorted(new))}'
                if lost:
                    line += f'\n      зникли: {",".join(sorted(lost))}'
            print(line)
            prev = cur
        if len(seq) >= 2:
            first, last = days[grp][seq[0]], days[grp][seq[-1]]
            if first and last:
                stable = len(first & last) / max(len(first), len(last))
                print(f'  склад {seq[0]} → {seq[-1]}: збіг {stable:.0%} '
                      f'({"поріг — перелік стабільний" if stable >= 0.8 else "схоже на ротацію"})')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--api', action='store_true')
    ap.add_argument('--compare', action='store_true')
    a = ap.parse_args()
    if a.compare:
        return compare()
    conf = load_conf()
    if not conf['groups']:
        sys.exit('активних маркер-експериментів немає')
    api_check(conf) if a.api else browser_check(conf)


if __name__ == '__main__':
    main()
