#!/usr/bin/env python3
"""
tools/prom_postprocess.py
==========================
Постобробка фіду Prom одразу після генерації: одиниці виміру, характеристики,
назви, описи, пошукові запити.

ЧОМУ ПОСТОБРОБКА, А НЕ ПРАВКА ГОТОВОГО ФАЙЛУ. Фід перегенеровується сервером
(повна збірка о 06:30, публікації о 7:40/11:40/15:40/19:40). Правка готового
XML живе до наступної перегенерації, після чого зникає. Тому зміни мають
застосовуватись **до кожної нової збірки**, а не одноразово.

ЧОМУ НЕ ВСЕРЕДИНІ ГЕНЕРАТОРА. Окремий прохід не чіпає перевірену логіку збірки
цін і наявності. Якщо він упаде, лишається робочий фід попереднього кроку, а не
зламаний — тому скрипт **пише в тимчасовий файл і підміняє оригінал лише після
успішного розбору результату**.

    python3 tools/prom_postprocess.py --src output/noire_prom.xml --inplace
    python3 tools/prom_postprocess.py --src ... --out ... --dry-run
"""
import os, sys, argparse, shutil, subprocess, tempfile
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
STEPS = [
    ('одиниці виміру (весь фід)', 'tools/prom_units_normalize.py'),
    ('характеристики категорії', 'tools/prom_params_fill.py'),
    ('назви, описи, ключі', 'tools/prom_content_fix.py'),
]


def run(script, src, out):
    env = dict(os.environ, STEP_SRC=src, PROM_FEED=src)
    r = subprocess.run([PY, os.path.join(BASE, script), '--write', out],
                       cwd=BASE, env=env, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f'{script}: {r.stderr[-600:]}')
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=os.path.join(BASE, 'output', 'noire_prom.xml'))
    ap.add_argument('--out')
    ap.add_argument('--inplace', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    before = len(ET.parse(a.src).getroot().findall('.//offer'))
    print(f'вхід: {a.src} — {before} офферів')

    tmpdir = tempfile.mkdtemp(prefix='prom_pp_')
    cur = a.src
    try:
        for i, (label, script) in enumerate(STEPS, 1):
            nxt = os.path.join(tmpdir, f'step{i}.xml')
            out = run(script, cur, nxt)
            print(f'\n── крок {i}: {label} ──')
            for line in out.splitlines():
                if line.strip() and not line.startswith('копію'):
                    print('   ' + line)
            cur = nxt

        after = len(ET.parse(cur).getroot().findall('.//offer'))
        if after != before:
            raise RuntimeError(f'кількість офферів змінилась: {before} → {after}')
        print(f'\nперевірка: {after} офферів, XML розбирається')

        if a.dry_run:
            print('DRY-RUN: результат не збережено')
            return
        dest = a.out or (a.src if a.inplace else None)
        if not dest:
            print('не вказано --out або --inplace; результат відкинуто'); return
        if a.inplace:
            shutil.copy2(a.src, a.src + '.bak')
            print(f'резервна копія: {a.src}.bak')
        shutil.move(cur, dest)
        print(f'записано: {dest}')
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    main()
