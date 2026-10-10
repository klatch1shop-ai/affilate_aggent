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
    # Prom публікується за РОЗКЛАДОМ, а не рівномірно: 07:40, 11:40, 15:40,
    # 19:40. Уночі між 19:40 і 07:40 розрив 12 годин — це норма, бо Prom у
    # цей час фід і не забирає. З порогом «6 годин» сторож кричав ЩОНОЧІ
    # (06.10: фід 10,3 год, межа 6 → «ЗАСТІЙ», і так кожну ніч).
    # Підняти поріг до 13 було б гірше: тоді денний застій на 12 годин
    # пройшов би непоміченим. Тому міряємо від ОСТАННЬОЇ ЗАПЛАНОВАНОЇ
    # публікації, а не від «скільки годин минуло».
    'noire_prom.xml':       {'at': (7, 11, 15, 19), 'minute': 40, 'slack': 1.5,
                             'why': 'Prom: публікація 07:40, 11:40, 15:40, 19:40'},
    'noire_epicentr_stock.xml': {'hours': 4, 'why': 'наявність Єпіцентру кожні 2 години'},
    'toptul_rozetka.xml':   {'hours': 3,  'why': 'синхронізація щогодини з 03.10'},
    'dropoffice_rozetka.xml': {'hours': 3, 'why': 'синхронізація щогодини з 03.10'},
    # noire_epicentr.xml навмисно НЕ тут: вміст заморожений після модерації
}


def is_stale(rule, mtime, now):
    """Чи застояв фід. ЄДИНЕ місце, де це вирішується.

    06.10: правило жило у двох написаннях — тут і в `helper/feeds.py`
    (поріг 180 хв на всі фіди). Власник отримував скаргу на застій фіду
    Prom ОДРАЗУ З ДВОХ джерел, і виправлення в одному не доходило в інше.

    `at` — розклад публікації (години). Тоді фід мусить бути новіший за
    останню заплановану публікацію: так ловиться і нічний збій, якого
    «вік у годинах» не побачив би.
    """
    if 'at' in rule:
        due = None
        for back in (0, 1):
            day = now.date() - datetime.timedelta(days=back)
            for h in rule['at']:
                t = datetime.datetime.combine(
                    day, datetime.time(h, rule.get('minute', 0)))
                if t <= now and (due is None or t > due):
                    due = t
        bad = due is not None and mtime < due - datetime.timedelta(
            hours=rule.get('slack', 1))
        return bad, (f'після {due:%H:%M}' if due else '—')
    hours = (now - mtime).total_seconds() / 3600
    return hours > rule['hours'], rule['hours']


def rule_for(name):
    """Правило за іменем файла або назвою майданчика ('prom', 'rozetka')."""
    if name in EXPECTED:
        return EXPECTED[name]
    for fname, rule in EXPECTED.items():
        if fname.startswith(f'noire_{name}') or f'_{name}.' in fname:
            return rule
    return {'hours': 3, 'why': 'правила немає, беремо 3 години'}


def check():
    """→ (рядки, застояли). Якщо теки фідів тут немає — це НЕ застій.

    Фіди лежать на сервері (`~/noire-feed`). На ноутбуці теки немає, і перша
    версія цієї перевірки оголошувала всі пʼять фідів застояними — хибна
    тривога, яка на демонстрації виглядала б як пʼять справжніх проблем.
    """
    now = datetime.datetime.now()
    if not os.path.isdir(REPO):
        return ([(n, None, r.get('hours', '—'), 'перевірка лише на сервері')
                 for n, r in EXPECTED.items()], [])
    rows, stale = [], []
    for name, rule in EXPECTED.items():
        path = os.path.join(REPO, name)
        if not os.path.exists(path):
            rows.append((name, None, rule, 'ФАЙЛУ НЕМАЄ'))
            stale.append(name)
            continue
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
        hours = (now - mtime).total_seconds() / 3600
        bad, limit = is_stale(rule, mtime, now)
        rows.append((name, hours, limit, 'ЗАСТІЙ' if bad else 'ок'))
        if bad:
            stale.append(name)
    return rows, stale


def main(notify):
    rows, stale = check()
    print(f'{"фід":<26}{"вік, год":>10}{"межа":>14}  стан')
    for name, hours, limit, state in rows:
        h = f'{hours:.1f}' if hours is not None else '—'
        print(f'{name:<26}{h:>10}{str(limit):>14}  {state}')
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
