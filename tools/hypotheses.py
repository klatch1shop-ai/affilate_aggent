#!/usr/bin/env python3
"""Реєстр гіпотез: висунути → перевірити → впровадити або відкинути.

Навіщо (власник, 03.10): «нам треба система, яка може робити гіпотези,
перевіряти їх та впроваджувати». За один день 03.10 було висунуто з десяток
гіпотез про Prom; три спростовано, одну підтверджено, решта загубилась у
переписці. Реєстр робить цикл замкненим.

ГІПОТЕЗИ ВИСУВАЮТЬСЯ ВІЛЬНО. Правило «перевір вимірювач перед тим, як
назвати число» (скіл measuring-before-reporting) стосується ПЕРЕВІРКИ, а не
висування: гіпотеза має бути дешевою, їх має бути багато, і смілива гіпотеза
нічого не коштує, доки її не оголосили фактом.

Кожна гіпотеза має нести ЧОТИРИ речі, інакше вона не гіпотеза, а думка:
  * predicts — що саме ми побачимо, якщо вона правдива;
  * refuted_by — яке спостереження її ВБИВАЄ (записується ДО заміру);
  * measured_by — чим міряємо і чи перевірений цей вимірювач;
  * if_true — що робимо, якщо підтвердиться. Без цього перевірка марна.

«refuted_by» записується наперед не з формальності: маркер-дослід 15.09 мав
наперед записаний критерій («стабільний перелік = поріг, змінний = ротація»),
і саме тому його результат вдалося прочитати однозначно через три тижні.

Гіпотезу НЕ перевіряють наодинці: `--discuss H7` віддає її колегам через
tools/deliberate.py — вони атакують саме формулювання, спростовність і
спосіб заміру, перш ніж ми витратимо добу на експеримент (нагадаю: ключі
оновлюються лише нічним імпортом, тож один дослід = одна доба).

    venv/bin/python3 tools/hypotheses.py --list
    venv/bin/python3 tools/hypotheses.py --discuss H7
    venv/bin/python3 tools/hypotheses.py --add
    venv/bin/python3 tools/hypotheses.py --resolve H3 --status спростована --note "..."
"""
import argparse
import datetime
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, 'docs', 'research', 'hypotheses.json')

STATUSES = ('нова', 'перевіряється', 'підтверджена', 'спростована',
            'впроваджена', 'відкладена')


def load():
    if os.path.exists(LEDGER):
        return json.load(open(LEDGER, encoding='utf-8'))
    return {'next_id': 1, 'items': []}


def save(d):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    json.dump(d, open(LEDGER, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def add(d, **kw):
    hid = f'H{d["next_id"]}'
    d['next_id'] += 1
    d['items'].append({
        'id': hid, 'created': datetime.date.today().isoformat(),
        'status': 'нова', 'resolved': None, 'note': '', **kw})
    return hid


def show(d, status=None):
    rows = [h for h in d['items'] if not status or h['status'] == status]
    if not rows:
        print('порожньо')
        return
    order = {s: i for i, s in enumerate(STATUSES)}
    for h in sorted(rows, key=lambda x: (order.get(x['status'], 9), x['id'])):
        print(f'\n[{h["id"]}] {h["status"].upper()} · {h["created"]}'
              f'{" → " + h["resolved"] if h["resolved"] else ""}')
        print(f'  гіпотеза:   {h["claim"]}')
        print(f'  передбачає: {h["predicts"]}')
        print(f'  спростує:   {h["refuted_by"]}')
        print(f'  міряємо:    {h["measured_by"]}')
        print(f'  якщо так:   {h["if_true"]}')
        if h.get('note'):
            print(f'  підсумок:   {h["note"]}')


DISCUSS = """Перевір ГІПОТЕЗУ перед тим, як ми витратимо на неї добу.

Гіпотеза:        {claim}
Що передбачає:   {predicts}
Що її спростує:  {refuted_by}
Чим міряємо:     {measured_by}
Що робимо, якщо підтвердиться: {if_true}
Що вже відомо:   {note}

КОНТЕКСТ (усе — заміри, не оцінки):
{context}

ПИТАННЯ:
 1. Чи є «що її спростує» справжнім спростуванням? Назви спостереження,
    яке вписалось би і в гіпотезу, і в її заперечення — тоді критерій
    нічого не розрізняє.
 2. Чи може названий вимірювач дати це число, навіть якщо гіпотеза хибна?
    Яким чином зламаний інструмент підробив би саме такий результат?
 3. Яке ІНШЕ пояснення дає ті самі передбачення? Назви щонайменше одне.
 4. Чи варта ця гіпотеза доби експерименту, чи є дешевший спосіб її
    закрити вже наявними даними?

Відповідай коротко й по пунктах. Рішень не пропонуй — лише ламай."""


def discuss(d, hid, context=''):
    import subprocess
    import tempfile
    h = next((x for x in d['items'] if x['id'] == hid), None)
    if not h:
        raise SystemExit(f'немає гіпотези {hid}')
    text = DISCUSS.format(context=context or '(не наведено)', **{
        k: h.get(k, '') for k in
        ('claim', 'predicts', 'refuted_by', 'measured_by', 'if_true', 'note')})
    f = tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False,
                                    encoding='utf-8')
    f.write(text)
    f.close()
    print(f'{hid} → на обговорення колегам\n')
    subprocess.run([os.sys.executable,
                    os.path.join(BASE, 'tools', 'deliberate.py'),
                    '--question', f.name], cwd=BASE)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--status', choices=STATUSES)
    ap.add_argument('--resolve', metavar='ID')
    ap.add_argument('--discuss', metavar='ID',
                    help='віддати гіпотезу колегам на критику перед дослідом')
    ap.add_argument('--context', default='', help='факти для обговорення')
    ap.add_argument('--note', default='')
    a = ap.parse_args()
    d = load()
    if a.discuss:
        discuss(d, a.discuss, a.context)
    elif a.resolve:
        for h in d['items']:
            if h['id'] == a.resolve:
                h['status'] = a.status or h['status']
                h['resolved'] = datetime.date.today().isoformat()
                h['note'] = a.note or h['note']
                print(f'{h["id"]} → {h["status"]}')
        save(d)
    else:
        show(d, a.status if a.list is False else None)
