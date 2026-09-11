#!/usr/bin/env python3
"""Мішане написання: латинські літери всередині кириличних слів.

У фіді постачальника TOPTUL частина слів набрана двома абетками одночасно —
`дoзвoляє`, `нaпpугa`, `Пoвeрбaнк`, `CTAHДAPT`. Літери `o`, `a`, `p`, `c`,
`e`, `x`, `y` й великі `A B C E H K M O P T X` виглядають однаково в латиниці
й кирилиці, тож око дефекту не бачить, а машина бачить інше слово.

Наслідок подвійний і обидва рази дорогий:

  * **Rozetka не знайде такий товар пошуком.** `дoзвoляє` з латинськими `o`
    не збігається з `дозволяє` ні в пошуку майданчика, ні в наших фільтрах;
  * **наша ознака мови бреше.** У `cили` (латинська `c`) кириличний залишок —
    `или`, і `uk_lexicon` чесно називає його російським. Саме звідти останні
    6 «російських вживань» у фіді після перекладу 01.09.2026, і перекладом
    вони не лікуються: слово вже українське, зіпсоване лише написання.

## Рішення береться на СЛОВНИКУ, а не на більшості літер

Спокуса — «переводити меншість у більшість». Замір це відкидає: `CTAHДAPT`
має 7 латинських літер проти однієї кириличної `Д`, і правильна відповідь —
кирилиця; `МхF` має дві кириличні проти однієї латинської `F`, і правильна
відповідь — латиниця. Тому напрямок визначається тим, який варіант узагалі
можливий, а неоднозначність розводить український словник:

  1. токен мусить містити ОБИДВІ абетки — інакше не чіпаємо. `TOPTUL`,
     `GAAI0802`, `Hм` суто латинські або суто кириличні й лишаються як є;
  2. `→ кирилиця` можлива, лише якщо в токені немає латинських літер БЕЗ
     кириличного двійника (`b d f g j l n q r s u v w z`, великі `D F G J L
     N Q R S U V W Z`);
  3. `→ латиниця` можлива, лише якщо немає кириличних без латинського
     двійника (`б в г д ж з и й л п т ф ц ч ш щ ь ю я є ї` тощо);
  4. можливі обидві (усі літери — двійники, `Hі`, `Tуpe`, `pecуpc`) →
     виграє кирилиця, ЯКЩО результат є в словнику українських словоформ
     (`Ні`, `ресурс`), інакше латиниця (`Type`, `AAA`, `TCM`);
  5. жодна не можлива (`тORIN`, `Беzdротова`) → лишаємо й доповідаємо.

## Запобіжник на довгий кириличний хвіст

Пункт 3 сам по собі зіпсував би `Vрес` («V ресивера = 150 л», 20 вживань):
`V` кириличного двійника не має, тож єдиний можливий напрямок — латиниця, і
`рес` перетворилось би на `pec`. Це не зіпсоване написання, а законна суміш —
латинська позначка плюс українське скорочення.

Відрізнити їх правилом про більшість не вийшло (`МхF` — контрприклад), тому
стоїть запобіжник: **перетворення в латиницю не робиться, якщо суцільний
кириличний відрізок довший за `MAX_CYR_RUN`.** Один зіпсований символ у
латинському коді (`GIZMATIС`, `Batterу`, `LVМP`) дає відрізок 1–2; ціле
українське слово — 3 і більше. На всьому фіді запобіжник спрацював рівно на
`Vрес` і на жодному іншому з 16 випадків.

Порогові значення тут — не окомір, а замір по фіду; перш ніж рухати, див.
`--audit`, який друкує кожне перетворення з напрямком.

    python3 tools/homoglyph.py --selftest
    python3 tools/homoglyph.py --audit output/toptul_rozetka.xml
    python3 tools/homoglyph.py --audit output/toptul_rozetka.xml --report FILE
"""
import argparse
import collections
import os
import re
import sys
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))

import uk_lexicon as LEX  # noqa: E402

# Пари, які в звичайних шрифтах не розрізнити оком. Малих пар менше за
# великі: `т`/`t`, `н`/`h`, `в`/`b` схожі лише у великому написанні, тому
# `т` у `тORIN` лишається кириличною-без-двійника — і саме тому той токен
# чесно потрапляє в «нерозвʼязні», а не перетворюється навмання.
LAT2CYR = {
    'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'I': 'І', 'K': 'К',
    'M': 'М', 'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х', 'Y': 'У',
    'a': 'а', 'c': 'с', 'e': 'е', 'i': 'і', 'o': 'о', 'p': 'р', 'x': 'х',
    'y': 'у',
}
CYR2LAT = {v: k for k, v in LAT2CYR.items()}

_LAT = re.compile(r'[A-Za-z]')
_CYR = re.compile(r'[Ѐ-ӿ]')
# Токен — суцільний відрізок літер обох абеток. Цифри й розділові знаки в
# нього не входять свідомо: артикул `GAAI0802` розпадається на `GAAI` (суто
# латинський, не чіпаємо) і число, а `1/2"` не є токеном узагалі.
TOKEN = re.compile(r'[A-Za-zЀ-ӿ]+')

# Довший суцільний кириличний відрізок у бік латиниці не переводиться —
# див. розбір `Vрес` у шапці модуля.
MAX_CYR_RUN = 2

KEEP = 'keep'       # лишити як є
TO_CYR = 'cyr'
TO_LAT = 'lat'


def is_mixed(tok: str) -> bool:
    return bool(_LAT.search(tok)) and bool(_CYR.search(tok))


def _longest_cyr_run(tok: str) -> int:
    return max((len(m) for m in re.findall(r'[Ѐ-ӿ]+', tok)),
               default=0)


def fix_token(tok: str) -> tuple:
    """(новий токен, напрямок, причина). Напрямок `keep` — не змінено."""
    if not is_mixed(tok):
        return tok, KEEP, 'не мішаний'

    lat_orphan = [c for c in tok if _LAT.match(c) and c not in LAT2CYR]
    cyr_orphan = [c for c in tok if _CYR.match(c) and c not in CYR2LAT]

    to_cyr = ''.join(LAT2CYR.get(c, c) for c in tok) if not lat_orphan else None
    to_lat = ''.join(CYR2LAT.get(c, c) for c in tok) if not cyr_orphan else None

    if to_cyr and to_lat:
        # Усі літери — двійники, напрямок з написання не видно. Вирішує
        # словник: `Hі` → `Ні` (є в словнику), `Tуpe` → `Type` (немає).
        if LEX.norm(to_cyr) in _uk_forms():
            return to_cyr, TO_CYR, 'обидва напрямки; кирилиця є в словнику'
        return to_lat, TO_LAT, 'обидва напрямки; кирилиці немає в словнику'
    if to_cyr:
        return to_cyr, TO_CYR, 'латинські літери в кириличному слові'
    if to_lat:
        run = _longest_cyr_run(tok)
        if run > MAX_CYR_RUN:
            return tok, KEEP, (f'кириличний відрізок {run} літер — схоже на '
                               f'законну суміш, не латинізуємо')
        return to_lat, TO_LAT, 'кириличні літери в латинському коді'
    return tok, KEEP, 'обидві абетки мають літери без двійника'


def _uk_forms() -> set:
    LEX._load()
    return LEX._uk


# ── Кирилична «З» на місці цифри 3 ─────────────────────────────────────────
# Другий клас того самого дефекту, і найбільший із залишків заміру 01.09:
# `X-4З1 PROЗ SE` замість `X-431 PRO3 SE`, `QCЗ.0`, `З60 хв`, `1З мм`,
# `ЗЗ8x2З7хЗ12 мм`. Правило про «латинську літеру в кириличному слові» його
# не бачить за побудовою: `З60` — суто кириличний токен, мішаним він не є.
#
# Заміну «більшість вирішує» тут теж застосувати не можна, і контрприклади
# знову справжні, з фіду:
#
#   * `ЗМЗ406` — двигун ЗМЗ-406, `З` кирилична законно, і в токені є цифри;
#   * `РАЗВ7.01`, `РАЗВ1719В` — артикули розвальцьовок, теж законні;
#   * `з`/`З` як прийменник — 20 080 вживань у фіді, тобто ціна хибної
#     тривоги тут найвища з усіх, що траплялись.
#
# Тому вирішує НЕ токен цілком, а сусідство кожної окремої `З`:
#
#   1. у токені мусить бути цифра або латинська літера — інакше це слово
#      (`Зчеплення`) або прийменник, і ми не чіпаємо;
#   2. попередня літера НЕ кирилична — саме це рятує `ЗМЗ406` (друга `З`
#      стоїть після `М`) і всі `РАЗВ*` (після `А`). Виняток один: кириличний
#      `х` між цифрами — це роздільник розмірів (`456хЗ72x155`), а не буква
#      слова, і після нього `З` цілком може бути цифрою;
#   3. і хоч одне з трьох: кирилиці в токені більше немає взагалі
#      (`PROЗ`, `З60`), або сусідня цифра стоїть поруч (`1Змм`, `T8З502`),
#      або поруч роздільник розмірів.
#
# Прохід іде зліва направо ПО ВЖЕ ЗМІНЕНОМУ рядку: у `4ЗЗMHz` друга `З`
# спирається на першу, яка на той момент уже стала цифрою.
#
# Правило перевірено не на здогадці: сухий прогін по фіду (5783 оффери) дав
# 125 різних замін у 524 вживаннях, і всі 125 переглянуто очима — жодного
# українського слова, жодного артикула `РАЗВ*`, `ЗМЗ406` недоторканий.
ALNUM = re.compile(r'[A-Za-zЀ-ӿ0-9]+')
_DIG = re.compile(r'[0-9]')
DIM_SEP = 'хХ'      # кириличний «х» як знак множення в розмірах
TO_DIG = 'dig'


def fix_digit_token(tok: str) -> tuple:
    """(новий токен, напрямок, причина) для `З`, що насправді цифра 3."""
    if 'З' not in tok and 'з' not in tok:
        return tok, KEEP, 'немає «З»'
    if not (_DIG.search(tok) or _LAT.search(tok)):
        return tok, KEEP, 'ні цифри, ні латиниці — це слово, не код'
    # Запобіжник, знайдений на СИРОМУ фіді постачальника, а не в готовому.
    # У сирому тексті слова набрані навпіл латиницею, тож `зa` (латинська
    # `a`) має і кирилицю, і латиницю — і без цієї перевірки ставало б `3a`
    # у 120 вживаннях, `Зa` — у 20, `poз` — у 22, а бренд `BAЗ` (латинські
    # `B`, `A`) — `BA3`. У конвеєрі літерний прохід іде першим і всі чотири
    # знімає, але спиратись на порядок не можна: правило мусить бути
    # безпечним і на сирому рядку, бо саме так його викличе наступний
    # інструмент.
    if not _DIG.search(tok) and fix_token(tok)[1] == TO_CYR:
        return tok, KEEP, 'літерне правило впізнало кириличне слово'
    only_z = not (set(c for c in tok if _CYR.match(c)) - set('Зз'))
    sep_ok = not (set(c for c in tok if _CYR.match(c)) - set('Зз' + DIM_SEP))
    out = list(tok)
    for i, ch in enumerate(tok):
        if ch not in 'Зз':
            continue
        prev = out[i - 1] if i else ''
        prev2 = out[i - 2] if i >= 2 else ''
        nxt = tok[i + 1] if i + 1 < len(tok) else ''
        if prev and _CYR.match(prev):
            # Після кириличної літери — це буква слова чи артикула. Єдиний
            # виняток: `х` між цифрами, тобто розмір `167x10Зх50`.
            if not (prev in DIM_SEP and prev2.isdigit()):
                continue
        if (only_z or (prev and prev.isdigit()) or nxt.isdigit()
                or (sep_ok and (prev in DIM_SEP or nxt in DIM_SEP))):
            out[i] = '3'
    new = ''.join(out)
    if new == tok:
        return tok, KEEP, 'кирилична «З» стоїть як буква'
    return new, TO_DIG, 'кирилична «З» на місці цифри 3'


def fix_digits(text: str) -> tuple:
    """(виправлений текст, Counter{(було, стало, напрямок): скільки})."""
    hits = collections.Counter()
    if not text or ('З' not in text and 'з' not in text):
        return text, hits

    def sub(m):
        tok = m.group(0)
        new, direction, _ = fix_digit_token(tok)
        if new != tok:
            hits[(tok, new, direction)] += 1
        return new

    return ALNUM.sub(sub, text), hits


def fix_text(text: str) -> tuple:
    """(виправлений текст, Counter{(було, стало, напрямок): скільки}).

    Два проходи різними токенізаторами: літерний знімає мішане написання,
    алфавітно-цифровий — кириличну `З` на місці цифри. Порядок саме такий,
    бо перший може створити роботу другому (`PROЗ` лишається мішаним і після
    латинізації, а `З` у ньому стає видимою лише як цифра), а не навпаки.
    """
    hits = collections.Counter()
    if not text:
        return text, hits
    if is_mixed(text):
        def sub(m):
            tok = m.group(0)
            new, direction, _ = fix_token(tok)
            if new != tok:
                hits[(tok, new, direction)] += 1
            return new

        text = TOKEN.sub(sub, text)
    text, dig = fix_digits(text)
    hits.update(dig)
    return text, hits


def leftovers(text: str) -> list:
    """Мішані токени, які лишились після виправлення, — для звіту власникові."""
    out = []
    for tok in TOKEN.findall(text or ''):
        if not is_mixed(tok):
            continue
        new, direction, why = fix_token(tok)
        if direction != KEEP:
            continue
        # `PROЗ` літерним правилом нерозвʼязний, але цифровим — розвʼязний.
        # Без цієї перевірки перелік «лишилось» називав би токени, яких у
        # готовому тексті вже немає, і замір розійшовся б із фідом.
        if fix_digit_token(tok)[1] != KEEP:
            continue
        out.append((tok, why))
    return out


# ── Позитивний контроль ────────────────────────────────────────────────────
# Кожен рядок узятий із ФІДУ, а не вигаданий: `Vрес` і `МхF` — це ті самі два
# контрприклади, через які правило «меншість у більшість» відкинуто.
SELFTEST_FIX = [
    ('дoзвoляє', 'дозволяє'),      # три латинські `o` в українському слові
    ('нaпpугa', 'напруга'),
    ('cили', 'сили'),              # саме воно давало «російське» `или`
    ('CTAHДAPT', 'СТАНДАРТ'),      # 7 латинських проти однієї `Д`
    ('Cтенд', 'Стенд'),
    ('Сiч', 'Січ'),                # «Мотор Січ»
    ('Пoвeрбaнк', 'Повербанк'),
    ('GIZMATIС', 'GIZMATIC'),      # кирилична `С` у хвості артикула
    ('Batterу', 'Battery'),
    ('molуbdenum', 'molybdenum'),
    ('LVМP', 'LVMP'),
    ('МхF', 'MxF'),                # 2 кириличні проти 1 латинської — і все ж латиниця
    ('хSL', 'xSL'),
    ('Hі', 'Ні'),                  # обидва напрямки, виграє словник
    ('Tуpe', 'Type'),              # обидва напрямки, словник мовчить
    ('pecуpc', 'ресурс'),
    ('Уcі', 'Усі'),
]
SELFTEST_KEEP = [
    'TOPTUL', 'GAAI0802', 'Нм', 'Toyota', 'викрутка', 'HHCM0052',   # не мішані
    'Vрес',          # запобіжник: `рес` — скорочення, не зіпсоване написання
    'тORIN',         # `т` і `R`/`N` двійників не мають
    'Беzdротова',    # те саме з `z`/`d`
    'PROЗ',          # кирилична `З` замість цифри 3 — інше правило, нижче
]

# Цифрове правило. Кожен рядок — із фіду, а не вигаданий.
SELFTEST_DIG = [
    ('PROЗ', 'PRO3'),              # X-431 PRO3 SE, 34 вживання
    ('QCЗ', 'QC3'),                # QC3.0, 32 вживання
    ('X4З1', 'X431'),
    ('З60', '360'),                # «Час зарядки від розетки: 360 хв»
    ('1З', '13'),                  # «13 мм» у переліку розмірів
    ('4ЗЗMHz', '433MHz'),          # дві поспіль: друга спирається на першу
    ('1Змм', '13мм'),              # кирилиця «мм» поруч, а `З` усе одно цифра
    ('R12З4yf', 'R1234yf'),
    ('T8З502', 'T83502'),
    ('З00kgf', '300kgf'),
    ('ЗЗ8x2З7хЗ12', '338x237х312'),  # розмір із кириличним «х»-роздільником
    ('Зх250', '3х250'),
    ('SDCAЗ001', 'SDCA3001'),
    ('vЗ', 'v3'),
]
SELFTEST_DIG_KEEP = [
    'ЗМЗ406',        # двигун ЗМЗ-406: `З` кирилична законно, і поруч цифри
    'РАЗВ7',         # артикул розвальцьовки
    'РАЗВ1719В',
    'РАЗВ25ЦЕЛ',
    'ТЗ0',           # `T30`, набране двома кириличними — правилом не видно
    'З',             # прийменник: 20 080 вживань у фіді, ціна помилки найвища
    'з',
    'Зі',
    'Зчеплення',
    'зазор',
    '1239із',        # «ST-1239 із 39 одиниць» без пробілу
    'GAAI0802',
    # Сирий фід постачальника: слово, набране навпіл латиницею. Тут `З`/`з` —
    # буква, а не цифра, і без запобіжника вийшло б `3a`, `po3`, `BA3`.
    'зa', 'Зa', 'poз', 'Poз', 'зapaз', 'BAЗ',
]


def selftest() -> int:
    bad = 0
    for src, want in SELFTEST_FIX:
        got, direction, why = fix_token(src)
        if got != want:
            print(f'  ПОМИЛКА  {src!r} → {got!r}, очікувалось {want!r} ({why})')
            bad += 1
    for src in SELFTEST_KEEP:
        got, direction, why = fix_token(src)
        if got != src:
            print(f'  ПОМИЛКА  {src!r} мусив лишитись, став {got!r} ({why})')
            bad += 1
    for src, want in SELFTEST_DIG:
        got, direction, why = fix_digit_token(src)
        if got != want:
            print(f'  ПОМИЛКА  цифра: {src!r} → {got!r}, очікувалось {want!r} '
                  f'({why})')
            bad += 1
    for src in SELFTEST_DIG_KEEP:
        got, direction, why = fix_digit_token(src)
        if got != src:
            print(f'  ПОМИЛКА  цифра: {src!r} мусив лишитись, став {got!r} '
                  f'({why})')
            bad += 1
    # Негативний контроль на рівні тексту: чистий український рядок не
    # повинен змінитись жодним символом. Речення взяте з прийменником `з` і
    # цифрами поруч — саме те сусідство, на якому цифрове правило могло б
    # хибно спрацювати.
    clean = ('Ключ ріжковий 12 мм TOPTUL AAAE1212 дозволяє працювати з '
             '3 гайками в тісноті, з 2011 року з набору')
    out, hits = fix_text(clean)
    if out != clean or hits:
        print(f'  ПОМИЛКА  чистий рядок змінено: {hits}')
        bad += 1
    # І навпаки — рядок із дефектом мусить змінитись САМЕ там, де треба.
    dirty = 'Автосканер Launch X4З1 PROЗ SE 220 B, розмір З60x270x280 мм'
    want = 'Автосканер Launch X431 PRO3 SE 220 B, розмір 360x270x280 мм'
    out, hits = fix_text(dirty)
    if out != want:
        print(f'  ПОМИЛКА  рядок з дефектом: {out!r}')
        bad += 1
    print(f'Самоперевірка: виправлень {len(SELFTEST_FIX)}, недоторканних '
          f'{len(SELFTEST_KEEP) + 1}, цифрових виправлень {len(SELFTEST_DIG)}, '
          f'цифрових недоторканних {len(SELFTEST_DIG_KEEP)}, помилок {bad}')
    return 1 if bad else 0


# ── Замір по фіду ──────────────────────────────────────────────────────────
AUDIT_FIELDS = ('name', 'name_ua', 'description', 'description_ua')


def audit(path: str, report: str = None) -> int:
    root = ET.parse(path).getroot()
    offers = root.findall('.//offer')
    per_field = {}
    fixes = collections.Counter()
    rest = collections.Counter()
    rest_where = collections.defaultdict(set)
    mixed_offers = set()
    rest_offers = set()
    # Цифровий клас міряється ОКРЕМИМ проходом і окремим токенізатором:
    # `З60` мішаним не є, тож у переліку вище його не буде взагалі. Без цього
    # «нуль мішаних» читалось би як «нуль зіпсованого», а це різні речі.
    dig = collections.Counter()
    dig_offers = set()

    for o in offers:
        sku = o.get('id')
        # Характеристики міряються теж: критерій черги — «нуль мішаних
        # токенів У ФІДІ», а не в описах. Три значення там і були
        # (`РZ`, `ЕURO`, `Беzdротова`), і без цього рядка вони лишились би
        # поза заміром — рівно та помилка, від якої застерігає правило
        # позитивного контролю.
        params = ' \n '.join(
            (p.get('name') or '') + ' ' + ''.join(p.itertext())
            for p in o.findall('param'))
        for f in AUDIT_FIELDS + ('param',):
            if f == 'param':
                txt = params
            else:
                e = o.find(f)
                txt = ''.join(e.itertext()) if e is not None else ''
            if not txt:
                continue
            for t in ALNUM.findall(txt):
                new, direction, _ = fix_digit_token(t)
                if direction != KEEP:
                    dig[(t, new)] += 1
                    dig_offers.add(sku)
            toks = [t for t in TOKEN.findall(txt) if is_mixed(t)]
            if not toks:
                continue
            uses, offs = per_field.setdefault(f, [0, set()])
            per_field[f][0] = uses + len(toks)
            per_field[f][1].add(sku)
            mixed_offers.add(sku)
            for t in toks:
                new, direction, why = fix_token(t)
                if direction == KEEP:
                    # Токен, розвʼязний цифровим правилом, у «нерозвʼязних»
                    # не рахується: інакше `PROЗ` стоїть у двох переліках
                    # одночасно й підсумок завищений удвічі.
                    if fix_digit_token(t)[1] != KEEP:
                        continue
                    rest[(t, why)] += 1
                    rest_where[t].add(sku)
                    rest_offers.add(sku)
                else:
                    fixes[(t, new, direction)] += 1

    print(f'Файл: {path}   офферів: {len(offers)}')
    print('Мішані токени по полях (вживань / офферів):')
    for f in AUDIT_FIELDS + ('param',):
        uses, offs = per_field.get(f, [0, set()])
        print(f'   {f:16} {uses:6} / {len(offs):5}')
    # Підсумок береться з полів, а не зі суми «виправні + нерозвʼязні»:
    # частину мішаних токенів забирає цифрове правило, і додавання двох
    # переліків давало б число, яке не сходиться з жодним із них.
    total = sum(v[0] for v in per_field.values())
    # Числа по полях СВІДОМО не зводяться в одне: у фіді TOPTUL `<name>` і
    # `<name_ua>` несуть той самий текст, як і `<description>` з
    # `<description_ua>` (іншого в нас немає, а порожній обовʼязковий тег
    # гірший за повторений). Тому кожне вживання рахується двічі — і краще
    # це бачити рядком вище, ніж ділити навпіл десь у голові.
    print(f'Разом мішаних: {total} вживань у {len(mixed_offers)} офферах '
          f'(текст назв і описів продубльовано в парних тегах)')
    by_dir = collections.Counter()
    for (t, new, d), n in fixes.items():
        by_dir[d] += n
    print(f'   виправних → кирилиця: {by_dir[TO_CYR]}, '
          f'→ латиниця: {by_dir[TO_LAT]}, різних токенів {len(fixes)}')
    print(f'   НЕрозвʼязних: {sum(rest.values())} вживань, '
          f'{len(rest)} різних, {len(rest_offers)} офферів')

    # Перетворення в латиницю друкуються ПОВНІСТЮ, а не вибіркою: їх мало
    # (десятки), а помилка тут псує артикул чи назву бренду.
    lat = sorted(((n, t, new) for (t, new, d), n in fixes.items()
                  if d == TO_LAT), reverse=True)
    if lat:
        print(f'Усі перетворення в латиницю ({len(lat)}) — на очну звірку:')
        for n, t, new in lat:
            print(f'   {n:5}  {t!r} → {new!r}')
    print(f'Кирилична «З» на місці цифри: {sum(dig.values())} вживань, '
          f'{len(dig)} різних, {len(dig_offers)} офферів')
    if dig:
        for (t, new), n in dig.most_common(20):
            print(f'   {n:5}  {t!r} → {new!r}')
        if len(dig) > 20:
            print(f'   … ще {len(dig) - 20} різних')
    if rest:
        print('Нерозвʼязні (лишились як є):')
        for (t, why), n in rest.most_common():
            print(f'   {n:5}  {t!r}: {why}')

    if report:
        with open(report, 'w', encoding='utf-8') as fh:
            fh.write('# Мішані токени, які НЕ виправлені автоматично\n')
            fh.write('# Потрібне рішення власника: правило заміни тут не\n')
            fh.write('# виводиться з написання, а вгадувати заборонено.\n')
            fh.write('# «Вживань» удвічі більше за фактичні: текст назв і\n')
            fh.write('# описів лежить у парних тегах (name/name_ua,\n')
            fh.write('# description/description_ua) і рахується в обох.\n\n')
            fh.write('токен\tвживань\tофферів\tпричина\tприклади SKU\n')
            for (t, why), n in rest.most_common():
                skus = ', '.join(sorted(rest_where[t])[:5])
                fh.write(f'{t}\t{n}\t{len(rest_where[t])}\t{why}\t{skus}\n')
        print(f'Звіт про нерозвʼязні: {report}')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--audit', metavar='XML')
    ap.add_argument('--report', metavar='FILE')
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.audit:
        sys.exit(audit(a.audit, a.report))
    ap.error('потрібен --selftest або --audit')


if __name__ == '__main__':
    main()
