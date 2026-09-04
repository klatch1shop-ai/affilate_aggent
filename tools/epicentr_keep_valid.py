#!/usr/bin/env python3
"""
tools/epicentr_keep_valid.py
=============================
Лишає у фіді Єпіцентру лише оффери, які пройшли валідацію, і зшиває кілька
фідів в один файл для завантаження.

НАВІЩО. Імпорт у кабінет приймає файл цілком; оффер із незаповненим
обовʼязковим атрибутом не просто не публікується — він засмічує звіт імпорту
й ускладнює розбір того, що справді заїхало. Тому вантажимо тільки готове,
а решта чекає на дозаповнення окремо.

Список артикулів, що пройшли, беремо з виводу самого валідатора: інакше
довелось би дублювати його правила тут і згодом розійтися з ним у поведінці.

    python3 tools/epicentr_keep_valid.py --src a.xml b.xml --out ready.xml
"""
import os, re, sys, argparse, subprocess
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR = os.path.join(BASE, 'tools', 'noire_epicentr_validator.py')
ROW = re.compile(r'^\[\s*\d+\]\s+(\S+)\s+.*?(PASS|WARN|FAIL)', re.M)


def verdicts(path):
    r = subprocess.run([sys.executable, VALIDATOR, path],
                       capture_output=True, text=True, timeout=1800)
    return {sku: v for sku, v in ROW.findall(r.stdout or '')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', nargs='+', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--exclude-existing', metavar='JSON',
                    help='data/epicentr_products.json — прибрати артикули, '
                         'які вже є в кабінеті, щоб імпорт їх не перезаписав')
    ap.add_argument('--keep-warn', action='store_true',
                    help='лишати також WARN (попередження не блокують публікацію)')
    a = ap.parse_args()

    ok_set = {'PASS', 'WARN'} if a.keep_warn else {'PASS'}
    # Імпорт із наявним артикулом ОНОВЛЮЄ картку, а не створює нову. Серед
    # наших 3227 сім артикулів уже є в кабінеті, і один із них опублікований —
    # завантаження перезаписало б готову картку чернеткою.
    # Правило «оновлення замість створення»: збіг артикулу — це не завжди
    # привід пропустити. Картку в роботі (draft/enrich) наш файл **доповнює**
    # свіжими даними, і це саме те, чого їй бракує. А ось опубліковану або ту,
    # що на модерації, чіпати не можна: перезапис збив би працюючий контент.
    existing = set()
    if a.exclude_existing:
        import json as _j
        LOCKED = {'published', 'moderating', 'banned'}
        cab = _j.load(open(a.exclude_existing, encoding='utf-8'))
        existing = {(x.get('sku') or '').strip() for x in cab
                    if (x.get('status') or '') in LOCKED}
        upd = {(x.get('sku') or '').strip() for x in cab
               if (x.get('status') or '') not in LOCKED}
        print(f'у кабінеті: {len(cab)} | заблоковано для перезапису: {len(existing)}'
              f' | доступно для оновлення: {len(upd)}')
    merged = None
    offers_el = None
    kept = dropped = 0
    for path in a.src:
        v = verdicts(path)
        tree = ET.parse(path); root = tree.getroot()
        if merged is None:
            merged, offers_el = tree, root.find('.//offers')
            for o in list(offers_el):
                sku = o.get('id')
                if v.get(sku) in ok_set and sku not in existing:
                    kept += 1
                else:
                    offers_el.remove(o); dropped += 1
            continue
        for o in root.findall('.//offer'):
            if v.get(o.get('id')) in ok_set and o.get('id') not in existing:
                offers_el.append(o); kept += 1
            else:
                dropped += 1
        print(f'  {os.path.basename(path)}: додано '
              f'{sum(1 for o in root.findall(".//offer") if v.get(o.get("id")) in ok_set and o.get("id") not in existing)}')

    merged.write(a.out, encoding='utf-8', xml_declaration=True)
    size = os.path.getsize(a.out) / 1024 / 1024
    print(f'\nзалишено: {kept} | відкинуто: {dropped}')
    print(f'файл: {a.out}  ({size:.1f} МБ)')
    if kept > 10000:
        print('УВАГА: понад 10 000 офферів — ліміт імпорту Єпіцентру, треба ділити')
    if size > 50:
        print('УВАГА: понад 50 МБ — ліміт розміру файлу імпорту')


if __name__ == '__main__':
    main()
