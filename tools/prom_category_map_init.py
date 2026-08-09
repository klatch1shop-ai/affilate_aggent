#!/usr/bin/env python3
"""Мапінг категорій Epicentr → Prom для NOIRE.

Чому через Epicentr, а не напряму з SexOpt: мапінг SexOpt→Epicentr уже
пройшов два цикли аудиту й виправлень, тобто товар у ньому вже класифіковано
перевірено. Додати треба лише один шар — 33 відповідності замість 170+
окремих категорій постачальника.

Два правила, які визначили вибір категорій:

  1. Обходимо «…загальне». Правила оформлення карток Prom прямо радять їх
     уникати («менше трафіку»), і тарифи це підтверджують економічно:
     25.00% проти 18.88% у конкретних категоріях — на третину дорожче.

  2. Де дерево Prom грубіше за Epicentr, кілька категорій зливаються в одну
     (ерекційні кільця + насадки на член → 161016). Де навпаки тонше —
     розділяємо за назвою товару через name_rule.

Запуск:
    python3 tools/prom_category_map_init.py --dry
    python3 tools/prom_category_map_init.py
"""
import argparse
import os
import sys

import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402

SOURCE = 'noire'

# (epicentr_code, prom_id, name_rule, confidence, reasoning)
# name_rule — регулярка по назві товару; спрацьовує ПЕРШОЮ, якщо збігається,
# інакше діє рядок без правила для того самого epicentr_code.
MAP = [
    ('9466', '161011',   None, 1.00, 'Вібратори → Вібратори. Пряма відповідність.'),
    ('9458', '161007',   None, 1.00, 'Фетиш та BDSM → Бдсм-іграшки. Пряма відповідність.'),
    ('9472', '161013',   None, 1.00, 'Мастурбатори → Мастурбатори.'),
    ('9480', '161010',   None, 1.00, 'Фалоімітатори → Фалоімітатори.'),
    ('9484', '161014',   None, 1.00, 'Анальні пробки → Анальні пробки.'),
    ('9482', '161012',   None, 1.00, 'Страпони → Страпони.'),
    ('9488', '16102104', None, 1.00, 'Масажери простати → Масажери простати.'),
    ('9468', '161015',   None, 1.00, 'Секс-ляльки → Секс-ляльки.'),
    ('9456', '161020',   None, 1.00, 'Секс-машини → Секс-машини.'),
    ('9578', '161019',   None, 1.00, 'Меблі для сексу → Меблі для сексу.'),
    ('3275', '16131201', None, 1.00, 'Презервативи → Презервативи. Найнижча ставка гілки, 15.42%.'),

    # Дерево Prom грубіше: дві категорії Epicentr в одну
    ('9470', '161016', None, 0.95,
     'Ерекційні кільця → «Насадки на член та ерекційні кільця». Prom обʼєднує їх з насадками.'),
    ('9474', '161016', None, 0.95,
     'Насадки на член → та сама обʼєднана категорія, що й ерекційні кільця.'),
    ('9486', '161014', None, 0.90,
     'Анальні кульки та намисто → Анальні пробки. Окремої категорії для кульок Prom не має.'),
    ('9548', '161014', None, 0.85,
     'Анальні розширювачі → Анальні пробки. Найближче доречне; окремої категорії немає.'),
    ('9616', '161012', None, 0.90,
     'Аксесуари для страпонів → Страпони. Prom не виділяє аксесуари окремо.'),
    ('9620', '161013', None, 0.90,
     'Аксесуари для мастурбаторів → Мастурбатори. Аналогічно.'),

    # Дерево Prom тонше: розділяємо за назвою
    ('9476', '16102105', r'екстендер|extender|подовжувач', 0.95,
     'Екстендери та помпи → Екстендери, коли в назві саме екстендер.'),
    ('9476', '161017', None, 0.95,
     'Екстендери та помпи → Вакуумні помпи (решта). У Prom це дві різні категорії.'),
    ('9478', '16102102', r'тренажер|кегел|kegel', 0.95,
     'Вагінальні кульки та тренажери → Тренажери кегеля, коли назва про тренажер.'),
    ('9478', '16102103', None, 0.95,
     'Вагінальні кульки та тренажери → Вагінальні кульки (решта).'),
    ('9452', '161003', r'лубрикант|змазк|гель-?змазк|\bglide\b|\blube\b', 0.95,
     'Збуджуючі засоби → Лубриканти, коли товар справді лубрикант. '
     'У Epicentr весь цей асортимент лежить в одній категорії, у Prom — у двох.'),
    ('9452', '161002', None, 0.90,
     'Збуджуючі засоби → Збуджуючі засоби (решта: стимулювальні гелі, афродизіаки).'),

    # Косметика: у Prom немає окремих категорій для масажних олій і свічок,
    # а «Інтимна косметика, загальне» обходимо через 25% і низький трафік
    ('9450', '161002', None, 0.75,
     'Еротичні масажні олії та косметика → Збуджуючі засоби. Окремої категорії '
     'для масажної косметики Prom не має; «…загальне» обходимо (25% проти 18.88%).'),
    ('9632', '161002', None, 0.75,
     'Олія для еротичного масажу → Збуджуючі засоби. Та сама причина.'),
    ('9630', '161002', None, 0.70,
     'Свічки для інтимного масажу → Збуджуючі засоби. Категорії свічок у Prom немає.'),
    ('9628', '161003', None, 0.85,
     'Засоби для орального сексу → Лубриканти. Це їстівні змазки й гелі.'),
    ('9636', '161002', None, 0.80, 'Пролонгатори → Збуджуючі засоби.'),
    ('9626', '161002', None, 0.80, 'Засоби для звуження піхви → Збуджуючі засоби.'),
    ('9624', '161002', None, 0.80, 'Засоби для збільшення члену → Збуджуючі засоби.'),

    ('9448', '161008', None, 1.00,
     'Догляд за секс-іграшками → Засоби для догляду за інтимними іграшками.'),
    ('9526', '161008', None, 0.80,
     'Аксесуари до інтимних іграшок → Засоби для догляду. Найближче доречне: '
     'окремої категорії аксесуарів немає, крім «…загальне».'),
    ('9550', '161008', None, 0.70,
     'Анальний душ → Засоби для догляду за інтимними іграшками. Категорії для '
     'анального душу Prom не має; це гігієнічний аксесуар.'),

    # Поза гілкою «Інтимні товари» — знайдено точнішу відповідність
    ('9454', '161610', None, 0.95,
     'Парфуми з феромонами → «Краса та здоровʼя > Парфумерія > Парфумерія з '
     'феромонами». Точніше за «Збуджуючі засоби»; ставка 18.15%.'),
    ('9460', '1767', None, 0.85,
     'Еротичні приколи та сувеніри → Еротичні подарунки. Ставка 16.82%.'),

    # Фаза 2 — записуємо, але позначаємо виключеними зі скоупу
    ('7216', '16100403', None, 0.95,
     'ВИКЛЮЧЕНО ЗІ СКОУПУ (Фаза 2). Еротична білизна → Жіноча еротична білизна і одяг.'),
    ('9464', '16100402', None, 0.80,
     'ВИКЛЮЧЕНО ЗІ СКОУПУ (Фаза 2). Еротичні костюми → Чоловіча/жіноча білизна і одяг.'),
]
EXCLUDED = {'7216', '9464'}


def ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prom_category_mapping (
            id              SERIAL PRIMARY KEY,
            epicentr_code   TEXT NOT NULL,
            prom_category_id TEXT NOT NULL,
            name_rule       TEXT,
            confidence      NUMERIC,
            excluded        BOOLEAN NOT NULL DEFAULT FALSE,
            reasoning       TEXT,
            source          TEXT NOT NULL DEFAULT 'noire',
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS prom_category_mapping_uk
                   ON prom_category_mapping
                   (epicentr_code, prom_category_id,
                    COALESCE(name_rule, ''), source)""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT code, name_ua FROM epicentr_intimate_categories")
    ep = {r['code']: r['name_ua'] for r in cur.fetchall()}
    cur.execute("SELECT category_id, name, full_path FROM prom_categories")
    pr = {str(r['category_id']): r for r in cur.fetchall()}
    cur.execute("""SELECT category_id, cpa_rate FROM prom_cpa_rates
                   WHERE source = %s""", (SOURCE,))
    rate = {r['category_id']: r['cpa_rate'] for r in cur.fetchall()}

    bad = [(e, p) for e, p, *_ in MAP if e not in ep or p not in pr]
    if bad:
        logger.error(f'Невідомі коди: {bad}')
        return
    general = [(e, p) for e, p, *_ in MAP if 'загальне' in pr[p]['name'].lower()]
    if general:
        logger.error(f'Потрапили в «…загальне»: {general}')
        return

    print(f"{'Epicentr':34} → {'Prom':38} {'ставка':>7}  правило")
    for e, p, rule, conf, why in MAP:
        mark = '  [Фаза 2]' if e in EXCLUDED else ''
        r = rate.get(p)
        print(f"{ep[e][:32]:34} → {pr[p]['name'][:36]:38} "
              f"{(str(r)+'%') if r else '—':>7}  {rule or ''}{mark}")

    if a.dry:
        print(f'\n(--dry: {len(MAP)} рядків не записано)')
        return

    ensure_table(cur)
    for e, p, rule, conf, why in MAP:
        cur.execute("""
            INSERT INTO prom_category_mapping
              (epicentr_code, prom_category_id, name_rule, confidence,
               excluded, reasoning, source)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (epicentr_code, prom_category_id,
                         COALESCE(name_rule,''), source)
            DO UPDATE SET confidence=EXCLUDED.confidence,
                          excluded=EXCLUDED.excluded,
                          reasoning=EXCLUDED.reasoning
        """, (e, p, rule, conf, e in EXCLUDED, why, SOURCE))
    conn.commit()
    logger.success(f'Записано {len(MAP)} відповідностей')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
