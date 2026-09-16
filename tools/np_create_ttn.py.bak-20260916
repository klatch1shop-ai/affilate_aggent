#!/usr/bin/env python3
"""ТТН Нової Пошти для замовлення Rozetka (NOIRE) — перша ручна версія.

Покрокові вказівки власника (13.09.2026):
  * відправка завжди з Дніпра, відділення №1;
  * за доставку платить замовник (одержувач, готівкою);
  * посилка — опція «до 2 кг»; оголошена вартість = сума замовлення;
  * опис вантажу — коротка назва товару (15.09; спершу було «нейтрально»);
  * оплачене замовлення — БЕЗ післяплати; оплата при отриманні — З
    післяплатою на суму замовлення (на карту власника, NP_COD_CARD). Поки НП
    блокує переказ на карту через API (20000201794) — ТТН без післяплати, а в
    Telegram — «додайте післяплату N грн» (власник додає в кабінеті);
  * після створення — зберегти наклейку 100×100 (PDF) і надіслати в Telegram;
  * якщо щось не так — власник видалить ТТН у кабінеті, пробуємо знову;
  * (13.09, пізніше) після створення — ТТН у замовлення Rozetka і статус
    61 «Заплановано передачу перевізникові», з перевіркою читанням.

Друк наклейки блокує зміни ТТН через API («Document is already printed»),
тому коли власник має додати післяплату вручну — наклейку не друкуємо,
у Telegram лише текст (друк — з кабінету після зміни).

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
COD_CARD = os.getenv('NP_COD_CARD', '')   # карта власника для післяплати (лише в .env)

# Відправник: Дніпро, Відділення №1 (вул. Повітряна, 2) — перевірено 13.09.2026
SENDER_CITY = 'db5c88f0-391c-11dd-90d9-001a92567626'
SENDER_WAREHOUSE = '0d545f59-e1c2-11e3-8c4a-0050568002cf'
DESCRIPTION = 'Косметика'          # запасний опис, якщо НП не прийме коротку назву
PARCEL_WEIGHT = '2'                # опція «посилка до 2 кг»
# коробка як у всіх ручних ТТН власника: 30×20×10 см (0,006 м³, об'ємна вага 1,5 кг);
# для поштомата НП вимагає саме OptionsSeat
BOX = {'volumetricLength': '30', 'volumetricWidth': '20', 'volumetricHeight': '10'}
VOLUME = '0.006'


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


def tg_text(text):
    r = requests.post(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                      data={'chat_id': TG_CHAT, 'text': text, 'parse_mode': 'HTML'}, timeout=30)
    return r.json().get('ok'), r.text[:200]


def rozetka_ttn(order_id, ttn):
    """ТТН у замовлення Rozetka + статус 61 «Заплановано передачу перевізникові»; перевірка читанням.

    PATCH /orders/{id} {status: 61, ttn} — перевірено 13.09 на #905931436 (з 26).
    """
    st, av = RZ._status_available(order_id)
    if st != 61 and 61 not in av:
        return f'❗ Rozetka: статус 61 недоступний зі статусу {st} — ТТН не додано, додайте вручну'
    try:
        r = requests.patch(f'{RZ.ROZETKA_BASE}/orders/{order_id}', headers=RZ.rz_headers(), verify=False,
                           json={'status': 61, 'ttn': ttn}, timeout=30).json()
    except Exception as e:
        r = {'errors': str(e)}
    time.sleep(3)
    chk = RZ.get_order_details(order_id)
    got = chk.get('ttn') or RZ._ttn_of(chk)
    if chk.get('status') == 61 and got == ttn:
        return 'Rozetka: ТТН додано, статус «Заплановано передачу перевізникові»'
    return f'❗ Rozetka: не підтвердилось (статус {chk.get("status")}, ТТН {got or "—"}; {r.get("errors") or ""})'


def short_description(d):
    """Опис вантажу — коротка назва товару, як у ручних ТТН власника («Satisfyer Juicy»,
    «Otouch DECOR», «Pjur Woman», «Тренажер»). Рішення власника 15.09.

    Бренд — `vendor` із sexopt_products без країни; коротка назва = бренд + наступне
    слово з назви. Бренду в назві немає → перше слово назви. Кілька позицій → « +N»."""
    arts = [str((p.get('item') or {}).get('article') or p.get('article') or '').strip() for p in (d.get('purchases') or [])]
    names = {str((p.get('item') or {}).get('article') or p.get('article') or '').strip():
             p.get('item_name') or (p.get('item') or {}).get('name') or '' for p in (d.get('purchases') or [])}
    rows = {}
    try:
        conn = RZ.get_connection(); cur = conn.cursor()
        cur.execute('SELECT sku, name, vendor FROM sexopt_products WHERE sku = ANY(%s)', (arts,))
        rows = {r['sku']: r for r in cur.fetchall()}
        cur.close(); conn.close()
    except Exception:
        pass
    shorts = []
    for a in arts:
        name = (rows.get(a) or {}).get('name') or names.get(a) or ''
        brand = re.sub(r'\s*\(.*?\)\s*$', '', (rows.get(a) or {}).get('vendor') or '').strip()
        words = name.split()
        m = re.search(re.escape(brand), name, re.I) if brand else None
        if m:
            nxt = re.match(r'\s*([A-Za-z0-9][\w\-]*)', name[m.end():])
            shorts.append(brand + (' ' + nxt.group(1) if nxt else ''))
        elif words:
            shorts.append(words[0].strip(',.'))
    if not shorts:
        return DESCRIPTION
    text = shorts[0] + (f' +{len(shorts) - 1}' if len(shorts) > 1 else '')
    return text[:40]


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
    desc = short_description(d)
    print(f"#{a.order_id}: опис «{desc}» | {w['Description']} | оплата {ptype} paid={paid} → післяплата {cod or 'НІ'} | "
          f"оголошена {amount} | вартість доставки {price.get('data')}")
    if not a.create:
        return
    if cod and not COD_CARD:
        sys.exit('післяплата: у .env немає NP_COD_CARD — без карти не створюємо')

    r = np('Counterparty', 'save', {'CounterpartyType': 'PrivatePerson', 'CounterpartyProperty': 'Recipient', **rcp})
    if not r.get('success'):
        sys.exit(f"одержувача не створено: {r.get('errors')}")
    rec = r['data'][0]
    params = {
        'PayerType': 'Recipient', 'PaymentMethod': 'Cash', 'DateTime': date.today().strftime('%d.%m.%Y'),
        'CargoType': 'Parcel', 'Weight': PARCEL_WEIGHT, 'VolumeGeneral': VOLUME, 'ServiceType': 'WarehouseWarehouse',
        'SeatsAmount': '1', 'Description': desc, 'Cost': amount, **snd,
        'CityRecipient': w['CityRef'], 'Recipient': rec['Ref'], 'RecipientAddress': w['Ref'],
        'ContactRecipient': rec['ContactPerson']['data'][0]['Ref'], 'RecipientsPhone': rp,
        'InfoRegClientBarcodes': str(a.order_id),
        'OptionsSeat': [{**BOX, 'volumetricVolume': VOLUME, 'weight': PARCEL_WEIGHT}],
    }
    if cod:
        # післяплата на карту власника — як у його ручних ТТН; поле PaymentCard
        # (інші назви НП мовчки ігнорує, README «Перевірено справжньою ТТН»)
        params['BackwardDeliveryData'] = [{'PayerType': 'Recipient', 'CargoType': 'Money',
                                           'RedeliveryString': cod, 'PaymentCard': COD_CARD}]
    doc = np('InternetDocument', 'save', params, retries=1)
    if not doc.get('success') and any('escription' in str(e) for e in doc.get('errors') or []):
        print(f'НП не прийняла опис «{desc}»: {doc.get("errors")} — повтор з «{DESCRIPTION}»')
        params['Description'] = DESCRIPTION
        doc = np('InternetDocument', 'save', params, retries=1)
    cod_todo = None   # післяплату власник додає вручну в кабінеті НП
    if not doc.get('success') and cod and '20000201794' in (doc.get('errorCodes') or []):
        # власник 13.09: поки НП блокує переказ на карту через API — створювати без
        # післяплати й писати в Telegram, на яку суму її додати
        params.pop('BackwardDeliveryData')
        doc = np('InternetDocument', 'save', params, retries=1)
        cod_todo = cod
    if not doc.get('success'):
        print('ПОМИЛКА створення:', doc.get('errors'), doc.get('warnings'))
        sys.exit(1)
    t = doc['data'][0]
    ttn, ref = t['IntDocNumber'], t['Ref']
    print(f"СТВОРЕНО ТТН {ttn} (Ref {ref}), вартість {t.get('CostOnSite')} грн, доставка {t.get('EstimatedDeliveryDate')}")
    if cod_todo:
        cod_line = (f'⚠️ <b>ДОДАЙТЕ ПІСЛЯПЛАТУ {cod_todo} грн</b> у кабінеті НП до відправки '
                    f'(через API на карту заблоковано) і роздрукуйте наклейку звідти')
    elif cod:
        cod_line = f'Післяплата: {cod} грн на карту *{COD_CARD[-4:]}'
    else:
        cod_line = 'Післяплата: немає (оплачено)'
    if cod_todo:
        print(f'УВАГА: ТТН без післяплати — додати {cod_todo} грн вручну')
    rz_line = rozetka_ttn(a.order_id, ttn)
    print(rz_line)
    caption = (f'📦 <b>ТТН {ttn}</b> — Rozetka #{a.order_id}\n'
               f'{w.get("CityDescription", "")}, {w["Description"][:60]}\n'
               f'{cod_line}\n'
               f'Оголошена {amount} грн | доставка {t.get("CostOnSite")} грн — платить одержувач\n'
               f'{rz_line}')
    if cod_todo:
        # друк заблокував би зміну ТТН через API («Document is already printed»)
        ok, info = tg_text(caption)
        print('Telegram (текст, без наклейки):', 'надіслано' if ok else f'НЕ надіслано: {info}')
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    pdf = os.path.join(OUT_DIR, f'{ttn}_rozetka_{a.order_id}_100x100.pdf')
    url = f'https://my.novaposhta.ua/orders/printMarking100x100/orders[]/{ref}/type/pdf/apiKey/{NP_KEY}'
    body = requests.get(url, timeout=60).content
    if not body.startswith(b'%PDF'):
        print('наклейку не отримано як PDF:', body[:200])
        ok, info = tg_text(caption + '\n❗ Наклейку не отримано — роздрукуйте з кабінету НП')
        print('Telegram (текст):', 'надіслано' if ok else f'НЕ надіслано: {info}')
        sys.exit(1)
    open(pdf, 'wb').write(body)
    print('наклейка 100×100 збережена:', pdf, len(body), 'байт')
    ok, info = tg_document(pdf, caption)
    print('Telegram:', 'надіслано' if ok else f'НЕ надіслано: {info}')


if __name__ == '__main__':
    main()
