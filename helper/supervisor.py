"""Режим керування «СУПЕРБОТ»: команди власника в Telegram → методи API.

Це перший справжній шар «павутини команд» (TASK-37) у роботі. Мета власника:
голосове завдання розпізнається і компілюється в послідовність методів. Тут
поки текст, але контракт той самий — команда, параметри, ризик, підтвердження.

ЧОМУ ОКРЕМИЙ РЕЖИМ. Звичайний бот відповідає на питання і нічого не змінює.
Команди змінюють: статус замовлення, текст покупцю, ТТН за гроші. Тому режим
вмикається кнопкою і виходить із нього теж явно — щоб випадкова фраза в чаті
не виконалась як наказ.

ПЕРЕВІРЕНІ ФАКТИ (живі виклики 04.10.2026 з СЕРВЕРА, негативний контроль —
вигаданий шлях, що дає HTML 404; усе нижче відповіло ІНАКШЕ, отже існує):

  GET  /orders/list, /orders/{id}, /messages/list, /products/list — працюють
  POST /orders/set_status — приймає ЛИШЕ received, delivered, paid.
       Віддає 200 І НА ПОМИЛКУ. Успіх = наш id у `processed_ids`.
  POST /messages/reply {thread_id, text} — існує (на вигаданому id дає
       {"error": "Incorrect message id"}, а не 404).
       Успіх = у відповіді НЕМАЄ ключа `error`.

  ВИПРАВЛЕНО 10.10.2026 — тут стояли два хибні твердження. Обидва я зробив,
  перебравши назви шляхів замість прочитати офіційну специфікацію (вона тепер
  лежить у `shared/knowledge_base/prom/openapi/`).

  ТТН у замовлення Prom ЗАПИСУЄТЬСЯ: `POST /delivery/save_declaration_id`
  {delivery_type, order_id, declaration_id}. Див. `tools/prom_order_pipeline.py`.

  Покупцю МОЖНА написати першим: родина `chat/*`, метод
  `POST /chat/send_message` приймає `room_ident` ({user_id}_{company_id}_buyer,
  вищий пріоритет) або `user_id`, плюс `body` до 2000 знаків і `project`.
  Команда `chat.send`. `messages.reply` лишається для відповіді в гілку,
  яку створив покупець.

  `delivery_provider_data.recipient_warehouse_id` у замовленні Prom — це
  справжній Ref відділення Нової Пошти. Перевірено: Address.getWarehouses за
  цим Ref віддав «Відділення №11, вул. Максима Чиженка, 33-б», що збіглося з
  текстовою адресою в самому замовленні.

РИЗИКИ. R0 — лише читання, виконується одразу. R2 — змінює дані майданчика.
R3 — витрачає гроші або створює зобовʼязання. R2 і R3 проходять через
`helper/confirm.py`: пропозиція, показ параметрів, підтвердження, TTL.
"""
import os
import re
import sys
from datetime import datetime, timezone

import requests
import urllib3

# Rozetka віддає сертифікат, якому requests не вірить; агент замовлень ходить
# туди з verify=False, і ми робимо так само, але без шуму в журналі.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROM_BASE = 'https://my.prom.ua/api/v1'
PROM_STATUSES = ('received', 'delivered', 'paid')
# Людські назви: власник каже «отримано», а не «received».
STATUS_WORDS = {'отрим': 'received', 'прийн': 'received',
                'достав': 'delivered', 'видан': 'delivered', 'виконан': 'delivered',
                'оплач': 'paid', 'сплач': 'paid'}
TIMEOUT = 40


def _token():
    t = os.getenv('PROM_API_TOKEN')
    if not t:
        raise RuntimeError('немає PROM_API_TOKEN у .env')
    return t


def _prom(method, path, body=None, params=None):
    """Запит до Prom. Помилку транспорту відрізняємо від помилки майданчика.

    `raise_for_status` тут НЕ викликаємо: Prom віддає 200 і на змістову
    помилку, тож код статусу нічого не вирішує, а 404 ми хочемо побачити
    текстом, а не як виняток requests.
    """
    r = requests.request(method, f'{PROM_BASE}/{path}',
                         headers={'Authorization': f'Bearer {_token()}'},
                         json=body, params=params, timeout=TIMEOUT)
    if r.status_code == 401:
        raise RuntimeError('Prom не прийняв токен (401). Перевірте PROM_API_TOKEN')
    if r.status_code == 404:
        raise RuntimeError(f'Prom: методу {path} не існує (404)')
    try:
        return r.json()
    except ValueError:
        raise RuntimeError(f'Prom віддав не JSON: {r.text[:150]}')


# ─────────────────────────── виконавці ───────────────────────────

def orders_list(limit=5, **kw):
    d = _prom('GET', 'orders/list', params={'limit': int(limit)})
    return {'замовлення': d.get('orders') or []}


def orders_get(order_id=None, **kw):
    d = _prom('GET', f'orders/{int(order_id)}')
    return {'замовлення': d.get('order') or {}}


def orders_set_status(order_id=None, status=None, dry_run=False, **kw):
    if status not in PROM_STATUSES:
        return {'відмова': f'Prom не приймає статус «{status}». '
                           f'Дозволені: {", ".join(PROM_STATUSES)}'}
    if dry_run:
        return {'холостий': f'замовлення {order_id} → «{status}»'}
    order_id = int(order_id)
    d = _prom('POST', 'orders/set_status', {'ids': [order_id], 'status': status})
    # Успіх ЛИШЕ за processed_ids. Код 200 тут нічого не означає — на цьому
    # вже горіло підтвердження замовлень: перевіряли status_code і думали,
    # що працює, а Prom мовчки відмовляв.
    ok = order_id in (d.get('processed_ids') or [])
    if not ok:
        # ПІДНІМАЄМО виняток, а не повертаємо {'успіх': False}. `run_action`
        # у confirm.py вважає успіхом будь-яке завершення без винятку, і
        # 04.10 через це виконання показало ✅ на невдалому надсиланні —
        # та сама пастка «200 на помилку», що на рівень вище.
        raise RuntimeError(f'Prom не змінив статус замовлення {order_id}: '
                           f'{d.get("warning_message") or d}')
    return {'успіх': True, 'замовлення': order_id, 'статус': status,
            'відповідь': d}


def messages_list(limit=20, **kw):
    d = _prom('GET', 'messages/list', params={'limit': int(limit)})
    return {'питання': d.get('messages') or []}


def messages_reply(thread_id=None, text=None, dry_run=False, **kw):
    if not (text or '').strip():
        return {'відмова': 'порожній текст відповіді'}
    if dry_run:
        return {'холостий': f'у гілку {thread_id}: «{text[:200]}»'}
    d = _prom('POST', 'messages/reply',
              {'thread_id': int(thread_id), 'text': text})
    # Успіх = немає ключа `error`. Prom і тут віддає 200 на помилку.
    if 'error' in d:
        raise RuntimeError(f'Prom не надіслав відповідь у гілку {thread_id}: '
                           f'{d["error"]}')
    return {'успіх': True, 'гілка': thread_id, 'відповідь': d}


def epicentr_orders(dry_run=False, **kw):
    """Замовлення Єпіцентру на Новій Пошті — що відкрите, що вже відправлене."""
    import subprocess, json as _j, os as _o
    r = subprocess.run([__import__('sys').executable,
                        _o.path.join(BASE, 'tools', 'epicentr_order_pipeline.py'),
                        '--list'], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f'перелік Єпіцентру: {(r.stderr or "")[-200:]}')
    return {'замовлення_епіцентр': _j.loads(r.stdout)}


def epicentr_ship(order=None, dry_run=False, **kw):
    """Повний ланцюг Єпіцентру: підтвердити → накладна → номер → відправлено."""
    import subprocess, json as _j, os as _o, sys as _s
    cmd = [_s.executable, _o.path.join(BASE, 'tools', 'epicentr_order_pipeline.py'),
           '--order', str(order)]
    if not dry_run:
        cmd.append('--execute')
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or '').strip()[-300:])
    return _j.loads(r.stdout)


PRESENCE = {'available': 'є в наявності', 'not_available': 'немає',
            'order': 'під замовлення', 'service': 'послуга',
            'waiting': 'очікується'}


def products_stock(sku=None, presence=None, quantity=None, dry_run=False, **kw):
    """Наявність і кількість товару за артикулом.

    Перевірено 04.10 зворотною зміною на справжньому товарі: 5 → 7 → 5,
    підтверджено читанням після кожного кроку. Стара матриця казала, що
    залишки змінюються лише вивантаженням файла, — це було неправильно.

    Беремо `edit_by_external_id`, бо власник знає товар за артикулом
    (SO5912), а не за внутрішнім номером Prom.
    """
    sku = str(sku).strip().upper()
    cur = _prom('GET', 'products/list',
                params={'search_term': sku, 'limit': 5}).get('products') or []
    cur = next((p for p in cur
                if str(p.get('external_id', '')).upper() == sku), None)
    if cur is None:
        return {'відмова': f'товару з артикулом {sku} не знайдено'}
    patch = {'id': sku}
    if presence:
        patch['presence'] = presence
    if quantity is not None:
        patch['quantity_in_stock'] = int(quantity)
    if len(patch) == 1:
        return {'відмова': 'не вказано ні наявності, ні кількості'}
    was = {'наявність': PRESENCE.get(cur.get('presence'), cur.get('presence')),
           'кількість': cur.get('quantity_in_stock')}
    if dry_run:
        return {'холостий': {'товар': f"{sku} · {str(cur.get('name'))[:50]}",
                             'було': was,
                             'стане': {'наявність': PRESENCE.get(presence, presence or '—'),
                                       'кількість': quantity if quantity is not None else '—'}}}
    d = _prom('POST', 'products/edit_by_external_id', [patch])
    if sku not in [str(x) for x in (d.get('processed_ids') or [])]:
        raise RuntimeError(f'Prom не змінив товар {sku}: '
                           f'{d.get("errors") or d}')
    return {'успіх': True, 'товар': sku, 'було': was, 'зміни': patch}


def _short_description(products):
    """Опис вантажу для НП — коротка назва першого товару (вказівка власника
    15.09.2026). Службові хвости на кшталт «, цвет Черный» відкидаємо: НП
    інколи не приймає довгі описи з комами."""
    if not products:
        return None
    name = str(products[0].get('name') or '')
    return re.split(r'[,(]', name)[0].strip()[:60] or None


def ttn_manual(last=None, first=None, phone=None, city=None, warehouse=None,
               amount=None, cod=None, description=None, dry_run=False, **kw):
    """Накладна за даними, введеними руками в «СУПЕРБОТІ».

    Потрібна, коли замовлення прийшло не через API — телефоном, у Instagram,
    у Viber. Відділення шукаємо за назвою міста й номером, бо власник їх так
    і бачить («Київ, №5»), а не у вигляді Ref.
    """
    from helper import ttn as T
    w, city_present = T.find_warehouse(city, warehouse)
    cod_sum = 0 if cod in (None, '', 0, '0') else (amount if cod is True else cod)
    out = T.create({'first': first, 'last': last, 'phone': phone}, w,
                   amount, cod=cod_sum, description=description,
                   tag='ручна', dry_run=dry_run)
    if dry_run:
        out['холостий']['місто_знайдено'] = city_present
    return out


def ttn_create(order_id=None, dry_run=False, **kw):
    """ТТН з контролем оплати за замовленням Prom.

    Контроль оплати потрібен лише коли замовлення НЕ оплачене: у Prom це
    видно з `payment_data.status` (у оплачених — `paid_out`) і з назви
    способу оплати («Наложенный платеж»).

    Саме створення віддаємо перевіреному `tools/np_create_ttn.py`, а не
    пишемо другий шлях: там уже враховано і ліміт ваги точки, і поштомати,
    і запасний шлях, якщо НП не приймає контроль оплати.
    """
    o = _prom('GET', f'orders/{int(order_id)}').get('order') or {}
    if not o:
        return {'відмова': f'замовлення {order_id} не знайдено'}
    dp = o.get('delivery_provider_data') or {}
    if dp.get('provider') != 'nova_poshta':
        return {'відмова': f'доставка не Нова Пошта: {dp.get("provider")}'}
    paid = (o.get('payment_data') or {}).get('status') == 'paid_out'
    amount = re.sub(r'[^\d.]', '', (o.get('price') or '').replace(' ', ''))
    cod = 0 if paid else amount
    # Ref відділення у показі НЕ друкуємо: маскувальник приватних даних
    # приймає хвіст UUID за номер телефону й ріже рядок
    # («...-acce-[телефон приховано]cf»). Власнику потрібна адреса, а не Ref.
    plan = {'замовлення': order_id,
            'відділення': (o.get('delivery_address') or '—')[:90],
            'оплачено': paid,
            'контроль_оплати': cod or 'не потрібен (оплачено)',
            'оголошена_вартість': amount,
            'вже_є_ттн': dp.get('declaration_number')}
    if dry_run:
        return {'холостий': plan}
    if dp.get('declaration_number'):
        raise RuntimeError(f'у замовленні {order_id} вже є ТТН '
                           f'{dp["declaration_number"]} — повторна не створюється')
    from helper import ttn as T
    r = o.get('delivery_recipient') or o.get('client') or {}
    w = T.warehouse_by_ref(dp.get('recipient_warehouse_id'))
    return T.create({'first': r.get('first_name'), 'last': r.get('last_name'),
                     'middle': r.get('second_name'),
                     'phone': r.get('phone') or o.get('phone')},
                    w, amount, cod=cod,
                    description=_short_description(o.get('products')),
                    tag=order_id)



# ─── Prom: чат із покупцем ───────────────────────────────────────
# Родину chat/* знайдено 09.10.2026 в офіційній специфікації
# (shared/knowledge_base/prom/openapi/). До того я двічі записував у
# пам'ять, що «покупцю першим написати неможливо» — бо перебирав назви
# шляхів замість прочитати доку. Відповідь тут інша за старі методи:
# {"status": "ok", "data": {...}}.

def chat_rooms(limit=10, **kw):
    d = _prom('GET', 'chat/rooms', params={'limit': int(limit)})
    return {'кімнати': ((d.get('data') or {}).get('rooms') or [])}


def chat_history(limit=20, status=None, **kw):
    pr = {'limit': int(limit)}
    if status in ('new', 'read'):
        pr['status'] = status
    d = _prom('GET', 'chat/messages_history', params=pr)
    return {'повідомлення': ((d.get('data') or {}).get('messages') or [])}


def chat_send(room_ident=None, user_id=None, text=None, dry_run=False, **kw):
    """Написати покупцю ПЕРШИМ. Приймає room_ident або user_id."""
    if not text:
        return {'відмова': 'немає тексту повідомлення'}
    if len(text) > 2000:
        return {'відмова': f'Prom приймає до 2000 знаків, а тут {len(text)}'}
    if not (room_ident or user_id):
        return {'відмова': 'потрібен room_ident або user_id покупця'}
    body = {'body': text, 'project': 'promua'}
    # room_ident має вищий пріоритет — так написано в специфікації.
    if room_ident:
        body['room_ident'] = str(room_ident)
    else:
        body['user_id'] = str(user_id)
    if dry_run:
        return {'холостий': f'покупцю {room_ident or user_id}: «{text[:80]}»'}
    d = _prom('POST', 'chat/send_message', body=body)
    if (d.get('status') or '').lower() != 'ok':
        raise RuntimeError(f'Prom не надіслав: {str(d)[:160]}')
    return {'надіслано': d.get('data') or d}


# ─── Єпіцентр: довідник атрибутів ────────────────────────────────
# Лежить на core-api, доступний нашою сесією. Токен merchant-api для
# цього НЕ потрібен, як я помилково вважав 09.10.

def epicentr_attributes(code=None, limit=20, **kw):
    from core.actions import _epicentr_session
    s, api = _epicentr_session()
    if code:
        r = s.get(f'{api}/v2/pim/attributes/by-code/{code}/options',
                  params={'limit': int(limit)}, timeout=60)
        if r.status_code == 404:
            return {'відмова': f'атрибута з кодом «{code}» немає'}
        r.raise_for_status()
        return {'значення': (r.json() or {}).get('items') or r.json()}
    r = s.get(f'{api}/v2/pim/attribute-sets', params={'limit': int(limit)},
              timeout=60)
    r.raise_for_status()
    d = r.json() or {}
    return {'усього_наборів': d.get('total'), 'набори': d.get('items') or []}


def epicentr_cards(**kw):
    """Скільки карток за статусом — із останнього зрізу кабінету."""
    import json as _json
    path = os.path.join(BASE, 'data', 'epicentr_products.json')
    if not os.path.exists(path):
        return {'відмова': 'зрізу немає, запустіть tools/epicentr_products_dump.py'}
    with open(path, encoding='utf-8') as f:
        cards = _json.load(f)
    by = {}
    for c in cards:
        by[c.get('status')] = by.get(c.get('status'), 0) + 1
    return {'усього': len(cards),
            'за_статусом': dict(sorted(by.items(), key=lambda x: -x[1])),
            'зріз_від': datetime.fromtimestamp(os.path.getmtime(path)).strftime('%d.%m %H:%M')}


# ─── Rozetka: відгуки про магазин ────────────────────────────────

def _rz():
    sys.path.insert(0, os.path.join(BASE, 'agents', 'orders'))
    import rozetka_order_agent as RZ
    return RZ


def rozetka_reviews(limit=10, **kw):
    RZ = _rz()
    r = requests.get(f'{RZ.ROZETKA_BASE}/market-reviews/search',
                     headers=RZ.rz_headers(), verify=False, timeout=TIMEOUT,
                     params={'limit': int(limit)})
    d = r.json()
    if not d.get('success'):
        raise RuntimeError(f'Rozetka: {str(d.get("errors"))[:140]}')
    c = d.get('content') or {}
    return {'відгуки': c.get('reviews') or c}


def rozetka_review_reply(review_id=None, text=None, dry_run=False, **kw):
    if not (review_id and text):
        return {'відмова': 'потрібні номер відгуку і текст'}
    if dry_run:
        return {'холостий': f'відгук {review_id}: «{text[:80]}»'}
    RZ = _rz()
    r = requests.post(f'{RZ.ROZETKA_BASE}/market-review-replies/reply',
                      headers=RZ.rz_headers(), verify=False, timeout=TIMEOUT,
                      json={'review_id': int(review_id), 'text': text})
    d = r.json()
    if not d.get('success'):
        raise RuntimeError(f'Rozetka не прийняла відповідь: {str(d)[:160]}')
    return {'відповідь_додано': review_id}


def rozetka_orders(limit=10, **kw):
    RZ = _rz()
    r = requests.get(f'{RZ.ROZETKA_BASE}/orders/search',
                     headers=RZ.rz_headers(), verify=False, timeout=TIMEOUT,
                     params={'types': 'all', 'limit': int(limit)})
    d = r.json()
    if not d.get('success'):
        raise RuntimeError(f'Rozetka: {str(d.get("errors"))[:140]}')
    return {'замовлення': (d.get('content') or {}).get('orders') or []}


COMMANDS = {
    'orders.list': {'fn': orders_list, 'params': ['limit'], 'risk': 'R0',
                    'about': 'останні замовлення Prom'},
    'orders.get': {'fn': orders_get, 'params': ['order_id'], 'risk': 'R0',
                   'about': 'одне замовлення за номером'},
    'messages.list': {'fn': messages_list, 'params': ['limit'], 'risk': 'R0',
                      'about': 'питання покупців'},
    'orders.set_status': {'fn': orders_set_status,
                          'params': ['order_id', 'status'], 'risk': 'R2',
                          'about': 'змінити статус замовлення'},
    'messages.reply': {'fn': messages_reply, 'params': ['thread_id', 'text'],
                       'risk': 'R2', 'about': 'відповісти покупцю в гілку'},
    'ttn.create': {'fn': ttn_create, 'params': ['order_id'], 'risk': 'R3',
                   'about': 'накладна за замовленням, з контролем оплати'},
    'epicentr.orders': {'fn': epicentr_orders, 'params': [], 'risk': 'R0',
                        'about': 'замовлення Єпіцентру на Новій Пошті'},
    'epicentr.ship': {'fn': epicentr_ship, 'params': ['order'], 'risk': 'R3',
                      'about': 'Єпіцентр: підтвердити, накладна, відправлено'},
    'products.stock': {'fn': products_stock,
                       'params': ['sku', 'presence', 'quantity'], 'risk': 'R2',
                       'about': 'наявність і кількість товару за артикулом'},
    'ttn.manual': {'fn': ttn_manual,
                   'params': ['last', 'first', 'phone', 'city', 'warehouse',
                              'amount', 'cod'], 'risk': 'R3',
                   'about': 'накладна за даними, введеними руками'},
    # ── додано 10.10.2026 за підсумком аудиту API ──
    'chat.rooms': {'fn': chat_rooms, 'params': ['limit'], 'risk': 'R0',
                   'about': 'Prom: кімнати чату з покупцями'},
    'chat.history': {'fn': chat_history, 'params': ['limit', 'status'],
                     'risk': 'R0', 'about': 'Prom: історія листування'},
    'chat.send': {'fn': chat_send,
                  'params': ['room_ident', 'user_id', 'text'], 'risk': 'R3',
                  'about': 'Prom: написати покупцю ПЕРШИМ (до 2000 знаків)'},
    'epicentr.attributes': {'fn': epicentr_attributes,
                            'params': ['code', 'limit'], 'risk': 'R0',
                            'about': 'Єпіцентр: довідник атрибутів і значень'},
    'epicentr.cards': {'fn': epicentr_cards, 'params': [], 'risk': 'R0',
                       'about': 'Єпіцентр: картки за статусом'},
    'rozetka.orders': {'fn': rozetka_orders, 'params': ['limit'], 'risk': 'R0',
                       'about': 'Rozetka: останні замовлення'},
    'rozetka.reviews': {'fn': rozetka_reviews, 'params': ['limit'],
                        'risk': 'R0', 'about': 'Rozetka: відгуки про магазин'},
    'rozetka.review_reply': {'fn': rozetka_review_reply,
                             'params': ['review_id', 'text'], 'risk': 'R2',
                             'about': 'Rozetka: відповісти на відгук'},
}


# ─────────────────────────── розбір ───────────────────────────
# Основи, а НЕ словоформи: українська відмінюється, і «замовлення» не
# міститься в основі «замовлень». На цій же пастці колись зламався
# генератор ключів Prom (_is_adj пропускав відмінкові іменники).

def parse(text):
    """Текст власника → {'command', 'params'} або None, якщо не команда."""
    t = (text or '').strip()
    low = t.lower()
    nums = [int(n) for n in re.findall(r'\d+', t)]

    # ── нові родини, додані 10.10.2026 ────────────────────────────
    # Порядок має значення: гілка «епіцентр» нижче перехоплює БУДЬ-ЯКУ
    # фразу про Єпіцентр, а гілка «чат» — вела б на messages.list.
    # Тому вузьке перевіряємо першим, широке — потім.

    if any(w in low for w in ('атрибут', 'характеристик', 'довідник')):
        code = re.search(r'\b([a-z][a-z0-9_-]{2,})\b', low.split('атрибут')[-1])
        p = {}
        if code and code.group(1) not in ('епіцентр', 'епицентр'):
            p['code'] = code.group(1)
        return {'command': 'epicentr.attributes', 'params': p}

    if 'картк' in low and ('епіцентр' in low or 'епицентр' in low
                           or 'статус' in low or 'скільки' in low):
        return {'command': 'epicentr.cards', 'params': {}}

    if any(w in low for w in ('відгук', 'отзыв', 'рейтинг')):
        # «відповісти на відгук 123 текст» — запис; просто «відгуки» — читання.
        if any(w in low for w in ('відпов', 'відпиши', 'відкаж')) and nums:
            rid = nums[0]
            tail = t[t.find(str(rid)) + len(str(rid)):].strip(' :,—-')
            if not tail:
                return {'command': 'rozetka.review_reply', 'params': {'review_id': rid},
                        'брак': ['текст відповіді']}
            return {'command': 'rozetka.review_reply',
                    'params': {'review_id': rid, 'text': tail}}
        return {'command': 'rozetka.reviews', 'params': {'limit': 10}}

    if 'розетк' in low or 'rozetka' in low:
        return {'command': 'rozetka.orders', 'params': {'limit': 10}}

    if 'кімнат' in low or 'чати' in low or 'листуванн' in low:
        return {'command': 'chat.rooms' if 'кімнат' in low or 'чати' in low
                else 'chat.history', 'params': {'limit': 20}}

    if 'напиши покупц' in low or 'повідом покупц' in low:
        # Адресат: room_ident виду 44332113_4053918_buyer або голий id.
        # Текст беремо ЛИШЕ ПІСЛЯ адресата — та сама пастка, що з артикулом:
        # інакше слово-тригер зараховує саме себе.
        p, key = {}, None
        ident = re.search(r'\b(\d+_\d+_buyer)\b', t)
        uid = None if ident else re.search(r'покупц\w*\s+(\d{4,})', low)
        if ident:
            p['room_ident'], key = ident.group(1), ident.group(1)
        elif uid:
            p['user_id'], key = uid.group(1), uid.group(1)
        after = t[t.find(key) + len(key):] if key else ''
        body = after.strip(' :,—-')
        if body:
            p['text'] = body
        брак = []
        if not key:
            брак.append('кімната виду 44332113_4053918_buyer або id покупця')
        if not body:
            брак.append('текст повідомлення')
        return ({'command': 'chat.send', 'params': p, 'брак': брак} if брак
                else {'command': 'chat.send', 'params': p})

    if 'епіцентр' in low or 'епицентр' in low or 'epicentr' in low:
        if nums and nums[0] > 1000:
            return {'command': 'epicentr.ship', 'params': {'order': nums[0]}}
        return {'command': 'epicentr.orders', 'params': {}}

    if any(w in low for w in ('наявн', 'кількіст', 'залишк', 'склад')):
        art = re.search(r'\b([A-Za-zА-Яа-я]{2}\d{3,8})\b', t)
        if not art:
            return {'command': 'products.stock', 'params': {},
                    'брак': ['артикул, напр. «наявність SO5912 немає»']}
        p = {'sku': art.group(1)}
        # Значення шукаємо ЛИШЕ ПІСЛЯ артикула. Інакше слово-тригер
        # зараховує саме себе: «наявність SO5912» без значення мовчки
        # ставило «є» — тиха неправильна дія, гірша за відмову.
        tail = t[art.end():].lower()
        # «немає» перевіряємо ПЕРШИМ: слово «є» міститься і в «немає».
        if any(w in tail for w in ('нема', 'відсут', 'закінч')):
            p['presence'] = 'not_available'
        elif 'замовл' in tail:
            p['presence'] = 'order'
        elif re.search(r'\bє\b|наявн|появ', tail):
            p['presence'] = 'available'
        qty = [int(n) for n in re.findall(r'\b(\d{1,5})\b', t[art.end():])]
        if qty:
            p['quantity'] = qty[-1]
            p.setdefault('presence', 'available' if qty[-1] else 'not_available')
        if len(p) == 1:
            return {'command': 'products.stock', 'params': p,
                    'брак': ['що саме: «є», «немає» або кількість']}
        return {'command': 'products.stock', 'params': p}

    if any(w in low for w in ('ттн', 'накладн', 'наклейк')) and ';' in t:
        # Ручне введення: поля через «;». Формат показує сам бот, тому
        # вгадувати порядок не треба.
        #   накладна Іванов; Іван; +380671234567; Київ; 5; 1200; післяплата
        body = re.sub(r'^\s*\S+\s*', '', t, count=1)
        f = [x.strip() for x in body.split(';')]
        if len(f) < 6:
            return {'command': 'ttn.manual', 'params': {},
                    'брак': ['прізвище; імʼя; телефон; місто; відділення; сума'
                             '[; післяплата]']}
        cod = len(f) > 6 and any(w in f[6].lower()
                                 for w in ('післяплат', 'post', 'контрол', 'так'))
        return {'command': 'ttn.manual',
                'params': {'last': f[0], 'first': f[1], 'phone': f[2],
                           'city': f[3], 'warehouse': f[4], 'amount': f[5],
                           'cod': True if cod else 0}}

    if any(w in low for w in ('ттн', 'накладн', 'наклейк')):
        if not nums:
            return {'command': 'ttn.create', 'params': {}, 'брак': ['order_id']}
        return {'command': 'ttn.create', 'params': {'order_id': nums[0]}}

    # «відповід» НЕ міститься у «відповісти» (там «відповіс») — 10.10 через
    # це найприродніша фраза «відповісти 123 текст» не розпізнавалась
    # узагалі. Спільна основа — «відпов».
    if any(w in low for w in ('відпов', 'відпиши', 'напиши покупц', 'відкаж')):
        # Текст відповіді — усе після номера гілки.
        if not nums:
            return {'command': 'messages.reply', 'params': {},
                    'брак': ['thread_id', 'text']}
        tail = t[t.find(str(nums[0])) + len(str(nums[0])):].strip(' :—-')
        p = {'thread_id': nums[0]}
        if tail:
            p['text'] = tail
        return {'command': 'messages.reply', 'params': p,
                **({} if tail else {'брак': ['text']})}

    if any(w in low for w in ('статус', 'познач')):
        st = next((v for k, v in STATUS_WORDS.items() if k in low), None)
        if not nums:
            return {'command': 'orders.set_status', 'params': {},
                    'брак': ['order_id', 'status']}
        p = {'order_id': nums[0]}
        if st:
            p['status'] = st
        return {'command': 'orders.set_status', 'params': p,
                **({} if st else {'брак': ['status']})}

    if any(w in low for w in ('питанн', 'запитанн', 'повідомленн', 'чат')):
        return {'command': 'messages.list', 'params': {'limit': 20}}

    # Статус названо прямо — «замовлення 123 отримано». Доти працювало лише
    # зі словом «статус» чи «познач», а це не те, як говорять.
    if nums and nums[0] > 1000 and any(k in low for k in STATUS_WORDS):
        st = next(v for k, v in STATUS_WORDS.items() if k in low)
        return {'command': 'orders.set_status',
                'params': {'order_id': nums[0], 'status': st}}

    if any(w in low for w in ('замовл', 'заказ', 'продаж')):
        if nums and nums[0] > 1000:      # номер замовлення, а не «покажи 5»
            return {'command': 'orders.get', 'params': {'order_id': nums[0]}}
        return {'command': 'orders.list',
                'params': {'limit': nums[0] if nums else 5}}
    return None


# ─────────────────────────── показ ───────────────────────────

def _order_line(o):
    pay = (o.get('payment_data') or {}).get('status') or '—'
    dp = o.get('delivery_provider_data') or {}
    ttn = dp.get('declaration_number') or 'без ТТН'
    return (f"#{o.get('id')} {o.get('status_name') or o.get('status')} · "
            f"{o.get('price')} · оплата {pay} · {ttn}")


def render(command, result, limit=3500):
    if not isinstance(result, dict):
        return str(result)[:limit]
    for key in ('відмова', 'холостий', 'збій'):
        if key in result:
            v = result[key]
            return f'{key}: {v}'[:limit] if not isinstance(v, dict) else \
                   (f'{key}:\n' + '\n'.join(f'  {a}: {b}' for a, b in v.items()))[:limit]
    if command == 'orders.list':
        rows = result['замовлення']
        if not rows:
            return 'Замовлень немає.'
        return (f'Замовлень: {len(rows)}\n\n'
                + '\n'.join(_order_line(o) for o in rows))[:limit]
    if command == 'orders.get':
        o = result['замовлення']
        items = '\n'.join(f"  · {p.get('name','')[:60]} ×{p.get('quantity')}"
                          for p in (o.get('products') or []))
        dp = o.get('delivery_provider_data') or {}
        return (f"{_order_line(o)}\n"
                f"Доставка: {o.get('delivery_address') or '—'}\n"
                f"Тип доставки: {dp.get('type') or '—'}\n"
                f"Товари:\n{items}")[:limit]
    if command == 'messages.list':
        rows = result['питання']
        if not rows:
            return 'Нових питань немає.'
        return (f'Питань: {len(rows)}\n\n' + '\n'.join(
            f"#{m.get('id')} {str(m.get('text',''))[:120]}" for m in rows))[:limit]
    if command == 'orders.set_status':
        return ('✅ ' if result.get('успіх') else '❌ ') + \
               f"замовлення {result.get('замовлення')} → {result.get('статус')}" + \
               ('' if result.get('успіх') else f"\n{result.get('відповідь')}")
    if command == 'epicentr.orders':
        rows = result['замовлення_епіцентр']
        if not rows:
            return 'Замовлень Єпіцентру на Новій Пошті немає.'
        op = [r for r in rows if r['відкрите']]
        out = [f'Єпіцентр, Нова Пошта: {len(rows)} замовлень, '
               f'відкритих {len(op)}', '']
        for r in rows:
            mark = '🔔 ' if r['відкрите'] else '   '
            pay = {'hold_set': 'гроші на картці', 'hold_unset': 'оплачено',
                   'payment_canceled': 'оплату скасовано',
                   'hold_canceled': 'блок знято'}.get(r['оплата'], r['оплата'])
            out.append(f"{mark}#{r['номер']} {r['стан']} · {r['сума']} грн · "
                       f"{pay} · {r['ттн'] or 'без ТТН'}")
        return '\n'.join(out)[:limit]
    if command == 'epicentr.ship':
        if 'ттн' in result:
            return (f"✅ Єпіцентр {result['замовлення']}: ТТН {result['ттн']}\n"
                    f"{result.get('відділення','')}\n{result.get('післяплата','')}\n"
                    f"статус: {result.get('статус_після')}")
        return str(result)[:limit]
    if command == 'products.stock':
        return (f"✅ {result['товар']}: було {result['було']['наявність']}, "
                f"{result['було']['кількість']} шт → {result['зміни']}")
    if command == 'messages.reply':
        return ('✅ відповідь надіслано в гілку '
                if result.get('успіх') else '❌ не надіслано, гілка ') + \
               f"{result.get('гілка')}" + \
               ('' if result.get('успіх') else f"\n{result.get('відповідь')}")
    return str(result)[:limit]


# ─────────────────────────── режим ───────────────────────────

class Supervisor:
    """Стан режиму керування й виконання команд.

    `active=False` — модуль мовчить і повертає None, бот працює як завжди.
    Це важливо: увімкнення має бути свідомим, бо команди змінюють дані.
    """

    def __init__(self, store=None, modes=None):
        self.active = False
        self.store = store
        self.modes = modes or {}

    def on(self):
        self.active = True
        return ('🤖 <b>Режим керування увімкнено.</b>\n\n'
                'Команди:\n'
                '· <code>замовлення</code> — останні\n'
                '· <code>замовлення 426501433</code> — одне\n'
                '· <code>питання</code> — чати покупців\n'
                '· <code>відповідь 55 текст…</code> — написати покупцю\n'
                '· <code>статус 426501433 отримано</code>\n'
                '· <code>наявність SO5912 немає</code>\n'
                '· <code>кількість SO5912 7</code>\n'
                '· <code>епіцентр</code> — замовлення Єпіцентру\n'
                '· <code>епіцентр 58192585</code> — відправити\n'
                '· <code>ттн 426501433</code> — за замовленням\n'
                '· <code>накладна Іванов; Іван; +380671234567;\n'
                '  Київ; 5; 1200; післяплата</code> — руками\n\n'
                'Зміни й гроші — лише після підтвердження.\n'
                'Вийти: «вихід».')

    def off(self):
        self.active = False
        return '🔕 Режим керування вимкнено.'

    def handle(self, text, user_id=None, now=None):
        """None — не для нас. Інакше текст відповіді власнику."""
        if not self.active:
            return None
        low = (text or '').strip().lower()
        if low in ('вихід', 'виход', 'стоп', 'off'):
            return self.off()
        p = parse(text)
        if p is None:
            return ('Не розпізнав команду. Напишіть «замовлення», «питання», '
                    '«статус <номер> отримано», «відповідь <гілка> текст», '
                    '«наявність <артикул> немає», «кількість <артикул> 7», '
                    '«ттн <номер>» або «накладна …». Вийти — «вихід».')
        if p.get('брак'):
            return f"Бракує: {', '.join(p['брак'])}"
        spec = COMMANDS[p['command']]
        if spec['risk'] == 'R0':
            try:
                return render(p['command'], spec['fn'](**p['params']))
            except Exception as exc:
                return f'збій: {type(exc).__name__}: {exc}'
        if self.store is None:
            # Без сховища підтверджень показуємо лише холостий прогін —
            # ніколи не виконуємо зміну без підтвердження.
            return render(p['command'], spec['fn'](dry_run=True, **p['params']))
        from helper.confirm import confirm_text
        now = now or datetime.now(timezone.utc)
        try:
            dry = spec['fn'](dry_run=True, **p['params'])
        except Exception as exc:
            return f'відмова: {exc}'
        # Якщо холостий прогін уже каже «ні» — не питаємо підтвердження на
        # те, що однаково не виконається.
        if isinstance(dry, dict) and 'відмова' in dry:
            return f"відмова: {dry['відмова']}"
        preview = render(p['command'], dry)
        act = self.store.create(intent=p['command'], params=p['params'],
                                risk=spec['risk'], preview=preview,
                                requested_by=user_id, now=now)
        return confirm_text(act)

    def execute(self, action_id, user_id=None, now=None):
        """Виконати вже підтверджену дію."""
        from helper.confirm import run_action
        now = now or datetime.now(timezone.utc)
        act = self.store.get(action_id)
        if act is None:
            return 'Дію не знайдено.'
        spec = COMMANDS.get(act['intent'])
        if spec is None:
            return f'Невідома дія {act["intent"]}.'
        res = run_action(self.store, action_id, spec['fn'],
                         user_id=user_id, now=now, modes=self.modes)
        return ('✅ ' if res.get('ok') else '❌ ') + \
               f"{act['intent']}: {res.get('result') or res.get('message')}"
