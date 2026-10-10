#!/usr/bin/env python3
"""Аудит системи: що запущено, що розходиться між ноутбуком і сервером,
що лежить мертвим. Лише читання.

Навіщо інструмент, а не документ: 10.10.2026 аудит знайшов 2209 рядків
робочого коду ПОЗА git і сервер, який працював на старішій версії конвеєра
NOIRE. Текстовий опис такого не ловить — він застаріває тихо. Цей скрипт
перевіряє щоразу заново.

    venv/bin/python tools/system_audit.py              # усе
    venv/bin/python tools/system_audit.py --sync       # лише розбіжності
    venv/bin/python tools/system_audit.py --runtime    # лише що запущено
"""
import argparse
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRV = os.getenv('AGENT_SERVER', 'tek@192.168.3.28')
SRV_DIR = os.getenv('AGENT_SERVER_DIR', '/home/tek/agent-system')

# Теки, які сервер перегенеровує сам — у git їх не тримаємо
# (рішення власника 10.10.2026).
GENERATED = ('exports/', 'data/', 'output/', 'logs/', 'scratchpad/')
# Окремий підпроєкт, не частина agent-system
FOREIGN = ('claw-code/', '.cache/', 'venv/', '.git/', 'node_modules/')


def sh(cmd, cwd=None):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return r.stdout.strip()


def ssh(cmd):
    return sh(f"ssh {SRV} {cmd!r}")


def py_files_local():
    out = []
    for root, dirs, files in os.walk(BASE):
        rel = os.path.relpath(root, BASE)
        rel = '' if rel == '.' else rel + '/'
        if any(rel.startswith(p) for p in FOREIGN + GENERATED):
            dirs[:] = []
            continue
        for f in files:
            if f.endswith('.py'):
                out.append(os.path.join(rel, f))
    return sorted(out)


def check_git():
    print('── GIT ───────────────────────────────────────────')
    br = sh('git branch --show-current', BASE)
    sh('git fetch -q origin', BASE)
    lr = sh('git rev-list --left-right --count origin/main...HEAD', BASE).split()
    print(f'  гілка: {br} · на GitHub немає: {lr[1] if len(lr) > 1 else "?"} '
          f'· у нас немає: {lr[0] if lr else "?"}')
    srv_head = ssh(f'cd {SRV_DIR} && git log --pretty=%h -1')
    loc_head = sh('git log --pretty=%h -1', BASE)
    print(f'  ноутбук {loc_head} · сервер {srv_head} '
          f'{"✓ однаково" if srv_head == loc_head else "✗ РОЗІЙШЛИСЬ"}')
    # код поза git
    untracked = [l[3:].strip('"') for l in sh('git status --short', BASE).splitlines()
                 if l.startswith('??')]
    code_out = [f for f in untracked
                if f.endswith(('.py', '.md', '.yaml', '.sh'))
                and not any(f.startswith(p) for p in GENERATED + FOREIGN)]
    if code_out:
        print(f'  ✗ КОД ПОЗА GIT ({len(code_out)}):')
        for f in code_out[:20]:
            print(f'      {f}')
    else:
        print('  ✓ коду поза git немає')


def check_sync():
    print('── НОУТБУК ↔ СЕРВЕР ─────────────────────────────')
    local = py_files_local()
    excl = ' '.join(f"-not -path './{p}*'" for p in FOREIGN + GENERATED)
    remote = ssh(f"cd {SRV_DIR} && find . -name '*.py' {excl} | sed 's#^\\./##' | sort").splitlines()
    rs, ls = set(remote), set(local)
    print(f'  файлів: ноутбук {len(ls)} · сервер {len(rs)} · спільних {len(ls & rs)}')
    only_l = sorted(ls - rs)
    only_r = sorted(rs - ls)
    for name, lst in (('лише на ноутбуці', only_l), ('лише на сервері', only_r)):
        if lst:
            print(f'  {name} ({len(lst)}): {", ".join(lst[:6])}'
                  + (' …' if len(lst) > 6 else ''))
    both = sorted(ls & rs)
    lmd = {}
    for f in both:
        lmd[f] = sh(f'md5sum {f!r}', BASE).split()[0] if os.path.exists(os.path.join(BASE, f)) else ''
    listing = '\n'.join(both)
    rmd_raw = ssh(f"cd {SRV_DIR} && md5sum {' '.join(repr(f) for f in both)} 2>/dev/null")
    rmd = {}
    for line in rmd_raw.splitlines():
        p = line.split(None, 1)
        if len(p) == 2:
            rmd[p[1].strip()] = p[0]
    diff = [f for f in both if f in rmd and lmd.get(f) and lmd[f] != rmd[f]]
    if diff:
        print(f'  ✗ РІЗНИЙ ЗМІСТ ({len(diff)}):')
        for f in diff:
            print(f'      {f}')
    else:
        print('  ✓ зміст спільних файлів однаковий')


def check_runtime():
    print('── ЩО ЗАПУЩЕНО НА СЕРВЕРІ ───────────────────────')
    raw = ssh('systemctl --user list-units --type=service --state=running '
              '--no-legend --plain').splitlines()
    # Перший токен рядка — назва юніта. awk через ssh губить лапки,
    # тому розбираємо тут.
    units = [l.split()[0] for l in raw if l.split()]
    ours = [u for u in units if u not in ('dbus.service',)]
    print(f'  служб: {len(ours)}')
    for u in ours:
        ex = ssh(f'systemctl --user show -p ExecStart --value {u}')
        tgt = next((os.path.basename(t) for t in ex.split()
                    if t.endswith('.py')), '')
        if not tgt and 'http.server' in ex:
            tgt = 'http.server (shared/feeds, НАЗОВНІ через tailscale funnel)'
        print(f'    {u:30} {tgt or ex[:46]}')
    cron = [l for l in ssh('crontab -l').splitlines()
            if l.strip() and not l.startswith('#')]
    print(f'  записів у cron: {len(cron)}')
    procs = ssh("ps -eo etime,cmd --no-headers | grep agent-system | grep -v grep "
                "| sed -E 's#^(.{12}).*/([a-z_]+\\.py).*#\\1 \\2#'").splitlines()
    if procs:
        print('  довгоживучі процеси:')
        for p in procs[:10]:
            print(f'    {p.strip()}')


def check_orphans():
    print('── НЕ ВИКОРИСТОВУЄТЬСЯ ──────────────────────────')
    runtime = ssh('crontab -l') + ssh('cat ~/.config/systemd/user/*.service')
    local = py_files_local()
    text = {}
    for f in local:
        try:
            text[f] = open(os.path.join(BASE, f), encoding='utf-8').read()
        except Exception:
            text[f] = ''
    blob = '\n'.join(text.values())
    cats = {'у cron/службі': [], 'імпортується': [], 'ручний інструмент': [],
            'тест': []}
    for f in local:
        base = os.path.basename(f)[:-3]
        if f.startswith('tests/'):
            cats['тест'].append(f)
        elif base + '.py' in runtime:
            cats['у cron/службі'].append(f)
        elif f'import {base}' in blob or f'from {base}' in blob:
            cats['імпортується'].append(f)
        else:
            cats['ручний інструмент'].append(f)
    for k, v in cats.items():
        print(f'  {k:20}{len(v):5}')
    print('  («ручний інструмент» — НЕ мертвий код: це скрипти для запуску '
          'руками.\n   Мертве шукати за датою останньої зміни, див. '
          'docs/АУДИТ_КОДУ.md)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sync', action='store_true')
    ap.add_argument('--runtime', action='store_true')
    ap.add_argument('--orphans', action='store_true')
    a = ap.parse_args()
    allof = not (a.sync or a.runtime or a.orphans)
    if allof:
        check_git()
    if allof or a.sync:
        check_sync()
    if allof or a.runtime:
        check_runtime()
    if allof or a.orphans:
        check_orphans()


if __name__ == '__main__':
    main()
