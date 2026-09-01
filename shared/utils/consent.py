"""
shared/utils/consent.py
========================
Запобіжник на дії, які власник тримає під своїм рішенням.

Що це НЕ є: захист від зловмисника. Той, хто має оболонку, може поставити
дозвіл сам. Це запобіжник від **випадкової** дії й слід у журналі: дозвіл
має автора, причину й термін, і його видно в git-історії журналу.

Чого НЕ стосується (свідомо):
  • читання, пошук, парсинг, скрейпінг — вільно, без дозволів;
  • щогодинна публікація Rozetka і Prom з cron — узгоджена автоматика,
    її блокувати не можна, фід має лишатись свіжим;
  • підтвердження й скасування замовлень агентами — окремий узгоджений
    контур із власним правилом доказу (SKILL-19).

Стосується (рішення власника 23.08.2026):
  epicentr_publish   — публікація фіду Єпіцентру
  epicentr_import    — завантаження файлу в кабінет
  epicentr_moderate  — пакетне переведення карток на модерацію
  price_change       — зміна формули ціни

Дозвіл видається на строк і згасає сам, щоб забутий прапорець не спрацював
через тиждень.

Видати:   python3 -m shared.utils.consent --allow epicentr_publish --hours 12 --why "лист Євгенію"
Показати: python3 -m shared.utils.consent --show
Зняти:    python3 -m shared.utils.consent --revoke epicentr_publish
"""
import os
import sys
import json
import argparse
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORE = os.path.join(BASE, 'data', 'consent.json')
LOG = os.path.join(BASE, 'logs', 'consent.log')

GUARDED = {
    'epicentr_publish':  'публікація фіду Єпіцентру',
    'epicentr_import':   'завантаження файлу в кабінет Єпіцентру',
    'epicentr_moderate': 'пакетне переведення карток на модерацію',
    'price_change':      'зміна формули ціни',
}


def _load():
    if not os.path.exists(STORE):
        return {}
    try:
        with open(STORE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def _log(line):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'{datetime.now():%Y-%m-%d %H:%M}  {line}\n')


def allowed(action: str) -> bool:
    """Чи є чинний дозвіл. Невідома дія — не заблокована (не наша справа)."""
    if action not in GUARDED:
        return True
    rec = _load().get(action)
    if not rec:
        return False
    try:
        return datetime.fromisoformat(rec['until']) > datetime.now()
    except Exception:
        return False


def require(action: str, what: str = '') -> None:
    """Зупиняє програму, якщо дозволу немає. Друкує, що саме зробила б."""
    if allowed(action):
        _log(f'ВИКОНАНО {action} {what}')
        return
    print(f'\n⛔ Дію «{GUARDED.get(action, action)}» зупинено: немає дозволу власника.', file=sys.stderr)
    if what:
        print(f'   Зробила б: {what}', file=sys.stderr)
    print(f'   Видати дозвіл:\n'
          f'     python3 -m shared.utils.consent --allow {action} --hours 12 --why "причина"\n',
          file=sys.stderr)
    _log(f'ЗУПИНЕНО {action} {what}')
    sys.exit(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--allow'); ap.add_argument('--revoke')
    ap.add_argument('--hours', type=float, default=12)
    ap.add_argument('--why', default='')
    ap.add_argument('--show', action='store_true')
    a = ap.parse_args()
    d = _load()

    if a.allow:
        if a.allow not in GUARDED:
            sys.exit(f'невідома дія. Є: {", ".join(GUARDED)}')
        until = datetime.now() + timedelta(hours=a.hours)
        d[a.allow] = {'until': until.isoformat(timespec='minutes'),
                      'why': a.why, 'granted': datetime.now().isoformat(timespec='minutes')}
        _save(d); _log(f'ДОЗВІЛ {a.allow} до {until:%d.%m %H:%M} — {a.why}')
        print(f'дозволено «{GUARDED[a.allow]}» до {until:%d.%m %H:%M}')
        return
    if a.revoke:
        d.pop(a.revoke, None); _save(d); _log(f'ЗНЯТО {a.revoke}')
        print(f'дозвіл на {a.revoke} знято'); return

    print('дія                  стан')
    for k, name in GUARDED.items():
        rec = d.get(k)
        if allowed(k) and rec:
            print(f'  {k:18} ✅ до {rec["until"][5:16].replace("T", " ")}  {rec.get("why", "")}')
        else:
            print(f'  {k:18} ⛔ немає дозволу    ({name})')


if __name__ == '__main__':
    main()
