#!/usr/bin/env python3
"""Ціни й наявність ЮГ-Контракту в опублікованому фіді Rozetka.

ПРАВИЛО (власник, 02.10.2026): щойно фід подано, ціна й наявність у ньому
мусять бути реальні й оновлюватись. Фід, який ніхто не оновлює, продає
те, чого немає — на TOPTUL це вже коштувало замовлення на відсутній
товар.

ВІДМІННІСТЬ ВІД `feed_stock_sync.py`: у ЮК немає XML-фіду, стан береться
з їхнього порталу через API (сесія в data/yug_session.json). Тому крок
перший — оновити вивантаження каталогу, і лише потім правити фід.

ПРАВКА ХІРУРГІЧНА: чіпаємо тільки `price`, `stock_quantity` і
`available`. Решта тегів заморожена, бо після модерації зміст фіду
міняти не можна (SKILL-36).

    venv/bin/python tools/yug_stock_sync.py --dry
    venv/bin/python tools/yug_stock_sync.py --write --publish
"""
import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
КАТАЛОГ = os.path.join(BASE, 'data', 'yug_catalog.json')
РЕПО = os.path.expanduser('~/noire-feed')
ФАЙЛ = 'yug_rozetka.xml'


def оновити_каталог(категорії):
    """Перевивантажити категорії фіду з порталу — ціни й залишки живі."""
    for cid in категорії:
        subprocess.run([sys.executable, os.path.join(BASE, 'tools', 'yug_catalog_dump.py'),
                        '--категорія', str(cid), '--сторінок', '6',
                        '--на-сторінці', '100'],
                       cwd=BASE, capture_output=True, timeout=900)


def стан_постачальника():
    """{product_id: (ціна_ррц, залишок)} з останнього вивантаження."""
    d = json.load(open(КАТАЛОГ, encoding='utf-8'))
    out = {}
    for lst in (d.get('товари') or {}).values():
        for t in lst:
            pid = str(t.get('product_id') or t.get('artikul'))
            ррц = t.get('price_rrc') or 0
            наявн = t.get('availability') or 0
            if pid:
                out[pid] = (float(ррц), int(наявн))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--publish', action='store_true')
    ap.add_argument('--без-оновлення', action='store_true', dest='без_оновлення',
                    help='не ходити на портал, узяти наявне вивантаження')
    a = ap.parse_args()

    шлях = os.path.join(РЕПО, ФАЙЛ)
    if not os.path.exists(шлях):
        sys.exit(f'немає опублікованого фіду {шлях}')
    дерево = ET.parse(шлях)
    корінь = дерево.getroot()
    офери = корінь.findall('.//offer')
    print(f'у фіді офферів: {len(офери)}')

    if not a.без_оновлення:
        катал = json.load(open(КАТАЛОГ, encoding='utf-8'))
        категорії = list((катал.get('товари') or {}).keys())
        print(f'оновлюю {len(категорії)} категорій з порталу…')
        оновити_каталог(категорії)

    стан = стан_постачальника()
    print(f'позицій у вивантаженні: {len(стан)}')

    зміни = {'ціна': 0, 'наявність': 0, 'зникли': 0}
    for o in офери:
        pid = o.get('id')
        if pid not in стан:
            # Товару більше немає у вивантаженні — вимикаємо, а не
            # видаляємо: видалення змінює зміст фіду, а ми маємо право
            # міняти лише наявність.
            if o.get('available') != 'false':
                o.set('available', 'false')
                sq = o.find('stock_quantity')
                if sq is not None:
                    sq.text = '0'
                зміни['зникли'] += 1
            continue
        ррц, наявн = стан[pid]
        ц = o.find('price')
        if ц is not None and ррц and abs(float(ц.text or 0) - ррц) >= 0.5:
            ц.text = f'{ррц:.0f}'
            зміни['ціна'] += 1
        було = o.get('available')
        стало = 'true' if наявн > 0 else 'false'
        sq = o.find('stock_quantity')
        if було != стало or (sq is not None and sq.text != str(наявн)):
            o.set('available', стало)
            if sq is not None:
                sq.text = str(наявн)
            зміни['наявність'] += 1

    print(f"змінено: цін {зміни['ціна']}, наявності {зміни['наявність']}, "
          f"зникли з каталогу {зміни['зникли']}")
    if a.dry or not a.write:
        print('холостий прогін, файл не змінено')
        return
    дерево.write(шлях, encoding='UTF-8', xml_declaration=True)
    print(f'записано {шлях}')
    if a.publish:
        subprocess.run(['git', 'add', ФАЙЛ], cwd=РЕПО, check=True)
        r = subprocess.run(['git', 'commit', '-m',
                            f"yug: ціни й наявність {зміни['ціна']}/{зміни['наявність']}"],
                           cwd=РЕПО, capture_output=True, text=True)
        if r.returncode == 0:
            subprocess.run(['git', 'push', 'origin', 'main'], cwd=РЕПО, check=False)
            print('опубліковано')
        else:
            print('нема що комітити')


if __name__ == '__main__':
    main()
