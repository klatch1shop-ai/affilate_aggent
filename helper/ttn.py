"""Створення накладної Нової Пошти — спільне ядро для обох шляхів.

ДВА ШЛЯХИ, ОДНЕ ЯДРО:
  1) за новим замовленням майданчика — одержувача й відділення беремо з
     самого замовлення;
  2) за даними, які власник вводить у «СУПЕРБОТІ» руками — коли замовлення
     прийшло не через API (телефоном, у соцмережах) або в ньому немає
     доставки.

Обидва шляхи закінчуються тим самим викликом `InternetDocument.save` з тим
самим набором параметрів, тому помилка в одному не може розійтися з іншим.
Набір параметрів НЕ вигаданий: він знятий із реальної накладної власника
20451551222733 (03.10.2026) і повторює перевірений `tools/np_create_ttn.py`.

КОНТРОЛЬ ОПЛАТИ — це ОДИН параметр `AfterpaymentOnGoodsCost`. Картка не
потрібна, `BackwardDeliveryData` тут ні до чого. Помилка 20000201794 до
03.10 означала відсутність договору ФОП із цією послугою, а не дефект коду.
"""
import os
import re
import time
from datetime import date

import requests

NP_URL = 'https://api.novaposhta.ua/v2.0/json/'
# Відправник: Дніпро, Відділення №1 (вул. Повітряна, 2) — перевірено 13.09.2026
SENDER_CITY = 'db5c88f0-391c-11dd-90d9-001a92567626'
SENDER_WAREHOUSE = '0d545f59-e1c2-11e3-8c4a-0050568002cf'
PARCEL_WEIGHT = '2'                # опція «посилка до 2 кг»
BOX = {'volumetricLength': '30', 'volumetricWidth': '20', 'volumetricHeight': '10'}
VOLUME = '0.006'
FALLBACK_DESC = 'Косметика'
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'shared', 'feeds', 'orders', 'np_ttn')


def _key():
    k = os.getenv('NP_API_KEY')
    if not k:
        raise RuntimeError('немає NP_API_KEY у .env')
    return k


def np(model, method, props, retries=3):
    """Виклик НП. Порожній data при success — повтор: таке траплялось 13.09."""
    r = {}
    for i in range(retries):
        r = requests.post(NP_URL, timeout=40,
                          json={'apiKey': _key(), 'modelName': model,
                                'calledMethod': method,
                                'methodProperties': props}).json()
        if not r.get('success') or r.get('data'):
            return r
        time.sleep(2 * (i + 1))
    return r


def phone380(p):
    d = re.sub(r'\D', '', p or '')
    if d.startswith('0'):
        d = '38' + d
    return d if len(d) == 12 and d.startswith('380') else ''


def sender():
    s = np('Counterparty', 'getCounterparties',
           {'CounterpartyProperty': 'Sender', 'Page': '1'})
    if not s.get('data'):
        raise RuntimeError(f'відправника НП не отримано: {s.get("errors")}')
    s = s['data'][0]
    cp = np('Counterparty', 'getCounterpartyContactPersons',
            {'Ref': s['Ref'], 'Page': '1'})['data'][0]
    return {'Sender': s['Ref'], 'ContactSender': cp['Ref'],
            'SendersPhone': phone380(cp.get('Phones')),
            'CitySender': SENDER_CITY, 'SenderAddress': SENDER_WAREHOUSE}


def warehouse_by_ref(ref):
    d = np('Address', 'getWarehouses', {'Ref': ref or ''})
    if not d.get('data'):
        raise RuntimeError(f'відділення за Ref {ref} не знайдено: {d.get("errors")}')
    return d['data'][0]


def find_warehouse(city, number):
    """Відділення за назвою міста й номером — для ручного введення.

    Спершу населений пункт (`searchSettlements` розуміє людський ввід
    «Київ», «м. Кам'янське»), далі відділення саме цього міста. Номер
    звіряємо ТОЧНО: «№5» і «№50» інакше злилися б.
    """
    s = np('Address', 'searchSettlements', {'CityName': city, 'Limit': '5'})
    addrs = ((s.get('data') or [{}])[0].get('Addresses') or [])
    if not addrs:
        raise RuntimeError(f'міста «{city}» НП не знає')
    ref = addrs[0]['DeliveryCity']
    num = re.sub(r'\D', '', str(number))
    if not num:
        raise RuntimeError(f'не розібрав номер відділення з «{number}»')
    w = np('Address', 'getWarehouses', {'CityRef': ref, 'FindByString': num})
    hits = [x for x in (w.get('data') or []) if str(x.get('Number')) == num]
    if not hits:
        raise RuntimeError(f'у «{addrs[0]["Present"]}» немає відділення №{num}')
    return hits[0], addrs[0]['Present']


def create(recipient, warehouse, amount, cod=0, description=None,
           tag='', dry_run=False):
    """Створити накладну. `recipient` = {first,last,middle,phone}.

    Повертає {'ттн','ref','вартість_доставки','наклейка',...}.
    `cod` > 0 → контроль оплати на цю суму.
    """
    rp = phone380(recipient.get('phone'))
    if not (recipient.get('first') and recipient.get('last') and rp):
        raise RuntimeError('потрібні імʼя, прізвище і телефон одержувача '
                           f'(телефон розібрано як «{rp}»)')
    amount = str(int(float(amount)))
    cod = int(float(cod or 0))
    desc = (description or FALLBACK_DESC)[:60]

    # Післяплата в поштомат ДОЗВОЛЕНА власником 06.10.2026 як дослід.
    # Факт лишається: платіжного терміналу в поштоматах немає (перевірено
    # на 2737 точках Дніпра — POSTerminal=1 лише у відділень). Якщо НП не
    # прийме, спрацює запасний шлях без контролю оплати.
    if cod and warehouse.get('CategoryOfWarehouse') == 'Postomat':
        print(f'УВАГА: контроль оплати {cod} грн у ПОШТОМАТ — дослід, '
              f'платіжного терміналу там немає')
    limit = float(warehouse.get('TotalMaxWeightAllowed') or 0)
    if limit and float(PARCEL_WEIGHT) > limit:
        raise RuntimeError(f'вага {PARCEL_WEIGHT} кг більша за ліміт точки {limit:g} кг')

    price = np('InternetDocument', 'getDocumentPrice', {
        'CitySender': SENDER_CITY, 'CityRecipient': warehouse['CityRef'],
        'Weight': PARCEL_WEIGHT, 'ServiceType': 'WarehouseWarehouse',
        'Cost': amount, 'CargoType': 'Parcel', 'SeatsAmount': '1',
        **({'RedeliveryCalculate': {'CargoType': 'Money', 'Amount': cod}} if cod else {})})
    plan = {'одержувач': f"{recipient['last']} {recipient['first']}",
            'телефон': rp, 'відділення': warehouse.get('Description', '')[:70],
            'місто': warehouse.get('CityDescription', ''),
            'оголошена_вартість': f'{amount} грн',
            'контроль_оплати': f'{cod} грн' if cod else 'не потрібен (оплачено)',
            'опис': desc,
            'доставка_орієнтовно': (price.get('data') or [{}])[0].get('Cost')}
    if dry_run:
        return {'холостий': plan}

    r = np('Counterparty', 'save', {
        'CounterpartyType': 'PrivatePerson', 'CounterpartyProperty': 'Recipient',
        'FirstName': recipient['first'], 'LastName': recipient['last'],
        'MiddleName': recipient.get('middle') or '', 'Phone': rp})
    if not r.get('success'):
        raise RuntimeError(f'одержувача не створено: {r.get("errors")}')
    rec = r['data'][0]

    params = {
        'PayerType': 'Recipient', 'PaymentMethod': 'Cash',
        'DateTime': date.today().strftime('%d.%m.%Y'), 'CargoType': 'Parcel',
        'Weight': PARCEL_WEIGHT, 'VolumeGeneral': VOLUME,
        'ServiceType': 'WarehouseWarehouse', 'SeatsAmount': '1',
        'Description': desc, 'Cost': amount, **sender(),
        'CityRecipient': warehouse['CityRef'], 'Recipient': rec['Ref'],
        'RecipientAddress': warehouse['Ref'],
        'ContactRecipient': rec['ContactPerson']['data'][0]['Ref'],
        'RecipientsPhone': rp,
        'OptionsSeat': [{**BOX, 'volumetricVolume': VOLUME,
                         'weight': PARCEL_WEIGHT}],
    }
    if tag:
        params['InfoRegClientBarcodes'] = str(tag)
    if cod:
        params['AfterpaymentOnGoodsCost'] = str(cod)

    doc = np('InternetDocument', 'save', params, retries=1)
    # НП інколи не приймає опис вантажу — пробуємо запасний.
    if not doc.get('success') and any('escription' in str(e)
                                      for e in doc.get('errors') or []):
        params['Description'] = FALLBACK_DESC
        doc = np('InternetDocument', 'save', params, retries=1)
    cod_todo = None
    if not doc.get('success') and cod:
        # Запасний шлях: без контролю оплати, власник додасть у кабінеті.
        # Договір ФОП є з 03.10, тому спрацювання цього шляху означає НОВУ
        # причину — її треба розібрати, а не глушити мовчки.
        params.pop('AfterpaymentOnGoodsCost', None)
        doc = np('InternetDocument', 'save', params, retries=1)
        cod_todo = cod
    if not doc.get('success'):
        raise RuntimeError(f'НП не створила накладну: {doc.get("errors")} '
                           f'{doc.get("warnings")}')
    t = doc['data'][0]
    out = {'ттн': t['IntDocNumber'], 'ref': t['Ref'],
           'вартість_доставки': t.get('CostOnSite'),
           'доставка_до': t.get('EstimatedDeliveryDate'),
           'контроль_оплати': (f'{cod} грн' if cod and not cod_todo
                               else 'НЕ встановлено — додайте в кабінеті НП'
                               if cod_todo else 'не потрібен'),
           **plan}
    # Наклейку НЕ друкуємо, якщо власник має щось правити: друк блокує зміни
    # ТТН через API («Document is already printed»).
    if not cod_todo:
        out['наклейка'] = label(t['Ref'], t['IntDocNumber'], tag)
    return out


def label(ref, ttn, tag=''):
    """Наклейка 100×100 у PDF. Повертає шлях або None."""
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f'{ttn}{"_" + str(tag) if tag else ""}_100x100.pdf')
    url = (f'https://my.novaposhta.ua/orders/printMarking100x100/orders[]/'
           f'{ref}/type/pdf/apiKey/{_key()}')
    body = requests.get(url, timeout=60).content
    if not body.startswith(b'%PDF'):
        return None
    with open(path, 'wb') as f:
        f.write(body)
    return path
