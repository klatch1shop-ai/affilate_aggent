"""PDF-наклейка 100×100 для ТТН з нашого кабінету НП — без шкоди для чужої накладної.

Власник 18.09.2026: коли Carvol надсилає ТТН текстом, «PDF теж має бути».

Пастка (NOIRE, 13.09): завантаження наклейки через API позначає накладну
надрукованою, і змінити її вже не можна («Document is already printed»).
Тому друкуємо лише те, що вже надруковане (Printed=1) або вже передане у
відправку (StateId > 1). Свіжостворену ненадруковану — відкладаємо, щоб не
заблокувати відправнику правки. Накладну з чужого кабінету (Carvol) ми
надрукувати не можемо взагалі — PDF дає лише її власник.
"""
import json
import os
from datetime import date, timedelta

import requests

NP_URL = 'https://api.novaposhta.ua/v2.0/json/'
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PENDING = os.path.join(BASE, 'logs', 'np_label_pending.jsonl')


def _key():
    return os.getenv('NP_API_KEY', '')


def our_document(ttn, days=14):
    """Накладна з нашого кабінету (Ref, StateId, Printed…) або None.

    18.09.2026: НП обмежує частоту («To many requests, try again after 1 seconds»)
    і повертає порожній список. Порожнеча через відмову ≠ «накладної немає» —
    перша версія назвала нашу ж накладну NOIRE чужою. Тепер: повтор, а якщо
    відмова лишається — виняток, не None.
    """
    import time
    body = {'apiKey': _key(), 'modelName': 'InternetDocument', 'calledMethod': 'getDocumentList',
            'methodProperties': {'DateTimeFrom': (date.today() - timedelta(days=days)).strftime('%d.%m.%Y'),
                                 'DateTimeTo': date.today().strftime('%d.%m.%Y'), 'GetFullList': '1'}}
    for attempt in range(4):
        r = requests.post(NP_URL, timeout=60, json=body).json()
        if not r.get('errors'):
            return next((d for d in r.get('data') or [] if d.get('IntDocNumber') == str(ttn)), None)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"НП відмовила: {r.get('errors')}")


def label_pdf(ttn, out_dir='/tmp'):
    """→ (шлях до PDF або None, пояснення, 'ok' | 'later' | 'foreign' | 'error')."""
    try:
        doc = our_document(ttn)
    except Exception as e:
        return None, f'НП недоступна: {e}', 'error'
    if not doc:
        return None, 'накладна створена не в нашому кабінеті НП — PDF може дати лише відправник (Carvol)', 'foreign'
    printed = str(doc.get('Printed')) == '1'
    state = int(doc.get('StateId') or 0)
    if not printed and state <= 1:
        return None, ('накладна щойно створена й не надрукована — друк зараз заблокував би її '
                      'зміну відправнику; PDF надішлю о 21:00'), 'later'
    url = (f"https://my.novaposhta.ua/orders/printMarking100x100/orders[]/{doc['Ref']}"
           f"/type/pdf/apiKey/{_key()}")
    body = requests.get(url, timeout=60).content
    if not body.startswith(b'%PDF'):
        return None, 'НП не віддала PDF — роздрукуйте з кабінету', 'error'
    path = os.path.join(out_dir, f'{ttn}_100x100.pdf')
    open(path, 'wb').write(body)
    return path, f'наклейка 100×100 з нашого кабінету НП ({doc.get("StateName", "")})', 'ok'


def defer(ttn, order_id):
    os.makedirs(os.path.dirname(PENDING), exist_ok=True)
    with open(PENDING, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'ttn': str(ttn), 'order_id': order_id, 'since': date.today().isoformat()}) + '\n')


def pending():
    if not os.path.exists(PENDING):
        return []
    out = {}
    for line in open(PENDING, encoding='utf-8'):
        try:
            r = json.loads(line)
            out[r['ttn']] = r
        except ValueError:
            continue
    return list(out.values())


def done(ttns):
    left = [r for r in pending() if r['ttn'] not in set(ttns)]
    with open(PENDING, 'w', encoding='utf-8') as f:
        for r in left:
            f.write(json.dumps(r) + '\n')
