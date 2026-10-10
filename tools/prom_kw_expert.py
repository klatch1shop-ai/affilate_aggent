#!/usr/bin/env python3
"""Ключові слова Prom за аналізом УСІЄЇ картки, включно з фото.

Метод (власник, 03.10.2026): дати колезі максимально продуктивну роль —
з розумінням стеку й обмежень — і попросити написати ідеальні ключі на
основі всієї інформації картки: назв двома мовами, опису, характеристик і
ФОТО.

Чому фото вирішальне. Перевірено на SX0682 «Driminals Golden Touch»: на
тюбику надруковано CAPSAICIN, ARGININA, DAMIANA, GUARANA — складники, яких
НЕМАЄ ні в назві, ні в описі, ні в характеристиках. Я звірив зображення
очима: модель не вигадала нічого. Жоден детермінований генератор цього
джерела не дістане.

Чому роль спрацювала. Не через слово «фахівець», а через те, що в запит
покладені ОБМЕЖЕННЯ СТЕКУ як факти: два окремі поля по 9 слотів, збіг у
межах одного ключа, заборона розділеного збігу, і головне — що 91,7 %
наших слотів уже зайняті спільними фразами, тож загальний ключ картці
користі не дає. Без цього модель видає звичайний список загальних фраз.

ПОРЯДОК (кожен крок обовʼязковий):
  1. відбір карток за категорією
  2. збір УСІХ даних картки + фото
  3. Gemini з роллю → пропозиції з обґрунтуванням кожної фрази
  4. детермінована перевірка: мова, довжина, повтори, частота в каталозі
  5. перехресна перевірка другим вендором на вибірці
  6. показ власнику ДО внесення
  7. внесення лише доповненням, ніколи заміною

    venv/bin/python3 tools/prom_kw_expert.py --category Лубриканты --limit 5
"""
import argparse
import base64
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter as collections_Counter
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# Ознаки ВИЧЕРПАНОГО КАНАЛУ, а не дефекту картки. Перелік один на всі
# інструменти: 03.10 він розʼїхався між `ask()` і відновлюваним прогоном, і
# CodexLimitError («You've hit your usage limit») не впізнався — прогін
# крутився по колу, щоразу позначаючи ті самі 48 карток «немає JSON».
EXHAUSTED_SIGNS = ('402', '429', 'depleted', 'resource_exhausted', 'usage limit',
                   'rate limit', 'quota', 'codexlimiterror', 'too many requests')


def is_exhausted(exc):
    return any(s in f'{type(exc).__name__} {exc}'.lower() for s in EXHAUSTED_SIGNS)
from shared.utils.llm_router import call_gemini  # noqa: E402
from shared.utils.vendor_pool import call as vendor_call  # noqa: E402
from shared.utils.llm_router import call_deepseek  # noqa: E402

FEED = '/tmp/prom_live.xml'
OUT = os.path.join(BASE, 'exports', 'prom_kw_expert.json')
LIMIT = 9
CYR_UA = re.compile(r'[іїєґІЇЄҐ]')
CYR_RU = re.compile(r'[ыэъёЫЭЪЁ]')
# Межа слова тільки НА ПОЧАТКУ. 04.10: з \b і в кінці фільтр пропускав
# «недорогой», «украинская» — після стему йде літера, межі там немає, і
# 14 таких ключів дійшли до фіду. Межа в кінці ще й шкідлива: без неї на
# початку «цена» знаходиться всередині «сценариями».
BANNED = re.compile(r'\b(купит|купувати|купити|замовит|заказат|недорог|дешев|'
                    r'цін|цена|київ|киев|україн|украин|доставк)', re.I)

ROLE = """Ти — SEO-спеціаліст українських маркетплейсів із 8-річним досвідом,
спеціалізація Prom.ua, категорія 18+. Ти вів каталоги на 10-50 тисяч позицій
і знаєш механіку Prom з практики, а не з блогів.

ОБМЕЖЕННЯ СТЕКУ (факти, перевірені викликами API):
1. Поля `keywords` (російські) і `keywords_ua` (українські) — ОКРЕМІ, по 9
   слотів. Мови не змішувати: російське слово в українському полі марне.
2. Збіг з запитом шукається В МЕЖАХ ОДНОГО ключа, не по всьому переліку.
   Повна відповідність не обовʼязкова: ключ «червона сукня в смужку»
   знайдеться за запитом «червона сукня».
3. КРИТИЧНО: часткова відповідність у НАЗВІ + часткова в КЛЮЧАХ = товару у
   видачі НЕМАЄ. Кожен ключ мусить сам покривати цілий запит.
4. Між релевантними словами у фразі — максимум 5 слів.
5. «купити», «замовити», назву міста НЕ додавати.
6. Назва важить більше за ключі.

СТАН ЦЬОГО МАГАЗИНУ (виміряно 03.10):
5401 картка; 91,7 % слотів зайняті фразами, СПІЛЬНИМИ з іншими картками
цього ж магазину — «вибратор для клитора» стоїть на 1149 картках. Картки
конкурують одна з одною. Тому ключ, який уже на сотнях наших карток, цій
картці користі НЕ дає. Потрібні фрази, унікальні для неї."""

# ВАРІАНТ Б — дослід 04.10. Три зміни проти основного запиту:
#   1. якщо жоден наявний ключ не унікальний, дозволено замінити ВСІ 9 слотів
#      (ключ, що стоїть на тисячі карток, усе одно нічого не дає);
#   2. знахідка з фото, якої немає в тексті, МУСИТЬ стати ключем — це єдине
#      джерело унікальності картки;
#   3. міркування увімкнене.
# Привід: на SX2663 модель побачила підсвічування на фото, але в ключ його
# не винесла, і дала лише 5 ключів, бо звільнила лише 5 слотів.
TASK_B = """
Поверни ЛИШЕ JSON такої форми, без жодного тексту навколо:
{
 "ru": [{"k": "фраза", "why": "який запит покриває"}, ...],
 "ua": [{"k": "фраза", "why": "..."}, ...],
 "remove": [{"k": "нинішній ключ", "why": "чому прибрати"}, ...],
 "from_photo": "що видно на фото, чого немає в тексті картки, або порожньо",
 "beyond_keywords": "одна зміна поза ключами, яка дасть більше"
}

ПРАВИЛА ЦЬОГО ЗАВДАННЯ:
* Пропонуй до 9 фраз на кожну мову. Якщо серед нинішніх ключів НЕМАЄ жодного,
  унікального для цієї картки, — пропонуй ВСІ 9 і прибирай усі загальні:
  ключ, що стоїть на сотнях карток магазину, цій картці користі не дає.
* Якщо на ФОТО видно щось, чого немає в назві, описі й характеристиках, —
  це МУСИТЬ стати ключем. Саме така деталь робить картку унікальною, і
  більше її взяти нізвідки.
* У фразах НЕ ВЖИВАЙ КОМУ й крапку з комою: ключі зберігаються через кому,
  тому «вібратор 2,5 см» перетвориться на два зламані ключі."""

# ВАРІАНТ В — дослід 04.10: усе корисне з Б, але БЕЗ міркування й з
# вимогою різноманітності. Привід: варіант Б на картці Tenga дав 8 ключів
# із 16, що починались з «мастурбатор тенга» — набивання однієї основи.
# За правилом Prom збіг шукається в межах ОДНІЄЇ фрази, тож вісім майже
# однакових фраз конкурують між собою замість покривати різні запити.
TASK_C = """
Поверни ЛИШЕ JSON такої форми, без жодного тексту навколо:
{
 "ru": [{"k": "фраза", "why": "який запит покриває"}, ...],
 "ua": [{"k": "фраза", "why": "..."}, ...],
 "remove": [{"k": "нинішній ключ", "why": "чому прибрати"}, ...],
 "from_photo": "що видно на фото, чого немає в тексті картки, або порожньо",
 "beyond_keywords": "одна зміна поза ключами, яка дасть більше"
}

ПРАВИЛА ЦЬОГО ЗАВДАННЯ:
* До 9 фраз на мову. Якщо серед нинішніх ключів НЕМАЄ жодного, унікального
  для цієї картки, — пропонуй усі 9 і прибирай загальні: ключ, що стоїть на
  сотнях карток магазину, цій картці користі не дає.
* Якщо на ФОТО видно те, чого немає в назві, описі й характеристиках, — це
  МУСИТЬ стати ключем. Інакше взяти унікальність нізвідки.
* РІЗНОМАНІТНІСТЬ ОБОВʼЯЗКОВА: не більше ТРЬОХ фраз на мову можуть
  починатися з того самого слова. Збіг шукається в межах однієї фрази, тож
  вісім схожих фраз конкурують між собою, а не покривають різні запити.
  Краще дев'ять різних напрямів, ніж дев'ять варіацій одного.
* Корисні напрями, які часто пропускають: транслітерація бренду чи імені
  кирилицею (люди не перемикають розкладку); сумісність з іншим пристроєм;
  сценарій використання; матеріал; розмір; те, що видно на фото.
* НЕ ВЖИВАЙ КОМУ й крапку з комою: ключі зберігаються через кому."""

TASK = """
Поверни ЛИШЕ JSON такої форми, без жодного тексту навколо:
{
 "ru": [{"k": "фраза", "why": "який запит покриває"}, ...],
 "ua": [{"k": "фраза", "why": "..."}, ...],
 "remove": [{"k": "нинішній ключ", "why": "чому прибрати"}, ...],
 "from_photo": "що видно на фото, чого немає в тексті картки, або порожньо",
 "beyond_keywords": "одна зміна поза ключами, яка дасть більше"
}
У "ru" і "ua" — до 9 фраз кожна, лише ті, яких ЩЕ НЕМАЄ в нинішніх ключах.
У фразах НЕ ВЖИВАЙ КОМУ й крапку з комою: ключі зберігаються через кому,
тому «вібратор 2,5 см» перетвориться на два зламані ключі."""


def card_text(o, cat):
    g = lambda t: (o.findtext(t) or '').strip()
    params = '\n'.join(f'  {p.get("name")}: {(p.text or "").strip()}'
                       for p in o.findall('param') if (p.text or '').strip())
    return f"""
КАРТКА {o.get('id')} · категорія: {cat}
Назва (рос): {g('name')}
Назва (укр): {g('name_ua')}
Бренд: {g('vendor')} · Ціна: {g('price')} грн
Характеристики:
{params or '  (немає)'}
Опис (рос): {g('description')[:700]}
Ключові слова ЗАРАЗ:
  keywords (рос): {g('keywords') or '(порожньо)'}
  keywords_ua (укр): {g('keywords_ua') or '(порожньо)'}
"""


# Фото більші за це не надсилаємо: зайвий трафік і ризик HTTP 400.
MAX_IMAGE = 4 * 1024 * 1024
OK_MIME = ('image/jpeg', 'image/png', 'image/webp')


def fetch_image(url):
    """→ (байти, mime) або (None, None). Тип беремо З ВІДПОВІДІ, не вгадуємо.

    03.10 інструмент оголошував усі фото як image/jpeg і на частині карток
    отримував HTTP 400: у фіді трапляються png і webp.
    """
    try:
        r = requests.get(url, timeout=40)
        if r.status_code != 200 or len(r.content) > MAX_IMAGE:
            return None, None
        mime = (r.headers.get('content-type') or '').split(';')[0].strip()
        if mime not in OK_MIME:
            return None, None
        return r.content, mime
    except Exception:
        return None, None


def ask(o, cat, vendor='gemini', variant='a'):
    """vendor: 'gemini', 'codex' або 'deepseek'.

    Codex приймає зображення лише ФАЙЛОМ — `vendor_pool.call` це робить сам,
    кладучи байти в тимчасовий файл. Gemini навпаки приймає лише байти.
    """
    pics = [p.text for p in o.findall('picture') if p.text]
    img, mime = fetch_image(pics[0]) if pics else (None, None)
    # Незмінна частина (ROLE + TASK) — ПЕРШОЮ, дані картки — в кінці.
    # Кеш вхідних токенів працює лише на байтово точному префіксі від
    # нульового токена. Раніше TASK стояв ПІСЛЯ даних картки й тому не
    # кешувався взагалі — префікс обривався на першому ж унікальному слові.
    prompt = ROLE + {'b': TASK_B, 'c': TASK_C}.get(variant, TASK) + card_text(o, cat)

    def once(with_image):
        if vendor == 'deepseek':
            # міркування вимкнене: для «прочитати картку → JSON» роздуми
            # лише палять вихідні токени, а вони вчетверо дорожчі за вхідні
            return call_deepseek(prompt, timeout=600,
                                 max_tokens=16000 if variant == 'b' else 8000,
                                 image_bytes=img if with_image else None,
                                 image_mime=mime, thinking=(variant == 'b'))
        if vendor == 'codex':
            return vendor_call('codex', prompt, timeout=600,
                               image_bytes=img if with_image else None,
                               image_mime=mime, max_tokens=16000)
        return call_gemini(prompt, timeout=240, max_tokens=16000,
                           model='gemini-3.5-flash',
                           image_bytes=img if with_image else None,
                           image_mime=mime)

    try:
        res = once(True)
    except Exception as exc:
        # 402 (скінчились кошти) і 429 — не дефект картки, зупиняємо прогін,
        # а не палимо чергу: 03.10 усі 968 карток БДСМ позначились збоєм,
        # хоча причиною були вичерпані кошти Gemini.
        if is_exhausted(exc):
            raise RuntimeError(f'КАНАЛ ВИЧЕРПАНО: {str(exc)[:160]}')
        if img is None:
            return None
        try:
            res = once(False)
        except Exception:
            return None
    txt = res[0] if isinstance(res, tuple) else res
    # gemini-3.5-flash — модель із міркуванням: при max_tokens=3000 роздуми
    # зʼїдали бюджет і видимий текст обривався на 327 символах. 16000 вистачає.
    m = re.search(r'\{.*\}', txt or '', re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def removable(o, key, freq, tag):
    """Чи МОЖНА прибрати цей ключ. Думки моделі НЕ досить.

    Правило merge-not-replace лишається чинним: заміна ключів за правилами
    колись убила довгий хвіст. Тому прибираємо ЛИШЕ те, що провалює
    ВИМІРЮВАНИЙ тест, а не те, що моделі здалося зайвим:
      * ключ стоїть на 50+ наших картках — внутрішня конкуренція, показатись
        за ним може кілька, решта ніколи;
      * усі слова ключа вже є в назві — назва важить більше, а за правилом
        Prom часткова відповідність у назві + часткова в ключах узагалі
        виводить товар із видачі.
    """
    k = key.strip().lower()
    if freq[tag].get(k, 0) >= 50:
        return f'стоїть на {freq[tag][k]} наших картках'
    name = (o.findtext('name' if tag == 'keywords' else 'name_ua') or '').lower()
    words = set(re.findall(r'\w+', k))
    if words and words <= set(re.findall(r'\w+', name)):
        return 'усі слова вже є в назві'
    return None


def validate(o, data, freq):
    """Детермінована перевірка пропозицій. Повертає (прийняті, відхилені)."""
    g = lambda t: [k.strip().lower()
                   for k in (o.findtext(t) or '').split(',') if k.strip()]
    # СПЕРШУ рахуємо, що можна звільнити: інакше найкращі ключі
    # відхиляються з причини «немає вільних слотів», хоча слоти зайняті
    # саме сміттям, яке ми й збираємось прибрати.
    drop = []
    for item in (data.get('remove') or []):
        kk = str(item.get('k', '')).strip().lower()
        for tg in ('keywords', 'keywords_ua'):
            if kk in set(g(tg)):
                why = removable(o, kk, freq, tg)
                if why:
                    drop.append({'k': kk, 'tag': tg, 'why_model': item.get('why', ''),
                                 'why_measured': why})
    freed = {t: sum(1 for d in drop if d['tag'] == t)
             for t in ('keywords', 'keywords_ua')}

    ok, bad = {'keywords': [], 'keywords_ua': []}, []
    stems = {'keywords': collections_Counter(), 'keywords_ua': collections_Counter()}
    for lang, tag in (('ru', 'keywords'), ('ua', 'keywords_ua')):
        have = set(g(tag))
        free = LIMIT - len(have) + freed[tag]
        for item in (data.get(lang) or []):
            k = re.sub(r'\s+', ' ', str(item.get('k', '')).strip().lower())
            why = item.get('why', '')
            if len(ok[tag]) >= free:
                bad.append((k, 'немає вільних слотів'))
                continue
            # КОМА В КЛЮЧІ НЕДОПУСТИМА: ключі зберігаються через кому, тож
            # «вибропуля 2,5 см» при читанні розпадається на два ключі й
            # ламає ліміт у 9 слотів. 04.10 так вийшло на 9 картках.
            if ',' in k or ';' in k:
                bad.append((k, 'кома в ключі — розпадеться на два'))
            elif BANNED.search(k):
                # довідка Prom: «купити», «замовити», назву регіону додавати
                # НЕ треба — вони лише з'їдають слот
                bad.append((k, 'заборонене довідкою слово'))
            elif not (2 <= len(k.split()) <= 6):
                bad.append((k, 'не фраза-запит: 2-6 слів'))
            elif k in have or k in {x['k'] for x in ok[tag]}:
                bad.append((k, 'уже є на картці'))
            elif lang == 'ua' and CYR_RU.search(k):
                bad.append((k, 'російські літери в українському полі'))
            elif lang == 'ru' and CYR_UA.search(k):
                bad.append((k, 'українські літери в російському полі'))
            elif freq[tag].get(k, 0) >= 50:
                bad.append((k, f'уже на {freq[tag][k]} картках — спільний'))
            elif stems[tag][k.split()[0]] >= 3:
                # не більше трьох фраз з того самого першого слова: інакше
                # вони конкурують між собою, а не покривають різні запити
                bad.append((k, f'четверта фраза з «{k.split()[0]}» — набивання'))
            else:
                stems[tag][k.split()[0]] += 1
                ok[tag].append({'k': k, 'why': why})
    return ok, bad, drop


def main(category, limit, workers, vendor='gemini'):
    import collections
    offers = list(ET.parse(FEED).getroot().iter('offer'))
    cats = json.load(open('/tmp/prom_cats.json', encoding='utf-8'))
    freq = {t: collections.Counter(
        k.strip().lower() for o in offers
        for k in (o.findtext(t) or '').split(',') if k.strip())
        for t in ('keywords', 'keywords_ua')}

    pick = [o for o in offers if cats.get(o.get('id')) == category]
    if limit:
        pick = pick[:limit]
    print(f'категорія «{category}»: {len(pick)} карток', flush=True)

    result, rejected = {}, []

    def one(o):
        data = ask(o, category, vendor)
        if not data:
            return o.get('id'), None, [('—', 'модель не повернула JSON')]
        good, bad, drop = validate(o, data, freq)
        return o.get('id'), {'name': (o.findtext('name') or '')[:80],
                             'add': good, 'remove': drop,
                             'remove_suggested': data.get('remove') or [],
                             'from_photo': data.get('from_photo') or '',
                             'beyond': data.get('beyond_keywords') or ''}, bad

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, (pid, row, bad) in enumerate(pool.map(one, pick), 1):
            if row:
                result[pid] = row
            rejected += [(pid, k, why) for k, why in bad]
            if n % 25 == 0:
                print(f'  {n}/{len(pick)}', flush=True)

    added = sum(len(v['add'][t]) for v in result.values()
                for t in ('keywords', 'keywords_ua'))
    droppable = sum(len(v['remove']) for v in result.values())
    suggested = sum(len(v['remove_suggested']) for v in result.values())
    with_photo = sum(1 for v in result.values() if v['from_photo'])
    print(f'\nкарток оброблено: {len(result)}')
    print(f'ключів ПРИЙНЯТО перевіркою: {added}')
    print(f'відхилено: {len(rejected)}')
    print(f'карток, де фото дало нове: {with_photo}')
    print(f'модель радить прибрати: {suggested} · ПІДТВЕРДЖЕНО виміром: {droppable}')
    for k, why in collections.Counter(w for _p, _k, w in rejected).most_common(6):
        print(f'   {why}: {k}')
    json.dump({'category': category, 'cards': result, 'rejected': rejected},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('→', OUT)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--category', required=True)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--vendor', choices=['gemini', 'codex', 'deepseek'],
                    default='gemini')
    a = ap.parse_args()
    main(a.category, a.limit, a.workers, a.vendor)
