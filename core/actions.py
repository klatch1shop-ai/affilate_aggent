#!/usr/bin/env python3
"""Скелет павутини команд: реєстр ДІЙ над каналами.

Мета (власник, 03.10.2026): інтелектуальний сервіс керування, де голосове
завдання користувача розпізнається і перетворюється в послідовність методів.
Цей модуль — та сама «послідовність методів»: словник дій, у який буде
компілюватись намір.

Чому дія, а не скрипт. Зараз кожна операція написана окремо під кожен канал
(понад 60 файлів `tools/*`). 02.10 це дало замовлення на товар, якого немає:
синхронізацію наявності написали для одного постачальника й не написали для
двох інших. Дія описує, ЩО робимо; канал — лише спосіб.

Кожна дія несе машиночитний контракт:
  channels   — де вона взагалі можлива (з перевіреної матриці COMMAND_WEB.md)
  params     — що приймає
  reversible — чи можна відкотити; незворотні вимагають підтвердження
  cost       — чи витрачає гроші або створює зобовʼязання

ГОЛОВНЕ ПРАВИЛО СКЕЛЕТА: за замовчуванням дія виконується ВХОЛОСТУ.
Справжнє виконання вмикається явно (`execute=True`). Голос двозначний, і
неправильно розпізнаний намір не має права скасувати замовлення чи змінити
ціну.

    venv/bin/python3 core/actions.py --list
    venv/bin/python3 core/actions.py --run orders.list --channel rozetka
    venv/bin/python3 core/actions.py --plan "показати замовлення і перевірити фіди"
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

REGISTRY = {}


def action(name, channels, params=(), reversible=True, cost=False, about=''):
    def wrap(fn):
        REGISTRY[name] = {'name': name, 'channels': list(channels),
                          'params': list(params), 'reversible': reversible,
                          'cost': cost, 'about': about or (fn.__doc__ or '').strip(),
                          'fn': fn}
        return fn
    return wrap


def _env():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, '.env'), override=True)
    return os.environ


def _need(e, *keys):
    """Доступи: кажемо, ЧОГО бракує, а не падаємо KeyError.

    .env ноутбука і сервера різні: 03.10 на сервері не було
    EPICENTR_EMAIL/PASSWORD (там EPICENTR_TOKEN), і зведення падало
    незрозумілим KeyError замість зрозумілого «немає доступу».
    """
    missing = [k for k in keys if not e.get(k)]
    if missing:
        raise RuntimeError(f'немає доступів у .env: {", ".join(missing)}')
    return [e[k] for k in keys]


def _epicentr_session():
    """Сесія Єпіцентру: логін з паролем або готовий токен — що є в .env."""
    import requests
    e = _env()
    api = 'https://core-api.epicentrm.com.ua'
    s = requests.Session()
    if e.get('EPICENTR_EMAIL') and e.get('EPICENTR_PASSWORD'):
        t = s.post(f'{api}/v2/users/login',
                   json={'login': e['EPICENTR_EMAIL'],
                         'password': e['EPICENTR_PASSWORD']}, timeout=40)
        s.headers['Authorization'] = f"Bearer {t.json()['token']['auth']}"
    elif e.get('EPICENTR_TOKEN'):
        s.headers['Authorization'] = f"Bearer {e['EPICENTR_TOKEN']}"
    else:
        raise RuntimeError('немає доступів у .env: EPICENTR_EMAIL+PASSWORD '
                           'або EPICENTR_TOKEN')
    return s, api


# ─────────────────────────── читання ───────────────────────────

@action('orders.list', ['prom', 'rozetka', 'epicentr'], ['limit'],
        about='Список замовлень каналу')
def orders_list(channel, limit=5, execute=False, **kw):
    import requests
    e = _env()
    if channel == 'prom':
        (tok,) = _need(e, 'PROM_API_TOKEN')
        r = requests.get('https://my.prom.ua/api/v1/orders/list',
                         headers={'Authorization': f'Bearer {tok}'},
                         params={'limit': limit}, timeout=40)
        if r.status_code == 401:
            raise RuntimeError('Prom: токен недійсний (401). '
                               'Перевірено 03.10: токен сервера протермінований, '
                               'на ноутбуці той самий виклик працює')
        items = r.json().get('orders', [])
        return [{'id': o.get('id'), 'status': o.get('status'),
                 'sum': o.get('full_price')} for o in items]
    if channel == 'rozetka':
        r = requests.get('https://api-seller.rozetka.com.ua/orders/search',
                         headers={'Authorization': f'Bearer {e["ROZETKA_API_TOKEN"]}'},
                         params={'expand': 'delivery', 'page': 1}, timeout=40)
        items = (r.json().get('content') or {}).get('orders') or []
        return [{'id': o.get('id'), 'status': o.get('status'),
                 'sum': o.get('amount')} for o in items[:limit]]
    if channel == 'epicentr':
        s, api = _epicentr_session()
        r = s.get(f'{api}/v3/oms/orders', params={'limit': limit}, timeout=40)
        return [{'id': o.get('id'), 'status': o.get('statusCode')}
                for o in r.json().get('items', [])]
    raise ValueError(f'канал {channel} не підтримує orders.list')


@action('feeds.freshness', ['all'], about='Чи не застояли опубліковані фіди')
def feeds_freshness(channel='all', execute=False, **kw):
    from tools.feed_freshness_watch import check
    rows, stale = check()
    return {'застояли': stale,
            'перевірено': [{'фід': n, 'вік_год': round(h, 1) if h else None}
                           for n, h, _r, _s in rows]}


@action('delivery.warehouse', ['novaposhta'], ['ref'],
        about='Відділення Нової Пошти за Ref із замовлення Rozetka')
def delivery_warehouse(channel='novaposhta', ref=None, execute=False, **kw):
    import requests
    e = _env()
    r = requests.post('https://api.novaposhta.ua/v2.0/json/',
                      json={'apiKey': e['NP_API_KEY'], 'modelName': 'Address',
                            'calledMethod': 'getWarehouses',
                            'methodProperties': {'Ref': ref}}, timeout=40)
    d = (r.json().get('data') or [{}])[0]
    return {'відділення': d.get('Description'), 'місто': d.get('CityDescription'),
            'ліміт_ваги': d.get('TotalMaxWeightAllowed')}


@action('delivery.track', ['novaposhta'], ['ttn'], about='Статус посилки за ТТН')
def delivery_track(channel='novaposhta', ttn=None, execute=False, **kw):
    import requests
    e = _env()
    r = requests.post('https://api.novaposhta.ua/v2.0/json/',
                      json={'apiKey': e['NP_API_KEY'],
                            'modelName': 'TrackingDocument',
                            'calledMethod': 'getStatusDocuments',
                            'methodProperties': {
                                'Documents': [{'DocumentNumber': ttn}]}}, timeout=40)
    d = (r.json().get('data') or [{}])[0]
    return {'ттн': ttn, 'статус': d.get('Status'),
            'контроль_оплати': d.get('AfterpaymentOnGoodsCost')}


# ───────────────────── Prom: аналіз карток ─────────────────────
# Prom — головний канал демонстрації: саме він під експериментами.

@action('products.count', ['prom', 'rozetka', 'epicentr'],
        about='Скільки карток у кабінеті та в якому стані')
def products_count(channel='prom', execute=False, **kw):
    import requests, collections
    e = _env()
    if channel == 'prom':
        (tok,) = _need(e, 'PROM_API_TOKEN')
        H = {'Authorization': f'Bearer {tok}'}
        out, last = [], None
        while True:
            prm = {'limit': 100}
            if last:
                prm['last_id'] = last
            r = requests.get('https://my.prom.ua/api/v1/products/list',
                             headers=H, params=prm, timeout=60)
            if r.status_code == 401:
                raise RuntimeError('Prom: токен недійсний (401)')
            items = r.json().get('products', [])
            if not items:
                break
            out += items
            last = items[-1]['id']
        return {'канал': 'prom', 'карток': len(out),
                'статус': dict(collections.Counter(x.get('status') for x in out)),
                'наявність': dict(collections.Counter(x.get('presence') for x in out)),
                'категорій': len({(x.get('category') or {}).get('id') for x in out})}
    if channel == 'rozetka':
        (tok,) = _need(e, 'ROZETKA_API_TOKEN')
        H = {'Authorization': f'Bearer {tok}'}
        r = requests.get('https://api-seller.rozetka.com.ua/goods/all',
                         headers=H, params={'page': 1}, timeout=60)
        c = r.json().get('content') or {}
        items = c.get('goods') or c.get('items') or []
        return {'канал': 'rozetka', 'на_сторінці': len(items),
                'усього': c.get('total_count') or c.get('total')}
    if channel == 'epicentr':
        # повний перелік уже вивантажений у data/epicentr_products.json;
        # курсорна пагінація PIM повільна, тому для зведення беремо total
        s_, api = _epicentr_session()
        r = s_.get(f'{api}/v2/pim/products', params={'limit': 1}, timeout=60)
        return {'канал': 'epicentr', 'усього': r.json().get('total')}
    raise ValueError(f'канал {channel} не підтримує products.count')


@action('status.all', ['all'],
        about='Зведення по ВСІХ каналах одразу: картки, замовлення, фіди')
def status_all(channel='all', execute=False, **kw):
    """Одна дія — уся павутина. Саме це неможливо було зробити, доки кожна
    операція жила окремим скриптом під кожен канал."""
    out = {}
    for ch in ('prom', 'rozetka', 'epicentr'):
        try:
            out[ch] = {'товари': products_count(channel=ch),
                       'замовлення': len(orders_list(channel=ch, limit=50))}
        except Exception as exc:
            out[ch] = {'збій': f'{type(exc).__name__}: {exc}'}
    try:
        out['фіди'] = feeds_freshness()
    except Exception as exc:
        out['фіди'] = {'збій': str(exc)}
    return out


@action('keywords.audit', ['prom'], about='Якість ключових слів: що саме зламано')
def keywords_audit(channel='prom', execute=False, **kw):
    """Рахує по опублікованому фіду, а не по API: API не віддає keywords_ua."""
    import xml.etree.ElementTree as ET
    import collections
    import requests
    raw = requests.get('https://raw.githubusercontent.com/klatch1shop-ai/'
                       'noire-feed/main/noire_prom.xml', timeout=300).content
    offers = list(ET.fromstring(raw).iter('offer'))

    def kw(o, tag):
        return [k.strip() for k in (o.findtext(tag) or '').split(',') if k.strip()]

    res = {'офферів': len(offers)}
    for tag, label in (('keywords', 'рос'), ('keywords_ua', 'укр')):
        cnt = collections.Counter(k.lower() for o in offers for k in kw(o, tag))
        total = sum(cnt.values())
        no_uniq = sum(1 for o in offers
                      if kw(o, tag) and not any(cnt[k.lower()] == 1 for k in kw(o, tag)))
        res[label] = {
            'слотів_заповнено': total,
            'слотів_порожніх': len(offers) * 9 - total,
            'карток_без_унікального_ключа': no_uniq,
            'частка_спільних_слотів': round(
                sum(n for n in cnt.values() if n > 1) / total * 100, 1) if total else 0,
        }
    top = collections.Counter(k.lower() for o in offers for k in kw(o, 'keywords'))
    res['найчастіший_спільний_ключ'] = top.most_common(1)[0] if top else None
    return res


@action('experiment.status', ['prom'], about='Стан пілота з ключовими словами')
def experiment_status(channel='prom', execute=False, **kw):
    import json as _j
    path = os.path.join(BASE, 'data', 'prom', 'kw_pilot.json')
    if not os.path.exists(path):
        return {'пілот': 'не запущено'}
    d = _j.load(open(path, encoding='utf-8'))
    return {'запущено': d.get('started'),
            'дослідна_група': len(d.get('test') or []),
            'контрольна_група': len(d.get('control') or []),
            'додано_ключів': d.get('added'),
            'видалено_помилкових': d.get('removed'),
            'замір': 'через 14 днів проти контрольної групи'}


# ─────────────────────────── запис ───────────────────────────

@action('orders.set_status', ['prom', 'rozetka', 'epicentr'],
        ['order_id', 'status'], reversible=False,
        about='Змінити статус замовлення. Prom приймає лише received/delivered/paid')
def orders_set_status(channel, order_id=None, status=None, execute=False, **kw):
    import requests
    e = _env()
    if channel == 'prom' and status not in ('received', 'delivered', 'paid'):
        return {'відмова': f'Prom не приймає статус «{status}»; '
                           'дозволені received, delivered, paid'}
    if not execute:
        return {'холостий_прогін': f'{channel}: замовлення {order_id} → «{status}»'}
    if channel == 'prom':
        r = requests.post('https://my.prom.ua/api/v1/orders/set_status',
                          headers={'Authorization': f'Bearer {e["PROM_API_TOKEN"]}'},
                          json={'ids': [order_id], 'status': status}, timeout=40)
        d = r.json()
        # Prom віддає 200 і на помилку: успіх — наш id у processed_ids
        return {'успіх': order_id in (d.get('processed_ids') or []), 'відповідь': d}
    raise NotImplementedError(f'запис для каналу {channel} ще не підключено')


@action('delivery.create_ttn', ['novaposhta'], ['order_id'],
        reversible=False, cost=True,
        about='Створити ТТН з контролем оплати (AfterpaymentOnGoodsCost)')
def delivery_create_ttn(channel='novaposhta', order_id=None, execute=False, **kw):
    if not execute:
        return {'холостий_прогін': f'ТТН для замовлення {order_id} '
                                   '(гроші й зобовʼязання — потрібне підтвердження)'}
    raise NotImplementedError('виконання через tools/np_create_ttn.py --create')


# ─────────────────────────── план ───────────────────────────

def plan_from_text(text):
    """Заготовка компілятора наміру: поки за ключовими словами, далі — модель.

    Саме сюди прийде розпізнаний голос. Повертає послідовність кроків, яку
    ПОКАЗУЮТЬ користувачу до виконання.
    """
    t = text.lower()
    steps = []
    if any(w in t for w in ('замовл', 'order', 'продаж')):
        for ch in ('rozetka', 'prom', 'epicentr'):
            if ch in t or 'усі' in t or 'все' in t:
                steps.append({'action': 'orders.list', 'channel': ch, 'limit': 5})
        if not steps:
            steps.append({'action': 'orders.list', 'channel': 'rozetka', 'limit': 5})
    if any(w in t for w in ('ключ', 'keyword', 'слов', 'seo')):
        steps.append({'action': 'keywords.audit', 'channel': 'prom'})
    # Основи коротші за словоформи: «карток» НЕ містить «картк» (відмінювання).
    # Та сама пастка колись зламала генератор ключів Prom.
    if any(w in t for w in ('карт', 'товар', 'асортимент', 'позиці')):
        steps.append({'action': 'products.count', 'channel': 'prom'})
    if any(w in t for w in ('експеримент', 'пілот', 'дослід')):
        steps.append({'action': 'experiment.status', 'channel': 'prom'})
    if any(w in t for w in ('усе', 'все', 'зведен', 'загалом', 'огляд')):
        return [{'action': 'status.all', 'channel': 'all'}]
    if any(w in t for w in ('фід', 'наявн', 'застоя')):
        steps.append({'action': 'feeds.freshness', 'channel': 'all'})
    if any(w in t for w in ('ттн', 'посилк', 'відстеж', 'достав')):
        steps.append({'action': 'delivery.track', 'channel': 'novaposhta',
                      'ttn': '<номер>'})
    return steps


def run_step(step, execute=False):
    a = REGISTRY.get(step['action'])
    if not a:
        return {'помилка': f'немає дії {step["action"]}'}
    kw = {k: v for k, v in step.items() if k != 'action'}
    try:
        return a['fn'](execute=execute, **kw)
    except Exception as exc:
        return {'збій': f'{type(exc).__name__}: {exc}'}


def show(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--run', metavar='ДІЯ')
    ap.add_argument('--channel', default='rozetka')
    ap.add_argument('--plan', metavar='ТЕКСТ')
    ap.add_argument('--execute', action='store_true',
                    help='справжнє виконання; без нього — холостий прогін')
    ap.add_argument('--arg', action='append', default=[], metavar='КЛЮЧ=ЗНАЧЕННЯ')
    a = ap.parse_args()
    extra = dict(x.split('=', 1) for x in a.arg)

    if a.list:
        print(f'{"дія":<22}{"канали":<34}{"оборотна":>9}{"гроші":>7}')
        for n, d in sorted(REGISTRY.items()):
            print(f'{n:<22}{",".join(d["channels"]):<34}'
                  f'{"так" if d["reversible"] else "НІ":>9}{"так" if d["cost"] else "—":>7}')
            print(f'   {d["about"]}')
    elif a.plan:
        steps = plan_from_text(a.plan)
        print(f'ПЛАН для «{a.plan}»: {len(steps)} кроків')
        for i, s in enumerate(steps, 1):
            d = REGISTRY.get(s['action'], {})
            mark = '' if d.get('reversible', True) else '  ⚠ НЕОБОРОТНА'
            print(f'  {i}. {s["action"]} ({s.get("channel")}){mark}')
        print()
        for i, s in enumerate(steps, 1):
            print(f'── крок {i}: {s["action"]} ──')
            show(run_step(s, execute=a.execute))
    elif a.run:
        show(run_step({'action': a.run, 'channel': a.channel, **extra},
                      execute=a.execute))
    else:
        ap.print_help()
