#!/usr/bin/env python3
"""Автоматизація замовлень NOIRE на Prom — лише Нова Пошта.

Рішення власника 07.10.2026: «для прому треба noire автоматизацію ввімкнути».

ЩО БУЛО ДО ЦЬОГО. На Prom працював `order_agent_daemon.py` під системною
службою root `order-agent.service` з `Restart=always`. Він написаний під
ДРОПШИПІНГ TOPTUL, а на Prom у нас NOIRE — товарів TOPTUL там нуль
(перевірено: 5684 картки, жодного артикула). Тобто він щоп'ять хвилин ганяв
порожній цикл, ще й із мертвим токеном. Зупинено й вимкнено 07.10.

ПЕРЕВІРЕНІ ФАКТИ PROM (живі виклики 06–07.10, негативний контроль — вигаданий
шлях дає HTML 404):
  GET  /orders/list, /orders/{id}      — працюють
  POST /orders/set_status              — приймає ЛИШЕ received/delivered/paid,
                                         віддає 200 І НА ПОМИЛКУ;
                                         успіх = наш id у `processed_ids`
  POST /delivery/save_declaration_id   — ЗАПИС ТТН У ЗАМОВЛЕННЯ
       {delivery_type, order_id, declaration_id}
       delivery_type: nova_poshta | ukrposhta | meest | rozetka_delivery

  07.10 я спершу оголосив, що такого методу НЕМАЄ: перебрав вісім назв
  (set_declaration, set_ttn, orders/edit, declarations/save…), усі дали 404,
  і я зробив висновок. Насправді правильна назва лежала в нашій же довідці
  `shared/knowledge_base/prom/api_faq.txt` — різниця у двох літерах `_id`.
  Урок: перед тим як вгадувати шляхи, читати власну базу знань.

  `delivery_provider_data.recipient_warehouse_id` — це справжній Ref
  відділення Нової Пошти. Звірено: НП за цим Ref повернула відділення, яке
  збіглося з текстовою адресою в самому замовленні.

  Оплата: `payment_data.status == 'paid_out'` — гроші отримано. Інакше
  післяплата на суму замовлення.

ЛАНЦЮГ: наявність → ТТН (з контролем оплати, якщо не оплачено) → наклейка →
замовлення в CRM постачальника → прикріплення ТТН → Telegram власнику.

РЕЖИМИ — однаково з noire_order_pipeline і epicentr_order_pipeline, щоб
не повторити 58264730 (там `--auto` означав різне у двох файлах і замовлення
добу крутилось вхолосту):
    --auto          ВИКОНУЄ всі відкриті замовлення (це і стоїть у cron)
    --auto --dry    те саме вхолосту
    --order N       показує, нічого не робить
    --order N --execute   виконує одне замовлення

    venv/bin/python tools/prom_order_pipeline.py --list
    venv/bin/python tools/prom_order_pipeline.py --auto --dry
    venv/bin/python tools/prom_order_pipeline.py --auto
"""
import argparse
import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'agents', 'orders'))
sys.path.insert(0, os.path.join(BASE, 'tools'))

from dotenv import load_dotenv                                     # noqa: E402
load_dotenv(os.path.join(BASE, '.env'), override=True)

import requests                                                    # noqa: E402
from helper.supervisor import _prom                                # noqa: E402
from helper import ttn as T                                        # noqa: E402

NP = 'nova_poshta'
# Кінцеві стани, у яких робити нічого. Решту вважаємо відкритими — так
# безпечніше: новий статус Prom не має тихо випадати з обробки.
FINAL = ('delivered', 'canceled', 'completed', 'closed')
PAID = ('paid_out', 'paid', 'success')
STATE = os.path.join(BASE, 'logs', 'prom_pipeline_state.json')
LOCK = os.path.join(BASE, 'logs', 'prom_pipeline.lock')
# Кошик у CRM постачальника ОДИН на акаунт, а конвеєрів три (Rozetka,
# Єпіцентр, Prom) — кожен зі своїм локом, тож один одного вони не стримують.
# Перекриття означало б, що один чистить кошик, поки другий його наповнює.
# `cart_matches()` таке зловить і скасує оформлення, але краще не доводити.
# Цей лок беремо на час роботи з CRM; щоб він захищав по-справжньому, ті
# самі два рядки потрібні в noire_ та epicentr_pipeline — а їх без дозволу
# власника не чіпаю (правило «noire не змінювати»).
CART_LOCK = os.path.join(BASE, 'logs', 'smtm_cart.lock')
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


def order_items(o):
    out = {}
    for p in (o.get('products') or []):
        a = (p.get('external_id') or '').strip()
        if a:
            out[a] = out.get(a, 0) + int(float(p.get('quantity') or 1))
    return out


def amount(o):
    return float(re.sub(r'[^\d.]', '', (o.get('price') or '').replace(' ', '')) or 0)


def is_paid(o):
    return (o.get('payment_data') or {}).get('status') in PAID


def plan(oid):
    o = _prom('GET', f'orders/{int(oid)}').get('order') or {}
    if not o:
        return {'відмова': f'замовлення {oid} не знайдено'}
    if o.get('status') in FINAL:
        return {'пропуск': f'стан «{o.get("status")}» — обробляти нічого',
                'замовлення': oid}
    dp = o.get('delivery_provider_data') or {}
    if dp.get('provider') != NP:
        return {'пропуск': f'доставка {dp.get("provider")} — автоматизуємо '
                           'лише Нову Пошту', 'замовлення': oid}
    if dp.get('declaration_number'):
        # ТТН є — але чи йшло замовлення постачальнику? Якщо її створив
        # власник руками (09.10, замовлення 432486760 — «я в дорозі це
        # заповнював»), ми пропускали ВЕСЬ ланцюг, і крок 2 не виконувався
        # теж. Оформити самим не можна: власник міг уже оформити, а дубль у
        # постачальника коштує грошей. Тому один раз питаємо людину.
        return {'пропуск': f'ТТН уже є: {dp["declaration_number"]}',
                'замовлення': oid, '_ttn_чужа': dp['declaration_number']}
    items = order_items(o)
    if not items:
        return {'відмова': 'у замовленні немає артикулів'}

    import rozetka_order_agent as RZ
    noire = set(RZ.get_noire_articles())
    # Порожній перелік — це «не змогли прочитати», а НЕ «нічого немає».
    if len(noire) < 100:
        raise SystemExit(f'перелік артикулів NOIRE має лише {len(noire)} '
                         'позицій — фід не прочитано, зупиняюсь')
    if not set(items) <= noire:
        return {'пропуск': 'не всі артикули з NOIRE — потрібна людина',
                'замовлення': oid, 'чужі': sorted(set(items) - noire)}

    paid = is_paid(o)
    total = amount(o)
    w = T.warehouse_by_ref(dp.get('recipient_warehouse_id'))
    r = o.get('delivery_recipient') or o.get('client') or {}
    return {
        'замовлення': oid, 'стан': o.get('status'),
        'одержувач': f"{r.get('last_name') or ''} {r.get('first_name') or ''}".strip(),
        'телефон': r.get('phone') or o.get('phone'),
        'відділення': (o.get('delivery_address') or w.get('Description', ''))[:90],
        'сума': total,
        'післяплата': 'не потрібна (оплачено)' if paid else f'{total:.0f} грн',
        'товари': items,
        '_w': w, '_cod': 0 if paid else total, '_o': o, '_items': items,
    }


def run(oid, execute=False, place=True):
    st = load_state()
    p = plan(oid)
    if p.get('_ttn_чужа'):
        done = st.setdefault(str(oid), {})
        # Про замовлення постачальнику ми знаємо лише з власного стану.
        # Немає запису — отже від нас воно не йшло.
        if (execute and not done.get('crm_id')
                and not done.get('спитано_про_постачальника')):
            # Позначку ставимо ЛИШЕ якщо повідомлення дійшло: tg() глушить
            # помилки й повертає False, а незаслужена позначка приховала б
            # питання назавжди.
            if tg(f'❓ <b>Prom {oid}</b>: ТТН <code>{p["_ttn_чужа"]}</code> уже '
                  f'в замовленні, але від нас замовлення постачальнику НЕ йшло.\n'
                  f'Якщо ви оформили його самі — нічого робити не треба. '
                  f'Якщо ні — оформіть, бо автоматика цього замовлення вже '
                  f'не торкнеться.'):
                done['спитано_про_постачальника'] = True
                save_state(st)
        return p
    if 'пропуск' in p or 'відмова' in p:
        return p
    show = {k: v for k, v in p.items() if not k.startswith('_')}
    if not execute:
        return {'холостий': show}

    done = st.setdefault(str(oid), {})

    # 0. наявність у постачальника — ДО будь-якої незворотної дії
    import rozetka_order_agent as RZ
    ok, lines = RZ.noire_stock([{'sku': k, 'quantity': v}
                                for k, v in p['_items'].items()])
    if ok is not True:
        tg(f'⚠️ Prom {oid}: товару немає у постачальника\n' + '\n'.join(lines))
        return {'зупинка': 'наявність не підтверджена', 'деталі': lines}

    # 1. накладна — спільне ядро з рештою каналів
    if not done.get('ttn'):
        r = p['_o'].get('delivery_recipient') or p['_o'].get('client') or {}
        res = T.create({'first': r.get('first_name'), 'last': r.get('last_name'),
                        'middle': r.get('second_name'),
                        'phone': r.get('phone') or p['_o'].get('phone')},
                       p['_w'], p['сума'], cod=p['_cod'], tag=oid)
        done['ttn'] = res['ттн']
        done['наклейка'] = res.get('наклейка')
        save_state(st)
    ttn = done['ttn']

    # 2. постачальник
    if place and not done.get('crm_id'):
        from playwright.sync_api import sync_playwright
        import smtm_crm as CRM
        cart_lk = open(CART_LOCK, 'w')
        try:
            fcntl.flock(cart_lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            tg(f'⏸ Prom {oid}: кошик CRM зайнятий іншим конвеєром, '
               f'спробую наступним прогоном. ТТН {ttn} уже створена.')
            return {'замовлення': oid, 'ттн': ttn,
                    'відкладено': 'кошик CRM зайнятий'}
        with sync_playwright() as pw:
            crm = CRM.Crm(pw)
            try:
                crm.login()
                if not crm.cart_is_empty():
                    left = crm.cart_items()
                    if not crm.clear_cart():
                        tg(f'⚠️ Prom {oid}: кошик CRM не очистився ({left}). Зупиняюсь.')
                        raise RuntimeError('кошик не очистився')
                for sku, qty in p['_items'].items():
                    if not crm.add(sku, qty):
                        raise RuntimeError(f'{sku}: кількість у кошику не збіглась')
                same, why = crm.cart_matches(p['_items'])
                if not same:
                    tg(f'❌ Prom {oid}: {why}. Нічого не оформлено.')
                    raise RuntimeError(why)
                crm.checkout_open()
                done['crm_id'] = crm.place_order()
                save_state(st)          # фіксуємо ОДРАЗУ після незворотного
                if not crm.cart_is_empty():
                    crm.clear_cart()
                try:
                    crm.attach_ttn(ttn, done.get('наклейка'))
                except Exception as exc:
                    tg(f'⚠️ Prom {oid}: ТТН {ttn} не прикріпилась ({exc}). '
                       f'Прикріпіть вручну: ID {done["crm_id"]}')
                info = crm.order_info(done['crm_id']) or {}
                done['сума_постачальнику'] = info.get('сума')
                done['ттн_прикріплено'] = info.get('джерело_ттн') == 'TTN_FILE'
                save_state(st)
            except Exception as exc:
                if done.get('crm_id'):
                    tg(f'❌ <b>ЗБІЙ ПІСЛЯ ОФОРМЛЕННЯ</b>\nProm {oid} → '
                       f'постачальник ID <b>{done["crm_id"]}</b>\n{exc}')
                raise
            finally:
                crm.close()
                fcntl.flock(cart_lk, fcntl.LOCK_UN)
                cart_lk.close()

    # 3. записати ТТН у замовлення Prom
    if not done.get('ttn_written'):
        r = _prom('POST', 'delivery/save_declaration_id',
                  {'delivery_type': NP, 'order_id': int(oid),
                   'declaration_id': str(ttn)})
        # Prom віддає 200 і на помилку — дивимось на поле `status`.
        if r.get('status') == 'error':
            tg(f'⚠️ Prom {oid}: ТТН {ttn} НЕ записана — {r.get("message")}\n'
               f'Внесіть вручну в кабінеті.')
            done['ttn_written'] = False
        else:
            done['ttn_written'] = True
        save_state(st)

    written = ('записана автоматично' if done.get('ttn_written')
               else '❗ ВНЕСІТЬ ВРУЧНУ — автоматичний запис не вдався')
    tg(f'📦 <b>Замовлення Prom {oid}</b>\n'
       f'ID у постачальника: <b>{done.get("crm_id") or "—"}</b>\n'
       f'До сплати постачальнику: <b>{done.get("сума_постачальнику") or "—"}</b>\n'
       f'ТТН: <code>{ttn}</code> ({p["післяплата"]})\n'
       f'{p["відділення"]}\nПозиції: {p["_items"]}\n\n'
       f'ТТН у замовленні: {written}', done.get('наклейка'))
    return {'замовлення': oid, 'ттн': ttn,
            'постачальник_id': done.get('crm_id'),
            'до_сплати_постачальнику': done.get('сума_постачальнику'),
            'ттн_прикріплено': done.get('ттн_прикріплено'),
            'ттн_записана_в_prom': done.get('ttn_written')}


def open_orders():
    out = []
    for o in (_prom('GET', 'orders/list', params={'limit': 100}).get('orders') or []):
        if o.get('status') in FINAL:
            continue
        dp = o.get('delivery_provider_data') or {}
        out.append({'номер': o['id'], 'стан': o.get('status'),
                    'сума': o.get('price'), 'доставка': dp.get('provider'),
                    'ттн': dp.get('declaration_number'),
                    'оплачено': is_paid(o)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--order')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--auto', action='store_true')
    ap.add_argument('--execute', action='store_true',
                    help='для --order: виконати, а не показати')
    # 09.10: код нижче читав `a.dry`, якого в парсері не було — тому `--auto`
    # падав на AttributeError ДО першої дії, і pipeline не виконався ні разу
    # за дві доби в системі. Саме через це замовлення 432486760 власник
    # заповнював руками в дорозі.
    ap.add_argument('--dry', action='store_true',
                    help='для --auto: показати, нічого не робити')
    ap.add_argument('--no-place', action='store_true')
    a = ap.parse_args()

    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, 'w') as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            sys.exit('уже працює інший примірник')
        if a.list or (not a.order and not a.auto):
            print(json.dumps(open_orders(), ensure_ascii=False, indent=1))
            return
        if a.auto:
            do = not a.dry
            res = []
            for row in open_orders():
                try:
                    res.append(run(row['номер'], do, not a.no_place))
                except Exception as exc:
                    msg = f'{type(exc).__name__}: {exc}'
                    tg(f'❌ Prom {row["номер"]}: ланцюг зупинився\n{msg[:300]}')
                    res.append({'замовлення': row['номер'], 'збій': msg})
            print(json.dumps(res or [{'тихо': 'відкритих замовлень NOIRE немає'}],
                             ensure_ascii=False, indent=1, default=str))
            return
        print(json.dumps(run(a.order, a.execute and not a.dry, not a.no_place),
                         ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()
