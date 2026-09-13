#!/usr/bin/env python3
"""Чи застосовує нічний імпорт Prom зміну ЛИШЕ українських ключів.

Підстава (13.09.2026): SX0666 — нічний імпорт 12.09 оновив вміст 2611
карток, але не цю, де відрізнялись лише `keywords_ua`; дата лишилась 04.09.
Одна картка — не доказ (AGENT_RULES 11.2), тож окремий замір.

Три можливі результати, і інструмент мусить сказати, який із них, а не лише
«UA не змінились» (зауваження чату 13.09):

  1  контроль оновився, група «лише UA» теж  → гіпотезу відхилено
  2  контроль оновився, група «лише UA» — ні → гіпотезу підтверджено
  3  контроль НЕ оновився                     → тест нічого не показує

Контроль — картки, у яких зміниться ПОМІТНЕ через API поле (рос. ключі):
якщо вони не оновились, імпорту вмісту не було, і про UA говорити нема
про що. Випадок 3 легко сплутати з 2, якщо дивитись лише на UA-картки.

Застереження: API не віддає `keywords_ua`, тож для групи «лише UA» ознака —
зміна дати (`date_modified`), і лише в картках, де ціна/кількість/наявність
не мінялись (денні імпорти посувають дату через кількість). Остаточно —
скріни 6 карток у кабінеті.

    # після публікації 19:40, до нічного імпорту
    python3 tools/prom_ua_probe_check.py --prepare
    # після нічного імпорту (~03:00), до публікації 7:40
    python3 tools/prom_ua_probe_check.py --check
"""
import argparse
import json
import os
import random
import shutil
import sys
import time
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'tools'))
from prom_api import call  # noqa: E402

FEED_REPO = '/home/tek/noire-feed'
STATE = os.path.join(BASE, 'data', 'prom', 'ua_probe')
BACKUP_OLD = os.path.join(BASE, 'backups', 'prom_20260912', 'noire_prom.xml')   # ≈ фід, імпортований 12→13.09
FIELDS_API = ('id', 'sku', 'name', 'name_multilang', 'keywords', 'description', 'presence',
              'status', 'date_modified', 'price', 'quantity_in_stock')


def api_dump():
    out, last = [], None
    while True:
        params = {'limit': 1000}
        if last:
            params['last_id'] = last
        r = call('GET', '/products/list', None, params=params)
        if r.status_code != 200:
            sys.exit(f'API HTTP {r.status_code}: {r.text[:120]}')
        ps = r.json().get('products') or []
        if not ps:
            break
        out += [{k: p.get(k) for k in FIELDS_API} for p in ps]
        last = ps[-1]['id']
        time.sleep(0.5)
    return {p['sku']: p for p in out if p.get('sku')}


def feed(path):
    return {(o.findtext('vendorCode') or o.get('id')): o for o in ET.parse(path).getroot().iter('offer')}


def nk(s):
    return ', '.join(x.strip().lower() for x in (s or '').split(',') if x.strip())


def nn(s):
    return ' '.join((s or '').lower().split())


def prepare():
    os.makedirs(STATE, exist_ok=True)
    src = os.path.join(FEED_REPO, 'noire_prom.xml')
    # має бути публікація 19:40 — саме її Prom імпортує вночі. Дивимось час
    # зміни САМОГО файлу, а не коміту: публікації Rozetka (:20 щогодини) і
    # Епіцентру перезбирають коміт з усіма файлами, не змінюючи noire_prom.xml
    # (13:22 — той самий вміст, що й 11:40, 13.09.2026).
    when = time.strftime('%F %T', time.localtime(os.path.getmtime(src)))
    if not ('19:40:00' <= when[11:] <= '20:30:00'):
        sys.exit(f'noire_prom.xml змінено {when} — це не публікація 19:40; зупиняюсь')
    dst = os.path.join(STATE, 'feed_imported_tonight.xml')
    shutil.copy(src, dst)
    pre = api_dump()
    json.dump(pre, open(os.path.join(STATE, 'api_pre.json'), 'w'), ensure_ascii=False)
    new, old = feed(dst), feed(BACKUP_OLD)

    control, ua_only = [], []
    for k, o in new.items():
        a = pre.get(k)
        if not a:
            continue
        ml = a.get('name_multilang') or {}
        ru_kw_changes = nk(a.get('keywords')) != nk(o.findtext('keywords'))
        if ru_kw_changes:
            control.append(k)
            continue
        same_visible = (nn(ml.get('ru') or a.get('name')) == nn(o.findtext('name'))
                        and nn(ml.get('uk')) == nn(o.findtext('name_ua')))
        b = old.get(k)
        if same_visible and b is not None \
                and (o.findtext('keywords_ua') or '') != (b.findtext('keywords_ua') or '') \
                and (o.findtext('description_ua') or '') == (b.findtext('description_ua') or '') \
                and (o.findtext('description') or '') == (b.findtext('description') or ''):
            ua_only.append(k)
    probe = random.Random(1409).sample(ua_only, min(6, len(ua_only)))
    meta = {'feed_commit': when, 'prepared_at': time.strftime('%F %T'),
            'control': control, 'ua_only': ua_only, 'screenshots': probe}
    json.dump(meta, open(os.path.join(STATE, 'groups.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'фід {when} збережено; контроль (зміняться рос. ключі): {len(control)}; '
          f'лише укр. ключі: {len(ua_only)}; для скрінів: {" ".join(probe)}')


def check():
    meta = json.load(open(os.path.join(STATE, 'groups.json')))
    pre = json.load(open(os.path.join(STATE, 'api_pre.json')))
    new = feed(os.path.join(STATE, 'feed_imported_tonight.xml'))
    post = api_dump()
    json.dump(post, open(os.path.join(STATE, 'api_post.json'), 'w'), ensure_ascii=False)

    ctl = [k for k in meta['control'] if k in post]
    ctl_ok = sum(nk(post[k].get('keywords')) == nk(new[k].findtext('keywords')) for k in ctl)
    share = ctl_ok / len(ctl) if ctl else 0

    def stable(k):
        a, b = pre[k], post[k]
        return (a.get('price'), a.get('quantity_in_stock'), a.get('presence')) == \
               (b.get('price'), b.get('quantity_in_stock'), b.get('presence'))
    grp = [k for k in meta['ua_only'] if k in post and stable(k)]
    bumped = [k for k in grp if post[k].get('date_modified') != pre[k].get('date_modified')]
    ushare = len(bumped) / len(grp) if grp else 0

    print(f"фід імпорту: {meta['feed_commit']} · підготовлено {meta['prepared_at']}")
    print(f'КОНТРОЛЬ: рос. ключі = фіду в {ctl_ok}/{len(ctl)} ({share:.0%})')
    print(f'ЛИШЕ UA: дата змінилась у {len(bumped)}/{len(grp)} ({ushare:.0%}) '
          f'[з {len(meta["ua_only"])}; решта мали зміну ціни/кількості/наявності]')
    if share < 0.8:
        print('РЕЗУЛЬТАТ 3: контроль не оновився — імпорту вмісту не було, тест нічого не показує; потрібен ще цикл')
    elif ushare >= 0.8:
        print('РЕЗУЛЬТАТ 1 (попередньо): зміни лише укр. ключів застосовуються — гіпотезу відхилено; підтвердити скрінами')
    elif ushare <= 0.2:
        print('РЕЗУЛЬТАТ 2 (попередньо): контроль оновився, «лише UA» — ні — гіпотезу підтверджено; підтвердити скрінами')
    else:
        print('ЗМІШАНИЙ: частина «лише UA» оновилась — дивитись список і скріни')
    print(f"скріни укр. ключів: {' '.join(meta['screenshots'])}")
    for k in meta['screenshots']:
        print(f"  {k}: має стати → {new[k].findtext('keywords_ua')}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--prepare', action='store_true')
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    prepare() if a.prepare else check() if a.check else ap.print_help()
