#!/usr/bin/env python3
"""Українізація ОПИСІВ TOPTUL — по реченнях, а не по картках.

Замір 01.09.2026 (`toptul_ru_audit.py` по `output/toptul_rozetka.xml`):
478 оферів мають російські слова в `description_ua`, 1206 різних слів,
4651 вживання. Це останній російський шматок фіду: назви товарів, назви й
значення характеристик уже нульові.

── Чому по реченнях, а не по цілих описах ─────────────────────────────────

Розподіл, а не враження: з 433 різних описів **287 мають лише 1–2 російські
слова** серед 300–1400 слів українського тексту, і тільки 109 російські
суціль. Віддати модель цілий опис на 1400 слів заради двох — це не марна
витрата токенів, а ризик: модель переписує й те, що переписувати не просили
(на пробі 01.09 вона з «проводов, проволоки» зробила «дротів, дроту»,
злила два різні терміни в один).

Речення — найбільша одиниця, яку можна замінити, не чіпаючи сусідніх.
Числа: 433 описи = 3363 речення, з них російських **720 різних**. Решта
2328 лишаються БАЙТ У БАЙТ, і це не обіцянка, а властивість побудови.

**Розбиття перевірено на зворотність** перед тим, як на нього спиратись:
`' '.join(SPLIT.split(t)) == t` для всіх 433 описів (`--selftest` повторює
цю перевірку на вбудованому наборі). Опис уже пройшов `plain()`, тобто
пробіли зведені, тому склеювання через один пробіл відновлює оригінал.

── Дві фази: партії, а потім поодинці ─────────────────────────────────────

Замір пропускної здатності 01.09.2026 (`--models`, `--conc` у чернетках):
відповідає ОДНА модель, `nvidia/nemotron-3-super-120b-a12b` (решта — 404,
410 або таймаут понад 180 с), одне речення коштує 13–70 с, і на 3–6 потоках
виходить **5–6 успішних запитів за хвилину**. Тобто 720 запитів поодинці —
це понад дві години, і саме стільки з'їв би найпростіший шлях.

Тому фаза 1 — партіями по кілька речень із прив'язкою `оригінал |||
переклад`, тією самою, якою `toptul_translate.py` лікували 21.08.2026 від
зсуву. Ключове: приймається ЛИШЕ пара, ліва частина якої дослівно збігається
з надісланим реченням. Не збіглась — речення не «підганяється» і не
губиться, а лишається на фазу 2, де йде в запиті сам-один і сплутати його
немає з чим. Зсув неможливий за побудовою в обох фазах.

Довгі речення (понад 600 символів, їх 20) у партії не потрапляють узагалі:
подвоєння виводу на такому рядку з'їдає бюджет токенів.

── Перевірки відповіді (партія відхиляється ЦІЛКОМ, а не підганяється) ────

1. **Числа.** Множина числових токенів у перекладі мусить дорівнювати
   вхідній. Опис інструмента — це розміри, тиски й моменти; модель, яка
   «покращила» 1/2" на 3/8", гірша за неперекладене речення.
2. **Латиниця.** Те саме для латинських токенів: бренди, серії й артикули
   (`TOPTUL`, `Pro-Plus`, `DBAB1608`) не перекладають — правило SKILL-16.
3. **Довжина** в межах 0.6–1.6 від оригіналу: обрив і переказ.
4. **Один рядок.** Вхід після `plain()` однорядковий; багаторядкова
   відповідь означає, що модель заговорила від себе.
5. **Службові маркери** (`|||`, ```` ``` ````, «Ось переклад») — відмова.
6. **Мова результату.** `uk_lexicon.ru_words(dst)` мусить бути порожнім.
   Не порожній — повтор іншою моделлю; лишився — запис із `ru_left>0`, і
   це число видно в `--audit`, а не ховається за «записано 720».

`reasoning_content` не читається взагалі — 21.08.2026 воно отруїло вивід
(сотні рядків міркування замість 40 перекладів). Модель тут міркує (проба
01.09: 1731 символ міркування на 656 токенів відповіді), тому бюджет
токенів рахується від довжини речення й підіймається при повторі.

── Власний аудит після перекладу — окремий крок, не побічний ефект ────────

Модель помиляється в українській: на пробі 01.09 вона видала «відвертка»
замість «викрутка» і «слесарним» замість «слюсарним». Замінити російські
слова на неправильні українські — це не переклад, а маскування, причому
виглядає воно як успіх: `ru_words` дає нуль, бо «відвертка» пишеться
українськими літерами.

Тому: `data/toptul_uk_fixes.tsv` — перелік хибних форм і правильних,
`--fix` переписує вже збережені переклади, `--audit` шукає хибні форми й
завершується кодом 1, доки їх не нуль.

Запуск:
    python3 tools/toptul_desc_translate.py --selftest      # без мережі й БД
    python3 tools/toptul_desc_translate.py --dry
    python3 tools/toptul_desc_translate.py --run --limit 10
    python3 tools/toptul_desc_translate.py --run
    python3 tools/toptul_desc_translate.py --fix
    python3 tools/toptul_desc_translate.py --audit
"""
import argparse
import collections
import concurrent.futures as cf
import hashlib
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2.extras  # noqa: E402
from loguru import logger  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402
from uk_lexicon import ru_words, unknown_words, sizes as lexicon_sizes  # noqa: E402
from homoglyph import fix_text as fix_homoglyphs  # noqa: E402
from homoglyph import is_mixed, TOKEN as HG_TOKEN  # noqa: E402

FEED = os.getenv('TOPTUL_FEED_FILE', '/tmp/toptul.xml')
OUR_FEED = os.path.join(BASE_DIR, 'output', 'toptul_rozetka.xml')
FIXES = os.path.join(BASE_DIR, 'data', 'toptul_uk_fixes.tsv')

API = 'https://integrate.api.nvidia.com/v1/chat/completions'
# Перелік, а не одна модель: доступ до КОНКРЕТНОЇ моделі зникає серед дня
# (21.08.2026 — HTTP 404 з порожнім тілом при робочому ключі). Перевірено
# 01.09.2026: з переліку відповідає лише перша, решта дає 404 — але саме
# тому перелік і потрібен, бо завтра це може бути навпаки.
MODELS = [m for m in (os.getenv('NOIRE_TRANSLATE_MODEL'),
                      'nvidia/nemotron-3-super-120b-a12b',
                      'mistralai/mistral-nemotron',
                      'deepseek-ai/deepseek-v4-flash-0731') if m]
# 4 потоки — заміряно, не вгадано (01.09.2026, по 1/2/3/4/6 потоків на тому
# самому реченні): 1 потік — 3.1 успішних запити/хв, 4 — 6.3, 6 — 4.9 і
# розкид часу відповіді втричі більший. Тобто вище четвірки пропускна
# здатність не росте, а 503 «Service temporarily overloaded» стає частішим.
WORKERS = 4
# Скільки речень в одну партію фази 1 і яка найбільша довжина рядка в ній.
# 6×600 — це ~3600 символів вводу й стільки ж виводу (модель повторює
# оригінал ліворуч), що вкладається в бюджет токенів разом із міркуванням.
BATCH = 6
BATCH_MAX_LEN = 600
# Частка російських слів, до якої речення виправляється ПО СЛОВАХ, а не
# переписується цілком. Обрано за розподілом, а не на око: при 25% у групу
# «слово-в-слово» потрапляє 296 речень із 720, і в них лише 242 різні
# російські словоформи.
#
# Чому це головна межа інструмента. Проба 01.09 на 30 реченнях показала, що
# модель, переписуючи речення цілком, псує вже українське: з «Вислизанню
# інструменту з рук перешкоджає обрезиненное покриття» вона зробила
# «Вислизанню інструменту з рук обгумоване покриття» — прибрала присудок.
# Там, де українського тексту більшість, ціна такої «допомоги» вища за
# користь, тому заміняється РІВНО те слово, що російське, а решта речення
# лишається байт у байт. Переписування цілком лишається для речень, де
# зберігати нічого.
WORD_SHARE = 0.25
WORD_BATCH = 15
_CYR_WORD = re.compile(r"[А-Яа-яЁёЇїІіЄєҐґ']{2,}")

_TAGS = re.compile(r'<[^>]+>')
_MS = re.compile(r'\s+')
SPLIT = re.compile(r'(?<=[.!?])\s+')
_NUM = re.compile(r'\d+(?:[.,]\d+)?')
_ENTITY = re.compile(r'&[a-zA-Z]+;|&#\d+;')
_LAT = re.compile(r'[A-Za-z]{2,}')
_PREAMBLE = re.compile(r'^\s*(ось|нижче|переклад|ось переклад|sure|here)\b', re.I)


def plain(desc: str) -> str:
    """Те саме перетворення, що в генераторі, — інакше ключі не зійдуться."""
    return _MS.sub(' ', _TAGS.sub(' ', desc or '')).strip()


def sentences(text: str) -> list:
    return [s for s in (p.strip() for p in SPLIT.split(text)) if s]


def h(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


# ── Словник виправлень ─────────────────────────────────────────────────────

def load_fixes() -> list:
    """[(регекс, заміна, підпис)]. Порожній файл — не помилка, а стан «ще ні»."""
    out = []
    if not os.path.exists(FIXES):
        return out
    with open(FIXES, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            bad, good = parts[0].strip(), parts[1].strip()
            if not bad:
                continue
            # Дві форми запису, і різниця між ними не косметична.
            #   `відвертк*` — ОСНОВА: ловить «відвертка/відвертки/відверткою».
            #   `бита`      — ЦІЛЕ слово: основа `бит` зачепила б українські
            #                 «битва» й «битий», тобто виправлення саме стало
            #                 б помилкою. Ціле слово тут — не обережність, а
            #                 єдиний спосіб не зіпсувати текст.
            if bad.endswith('*'):
                rx = re.compile(rf'\b{re.escape(bad[:-1])}', re.I)
            else:
                rx = re.compile(rf'\b{re.escape(bad)}\b', re.I)
            out.append((rx, good, bad))
    return out


def apply_fixes(text: str, fixes: list) -> tuple:
    """(текст, [які правила спрацювали]). Зберігає регістр першої літери."""
    hits = []
    for rx, good, label in fixes:
        def _sub(m):
            src = m.group(0)
            return good.capitalize() if src[:1].isupper() else good
        text, n = rx.subn(_sub, text)
        if n:
            hits.append(label)
    return text, hits


def bad_forms(text: str, fixes: list) -> list:
    return [label for rx, _, label in fixes if rx.search(text)]


# ── Запит до моделі ────────────────────────────────────────────────────────
#
# Глосарій у промпті — це ті самі помилки, які модель робила на пробі 01.09
# («відвертка», «слесарний»). Дешевше не дати їй помилитись, ніж ловити
# потім; але ловимо все одно — `--audit` не довіряє промпту.
PROMPT = """Ти редагуєш україномовний каталог ручного інструменту.

Перепиши речення нижче правильною українською мовою.

ПРАВИЛА:
- виправляй ЛИШЕ те, що не є українською; українські слова лишай як є;
- нічого не додавай, не прибирай і не скорочуй;
- числа, розміри й одиниці виміру не змінюй;
- бренди, серії, артикули й латинські позначення лишай без змін;
- відповідь — САМЕ це речення, одним рядком, без пояснень, без лапок.

СЛОВНИК (уживай саме ці відповідники):
{glossary}

РЕЧЕННЯ:
{s}"""


# Партія фази 1. Формат `оригінал ||| переклад` — той самий, яким 21.08.2026
# полагодили зсув у перекладі характеристик: зіставлення йде ЗА РЯДКОМ, а не
# за позицією, тож пропущений або зайвий рядок відповіді нікому не віддає
# чужий переклад — він лише лишає своє речення на фазу 2.
PROMPT_BATCH = """Ти редагуєш україномовний каталог ручного інструменту.

Перепиши кожне речення правильною українською мовою.

ФОРМАТ ВІДПОВІДІ — рівно один рядок на кожне речення:
оригінал ||| переклад

ПРАВИЛА:
- ліворуч від ||| постав оригінал ТОЧНО як у переліку, без жодної зміни;
- виправляй ЛИШЕ те, що не є українською; українські слова лишай як є;
- нічого не додавай, не прибирай і не скорочуй;
- числа, розміри й одиниці виміру не змінюй;
- бренди, серії, артикули й латинські позначення лишай без змін;
- без нумерації, без пояснень, без порожніх рядків.

СЛОВНИК (уживай саме ці відповідники):
{glossary}

РЕЧЕННЯ ({n}):
{items}"""

# Глосарій — це ті самі помилки, які модель робила на пробі 01.09
# («відвертка», «слесарний»). Дешевше не дати їй помилитись, ніж ловити
# потім; але ловимо все одно — `--audit` промпту не довіряє.
GLOSSARY = (
    'отвёртка/відвертка — викрутка; слесарный/слесарний — слюсарний; '
    'бита — біта; ключ рожковый — ключ ріжковий; головка торцевая — головка '
    'торцева; трещотка — тріскачка; плоскогубцы — плоскогубці; бокорезы — '
    'бокорізи; пассатижи — пасатижі; напильник — напилок; сверло — свердло; '
    'монтировка — монтувалка; резьба — різь; удлинитель — подовжувач; '
    'обрезиненный — обгумований; хромомолибденовая — хромомолібденова.')


def ask(prompt: str, key: str, tokens: int, model_idx: int) -> tuple:
    """(відповідь, індекс моделі). Порожня відповідь — не виняток, а стан."""
    # 503 «Service temporarily overloaded» — це НЕ відмова моделі, а черга на
    # боці NVIDIA: на пробі 01.09 п'ять таких відповідей прийшли за першу
    # хвилину прогону в 6 потоків і коштували двох втрачених речень. Тому
    # 503 і 429 обробляються однаково — чеканням, а не втратою партії.
    # Межа спроб потрібна, щоб прогін не завис назавжди на мертвому сервісі.
    tries = 0
    while model_idx < len(MODELS):
        model = MODELS[model_idx]
        try:
            r = requests.post(
                API, headers={'Authorization': f'Bearer {key}'},
                json={'model': model, 'temperature': 0, 'max_tokens': tokens,
                      'messages': [{'role': 'user', 'content': prompt}]},
                timeout=300)
        except Exception as e:
            logger.warning(f'{type(e).__name__} — запит пропущено в цій спробі')
            return '', model_idx
        if r.status_code in (404, 401, 403):
            logger.warning(f'модель {model}: HTTP {r.status_code} — переходжу далі')
            model_idx += 1
            continue
        if r.status_code in (429, 503):
            # 503 приходить миттєво (0.4 с), тому чекати довго немає сенсу:
            # звільнити слот і спробувати ще — дешевше, ніж наростаюча пауза,
            # яка на пробі 01.09 розтягнула 24 речення на понад 20 хвилин.
            tries += 1
            if tries > 15:
                logger.warning(f'модель {model}: {r.status_code} п\'ятнадцять '
                               f'разів поспіль — здаюсь на цьому запиті')
                return '', model_idx
            time.sleep(2)
            continue
        if r.status_code != 200:
            logger.warning(f'модель {model}: HTTP {r.status_code}')
            return '', model_idx
        try:
            # ТІЛЬКИ content. `reasoning_content` не читається навіть як
            # резерв: у ньому сотні рядків роздумів, і 21.08.2026 саме
            # резервне читання отруїло вивід.
            return (r.json()['choices'][0]['message'].get('content')
                    or '').strip(), model_idx
        except Exception:
            logger.warning(f'модель {model}: нечитана відповідь HTTP '
                           f'{r.status_code} — переходжу далі')
            model_idx += 1
    return '', model_idx


def restore_tail(src: str, dst: str) -> str:
    """Повертає кінцевий розділовий знак, якщо модель його з'їла.

    Не косметика. Опис збирається назад через `' '.join(речення)`, тому
    речення без крапки зливається з наступним в одне: «…різьбових з'єднань
    Виготовлена зі сталі». Замір на 48 реченнях першої проби 01.09.2026 —
    **3 випадки з 48**, серед них найчастіше речення фіду (20 оферів).

    Чому відновлення, а не відмова: знак — єдине, чого бракує, а сам
    переклад уже пройшов перевірки на числа, латиницю й довжину. Обрив
    речення так не замаскується — обірваний хвіст ловить межа довжини 0.6.
    """
    if not dst or src[-1:] not in '.!?':
        return dst
    if dst[-1:] in '.!?':
        return dst
    return dst.rstrip(' ,;:') + src[-1]


def check(src: str, dst: str) -> str:
    """'' = приймаємо. Інакше — причина відмови словами."""
    if not dst:
        return 'порожня відповідь'
    if '\n' in dst:
        return 'багаторядкова відповідь'
    if '|||' in dst or '```' in dst:
        return 'службовий маркер у відповіді'
    if _PREAMBLE.match(dst):
        return 'пояснення замість тексту'
    if not 0.6 <= len(dst) / max(len(src), 1) <= 1.6:
        return f'довжина {len(dst)} проти {len(src)}'
    # HTML-сутності виводяться з-під порівняння, і це не послаблення
    # перевірки, а виправлення її прицілу. Описи постачальника несуть
    # `&nbsp;` і `&#39;` просто текстом; `nbsp` — латинський токен, `39` —
    # число, тож модель, яка розгорнула сутність у звичайний пробіл чи
    # апостроф, відхилялась за «латиниця не збігається» й «числа не
    # збігаються». На пробі 01.09 це було 3 відмови з 30 — усі хибні.
    a, b = _ENTITY.sub(' ', src), _ENTITY.sub(' ', dst)
    if collections.Counter(_NUM.findall(a)) != collections.Counter(_NUM.findall(b)):
        return 'числа не збігаються'
    if (collections.Counter(w.lower() for w in _LAT.findall(a)) !=
            collections.Counter(w.lower() for w in _LAT.findall(b))):
        return 'латиниця не збігається'
    return ''


# ── Залишок: російські слова, що ПЕРЕЖИЛИ переклад ─────────────────────────
#
# Навіщо друга ознака, коли є `ru_words`. Тому що на прозі описів вона сліпа,
# і це не здогад, а замір 01.09.2026: у збереженому перекладі «Качество
# інструмента почти всегда зависит от прочного матеріала из которого он
# производится» `ru_words` дає **нуль**. Лексикон російського зібраний із
# назв і значень характеристик, а описи — це речення, і в них інші слова:
# «почти», «зависит», «которого», «производится», «качество». Жодне з них не
# має орфографічної позначки (`ы/э/ъ/ё`) і жодне не має закінчення, за яким
# їх упізнав би морфологічний бік ознаки. Тобто рядок «російські слова В
# ПЕРЕКЛАДІ: 0» був фактом про словник, а не про дані — рівно той клас
# помилки, від якого застерігає правило позитивного контролю в CLAUDE.md.
#
# Ця ознака словника російського не потребує ЗОВСІМ, тому й не успадковує
# його прогалин. Твердження просте: слово лишилось у перекладі ДОСЛІВНО
# таким, як у російському оригіналі, і українському словникові воно
# невідоме. Перекладене слово так виглядати не може — воно або змінилось,
# або є в українському словнику. Обидві умови потрібні: без першої в залишок
# потрапив би весь суржик перекладу («розпсилення»), без другої — кожне
# слово, спільне для обох мов («момент», «ширина»), тобто повернулась би
# хвороба, від якої лікували ознаку 22 і 25.08.
#
# Гомогліфні рядки ознака не міряє. У них латинські двійники стоять
# усередині кирилиці (`нeoбxідним` — три латинські літери), тому токенізатор
# ріже слово на уламки («тичним», «збл», «кув»), і кожен уламок невідомий
# обом словникам. Це інший дефект — окремий, більший і не мовний: 244 оффери
# фіду 01.09.2026. Міряти його цією ознакою означало б отримати число, яке
# не зменшується від жодного перекладу.
#
# Ознака — імпорт із `tools/homoglyph.py`, а не другий регекс: там же живе
# й ВИПРАВЛЕННЯ, яке накладає `collect()`. Два власні визначення розійшлись
# би, і `residue()` мовчала б на рядках, які виправлення вже вилікувало.
def homoglyph(s: str) -> bool:
    return any(is_mixed(t) for t in HG_TOKEN.findall(s or ''))


def residue(src: str, dst: str) -> list:
    """Слова оригіналу, які лишились у перекладі й невідомі укр. словнику."""
    if homoglyph(src):
        return []
    from uk_lexicon import tokens as _tok
    have = set(_tok(src))
    return [w for w in unknown_words(dst) if w in have]


# ── Збір речень ────────────────────────────────────────────────────────────

def collect() -> collections.Counter:
    """{речення: у скількох оферах}. Лише офери, які є в НАШОМУ фіді.

    Крок 1 правила позитивного контролю: тег опису не вгадується. У фіді
    TOPTUL непорожні ОБИДВА теги (`description` і `description_ua`, по 6904),
    і генератор бере `description_ua` — беремо той самий, інакше словник
    складався б для тексту, якого в нашому фіді немає.
    """
    ours = {o.get('id') for o in ET.parse(OUR_FEED).getroot().iter('offer')}
    offers = ET.parse(FEED).getroot().find('shop').find('offers').findall('offer')
    logger.info(f'офферів: постачальник {len(offers)}, наш фід {len(ours)}')
    for tag in ('description_ua', 'description'):
        n = sum(1 for o in offers if (o.findtext(tag) or '').strip())
        logger.info(f'   тег {tag}: непорожніх {n}')
    c = collections.Counter()
    texts = 0
    for o in offers:
        if o.get('id') not in ours:
            continue
        # Мішане написання знімається тим самим кодом, що й у генераторі, і
        # саме тут, до `ru_words()`. Дві причини, і обидві вимірені:
        #   * без нього ознака мови бреше в ОБИДВА боки — `cили` з латинською
        #     `c` дає «російське» `или` (хибна тривога), а справді російські
        #     «Размери», «Материал» ховаються в уламках і не знаходяться
        #     зовсім. На фіді 01.09.2026 це 731 «російське» речення проти
        #     745 справжніх;
        #   * ключ, за яким `run()` відрізняє перекладене від
        #     неперекладеного, — сам рядок. Він мусить бути тим самим, що йде
        #     у фід, інакше 728 уже перекладених речень виглядають новими
        #     (див. `tools/toptul_homoglyph_normalize.py`).
        d = fix_homoglyphs(plain(o.findtext('description_ua') or ''))[0]
        if not d or not ru_words(d):
            continue
        texts += 1
        for s in sentences(d):
            if ru_words(s):
                c[s] += 1
    logger.info(f'описів з російськими словами: {texts}, '
                f'російських речень: {len(c)} різних, {sum(c.values())} вживань')
    return c


# ── База ───────────────────────────────────────────────────────────────────

def ensure(cur):
    # Окрема таблиця, а не `kind='desc'` у `toptul_translation`: там ключ
    # PRIMARY KEY (kind, src), а найдовше речення — 2009 символів кирилиці,
    # тобто ~4 КБ, і btree-індекс Postgres такого рядка не приймає (межа
    # 2704 Б). Ключ — sha256 тексту, сам текст лежить полем.
    cur.execute("""CREATE TABLE IF NOT EXISTS toptul_desc_translation (
        src_hash TEXT PRIMARY KEY,
        src      TEXT NOT NULL,
        dst      TEXT NOT NULL,
        raw      TEXT,
        uses     INT,
        ru_left  INT DEFAULT 0,
        model    TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW())""")
    # `raw` — відповідь моделі ДО словника виправлень. Без неї аудит хибних
    # форм був би замкнений сам на себе: виправлення накладаються при записі,
    # тому в `dst` їх не буде за побудовою, і нуль нічого не доводив би.
    # Порівняння `raw` з `dst` і є позитивний контроль словника: у `raw`
    # хибні форми МУСЯТЬ знаходитись, інакше словник міряє порожнечу.
    cur.execute("""ALTER TABLE toptul_desc_translation
                   ADD COLUMN IF NOT EXISTS raw TEXT""")


def load_db(cur) -> dict:
    cur.execute('SELECT src, dst FROM toptul_desc_translation')
    return {r['src']: r['dst'] for r in cur.fetchall()}


# ── Прогін ─────────────────────────────────────────────────────────────────

# ── Гілка «слово-в-слово» ──────────────────────────────────────────────────

PROMPT_WORDS = """Переклади українською слова з опису ручного інструменту.

ФОРМАТ ВІДПОВІДІ — по одному рядку на кожне слово:
оригінал ||| переклад

ПРАВИЛА:
- ліворуч від ||| постав оригінал ТОЧНО як у переліку;
- переклад має бути В ТІЙ САМІЙ граматичній формі (відмінок, рід, число):
  «монтировку» → «монтувалку», «губцевым» → «губцевим»;
- одне слово — один відповідник, без пояснень і без варіантів у дужках;
- бренди, моделі й артикули не перекладай — повтори без змін;
- без нумерації, без порожніх рядків.

СЛОВНИК (уживай саме ці відповідники):
{glossary}

СЛОВА ({n}):
{items}"""


def word_share(s: str) -> float:
    return len(ru_words(s)) / max(len(_CYR_WORD.findall(s)), 1)


def check_word(src: str, dst: str) -> str:
    """'' = приймаємо переклад ОДНОГО слова."""
    if not dst:
        return 'порожньо'
    if len(dst.split()) > 3:
        return 'не слово, а фраза'
    if _NUM.search(dst) or _LAT.search(dst):
        return 'цифри або латиниця в перекладі слова'
    if ru_words(dst):
        return 'переклад сам російський'
    return ''


def substitute(sent: str, words: dict) -> tuple:
    """Заміна російських слів у реченні. (новий текст, скільки замінено).

    Заміна йде по МЕЖІ СЛОВА й зберігає регістр першої літери. Решта рядка
    не змінюється взагалі — саме в цьому сенс гілки.
    """
    n = 0
    out = sent
    for src in sorted(set(ru_words(sent)), key=len, reverse=True):
        dst = words.get(src.lower())
        if not dst:
            continue
        rx = re.compile(rf'\b{re.escape(src)}\b', re.I)

        def _sub(m):
            w = m.group(0)
            return dst.capitalize() if w[:1].isupper() else dst
        out, k = rx.subn(_sub, out)
        n += k
    return out, n


def budget_for(chars: int, floor: int = 2500) -> int:
    """Бюджет токенів від довжини вводу, але не менший за `floor`.

    Міркування моделі лежить окремим полем, але `max_tokens` їсть так само:
    проба 01.09 — 656 токенів відповіді при 1731 символі міркування на
    реченні в 300 символів. Тому запас чотирикратний, а не «на око».

    **Чому з'явилась нижня межа (замір 01.09.2026, прогін 09:27–09:51).**
    Фаза 1 віддавала на фазу 2 майже все: 20 партій зі 120 речень дали лише
    33 записи. Причина не в розборі й не в перевірках — партія поверталась
    БЕЗ ЖОДНОЇ пари. Проба на одній партії з шести речень, три виклики
    поспіль:

    | бюджет | finish_reason | reasoning | content | пар |
    |---:|---|---:|---:|---:|
    | 4800 (порахований від довжини) | `length` | 12787 симв | 12787 симв | 0 |
    | 4000 + system «detailed thinking off» | `length` | 12787 | 12787 | 0 |
    | **16000** | `stop` | 13343 | **1453** | **5/6** |

    Тобто при обриві модель віддає в `content` СВОЄ МІРКУВАННЯ (content і
    reasoning збігаються символ у символ), а відповідь не встигає початись.
    Це та сама пастка, що 23.08.2026 з назвами товарів: `content` не
    порожній — він повний не тим, тому й повтор «на порожній відповіді» не
    рятував. Міркування коштує ~4500 токенів майже незалежно від довжини
    вводу, тому межа — стала, а не частка від тексту.

    Система «detailed thinking off» перевірена й не працює на цій моделі:
    міркування лишається тим самим. Тобто його треба ВМІСТИТИ, а не
    вимкнути.
    """
    return min(24000, max(floor, chars * 4))


def batches(todo: list) -> list:
    """Партії фази 1 і перелік речень, які в партію не йдуть."""
    short = [s for s in todo if len(s) <= BATCH_MAX_LEN]
    long_ = [s for s in todo if len(s) > BATCH_MAX_LEN]
    return [short[i:i + BATCH] for i in range(0, len(short), BATCH)], long_


def parse_batch(txt: str, wanted: set) -> dict:
    """Пари з відповіді. Приймається лише ДОСЛІВНИЙ збіг лівої частини.

    Саме тут проходить межа між «партія втрачена» і «характеристика дістала
    чужий переклад». Другого бути не може: рядок, ліва частина якого не
    збігається з надісланим реченням, не зіставляється ні з чим — речення
    просто лишається на фазу 2.
    """
    pairs = {}
    norm = {_MS.sub(' ', w).strip(): w for w in wanted}
    for line in txt.split('\n'):
        if '|||' not in line:
            continue
        left, _, right = line.partition('|||')
        left = _MS.sub(' ', re.sub(r'^\s*\d+[.)]\s*', '', left)).strip()
        right = right.strip()
        src = norm.get(left)
        if src and right:
            pairs[src] = right
    return pairs


def run(limit: int, redo: bool):
    key = os.getenv('NVIDIA_API_KEY')
    if not key:
        logger.error('NVIDIA_API_KEY немає — ключ є лише на ноутбуці')
        return 1
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()
    done = load_db(cur)
    fixes = load_fixes()
    logger.info(f'словник виправлень: {len(fixes)} правил')

    src = collect()
    todo = [s for s in src if redo or s not in done]
    todo.sort(key=lambda s: -src[s])       # найчастіші першими
    if limit:
        todo = todo[:limit]
    total = len(todo)
    logger.info(f'до перекладу: {total} речень '
                f'({sum(len(s) for s in todo)} символів), уже в базі {len(done)}')
    if not todo:
        return 0

    lock = threading.Lock()
    stats = collections.Counter()
    model_idx = [0]
    t0 = time.time()

    def store(s, dst):
        """Записує пару, повертає кількість російських слів, що лишились."""
        raw = dst
        dst, _ = apply_fixes(dst, fixes)
        left = len(ru_words(dst))
        cur.execute("""INSERT INTO toptul_desc_translation
            (src_hash, src, dst, raw, uses, ru_left, model)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (src_hash) DO UPDATE SET
              dst=EXCLUDED.dst, raw=EXCLUDED.raw, uses=EXCLUDED.uses,
              ru_left=EXCLUDED.ru_left, model=EXCLUDED.model""",
            (h(s), s, dst, raw, src[s], left,
             MODELS[min(model_idx[0], len(MODELS) - 1)]))
        conn.commit()
        stats['записано'] += 1
        if left:
            stats['записано з російськими залишками'] += 1
        return left

    # ── фаза 0: речення, де російського мало, — заміна ПО СЛОВАХ ──────────
    low = [s for s in todo if word_share(s) <= WORD_SHARE]
    forms = collections.Counter()
    for s in low:
        for w in ru_words(s):
            forms[w.lower()] += src[s]
    cur.execute("SELECT src, dst FROM toptul_translation WHERE kind='dword'")
    words = {r['src']: r['dst'] for r in cur.fetchall()}
    need = [w for w in forms if w not in words]
    logger.info(f'фаза 0: {len(low)} речень зі часткою російського ≤'
                f'{WORD_SHARE:.0%}, у них {len(forms)} різних словоформ, '
                f'нових {len(need)} (у словнику вже {len(words)})')

    def work_words(part):
        prompt = PROMPT_WORDS.format(n=len(part), glossary=GLOSSARY,
                                     items='\n'.join(part))
        txt, model_idx[0] = ask(prompt, key, 6000, model_idx[0])
        if model_idx[0] >= len(MODELS):
            return {}
        good = {}
        for s, d in parse_batch(txt, set(part)).items():
            why = check_word(s, d)
            if why:
                stats[f'слово: відхилено — {why}'] += 1
                continue
            good[s] = d
        return good

    if need:
        parts = [need[i:i + WORD_BATCH]
                 for i in range(0, len(need), WORD_BATCH)]
        with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for i, good in enumerate(ex.map(work_words, parts), 1):
                with lock:
                    for s, d in good.items():
                        cur.execute(
                            """INSERT INTO toptul_translation (kind, src, dst, uses)
                               VALUES ('dword',%s,%s,%s)
                               ON CONFLICT (kind, src) DO UPDATE SET dst=EXCLUDED.dst""",
                            (s, d, forms[s]))
                        words[s] = d
                    conn.commit()
                    stats['словоформ перекладено'] += len(good)
                    if i % 5 == 0:
                        logger.info(f'  слова: партія {i}/{len(parts)}, '
                                    f'{time.time()-t0:.0f} c')

    # Складання речень із замін. Мережі тут уже немає — лише підстановка,
    # тому й перевірка інша: речення, у якому лишилось російське слово (бо
    # словоформа не перекладена), НЕ записується, а йде далі на переписування.
    to_rewrite = []
    for s in todo:
        if s not in low:
            to_rewrite.append(s)
            continue
        new, k = substitute(s, words)
        if not k or ru_words(new):
            to_rewrite.append(s)
            stats['слово-в-слово не вийшло — на переписування'] += 1
            continue
        why = check(s, new)
        if why:
            to_rewrite.append(s)
            stats[f'слово-в-слово: відхилено — {why}'] += 1
            continue
        store(s, new)
        stats['зібрано зі слів'] += 1
    logger.info(f'фаза 0: зібрано зі слів {stats["зібрано зі слів"]}, '
                f'на переписування {len(to_rewrite)} за {time.time()-t0:.0f} c')
    todo = to_rewrite

    # ── фаза 1: партіями ──────────────────────────────────────────────────
    def work_batch(part):
        prompt = PROMPT_BATCH.format(n=len(part), glossary=GLOSSARY,
                                     items='\n'.join(part))
        chars = sum(len(s) for s in part)
        # Нижня межа 16000 — саме той бюджет, на якому проба дала 5 пар із 6
        # замість нуля (див. `budget_for`). Менший бюджет не «трохи гірший»,
        # а нульовий: партія повертається без жодної пари.
        txt, model_idx[0] = ask(prompt, key, budget_for(chars * 2, 16000),
                                model_idx[0])
        if model_idx[0] >= len(MODELS):
            return part, {}
        pairs = parse_batch(txt, set(part))
        good = {}
        for s, d in pairs.items():
            d = restore_tail(s, d)
            why = check(s, d)
            if why:
                stats[f'партія: відхилено — {why}'] += 1
                continue
            good[s] = d
        rest = [s for s in part if s not in good]
        return rest, good

    parts, long_ = batches(todo)
    logger.info(f'фаза 1: {len(parts)} партій по ≤{BATCH}; '
                f'{len(long_)} довгих речень одразу поодинці')
    leftovers = list(long_)
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, (rest, good) in enumerate(ex.map(work_batch, parts), 1):
            with lock:
                for s, d in good.items():
                    store(s, d)
                leftovers += rest
                if i % 10 == 0:
                    logger.info(f'  партія {i}/{len(parts)}, записано '
                                f'{stats["записано"]}, на фазу 2 '
                                f'{len(leftovers)}, {time.time()-t0:.0f} c')
    logger.info(f'фаза 1: записано {stats["записано"]}, '
                f'лишилось {len(leftovers)} за {time.time()-t0:.0f} c')

    # ── фаза 2: по одному реченню ─────────────────────────────────────────
    def work_one(s):
        for attempt, mul in enumerate((1, 2)):
            prompt = PROMPT.format(s=s, glossary=GLOSSARY)
            # Та сама межа, що й у партії, і з тієї самої причини: міркування
            # коштує ~4500 токенів навіть на реченні в 300 символів, тож
            # бюджет, порахований від довжини, обривав відповідь до її
            # початку. Повтор подвоює — не «про всяк випадок», а на випадок
            # довшого міркування (перша спроба показує його розмір).
            dst, model_idx[0] = ask(prompt, key,
                                    budget_for(len(s), 12000) * mul,
                                    model_idx[0])
            if model_idx[0] >= len(MODELS):
                return s, None, 'усі моделі недоступні'
            dst = restore_tail(s, dst)
            why = check(s, dst)
            if why:
                continue
            return s, dst, ''
        return s, None, why or 'не пройшло перевірок'

    if leftovers:
        with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for i, (s, dst, why) in enumerate(ex.map(work_one, leftovers), 1):
                with lock:
                    if dst is None:
                        stats['відхилено'] += 1
                        stats[f'причина: {why}'] += 1
                        logger.warning(f'ВІДХИЛЕНО ({why}): {s[:90]}')
                    else:
                        store(s, dst)
                    if i % 25 == 0:
                        logger.info(f'  фаза 2: {i}/{len(leftovers)}, '
                                    f'{time.time()-t0:.0f} c')

    # Підсумок друкується ЗАВЖДИ: «прогін завершився» і «переклад зроблено» —
    # різні події, і 22.08.2026 лог їх не розрізняв (41 відповідь HTTP 401
    # без єдиного ERROR у логу).
    logger.info(f'── підсумок за {time.time()-t0:.0f} c ──')
    for k, v in sorted(stats.items()):
        logger.info(f'   {k}: {v}')
    if stats['відхилено']:
        logger.error(f'ВТРАЧЕНО {stats["відхилено"]} із {total}')
    elif not stats['записано']:
        logger.error('записано НУЛЬ — це помилка, а не тиша')
    else:
        logger.success(f'записано {stats["записано"]} із {total}')
    cur.close()
    conn.close()
    return 0 if stats['записано'] else 1


# ── Перепереклад рядків із залишком ────────────────────────────────────────

# Речення подається саме́, а не в партії, і разом із переліком слів, які
# лишились російськими. Причина в даних: партійний прохід уже перекладав ці
# рядки — і саме на них помилився, тож повторити той самий запит означало б
# чекати іншої відповіді на те саме питання.
PROMPT_RESIDUE = """Ти редагуєш україномовний каталог ручного інструменту.

Це речення переклали українською не до кінця: у ньому лишились російські
слова. Перепиши його ПОВНІСТЮ українською.

ОБОВʼЯЗКОВО переклади ці слова (жодне з них не має лишитись у відповіді):
{words}

ПРАВИЛА:
- нічого не додавай, не прибирай і не скорочуй;
- числа, розміри й одиниці виміру не змінюй;
- бренди, серії, артикули й латинські позначення лишай без змін;
- відповідь — САМЕ це речення, одним рядком, без пояснень, без лапок.

СЛОВНИК (уживай саме ці відповідники):
{glossary}

РЕЧЕННЯ:
{s}"""


def redo_residue(limit: int):
    """Перекладає заново рядки, у яких `residue()` знайшла залишок.

    Умова прийняття тут строгіша, ніж у першому прогоні, і це головне:
    крім усіх перевірок `check()`, залишок мусить СТАТИ МЕНШИМ. Відповідь,
    яка залишок не зменшила, не записується взагалі — інакше прохід
    «оновив 274 рядки» й не змінив нічого по суті, а число оновлених
    читалося б як результат.
    """
    key = os.getenv('NVIDIA_API_KEY')
    if not key:
        logger.error('NVIDIA_API_KEY немає — ключ є лише на ноутбуці')
        return 1
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    fixes = load_fixes()
    # Лише те, що справді є в НАШОМУ фіді: чистити рядок, який у фід не
    # потрапляє, означає робити таблицю «кращою» без наслідку.
    src_all = collect()
    cur.execute('SELECT src_hash, src, dst, uses FROM toptul_desc_translation')
    rows = []
    for r in cur.fetchall():
        if r['src'] not in src_all:
            continue
        res = residue(r['src'], r['dst'])
        if res:
            rows.append((r, res))
    rows.sort(key=lambda x: -(x[0]['uses'] or 1) * len(x[1]))
    if limit:
        rows = rows[:limit]
    words_total = sum(len(res) * (r['uses'] or 1) for r, res in rows)
    logger.info(f'рядків із залишком: {len(rows)}, вживань слів: {words_total}')
    if not rows:
        return 0

    model_idx = [0]
    stats = collections.Counter()
    lock = threading.Lock()
    t0 = time.time()

    def work(item):
        r, res = item
        prompt = PROMPT_RESIDUE.format(s=r['src'], glossary=GLOSSARY,
                                       words=', '.join(sorted(set(res))))
        txt, model_idx[0] = ask(prompt, key, budget_for(len(r['src']) * 2, 4000),
                                model_idx[0])
        if model_idx[0] >= len(MODELS):
            return item, None
        d = restore_tail(r['src'], (txt or '').strip())
        return item, d

    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, ((r, res), d) in enumerate(ex.map(work, rows), 1):
            with lock:
                if not d:
                    stats['порожня відповідь'] += 1
                else:
                    why = check(r['src'], d)
                    if why:
                        stats[f'відхилено — {why}'] += 1
                    else:
                        new, _ = apply_fixes(d, fixes)
                        left = residue(r['src'], new)
                        if len(left) >= len(res):
                            stats['відхилено — залишок не зменшився'] += 1
                        else:
                            cur.execute(
                                """UPDATE toptul_desc_translation
                                   SET dst=%s, raw=%s, ru_left=%s,
                                       model=%s WHERE src_hash=%s""",
                                (new, d, len(ru_words(new)),
                                 MODELS[min(model_idx[0], len(MODELS) - 1)],
                                 r['src_hash']))
                            conn.commit()
                            stats['оновлено'] += 1
                            stats['слів прибрано'] += len(res) - len(left)
                            if left:
                                stats['оновлено, але залишок є'] += 1
                if i % 20 == 0:
                    logger.info(f'  {i}/{len(rows)}, {time.time()-t0:.0f} c, '
                                f'оновлено {stats["оновлено"]}')
    logger.info('── підсумок ──')
    for k, v in sorted(stats.items()):
        logger.info(f'   {k}: {v}')
    cur.close()
    conn.close()
    # Нуль оновлених — помилка, а не тиша: рядки із залишком є, отже прохід,
    # який не змінив жодного, не спрацював.
    return 0 if stats['оновлено'] else 1


# ── Виправлення вже записаного ─────────────────────────────────────────────

def fix():
    fixes = load_fixes()
    if not fixes:
        logger.error(f'{FIXES} порожній або відсутній — виправляти нічим')
        return 1
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    cur.execute('SELECT src_hash, src, dst FROM toptul_desc_translation')
    rows = cur.fetchall()
    changed = collections.Counter()
    n = 0
    for r in rows:
        new, hits = apply_fixes(r['dst'], fixes)
        if new != r['dst']:
            cur.execute("""UPDATE toptul_desc_translation
                           SET dst=%s, ru_left=%s WHERE src_hash=%s""",
                        (new, len(ru_words(new)), r['src_hash']))
            n += 1
            for hit in hits:
                changed[hit] += 1
    conn.commit()
    logger.success(f'виправлено {n} перекладів із {len(rows)}, '
                   f'{len(fixes)} правил')
    for k, v in changed.most_common():
        logger.info(f'   {k}: {v}')
    cur.close()
    conn.close()
    return 0


def polish(limit: int):
    """Дочищає ЗБЕРЕЖЕНІ переклади, у яких лишились російські слова.

    Навіщо окремий прохід. `check()` не дивиться на мову результату — і це
    свідомо: відхилити речення через одне неперекладене слово означає
    лишити його російським ЦІЛКОМ, тобто гірше. Тому такі переклади
    записуються з `ru_left>0`, і саме вони — залишок, який не дає дійти до
    цільових ≤20 вживань. Замір 01.09.2026 після першого прогону: 51 речення,
    37 різних слів, 69 вживань.

    Чому по словах, а не переписуванням речення заново. У цих рядках
    український текст уже є, і його більшість; переписування ризикує ним, як
    показала проба 01.09 («Вислизанню інструменту з рук перешкоджає
    обрезиненное покриття» → модель прибрала присудок). Тут же міняється
    РІВНО те слово, що лишилось російським, решта — байт у байт. Гілка та
    сама, що й фаза 0, тільки джерелом є `dst`, а не `src`, і словник
    словоформ `toptul_translation kind='dword'` спільний.

    Перевірки не послаблені: `check(src, new)` звіряє числа, латиницю й
    довжину з ОРИГІНАЛОМ, а не з попереднім перекладом.
    """
    key = os.getenv('NVIDIA_API_KEY')
    if not key:
        logger.error('NVIDIA_API_KEY немає — ключ є лише на ноутбуці')
        return 1
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    fixes = load_fixes()
    # Беруться лише ті, що справді є в НАШОМУ фіді: чистити рядок, який у фід
    # не потрапляє, означає робити таблицю «кращою» без наслідку (та сама
    # засторога, що й 01.09 про «кантер» і «Минеральное»).
    src_all = collect()
    cur.execute("""SELECT src_hash, src, dst, uses FROM toptul_desc_translation
                   WHERE ru_left > 0""")
    rows = [r for r in cur.fetchall() if r['src'] in src_all]
    if limit:
        rows = sorted(rows, key=lambda r: -(r['uses'] or 0))[:limit]
    forms = collections.Counter()
    for r in rows:
        for w in ru_words(r['dst']):
            forms[w.lower()] += (r['uses'] or 1)
    cur.execute("SELECT src, dst FROM toptul_translation WHERE kind='dword'")
    words = {r['src']: r['dst'] for r in cur.fetchall()}
    need = [w for w in forms if w not in words]
    logger.info(f'дочищення: {len(rows)} речень із залишками, '
                f'{len(forms)} різних словоформ, нових {len(need)} '
                f'(у словнику вже {len(words)})')
    if not rows:
        return 0

    model_idx = [0]
    stats = collections.Counter()
    lock = threading.Lock()

    def work_words(part):
        prompt = PROMPT_WORDS.format(n=len(part), glossary=GLOSSARY,
                                     items='\n'.join(part))
        txt, model_idx[0] = ask(prompt, key, 6000, model_idx[0])
        if model_idx[0] >= len(MODELS):
            return {}
        good = {}
        for s, d in parse_batch(txt, set(part)).items():
            why = check_word(s, d)
            if why:
                stats[f'слово: відхилено — {why}'] += 1
                continue
            good[s] = d
        return good

    if need:
        parts = [need[i:i + WORD_BATCH]
                 for i in range(0, len(need), WORD_BATCH)]
        with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for good in ex.map(work_words, parts):
                with lock:
                    for s, d in good.items():
                        cur.execute(
                            """INSERT INTO toptul_translation (kind, src, dst, uses)
                               VALUES ('dword',%s,%s,%s)
                               ON CONFLICT (kind, src) DO UPDATE SET dst=EXCLUDED.dst""",
                            (s, d, forms[s]))
                        words[s] = d
                    conn.commit()
                    stats['словоформ перекладено'] += len(good)

    for r in rows:
        new, k = substitute(r['dst'], words)
        if not k:
            stats['словоформи немає — лишено як є'] += 1
            continue
        new, _ = apply_fixes(new, fixes)
        why = check(r['src'], new)
        if why:
            stats[f'відхилено — {why}'] += 1
            continue
        left = len(ru_words(new))
        cur.execute("""UPDATE toptul_desc_translation
                       SET dst=%s, ru_left=%s WHERE src_hash=%s""",
                    (new, left, r['src_hash']))
        stats['оновлено'] += 1
        if left:
            stats['оновлено, але залишок є'] += 1
    conn.commit()
    logger.info('── підсумок дочищення ──')
    for k, v in sorted(stats.items()):
        logger.info(f'   {k}: {v}')
    cur.execute("""SELECT count(*) n FROM toptul_desc_translation
                   WHERE ru_left > 0""")
    logger.info(f'   лишилось рядків із залишками: {cur.fetchone()["n"]}')
    cur.close()
    conn.close()
    # Нуль оновлених — це помилка, а не тиша: рядки з залишками є, отже
    # прохід, який нічого не змінив, не спрацював.
    return 0 if stats['оновлено'] else 1


# ── Аудит збереженого ──────────────────────────────────────────────────────

def audit(top: int):
    fixes = load_fixes()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    cur.execute('SELECT src, dst, raw, uses, ru_left FROM toptul_desc_translation')
    rows = cur.fetchall()
    src_all = collect()
    print(f'\nу базі: {len(rows)} перекладів, у фіді потрібно {len(src_all)}')
    miss = [s for s in src_all if s not in {r['src'] for r in rows}]
    print(f'не перекладено: {len(miss)} речень '
          f'({sum(src_all[s] for s in miss)} вживань)')
    for s in miss[:top]:
        print(f'   {src_all[s]:4}× {s[:100]}')

    ru = collections.Counter()
    ru_sent = 0
    res_w = collections.Counter()
    res_sent = []
    hg = 0
    unk = collections.Counter()
    bad = collections.Counter()
    raw_bad = collections.Counter()
    bad_sent = []
    same = 0
    for r in rows:
        for x in bad_forms(r['raw'] or '', fixes):
            raw_bad[x] += (r['uses'] or 1)
        w = ru_words(r['dst'])
        if w:
            ru_sent += 1
            for x in w:
                ru[x] += (r['uses'] or 1)
        for x in unknown_words(r['dst']):
            unk[x] += (r['uses'] or 1)
        hits = bad_forms(r['dst'], fixes)
        if hits:
            bad_sent.append((r['dst'], hits))
            for x in hits:
                bad[x] += (r['uses'] or 1)
        if r['dst'].strip() == r['src'].strip():
            same += 1
        if homoglyph(r['src']):
            hg += 1
        rs = residue(r['src'], r['dst'])
        if rs:
            res_sent.append((r, rs))
            for x in rs:
                res_w[x] += (r['uses'] or 1)

    print(f'\nпереклад дослівно збігається з оригіналом: {same}')
    print(f'російські слова В ПЕРЕКЛАДІ: {ru_sent} речень, {len(ru)} різних '
          f'слів, {sum(ru.values())} вживань')
    for w, n in ru.most_common(top):
        print(f'   {n:5}  {w}')
    # Друкується ОДРАЗУ під попереднім числом, і саме тому, що попереднє
    # число буває нулем при брудних даних: `ru_words` не знає прози описів
    # («почти», «зависит», «которого»), тож нуль над цим рядком означає лише
    # «словник таких слів не має». Залишок рахується без словника
    # російського взагалі — див. `residue()`.
    print(f'\nЗАЛИШОК: слова оригіналу, що ПЕРЕЖИЛИ переклад '
          f'(ознака без словника рос.): {len(res_sent)} речень, '
          f'{len(res_w)} різних слів, {sum(res_w.values())} вживань')
    for w, n in res_w.most_common(top):
        print(f'   {n:5}  {w}')
    for r, rs in sorted(res_sent, key=lambda x: -len(x[1]))[:5]:
        print(f'      {len(rs)} слів: {r["dst"][:110]}')
    print(f'   гомогліфних рядків (латиниця всередині кирилиці, залишок у '
          f'них не міряється — інший дефект): {hg}')
    # Позитивний контроль словника виправлень. Виправлення накладаються ще
    # при записі, тому нуль у `dst` за побудовою нічого не доводить — доказом
    # є ненуль у `raw` (сира відповідь моделі) на тих самих правилах.
    print(f'\nХибні форми в СИРІЙ відповіді моделі (контроль, має бути НЕнуль): '
          f'{len(raw_bad)} різних, {sum(raw_bad.values())} вживань')
    for w, n in raw_bad.most_common(top):
        print(f'   {n:5}  {w}')
    print(f'\nХИБНІ українські форми в перекладі (словник '
          f'{os.path.basename(FIXES)}, {len(fixes)} правил): {len(bad)} різних, '
          f'{sum(bad.values())} вживань')
    for w, n in bad.most_common(top):
        print(f'   {n:5}  {w}')
    for dst, hits in bad_sent[:5]:
        print(f'      {hits}: {dst[:120]}')
    print(f'\nнепізнані слова в перекладах: {len(unk)} різних, '
          f'{sum(unk.values())} вживань')
    for w, n in unk.most_common(top):
        print(f'   {n:5}  {w}')

    cur.close()
    conn.close()
    # Ненульові хибні форми — це провал критерію задачі, а не зауваження.
    rc = 1 if bad else 0
    if rc:
        print('\nДЕФЕКТ: у перекладах є хибні українські форми')
    else:
        print('\nХибних українських форм у перекладах немає.')
    return rc


# ── Самоперевірка без мережі й БД ──────────────────────────────────────────

SELF_TEXTS = [
    "Головка торцева під монтировку призначена для монтажу/демонтажу "
    "різьбових з'єднань. Головка виготовлена з якісної сталі. "
    "Термообробка підвищує стійкість до зносу.",
    "Отвертка TORX T30 Pro-Plus Series TOPTUL FFAF3013",
    "Довжина 160 мм, матеріал CR-V! Модель TOPTUL DBAB1608. Вага 0,5 кг?",
]
# Пари «прийняти / відхилити» — перевірка, яка вміє лише приймати, нічого
# не варта. Кожен рядок відрізняється від правильного рівно одним дефектом.
SELF_CHECK = [
    ('Довжина 160 мм, матеріал CR-V.', 'Довжина 160 мм, матеріал CR-V.', ''),
    ('Довжина 160 мм, матеріал CR-V.', 'Довжина 180 мм, матеріал CR-V.',
     'числа не збігаються'),
    ('Довжина 160 мм, матеріал CR-V.', 'Довжина 160 мм, матеріал CRV-X.',
     'латиниця не збігається'),
    ('Довжина 160 мм, матеріал CR-V.', '', 'порожня відповідь'),
    ('Довжина 160 мм, матеріал CR-V.', 'Довжина 160 мм.', 'довжина'),
    ('Довжина 160 мм, матеріал CR-V.',
     'Ось переклад: Довжина 160 мм, матеріал CR-V.', 'пояснення'),
    ('Довжина 160 мм, матеріал CR-V.',
     'Довжина 160 мм,\nматеріал CR-V.', 'багаторядкова'),
    # HTML-сутність розгорнута моделлю — це НЕ дефект (проба 01.09: три
    # хибні відмови з тридцяти саме на `&nbsp;` і `&#39;`).
    ('&nbsp;Тип: LVMP, з&#39;єднання 1/4.', ' Тип: LVMP, з\'єднання 1/4.', ''),
    ('&nbsp;Тип: LVMP, з&#39;єднання 1/4.', ' Тип: HVLP, з\'єднання 1/4.',
     'латиниця не збігається'),
]


def selftest() -> int:
    bad = 0
    # 0. Розбір партії. Приймається лише дослівний збіг лівої частини — на
    #    цьому тримається твердження «чужого перекладу бути не може».
    wanted = ['Отвертка TORX T30.', 'Клещи переставные 10".', 'Довжина 160 мм.']
    answer = ('Отвертка TORX T30. ||| Викрутка TORX T30.\n'
              '2) Довжина 160 мм. ||| Довжина 160 мм.\n'
              'Клещи переставні 10". ||| Кліщі переставні 10".\n'
              'просто рядок без роздільника\n')
    got = parse_batch(answer, set(wanted))
    if got.get('Отвертка TORX T30.') != 'Викрутка TORX T30.':
        print('  ПАРТІЯ: не прийнято дослівний збіг')
        bad += 1
    if got.get('Довжина 160 мм.') != 'Довжина 160 мм.':
        print('  ПАРТІЯ: нумерація ліворуч не знята')
        bad += 1
    if 'Клещи переставные 10".' in got:
        print('  ПАРТІЯ: прийнято рядок зі ЗМІНЕНИМ оригіналом — '
              'саме так речення дістає чужий переклад')
        bad += 1
    if len(got) != 2:
        print(f'  ПАРТІЯ: пар {len(got)}, очікувалось 2')
        bad += 1
    # 0.5. Заміна по словах: змінюється РІВНО російське слово, решта рядка
    #      лишається байт у байт — саме це й відрізняє цю гілку від
    #      переписування цілком.
    sent = ('Вислизанню інструменту з рук перешкоджає обрезиненное покриття '
            'ручок TOPTUL 160 мм.')
    new, k = substitute(sent, {'обрезиненное': 'обгумоване'})
    want = sent.replace('обрезиненное', 'обгумоване')
    if new != want or k != 1:
        print(f'  ЗАМІНА ПО СЛОВАХ: {new!r} (замін {k})')
        bad += 1
    if substitute(sent, {})[1] != 0:
        print('  ЗАМІНА ПО СЛОВАХ: без словника щось таки змінилось')
        bad += 1
    for w, d, want_why in (('монтировку', 'монтувалку', ''),
                           ('монтировку', 'монтировку', 'сам російський'),
                           ('монтировку', 'монтувалку (насадку) для ключа',
                            'не слово'),
                           ('монтировку', 'lever', 'латиниця'),
                           ('монтировку', '', 'порожньо')):
        got = check_word(w, d)
        if not ((want_why == '' and got == '') or (want_why and want_why in got)):
            print(f'  ПЕРЕВІРКА СЛОВА: на {d!r} очікувалось {want_why!r}, '
                  f'отримано {got!r}')
            bad += 1
    # 0.7. Кінцевий розділовий знак. Без нього речення зливаються при
    #      складанні опису; замір першої проби 01.09.2026 — 3 випадки з 48.
    for s, d, want in (
            ("Головка призначена для з'єднань.",
             "Головка призначена для з'єднань",
             "Головка призначена для з'єднань."),
            ('Видалення ізоляції і др.', 'Видалення ізоляції і тощо,',
             'Видалення ізоляції і тощо.'),
            ('Чи готовий інструмент?', 'Чи готовий інструмент',
             'Чи готовий інструмент?'),
            # Знак на місці — рядок не чіпається взагалі.
            ('Кейс із металу.', 'Кейс із металу.', 'Кейс із металу.'),
            # Оригінал без знака — дописувати нічого.
            ('Кейс із металу', 'Кейс із металу', 'Кейс із металу')):
        got = restore_tail(s, d)
        if got != want:
            print(f'  КІНЦЕВИЙ ЗНАК: на {d!r} очікувалось {want!r}, '
                  f'отримано {got!r}')
            bad += 1
    # 1. Розбиття на речення зворотне — на цьому тримається обіцянка
    #    «сусідні речення не змінюються».
    for t in SELF_TEXTS:
        if ' '.join(sentences(t)) != t:
            print(f'  РОЗБИТТЯ НЕ ЗВОРОТНЕ: {t[:60]!r}')
            bad += 1
    # 2. Перевірки відповіді ловлять кожен вид дефекту й не чіпають чистого.
    for src, dst, want in SELF_CHECK:
        got = check(src, dst)
        ok = (want == '' and got == '') or (want and want in got)
        if not ok:
            print(f'  ПЕРЕВІРКА: на {dst[:40]!r} очікувалось {want!r}, '
                  f'отримано {got!r}')
            bad += 1
    # 2.5. Залишок. Пари побудовані так, що `ru_words` на КОЖНІЙ дає нуль —
    #      інакше друга ознака нічого не доводила б: перевірялося б те, що
    #      вже вміє перша.
    RESIDUE_CASES = [
        # Речення, на якому ознака й народилась: перекладено два слова з
        # дев'яти, `ru_words` мовчить.
        ('Качество инструмента почти всегда зависит от прочного материала.',
         'Качество інструмента почти всегда зависит от прочного матеріала.',
         ['качество', 'почти', 'всегда', 'зависит', 'прочного']),
        # Переклад справді український — залишку немає.
        ('Качество инструмента почти всегда зависит от материала.',
         'Якість інструмента майже завжди залежить від матеріалу.', []),
        # Суржик перекладу («розпсилення») залишком НЕ є: у нього немає
        # оригіналу, тобто слово не «пережило переклад», а з'явилось.
        ('Экологичная система распыления HVLP.',
         'Екологічна система розпсилення HVLP.', []),
        # Спільне для обох мов слово залишком не є — саме на таких словах
        # двічі зривалась ознака мови (22 і 25.08.2026).
        ('Момент затяжки резьбового соединения.',
         'Момент затягування різьбового з\'єднання.', []),
        # Гомогліфний рядок не міряється зовсім: уламки латинізованих слів
        # дали б число, яке не зменшується від жодного перекладу.
        ('Bін є нeoбxідним інcтpумeнтoм для poбoти.',
         'Bін є нeoбxідним інcтpумeнтoм для poбoти.', []),
    ]
    for src, dst, want in RESIDUE_CASES:
        if ru_words(dst):
            print(f'  ЗАЛИШОК: випадок непридатний — ru_words уже ловить '
                  f'{ru_words(dst)} у {dst[:40]!r}')
            bad += 1
        got = sorted(set(residue(src, dst)))
        if got != sorted(set(want)):
            print(f'  ЗАЛИШОК: на {dst[:45]!r} очікувалось {sorted(set(want))}, '
                  f'отримано {got}')
            bad += 1
    # 3. Словник виправлень справді щось міняє (порожній словник — не «чисто»).
    fixes = load_fixes()
    probe = 'Відвертка слесарна з битою.'
    fixed, hits = apply_fixes(probe, fixes)
    print(f'  словник виправлень: {len(fixes)} правил, проба '
          f'{probe!r} → {fixed!r} (спрацювали: {hits})')
    if fixes and fixed == probe:
        print('  СЛОВНИК НЕ СПРАЦЬОВУЄ на відомо хибному рядку')
        bad += 1
    uk_n, ru_n = lexicon_sizes()
    print(f'  словники мови: {uk_n} укр. словоформ, {ru_n} рос. слів')
    print(f'САМОПЕРЕВІРКА: {"розбіжностей " + str(bad) if bad else "0 розбіжностей"}'
          f' ({len(SELF_TEXTS)} розбиттів, {len(SELF_CHECK)} перевірок)')
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', action='store_true')
    ap.add_argument('--dry', action='store_true', help='лише замір, без мережі')
    ap.add_argument('--fix', action='store_true',
                    help='перезастосувати словник виправлень до бази')
    ap.add_argument('--audit', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--redo', action='store_true',
                    help='перекласти заново навіть те, що вже в базі')
    ap.add_argument('--polish', action='store_true',
                    help='дочистити збережені переклади з ru_left>0 по словах')
    ap.add_argument('--redo-residue', action='store_true',
                    dest='redo_residue',
                    help='перекласти заново рядки, де слова оригіналу '
                         'пережили переклад (residue)')
    ap.add_argument('--top', type=int, default=20)
    a = ap.parse_args()

    if a.selftest:
        sys.exit(1 if selftest() else 0)
    if a.dry:
        src = collect()
        for s, n in src.most_common(15):
            print(f'   {n:4}×  {s[:120]}')
        sys.exit(0)
    if a.fix:
        sys.exit(fix())
    if a.polish:
        sys.exit(polish(a.limit))
    if a.redo_residue:
        sys.exit(redo_residue(a.limit))
    if a.audit:
        sys.exit(audit(a.top))
    if a.run:
        sys.exit(run(a.limit, a.redo))
    ap.print_help()


if __name__ == '__main__':
    main()
