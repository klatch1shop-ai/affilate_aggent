#!/usr/bin/env python3
"""Калібрування підходу до keywords Рівня 2: який промпт дає більше придатних фраз.

Порівнюємо чотири варіанти на однакових товарах і міряємо одне —
**частку фраз, що проходять валідатор**. Без цієї цифри проектувати
workflow немає сенсу: різниця між підходами може бути в рази.

Ключова ідея шаблонів: кожен слот заповнюється З НАШИХ ДАНИХ, а не текстом
моделі. Тоді фактична помилка на кшталт «Тканина TPE» структурно неможлива —
матеріал підставляється зі значення, яке в нас реально є, а не з того, що
модель вважає матеріалом. Заборонених слів («купити», «ціна», «відгуки»)
у шаблонах немає взагалі, тому їх нізвідки взяти.

Варіанти:
  A  Рівень 1 як є — детермінована комбінаторика, 0 витрат, точка відліку
  B  вільна генерація — «дай 4 фрази» (те, що показало сирий результат)
  C  вибір із заповнених шаблонів — модель лише обирає, не вигадує
  D  лише синоніми типу товару — модель дає лексику, фрази складаємо ми

Запуск:
    python3 tools/prom_kw_calibrate.py --n 20
"""
import argparse
import json
import os
import re
import sys
import time

import psycopg2.extras
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402
from prom_keywords import (CATEGORY, MATERIAL, GENDER_IDX, build,
                           name_phrase, real_vendor)  # noqa: E402

OLLAMA = 'http://localhost:11434/api/generate'
MODEL = 'aya-expanse:8b'

# Заборонені слова: Prom додає їх сам, ручне введення марнує ліміт і
# вважається спамом (SKILL-13.3). Плюс слова, які не є пошуковими фразами.
STOP = {'купити', 'замовити', 'ціна', 'ціни', 'дешево', 'недорого', 'терміново',
        'оптом', 'відгуки', 'відгук', 'огляд', 'де', 'продають', 'магазин',
        'доставка', 'знижка', 'акція', 'найкращий', 'топ'}

# 12 шаблонів. Жоден не має вільного слота — усі підставляються з наших полів.
# Свідомо немає шаблону виду «{тип} {дія}»: слот «дія» дозволив би моделі
# підставити «купити». Немає й «{тип} {будь-яка характеристика}» — лише
# конкретні поля, значення яких у нас є.
TEMPLATES = [
    ('{тип} {бренд}',              ('тип', 'бренд')),
    ('{тип} {модель}',             ('тип', 'модель')),
    ('{бренд} {модель}',           ('бренд', 'модель')),
    ('{тип} {призначення}',        ('тип', 'призначення')),
    ('{матеріал} {тип}',           ('матеріал', 'тип')),
    ('{тип} {колір}',              ('тип', 'колір')),
    ('{тип} {розмір}',             ('тип', 'розмір')),
    ('{тип} {аудиторія}',          ('тип', 'аудиторія')),
    ('{назва_голова}',             ('назва_голова',)),
    ('{назва_голова} {бренд}',     ('назва_голова', 'бренд')),
    ('{матеріал} {тип} {бренд}',   ('матеріал', 'тип', 'бренд')),
    ('{тип} {бренд} {призначення}', ('тип', 'бренд', 'призначення')),
]


def slots(item: dict) -> dict:
    """Значення слотів — виключно з наших полів. Порожні слоти вимикають шаблон."""
    cat = CATEGORY.get((item.get('cat') or '').strip())
    single, gender, purpose = cat if cat else ('', 'm', '')
    prm = item.get('params') or {}
    mat = (prm.get('Матеріал') or '').split('|')[0].split(',')[0].strip()
    name = item.get('name') or ''
    # У sexopt_products бренд записаний як «Hismith (Китай)» — країну треба
    # зняти, інакше вона потрапляє у фразу. Голову назви беремо перевіреною
    # функцією: власна копія не мала фіксу обриву на прийменнику.
    ven = real_vendor(re.sub(r'\s*\(.*?\)', '', item.get('vendor') or '').strip())
    head = name_phrase(name, ven)
    m = re.search(re.escape(ven) + r'\s+([A-Za-z][A-Za-z0-9\-]+)', name) if ven else None
    return {
        'тип': single,
        'бренд': ven if ven.lower() not in ('без бренда', 'без бренду') else '',
        'модель': m.group(1) if m else '',
        'призначення': purpose,
        'матеріал': (MATERIAL[mat][GENDER_IDX[gender]] if mat in MATERIAL else ''),
        'колір': (prm.get('Колір') or '').split('|')[0].strip().lower(),
        'розмір': (prm.get('Розмір') or '').split('|')[0].strip(),
        'аудиторія': {'Жіноча': 'для жінок', 'Чоловіча': 'для чоловіків',
                      'Унісекс': 'для пар'}.get((prm.get('Стать') or '').strip(), ''),
        'назва_голова': head.strip(),
    }


def filled_templates(item: dict) -> list:
    """Шаблони, для яких у нас є ВСІ потрібні значення."""
    s = slots(item)
    out = []
    for tpl, need in TEMPLATES:
        if all(s.get(k) for k in need):
            phrase = tpl
            for k, v in s.items():
                phrase = phrase.replace('{%s}' % k, v)
            phrase = re.sub(r'\s+', ' ', phrase).strip().lower()
            if 2 <= len(phrase.split()) <= 4 and phrase not in out:
                out.append(phrase)
    return out


def validate(phrase: str, item: dict, allowed_pool=None) -> str:
    """Порожній рядок = придатна фраза; інакше — причина відхилення."""
    p = re.sub(r'[«»"\'.;:]', ' ', (phrase or '')).strip().lower()
    p = re.sub(r'^\d+[\).\s]+', '', p).strip()
    if not p:
        return 'порожня'
    w = p.split()
    if not (2 <= len(w) <= 4):
        return f'{len(w)} слів'
    if any(x in STOP for x in w):
        return 'заборонене слово'
    if len(p) > 60:
        return 'задовга'
    # чужий бренд: будь-яка латиниця має належати нашому бренду або моделі
    ven = re.sub(r'\s*\(.*?\)', '', item.get('vendor') or '').strip().lower()
    name = (item.get('name') or '').lower()
    for x in w:
        if re.fullmatch(r'[a-z][a-z0-9\-]+', x) and x not in ven and x not in name:
            return f'чужий бренд/модель «{x}»'
    # факт, якого немає в наших даних: матеріал зі словника, але не наш
    prm = {k.lower(): (v or '').lower() for k, v in (item.get('params') or {}).items()}
    for mat in MATERIAL:
        forms = [f.lower() for f in MATERIAL[mat]]
        if any(x in forms for x in w) and mat.lower() not in prm.get('матеріал', ''):
            return f'матеріал «{mat}» не з наших даних'
    if allowed_pool is not None and p not in allowed_pool:
        return 'не зі списку шаблонів'
    return ''


def ask(prompt: str, npred=90) -> str:
    r = requests.post(OLLAMA, json={
        'model': MODEL, 'prompt': prompt, 'stream': False,
        'options': {'temperature': 0.2, 'num_predict': npred}}, timeout=300)
    return r.json().get('response', '')


def split_lines(txt: str) -> list:
    out = []
    for ln in re.split(r'[\n,;]', txt or ''):
        ln = re.sub(r'^\s*\d+[\).\s]+', '', ln).strip(' «»"\'.-')
        if ln:
            out.append(ln.lower())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=20)
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT p.sku, p.name, p.vendor, c.name cat
                   FROM sexopt_products p
                   JOIN sexopt_categories c ON c.id = p.category_id
                   WHERE p.available AND p.price_retail > 0
                   ORDER BY md5(p.sku) LIMIT %s""", (a.n,))
    items = [dict(r) for r in cur.fetchall()]
    cur.execute("""SELECT sku, param_name, param_value FROM sexopt_extracted_params
                   WHERE sku = ANY(%s)""", ([i['sku'] for i in items],))
    for r in cur.fetchall():
        for it in items:
            if it['sku'] == r['sku']:
                it.setdefault('params', {})[r['param_name']] = r['param_value']

    stats = {}
    for variant in ('A', 'B', 'C', 'D'):
        ok = bad = 0
        reasons, t0, sample = {}, time.time(), []
        for it in items:
            pool = filled_templates(it)
            if variant == 'A':
                phrases = build(it['name'],
                                re.sub(r'\s*\(.*?\)', '', it['vendor'] or '').strip(),
                                it['cat'], it.get('params') or {})
            elif variant == 'B':
                txt = ask(f"Товар: {it['name']}. Бренд: {slots(it)['бренд']}. "
                          f"Категорія: {it['cat']}.\nДай 4 пошукові фрази "
                          f"українською, по 2-4 слова, через кому. "
                          f"Тільки фрази.")
                phrases = split_lines(txt)[:4]
            elif variant == 'C':
                if not pool:
                    continue
                lst = '\n'.join(f'{i+1}. {p}' for i, p in enumerate(pool))
                txt = ask(f"Товар: {it['name']}.\nСписок фраз:\n{lst}\n"
                          f"Обери 4 найкращі для пошуку. Виведи лише обрані "
                          f"фрази, кожну з нового рядка, дослівно як у списку.",
                          npred=70)
                phrases = split_lines(txt)[:4]
            else:
                base = slots(it)['тип'] or (it['cat'] or '')
                txt = ask(f"Назви 3 синоніми українською для типу товару "
                          f"«{base}». Лише слова через кому, без пояснень.", 40)
                syn = [x for x in split_lines(txt) if 1 <= len(x.split()) <= 2][:3]
                ven = slots(it)['бренд']
                phrases = [f'{s} {ven}'.strip() for s in syn if ven] or syn
            for ph in phrases:
                why = validate(ph, it, pool if variant == 'C' else None)
                if why:
                    bad += 1
                    reasons[why.split('«')[0].strip()] = \
                        reasons.get(why.split('«')[0].strip(), 0) + 1
                else:
                    ok += 1
                    if len(sample) < 4:
                        sample.append(ph)
        tot = ok + bad
        stats[variant] = (ok, tot, time.time() - t0, reasons, sample)
        pct = ok * 100 // tot if tot else 0
        print(f'\n── ВАРІАНТ {variant} ──  придатних {ok}/{tot} ({pct}%)  '
              f'{stats[variant][2]:.0f} с')
        for k, v in sorted(reasons.items(), key=lambda x: -x[1])[:4]:
            print(f'     ✗ {k}: {v}')
        print(f'     приклади: {"; ".join(sample)}')

    print('\n══ ПІДСУМОК ══')
    print(f'{"вар":4}{"придатних":>12}{"%":>6}{"с/товар":>10}')
    for v, (ok, tot, dt, _, _) in stats.items():
        print(f'{v:4}{f"{ok}/{tot}":>12}{(ok*100//tot if tot else 0):>6}'
              f'{dt/max(len(items),1):>10.1f}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
