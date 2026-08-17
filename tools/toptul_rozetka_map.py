#!/usr/bin/env python3
"""Мапінг категорій TOPTUL → Rozetka за деревом реального продавця.

Джерело істини — не здогадка, а факт: `docs/rozetka_seller_categories.json`,
зібраний із каталогу конкурента `ttul`, який возить той самий TOPTUL. Його
категорії вже пройшли модерацію майданчика.

Чому не беремо `supplier_category_mapping`: замір 17.08.2026 показав, що з
338 використовуваних категорій TOPTUL непридатні 291 (5761 товар із 6895) —
216 без назви категорії, 162 вказують розділ ВЕРХНЬОГО рівня замість
категорії («Трещотки, воротки» → «Авто і мото товари»), 15 відсутні. 293 з
323 записів мають `confidence = auto`, тобто їх ніхто не звіряв.

Складність задачі: назви TOPTUL російською, назви Rozetka українською, і
близькість написання оманлива — «Отвертки» ↔ «Викрутки» не мають спільних
літер, а «Головки торцевые» ↔ «Торцеві головки» мають ще й інший порядок
слів. Тому чиста схожість рядків не працює: потрібен словник термінів плюс
зіставлення за основами слів.

Головне правило (SKILL-04): **нижче порогу — не вгадуємо**, а віддаємо на
ручний перегляд. Хибна категорія гірша за порожню: товар потрапляє туди, де
його не шукають, і фільтри до нього не застосовуються.

Запуск:
    python3 tools/toptul_rozetka_map.py                # звіт
    python3 tools/toptul_rozetka_map.py --save         # у таблицю
    python3 tools/toptul_rozetka_map.py --review       # лише спірні
"""
import argparse
import collections
import difflib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2.extras  # noqa: E402
from loguru import logger  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402

TREE = os.path.join(BASE_DIR, 'docs', 'rozetka_seller_categories.json')
FEED = os.getenv('TOPTUL_FEED_FILE', '/tmp/toptul.xml')
REVIEW = os.path.join(BASE_DIR, 'docs', 'toptul_rozetka_review.json')
MANUAL = os.path.join(BASE_DIR, 'docs', 'toptul_rozetka_manual.json')

# Пари «російський термін TOPTUL → український термін Rozetka». Беруться з
# фактичних назв обох дерев, не вигадуються. Без них збігаються лише ті
# назви, що схожі й так, а це менш ніж половина.
TERMS = {
    'отвертка': 'викрутка', 'отвертки': 'викрутки',
    'ключ': 'ключ', 'ключи': 'ключі',
    'головка': 'головка', 'головки': 'головки',
    'торцевые': 'торцеві', 'торцевая': 'торцева',
    'ударные': 'ударні', 'комбинированные': 'комбіновані',
    'накидные': 'накидні', 'рожковые': 'ріжкові',
    'трещоточные': 'тріскачні', 'трещотки': 'тріскачні',
    'динамометрические': 'динамометричні', 'имбусовые': 'імбусові',
    'съемники': 'знімачі', 'съемник': 'знімач',
    'наборы': 'набори', 'набор': 'набір',
    'инструмента': 'інструментів', 'инструмент': 'інструмент',
    'инструментов': 'інструментів',
    'краскопульты': 'фарбопульти', 'краскопульт': 'фарбопульт',
    'пневматические': 'пневматичні', 'пневматический': 'пневматичний',
    'домкраты': 'домкрати', 'домкрат': 'домкрат',
    'биты': 'біти', 'бита': 'біта', 'насадки': 'насадки',
    'плоскогубцы': 'плоскогубці', 'длинногубцы': 'довгогубці',
    'пассатижи': 'пасатижі', 'бокорезы': 'бокорізи',
    'молотки': 'молотки', 'молоток': 'молоток',
    'ножовки': 'ножівки', 'ножовка': 'ножівка',
    'напильники': 'напилки', 'зубила': 'зубила',
    'струбцины': 'струбцини', 'тиски': 'лещата',
    'шуруповерта': 'шуруповерта', 'сверла': 'свердла', 'сверло': 'свердло',
    'метчики': 'мітчики', 'плашки': 'плашки',
    'штангенциркули': 'штангенциркулі', 'рулетки': 'рулетки',
    'уровни': 'рівні', 'уровень': 'рівень',
    'манометры': 'манометри', 'компрессоры': 'компресори',
    'шланги': 'шланги', 'фитинги': 'фітинги',
    'ящики': 'скрині', 'сумки': 'сумки', 'тележки': 'візки',
    'перчатки': 'рукавички', 'очки': 'окуляри',
    'смазка': 'мастило', 'масла': 'оливи',
    'полива': 'поливу', 'полив': 'полив',
    'диагностическое': 'діагностичне', 'оборудование': 'обладнання',
    'воротки': 'воротки', 'удлинители': 'подовжувачі',
    'переходники': 'перехідники', 'карданы': 'кардани',
    'клещи': 'кліщі', 'ножницы': 'ножиці', 'резаки': 'різаки',
    'заклепочники': 'заклепувальники', 'пистолеты': 'пістолети',
    'фонари': 'ліхтарі', 'зеркала': 'дзеркала',
    'краски': 'фарби', 'шпатели': 'шпателі',
    'подшипников': 'підшипників', 'подшипник': 'підшипник',
    'колес': 'коліс', 'колесо': 'колесо',
    'тормозов': 'гальм', 'тормозные': 'гальмівні',
    'двигателя': 'двигуна', 'масляные': 'масляні',
    'воздушные': 'повітряні', 'воздуха': 'повітря',
    'измерительный': 'вимірювальний', 'измерения': 'вимірювання',
    # Другий прохід: терміни, яких бракувало найдорожчим категоріям
    # (за кількістю товарів у фіді).
    'трещоткой': 'тріскачні', 'трещеток': 'тріскачних',
    'гайковерты': 'гайковерти', 'гайковерт': 'гайковерт',
    'цанговые': 'цангові', 'соединения': 'зʼєднання',
    'развертки': 'розвертки', 'зенкеры': 'зенкери',
    'подъемники': 'підйомники', 'подъемник': 'підйомник',
    'шприцы': 'шприци', 'смазки': 'мастила',
    'круглогубцы': 'круглогубці', 'стопорных': 'стопорних',
    'колец': 'кілець', 'ремкомплекты': 'ремкомплекти',
    'штуцеры': 'штуцери', 'быстросъемные': 'швидкознімні',
    'насадкой': 'насадкою', 'ступичные': 'маточинні',
    'измерители': 'вимірювачі', 'температуры': 'температури',
    'рулевых': 'рульових', 'шаровых': 'кульових',
    'гаечных': 'гайкових', 'слива': 'зливу', 'откачки': 'відкачування',
    'масла': 'оливи', 'зарядные': 'зарядні', 'станции': 'станції',
    'станки': 'стенди', 'форсунки': 'форсунки', 'форсунок': 'форсунок',
    'резьбовые': 'різьбові', 'аксессуары': 'аксесуари',
    'расходные': 'витратні', 'материалы': 'матеріали',
}

STOP = {'для', 'и', 'та', 'й', 'з', 'с', 'в', 'до', 'по', 'та', 'the'}


def norm_tokens(name: str) -> list:
    """Слова в нижньому регістрі, з перекладом термінів і обрізанням закінчень."""
    words = re.split(r'[^\wʼ\'-]+', (name or '').lower())
    out = []
    for w in words:
        w = w.strip('-')
        if not w or w in STOP or len(w) < 3:
            continue
        out.append(TERMS.get(w, w))
    return out


# Обрізання основи до 6 символів здавалось безпечним і дало «Компрессоры» →
# «Компресометри» з оцінкою 1.0: обидва слова перетворювались на «компре».
# Тому слова порівнюються цілими, а різні відмінки покриває нечіткий збіг.
TOKEN_HIT = 0.82


def _token_match(x: str, y: str) -> bool:
    if x == y:
        return True
    if abs(len(x) - len(y)) > 4:
        return False
    return difflib.SequenceMatcher(None, x, y).ratio() >= TOKEN_HIT


def score(a: str, b: str) -> float:
    """0..1. Скільки слів одного заголовка має пару в іншому."""
    ta, tb = norm_tokens(a), norm_tokens(b)
    if not ta or not tb:
        return 0.0
    used, hits = set(), 0
    for x in ta:
        for j, y in enumerate(tb):
            if j not in used and _token_match(x, y):
                used.add(j)
                hits += 1
                break
    # Вкладеність важливіша за симетричний збіг: назва TOPTUL зазвичай
    # детальніша за категорію Rozetka («Краскопульты пневматические» проти
    # «Фарбопульти»), і зайве уточнення не має топити правильну відповідь.
    cover = hits / min(len(ta), len(tb))
    jac = hits / max(len(ta), len(tb))
    seq = difflib.SequenceMatcher(None, ' '.join(sorted(ta)),
                                  ' '.join(sorted(tb))).ratio()
    return round(0.5 * cover + 0.3 * jac + 0.2 * seq, 3)


def load_targets() -> list:
    tree = json.load(open(TREE))
    kids = collections.Counter(r['parent'] for r in tree if r.get('parent'))
    # Ціль мапінгу — ЛИСТ, а не розділ. Мапінг у розділ верхнього рівня і був
    # головним дефектом старої таблиці.
    return [r for r in tree if r['rz_id'] not in kids and r['depth'] >= 1]


def load_source() -> list:
    root = ET.parse(FEED).getroot()
    shop = root.find('shop')
    names = {c.get('id'): (c.text or '') for c in shop.find('categories').findall('category')}
    use = collections.Counter(o.findtext('categoryId')
                              for o in shop.find('offers').findall('offer'))
    return [{'toptul_id': cid, 'toptul_name': names.get(cid, ''), 'goods': n}
            for cid, n in use.most_common() if names.get(cid)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--save', action='store_true')
    ap.add_argument('--review', action='store_true')
    ap.add_argument('--auto', type=float, default=0.62)
    a = ap.parse_args()

    targets = load_targets()
    source = load_source()
    logger.info(f'Категорій TOPTUL у вжитку: {len(source)}; '
                f'листових категорій Rozetka: {len(targets)}')

    # Ручні відповідності мають безумовний пріоритет. Автоматика на цих
    # позиціях помилялась змістовно, а не трохи: «Компрессоры поршневые» вона
    # вела в «Компресометри», пневмошланги — у поливні, розпилювачі фарби —
    # у товщиноміри фарби. Кожна така помилка тиха: категорія існує, оцінка
    # висока, товар просто лежить не там.
    by_id = {t['rz_id']: t for t in targets}
    manual = {}
    if os.path.exists(MANUAL):
        raw = json.load(open(MANUAL))
        for name, rid in raw.items():
            if name.startswith('_'):
                continue
            if rid not in by_id:
                logger.error(f'ручна відповідність «{name}» → {rid}: '
                             f'такої листової категорії немає, пропущено')
                continue
            manual[name.strip().lower()] = by_id[rid]
        logger.info(f'Ручних відповідностей завантажено: {len(manual)}')

    rows = []
    for s in source:
        hit = manual.get((s['toptul_name'] or '').strip().lower())
        if hit:
            rows.append({**s, 'rz_id': hit['rz_id'], 'rz_name': hit['rz_name'],
                         'score': 1.0, 'runner_up': 0.0, 'tier': 'manual'})
            continue
        best = sorted(((score(s['toptul_name'], t['rz_name']), t) for t in targets),
                      key=lambda x: -x[0])[:2]
        top_sc, top_t = best[0]
        second = best[1][0] if len(best) > 1 else 0.0
        # Впевнено — тільки коли найкращий варіант помітно кращий за другий.
        tier = ('auto' if top_sc >= a.auto and top_sc - second >= 0.08
                else 'review' if top_sc >= 0.35 else 'none')
        rows.append({**s, 'rz_id': top_t['rz_id'] if tier != 'none' else None,
                     'rz_name': top_t['rz_name'] if tier != 'none' else None,
                     'score': top_sc, 'runner_up': second, 'tier': tier})

    by = collections.Counter(r['tier'] for r in rows)
    goods = collections.Counter()
    for r in rows:
        goods[r['tier']] += r['goods']
    print()
    print(f"{'рівень':10} {'категорій':>10} {'товарів':>9}")
    for t in ('manual', 'auto', 'review', 'none'):
        print(f'{t:10} {by[t]:10} {goods[t]:9}')
    print(f"{'усього':10} {len(rows):10} {sum(goods.values()):9}")

    show = [r for r in rows if r['tier'] == ('review' if a.review else 'auto')]
    print(f"\n--- {'спірні' if a.review else 'впевнені'} (перші 30) ---")
    for r in show[:30]:
        print(f"  {r['goods']:4}  {r['toptul_name'][:38]:40} → "
              f"{(r['rz_name'] or '—')[:34]:36} {r['score']}")

    json.dump([r for r in rows if r['tier'] in ('review', 'none')], open(REVIEW, 'w'),
              ensure_ascii=False, indent=1)
    logger.info(f'На ручний перегляд: {REVIEW}')

    if a.save:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""CREATE TABLE IF NOT EXISTS toptul_rozetka_category_map (
            toptul_id TEXT PRIMARY KEY, toptul_name TEXT,
            rz_id BIGINT, rz_name TEXT, goods INT,
            score NUMERIC, tier TEXT, verified BOOL DEFAULT FALSE,
            updated_at TIMESTAMPTZ DEFAULT NOW())""")
        for r in rows:
            cur.execute("""INSERT INTO toptul_rozetka_category_map
                (toptul_id, toptul_name, rz_id, rz_name, goods, score, tier, verified)
                VALUES (%(toptul_id)s,%(toptul_name)s,%(rz_id)s,%(rz_name)s,
                        %(goods)s,%(score)s,%(tier)s,%(tier)s='manual')
                ON CONFLICT (toptul_id) DO UPDATE SET
                  rz_id=EXCLUDED.rz_id, rz_name=EXCLUDED.rz_name,
                  goods=EXCLUDED.goods, score=EXCLUDED.score,
                  tier=EXCLUDED.tier, updated_at=NOW(),
                  verified=(EXCLUDED.tier='manual')
                WHERE NOT toptul_rozetka_category_map.verified
                   OR EXCLUDED.tier='manual'""", r)
        conn.commit()
        cur.close(); conn.close()
        logger.success(f'Збережено {len(rows)} записів; '
                       f'рядки з verified=TRUE не чіпались')


if __name__ == '__main__':
    main()
