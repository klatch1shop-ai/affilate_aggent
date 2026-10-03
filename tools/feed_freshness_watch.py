#!/usr/bin/env python3
"""Вартовий свіжості фідів: сигналить, якщо опублікований фід застояв.

Навіщо: 02.10.2026 прийшло замовлення на товар, якого немає — фід TOPTUL не
оновлювався з 11.09, dropoffice з 15.09. Жоден механізм про це не повідомив,
бо для кожного каналу синхронізацію писали окремо, і відсутність однієї
нічим не виявлялась.

Чому саме так, а не «спільний шар дій»: перехресне обговорення 03.10
(Gemini + Codex) зламало гіпотезу, що проблему розвʼязує спільний шар.
Codex: інцидент пояснюється відсутністю КОНТРОЛЮ обовʼязкових синхронізацій,
а не тим, що інструменти окремі. Gemini: закрити це можна за 20 хвилин.
Перелік обовʼязкових фідів тут — явний, бо забутий у переліку канал
лишиться невидимим (застереження Codex).

    venv/bin/python3 tools/feed_freshness_watch.py
    venv/bin/python3 tools/feed_freshness_watch.py --notify
"""
import argparse
import datetime
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.join(os.path.expanduser('~'), 'noire-feed')

# ЯВНИЙ перелік: що ми зобовʼязані оновлювати і як часто.
# Додав новий фід — додай сюди, інакше його застій ніхто не помітить.
EXPECTED = {
    'noire_rozetka.xml':    {'hours': 3,  'why': 'Rozetka забирає прайс щогодини'},
    'noire_prom.xml':       {'hours': 6,  'why': 'Prom забирає раз на 4 години, вікно 07:00-22:00'},
    'noire_epicentr_stock.xml': {'hours': 4, 'why': 'наявність Єпіцентру кожні 2 години'},
    'toptul_rozetka.xml':   {'hours': 3,  'why': 'синхронізація щогодини з 03.10'},
    'dropoffice_rozetka.xml': {'hours': 3, 'why': 'синхронізація щогодини з 03.10'},
    # noire_epicentr.xml навмисно НЕ тут: вміст заморожений після модерації
}


def check():
    now = datetime.datetime.now()
    rows, stale = [], []
    for name, rule in EXPECTED.items():
        path = os.path.join(REPO, name)
        if not os.path.exists(path):
            rows.append((name, None, rule, 'ФАЙЛУ НЕМАЄ'))
            stale.append(name)
            continue
        age = (now - datetime.datetime.fromtimestamp(os.path.getmtime(path)))
        hours = age.total_seconds() / 3600
        bad = hours > rule['hours']
        rows.append((name, hours, rule, 'ЗАСТІЙ' if bad else 'ок'))
        if bad:
            stale.append(name)
    return rows, stale


def main(notify):
    rows, stale = check()
    print(f'{"фід":<26}{"вік, год":>10}{"межа":>7}  стан')
    for name, hours, rule, state in rows:
        h = f'{hours:.1f}' if hours is not None else '—'
        print(f'{name:<26}{h:>10}{rule["hours"]:>7}  {state}')
    if not stale:
        print('\nусі фіди свіжі')
        return 0
    msg = ('⚠️ ЗАСТІЙ ФІДІВ: ' + ', '.join(stale) +
           '\nФід, який не оновлюється, продає те, чого немає '
           '(02.10 це дало замовлення на відсутній товар).')
    print('\n' + msg)
    if notify:
        try:
            sys.path.insert(0, BASE)
            from tools.notify_owner import notify as tg
            tg(msg)
            print('надіслано власнику')
        except Exception as e:
            print(f'не вдалось надіслати: {type(e).__name__}: {e}')
    return 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--notify', action='store_true')
    sys.exit(main(ap.parse_args().notify))
