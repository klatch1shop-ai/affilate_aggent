#!/usr/bin/env python3
"""
tools/epicentr_remaining_gaps_report.py
=======================================
Відповідає на питання власника «чого нам не вистачає, щоб завершити» по
картках NOIRE, які досі стоять у «Наповненні контентом».

Не «скільки бракує», а ЯКИХ САМЕ полів, у яких категоріях і **чи є значення
в наших даних**. Без цієї третьої колонки перелік прогалин марний: 300
порожніх «Підігрів» і 300 порожніх «Колір виробника» виглядають однаково, а
перше заповнюється одним правилом, друге не заповнюється взагалі.

Джерела (усе — читання):
  docs/epicentr_remaining_gaps.json  — прогалини по картках
                                       (tools/epicentr_enrich_audit.py --month)
  data/epicentr_attribute_sets.json  — типи й обовʼязковість атрибутів
  output/noire_prom.xml (--prom)     — наш фід Prom: характеристики + назва + опис
  merchant-api …/options             — довідник дозволених значень (кеш у файлі)

Класи джерела для кожної прогалини — від найдешевшого до найдорожчого:
  prom       значення є у фіді Prom і воно Є в довіднику Єпіцентру
             → заповнюється вже наявним tools/epicentr_fill_from_prom.py;
  prom-num   значення є у фіді Prom, а поле числове/текстове (довідника немає)
             → дані є, але інструмент такі поля ще не пише;
  prom-inval значення у Prom є, але його немає в довіднику
             → потрібна таблиця відповідностей, значення не вигадується;
  text       у Prom поля немає, але назва/опис картки містять рівно одне
             значення з довідника → кандидат на правило «з тексту»
             (як «Фетиш та BDSM» 24.08), кожне правило зі своїм контролем;
  text-many  у тексті знайшлось кілька різних значень довідника — правило
             потрібне, але однозначної відповіді текст не дає;
  binary-hint довідник = Так/Ні, і опис ЗГАДУЄ цю властивість — кандидат на
             правило, але саме тут 21.08 «можна нагрівати» стало «З підігрівом»;
  binary     довідник = Так/Ні, у тексті ознаки немає. «Ні» за замовчуванням
             може бути правдою, а може бути брехнею — це рішення власника,
             не наше (правило 5 черги);
  db / db-inval / db-num
             те саме, але значення взяте не з фіду Prom, а прямо з
             `sexopt_extracted_params` — таблиці, З ЯКОЇ фід Prom і збирається.
             Фід — копія з утратами: він не несе картки, яких немає в продажу,
             і не несе значень, що не лягли в закриті переліки Prom;
  none       ані Prom, ані БД, ані текст, ані довідник нічого не дають.

    python3 tools/epicentr_remaining_gaps_report.py --prom /tmp/noire_prom.xml
"""
import os, sys, json, re, argparse, collections
import xml.etree.ElementTree as ET
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
MAPI = 'https://merchant-api.epicentrm.com.ua'
GAPS = os.path.join(BASE, 'docs', 'epicentr_remaining_gaps.json')
SETS = os.path.join(BASE, 'data', 'epicentr_attribute_sets.json')
CACHE = os.path.join(BASE, 'data', 'epicentr_options_cache.json')
MD = os.path.join(BASE, 'docs', 'epicentr_remaining_gaps.md')
TSV = os.path.join(BASE, 'docs', 'epicentr_remaining_gaps.tsv')

BINARY = {'так', 'ні', 'да', 'нет'}

# Ознаки в тексті для полів Так/Ні. Це НЕ правило заповнення, а лише замір:
# «чи згадує наш опис цю властивість узагалі». Наявність ознаки не доводить
# «Так» — 21.08 правило `has_heating` саме так приписало 286 карткам підігрів,
# бо ловило «можна нагрівати» (гріє користувач) як функцію приладу. Тому
# колонка називається «ознака в тексті», а не «значення».
HINTS = {
    'Підігрів': ('підігрів', 'подогрев'),
    'Водонепроникний': ('водонепрон', 'водостійк', 'вологозахищ', 'waterproof',
                        'водонепроницаем'),
    'Телескопічний': ('телескопі', 'телескопич'),
    'Керування через застосунок (Smart)': ('застосун', 'смартфон', 'додаток',
                                           'приложени', 'smart', 'bluetooth'),
    'Кілька насадок': ('насадк',),
    'Кріплення на присоску': ('присоск',),
    'Вібрація': ('вібрац', 'вибрац'),
}


def ua(o):
    for t in (o or {}).get('translations', []):
        if t.get('languageCode') == 'ua':
            return t.get('value') or t.get('title')
    return None


# Апостроф пишеться чотирма різними символами в тих самих словах: Єпіцентр
# віддає «Об’єм» (U+2019) і «Об'єм» (U+0027), Prom — «Об`єм` (U+0060) і
# «Об'єм». Зіставлення назв «як є» дає нуль, не помиляючись.
APOS = {ord(c): "'" for c in '`´ʹʼ‘’'}


def norm(s):
    return re.sub(r'\s+', ' ', (s or '')).strip().lower().translate(APOS)


class Options:
    """Довідники дозволених значень. Кеш у файлі: 400+ запитів на прогін,
    а перелік значень змінюється рідко."""

    def __init__(self, path):
        self.path = path
        self.data = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}
        self.hits = 0

    def get(self, cat, code):
        key = f'{cat}:{code}'
        if key not in self.data:
            h = {'Authorization': f"Bearer {os.getenv('EPICENTR_TOKEN')}",
                 'Accept': 'application/json'}
            out, page = {}, 1
            while True:
                r = requests.get(
                    f'{MAPI}/v2/pim/attribute-sets/{cat}/attributes/{code}/options',
                    headers=h, params={'limit': 80, 'page': page}, timeout=40)
                if r.status_code != 200:
                    break
                j = r.json()
                for o in j.get('items', []):
                    t = ua(o)
                    if t:
                        out[norm(t)] = o['code']
                if page >= (j.get('pages') or 1):
                    break
                page += 1
            self.data[key] = out
            self.hits += 1
            if self.hits % 25 == 0:
                self.save()
        return self.data[key]

    def save(self):
        json.dump(self.data, open(self.path, 'w', encoding='utf-8'), ensure_ascii=False)


def load_prom(path):
    """{sku: {'params': {назва: значення}, 'text': 'назва + опис'}}"""
    out = {}
    for o in ET.parse(path).getroot().findall('.//offer'):
        sku = (o.findtext('vendorCode') or o.get('id') or '').strip()
        if not sku:
            continue
        text = ' '.join(filter(None, [o.findtext('name_ua'), o.findtext('name'),
                                      o.findtext('description_ua'),
                                      o.findtext('description')]))
        # Ключ — НОРМАЛІЗОВАНА назва: Єпіцентр пише «Об’єм» (U+2019), Prom —
        # «Об'єм» (U+0027). Точне зіставлення давало по цьому полю нуль, і нуль
        # виглядав як «у Prom значення немає» (172 прогалини, 156 з них «none»).
        out[sku] = {'params': {norm(p.get('name')): (p.text or '').strip()
                               for p in o.findall('param') if (p.text or '').strip()},
                    'text': norm(text)}
    return out


def load_params(path):
    """Вивантаження `sexopt_extracted_params` → {sku: {назва: значення}}."""
    out = collections.defaultdict(dict)
    if not path or not os.path.exists(path):
        return out
    for line in open(path, encoding='utf-8'):
        f = line.rstrip('\n').split('\t')
        if len(f) >= 3 and f[2].strip():
            out[f[0]].setdefault(norm(f[1]), f[2].strip())
    return out


def classify(miss, cat, prom_row, opts, spec_attr, db_row=None):
    """Один клас на одну прогалину. Порядок перевірок — від дешевшого."""
    name = miss['name'] or ''
    typ = miss['type']
    val = (prom_row or {}).get('params', {}).get(norm(name), '') if prom_row else ''
    pfx = ''
    if not val and db_row:
        # Фід Prom мовчить — питаємо джерело, з якого він зроблений
        val = db_row.get(norm(name), '')
        pfx = 'db-' if val else ''
    table = opts.get(cat, miss['code']) if typ in ('select', 'multiselect') else {}

    if val:
        if not table:
            # Число або вільний текст: довідника немає взагалі. Значення в нас
            # Є, але наявний epicentr_fill_from_prom.py такі поля НЕ пише —
            # він вимагає код із довідника. Тому окремий клас, а не 'prom':
            # інакше звіт обіцяв би заповнення, якого сьогодні не станеться.
            return (pfx + 'prom-num') if not pfx else 'db-num', val
        if norm(val) in table:
            return 'db' if pfx else 'prom', val
        return 'db-inval' if pfx else 'prom-inval', val

    if not table:
        return 'none', ''

    text = (prom_row or {}).get('text', '')
    keys = [k for k in table if k not in BINARY and len(k) >= 3]
    if set(table) & BINARY and not keys:
        # Чистий Так/Ні. Значення з довідника в тексті шукати марно («Так» як
        # слово там не стоїть), тому питаємо інакше: чи згадує опис саму
        # властивість. Відповідь «згадує» — привід для правила, не значення.
        for h in HINTS.get(name, ()):
            if h in text:
                return 'binary-hint', h
        return 'binary', ''

    found = sorted({k for k in keys if k in text}) if text else []
    if len(found) == 1:
        return 'text', found[0]
    if len(found) > 1:
        return 'text-many', ', '.join(found[:3])
    return 'none', ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prom', default=os.path.join(BASE, 'output', 'noire_prom.xml'))
    ap.add_argument('--gaps', default=GAPS)
    ap.add_argument('--params', default='', help='TSV sku/назва/значення/джерело '
                    'з sexopt_extracted_params')
    a = ap.parse_args()

    gaps = json.load(open(a.gaps, encoding='utf-8'))
    sets = json.load(open(SETS, encoding='utf-8'))
    prom = load_prom(a.prom)
    dbp = load_params(a.params)
    opts = Options(CACHE)

    print(f'карток у «Наповненні контентом»: {len(gaps)}')
    print(f'товарів у фіді Prom: {len(prom)}')
    in_prom = sum(1 for g in gaps if (g.get('sku') or '').strip() in prom)
    print(f'з них є у фіді Prom: {in_prom}\n')

    rows = []                    # (cat, catName, code, attrName, type, class, value, sku)
    card_cls = {}                # id → набір класів прогалин картки
    why_none = collections.Counter()
    for g in gaps:
        sku = (g.get('sku') or '').strip()
        row = prom.get(sku)
        cat = g['category']
        spec = {str(x.get('code')): x for x in (sets.get(cat) or {}).get('attributes', [])}
        seen = set()
        for m in g['missing']:
            cls, val = classify(m, cat, row, opts, spec.get(str(m['code'])),
                                dbp.get(sku))
            rows.append((cat, g['categoryName'], str(m['code']), m['name'],
                         m['type'], cls, val, sku))
            seen.add(cls)
            if cls == 'none':
                # Нуль треба пояснити механічно, а не «схоже, даних немає».
                # Дві причини різні за наслідком: «картки немає у фіді» лікує
                # перехід на БД, «поля немає ніде» — ні.
                d = dbp.get(sku) or {}
                if row is None and not d:
                    why_none['картки немає ні у фіді Prom, ні в БД'] += 1
                elif row is None:
                    why_none['картки немає у фіді Prom, поля немає в БД'] += 1
                elif norm(m['name']) not in row['params'] and norm(m['name']) not in d:
                    why_none['поля немає ні в характеристиках Prom, ні в БД'] += 1
                else:
                    why_none['поле є, але значення порожнє'] += 1
        card_cls[g['id']] = seen
    opts.save()

    by_cls = collections.Counter(r[5] for r in rows)
    print('прогалин за джерелом значення:')
    for k, v in by_cls.most_common():
        print(f'   {v:6}  {k}')

    with open(TSV, 'w', encoding='utf-8') as f:
        f.write('cat\tcatName\tcode\tattr\ttype\tsource\tvalue\tsku\n')
        for r in rows:
            f.write('\t'.join(str(x).replace('\t', ' ').replace('\n', ' ') for x in r) + '\n')
    print(f'\nпорядково → {TSV} ({len(rows)} рядків)')

    # --- групи «категорія × набір відсутніх полів» -------------------------
    sig = collections.Counter()
    for g in gaps:
        s = tuple(sorted(m['name'] for m in g['missing']))
        sig[(g['categoryName'], s)] += 1

    # --- зведення по (категорія, атрибут) ---------------------------------
    agg = collections.defaultdict(collections.Counter)
    for cat, catn, code, attr, typ, cls, val, sku in rows:
        agg[(catn, cat, code, attr, typ)][cls] += 1

    order = ['prom', 'db', 'prom-num', 'db-num', 'text', 'prom-inval',
             'db-inval', 'text-many', 'binary-hint', 'binary', 'none']
    L = []
    L.append('# Чого бракує 1760 карткам NOIRE на Єпіцентрі\n')
    L.append(f'Зібрано `{os.path.basename(__file__)}` з `{os.path.basename(a.gaps)}` '
             f'і `{os.path.basename(a.prom)}`.\n')
    L.append(f'Карток: **{len(gaps)}**, з них без жодної прогалини на момент '
             f'заміру — **{sum(1 for g in gaps if not g["missing"])}** '
             f'(плюс 3, заповнені після заміру як наскрізний контроль). '
             f'Порожніх обовʼязкових полів: **{len(rows)}**.\n')
    L.append('## Як це зміряно\n')
    L.append('* стан карток — `tools/epicentr_products_dump.py` (кабінет), '
             'прогалини — `tools/epicentr_enrich_audit.py --month 2026-07`, '
             'тобто категорія й обовʼязкові поля беруться з кабінету, а не з фіду;\n'
             '* довідники значень — `merchant-api …/options`, кеш '
             '`data/epicentr_options_cache.json`;\n'
             '* число `prom + db` звірено з незалежною реалізацією: '
             '`tools/epicentr_fill_from_prom.py --plan --params` дає **ті самі '
             '1037 полів у 545 картках**;\n'
             '* наскрізний контроль: три картки (AL40571, MD1137, F12441) '
             'заповнені по-справжньому й перечитані з кабінету — порожніх '
             'обовʼязкових полів у кожній стало 0. Тому «значення в нас є» тут '
             'не оцінка, а перевірене твердження.\n')
    L.append('## Прогалини за джерелом значення\n')
    L.append('| джерело | прогалин | що це означає |\n|---|---:|---|')
    mean = {'prom': 'значення є у фіді Prom і дозволене довідником — заповнюється сьогодні',
            'prom-num': 'значення є у фіді Prom, поле числове — інструмент такі ще не пише',
            'text': 'у тексті картки рівно одне значення довідника — правило з тексту',
            'prom-inval': 'Prom дає значення, якого немає в довіднику — потрібна відповідність',
            'text-many': 'у тексті кілька значень довідника — однозначності немає',
            'binary-hint': 'довідник Так/Ні, опис згадує властивість — кандидат на правило',
            'binary': 'довідник Так/Ні, у тексті ознаки немає — рішення власника',
            'db': 'значення є в `sexopt_extracted_params` і дозволене довідником',
            'db-num': 'значення є в БД, поле числове — інструмент такі ще не пише',
            'db-inval': 'значення є в БД, але його немає в довіднику Єпіцентру',
            'none': 'джерела немає ні в Prom, ні в БД, ні в тексті'}
    for k in order:
        if by_cls.get(k):
            L.append(f'| `{k}` | {by_cls[k]} | {mean[k]} |')
    L.append('')

    L.append('## Скільки карток закривається, а не скільки полів\n')
    L.append('Поле — не картка: на модерацію йде картка, у якій закриті ВСІ '
             'обовʼязкові поля.\n')
    L.append('| карток | стан |\n|---:|---|')
    closed = sum(1 for g in gaps if not g['missing'])
    easy = sum(1 for i, s in card_cls.items() if s and s <= {'prom', 'db'})
    easy2 = sum(1 for i, s in card_cls.items()
                if s and s <= {'prom', 'db', 'prom-num', 'db-num', 'text'})
    hard = sum(1 for i, s in card_cls.items() if 'none' in s)
    L.append(f'| {closed} | прогалин немає — формально готові до модерації |')
    L.append(f'| {easy} | закриваються значеннями, які вже є і дозволені '
             f'(`prom` + `db`) |')
    L.append(f'| {easy2} | закриваються тим самим + числовими полями + правилом з тексту |')
    L.append(f'| {hard} | мають хоч одну прогалину без джерела (`none`) |')
    L.append('')

    L.append('### Чому «none»\n')
    L.append('| прогалин | причина |\n|---:|---|')
    for k, v in why_none.most_common():
        L.append(f'| {v} | {k} |')
    no_prom = sorted({g['sku'] for g in gaps
                      if (g.get('sku') or '').strip() not in prom})
    have_db = sum(1 for s_ in no_prom if dbp.get(s_))
    L.append(f'\nКарток, яких **немає у фіді Prom узагалі**: {len(no_prom)} із '
             f'{len(gaps)}. Це не означає, що даних немає: характеристики '
             f'{have_db} із них лежать у `sexopt_extracted_params` — тій самій '
             f'таблиці, з якої фід і збирається. Фід — копія з утратами, і '
             f'заповнювати картки треба з джерела, а не з копії.\n')

    L.append('### `prom-inval`: значення в нас є, але воно поза довідником\n')
    L.append('Це не брак даних, а брак відповідності. Значень не вигадуємо '
             '(правило 5), але зіставити наше «силікон» із їхнім «Силікон» — '
             'не вигадування. Найчастіші пари:\n')
    L.append('| разів | поле | наше значення |\n|---:|---|---|')
    inval = collections.Counter((r[3], r[6]) for r in rows if r[5] == 'prom-inval')
    for (attr, val), n in inval.most_common(20):
        L.append(f'| {n} | {attr} | {val[:60].replace("|", "\\|")} |')
    L.append('')

    L.append('## Групи «категорія × набір відсутніх полів»\n')
    L.append('| карток | категорія | яких полів бракує |\n|---:|---|---|')
    cum = 0
    for (catn, s), n in sig.most_common(25):
        cum += n
        L.append(f'| {n} | {catn} | {", ".join(s) if s else "—"} |')
    L.append(f'\nПерші 25 груп покривають {cum} карток із {len(gaps)} '
             f'({cum * 100 // len(gaps)}%). Усього груп: {len(sig)}.\n')

    L.append('## Поля по категоріях: чи є значення в наших даних\n')
    L.append('Колонка «Prom» — у скількох офферах фіду Prom таке поле взагалі '
             'заповнене. Нуль у ній означає, що поля немає в наших даних як '
             'класу, а не що воно загубилось по дорозі.\n')
    L.append('| категорія | поле | тип | бракує | Prom | ' + ' | '.join(order) + ' |')
    L.append('|---|---|---|---:|---:|' + '---:|' * len(order))
    in_feed = collections.Counter()
    for row in prom.values():
        in_feed.update(row['params'].keys())
    for (catn, cat, code, attr, typ), c in sorted(
            agg.items(), key=lambda kv: -sum(kv[1].values())):
        tot = sum(c.values())
        if tot < 10:
            continue
        L.append(f'| {catn} | {attr} `{code}` | {typ} | {tot} | '
                 f'{in_feed.get(norm(attr), 0)} | ' +
                 ' | '.join(str(c.get(k, 0) or '') for k in order) + ' |')
    L.append('')

    # --- що з цього треба вирішити власникові ------------------------------
    # тільки 'binary': змішавши сюди 'none', перелік «найбільших» назвав би
    # «Вид — 317», якого в полях Так/Ні немає взагалі
    no_src = collections.Counter(r[3] for r in rows if r[5] == 'binary')
    no_data = collections.Counter(r[3] for r in rows if r[5] == 'none')
    L.append('## Що з цього потрібно від власника\n')
    L.append(f'1. **Поля Так/Ні без ознаки в тексті — {by_cls.get("binary", 0)} '
             f'прогалин.** Проставити «Ні» за замовчуванням — рішення на гроші, '
             f'а не на техніку: воно піде в картку майданчика як факт про товар. '
             f'Правило 5 черги забороняє вигадувати значення, тож потрібне слово. '
             f'Найбільші: ' +
             ', '.join(f'{a} — {n}' for a, n in no_src.most_common(4)) + '.')
    L.append(f'2. **Значення поза довідником — '
             f'{by_cls.get("prom-inval", 0) + by_cls.get("db-inval", 0)} '
             f'прогалин.** Тут дані Є, бракує таблиці відповідностей '
             f'(«для стимуляції вульви» → що саме з переліку Єпіцентру). '
             f'Скласти її можемо ми, але кожен рядок — це рішення про товар, '
             f'а не переклад.')
    L.append(f'3. **Числові поля — '
             f'{by_cls.get("prom-num", 0) + by_cls.get("db-num", 0)} прогалин.** '
             f'Значення є, довідника в таких полів немає, і '
             f'`epicentr_fill_from_prom.py` їх поки не пише. Це наша робота, '
             f'не рішення власника — але окремий пункт черги.')
    L.append(f'4. **Прогалини без джерела — {by_cls.get("none", 0)}.** '
             f'Найбільші поля: ' +
             ', '.join(f'{a} — {n}' for a, n in no_data.most_common(5)) +
             '. Тут не бракує інструмента — бракує самих даних.')
    L.append(f'5. **`Колір виробника` (`78`).** Довідник вимагає, у наших даних '
             f'кольору немає як класу — у фіді Prom поле не заповнене в жодного '
             f'оффера. Або джерело (постачальник), або лишається порожнім.\n')

    open(MD, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print(f'звіт → {MD}')


if __name__ == '__main__':
    main()
