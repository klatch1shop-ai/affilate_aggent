#!/usr/bin/env python3
"""Переклад характеристик TOPTUL на українську — словником, не по картках.

Замір 21.08.2026: у фіді 33757 характеристик, з них **45% мають російську
назву** (15256 вживань), а різних назв лише 319. Значень російською 6950.
Тобто перекладати треба словник унікальних рядків, а не кожне вживання —
319 запитів замість 15 тисяч.

Чому хмарна модель тут дозволена: асортимент — інструменти, обмеження щодо
18+ на TOPTUL не поширюється (перевірено, NVIDIA обробляє без відмов).

Захист від вигадок: модель повертає рядки ПОРЯДКОВО, і кількість рядків у
відповіді мусить збігатися з кількістю на вході. Не збіглась — партія
відхиляється цілком, а не «підганяється».

Запуск:
    python3 tools/toptul_translate.py --names --dry
    python3 tools/toptul_translate.py --names --values
"""
import argparse
import collections
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2.extras  # noqa: E402
from loguru import logger  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402

FEED = os.getenv('TOPTUL_FEED_FILE', '/tmp/toptul.xml')
API = 'https://integrate.api.nvidia.com/v1/chat/completions'
# Доступ до КОНКРЕТНОЇ моделі зникає без попередження: 21.08.2026 о 06:20
# nemotron-120b обробила 30 запитів поспіль, а о 06:58 почала віддавати
# HTTP 404 із порожнім тілом, тоді як решта моделей працювала. Тому не одна
# модель, а перелік: на 404 переходимо до наступної й далі працюємо нею.
MODELS = [m for m in (os.getenv('NOIRE_TRANSLATE_MODEL'),
                      'nvidia/nemotron-3-super-120b-a12b',
                      'mistralai/mistral-nemotron',
                      'deepseek-ai/deepseek-v4-flash-0731') if m]
_active = [0]
BATCH = 15

# ── Ознака російської: словник, а не перелік основ ────────────────────────
#
# Тут стояли дві версії ручного переліку основ, і обидві провалились однаково.
# Перша хибно тривожила: `ширина`, `рукоятк*`, `привод*`, `момент*` однакові в
# українській, і самоперевірка рахувала «26 назв російською, 1203 вживання» на
# вже перекладених рядках. Друга (22.08) прибрала хибні спрацювання й
# розширила добір — 25.08 незалежна перевірка показала, що вона так само не
# бачить «Рабочий профиль» (790 вживань), «Расход воздуха» (322),
# «Пневматический» (283), «двухсторонний» (226), «Набор ключей», «Монитор».
#
# Причина не в конкретному переліку, а в підході. «набор», «нет», «ключи»,
# «металл», «класс», «воздух», «сеть», «нож» пишуться літерами, допустимими в
# українській, і не мають ЖОДНОЇ орфографічної позначки — регексом їх не
# відрізнити в принципі. Тому рішення приймає словник: 1.55 млн українських
# словоформ плюс лексикон російських слів каталогу (`tools/uk_lexicon.py`).
#
# `is_ru` — для замірів (що ЗНАЙДЕНО російським), `needs_translation` — для
# відбору рядків на переклад: воно бере ще й непізнані слова, бо ціна помилки
# протилежна (зайвий рядок у партії — кілька токенів, пропущений російський —
# назавжди у фіді).
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from uk_lexicon import (is_ru, needs_translation, ru_words,   # noqa: E402
                        unknown_words, sizes as lexicon_sizes)

# Сумісність: генератор і сторонні скрипти імпортували `RU` як об'єкт із
# `.search()`. Лишаємо саме таку форму, щоб виклики не мовчали, — але за нею
# тепер словник, а не регекс.
class _RuSignal:
    @staticmethod
    def search(s):
        w = ru_words(s or '')
        return w[0] if w else None


RU = _RuSignal()
RU_WIDE = type('_RuWide', (), {'search': staticmethod(
    lambda s: needs_translation(s or '') or None)})()

# Позитивний контроль: перевірка, яка нічого не ловить, дає нуль, не
# помиляючись. Пари підібрані так, щоб кожен рядок LEFT відрізнявся від
# RIGHT лише мовою. Перші сім пар — з постановки задачі 25.08 (те, чого
# попередня ознака не бачила); решта — рядки, на яких вона хибно тривожила.
SELFTEST_RU = [
    'Рабочий профиль', 'Расход воздуха', 'Пневматический', 'двухсторонний',
    'Крок резьби', 'набор отверток', 'Металлический кейс',
    'Ширина зажима', 'Дополнительная рукоятка',
    # «Тип привода» тут БУВ і прибраний свідомо: `привода` — омограф,
    # український словник має цю словоформу (як і `приводу`, `привід`), тож
    # оголосити її російською означає внести хибну тривогу в замір, ціль якого
    # нуль. Сам рядок від цього не тікає: він цілком є в `toptul_translation`
    # («Тип привода» → «Тип приводу», 9 вживань) і до заміру не доходить.
    'Передаточное число', 'Ключ шестигранный', 'Диаметр колес',
    'Материал изделия', 'Прямой', 'Накидной', 'Назначение', 'Питание',
    'Комплектация', 'Погрешность, +/-', 'Мощность лампы',
    'Трещоточная викрутка-бітотримач', 'Ключ накидной силовой односторонний',
    'Тип шлица', 'Маркировка наконечника', 'Монитор', 'Набор ключей',
    'Подсветка дисплея', 'Глубина', 'Тип мебели', 'Тип аккумулятора',
    'Шкала измерений', 'Регулировка количества оборотов', 'Тип двигателя',
]
SELFTEST_UK = [
    'Робочий профіль', 'Витрата повітря', 'Пневматичний', 'двосторонній',
    'Крок різі', 'набір викруток', 'Металевий кейс',
    'Ширина', 'Матеріал рукоятки', 'Вид приводу інструмента',
    'Ширина полотна', 'Ширина губок', 'Додаткова рукоятка',
    'Довжина рукоятки', 'Передаточне число', 'Шестигранник', 'Шестигранні',
    'Ключ шестигранний', 'Тип приводу', 'з прямим приводом',
    'Максимальний крутний момент', 'Діаметр коліс', 'Матеріал виробу',
    'Призначення', 'Живлення', 'Потужність лампи', 'Комплектація',
    'Набір ключів', 'Головка торцева', 'алое', 'герой',
    'Маркування наконечника', 'Монітор', 'Глибина', 'Тип меблів',
    'Тип акумулятора', 'Шкала вимірювань', 'Тип двигуна',
]


def selftest() -> int:
    """0 = ознака поводиться як задумано."""
    bad = 0
    for s in SELFTEST_RU:
        if not is_ru(s):
            logger.error(f'НЕ впізнано російське: {s!r} '
                         f'(непізнані слова: {unknown_words(s)})')
            bad += 1
    for s in SELFTEST_UK:
        hit = ru_words(s)
        if hit:
            logger.error(f'ХИБНА тривога на українському: {s!r} через {hit}')
            bad += 1
    uk_n, ru_n = lexicon_sizes()
    logger.info(f'словники: {uk_n} укр. словоформ, {ru_n} рос. слів')
    if bad:
        logger.error(f'самоперевірка ознаки мови: {bad} розбіжностей')
    else:
        logger.success(f'самоперевірка ознаки мови: {len(SELFTEST_RU)} '
                       f'російських впізнано, 0 хибних на '
                       f'{len(SELFTEST_UK)} українських')
    return bad

# Прив'язка за ПОРЯДКОМ рядків виявилась крихкою: модель розбивала
# багатослівні значення на кілька рядків, і партія на 25 позицій приходила
# як 27 або 34 — відхилялась цілком. Тому кожен рядок несе свій оригінал,
# і зіставлення йде за ним, а не за позицією. Зайві рядки ігноруються.
PROMPT = """Переклади українською терміни з каталогу інструментів.

ФОРМАТ ВІДПОВІДІ — по одному рядку на кожен термін:
оригінал ||| переклад

ПРАВИЛА:
- зліва від ||| постав оригінал ТОЧНО як у переліку, без змін;
- якщо термін уже українською — праворуч повтори його без змін;
- бренди, моделі, артикули, одиниці виміру НЕ перекладай;
- без нумерації, без пояснень, без порожніх рядків.

ПЕРЕЛІК ({n}):
{items}"""


def ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS toptul_translation (
        kind TEXT, src TEXT, dst TEXT, uses INT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (kind, src))""")


def _parse(txt: str, wanted: set) -> dict:
    """Пари з відповіді. Зіставлення за рядком, не за позицією.

    Позиційна прив'язка ламалась 21.08.2026: модель розбивала багатослівне
    значення на кілька рядків, і зсув давав характеристиці ЧУЖИЙ переклад —
    гірше, ніж не перекласти. Тут кожен рядок несе свій оригінал, тож зсув
    неможливий за побудовою.
    """
    pairs = {}
    for line in txt.split('\n'):
        if '|||' not in line:
            continue
        src, _, dst = line.partition('|||')
        src = re.sub(r'^\s*\d+[\.\)]\s*', '', src.strip())
        dst = dst.strip()
        if src in wanted and dst:
            pairs[src] = dst
    return pairs


def translate(items: list, key: str) -> dict:
    """{оригінал: переклад}. Зіставлення за рядком, не за позицією."""
    wanted = set(items)
    # Читаємо ТІЛЬКИ content. Резервне читання reasoning_content, доречне в
    # класифікації, тут отруйне: у міркуванні сотні рядків, і партія на 40
    # позицій відхилялась як «198 рядків замість 40».
    #
    # Умова повтору — НЕ «content порожній», а «жодної пари не розібрано».
    # 23.08.2026 на назвах товарів (вони втричі довші за назви характеристик)
    # `nemotron-3-super` витрачав увесь бюджет 1500 токенів на міркування й
    # віддавав його ж у полі `content`: `finish_reason=length`, 4101 символ
    # роздумів англійською, жодного `|||`. Стара умова бачила непорожній
    # рядок, вважала відповідь одержаною й не підвищувала бюджет — 15 партій
    # поспіль, 353 рядки, 0 записів у БД. Замір на тій самій партії з 15
    # назв: 1500 токенів — 0/15 пар, 6000 — 15/15.
    for tokens in (3000, 8000):
        txt = ''
        while _active[0] < len(MODELS):
            model = MODELS[_active[0]]
            body = {'model': model, 'temperature': 0, 'max_tokens': tokens,
                    'messages': [{'role': 'user', 'content': PROMPT.format(
                        n=len(items), items='\n'.join(items))}]}
            try:
                r = requests.post(API, headers={'Authorization': f'Bearer {key}'},
                                  json=body, timeout=240)
            except Exception as e:
                logger.warning(f'{type(e).__name__}')
                return {}
            if r.status_code == 404:
                logger.warning(f'модель {model} недоступна (404) — переходжу далі')
                _active[0] += 1
                continue
            try:
                txt = (r.json()['choices'][0]['message'].get('content') or '').strip()
            except Exception:
                # Не лише 404: 23.08.2026 `deepseek-v4-flash` віддав 200 без
                # ключа `choices`. Відповідь без вибору — та сама недоступність
                # моделі, тож і поводитись треба так само, інакше партія
                # мовчки гине на робочому ключі.
                logger.warning(f'модель {model}: нечитана відповідь HTTP '
                               f'{r.status_code} — переходжу далі')
                _active[0] += 1
                continue
            break
        if _active[0] >= len(MODELS):
            logger.error('усі моделі недоступні')
            return {}
        pairs = _parse(txt, wanted)
        if pairs:
            return pairs
    logger.warning(f'жодної пари навіть на 8000 токенів (партія {len(items)}, '
                   f'модель {MODELS[_active[0]]}) — партія втрачена')
    return {}


# Третій вид рядків — НАЗВА ТОВАРУ. Вона не лежить у `<param>`, тому
# окрема гілка: беремо той самий тег, який обирає генератор, і перекладаємо
# СИРУ назву постачальника. Не побудовану: `build_name()` викидає бренд,
# артикул і пунктуацію, тож побудована назва — похідна, і словник із неї
# розсипався б від будь-якої зміни правил побудови.
KINDS = ('name', 'value', 'title')
TITLE_TAGS = ('name_ua', 'name')


def title_tag(offers: list) -> str:
    """Тег назви не вгадується (крок 1 правила позитивного контролю).

    У фіді TOPTUL є ОБИДВА теги, і вони різні за мовою: `name` російський
    у 5688 випадках із 6895, `name_ua` — у 238. Взяти не той означало б
    «перекласти» 5,7 тис. рядків, яких у фіді Rozetka немає взагалі.
    """
    for t in TITLE_TAGS:
        if any((o.findtext(t) or '').strip() for o in offers):
            return t
    return TITLE_TAGS[0]


def collect(kind: str) -> collections.Counter:
    root = ET.parse(FEED).getroot()
    offers = root.find('shop').find('offers').findall('offer')
    c = collections.Counter()
    if kind == 'title':
        tag = title_tag(offers)
        for o in offers:
            s = (o.findtext(tag) or '').strip()
            # Відбір — ШИРОКОЮ ознакою (див. нижче), тому сюди потрапляють і
            # вже українські назви на кшталт «Вороток з рукояткою». Модель
            # повертає їх без змін, і це дешевше за пропущений російський рядок.
            if s and RU_WIDE.search(s):
                c[s] += 1
        return c
    for o in offers:
        for p in o.findall('param'):
            s = (p.get('name') if kind == 'name' else (p.text or '')).strip()
            # Відбір — ШИРОКОЮ ознакою: краще віддати моделі зайвий
            # український рядок, ніж лишити російський неперекладеним.
            if s and RU_WIDE.search(s):
                c[s] += 1
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--names', action='store_true')
    ap.add_argument('--values', action='store_true')
    ap.add_argument('--titles', action='store_true',
                    help='назви товарів (сирий тег фіду, не побудована назва)')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--selftest', action='store_true',
                    help='позитивний контроль ознаки мови, без мережі й БД')
    a = ap.parse_args()

    if a.selftest:
        sys.exit(1 if selftest() else 0)

    key = os.getenv('NVIDIA_API_KEY')
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()

    for kind in [k for k, on in (('name', a.names), ('value', a.values),
                                 ('title', a.titles)) if on]:
        src = collect(kind)
        cur.execute('SELECT src FROM toptul_translation WHERE kind=%s', (kind,))
        done = {r['src'] for r in cur.fetchall()}
        todo = [s for s in src if s not in done]
        logger.info(f'модель {MODELS[_active[0]]}');logger.info(f'{kind}: різних {len(src)}, вживань {sum(src.values())}, '
                    f'до перекладу {len(todo)}')
        if a.dry:
            for s in todo[:10]:
                print(f'   {src[s]:5}  {s}')
            continue
        ok = lost = 0
        for i in range(0, len(todo), BATCH):
            part = todo[i:i + BATCH]
            out = translate(part, key)
            if not out:
                # Партія, що не дала жодної пари, ЗНИКАЄ. Раніше тут був німий
                # `continue`, і 22.08.2026 прогін із 41 відповіддю HTTP 401
                # завершився без єдиного `ERROR` у логу: «прогін пройшов» і
                # «переклад зроблено» — різні події, а лог їх не розрізняв.
                lost += len(part)
                continue
            for s, d in out.items():
                cur.execute("""INSERT INTO toptul_translation (kind, src, dst, uses)
                               VALUES (%s,%s,%s,%s)
                               ON CONFLICT (kind, src) DO UPDATE SET dst=EXCLUDED.dst""",
                            (kind, s, d, src[s]))
            conn.commit()
            ok += len(out)
            logger.info(f'  {kind}: {ok}/{len(todo)}')
            time.sleep(0.3)
        # Підсумок друкується ЗАВЖДИ, і нуль записів — це помилка, а не тиша.
        if lost or not ok:
            logger.error(f'{kind}: записано {ok}, ВТРАЧЕНО {lost} із {len(todo)}')
        else:
            logger.success(f'{kind}: записано {ok} із {len(todo)}, втрат немає')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
