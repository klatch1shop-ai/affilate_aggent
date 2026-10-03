#!/usr/bin/env python3
"""Семантична перевірка запропонованих ключів через Gemini.

Навіщо окремий крок: детерміновані правила ловлять уламки, підміну типу й
підміну статі, але не бачать того, що видно лише зі змісту. У вибірці 03.10
пройшли повз правила три справжні дефекти:
  * «набор art of sex» — тип «набор» надто загальний, запитом не буває;
  * «ns novelties i dream» — модель обрізана посеред назви «I Dream of MILF»;
  * «вибратор для женщин» на рідкому гелі-збуднику — товар не прилад.

Модель тут НЕ вигадує ключі (вигадані нею фрази нічим не перевірити) — вона
лише БРАКУЄ запропоновані детермінованим генератором. Відповідь жорстка:
кожен ключ дістає «так» або «ні» з причиною. Усе, що не «так», у фід не йде.

Перевірка — ДВОМА РІЗНИМИ вендорами (groq і cerebras), а не однією моделлю
двічі. Це головне правило партійних задач: 26.09 батч атрибутів Єпіцентру
дав 2557 рядків, де 94 % «перевірок двома джерелами» виявились однією
моделлю, бо запасний канал тихо підміняв основний. Збіг моделі з самою
собою нічого не доводить.

При розбіжності двох вендорів питаємо третього (gemini) як арбітра — його
добова квота мала, тому він працює лише на спірних, а не на всьому потоці.

Одна картка — один запит, зате паралельно. Пакетування по 5-8 карток
обривалось за лімітом токенів, і половина ключів лишалась без вердикту;
дробити пачки виявилось складніше, ніж не пакетувати взагалі.

    venv/bin/python3 tools/prom_kw_verify.py --limit 50 --workers 8
"""
import argparse
import collections
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from shared.utils.vendor_pool import call as vendor_call  # noqa: E402

PLAN = os.path.join(BASE, 'exports', 'prom_kw_plan.json')
OUT = os.path.join(BASE, 'exports', 'prom_kw_verified.json')

PROMPT = """Ти перевіряєш ключові слова для товарів на маркетплейсі Prom.ua.

Ключове слово — це ПОШУКОВИЙ ЗАПИТ, який покупець сам вводить у пошук.
Не опис товару, не перелік ознак, а те, що людина друкує.

Відхиляй ключ, якщо він:
 - називає інший товар, ніж у назві (напр. гель названо приладом);
 - плутає стать користувача (мастурбатор — чоловічий товар; фалоімітатор,
   вібратор для клітора — жіночі);
 - містить обрізану назву моделі (напр. «i dream» від «I Dream of MILF»);
 - складається з надто загального слова («набір», «товар», «пристрій»),
   бо за таким запитом товар не знайдуть;
 - просто неприродний як запит українською чи російською.

Приймай ключ, якщо людина реально могла б так шукати цей товар.

ТОВАРИ:
{items}

Відповідь — ЛИШЕ рядки виду:
<номер ключа>|<так або ні>|<коротка причина, якщо ні>

Номер бери той, що стоїть перед ключем. Сам ключ НЕ переписуй — лише номер.
Нічого іншого не пиши."""


def norm(s):
    return re.sub(r'\s+', ' ', (s or '').strip().lower())


def ask_batch(cards, vendor, timeout=180):
    """cards: [(назва, [ключі])] → {наскрізний номер: (ок, причина)}.

    Пакетуємо навмисне. groq і cerebras на ОДИНОЧНІЙ картці повертають
    порожню відповідь (моделі з міркуванням витрачають бюджет на роздуми,
    коли очікується один рядок), а на пачці з кількох товарів відповідають
    справно — перевірено 03.10. Gemini навпаки тягне й поодинокі, тому
    добирає тих, кого пачка не покрила.

    Ключі нумеруються наскрізно, і модель відповідає НОМЕРОМ: зіставляти за
    текстом не можна, бо groq віддавав «двосторонний» замість «двусторонний»,
    а cerebras «клиторальний» замість «клиторальный».
    """
    body, n, numbers = [], 0, []
    for i, (name, keys) in enumerate(cards, 1):
        body.append(f'Товар {i}: {name}')
        row = []
        for k in keys:
            n += 1
            row.append(n)
            body.append(f'   {n}) {k}')
        numbers.append(row)
    try:
        res = vendor_call(vendor, PROMPT.format(items='\n'.join(body)),
                          timeout=timeout, max_tokens=4000)
    except Exception:
        return {}, numbers
    txt = res[0] if isinstance(res, tuple) else res
    out = {}
    for line in (txt or '').splitlines():
        parts = [x.strip() for x in line.split('|')]
        if len(parts) < 2 or not parts[0].rstrip('.)').isdigit():
            continue
        out[int(parts[0].rstrip('.)'))] = (
            parts[1].lower().startswith(('так', 'yes')),
            parts[2] if len(parts) > 2 else '')
    return out, numbers


def ask_both_orders(cards, vendor):
    """Питаємо той самий набір у ПРЯМОМУ і ЗВОРОТНОМУ порядку.

    Судді віддають перевагу тому, що стоїть першим. Заміряно на НАШИХ даних
    03.10.2026: вердикт змінюється від порядку в 12,5 % випадків у groq і
    8,3 % у cerebras (52 вердикти). Менше за 15-30 % із літератури, але не
    нуль — і це чисті помилки, бо зміст ключа від порядку не залежить.

    Зараховуємо лише ті вердикти, що збіглися в обох порядках.
    """
    rev = [(name, list(reversed(keys))) for name, keys in cards]
    fwd_ans, numbers = ask_batch(cards, vendor)
    rev_ans, _ = ask_batch(rev, vendor)
    agreed = {}
    for i, (_name, keys) in enumerate(cards):
        row = numbers[i]
        n = len(row)
        for j, _k in enumerate(keys):
            va, vb = fwd_ans.get(row[j]), rev_ans.get(row[n - 1 - j])
            if va and vb and va[0] == vb[0]:
                agreed[row[j]] = va
    return agreed, numbers


def verify_batch(ids, plan):
    cards = []
    for pid in ids:
        p = plan[pid]
        cards.append((p['name'], [k for ks in p['add'].values() for k in ks]))
    a, numbers = ask_both_orders(cards, 'groq')
    b, _ = ask_both_orders(cards, 'cerebras')
    want = {n for row in numbers for n in row}
    if not (want <= set(a)) or not (want <= set(b)):
        # пачку обрізало — добираємо Gemini, він тягне й короткі відповіді
        g, _ = ask_batch(cards, 'gemini')
        for n, v in g.items():
            a.setdefault(n, v)
            b.setdefault(n, v)
    kept, dropped = {}, []
    for i, pid in enumerate(ids):
        p = plan[pid]
        nums, pos, good = numbers[i], 0, {}
        for tag, ks in p['add'].items():
            okk = []
            for k in ks:
                num = nums[pos]; pos += 1
                ra, rb = a.get(num), b.get(num)
                if ra and rb and ra[0] == rb[0]:
                    if ra[0]:
                        okk.append(k)
                    else:
                        dropped.append({'id': pid, 'key': k, 'why': ra[1],
                                        'by': 'groq+cerebras'})
                elif ra and rb:
                    dropped.append({'id': pid, 'key': k, 'by': 'спірне',
                                    'why': f'розбіжність groq={ra[0]} cerebras={rb[0]}'})
                else:
                    dropped.append({'id': pid, 'key': k, 'by': '—',
                                    'why': 'немає відповіді'})
            if okk:
                good[tag] = okk
        if good:
            kept[pid] = {'name': p['name'], 'add': good}
    return kept, dropped


def main(limit, workers, batch=6):
    from concurrent.futures import ThreadPoolExecutor
    plan = json.load(open(PLAN, encoding='utf-8'))
    ids = list(plan)[:limit] if limit else list(plan)
    chunks = [ids[i:i + batch] for i in range(0, len(ids), batch)]
    kept, dropped = {}, []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(verify_batch, c, plan) for c in chunks]
        for n, f in enumerate(futs, 1):
            k, d = f.result()
            kept.update(k)
            dropped += d
            if n % 40 == 0:
                print(f'  {n*batch}/{len(ids)}', flush=True)

    total_in = sum(len(k) for pid in ids for k in plan[pid]['add'].values())
    total_out = sum(len(k) for p in kept.values() for k in p['add'].values())
    print(f'\nкарток: {len(ids)} · з прийнятими ключами: {len(kept)}')
    print(f'ключів запропоновано: {total_in} · ПРИЙНЯТО двома вендорами: {total_out}')
    print(f'відхилено: {len(dropped)}')
    for w, n in collections.Counter(d['why'][:44] for d in dropped).most_common(10):
        print(f'   {n:>5}  {w}')
    json.dump({'kept': kept, 'dropped': dropped},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('→', OUT)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--batch', type=int, default=6)
    a = ap.parse_args()
    main(a.limit, a.workers, a.batch)
