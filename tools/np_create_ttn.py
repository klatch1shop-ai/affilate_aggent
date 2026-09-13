#!/usr/bin/env python3
"""ТТН Нової Пошти для замовлення Rozetka (NOIRE) — перша ручна версія.

Покрокові вказівки власника (13.09.2026):
  * відправка завжди з Дніпра, відділення №1;
  * за доставку платить замовник (одержувач, готівкою);
  * посилка — опція «до 2 кг»; оголошена вартість = сума замовлення;
  * опис вантажу нейтральний;
  * оплачене замовлення — БЕЗ післяплати; оплата при отриманні — З
    післяплатою на суму замовлення;
  * після створення — зберегти наклейку 100×100 (PDF) і надіслати в Telegram;
  * якщо щось не так — власник видалить ТТН у кабінеті, пробуємо знову.

ТТН у замовлення Rozetka цей скрипт НЕ ставить (статус змінився б на 61) —
окремим кроком за вказівкою власника.

Довідка: shared/knowledge_base/novaposhta/README.md

    python3 tools/np_create_ttn.py 905931436            # розрахунок, без створення
    python3 tools/np_create_ttn.py 905931436 --create   # створити, PDF, Telegram
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import date

import requests
import urllib3

urllib3.disable_warnings()
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'agents', 'orders'))
sys.path.insert(0, BASE)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE, '.env'))
import rozetka_order_agent as RZ  # noqa: E402

NP_URL = 'https://api.novaposhta.ua/v2.0/json/'
NP_KEY = os.getenv('NP_API_KEY', '')
TG_TOKEN = os.getenv('TG_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT = os.getenv('TG_CHAT_ID') or os.getenv('TELEGRAM_ADMIN_ID')
OUT_DIR = os.path.join(BASE, 'shared', 'feeds', 'orders', 'np_ttn')

# Відправник: Дніпро, Відділення №1 (вул. Повітряна, 2) — перевірено 13.09.2026
SENDER_CITY = 'db5c88f0-391c-11dd-90d9-001a92567626'
SENDER_WAREHOUSE = '0d545f59-e1c2-11e3-8c4a-0050568002cf'
DESCRIPTION = 'Косметика'          # нейтрально, значення з довідника НП
PARCEL_WEIGHT = '2'                # опція «посилка до 2 кг»
VOLUME = '0.002'                   # м³ ≈ 20×10×10 см, об'ємна вага 0,5 кг


def np(model, method, props, retries=3):
    """Запит до НП. Порожній data при success — повтор (траплялось 13.09)."""
    for i in range(retries):
        r = requests.post(NP_URL, json={'apiKey': NP_KEY, 'modelName': model,
                                        'calledMethod': method, 'methodProperties': props},
                          timeout=40).json()
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
    s = np('Counterparty', 'getCounterparties', {'CounterpartyProperty': 'Sender', 'Page': '1'})['data'][0]
    cp = np('Counterparty', 'getCounterpartyContactPersons', {'Ref': s['Ref'], 'Page': '1'})['data'][0]
    return {'Sender': s['Ref'], 'ContactSender': cp['Ref'], 'SendersPhone': phone380(cp.get('Phones')),
            'CitySender': SENDER_CITY, 'SenderAddress': SENDER_WAREHOUSE}


def tg_document(path, caption):
    with open(path, 'rb') as f:
        r = requests.post(f'https://api.telegram.org/bot{TG_TOKEN}/sendDocument',
                          data={'chat_id': TG_CHAT, 'caption': caption, 'parse_mode': 'HTML'},
                          files={'document': (os.path.basename(path), f, 'application/pdf')}, timeout=60)
    return r.json().get('ok'), r.text[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('order_id', type=int)
    ap.add_argument('--create', action='store_true', help='створити ТТН (без прапорця — лише розрахунок)')
    a = ap.parse_args()

    d = RZ.get_order_details(a.order_id)
    if not d:
        sys.exit('замовлення не прочитано')
    dl = d.get('delivery') or {}
    if dl.get('delivery_service_id') != 5:
        sys.exit(f"доставка не Нова Пошта (delivery_service_id={dl.get('delivery_service_id')})")
    if d.get('ttn') or RZ._ttn_of(d):
        sys.exit(f'у замовленні вже є ТТН: {d.get("ttn") or RZ._ttn_of(d)}')

    paid = RZ.payment_paid(d)
    ptype = d.get('payment_type') or (d.get('payment') or {}).get('payment_type')
    amount = str(int(float(d.get('amount') or d.get('cost') or 0)))
    if paid is True:
        cod = None
    elif ptype in ('cash', 'cod'):
        cod = amount
    else:
        sys.exit(f'оплата «{ptype}» (paid={paid}) — правило післяплати не визначене, зупиняюсь')

    wh = np('Address', 'getWarehouses', {'Ref': dl.get('ref_id') or ''})
    if not wh.get('data'):
        sys.exit(f"відділення НП за ref_id {dl.get('ref_id')} не знайдено — потрібен запасний пошук")
    w = wh['data'][0]
    if str(w.get('Number')) not in str(dl.get('place_number')):
        sys.exit(f"номер відділення не збігся: НП {w.get('Number')} ≠ Rozetka {dl.get('place_number')}")

    rp = phone380(dl.get('recipient_phone') or d.get('recipient_phone'))
    rcp = {'FirstName': dl.get('recipient_first_name'), 'LastName': dl.get('recipient_last_name'),
           'MiddleName': dl.get('recipient_second_name') or '', 'Phone': rp}
    if not (rcp['FirstName'] and rcp['LastName'] and rp):
        sys.exit('немає імені, прізвища чи телефону одержувача')

    snd = sender()
    price = np('InternetDocument', 'getDocumentPrice', {
        'CitySender': SENDER_CITY, 'CityRecipient': w['CityRef'], 'Weight': PARCEL_WEIGHT,
        'ServiceType': 'WarehouseWarehouse', 'Cost': amount, 'CargoType': 'Parcel', 'SeatsAmount': '1',
        **({'RedeliveryCalculate': {'CargoType': 'Money', 'Amount': cod}} if cod else {})})
    print(f"#{a.order_id}: {w['Description']} | оплата {ptype} paid={paid} → післяплата {cod or 'НІ'} | "
          f"оголошена {amount} | вартість доставки {price.get('data')}")
    if not a.create:
        return

    r = np('Counterparty', 'save', {'CounterpartyType': 'PrivatePerson', 'CounterpartyProperty': 'Recipient', **rcp})
    if not r.get('success'):
        sys.exit(f"одержувача не створено: {r.get('errors')}")
    rec = r['data'][0]
    params = {
        'PayerType': 'Recipient', 'PaymentMethod': 'Cash', 'DateTime': date.today().strftime('%d.%m.%Y'),
        'CargoType': 'Parcel', 'Weight': PARCEL_WEIGHT, 'VolumeGeneral': VOLUME, 'ServiceType': 'WarehouseWarehouse',
        'SeatsAmount': '1', 'Description': DESCRIPTION, 'Cost': amount, **snd,
        'CityRecipient': w['CityRef'], 'Recipient': rec['Ref'], 'RecipientAddress': w['Ref'],
        'ContactRecipient': rec['ContactPerson']['data'][0]['Ref'], 'RecipientsPhone': rp,
        'InfoRegClientBarcodes': str(a.order_id),
    }
    if cod:
        params['BackwardDeliveryData'] = [{'PayerType': 'Recipient', 'CargoType': 'Money', 'RedeliveryString': cod}]
    doc = np('InternetDocument', 'save', params, retries=1)
    if not doc.get('success'):
        print('ПОМИЛКА створення:', doc.get('errors'), doc.get('warnings'))
        sys.exit(1)
    t = doc['data'][0]
    ttn, ref = t['IntDocNumber'], t['Ref']
    print(f"СТВОРЕНО ТТН {ttn} (Ref {ref}), вартість {t.get('CostOnSite')} грн, доставка {t.get('EstimatedDeliveryDate')}")

    os.makedirs(OUT_DIR, exist_ok=True)
    pdf = os.path.join(OUT_DIR, f'{ttn}_rozetka_{a.order_id}_100x100.pdf')
    url = f'https://my.novaposhta.ua/orders/printMarking100x100/orders[]/{ref}/type/pdf/apiKey/{NP_KEY}'
    body = requests.get(url, timeout=60).content
    if not body.startswith(b'%PDF'):
        print('наклейку не отримано як PDF:', body[:200])
        sys.exit(1)
    open(pdf, 'wb').write(body)
    print('наклейка 100×100 збережена:', pdf, len(body), 'байт')
    ok, info = tg_document(pdf, f'📦 <b>ТТН {ttn}</b> — Rozetka #{a.order_id}\n'
                                f'Київ, {w["Description"][:60]}\n'
                                f'Післяплата: {cod or "немає (оплачено)"} | оголошена {amount} грн\n'
                                f'Доставка {t.get("CostOnSite")} грн — платить одержувач')
    print('Telegram:', 'надіслано' if ok else f'НЕ надіслано: {info}')


if __name__ == '__main__':
    main()
