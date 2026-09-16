#!/usr/bin/env python3
"""Перевірка маркер-експерименту ключів Prom (протокол docs/prom_marker_experiment_20260915.md).

Для кожної групи: маркер шукається справжнім браузером (обидва блоки видачі —
основний і «частковий збіг»), в українському і російському пошуку, по 2 прогони.
Рахується, скільки карток групи знайдено і в якому блоці.

    venv/bin/python tools/prom_marker_check.py                  # ноутбук (Camoufox)
    venv/bin/python tools/prom_marker_check.py --api            # сервер: чи імпортовано маркер (API)

API віддає лише рос. `keywords` — тож --api підтверджує імпорт лише для групи RU;
для групи UA ознака імпорту — `date_modified` після публікації.
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
CONF = os.path.join(BASE_DIR, 'data', 'prom', 'marker_experiment.json')
LOG = os.path.join(BASE_DIR, 'docs', 'prom_marker_experiment_log.tsv')


def api_check(conf):
    from prom_api import call
    for g in conf['groups']:
        ok = 0
        for s in g['skus']:
            r = call('GET', f"/products/{conf['prom_ids'][s]}", None)
            p = (r.json() or {}).get('product', {}) if r.status_code == 200 else {}
            has = g['marker'] in (p.get('keywords') or '')
            ok += has
            print(f"  {g['lang']} {s:8} {p.get('status')} {p.get('presence')} змінено {p.get('date_modified')} "
                  f"| маркер у keywords (рос.): {has}")
            time.sleep(0.3)
        print(f"група {g['lang']}: маркер у рос. keywords API — {ok}/{len(g['skus'])}")


def browser_check(conf):
    import prom_search_browser as B
    from camoufox.sync_api import Camoufox
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    rows = []
    with Camoufox(headless=True, humanize=True, geoip=True, locale='uk-UA') as br:
        page = br.new_page()
        page.set_default_timeout(45000)
        ctl = B.search_both(page, B.PS.control_name())
        if not B.where(ctl, B.PS.CONTROL[1]).startswith('main'):
            sys.exit('КОНТРОЛЬ SO5178 НЕ ПРОЙДЕНО — перевірка не будується')
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
                    rows.append((now, g['lang'], g['marker'], lang, run, len(hits['main']), len(hits['partial']), total,
                                 ','.join(sorted(hits['main'] | hits['partial']))))
                    print(f"група {g['lang']} «{g['marker']}» · пошук {lang} · прогін {run}: "
                          f"основний {len(hits['main'])}/{len(pids)}, частковий {len(hits['partial'])}/{len(pids)}, усього блоків {total}",
                          flush=True)
    new = not os.path.exists(LOG)
    with open(LOG, 'a', encoding='utf-8') as f:
        if new:
            f.write('checked\tgroup\tmarker\tsearch\trun\tmain\tpartial\tblocks\tskus\n')
        for r in rows:
            f.write('\t'.join(map(str, r)) + '\n')
    print(f'→ {LOG}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--api', action='store_true')
    a = ap.parse_args()
    conf = json.load(open(CONF, encoding='utf-8'))
    api_check(conf) if a.api else browser_check(conf)


if __name__ == '__main__':
    main()
