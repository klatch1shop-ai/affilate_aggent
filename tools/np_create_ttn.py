#!/usr/bin/env python3
"""ТТН Нової Пошти для замовлення Rozetka (NOIRE) — перша ручна версія.

Покрокові вказівки власника (13.09.2026):
  * відправка завжди з Дніпра, відділення №1;
  * за доставку платить замовник (одержувач, готівкою);
  * посилка — опція «до 2 кг»; оголошена вартість = сума замовлення;
  * опис вантажу — коротка назва товару (15.09; спершу було «нейтрально»);
  * оплачене замовлення — БЕЗ контролю оплати; оплата при отриманні — з
    контролем оплати на суму замовлення через `AfterpaymentOnGoodsCost`
    (параметри знято з реальної ТТН 20451551222733). Картка не потрібна.
    Помилка 20000201794 до 03.10 виникала через відсутність договору ФОП
    із цією послугою, а не через код;
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
# NP_COD_CARD більше не використовується: контроль оплати картки не потребує
# (знято з реальної ТТН 20451551222733, 03.10.2026).

# Відправник: Дніпро, Відділення №1 (вул. Повітряна, 2) — перевірено 13.09.2026
SENDER_CITY = 'db5c88f0-391c-11dd-90d9-001a92567626'
SENDER_WAREHOUSE = '0d545f59-e1c2-11e3-8c4a-0050568002cf'
# служби доставки Rozetka, які насправді є Новою Поштою (перевірено на замовленнях):
#   5     — відділення (13.09, #906078985)
#   43660 — поштомат   (16.09, #906209393)
# ServiceType для обох — WarehouseWarehouse: поштомат у НП теж «відділення».
NP_SERVICES = {5: 'відділення', 43660: 'поштомат'}
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
    ap.add_argument('--dry-params', action='store_true',
                    help='показати ПАРАМЕТРИ майбутньої ТТН і вийти; працює '
                         'навіть якщо ТТН уже є — для перевірки логіки')
    a = ap.parse_args()

    d = RZ.get_order_details(a.order_id)
    if not d:
        sys.exit('замовлення не прочитано')
    dl = d.get('delivery') or {}
    kind = NP_SERVICES.get(dl.get('delivery_service_id'))
    if not kind:
        sys.exit(f"доставка не Нова Пошта (delivery_service_id={dl.get('delivery_service_id')}, "
                 f"назва «{dl.get('delivery_service_name')}»). Відомі: {NP_SERVICES}")
    if (d.get('ttn') or RZ._ttn_of(d)) and not a.dry_params:
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

    if a.dry_params:
        print(f'замовлення {a.order_id}: оплата «{ptype}», paid={paid}, сума {amount}')
        print(f'  → контроль оплати: '
              f'{"AfterpaymentOnGoodsCost=" + str(cod) if cod else "НЕ потрібен (оплачено)"}')
        print(f'  → відділення НП за ref_id {dl.get("ref_id")}')
        w0 = np('Address', 'getWarehouses', {'Ref': dl.get('ref_id') or ''})
        d0 = (w0.get('data') or [{}])[0]
        print(f'  → {d0.get("Description", "НЕ ЗНАЙДЕНО")}')
        print(f'  → одержувач: {dl.get("recipient_last_name")} '
              f'{dl.get("recipient_first_name")}, {dl.get("recipient_phone")}')
        return

    wh = np('Address', 'getWarehouses', {'Ref': dl.get('ref_id') or ''})
    if not wh.get('data'):
        sys.exit(f"відділення НП за ref_id {dl.get('ref_id')} не знайдено — потрібен запасний пошук")
    w = wh['data'][0]
    if str(w.get('Number')) not in str(dl.get('place_number')):
        sys.exit(f"номер відділення не збігся: НП {w.get('Number')} ≠ Rozetka {dl.get('place_number')}")
    # Поштомат — окремий тип точки (16.09: delivery_service_id 43660). Звіряємо з
    # довідником НП, а не з назвою служби в Rozetka, і перевіряємо ліміт ваги комірки.
    is_postomat = w.get('CategoryOfWarehouse') == 'Postomat'
    if (kind == 'поштомат') != is_postomat:
        sys.exit(f"тип точки не збігся: Rozetka каже «{kind}», НП — "
                 f"CategoryOfWarehouse={w.get('CategoryOfWarehouse')}")
    limit = float(w.get('TotalMaxWeightAllowed') or 0)
    if limit and float(PARCEL_WEIGHT) > limit:
        sys.exit(f'вага {PARCEL_WEIGHT} кг більша за ліміт точки {limit:g} кг')
    if cod and is_postomat:
        # у поштоматах післяплата має свої обмеження, ТТН такого виду ми ще не робили
        sys.exit(f'післяплата {cod} грн у поштомат — випадок не перевірений, потрібне рішення власника')

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
    print(f"#{a.order_id}: опис «{desc}» | {kind}: {w['Description']} | оплата {ptype} paid={paid} → післяплата {cod or 'НІ'} | "
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
        'SeatsAmount': '1', 'Description': desc, 'Cost': amount, **snd,
        'CityRecipient': w['CityRef'], 'Recipient': rec['Ref'], 'RecipientAddress': w['Ref'],
        'ContactRecipient': rec['ContactPerson']['data'][0]['Ref'], 'RecipientsPhone': rp,
        'InfoRegClientBarcodes': str(a.order_id),
        'OptionsSeat': [{**BOX, 'volumetricVolume': VOLUME, 'weight': PARCEL_WEIGHT}],
    }
    if cod:
        # КОНТРОЛЬ ОПЛАТИ — це ОДИН параметр `AfterpaymentOnGoodsCost`.
        # Зворотна доставка (`BackwardDeliveryData`) тут ні до чого.
        #
        # Знято з реальної ТТН власника 20451551222733 (03.10.2026), створеної
        # з увімкненим контролем оплати:
        #     AfterpaymentOnGoodsCost = '479.00'
        #     BackwardDeliveryMoney   = 0
        #     BackwardDeliveryCargoType = ''
        # тобто зворотна доставка НЕ використовується взагалі.
        #
        # Раніше код слав `BackwardDeliveryData` з `CargoType: Money` і полем
        # `PaymentCard`. Це був не той механізм. Помилка 20000201794 тоді
        # виникала тому, що в акаунта ще НЕ БУЛО договору ФОП із цією
        # послугою, — а не через код (власник уточнив 03.10). Токен ФОП
        # видано того ж дня.
        params['AfterpaymentOnGoodsCost'] = str(cod)
    doc = np('InternetDocument', 'save', params, retries=1)
    if not doc.get('success') and any('escription' in str(e) for e in doc.get('errors') or []):
        print(f'НП не прийняла опис «{desc}»: {doc.get("errors")} — повтор з «{DESCRIPTION}»')
        params['Description'] = DESCRIPTION
        doc = np('InternetDocument', 'save', params, retries=1)
    # Запасний шлях: якщо контроль оплати не приймається, створюємо ТТН без
    # нього й просимо власника додати вручну. До 03.10 так працювало ЗАВЖДИ,
    # бо не було договору ФОП із цією послугою. Тепер договір є, тож
    # спрацювання цього шляху означає НОВУ причину — її треба розібрати, а не
    # глушити мовчки.
    cod_todo = None
    if not doc.get('success') and cod:
        print(f'УВАГА: контроль оплати не прийнято. Помилки: {doc.get("errors")} '
              f'коди: {doc.get("errorCodes")}')
        params.pop('AfterpaymentOnGoodsCost', None)
        doc = np('InternetDocument', 'save', params, retries=1)
        cod_todo = cod
    if not doc.get('success'):
        print('ПОМИЛКА створення:', doc.get('errors'), doc.get('warnings'))
        sys.exit(1)
    t = doc['data'][0]
    ttn, ref = t['IntDocNumber'], t['Ref']
    print(f"СТВОРЕНО ТТН {ttn} (Ref {ref}), вартість {t.get('CostOnSite')} грн, доставка {t.get('EstimatedDeliveryDate')}")
    if cod_todo:
        cod_line = (f'⚠️ <b>ДОДАЙТЕ КОНТРОЛЬ ОПЛАТИ {cod_todo} грн</b> у кабінеті НП '
                    f'до відправки і роздрукуйте наклейку звідти')
    elif cod:
        cod_line = f'Контроль оплати: {cod} грн'
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
