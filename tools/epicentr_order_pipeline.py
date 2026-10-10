#!/usr/bin/env python3
"""Автоматизація замовлень Єпіцентру — лише Нова Пошта.

Рішення власника 04.10.2026: «автоматизуємо тільки замовлення нової пошти».
Другий перевізник Єпіцентру — `cvz_epicentr`, їхня власна доставка; такі
замовлення пайплайн НЕ чіпає взагалі.

ЛАНЦЮГ:
  1. знайти замовлення у стані, з якого є куди рухатись;
  2. відсіяти все, крім `nova_poshta`;
  3. визначити, чи потрібна післяплата (див. нижче);
  4. підтвердити замовлення, якщо майданчик це дозволяє;
  5. створити ТТН у Новій Пошті (спільне ядро `helper/ttn.py`);
  6. записати номер у замовлення;
  7. перевести в «відправлено»;
  8. надіслати власнику наклейку 100×100 і підсумок у Telegram.

ПЕРЕВІРЕНІ ФАКТИ (живі виклики 04.10.2026, негативний контроль — вигаданий
шлях, що дає `{"message":"No route configured"}`):

  GET   /v3/oms/orders                                  перелік
  GET   /v6/oms/orders/{id}                             одне замовлення
  GET   /v2/oms/orders/{id}/allowed-statuses            КУДИ можна рухатись зараз
  POST  /v2/oms/orders/{id}/change-status/to/{status}   зміна статусу
  PATCH /v1/oms/orders/{id}/shipment-number  {"number"} номер ТТН
  GET   /v2/oms/order-cancel-reasons/customer           26 причин скасування

  Працюють на базі `core-api` з нашою звичайною сесією. На
  `merchant-api.epicentrm.com.ua` ті самі шляхи просять ОКРЕМИЙ токен,
  який генерується в кабінеті (роль Адміністратор компанії) — у нас його
  немає, і він не потрібен.

  СТАТУСИ НЕ ВГАДУЄМО. `allowed-statuses` на замовленні 58192585 віддав
  рівно два: `canceled` і `confirmed`. Тобто «відправлено» одразу поставити
  не можна, спершу «підтверджено». Пайплайн завжди питає цей метод, бо
  перелік залежить від поточного стану.

  ОПЛАТА. Поле `payed` НЕ ПОКАЗНИК: воно `False` навіть у виконаних
  замовлень. Дивитись треба на `address.shipment.paymentStatus`:
      hold_set        — гроші заблоковані на картці, післяплата НЕ потрібна
      hold_unset      — блок знято (так у всіх виконаних)
      payment_canceled / hold_canceled — скасовані
      none            — трапляється лише з `pay_on_delivery`, це справжня
                        післяплата, і ось тоді потрібен контроль оплати
  Класифікацію знято з 12 замовлень кабінету, а не з документації.

  `shipment` лежить УСЕРЕДИНІ `address`, а не вгорі замовлення.

  Довідники доставки Єпіцентру — це Ref Нової Пошти: `settlement.external_id`
  = CityRef, `office.externalId` = Ref відділення. Звірено: НП за цим Ref
  повернула «Поштомат №26930, вул. Лісового, 45, Кривий Ріг», і CityRef
  збігся з `settlement.external_id`.

ОБЕРЕЖНО: у Єпіцентру НЕМАЄ тестового середовища — будь-яка зміна одразу
потрапляє в бойовий кабінет. Тому за замовчуванням усе йде ВХОЛОСТУ;
справжні дії вмикає `--execute`.

    venv/bin/python tools/epicentr_order_pipeline.py --list
    venv/bin/python tools/epicentr_order_pipeline.py --order 58192585
    venv/bin/python tools/epicentr_order_pipeline.py --order 58192585 --execute
"""
import argparse
import fcntl
import json
import os
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from dotenv import load_dotenv                                    # noqa: E402
load_dotenv(os.path.join(BASE, '.env'), override=True)

import requests                                                   # noqa: E402
from core.actions import _epicentr_session                        # noqa: E402
from helper import ttn as T                                       # noqa: E402

NP_PROVIDER = 'nova_poshta'
# Стани, у яких замовлення ще треба обробити. «Відправлено» й далі — вже наше.
OPEN_STATES = ('new', 'confirmed_by_merchant', 'confirmed')
# Ті, за яких гроші вже на картці й післяплата НЕ потрібна.
PREPAID = ('hold_set', 'hold_unset', 'payed', 'success')
STATE = os.path.join(BASE, 'logs', 'epicentr_pipeline_state.json')
LOCK = os.path.join(BASE, 'logs', 'epicentr_pipeline.lock')
TG_TOKEN = os.getenv('TG_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT = os.getenv('TG_CHAT_ID') or os.getenv('TELEGRAM_ADMIN_ID')


def tg(text, pdf=None):
    if not (TG_TOKEN and TG_CHAT):
        return False
    try:
        if pdf and os.path.exists(pdf):
            with open(pdf, 'rb') as f:
                r = requests.post(
                    f'https://api.telegram.org/bot{TG_TOKEN}/sendDocument',
                    data={'chat_id': TG_CHAT, 'caption': text[:1000],
                          'parse_mode': 'HTML'},
                    files={'document': (os.path.basename(pdf), f,
                                        'application/pdf')}, timeout=90)
        else:
            r = requests.post(
                f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                data={'chat_id': TG_CHAT, 'text': text[:4000],
                      'parse_mode': 'HTML'}, timeout=40)
        return bool(r.json().get('ok'))
    except Exception:
        return False


def load_state():
    try:
        with open(STATE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


class Epicentr:
    def __init__(self):
        self.s, self.api = _epicentr_session()

    def _j(self, r, what):
        if r.status_code >= 400:
            raise RuntimeError(f'{what}: HTTP {r.status_code} {r.text[:200]}')
        return r.json() if r.content else {}

    def orders(self, limit=50):
        r = self.s.get(f'{self.api}/v3/oms/orders',
                       params={'limit': limit}, timeout=60)
        return self._j(r, 'перелік замовлень').get('items') or []

    def order(self, oid):
        # v5, а НЕ v6. Найновіша версія не завжди краща: v6 віддає
        # `office.externalId` порожнім, а це і є Ref відділення Нової Пошти,
        # без якого накладну не створити. v3 і v5 його віддають. Перевірено
        # 04.10 на замовленні 58192585: v3/v5 → Ref, v6 → None.
        r = self.s.get(f'{self.api}/v5/oms/orders/{oid}', timeout=60)
        return self._j(r, f'замовлення {oid}')

    def office_ref(self, provider, settlement_id, office_id):
        """Запасний шлях до Ref відділення — через довідник доставки."""
        r = self.s.get(f'{self.api}/v3/deliveries/providers/{provider}'
                       f'/settlements/{settlement_id}/offices/{office_id}',
                       timeout=60)
        return (self._j(r, 'довідник відділень') or {}).get('externalId')

    def allowed(self, oid):
        r = self.s.get(f'{self.api}/v2/oms/orders/{oid}/allowed-statuses',
                       timeout=60)
        return [x['code'] for x in (self._j(r, 'дозволені статуси')
                                    .get('items') or [])]

    def set_status(self, oid, status):
        r = self.s.post(f'{self.api}/v2/oms/orders/{oid}/change-status/to/{status}',
                        timeout=60)
        return self._j(r, f'статус → {status}')

    def set_ttn(self, oid, number):
        r = self.s.patch(f'{self.api}/v1/oms/orders/{oid}/shipment-number',
                         json={'number': str(number)}, timeout=60)
        return self._j(r, 'запис ТТН')


def shipment(o):
    """`shipment` лежить усередині `address` — на цьому легко спіткнутись."""
    return ((o.get('address') or {}).get('shipment')) or {}


def needs_cod(o):
    """Чи потрібен контроль оплати. Повертає (так/ні, пояснення)."""
    sh = shipment(o)
    ps = sh.get('paymentStatus')
    if sh.get('paymentProvider') == 'pay_on_delivery' or ps in (None, 'none'):
        return True, f'оплата при отриманні (paymentStatus={ps})'
    if ps in PREPAID:
        return False, f'гроші вже на картці (paymentStatus={ps})'
    # Невідомий стан — НЕ вгадуємо на користь «оплачено»: помилка в цей бік
    # означає, що ми віддамо товар безкоштовно.
    raise RuntimeError(f'невідомий стан оплати «{ps}» — потрібне рішення власника')


def plan(ep, number_or_id, st):
    o = None
    for row in ep.orders(100):
        if str(row.get('number')) == str(number_or_id) or row.get('id') == number_or_id:
            o = ep.order(row['id'])
            o['id'] = o.get('id') or row['id']
            o['number'] = o.get('number') or row['number']
            break
    if o is None:
        raise RuntimeError(f'замовлення {number_or_id} не знайдено')

    sh = shipment(o)
    if sh.get('provider') != NP_PROVIDER:
        return {'пропуск': f'перевізник {sh.get("provider")} — автоматизуємо '
                           'лише Нову Пошту', 'замовлення': o['number']}
    if o.get('statusCode') not in OPEN_STATES:
        return {'пропуск': f'стан «{o.get("statusCode")}» — обробляти нічого',
                'замовлення': o['number']}
    if sh.get('number'):
        return {'пропуск': f'ТТН вже записана: {sh["number"]}',
                'замовлення': o['number']}

    cod_needed, why = needs_cod(o)
    amount = o.get('subtotal') or 0
    office = (o.get('office') or {}).get('externalId')
    if not office:
        office = ep.office_ref(NP_PROVIDER, sh.get('settlementId'),
                               sh.get('officeId'))
    if not office:
        raise RuntimeError('у замовленні немає Ref відділення Нової Пошти')
    w = T.warehouse_by_ref(office)
    cust = o.get('address') or {}
    return {
        'замовлення': o['number'], 'id': o['id'],
        'стан': o.get('statusCode'),
        'дозволені_переходи': ep.allowed(o['id']),
        'одержувач': f"{cust.get('lastName','')} {cust.get('firstName','')}".strip(),
        'телефон': cust.get('phone'),
        'відділення': w.get('Description', '')[:80],
        'місто': w.get('CityDescription'),
        'сума': amount,
        'післяплата': f'{amount} грн' if cod_needed else f'НЕ потрібна — {why}',
        'товари': [f"{i.get('sku')} ×{i.get('quantity')}" for i in (o.get('items') or [])],
        '_w': w, '_cod': amount if cod_needed else 0, '_o': o,
        '_items': {i['sku']: int(float(i.get('quantity') or 1))
                   for i in (o.get('items') or []) if i.get('sku')},
    }


def supplier_chain(p, ttn_num, pdf, done, st, save):
    """Оформлення в CRM постачальника — те саме, що й для Rozetka.

    Код навмисно повторює `tools/noire_order_pipeline.py`: там ці кроки вже
    пройшли живу перевірку на замовленні 907753887, разом із трьома рівнями
    страхування. Переписувати їх інакше означало б завести другий, не
    перевірений шлях до тих самих незворотних дій.
    """
    sys.path.insert(0, os.path.join(BASE, 'tools'))
    from playwright.sync_api import sync_playwright
    import smtm_crm as CRM

    items = p['_items']
    with sync_playwright() as pw:
        crm = CRM.Crm(pw)
        try:
            crm.login()
            if not done.get('crm_id'):
                # Кошик мусить бути порожній: недороблена спроба інакше
                # підмішає чужу позицію в наступне замовлення.
                if not crm.cart_is_empty():
                    left = crm.cart_items()
                    if not crm.clear_cart():
                        tg(f'⚠️ Єпіцентр {p["замовлення"]}: кошик CRM не '
                           f'очистився, там {crm.cart_items()}. Зупиняюсь.')
                        raise RuntimeError('кошик не очистився')
                    tg(f'ℹ️ Перед замовленням {p["замовлення"]} прибрано з '
                       f'кошика CRM: {left}')
                for sku, qty in items.items():
                    if not crm.add(sku, qty):
                        raise RuntimeError(f'{sku}: кількість у кошику не збіглась')
                same, why = crm.cart_matches(items)
                if not same:
                    tg(f'❌ Єпіцентр {p["замовлення"]}: {why}. Нічого не оформлено.')
                    raise RuntimeError(why)
                crm.checkout_open()
                done['crm_id'] = crm.place_order()
                save(st)          # фіксуємо ОДРАЗУ після незворотного
                if not crm.cart_is_empty():
                    crm.clear_cart()
            crm_id = done['crm_id']

            note = 'наклейки немає'
            if pdf and os.path.exists(pdf):
                try:
                    _, note = crm.attach_ttn(ttn_num, pdf)
                except Exception as exc:
                    note = f'{type(exc).__name__}: {exc}'
            info = crm.order_info(crm_id) or {}
            done['сума_постачальнику'] = info.get('сума')
            # Правду беремо з даних постачальника, а не з того, що здалося
            # браузеру: кнопка могла натиснутись без результату.
            done['ттн_прикріплено'] = info.get('джерело_ттн') == 'TTN_FILE'
            save(st)
            if not done['ттн_прикріплено']:
                tg(f'⚠️ <b>ПОТРІБНА РУКА</b>\n'
                   f'Єпіцентр {p["замовлення"]} оформлено в постачальника '
                   f'(ID <b>{crm_id}</b>), але ТТН НЕ прикріпилась.\n'
                   f'Причина: {str(note)[:200]}\n'
                   f'Відкрийте https://new.smtm.com.ua/uk/checkout/{crm_id}, '
                   f'оберіть «Прикріпити файл», введіть <code>{ttn_num}</code> '
                   f'і додайте PDF із цього повідомлення.', pdf)
            return done
        except Exception as exc:
            cid = done.get('crm_id')
            if cid:
                # Замовлення вже існує й коштує грошей — мовчати не можна.
                tg(f'❌ <b>ЗБІЙ ПІСЛЯ ОФОРМЛЕННЯ</b>\n'
                   f'Єпіцентр {p["замовлення"]} → постачальник ID <b>{cid}</b>\n'
                   f'{type(exc).__name__}: {str(exc)[:200]}\n'
                   f'Перевірте https://new.smtm.com.ua/uk/checkout/{cid}', pdf)
            raise
        finally:
            crm.close()


def run(number, execute=False, place=True):
    ep = Epicentr()
    st = load_state()
    p = plan(ep, number, st)
    if 'пропуск' in p:
        return p
    show = {k: v for k, v in p.items() if not k.startswith('_')}
    if not execute:
        return {'холостий': show}

    oid = p['id']
    done = st.setdefault(str(p['замовлення']), {})

    # 0. наявність у постачальника — ДО будь-якої незворотної дії
    sys.path.insert(0, os.path.join(BASE, 'agents', 'orders'))
    import rozetka_order_agent as RZ
    ok, lines = RZ.noire_stock([{'sku': k, 'quantity': v}
                                for k, v in p['_items'].items()])
    if ok is not True:
        tg(f'⚠️ Єпіцентр {p["замовлення"]}: товару немає у постачальника\n'
           + '\n'.join(lines))
        return {'зупинка': 'наявність не підтверджена', 'деталі': lines}

    # 1. підтвердити, якщо майданчик це дозволяє і ми ще не підтверджували
    if 'confirmed' in p['дозволені_переходи'] and not done.get('confirmed'):
        ep.set_status(oid, 'confirmed')
        done['confirmed'] = datetime.now(timezone.utc).isoformat()
        save_state(st)

    # 2. накладна — ядро спільне з ручним шляхом у «СУПЕРБОТІ»
    if not done.get('ttn'):
        cust = p['_o'].get('address') or {}
        res = T.create({'first': cust.get('firstName'),
                        'last': cust.get('lastName'),
                        'middle': cust.get('patronymic'),
                        'phone': cust.get('phone')},
                       p['_w'], p['сума'], cod=p['_cod'],
                       description=None, tag=p['замовлення'])
        done['ttn'] = res['ттн']
        done['наклейка'] = res.get('наклейка')
        save_state(st)
    ttn_num = done['ttn']

    # 3. записати номер у замовлення
    if not done.get('ttn_written'):
        ep.set_ttn(oid, ttn_num)
        done['ttn_written'] = True
        save_state(st)

    # 4. перевести у «відправлено», якщо вже дозволено
    allowed = ep.allowed(oid)
    if 'sent' in allowed and not done.get('sent'):
        ep.set_status(oid, 'sent')
        done['sent'] = datetime.now(timezone.utc).isoformat()
        save_state(st)

    # 5. постачальник: оформити й прикріпити ТТН — як у Rozetka
    if place:
        supplier_chain(p, ttn_num, done.get('наклейка'), done, st, save_state)

    out = {'замовлення': p['замовлення'], 'ттн': ttn_num,
           'постачальник_id': done.get('crm_id'),
           'до_сплати_постачальнику': done.get('сума_постачальнику'),
           'ттн_прикріплено': done.get('ттн_прикріплено'),
           'післяплата': p['післяплата'], 'відділення': p['відділення'],
           'статус_після': ep.order(oid).get('statusCode'),
           'дозволені_далі': ep.allowed(oid)}
    tg(f"📦 <b>Замовлення Єпіцентр {p['замовлення']}</b>\n"
       f"ID у постачальника: <b>{done.get('crm_id') or '—'}</b>\n"
       f"До сплати постачальнику: <b>{done.get('сума_постачальнику') or '—'}</b>\n"
       f"ТТН: <code>{ttn_num}</code> ({p['післяплата']})\n"
       f"{p['місто']}, {p['відділення']}\n"
       f"Позиції: {p['_items']}\n"
       f"ТТН прикріплено: "
       f"{'так' if done.get('ттн_прикріплено') else 'НІ — прикріпіть вручну'}\n"
       f"Статус на майданчику: {out['статус_після']}", done.get('наклейка'))
    return out


def auto(execute=False):
    """Знайти відкриті замовлення Нової Пошти й провести їх ланцюгом.

    Так само, як сторож Rozetka: ходить за розкладом, мовчить, коли нічого
    немає, і НЕ береться за замовлення інших перевізників.
    """
    ep = Epicentr()
    out = []
    for row in ep.orders(100):
        if row.get('statusCode') not in OPEN_STATES:
            continue
        o = ep.order(row['id'])
        if shipment(o).get('provider') != NP_PROVIDER:
            continue
        if shipment(o).get('number'):
            continue
        try:
            out.append(run(row['number'], execute))
        except Exception as exc:
            msg = f'{type(exc).__name__}: {exc}'
            tg(f'❌ Єпіцентр {row["number"]}: ланцюг зупинився\n{msg[:300]}')
            out.append({'замовлення': row['number'], 'збій': msg})
    return out or [{'тихо': 'відкритих замовлень Нової Пошти немає'}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--auto', action='store_true',
                    help='знайти й провести всі відкриті замовлення НП')
    ap.add_argument('--order', help='номер або uuid замовлення')
    ap.add_argument('--list', action='store_true', help='відкриті замовлення НП')
    # `--auto` ВИКОНУЄ, як і в noire_order_pipeline. 08.10: було навпаки —
    # той самий прапорець у двох інструментах означав різне, і замовлення
    # Єпіцентру 58264730 тричі на годину «оброблялось» вхолосту, а в
    # журналі стояло «холостий». Для перегляду тепер --dry.
    ap.add_argument('--execute', action='store_true',
                    help='виконати (для --order; --auto виконує завжди)')
    ap.add_argument('--dry', action='store_true',
                    help='лише показати план, нічого не робити')
    ap.add_argument('--no-place', action='store_true',
                    help='не оформлювати в CRM постачальника')
    a = ap.parse_args()

    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, 'w') as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            sys.exit('уже працює інший примірник')

        if a.auto:
            do = not a.dry
            print(json.dumps(auto(do), ensure_ascii=False, indent=1,
                             default=str))
            return
        ep = Epicentr()
        if a.list or not a.order:
            rows = []
            for row in ep.orders(100):
                o = ep.order(row['id'])
                sh = shipment(o)
                if sh.get('provider') != NP_PROVIDER:
                    continue
                rows.append({'номер': row['number'], 'стан': row.get('statusCode'),
                             'оплата': sh.get('paymentStatus'),
                             'ттн': sh.get('number'),
                             'сума': o.get('subtotal'),
                             'відкрите': row.get('statusCode') in OPEN_STATES})
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return
        print(json.dumps(run(a.order, a.execute and not a.dry, not a.no_place),
                         ensure_ascii=False,
                         indent=1, default=str))


if __name__ == '__main__':
    main()
