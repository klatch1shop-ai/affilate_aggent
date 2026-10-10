#!/usr/bin/env python3
"""Довідник команд для web/ — збирається З КОДУ, а не пишеться руками.

Кожна фраза проганяється через `supervisor.parse()`: у файл потрапляють
лише ті, що справді розпізнаються. 10.10.2026 саме так знайшлося, що
основа «відповід» не міститься у слові «відповісти» — найприродніша
фраза не працювала взагалі.

    venv/bin/python tools/web_commands_build.py
"""
import io
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from helper import supervisor as S                                 # noqa: E402

MARKET = {'orders.': 'Prom', 'messages.': 'Prom', 'chat.': 'Prom',
          'products.': 'Prom', 'ttn.': 'Нова Пошта',
          'epicentr.': 'Єпіцентр', 'rozetka.': 'Rozetka'}
RISK = {'R0': 'читання, виконується одразу',
        'R2': 'змінює дані майданчика',
        'R3': 'гроші або зобовʼязання'}
API = {
    'orders.list': 'GET /orders/list',
    'orders.get': 'GET /orders/{id}',
    'messages.list': 'GET /messages/list',
    'orders.set_status': 'POST /orders/set_status',
    'messages.reply': 'POST /messages/reply',
    'ttn.create': 'Нова Пошта: InternetDocument + AfterpaymentOnGoodsCost',
    'ttn.manual': 'Нова Пошта: InternetDocument',
    'epicentr.orders': 'GET /v3/oms/orders',
    'epicentr.ship': 'change-status → ТТН → PATCH /v1/oms/orders/{id}/shipment-number',
    'products.stock': 'GET /products/list + POST /products/edit_by_external_id',
    'chat.rooms': 'GET /chat/rooms',
    'chat.history': 'GET /chat/messages_history',
    'chat.send': 'POST /chat/send_message',
    'epicentr.attributes': 'GET /v2/pim/attribute-sets · /v2/pim/attributes/by-code/{code}/options',
    'epicentr.cards': 'локальний зріз data/epicentr_products.json',
    'rozetka.orders': 'GET /orders/search',
    'rozetka.reviews': 'GET /market-reviews/search',
    'rozetka.review_reply': 'POST /market-review-replies/reply',
}
SAY = {
    'orders.list': ['покажи замовлення'],
    'orders.get': ['замовлення 432486760'],
    'messages.list': ['питання покупців'],
    'orders.set_status': ['замовлення 432486760 отримано',
                          'познач замовлення 432486760 доставлено'],
    'messages.reply': ['відповісти 12345 Доброго дня, відправимо сьогодні'],
    'ttn.create': ['зроби ттн на замовлення 432486760'],
    'ttn.manual': ['ттн Шевченко; Тарас; 0501234567; Київ; 12; 780; післяплата'],
    'epicentr.orders': ['що на епіцентрі'],
    'epicentr.ship': ['епіцентр 58264730'],
    'products.stock': ['наявність SO5912 немає', 'наявність SO5912 20'],
    'chat.rooms': ['чати прому'],
    'chat.history': ['листування з покупцями'],
    'chat.send': ['напиши покупцю 44332113_4053918_buyer '
                  'Ваше замовлення передано у доставку'],
    'epicentr.attributes': ['атрибути епіцентру'],
    'epicentr.cards': ['картки епіцентру за статусом'],
    'rozetka.orders': ['замовлення розетки'],
    'rozetka.reviews': ['відгуки розетки'],
    'rozetka.review_reply': ['відповісти на відгук 6599303 Дякуємо за відгук!'],
}


def main():
    out, bad = [], []
    for name, spec in S.COMMANDS.items():
        phrases = []
        for ph in SAY.get(name, []):
            got = (S.parse(ph) or {}).get('command')
            if got == name:
                phrases.append(ph)
            else:
                bad.append(f'{name}: «{ph}» → {got}')
        if not phrases:
            bad.append(f'{name}: жодної робочої фрази')
        out.append({
            'команда': name,
            'майданчик': next((v for k, v in MARKET.items()
                               if name.startswith(k)), 'Інше'),
            'що': spec['about'], 'параметри': spec['params'],
            'api': API.get(name, ''), 'ризик': spec['risk'],
            'ризик_що': RISK[spec['risk']],
            'підтвердження': spec['risk'] != 'R0', 'фрази': phrases,
        })
    path = os.path.join(BASE, 'web', 'commands.json')
    io.open(path, 'w', encoding='utf-8').write(json.dumps(
        {'оновлено': __import__('datetime').date.today().isoformat(),
         'джерело': 'helper/supervisor.py',
         'перевірено': 'кожну фразу прогнано через parse()',
         'команди': out}, ensure_ascii=False, indent=1))
    print(f'команд: {len(out)} · фраз: {sum(len(c["фрази"]) for c in out)} → {path}')
    if bad:
        print('НЕ РОЗПІЗНАЛИСЬ:')
        for b in bad:
            print('  ' + b)
        sys.exit(1)
    print('усі фрази розпізнаються')


if __name__ == '__main__':
    main()
