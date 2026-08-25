#!/usr/bin/env python3
"""Які характеристики заповнює конкурент `ttul` там, де ми їх не заповнюємо.

Навіщо. Наш фід TOPTUL проходить валідатор на 0/0, але це нічого не каже про
ПОВНОТУ: у фільтри Rozetka потрапляє лише те, для чого є характеристика.
Конкурент `ttul` возить той самий TOPTUL і вже пройшов модерацію майданчика,
тож його картки — готова відповідь на питання «які поля тут узагалі заведено
заповнювати».

Межа застосування (SKILL-14.8): з чужих карток береться **лише перелік назв**
(структура). ЗНАЧЕННЯ характеристик не читаються, не зберігаються й не
потрапляють у звіт — чужа картка може стосуватись іншого варіанта товару, і
перенесення чужого факту на наш SKU є дезінформацією покупця, а не SEO.
Технічно це зроблено в `char_titles()`: із відповіді API беруться ключі
`title`, а гілка `values` не читається взагалі.

Два кроки, бо мережа й дані живуть на різних машинах:

1. `--dump-ours` — **на сервері**: читає `output/toptul_rozetka.xml` (наші
   назви характеристик по категоріях) і `data/rozetka_category_options.json`
   (офіційний довідник Rozetka) → JSON.
   Сервер для другого кроку не годиться: Cloudflare віддає йому 403 на
   сторінку продавця (перевірено 25.08.2026), тоді як `product-api` відповідає.
2. `--scrape` — **на ноутбуці**: сторінка продавця з фільтром `section_id`
   (= наш `rz_id`) → id товарів → `product-api/v4/goods/get-characteristic`
   → перелік назв → звіт `docs/toptul_competitor_fields.md`.

Запуск:
    ssh сервер 'venv/bin/python3 tools/toptul_competitor_fields.py \
        --dump-ours /tmp/toptul_ours.json'
    scp сервер:/tmp/toptul_ours.json /tmp/
    python3 tools/toptul_competitor_fields.py --scrape --ours /tmp/toptul_ours.json \
        --top 10 --sample 10
    python3 tools/toptul_competitor_fields.py --selftest
"""
import argparse
import collections
import difflib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FEED = os.path.join(BASE_DIR, 'output', 'toptul_rozetka.xml')
OPTIONS = os.path.join(BASE_DIR, 'data', 'rozetka_category_options.json')
REPORT = os.path.join(BASE_DIR, 'docs', 'toptul_competitor_fields.md')

SELLER = 'ttul'
# seller_id підтверджено 25.08.2026 на трьох товарах сторінки продавця; він же
# слугує перевіркою, що section_id не приніс чужі картки.
SELLER_ID = 13624

UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
HEADERS = {'User-Agent': UA, 'Accept-Language': 'uk-UA,uk;q=0.9'}
SELLER_URL = 'https://rozetka.com.ua/ua/seller/{seller}/goods/?section_id={sid}'
API = 'https://product-api.rozetka.com.ua/v4/goods/{method}'
PID_RE = re.compile(r'/p(\d{6,})/')

# Поріг консенсусу з SKILL-14.8: структуру беремо, коли її тримає більшість
# карток видачі, а не одна. Одиничне поле в одного продавця — його примха.
CONSENSUS = 0.5

# Поля, яких у нашому фіді немає й бути не може: їх проставляє сам майданчик
# або кабінет продавця, а не XML.
NOT_OURS = {'гарантія', 'країна-виробник товару', 'термін гарантії'}


# ─────────────────────────── спільне ────────────────────────────────────────

def norm(name: str) -> str:
    """Ключ порівняння назв характеристик.

    Апострофи в назвах Rozetka трапляються трьох видів (', ’, ʼ) — CLAUDE.md
    попереджає саме про це, і без зведення їх до одного «Кількість кишень» у
    нас і в них були б різними рядками, а звіт показав би вигадану прогалину.
    """
    s = (name or '').replace('’', "'").replace('ʼ', "'")
    s = s.replace(' ', ' ').strip().strip(':').lower()
    return re.sub(r'\s+', ' ', s)


# ─────────────────────── крок 1: наш бік (сервер) ───────────────────────────

def dump_ours(feed: str, options: str, out: str) -> dict:
    root = ET.parse(feed).getroot()
    cat_name, cat_rz = {}, {}
    for c in root.iter('category'):
        cat_name[c.get('id')] = (c.text or '').strip()
        cat_rz[c.get('id')] = c.get('rz_id')

    offers = collections.Counter()
    params = collections.defaultdict(collections.Counter)
    glob = collections.Counter()
    total = 0
    for o in root.iter('offer'):
        total += 1
        # <categoryId> у фіді — ЛОКАЛЬНИЙ id; rz_id живе атрибутом у <category>
        lid = (o.findtext('categoryId') or '').strip()
        offers[lid] += 1
        for p in o.findall('param'):
            params[lid][p.get('name')] += 1
            glob[p.get('name')] += 1

    rz_opts = {}
    if os.path.exists(options):
        with open(options, encoding='utf-8') as f:
            raw = json.load(f)
        for rz_id, rows in raw.items():
            seen = {}
            for r in rows:
                nm = r.get('name')
                if not nm:
                    continue
                seen.setdefault(norm(nm), {
                    'name': nm, 'id': r.get('id'),
                    'filter': r.get('filter_type') not in (None, 'disable'),
                })
            rz_opts[str(rz_id)] = seen

    cats, no_rz = {}, 0
    for lid, cnt in offers.items():
        rz = cat_rz.get(lid)
        if not rz:
            # без rz_id картку конкурента не знайти — такий рядок марний,
            # але мовчки зникати він не має права
            no_rz += 1
            continue
        cats[rz] = {
            'rz_id': rz,
            'local_id': lid,
            'name': cat_name.get(lid, ''),
            'offers': cnt,
            'our_params': dict(params[lid].most_common()),
            'rz_options': rz_opts.get(rz, {}),
        }
    if no_rz:
        print(f'УВАГА: категорій фіду без rz_id у блоці <category>: {no_rz}')

    data = {'generated': datetime.now().isoformat(timespec='seconds'),
            'feed': feed, 'feed_offers': total, 'categories': cats,
            # назва, яку ми вже вживаємо в ІНШИХ категоріях, — дешева
            # прогалина: словник і генератор її знають, бракує лише джерела
            # значень саме тут
            'global_params': dict(glob.most_common())}
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    print(f'офферів у фіді: {total}, категорій: {len(cats)}, '
          f'категорій із довідником Rozetka: '
          f'{sum(1 for c in cats.values() if c["rz_options"])}')
    print(f'→ {out} ({os.path.getsize(out)} Б)')
    return data


# ────────────────────── крок 2: бік конкурента (ноутбук) ────────────────────

def fetch(session, url: str, params=None, tries: int = 4):
    """GET із повтором. Rozetka рве зʼєднання (ConnectionReset) приблизно раз
    на сотню запитів; без повтору прогін падає посеред категорії, а гірше —
    міг би віддати неповний перелік карток як повний."""
    delay = 2.0
    for attempt in range(1, tries + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=40, params=params)
            if r.status_code == 200:
                return r
            if r.status_code in (403, 429, 500, 502, 503):
                print(f'  ! HTTP {r.status_code}, спроба {attempt}/{tries}')
            else:
                return r
        except Exception as e:
            print(f'  ! {type(e).__name__}, спроба {attempt}/{tries}')
        time.sleep(delay)
        delay *= 2
    return None


def seller_products(sid: str, session, pause: float = 1.2) -> list:
    """id товарів продавця у ЦІЙ категорії (перша сторінка видачі)."""
    r = fetch(session, SELLER_URL.format(seller=SELLER, sid=sid))
    if r is None or r.status_code != 200:
        print(f'  ! сторінка продавця недоступна '
              f'({r.status_code if r is not None else "немає відповіді"})')
        return []
    time.sleep(pause)
    return list(dict.fromkeys(PID_RE.findall(r.text)))


def api(method: str, gid: str, session):
    r = fetch(session, API.format(method=method), params={
        'front-type': 'xl', 'country': 'UA', 'lang': 'ua', 'goodsId': gid})
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json().get('data')
    except ValueError:
        return None


def char_titles(gid: str, session):
    """Перелік НАЗВ характеристик картки. Значення не читаються (SKILL-14.8).

    `None` — відповіді не отримано (дефект інструмента), `[]` — картка справді
    без характеристик. Змішувати ці два випадки не можна: перший зробив би
    «конкурент нічого не заповнює» твердженням про мережу.
    """
    data = api('get-characteristic', gid, session)
    if data is None:
        return None
    if not data:
        return []
    out = []
    for group in data:
        for opt in group.get('options', []):
            title = opt.get('title')
            if title:
                out.append(title)          # ← беремо title; opt['values'] ігнорується
    return list(dict.fromkeys(out))


def scrape(ours: dict, top: int, sample: int, pause: float) -> dict:
    import requests
    session = requests.Session()

    cats = sorted(ours['categories'].values(),
                  key=lambda c: -c['offers'])[:top]
    result = []
    for c in cats:
        rz = c['rz_id']
        print(f"[{rz}] {c['name']} — наших {c['offers']}")
        pids = seller_products(rz, session, pause)
        cards, skipped, empty = [], collections.Counter(), 0
        for gid in pids:
            if len(cards) >= sample:
                break
            main = api('get-main', gid, session)
            time.sleep(pause)
            if not main:
                skipped['картка не відповіла'] += 1
                continue
            if str(main.get('category_id')) != str(rz):
                skipped['інша категорія'] += 1
                continue
            if main.get('seller_id') != SELLER_ID:
                skipped['інший продавець'] += 1
                continue
            titles = char_titles(gid, session)
            time.sleep(pause)
            if titles is None:
                skipped['характеристики не відповіли'] += 1
                continue
            if not titles:
                empty += 1
            cards.append({'id': gid, 'title': main.get('title', ''),
                          'fields': titles})
        print(f'  карток узято {len(cards)} з {len(pids)} у видачі, '
              f'без характеристик {empty}, '
              f'відкинуто {dict(skipped) or "—"}')
        result.append({'rz_id': rz, 'name': c['name'], 'our_offers': c['offers'],
                       'our_params': c['our_params'],
                       'rz_options': c['rz_options'],
                       'listing': len(pids), 'empty': empty,
                       'skipped': dict(skipped), 'cards': cards})
    return {'generated': datetime.now().isoformat(timespec='seconds'),
            'ours_generated': ours['generated'], 'categories': result,
            'global_params': ours.get('global_params', {})}


# ──────────────────────────── розбір і звіт ─────────────────────────────────

def analyse(cat: dict) -> dict:
    """Порівняння переліків назв. Повертає й спільне, і відсутнє.

    Спільне потрібне не для краси: якщо перетин порожній, це майже напевно
    зламана нормалізація назв, а не «ми не заповнюємо нічого».
    """
    cards = cat['cards']
    n = len(cards)
    freq = collections.Counter()
    titles = {}
    for card in cards:
        for t in card['fields']:
            k = norm(t)
            freq[k] += 1
            titles.setdefault(k, t)

    ours = {norm(p): p for p in cat['our_params']}
    rz_opts = {norm(k): v for k, v in cat['rz_options'].items()}

    common, missing, rare = [], [], []
    for k, c in freq.most_common():
        share = c / n if n else 0
        rec = {'name': titles[k], 'cards': c, 'share': share,
               'rz_filter': rz_opts.get(k, {}).get('filter'),
               'rz_known': k in rz_opts}
        if k in ours:
            rec['our_name'] = ours[k]
            common.append(rec)
        elif k in NOT_OURS:
            continue
        elif share >= CONSENSUS:
            near = difflib.get_close_matches(k, list(ours), n=1, cutoff=0.75)
            rec['near'] = ours[near[0]] if near else None
            missing.append(rec)
        else:
            rare.append(rec)
    return {'n': n, 'common': common, 'missing': missing, 'rare': rare,
            'fields_seen': len(freq)}


def load_gaps(path: str) -> dict:
    """`docs/rozetka_option_gaps.json` — скільки назв бракує ЗА ОФІЦІЙНИМ
    довідником категорії. Потрібен для чесної рамки: довідник перелічує все,
    що майданчик уміє, разом із «EAN», «Код УКТ ЗЕД» і «Кнопкою
    передзамовлення», яких не заповнює ніхто. Скільки з того переліку
    заповнює живий продавець — і є відповідь цього звіту."""
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return {str(c['category_id']): c for c in json.load(f)}


def write_report(scraped: dict, path: str, gaps: dict = None) -> int:
    gaps = gaps or {}
    lines = [
        '# Структура характеристик у конкурента `ttul`',
        '',
        f'Зібрано {scraped["generated"]}; наш бік — зріз фіду '
        f'{scraped["ours_generated"]}.',
        '',
        'Джерело — картки продавця `ttul` (той самий TOPTUL) на Rozetka.',
        'За SKILL-14.8 узято **лише перелік назв характеристик**. Значення не',
        'читались і в звіті їх немає: чужа картка може стосуватись іншого',
        'варіанта товару.',
        '',
        f'«Бракує» = назву заповнює **≥{int(CONSENSUS * 100)}% його карток '
        'вибірки**, а в наших офферах цієї категорії такої назви немає жодного',
        'разу. Поодинокі поля винесені окремо — вони не консенсус.',
        '',
        'Колонка «Rozetka» — чи знає майданчик цю назву в цій категорії за '
        '`data/rozetka_category_options.json`:',
        '**фільтр** (потрапляє у фільтри видачі), **так** (знає, але не '
        'фільтр), **—** (у довіднику немає; довідник містить лише',
        'характеристики з переліком значень, тож числові поля туди не '
        'потрапляють).',
        '',
        'Колонка «У нас деінде» — скільки разів ця сама назва вже стоїть у '
        'нашому фіді в ІНШИХ категоріях. Ненуль означає, що назву наш',
        'словник і генератор уже знають, і бракує лише джерела значень саме '
        'тут; нуль — що поля в нас немає взагалі.',
        '',
    ]
    gp = collections.Counter()
    for k, v in (scraped.get('global_params') or {}).items():
        gp[norm(k)] += v

    total_missing = 0
    summary = []
    details = []
    broken = []

    for cat in scraped['categories']:
        a = analyse(cat)
        n = a['n']
        total_missing += len(a['missing'])
        gap = gaps.get(str(cat['rz_id']), {})
        summary.append((cat['name'], cat['rz_id'], cat['our_offers'], n,
                        len(a['common']), len(a['missing']),
                        len(gap.get('missing', [])) if gap else None))
        # Порожній перетин сам собою нічого не означає: він буває і тому, що
        # конкурент у цій категорії не заповнює НІЧОГО. Ознакою зламаної
        # нормалізації назв він є лише тоді, коли поля в нього Є.
        if n and a['fields_seen'] and not a['common']:
            broken.append(cat['name'])

        details.append('')
        details.append(f'## {cat["name"]} (`rz_id={cat["rz_id"]}`)')
        details.append('')
        details.append(f'Наших офферів **{cat["our_offers"]}**; карток '
                       f'конкурента у вибірці **{n}** '
                       f'(у видачі категорії {cat["listing"]}).')
        if cat['empty']:
            details.append(f'Карток без жодної характеристики: {cat["empty"]}.')
        if cat['skipped']:
            details.append('Відкинуто при відборі: ' + ', '.join(
                f'{k} — {v}' for k, v in cat['skipped'].items()) + '.')
        details.append('')
        if not n:
            details.append('_Карток конкурента у цій категорії не знайдено._')
            continue

        if not a['fields_seen']:
            details.append('_Конкурент у цій категорії не заповнює **жодної** '
                           'характеристики — порівнювати нема з чим. Порожній '
                           'перетин тут пояснений, а не підозрілий._')
            continue

        if a['missing']:
            details.append('**Бракує нам:**')
            details.append('')
            details.append('| Характеристика | У нього карток | Rozetka | '
                           'У нас деінде | Схоже на нашу |')
            details.append('|---|---:|---|---:|---|')
            for m in a['missing']:
                rz = ('**фільтр**' if m['rz_filter'] else
                      ('так' if m['rz_known'] else '—'))
                details.append(f'| {m["name"]} | {m["cards"]}/{n} | {rz} | '
                               f'{gp.get(norm(m["name"]), 0)} | '
                               f'{m.get("near") or ""} |')
        else:
            details.append('**Бракує нам:** нічого — усі його консенсусні поля '
                           'у нас є.')
        details.append('')
        details.append('**Заповнюємо обидва** (позитивний контроль порівняння, '
                       f'{len(a["common"])}): ' +
                       (', '.join(c['name'] for c in a['common'][:20]) +
                        ('…' if len(a['common']) > 20 else '')
                        if a['common'] else '**жодного — підозра на зламану '
                                            'нормалізацію назв**'))
        if a['rare']:
            details.append('')
            details.append(f'**Поодинокі поля** (<{int(CONSENSUS * 100)}% його '
                           'карток, не консенсус): ' +
                           ', '.join(f'{r["name"]} ({r["cards"]}/{n})'
                                     for r in a['rare'][:15]) +
                           ('…' if len(a['rare']) > 15 else ''))

    has_gaps = any(s[6] is not None for s in summary)
    head = ('| Категорія | `rz_id` | наших офферів | його карток | '
            'спільних полів | бракує проти нього |')
    sep = '|---|---:|---:|---:|---:|---:|'
    if has_gaps:
        head += ' бракує за довідником |'
        sep += '---:|'
    lines.append(head)
    lines.append(sep)
    total_gap = 0
    for name, rz, ours_n, n, com, mis, gp_n in summary:
        row = f'| {name} | {rz} | {ours_n} | {n} | {com} | **{mis}** |'
        if has_gaps:
            row += f' {gp_n if gp_n is not None else "—"} |'
            total_gap += gp_n or 0
        lines.append(row)
    lines.append('')
    lines.append(f'Разом бракує назв (з повторами по категоріях): '
                 f'**{total_missing}**.')
    if has_gaps:
        lines.append('')
        lines.append(f'Для порівняння: **офіційний довідник Rozetka** каже, що '
                     f'в цих самих 10 категоріях нам бракує **{total_gap}** '
                     f'назв (`docs/rozetka_option_gaps.json`).')
        lines.append('Різниця не в тому, що довідник помиляється, а в тому, що '
                     'він перелічує все, що майданчик уміє, — разом із «EAN», '
                     '«Код УКТ ЗЕД»,')
        lines.append('«Кнопка передзамовлення» й габаритами пакування, яких не '
                     'заповнює ніхто. Живий продавець того самого товару '
                     f'заповнює з них **{total_missing}**.')
        lines.append('Тобто цей звіт — не ще один перелік прогалин, а '
                     'відсіювання вже наявного переліку до здійсненного.')
    lines.append('')
    lines.append('**Межі цього заміру — щоб «0» не читалось ширше, ніж воно '
                 'є.** Вибірка — перша сторінка видачі продавця в кожній')
    lines.append('категорії (до 60 позицій), з неї беруться перші картки до '
                 'заданого ліміту. «Бракує 0» означає «серед цих карток нічого')
    lines.append('нового не знайшлось», а не «конкурент нічого більше не '
                 'заповнює». Категорії — найбільші НАШІ, решта не міряна.')
    lines.append('Порівнюються назви, не заповненість: якщо назва в нас є хоч '
                 'в одному офері категорії, поле вважається наявним.')
    lines += details
    lines.append('')

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'→ {path}: {len(scraped["categories"])} категорій, '
          f'бракує {total_missing} назв')
    if broken:
        print('ПОМИЛКА: у категоріях ' + ', '.join(broken) +
              ' перетин переліків порожній — це ознака зламаної нормалізації '
              'назв, а не порожнього фіду.')
        return 1
    return 0


# ──────────────────────────── самоперевірка ─────────────────────────────────

def selftest() -> int:
    fails = []

    # нормалізація: три види апострофа й двокрапка мусять зійтись
    keys = {norm("Кількість кишень"), norm("Кількість кишень"),
            norm('Кількість  кишень:'), norm('КІЛЬКІСТЬ КИШЕНЬ')}
    if len(keys) != 1:
        fails.append(f'norm() не звів апострофи/регістр: {keys}')

    # різні назви НЕ мусять злипатись
    if norm('Тип біти') == norm('Тип бити'):
        fails.append('norm() злив «Тип біти» і «Тип бити»')

    def cat(fields_per_card, our):
        return {'rz_id': '1', 'name': 'test', 'our_offers': 1,
                'our_params': {k: 1 for k in our}, 'rz_options': {},
                'listing': len(fields_per_card), 'empty': 0, 'skipped': {},
                'cards': [{'id': str(i), 'title': '', 'fields': f}
                          for i, f in enumerate(fields_per_card)]}

    # 1. поле в усіх картках конкурента, у нас немає → бракує
    a = analyse(cat([['Вага', 'Матеріал'], ['Вага', 'Матеріал']], ['Вага']))
    if [m['name'] for m in a['missing']] != ['Матеріал']:
        fails.append(f'не знайдено очевидну прогалину: {a["missing"]}')
    if [c['name'] for c in a['common']] != ['Вага']:
        fails.append(f'спільне поле не впізнане: {a["common"]}')

    # 2. НЕГАТИВНИЙ випадок: у нас є все → прогалин бути не може
    a = analyse(cat([['Вага', 'Матеріал'], ['Вага', 'Матеріал']],
                    ['Вага', 'Матеріал']))
    if a['missing']:
        fails.append(f'вигадана прогалина на повному переліку: {a["missing"]}')

    # 3. поріг консенсусу: 1 картка з 3 — не консенсус
    a = analyse(cat([['Вага', 'Колір'], ['Вага'], ['Вага']], ['Вага']))
    if a['missing'] or [r['name'] for r in a['rare']] != ['Колір']:
        fails.append(f'поріг консенсусу не спрацював: {a}')

    # 4. апостроф не мусить давати хибну прогалину
    a = analyse(cat([['Кількість кишень'], ['Кількість кишень']],
                    ['Кількість кишень']))
    if a['missing']:
        fails.append(f'апостроф дав хибну прогалину: {a["missing"]}')

    # 5. поля майданчика (Гарантія) не рахуються прогалиною
    a = analyse(cat([['Гарантія', 'Вага'], ['Гарантія', 'Вага']], ['Вага']))
    if a['missing']:
        fails.append(f'«Гарантія» зарахована прогалиною: {a["missing"]}')

    for f in fails:
        print('ЗБІЙ:', f)
    print(f'самоперевірка: випадків 5 + 2 на norm(), збоїв {len(fails)}')
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dump-ours', metavar='OUT')
    ap.add_argument('--feed', default=FEED)
    ap.add_argument('--options', default=OPTIONS)
    ap.add_argument('--scrape', action='store_true')
    ap.add_argument('--ours', default='/tmp/toptul_ours.json')
    ap.add_argument('--raw', default='/tmp/toptul_competitor_raw.json')
    ap.add_argument('--from-raw', action='store_true',
                    help='перезібрати звіт із уже зібраного --raw')
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--sample', type=int, default=10)
    ap.add_argument('--pause', type=float, default=1.0)
    ap.add_argument('--out', default=REPORT)
    ap.add_argument('--gaps', default=os.path.join(BASE_DIR, 'docs',
                                                   'rozetka_option_gaps.json'))
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.dump_ours:
        dump_ours(a.feed, a.options, a.dump_ours)
        return 0
    if a.from_raw:
        with open(a.raw, encoding='utf-8') as f:
            scraped = json.load(f)
        if not scraped.get('global_params') and os.path.exists(a.ours):
            with open(a.ours, encoding='utf-8') as f:
                scraped['global_params'] = json.load(f).get('global_params', {})
        return write_report(scraped, a.out, load_gaps(a.gaps))
    if a.scrape:
        with open(a.ours, encoding='utf-8') as f:
            ours = json.load(f)
        scraped = scrape(ours, a.top, a.sample, a.pause)
        with open(a.raw, 'w', encoding='utf-8') as f:
            json.dump(scraped, f, ensure_ascii=False)
        print(f'сире зібране → {a.raw}')
        return write_report(scraped, a.out, load_gaps(a.gaps))
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
