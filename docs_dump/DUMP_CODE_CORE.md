# DUMP_CODE_CORE.md — повний код критичних файлів (коміт 24bcf0e)

### `shared/utils/pricing.py` — 497 рядків

````python
"""
shared/utils/pricing.py
=======================
Централізована утиліта ціноутворення для всіх маркетплейсів.

Формула: наша_ціна = РРЦ / (1 - комісія_маркетплейсу)
Округлення до 10 грн, мінімум 40 грн.

Використання:
    from shared.utils.pricing import calc_price, get_prom_cpa, get_rozetka_commission, get_epicentr_cpa
"""

import os
import sys
import json
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# =============================================
# КОНСТАНТИ
# =============================================

MIN_PRICE = 40.0
ROUND_TO = 10
DEFAULT_PROM_CPA = 0.15
DEFAULT_EPICENTR_CPA = 0.15
DEFAULT_ROZETKA_CPA = 0.18

# =============================================
# МАППІНГ КАТЕГОРІЙ: РОСІЙСЬКА → УКРАЇНСЬКА
# Потрібен бо Prom API повертає категорії рос.
# а prom_cpa_rates містить українські назви
# =============================================

CATEGORY_MAP_RU_UK = {
    # Головки та воротки
    'Торцевые головки':                              'торцеві головки',
    'Воротки, трещотки':                             'воротки тріскачки',
    # Ключі
    'Комбинированные ключи':                         'комбіновані ключі',
    'Накидные ключи':                                'накидні ключі',
    'Торцевые ключи':                                'торцеві ключі',
    'Наборы ключей':                                 'набори ключів',
    'Рожковые ключи':                                'ріжкові ключі',
    'Динамометрические ключи':                       'динамометричні ключі',
    'Разводные ключи':                               'розвідні ключі',
    'Разрезные ключи':                               'торцеві ключі',
    'Трубные ключи':                                 'трубні ключі',
    'Балонные ключи':                                'балонні ключі',
    'Шестигранные ключи':                            'шестигранні ключі',
    'Мультипликаторы ключи':                         'торцеві ключі',
    'Серповидные ключи':                             'торцеві ключі',
    # Викрутки та біти
    'Отвертки':                                      'викрутки',
    'Отверточные биты':                              'викруткові біти',
    'Аккумуляторные отвертки':                       'дрилі шуруповерти',
    # Плоскогубці
    'Пассатижи, плоскогубцы, тонкогубцы':            'пасатижі плоскогубці тонкогубці',
    'Зажимные клещи':                                'затискні кліщі',
    'Бокорезы, кусачки':                             'бокорізи кусачки',
    'Монтажные пинцеты':                             'пасатижі плоскогубці тонкогубці',
    'Щипцы':                                         'пасатижі плоскогубці тонкогубці',
    # Молотки
    'Молотки, кувалды, киянки':                      'молотки кувалди киянки',
    # Знімачі
    'Механические съемники':                         'механічні знімачі',
    'Съемники подшипников':                          'знімачі підшипників',
    'Съемники автомобильных фильтров':               'знімачі автомобільних фільтрів',
    'Съемники стопорных колец':                      'знімачі стопорних кілець',
    'Гидравлические съемники':                       'механічні знімачі',
    'Съемники обшивки':                              'механічні знімачі',
    # Набори
    'Наборы инструментов':                           'набори інструментів',
    # Пневматика
    'Пневматические краскопульты':                   'пневматичні фарбопульти',
    'Пневматические гайковерты':                     'пневматичні гайкокрути',
    'Пневмошлифмашины':                              'пневмошліфмашіни',
    'Компоненты пневматики':                         'компоненти пневматики',
    'Пневматические пистолеты подкачки шин':         'автомобільні насоси компресори манометри',
    'Пневматические продувочные пистолеты':          'компоненти пневматики',
    'Пневматические пескоструйные пистолеты':        'компоненти пневматики',
    'Пневматические степлеры':                       'компоненти пневматики',
    'Пневматические зубила':                         'пробійники зубила борідки',
    'Пневматические отбойные молотки':               'пневматичні гайкокрути',
    'Пневмодрели':                                   'дрилі шуруповерти',
    'Пневматические заклепочники':                   'компоненти пневматики',
    'Пневматические шприцы для смазки':              'шприци масляні та змащувальні',
    'Пневматические распылительные пистолеты':       'пневматичні фарбопульти',
    'Пневматические штукатурные распылители':        'пневматичні фарбопульти',
    'Пневматические шуруповерты':                    'дрилі шуруповерти',
    # Компресори
    'Компрессоры поршневые':                         'поршневі компресори',
    'Комплектующие для компрессоров':                'компоненти пневматики',
    # Вимірювальний інструмент
    'Термометры, пирометры, тепловизоры':            'термометри пірометри тепловізори',
    'Мультиметры':                                   'мультиметри',
    'Измерительные рулетки':                         'вимірювальні рулетки',
    'Лазерные дальномеры':                           'лазерні далекоміри',
    'Лазерные нивелиры, уровни, сканеры':            'лазерні нівеліри рівні сканери',
    'Микрометры':                                    'мікрометри',
    'Толщиномеры':                                   'товщиноміри',
    'Штангенинструмент':                             'штангенінструмент',
    'Анемометры':                                    'анемометри',
    'Влагомеры':                                     'вологоміри',
    'Тестеры для аккумуляторов':                     'тестери для акумуляторів',
    'Кабельные тестеры, wi-fi тестеры':              'кабельні тестери wi-fi тестери',
    'Технические эндоскопы, видеоскопы':             'технічні ендоскопи відеоскопи',
    'Компрессометры и масломеры автомобильные':      'компресометри і масломіри автомобільні',
    'Угломеры':                                      'штангенінструмент',
    'Строительные уровни':                           'лазерні нівеліри рівні сканери',
    'Тахометры, спидометры':                         'термометри пірометри тепловізори',
    'Силомеры, динамометры':                         'динамометричні ключі',
    'Циферблатные индикаторы':                       'штангенінструмент',
    'Рефрактометры':                                 'термометри пірометри тепловізори',
    'Шумомеры':                                      'термометри пірометри тепловізори',
    'Люксметры':                                     'термометри пірометри тепловізори',
    'Газоанализаторы':                               'термометри пірометри тепловізори',
    'Омметры':                                       'мультиметри',
    'Твердомеры':                                    'товщиноміри',
    'Течеискатели':                                  'термометри пірометри тепловізори',
    'Манометры':                                     'автомобільні насоси компресори манометри',
    # Зубила
    'Пробойники, зубила, бородки':                   'пробійники зубила борідки',
    # Лещата та струбцини
    'Тиски':                                         'лещата',
    'Струбцины и зажимы':                            'струбцини і затискачі',
    # Домкрати та підйомники
    'Автомобильные домкраты, подставки':             'автомобільні домкрати підставки',
    'Подъемники автомобильные':                      'автомобільні домкрати підставки',
    'Гидравлические подкатные краны':                'гідравлічні підкатні крани',
    'Трансмиссионные стойки':                        'трансмісійні стійки',
    'Подъемники, лебедки, тали':                     'автомобільні домкрати підставки',
    # Шиномонтаж
    'Шиномонтажные станки':                          'комплектуючі для шиномонтажу',
    'Балансировочные станки':                        'комплектуючі для шиномонтажу',
    'Комплектующие для шиномонтажа':                 'комплектуючі для шиномонтажу',
    'Вулканизаторы для автомобильных шин и камер':   'комплектуючі для шиномонтажу',
    'Инструменты для ремонта и восстановления шин':  'інструменти для ремонту і відновлення шин',
    # Діагностика
    'Автомобильные диагностические сканеры':         'автомобільні діагностичні сканери',
    'Стенды регулировки развал-схождения колес':     'автомобільні діагностичні сканери',
    # Електроінструмент
    'Дрели, шуруповерты':                            'дрилі шуруповерти',
    'Электрические гайковерты':                      'електричні гайковерти',
    'Электрические удлинители':                      'електричні подовжувачі',
    # Ящики та сумки
    'Ящики, сумки для инструментов':                 'ящики сумки для інструментів',
    'Шкафы, тумбы и тележки инструментальные':       'ящики сумки для інструментів',
    # Запчастини
    'Комплектующие и запчасти для инструмента':      'запчастини для інструменту',
    # Насоси та компресори
    'Автомобильные насосы, компрессоры и манометры': 'автомобільні насоси компресори манометри',
    # Паяльники
    'Паяльники':                                     'паяльники',
    'Комплектующие для сварки и пайки':              'паяльники',
    'Аппараты контактной сварки':                    'паяльники',
    # Напилки
    'Напильники и надфили':                          'напилки та надфілі',
    # Болторізи
    'Болторезы':                                     'болторези',
    # Ножиці для труб
    'Ручные труборезы, ножницы для труб':            'ручні труборізи ножиці для труб',
    'Секторные ножницы, тросорезы':                  'ручні труборізи ножиці для труб',
    # Лежаки
    'Лежаки автослесарные подкатные':                'лежаки автослюсарні підкатні',
    # Магнітний інструмент
    'Магнитный инструмент':                          'магнітний інструмент',
    # Шприци
    'Шприцы маслянные и смазочные':                  'шприци масляні та змащувальні',
    # Освітлення
    'Переносные светильники':                        'переносні світильники',
    # Гідравліка
    'Гидравлические растяжки':                       'гідравлічні розтяжки',
    # Масло
    'Оборудование для замены масел и смазок':        'шприци масляні та змащувальні',
    # Заклепочники
    'Ручные заклепочники':                           'компоненти пневматики',
    'Ручные обжимные инструменты':                   'компоненти пневматики',
    # Загальне
    'Товары, общее':                                 'набори інструментів',
}


def translate_category(category_name: str) -> str:
    """
    Перекладає назву категорії з російської на українську.
    Якщо переклад не знайдено — повертає оригінал.
    """
    if not category_name:
        return ''
    translated = CATEGORY_MAP_RU_UK.get(category_name.strip())
    if translated:
        return translated
    # Спробуємо без зайвих пробілів
    translated = CATEGORY_MAP_RU_UK.get(category_name.strip())
    return translated or category_name


# =============================================
# 1. PROM.UA — CPA ПО КАТЕГОРІЇ
# =============================================

def get_prom_cpa(prom_category_name: str) -> float:
    """
    Повертає комісію Prom для категорії товару.

    Алгоритм:
    1. Переклад RU→UK через словник
    2. Точний збіг в prom_cpa_rates
    3. Часткове входження
    4. Зворотнє входження
    5. Fallback 15%

    Args:
        prom_category_name: назва категорії з Prom API (може бути рос. або укр.)

    Returns:
        float: комісія у частках (0.15 = 15%)
    """
    if not prom_category_name:
        return DEFAULT_PROM_CPA

    # Спочатку пробуємо переклад
    translated = translate_category(prom_category_name)
    name = translated.strip().lower()

    try:
        conn = get_connection()
        cur = conn.cursor()

        # Крок 1: точний збіг
        cur.execute(
            'SELECT cpa_rate FROM prom_cpa_rates WHERE LOWER(category_name) = %s',
            (name,)
        )
        row = cur.fetchone()
        if row:
            rate = float(row['cpa_rate']) / 100.0
            logger.debug(f'Prom CPA точний: "{prom_category_name}" → {rate*100:.2f}%')
            cur.close(); conn.close()
            return rate

        # Крок 2: часткове входження
        cur.execute(
            'SELECT category_name, cpa_rate FROM prom_cpa_rates WHERE LOWER(category_name) LIKE %s ORDER BY LENGTH(category_name) ASC LIMIT 1',
            (f'%{name}%',)
        )
        row = cur.fetchone()
        if row:
            rate = float(row['cpa_rate']) / 100.0
            logger.debug(f'Prom CPA частковий: "{prom_category_name}" → "{row["category_name"]}" → {rate*100:.2f}%')
            cur.close(); conn.close()
            return rate

        # Крок 3: зворотнє входження
        cur.execute(
            "SELECT category_name, cpa_rate FROM prom_cpa_rates WHERE %s LIKE CONCAT('%%', LOWER(category_name), '%%') ORDER BY LENGTH(category_name) DESC LIMIT 1",
            (name,)
        )
        row = cur.fetchone()
        if row:
            rate = float(row['cpa_rate']) / 100.0
            logger.debug(f'Prom CPA зворотній: "{prom_category_name}" → "{row["category_name"]}" → {rate*100:.2f}%')
            cur.close(); conn.close()
            return rate

        cur.close(); conn.close()
        logger.warning(f'Prom CPA не знайдено: "{prom_category_name}" (translated: "{translated}") → fallback {DEFAULT_PROM_CPA*100:.0f}%')
        return DEFAULT_PROM_CPA

    except Exception as e:
        logger.error(f'get_prom_cpa помилка: {e}')
        return DEFAULT_PROM_CPA


# =============================================
# 2. РОЗЕТКА — CPA ПО КАТЕГОРІЇ ТА ЦІНІ
# =============================================

def get_rozetka_commission(rozetka_category_id, price: float) -> float:
    """
    Повертає комісію Розетки з урахуванням діапазону ціни.

    Розетка: чим дорожчий товар — тим менша комісія.

    Args:
        rozetka_category_id: ID категорії Розетки (int або str)
        price: ціна товару в гривнях

    Returns:
        float: комісія у частках (0.18 = 18%)
    """
    if not rozetka_category_id:
        return DEFAULT_ROZETKA_CPA

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            'SELECT price_ranges, base_commission FROM rozetka_cpa_rates WHERE category_id = %s',
            (str(rozetka_category_id),)
        )
        row = cur.fetchone()
        cur.close(); conn.close()

        if not row:
            logger.warning(f'Розетка: категорія {rozetka_category_id} не знайдена → fallback {DEFAULT_ROZETKA_CPA*100:.0f}%')
            return DEFAULT_ROZETKA_CPA

        ranges = row['price_ranges']
        if isinstance(ranges, str):
            ranges = json.loads(ranges)

        for price_range in ranges:
            lo, hi, rate = price_range
            if lo <= price <= hi:
                return rate / 100.0

        return ranges[-1][2] / 100.0

    except Exception as e:
        logger.error(f'get_rozetka_commission помилка: {e}')
        return DEFAULT_ROZETKA_CPA


# =============================================
# 3. ЄПІЦЕНТР — CPA ПО КАТЕГОРІЇ
# =============================================

def get_epicentr_cpa(epicentr_category_name: str) -> float:
    """
    Повертає комісію Єпіцентру для категорії товару.

    Args:
        epicentr_category_name: назва категорії Єпіцентру з my_products

    Returns:
        float: комісія у частках (0.15 = 15%)
    """
    if not epicentr_category_name:
        return DEFAULT_EPICENTR_CPA

    name = epicentr_category_name.strip().lower()

    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            'SELECT cpa_rate FROM epicentr_cpa_rates WHERE LOWER(category_name) = %s',
            (name,)
        )
        row = cur.fetchone()
        if row:
            cur.close(); conn.close()
            return float(row['cpa_rate']) / 100.0

        cur.execute(
            'SELECT cpa_rate FROM epicentr_cpa_rates WHERE LOWER(category_name) LIKE %s ORDER BY LENGTH(category_name) ASC LIMIT 1',
            (f'%{name}%',)
        )
        row = cur.fetchone()
        if row:
            cur.close(); conn.close()
            return float(row['cpa_rate']) / 100.0

        cur.close(); conn.close()
        logger.warning(f'Єпіцентр CPA не знайдено: "{epicentr_category_name}" → fallback {DEFAULT_EPICENTR_CPA*100:.0f}%')
        return DEFAULT_EPICENTR_CPA

    except Exception as e:
        logger.error(f'get_epicentr_cpa помилка: {e}')
        return DEFAULT_EPICENTR_CPA


# =============================================
# 4. ГОЛОВНА ФУНКЦІЯ РОЗРАХУНКУ ЦІНИ
# =============================================

def calc_price(
    rrс_price: float,
    commission_rate: float,
    min_price: float = MIN_PRICE,
    round_to: int = ROUND_TO
) -> float:
    """
    Розраховує нашу ціну продажу.

    Формула: наша_ціна = РРЦ / (1 - комісія)
    Округлення до round_to грн вгору.
    Мінімум min_price грн.
    """
    if rrс_price <= 0:
        return min_price

    if commission_rate >= 1.0:
        logger.error(f'Некоректна комісія: {commission_rate}')
        commission_rate = DEFAULT_PROM_CPA

    raw_price = rrс_price * (1.0 + commission_rate)
    rounded = round(raw_price / round_to) * round_to
    if rounded < raw_price:
        rounded += round_to

    return max(rounded, min_price)


# =============================================
# 5. ЗРУЧНІ ФУНКЦІЇ ДЛЯ КОЖНОГО МАРКЕТПЛЕЙСУ
# =============================================

def calc_prom_price(rrс_price: float, prom_category_name: str) -> tuple:
    """
    Розраховує ціну для Prom.ua.
    Returns: (наша_ціна, комісія_відсоток)
    """
    commission = get_prom_cpa(prom_category_name)
    price = calc_price(rrс_price, commission)
    return price, round(commission * 100, 2)


def calc_rozetka_price(rrс_price: float, rozetka_category_id) -> tuple:
    """
    Розраховує ціну для Розетки.
    Returns: (наша_ціна, комісія_відсоток)
    """
    commission = get_rozetka_commission(rozetka_category_id, rrс_price)
    price = calc_price(rrс_price, commission)
    return price, round(commission * 100, 2)


def calc_epicentr_price(rrс_price: float, epicentr_category_name: str) -> tuple:
    """
    Розраховує ціну для Єпіцентру.
    Returns: (наша_ціна, комісія_відсоток)
    """
    commission = get_epicentr_cpa(epicentr_category_name)
    price = calc_price(rrс_price, commission)
    return price, round(commission * 100, 2)


# =============================================
# 6. ТЕСТ / ДЕМО
# =============================================

if __name__ == '__main__':
    print('=== Тест pricing.py ===\n')

    print('--- Базова формула calc_price ---')
    test_cases = [
        (1000, 0.15,   'Prom стандарт 15%'),
        (1000, 0.0905, 'Prom компресори 9.05%'),
        (1000, 0.1027, 'Prom електр.гайковерти 10.27%'),
        (30,   0.15,   'Мінімум 40 грн'),
        (414480, 0.1466, 'Дорогий діагностика'),
    ]
    for rrс, comm, label in test_cases:
        price = calc_price(rrс, comm)
        print(f'  {label:35s}: РРЦ={rrс:>10.0f} | {comm*100:5.2f}% | ціна={price:>10.0f} | маржа={price-rrс:>8.0f}')

    print('\n--- Переклад категорій RU→UK ---')
    ru_tests = [
        ('Торцевые головки',             'торцеві головки'),
        ('Отвертки',                     'викрутки'),
        ('Компрессоры поршневые',        'поршневі компресори'),
        ('Пневматические гайковерты',    'пневматичні гайкокрути'),
        ('Динамометрические ключи',      'динамометричні ключі'),
    ]
    for ru, expected in ru_tests:
        result = translate_category(ru)
        ok = '✅' if result == expected else '❌'
        print(f'  {ok} "{ru}" → "{result}"')

    print('\n--- Prom CPA з БД (через переклад) ---')
    prom_tests = [
        'Торцевые головки',
        'Отвертки',
        'Компрессоры поршневые',
        'Пневматические гайковерты',
        'Динамометрические ключи',
        'Съемники подшипников',
        'Мультиметры',
        'Наборы инструментов',
    ]
    for cat in prom_tests:
        cpa = get_prom_cpa(cat)
        print(f'  {cat:45s} → {cpa*100:.2f}%')

    print('\n--- Розетка: "1.5 Інструменти" (cat_id=4628758) ---')
    for price in [500, 5000, 15000, 50000]:
        comm = get_rozetka_commission('4628758', price)
        our = calc_price(price, comm)
        print(f'  РРЦ={price:>8.0f} | комісія={comm*100:.0f}% | наша={our:>8.0f} | маржа={our-price:>6.0f}')

````

### `agents/orders/price_engine.py` — 794 рядків

````python
"""
agents/orders/price_engine.py
==============================
Головний двигун ціноутворення.

Алгоритм:
1. Завантажує XML фід TOPTUL (актуальні РРЦ)
2. Для кожного товару:
   - Бере попередню ціну з price_history
   - Розраховує нову: feed_price * (1 + CPA)
   - Визначає чи є зміна
   - Записує в price_history (тільки зміни після першого запуску)
3. Оновлює my_products.price_our
4. Оновлює ціни на Prom через API (батчами)
5. Telegram звіт + CSV файл алертів

Режими запуску:
    python3 price_engine.py                  # щоденний (тільки зміни)
    python3 price_engine.py --full           # повний знімок всіх товарів
    python3 price_engine.py --dry-run        # без запису змін
    python3 price_engine.py --no-prom        # без оновлення Prom API
    python3 price_engine.py --limit 100      # тест на N товарах
    python3 price_engine.py --report-only    # тільки звіт без оновлення
"""

import os, sys, requests, time, csv, json, argparse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection
from shared.utils.pricing import calc_price, get_prom_cpa, DEFAULT_PROM_CPA

# =============================================
# КОНСТАНТИ
# =============================================

TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)

PROM_TOKEN = os.getenv('PROM_API_TOKEN')
PROM_HEADERS = {'Authorization': f'Bearer {PROM_TOKEN}'}
PROM_BASE = 'https://my.prom.ua/api/v1'

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')

LOGS_DIR = '/home/tek/agent-system/logs'

# Значення за замовчуванням (перезаписуються з БД)
DEFAULT_CONFIG = {
    'alert_threshold_pct':  20.0,
    'alert_threshold_high': 15.0,
    'high_price_threshold': 1000.0,
    'min_price':            40.0,
    'round_to':             10,
    'history_days_keep':    365,
    'stock_premium_pct':    0.0,
}


# =============================================
# TELEGRAM
# =============================================

def tg(text: str):
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_ADMIN, 'text': text, 'parse_mode': 'HTML'},
            timeout=15
        )
    except Exception as e:
        logger.error(f'Telegram: {e}')


def tg_file(path: str, caption: str = ''):
    try:
        with open(path, 'rb') as f:
            requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument',
                data={'chat_id': TELEGRAM_ADMIN, 'caption': caption, 'parse_mode': 'HTML'},
                files={'document': f},
                timeout=60
            )
    except Exception as e:
        logger.error(f'Telegram file: {e}')


# =============================================
# 1. КОНФІГУРАЦІЯ З БД
# =============================================

def load_config() -> dict:
    """Завантажує налаштування з price_engine_config."""
    config = DEFAULT_CONFIG.copy()
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('SELECT key, value FROM price_engine_config')
        for row in cur.fetchall():
            key = row['key']
            if key in config:
                try:
                    config[key] = type(DEFAULT_CONFIG[key])(row['value'])
                except (ValueError, TypeError):
                    pass
        cur.close(); conn.close()
    except Exception as e:
        logger.warning(f'Не вдалось завантажити config: {e} → використовуємо defaults')
    return config


def update_config(key: str, value: str):
    """Оновлює значення в price_engine_config."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO price_engine_config (key, value, updated_at) VALUES (%s, %s, NOW()) '
            'ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()',
            (key, str(value))
        )
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        logger.error(f'update_config: {e}')


# =============================================
# 2. ФІД TOPTUL
# =============================================

def load_feed() -> dict:
    """
    Завантажує XML фід TOPTUL.
    Returns: dict SKU → {price, available, stock}
    """
    logger.info('Завантажуємо фід TOPTUL...')
    try:
        resp = requests.get(TOPTUL_FEED, timeout=120)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        offers = root.find('shop').find('offers').findall('offer')

        feed = {}
        for offer in offers:
            sku_el = offer.find('vendorCode')
            sku = (sku_el.text or '').strip().upper() if sku_el is not None else ''
            if not sku:
                sku = (offer.get('id') or '').upper()
            if not sku:
                continue

            price_el = offer.find('price')
            price = float(price_el.text) if price_el is not None else 0.0
            available = offer.get('available', 'true') == 'true'
            stock_el = offer.find('stock_quantity')
            stock = stock_el.text if stock_el is not None else '*'

            feed[sku] = {
                'price': price,
                'available': available,
                'stock': stock or '*',
            }

        logger.success(f'Фід: {len(feed)} товарів')
        return feed

    except Exception as e:
        logger.error(f'Помилка фіду: {e}')
        return {}


# =============================================
# 3. ПОПЕРЕДНІ ЦІНИ З HISTORY
# =============================================

def load_previous_prices() -> dict:
    """
    Завантажує останні ціни з price_history для кожного SKU.
    Returns: dict SKU → {feed_price, our_price, date}
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT DISTINCT ON (sku)
                sku, feed_price, our_price, date
            FROM price_history
            ORDER BY sku, date DESC
        ''')
        result = {
            r['sku'].upper(): {
                'feed_price': float(r['feed_price']),
                'our_price': float(r['our_price']),
                'date': r['date'],
            }
            for r in cur.fetchall()
        }
        cur.close(); conn.close()
        logger.info(f'History: {len(result)} записів')
        return result
    except Exception as e:
        logger.error(f'load_previous_prices: {e}')
        return {}


# =============================================
# 4. ТОВАРИ З БД
# =============================================

def load_db_products(limit: int = None) -> list:
    """Завантажує товари з my_products."""
    conn = get_connection()
    cur = conn.cursor()

    # Перевіряємо наявність колонок категорій
    cur.execute('''
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'my_products'
        AND column_name IN ('prom_category_name', 'prom_group_name', 'prom_id')
    ''')
    existing = {r['column_name'] for r in cur.fetchall()}

    extra = ', '.join(c for c in ['prom_category_name', 'prom_group_name', 'prom_id'] if c in existing)
    if extra:
        extra = ', ' + extra

    query = f'''
        SELECT id, sku, name_uk, price_supplier, price_our{extra}
        FROM my_products
        WHERE price_supplier IS NOT NULL AND price_supplier > 0
        ORDER BY sku
    '''
    if limit:
        query += f' LIMIT {int(limit)}'

    cur.execute(query)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    logger.info(f'БД: {len(rows)} товарів')
    return rows


# =============================================
# 5. PROM API — ЗАВАНТАЖЕННЯ ТОВАРІВ
# =============================================

def load_prom_map() -> dict:
    """Завантажує SKU→prom_id з Prom API."""
    logger.info('Завантажуємо Prom API...')
    prom_map = {}
    last_id = None

    while True:
        params = {'limit': 100}
        if last_id:
            params['last_id'] = last_id
        try:
            resp = requests.get(
                f'{PROM_BASE}/products/list',
                headers=PROM_HEADERS,
                params=params,
                timeout=30
            )
            resp.raise_for_status()
            products = resp.json().get('products', [])
        except Exception as e:
            logger.error(f'Prom API: {e}')
            break

        if not products:
            break

        for p in products:
            sku = (p.get('sku') or '').strip().upper()
            if sku:
                prom_map[sku] = {
                    'id': p.get('id'),
                    'price': float(p.get('price') or 0),
                }

        last_id = products[-1]['id']
        if len(products) < 100:
            break
        time.sleep(0.35)

    logger.success(f'Prom: {len(prom_map)} товарів')
    return prom_map


# =============================================
# 6. ГОЛОВНА ЛОГІКА РОЗРАХУНКУ
# =============================================

def process_products(
    feed: dict,
    db_products: list,
    prev_prices: dict,
    config: dict,
    full_mode: bool = False,
) -> tuple:
    """
    Обробляє кожен товар: розраховує нову ціну, визначає зміни та алерти.

    Returns:
        tuple: (records_to_save, price_updates_for_prom, stats)
    """
    alert_threshold = config['alert_threshold_pct']
    alert_threshold_high = config['alert_threshold_high']
    high_price = config['high_price_threshold']
    min_price = config['min_price']
    round_to = int(config['round_to'])

    records = []        # записи для price_history
    prom_updates = []   # оновлення для Prom API
    stats = {
        'total': 0, 'in_feed': 0, 'not_in_feed': 0,
        'changed': 0, 'unchanged': 0,
        'price_up': 0, 'price_down': 0,
        'alerts': 0, 'unavailable': 0,
        'fallback_cpa': 0,
    }

    today = date.today()

    for product in db_products:
        sku = (product.get('sku') or '').strip().upper()
        if not sku:
            continue

        stats['total'] += 1
        feed_info = feed.get(sku)

        if not feed_info:
            stats['not_in_feed'] += 1
            # Якщо немає у фіді — пишемо запис про недоступність (тільки якщо змінилось)
            prev = prev_prices.get(sku)
            if prev and prev.get('available', True):
                # Був доступний, тепер немає — це зміна
                record = {
                    'sku': sku,
                    'date': today,
                    'feed_price': prev['feed_price'],
                    'our_price': prev['our_price'],
                    'prev_feed_price': prev['feed_price'],
                    'prev_our_price': prev['our_price'],
                    'feed_diff_pct': 0,
                    'our_diff_pct': 0,
                    'cpa_rate': 0,
                    'cpa_source': 'unavailable',
                    'available': False,
                    'stock': '-',
                    'is_change': True,
                    'is_alert': True,
                    'alert_reason': 'зник з фіду',
                    'prom_updated': False,
                }
                records.append(record)
                stats['alerts'] += 1
            continue

        stats['in_feed'] += 1
        new_feed_price = feed_info['price']
        available = feed_info['available']
        stock = feed_info['stock']

        if not available:
            stats['unavailable'] += 1

        # Визначаємо CPA
        prom_category = (product.get('prom_category_name') or '').strip()
        prom_group = (product.get('prom_group_name') or '').strip()
        cpa_source = 'default'

        if prom_category:
            cpa = get_prom_cpa(prom_category)
            if cpa != DEFAULT_PROM_CPA:
                cpa_source = prom_category
            elif prom_group:
                cpa = get_prom_cpa(prom_group)
                cpa_source = prom_group if cpa != DEFAULT_PROM_CPA else 'default'
        elif prom_group:
            cpa = get_prom_cpa(prom_group)
            cpa_source = prom_group if cpa != DEFAULT_PROM_CPA else 'default'
        else:
            cpa = DEFAULT_PROM_CPA

        if cpa_source == 'default':
            stats['fallback_cpa'] += 1

        # Розраховуємо нову ціну
        new_our_price = calc_price(new_feed_price, cpa, min_price, round_to)

        # Беремо попередні ціни
        prev = prev_prices.get(sku)
        prev_feed = prev['feed_price'] if prev else float(product.get('price_supplier') or 0)
        prev_our = prev['our_price'] if prev else float(product.get('price_our') or 0)

        # Розраховуємо зміни
        feed_diff_pct = ((new_feed_price - prev_feed) / prev_feed * 100) if prev_feed > 0 else 0
        our_diff_pct = ((new_our_price - prev_our) / prev_our * 100) if prev_our > 0 else 0

        # Визначаємо чи є зміна
        price_changed = abs(new_our_price - prev_our) >= 1.0 or abs(new_feed_price - prev_feed) >= 0.5
        availability_changed = prev and (prev.get('available', True) != available)
        is_change = price_changed or availability_changed or full_mode

        if not is_change:
            stats['unchanged'] += 1
            continue

        stats['changed'] += 1
        if our_diff_pct > 0:
            stats['price_up'] += 1
        elif our_diff_pct < 0:
            stats['price_down'] += 1

        # Визначаємо алерт
        threshold = alert_threshold_high if new_feed_price >= high_price else alert_threshold
        is_alert = abs(our_diff_pct) >= threshold or not available
        alert_reason = ''

        if not available:
            alert_reason = 'недоступний у фіді'
        if abs(our_diff_pct) >= threshold:
            direction = 'подорожчало' if our_diff_pct > 0 else 'подешевшало'
            alert_reason = (alert_reason + f' | {direction} на {abs(our_diff_pct):.1f}%').strip(' | ')

        if is_alert:
            stats['alerts'] += 1

        record = {
            'sku': sku,
            'date': today,
            'feed_price': new_feed_price,
            'our_price': new_our_price,
            'prev_feed_price': prev_feed,
            'prev_our_price': prev_our,
            'feed_diff_pct': round(feed_diff_pct, 2),
            'our_diff_pct': round(our_diff_pct, 2),
            'cpa_rate': round(cpa * 100, 2),
            'cpa_source': cpa_source,
            'available': available,
            'stock': stock,
            'is_change': is_change,
            'is_alert': is_alert,
            'alert_reason': alert_reason,
            'prom_updated': False,
        }
        records.append(record)

        # Готуємо для Prom API (тільки якщо ціна змінилась)
        if abs(new_our_price - prev_our) >= 1.0:
            prom_id = product.get('prom_id')
            if prom_id:
                prom_updates.append({'id': prom_id, 'price': new_our_price, 'sku': sku})

    return records, prom_updates, stats


# =============================================
# 7. ЗАПИС В БД
# =============================================

def save_history(records: list, dry_run: bool = False) -> int:
    """Зберігає записи в price_history і оновлює my_products."""
    if dry_run or not records:
        return 0

    conn = get_connection()
    cur = conn.cursor()
    saved = 0

    for r in records:
        try:
            cur.execute('''
                INSERT INTO price_history (
                    sku, date, feed_price, our_price,
                    prev_feed_price, prev_our_price,
                    feed_diff_pct, our_diff_pct,
                    cpa_rate, cpa_source,
                    available, stock,
                    is_change, is_alert, alert_reason,
                    prom_updated
                ) VALUES (
                    %(sku)s, %(date)s, %(feed_price)s, %(our_price)s,
                    %(prev_feed_price)s, %(prev_our_price)s,
                    %(feed_diff_pct)s, %(our_diff_pct)s,
                    %(cpa_rate)s, %(cpa_source)s,
                    %(available)s, %(stock)s,
                    %(is_change)s, %(is_alert)s, %(alert_reason)s,
                    %(prom_updated)s
                )
                ON CONFLICT (sku, date) DO UPDATE SET
                    feed_price      = EXCLUDED.feed_price,
                    our_price       = EXCLUDED.our_price,
                    prev_feed_price = EXCLUDED.prev_feed_price,
                    prev_our_price  = EXCLUDED.prev_our_price,
                    feed_diff_pct   = EXCLUDED.feed_diff_pct,
                    our_diff_pct    = EXCLUDED.our_diff_pct,
                    cpa_rate        = EXCLUDED.cpa_rate,
                    cpa_source      = EXCLUDED.cpa_source,
                    available       = EXCLUDED.available,
                    stock           = EXCLUDED.stock,
                    is_change       = EXCLUDED.is_change,
                    is_alert        = EXCLUDED.is_alert,
                    alert_reason    = EXCLUDED.alert_reason
            ''', r)

            # Оновлюємо my_products
            cur.execute(
                'UPDATE my_products SET price_supplier=%s, price_our=%s WHERE sku=%s',
                (r['feed_price'], r['our_price'], r['sku'])
            )
            saved += 1

        except Exception as e:
            logger.error(f'save_history {r["sku"]}: {e}')

    conn.commit()
    cur.close(); conn.close()
    logger.success(f'Збережено в history: {saved}')
    return saved


# =============================================
# 8. ОНОВЛЕННЯ PROM API
# =============================================

def update_prom_prices(
    prom_updates: list,
    prom_map: dict,
    records: list,
    dry_run: bool = False
) -> int:
    """Оновлює ціни на Prom батчами по 100."""
    if dry_run or not prom_updates:
        return 0

    # Збагачуємо prom_id з prom_map якщо не було в БД
    batch_data = []
    for upd in prom_updates:
        prom_id = upd.get('id')
        if not prom_id:
            prom_info = prom_map.get(upd['sku'].upper())
            prom_id = prom_info['id'] if prom_info else None
        if prom_id:
            batch_data.append({'id': prom_id, 'price': upd['price']})

    if not batch_data:
        return 0

    updated = 0
    updated_ids = set()

    for i in range(0, len(batch_data), 100):
        batch = batch_data[i:i+100]
        try:
            resp = requests.post(
                f'{PROM_BASE}/products/edit',
                headers=PROM_HEADERS,
                json=batch,
                timeout=30
            )
            if resp.status_code == 200:
                processed = resp.json().get('processed_ids', [])
                updated += len(processed)
                updated_ids.update(str(p) for p in processed)
                logger.success(f'Prom батч {i//100+1}: {len(processed)} оновлено')
            else:
                logger.error(f'Prom помилка {resp.status_code}: {resp.text[:200]}')
        except Exception as e:
            logger.error(f'Prom батч помилка: {e}')
        time.sleep(0.5)

    # Позначаємо prom_updated в history
    if updated_ids and records:
        conn = get_connection()
        cur = conn.cursor()
        today = date.today()
        for r in records:
            prom_info = prom_map.get(r['sku'].upper())
            if prom_info and str(prom_info['id']) in updated_ids:
                cur.execute(
                    'UPDATE price_history SET prom_updated=TRUE WHERE sku=%s AND date=%s',
                    (r['sku'], today)
                )
        conn.commit(); cur.close(); conn.close()

    return updated


# =============================================
# 9. ЗВІТ CSV
# =============================================

def write_alerts_csv(records: list, filepath: str):
    """Записує алерти в CSV."""
    alerts = [r for r in records if r['is_alert']]
    if not alerts:
        return None

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([
            'SKU', 'Ціна фіду стара', 'Ціна фіду нова', 'Зміна фіду %',
            'Наша ціна стара', 'Наша ціна нова', 'Зміна нашої %',
            'CPA %', 'Доступний', 'Залишок', 'Причина алерту'
        ])
        for r in sorted(alerts, key=lambda x: -abs(x['our_diff_pct'])):
            writer.writerow([
                r['sku'],
                f"{r['prev_feed_price']:.2f}",
                f"{r['feed_price']:.2f}",
                f"{r['feed_diff_pct']:+.2f}%",
                f"{r['prev_our_price']:.2f}",
                f"{r['our_price']:.2f}",
                f"{r['our_diff_pct']:+.2f}%",
                f"{r['cpa_rate']:.2f}%",
                'Так' if r['available'] else 'Ні',
                r['stock'],
                r['alert_reason'],
            ])

    logger.success(f'Алерти CSV: {filepath} ({len(alerts)} рядків)')
    return filepath


# =============================================
# 10. ОЧИЩЕННЯ СТАРИХ ЗАПИСІВ
# =============================================

def cleanup_old_history(days_keep: int):
    """Видаляє записи старші за days_keep днів."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cutoff = date.today() - timedelta(days=int(days_keep))
        cur.execute('DELETE FROM price_history WHERE date < %s', (cutoff,))
        deleted = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        if deleted > 0:
            logger.info(f'Очищено старих записів: {deleted} (старіше {cutoff})')
    except Exception as e:
        logger.error(f'cleanup: {e}')


# =============================================
# 11. ГОЛОВНИЙ ЗАПУСК
# =============================================

def run(
    full_mode: bool = False,
    dry_run: bool = False,
    no_prom: bool = False,
    limit: int = None,
    report_only: bool = False,
):
    start_time = datetime.now()
    mode_label = 'ПОВНИЙ' if full_mode else 'ЩОДЕННИЙ'
    logger.info(f'=== Price Engine {mode_label} старт ===')

    config = load_config()
    today_str = date.today().strftime('%Y%m%d_%H%M%S')
    alerts_file = f'{LOGS_DIR}/price_alerts_{today_str}.csv'

    # Завантажуємо дані
    feed = load_feed()
    if not feed:
        tg('⚠️ <b>Price Engine</b>: не вдалось завантажити фід TOPTUL')
        return

    db_products = load_db_products(limit=limit)
    prev_prices = load_previous_prices()

    is_first_run = len(prev_prices) == 0
    if is_first_run:
        logger.info('Перший запуск — збережемо повний знімок всіх товарів')
        full_mode = True

    # Завантажуємо Prom тільки якщо потрібно
    prom_map = {}
    if not no_prom and not dry_run and not report_only:
        prom_map = load_prom_map()

    # Обробляємо товари
    records, prom_updates, stats = process_products(
        feed, db_products, prev_prices, config, full_mode
    )

    elapsed_process = (datetime.now() - start_time).seconds

    # Зберігаємо в БД
    saved = 0
    if not report_only:
        saved = save_history(records, dry_run=dry_run)

    # Оновлюємо Prom
    prom_updated = 0
    if not no_prom and not dry_run and not report_only and prom_updates:
        prom_updated = update_prom_prices(prom_updates, prom_map, records)

    # Записуємо алерти в CSV
    alerts_path = None
    if records:
        alerts_path = write_alerts_csv(records, alerts_file)

    # Оновлюємо last_full_sync
    if full_mode and not dry_run:
        update_config('last_full_sync', date.today().isoformat())

    # Очищення старих записів
    if not dry_run and not report_only:
        cleanup_old_history(config['history_days_keep'])

    elapsed_total = (datetime.now() - start_time).seconds

    # Статистика
    alerts = [r for r in records if r['is_alert']]
    top_up = sorted([r for r in records if r['our_diff_pct'] > 0], key=lambda x: -x['our_diff_pct'])[:5]
    top_down = sorted([r for r in records if r['our_diff_pct'] < 0], key=lambda x: x['our_diff_pct'])[:5]

    mode_emoji = '🔄' if full_mode else '📅'
    msg = f'''{mode_emoji} <b>Price Engine — {mode_label}</b>
{date.today().strftime("%d.%m.%Y %H:%M")}

📦 Перевірено: {stats["total"]}
✅ У фіді: {stats["in_feed"]}
❓ Відсутні у фіді: {stats["not_in_feed"]}
🚫 Недоступні: {stats["unavailable"]}

💾 Збережено в history: {saved}
📈 Подорожчало: {stats["price_up"]}
📉 Подешевшало: {stats["price_down"]}
➡️ Без змін: {stats["unchanged"]}

⚠️ Алертів: {stats["alerts"]}
✅ Оновлено на Prom: {prom_updated}
🔄 Fallback CPA: {stats["fallback_cpa"]}
⏱ Час: {elapsed_total}с'''

    if top_up:
        msg += '\n\n📈 <b>Найбільше подорожчало:</b>'
        for r in top_up:
            msg += f'\n  {r["sku"]}: {r["prev_our_price"]:.0f}→{r["our_price"]:.0f} ({r["our_diff_pct"]:+.1f}%)'

    if top_down:
        msg += '\n\n📉 <b>Найбільше подешевшало:</b>'
        for r in top_down:
            msg += f'\n  {r["sku"]}: {r["prev_our_price"]:.0f}→{r["our_price"]:.0f} ({r["our_diff_pct"]:+.1f}%)'

    if dry_run:
        msg += '\n\n⚠️ <b>DRY RUN — зміни не збережено</b>'

    logger.success(msg.replace('<b>', '').replace('</b>', ''))

    if not dry_run:
        tg(msg)
        if alerts_path and alerts:
            tg_file(
                alerts_path,
                f'⚠️ Алерти цін {date.today().strftime("%d.%m.%Y")} — {len(alerts)} товарів'
            )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Price Engine — щоденне оновлення цін')
    parser.add_argument('--full', action='store_true',
                        help='Повний знімок всіх товарів (ігнорує unchanged)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Без запису в БД і Prom API')
    parser.add_argument('--no-prom', action='store_true',
                        help='Без оновлення Prom API')
    parser.add_argument('--limit', type=int, default=None,
                        help='Обмеження кількості товарів (для тесту)')
    parser.add_argument('--report-only', action='store_true',
                        help='Тільки аналіз без запису')
    args = parser.parse_args()

    run(
        full_mode=args.full,
        dry_run=args.dry_run,
        no_prom=args.no_prom,
        limit=args.limit,
        report_only=args.report_only,
    )

````

### `agents/orders/price_audit.py` — 471 рядків

````python
"""
agents/orders/price_audit.py
=============================
Аудит цін: порівнює поточні ціни в БД з новими розрахованими.

Алгоритм:
1. Завантажує XML фід TOPTUL (актуальні ціни постачальника)
2. Для кожного товару розраховує нову ціну: ціна_постачальника * (1 + CPA)
3. Порівнює з поточною ціною в БД
4. Записує повний лог змін у CSV файл
5. Окремий файл алертів для товарів зі зміною > ALERT_THRESHOLD%
6. Telegram звіт зі статистикою + файл алертів як вкладення

Запуск:
    python3 agents/orders/price_audit.py                    # стандартний
    python3 agents/orders/price_audit.py --threshold 10     # алерт при зміні >10%
    python3 agents/orders/price_audit.py --no-telegram      # без Telegram

Файли результатів:
    logs/price_audit_YYYYMMDD_HHMMSS.csv   — повний лог всіх товарів
    logs/price_alerts_YYYYMMDD_HHMMSS.csv  — тільки алерти (різкі зміни)
"""

import os, sys, requests, time, csv, json, argparse
import xml.etree.ElementTree as ET
from datetime import datetime
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection
from shared.utils.pricing import calc_price, get_prom_cpa, DEFAULT_PROM_CPA

# =============================================
# КОНСТАНТИ
# =============================================

ALERT_THRESHOLD_DEFAULT = 20.0  # % зміни ціни для алерту

TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)

LOGS_DIR = '/home/tek/agent-system/logs'

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')


# =============================================
# TELEGRAM
# =============================================

def tg_message(text: str):
    """Відправляє текстове повідомлення в Telegram."""
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={
                'chat_id': TELEGRAM_ADMIN,
                'text': text,
                'parse_mode': 'HTML'
            },
            timeout=15
        )
    except Exception as e:
        logger.error(f'Telegram message помилка: {e}')


def tg_file(file_path: str, caption: str = ''):
    """Відправляє файл в Telegram."""
    try:
        with open(file_path, 'rb') as f:
            requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument',
                data={
                    'chat_id': TELEGRAM_ADMIN,
                    'caption': caption,
                    'parse_mode': 'HTML'
                },
                files={'document': f},
                timeout=60
            )
        logger.success(f'Файл відправлено в Telegram: {os.path.basename(file_path)}')
    except Exception as e:
        logger.error(f'Telegram file помилка: {e}')


# =============================================
# 1. ФІД TOPTUL
# =============================================

def load_feed() -> dict:
    """
    Завантажує XML фід TOPTUL.
    Повертає dict: SKU → {price, available, stock}
    """
    logger.info('Завантажуємо фід TOPTUL...')
    try:
        resp = requests.get(TOPTUL_FEED, timeout=120)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        offers = root.find('shop').find('offers').findall('offer')

        feed = {}
        for offer in offers:
            sku_el = offer.find('vendorCode')
            sku = (sku_el.text or '').strip() if sku_el is not None else ''
            if not sku:
                sku = (offer.get('id') or '').upper()
            if not sku:
                continue

            price_el = offer.find('price')
            price = float(price_el.text) if price_el is not None else 0.0
            available = offer.get('available', 'true') == 'true'
            stock_el = offer.find('stock_quantity')
            stock = stock_el.text if stock_el is not None else '*'

            feed[sku.upper()] = {
                'price': price,
                'available': available,
                'stock': stock,
            }

        logger.success(f'Фід завантажено: {len(feed)} товарів')
        return feed

    except Exception as e:
        logger.error(f'Помилка завантаження фіду: {e}')
        return {}


# =============================================
# 2. БД — ЗАВАНТАЖЕННЯ ТОВАРІВ
# =============================================

def load_db_products() -> list:
    """
    Завантажує всі товари з my_products.
    Повертає list of dicts.
    """
    conn = get_connection()
    cur = conn.cursor()

    # Перевіряємо наявність колонок категорій
    cur.execute('''
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'my_products'
        AND column_name IN ('prom_category_name', 'prom_group_name')
    ''')
    existing = {r['column_name'] for r in cur.fetchall()}

    extra = ''
    if 'prom_category_name' in existing:
        extra += ', prom_category_name'
    if 'prom_group_name' in existing:
        extra += ', prom_group_name'

    cur.execute(f'''
        SELECT id, sku, name_uk, price_supplier, price_our{extra}
        FROM my_products
        WHERE price_supplier IS NOT NULL AND price_supplier > 0
        ORDER BY sku
    ''')
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    logger.info(f'БД: завантажено {len(rows)} товарів')
    return rows


# =============================================
# 3. АУДИТ ЦІН
# =============================================

def audit_prices(
    feed: dict,
    db_products: list,
    alert_threshold: float
) -> tuple:
    """
    Порівнює поточні ціни з новими розрахованими.

    Returns:
        tuple: (all_results, alerts)
            all_results — список всіх товарів з порівнянням
            alerts — список товарів зі зміною > alert_threshold%
    """
    all_results = []
    alerts = []

    total = len(db_products)
    logger.info(f'Аудит {total} товарів...')

    for i, product in enumerate(db_products):
        sku = (product.get('sku') or '').strip().upper()
        if not sku:
            continue

        name = (product.get('name_uk') or sku)[:60]
        old_supplier_price = float(product.get('price_supplier') or 0)
        old_our_price = float(product.get('price_our') or 0)

        # Беремо ціну з фіду
        feed_info = feed.get(sku)
        if not feed_info:
            # Товар не знайдено у фіді
            result = {
                'sku': sku,
                'name': name,
                'status': 'not_in_feed',
                'old_supplier': old_supplier_price,
                'new_supplier': 0,
                'old_our': old_our_price,
                'new_our': 0,
                'supplier_diff_pct': 0,
                'our_diff_pct': 0,
                'cpa': 0,
                'cpa_source': '',
                'available': False,
                'stock': '—',
                'is_alert': False,
                'alert_reason': '',
            }
            all_results.append(result)
            continue

        new_supplier_price = feed_info['price']
        available = feed_info['available']
        stock = feed_info['stock']

        # Визначаємо CPA
        prom_category = (product.get('prom_category_name') or '').strip()
        prom_group = (product.get('prom_group_name') or '').strip()

        cpa_source = 'default'
        if prom_category:
            cpa = get_prom_cpa(prom_category)
            if cpa != DEFAULT_PROM_CPA:
                cpa_source = prom_category
            elif prom_group:
                cpa = get_prom_cpa(prom_group)
                if cpa != DEFAULT_PROM_CPA:
                    cpa_source = prom_group
                else:
                    cpa_source = 'default'
        elif prom_group:
            cpa = get_prom_cpa(prom_group)
            if cpa != DEFAULT_PROM_CPA:
                cpa_source = prom_group
            else:
                cpa_source = 'default'
        else:
            cpa = DEFAULT_PROM_CPA
            cpa_source = 'default'

        # Розраховуємо нову ціну
        new_our_price = calc_price(new_supplier_price, cpa)

        # Відсоток зміни ціни постачальника
        if old_supplier_price > 0:
            supplier_diff_pct = (new_supplier_price - old_supplier_price) / old_supplier_price * 100
        else:
            supplier_diff_pct = 0

        # Відсоток зміни нашої ціни
        if old_our_price > 0:
            our_diff_pct = (new_our_price - old_our_price) / old_our_price * 100
        else:
            our_diff_pct = 0

        # Визначаємо чи є алерт
        is_alert = False
        alert_reason = ''

        if abs(our_diff_pct) >= alert_threshold:
            is_alert = True
            direction = 'подорожчало' if our_diff_pct > 0 else 'подешевшало'
            alert_reason = f'{direction} на {abs(our_diff_pct):.1f}%'

        if not available and old_our_price > 0:
            is_alert = True
            alert_reason = ('відсутній у фіді + ' + alert_reason).strip(' + ')

        result = {
            'sku': sku,
            'name': name,
            'status': 'ok',
            'old_supplier': old_supplier_price,
            'new_supplier': new_supplier_price,
            'old_our': old_our_price,
            'new_our': new_our_price,
            'supplier_diff_pct': round(supplier_diff_pct, 2),
            'our_diff_pct': round(our_diff_pct, 2),
            'cpa': round(cpa * 100, 2),
            'cpa_source': cpa_source,
            'available': available,
            'stock': stock,
            'is_alert': is_alert,
            'alert_reason': alert_reason,
        }
        all_results.append(result)

        if is_alert:
            alerts.append(result)

        if (i + 1) % 500 == 0:
            logger.info(f'Оброблено {i+1}/{total}...')

    logger.success(f'Аудит завершено: {len(all_results)} товарів, {len(alerts)} алертів')
    return all_results, alerts


# =============================================
# 4. ЗАПИС CSV ФАЙЛІВ
# =============================================

CSV_HEADERS = [
    'SKU', 'Назва', 'Статус',
    'Ціна постач. стара', 'Ціна постач. нова', 'Зміна постач. %',
    'Наша ціна стара', 'Наша ціна нова', 'Зміна нашої %',
    'CPA %', 'Джерело CPA',
    'Наявність', 'Залишок',
    'Алерт', 'Причина алерту',
]


def write_csv(results: list, file_path: str):
    """Записує результати у CSV файл."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(CSV_HEADERS)

        for r in results:
            writer.writerow([
                r['sku'],
                r['name'],
                r['status'],
                f"{r['old_supplier']:.2f}",
                f"{r['new_supplier']:.2f}",
                f"{r['supplier_diff_pct']:+.2f}%",
                f"{r['old_our']:.2f}",
                f"{r['new_our']:.2f}",
                f"{r['our_diff_pct']:+.2f}%",
                f"{r['cpa']:.2f}%",
                r['cpa_source'],
                'Так' if r['available'] else 'Ні',
                r['stock'],
                'Так' if r['is_alert'] else 'Ні',
                r['alert_reason'],
            ])

    logger.success(f'CSV записано: {file_path} ({len(results)} рядків)')


# =============================================
# 5. ГОЛОВНИЙ ЗАПУСК
# =============================================

def run(alert_threshold: float = ALERT_THRESHOLD_DEFAULT, send_telegram: bool = True):
    logger.info('=== Price Audit старт ===')
    logger.info(f'Поріг алерту: >{alert_threshold:.0f}%')

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    audit_file = f'{LOGS_DIR}/price_audit_{timestamp}.csv'
    alerts_file = f'{LOGS_DIR}/price_alerts_{timestamp}.csv'

    # Завантажуємо дані
    feed = load_feed()
    if not feed:
        tg_message('⚠️ <b>Price Audit</b>: не вдалось завантажити фід TOPTUL')
        return

    db_products = load_db_products()
    if not db_products:
        logger.error('Немає товарів в БД')
        return

    # Аудит
    all_results, alerts = audit_prices(feed, db_products, alert_threshold)

    # Статистика
    in_feed = [r for r in all_results if r['status'] == 'ok']
    not_in_feed = [r for r in all_results if r['status'] == 'not_in_feed']
    price_up = [r for r in in_feed if r['our_diff_pct'] > 1]
    price_down = [r for r in in_feed if r['our_diff_pct'] < -1]
    no_change = [r for r in in_feed if abs(r['our_diff_pct']) <= 1]
    unavailable = [r for r in in_feed if not r['available']]
    default_cpa = [r for r in in_feed if r['cpa_source'] == 'default']

    # Записуємо CSV файли
    write_csv(all_results, audit_file)
    if alerts:
        write_csv(alerts, alerts_file)
        logger.info(f'Алертів: {len(alerts)}')
    else:
        logger.info('Алертів немає')

    # Топ найбільших змін
    top_up = sorted(price_up, key=lambda x: -x['our_diff_pct'])[:5]
    top_down = sorted(price_down, key=lambda x: x['our_diff_pct'])[:5]

    # Формуємо Telegram повідомлення
    msg = f'''📊 <b>Price Audit — {datetime.now().strftime("%d.%m.%Y %H:%M")}</b>

📦 Всього товарів: {len(all_results)}
✅ Знайдено у фіді: {len(in_feed)}
❓ Відсутні у фіді: {len(not_in_feed)}
🚫 Недоступні: {len(unavailable)}

💰 Зміни цін:
📈 Подорожчало: {len(price_up)}
📉 Подешевшало: {len(price_down)}
➡️ Без змін: {len(no_change)}

⚠️ Алертів (>{alert_threshold:.0f}%): {len(alerts)}
🔄 Fallback CPA 15%: {len(default_cpa)} товарів'''

    if top_up:
        msg += '\n\n📈 <b>Найбільше подорожчало:</b>'
        for r in top_up:
            msg += f'\n  {r["sku"]}: {r["old_our"]:.0f}→{r["new_our"]:.0f} грн ({r["our_diff_pct"]:+.1f}%)'

    if top_down:
        msg += '\n\n📉 <b>Найбільше подешевшало:</b>'
        for r in top_down:
            msg += f'\n  {r["sku"]}: {r["old_our"]:.0f}→{r["new_our"]:.0f} грн ({r["our_diff_pct"]:+.1f}%)'

    if alerts:
        msg += f'\n\n📎 Файл алертів: {os.path.basename(alerts_file)}'

    logger.success(msg.replace('<b>', '').replace('</b>', ''))

    if send_telegram:
        tg_message(msg)
        if alerts:
            tg_file(
                alerts_file,
                caption=f'⚠️ Алерти цін {datetime.now().strftime("%d.%m.%Y")} — {len(alerts)} товарів зі зміною >{alert_threshold:.0f}%'
            )
        # Повний звіт також відправляємо
        tg_file(
            audit_file,
            caption=f'📊 Повний аудит цін {datetime.now().strftime("%d.%m.%Y")} — {len(all_results)} товарів'
        )

    logger.success(f'Аудит завершено. Файли:')
    logger.success(f'  Повний: {audit_file}')
    if alerts:
        logger.success(f'  Алерти: {alerts_file}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Price Audit — аудит цін з алертами')
    parser.add_argument('--threshold', type=float, default=ALERT_THRESHOLD_DEFAULT,
                        help=f'Поріг алерту у %% (default: {ALERT_THRESHOLD_DEFAULT})')
    parser.add_argument('--no-telegram', action='store_true',
                        help='Не відправляти в Telegram')
    args = parser.parse_args()

    run(
        alert_threshold=args.threshold,
        send_telegram=not args.no_telegram
    )

````

### `tools/carvol_epicentr_generator.py` — 997 рядків

````python
#!/usr/bin/env python3
"""
tools/carvol_epicentr_generator.py
====================================
Генератор XML для Єпіцентру з оптового прайсу Carvol (SpreadsheetML формат).

Запуск (на сервері):
    cd /home/tek/agent-system && source venv/bin/activate
    python3 tools/carvol_epicentr_generator.py
    python3 tools/carvol_epicentr_generator.py --input data/carvol_opt_20260613.xml
    python3 tools/carvol_epicentr_generator.py --input data/carvol_opt_20260613.xml --output exports/carvol_epicentr_new.xml
"""

import os, sys, re, hashlib, json, argparse, math
import xml.etree.ElementTree as ET
from datetime import datetime
from difflib import SequenceMatcher
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection

# ── Шляхи за замовчуванням ─────────────────────────────────────────────────

INPUT_FILE  = os.path.join(BASE_DIR, 'data', 'carvol_opt_20260613.xml')
OUTPUT_FILE = os.path.join(BASE_DIR, 'exports', 'carvol_epicentr_new.xml')
FEED_FILE   = os.path.join(BASE_DIR, 'data', 'carvol_feed.xml')

# SpreadsheetML namespace
SS_NS = 'urn:schemas-microsoft-com:office:spreadsheet'


def _t(name: str) -> str:
    return f'{{{SS_NS}}}{name}'


# ── Єпіцентр — константи ───────────────────────────────────────────────────

COUNTRY_CODE    = 'chn'
COUNTRY_NAME    = 'Китай'
DEFAULT_WEIGHT  = 500
DEFAULT_WIDTH   = 200
DEFAULT_HEIGHT  = 100
DEFAULT_LENGTH  = 200

# Категорія-дефолт якщо fuzzy-match не знайшов відповідника (≥0.6)
DEFAULT_EPICENTR_CAT = ('2866', 'Автомагнітоли')
DEFAULT_VENDOR = 'Carvol'
OTHER_BRAND_CODE = '827b4a70220f11ea918e001e67ecc97b'

# Комісія Єпіцентру по кодах категорій (% від ціни продажу)
# Джерело: таблиця epicentr_cpa_rates; відсутні категорії → дефолт 15%
EPICENTR_COMMISSION: dict[str, float] = {
    '8743': 15.0,  # Перехідні рамки для автомагнітол
    '3729': 15.0,  # Камери заднього огляду
    '2821': 15.0,  # Кабелі та перехідники
    '2848': 15.0,  # Аксесуари для автосигналізацій
    '2883': 15.0,  # LED-світло для автомобіля
    '2866': 15.0,  # Автомагнітоли
}
DEFAULT_COMMISSION = 15.0

# ── Єпіцентр PIM — valuecodes обов'язкових атрибутів ──────────────────────
# Джерело: tools/epicentr_attrs_explorer.py → таблиця epicentr_required_attrs

# attr 4866 — Марка автомобіля (multiselect, обов'язк. для 8743/3729/2866)
CAR_BRAND_UNIVERSAL = '3ad4056127c7c0038b78a7f24cc80941'   # 'універсальна'

# attr 6513 — Тип камери (select, обов'язк. 3729)
CAM_TYPE_UNIVERSAL = '7299e5c152994121d88f9bcd470856b4'    # 'універсальна'
CAM_TYPE_STOCK     = '7cf79577178c3c5c36f436083e063655'    # 'штатна'

# attr 11926 — Вид камери (select, обов'язк. 3729)
CAM_VIEW_EMBEDDED  = '7e95d2c4d062009c0be07a7f6977630a'   # 'врізна'
CAM_VIEW_PLATE     = 'ca3e67de55b5f4715e6f07126b29c833'   # 'рамка номеру'
CAM_VIEW_HANDLE    = 'bdfa916fc1b271066db95a8b50331c53'   # 'ручка багажника'

# attr 1514 — Роздільна здатність (select, обов'язк. 3729)
CAM_RES_640x480    = '9c9e3de91c6ed6fec1e4e1dd00ff42f5'   # '640x480'
CAM_RES_800x600    = 'e8cf43113ee5de6956e9e2604fd30726'   # '800x600'

# attr 51 — Вид рамки (multiselect, обов'язк. 8743)
FRAME_VIEW_FRAME   = 'oygfpb2qe85gkxu2'                   # 'рамка'

# attr 52 — Матеріал рамки (multiselect, обов'язк. 8743)
FRAME_MATERIAL_PLASTIC = '59474de511ea0'                   # 'пластик'

# attr 5575 — Розмір DIN (multiselect, обов'язк. 8743)
DIN_1       = 'b1ae2e6b91a1585c7f8f41c4d9ccf31a'          # '1 DIN'
DIN_2       = 'ac6de55906304dde5f3e2a9dce129472'          # '2 DIN'
DIN_STOCK   = 'f4b058f379b8a1e4f51ab8a2d19967b3'          # 'штатний'

# attr 12097 — Базовий колір (multiselect, обов'язк. 8743)
COLOR_BLACK  = '3ec160321d45b95cf3a540ad3a2bf896'         # 'чорний'
COLOR_GREY   = '59474de51f852'                             # 'сірий'
COLOR_SILVER = 'cda97fb08eda186db32c35530a77c169'         # 'срібло'

# attr 6547 — Монтажний розмір (select, обов'язк. 2866)
HU_DIN_1    = 'f50736375652d028ada0830633d6eabb'          # '1 DIN'
HU_DIN_2    = 'bf24a9c8dba87b73eff8558f920465dd'          # '2 DIN'
HU_DIN_STK  = 'f80c33cd5ad122b0061bcef59e834cf3'          # 'штатний'

# attr 6546 — Тип магнітоли (multiselect, обов'язк. 2866)
HU_TYPE_MULTIMEDIA = '6c37e1c5438d5c1def462d317a0badf4'  # 'мультимедіа'
HU_TYPE_NODISK     = '35f1542c708837463fa1ff36deeaa05f'  # 'бездискові'

# attr 6534 — Роз'єми (multiselect, обов'язк. 2866)
CONN_USB    = 'e0a4ed3c6ee0b0bd090f6fc9d3adae32'
CONN_AUX    = '6f4bfa054da3527036ed99c99b056ed8'
CONN_ISO    = '6f3dc117d0547a99070154f3b3d22cc1'
CONN_SD     = '23b8a01e61f6865a9110b464893915e0'
CONN_VIDEO_IN  = 'ce077fc1f63803d602423e1050710686'
CONN_CAM_OUT   = '2ea7e4f7513debab41bbd993a7e3fdf0'

# attr 11263 — Бездротові технології (multiselect, обов'язк. 2866)
WIRELESS_BT   = 'aa4cebda1eede9c3c1da569d448e0fca'
WIRELESS_WIFI = '24a7fbd807c8ae71bd5fe1b8a4029069'
WIRELESS_FM   = '6e41ac3ba4c89064a8cdc28547f8656e'

# attr 1548 — Тип тюнера (multiselect, обов'язк. 2866)
TUNER_DIGITAL  = '53b3e9a8edcf1f6eb9ce25aa1fdfb321'      # 'цифровий'
TUNER_ANALOG   = 'd528f19e248a8483d98ac08888337941'       # 'аналоговий'

# attr 1382 — Діапазон радіосигналу (multiselect, обов'язк. 2866 штатна)
RADIO_FM = '08eb2c3faa8be25954b063a2354e8886'

# attr 1384 — Налаштування частоти (multiselect, обов'язк. 2866 штатна) — 1 option
FREQ_DIGITAL = '46c7d550fed92fd045ac77e40674d8c0'          # 'цифрова'

# attr 5093 — Живлення (multiselect, обов'язк. 2866 штатна)
POWER_UNIVERSAL = 'a41774d7ec6d5740d58fe417dd76d8fa'       # 'універсальне'
POWER_NETWORK   = '0380ad214b03e5ae48e604b6c0f54ed0'       # 'від мережі'

# attr 6187 — ПДК (select, обов'язк. 2866 штатна)
REMOTE_YES = 'c5f6ccdb5b9768be76e66076d0c4a4ac'            # 'з пультом'
REMOTE_NO  = 'fb646e75fba1511bf08fa378fe404a54'            # 'без пульта'

# attr 78 — Колір виробника (multiselect, обов'язк. 2866 штатна / 2821)
COLOR_MFR_BLACK  = 'ff8cwdpi'                              # 'чорний'
COLOR_MFR_SILVER = 'wdlnhtlh'                              # 'срібний'
COLOR_MFR_RED    = '5uooq3p5'                              # 'червоний'

# attr 10986 — Призначення (select, обов'язк. 2821)
CABLE_PURPOSE_POWER = '2803714201cad2ef609cb764e73f458d'  # 'кабелі живлення'

# attr 11971 — Тип (select, обов'язк. 2821)
CABLE_TYPE_ADAPTER  = '4f94742a0b422cd62c6e501270a3a142'  # 'перехідники'

# attr 4857 — Довжина (select, обов'язк. 2821)
CABLE_LEN_05M       = 'f3d01fbc6fd71bbf58f2bb539a431c7b'  # 'до 0.5 м'

# attr 826 — Тип кабелю (select, обов'язк. 2821)
CABLE_SUBTYPE_EPP   = 'c5vpi0ent7q1djaq'                  # 'Expansion Power Port'

# attr 5290 — Вхідний роз'єм (select, обов'язк. 2821)
CABLE_IN_USB        = '3dc1e63667c128348dea5263491a5822'  # 'USB'

# attr 5291 — Вихідний роз'єм (select, обов'язк. 2821)
CABLE_OUT_ISO       = 'e9cbcc2cb07e985d8f62814707b15b60'  # 'ISO'


def _p(name: str, code: str, valuecode: str, value: str) -> str:
    """Генерує рядок <param> з valuecode."""
    return f'    <param name="{name}" paramcode="{code}" valuecode="{valuecode}">{value}</param>'


def _pf(name: str, code: str, value) -> str:
    """Генерує рядок <param> для числових атрибутів (без valuecode)."""
    return f'    <param name="{name}" paramcode="{code}">{value}</param>'


def _detect_din(name: str) -> str:
    """Детектує DIN розмір з назви товару (1DIN / 2DIN / штатний)."""
    n = name.lower()
    if '1 din' in n or '1din' in n:
        return '1 DIN'
    if 'штатний' in n or 'штатн' in n:
        return 'штатний'
    # Більшість QIV/Teyes — 2DIN (9"/10" головні пристрої)
    return '2 DIN'


def _detect_frame_color(name: str) -> str:
    """Детектує колір рамки з назви ('graphite'→grey, 'silver'→silver, default→black)."""
    n = name.lower()
    if 'graphite' in n or 'gray' in n or 'grey' in n or 'сір' in n:
        return 'grey'
    if 'silver' in n or 'срібл' in n:
        return 'silver'
    return 'black'


def _detect_cam_view(name: str) -> str:
    """Детектує вид камери з назви."""
    n = name.lower()
    if 'рамка номер' in n or 'номерн' in n or 'plate' in n:
        return 'plate'
    if 'ручка' in n or 'handle' in n:
        return 'handle'
    return 'embedded'


def _detect_cam_resolution(name: str) -> str:
    """Детектує роздільну здатність камери."""
    n = name.lower()
    if '1080' in n or 'fhd' in n or 'full hd' in n:
        return '1920х1080'
    if '720' in n or 'hd' in n:
        return '1280x720'
    if '800tvl' in n or '800 tvl' in n:
        return '800x600'
    return '640x480'


def get_category_params(cat_code: str, name: str, car_brand_map: dict | None = None) -> list[str]:
    """
    Повертає список рядків <param> для обов'язкових атрибутів категорії.
    car_brand_map: {name_lower: (valuecode, name_ua)} з epicentr_car_brands.
    """
    params = []
    cbm = car_brand_map or {}

    if cat_code == '8743':
        # Перехідні рамки для автомагнітол
        din = _detect_din(name)
        din_code = DIN_2 if din == '2 DIN' else (DIN_1 if din == '1 DIN' else DIN_STOCK)
        color = _detect_frame_color(name)
        color_code = COLOR_GREY if color == 'grey' else (COLOR_SILVER if color == 'silver' else COLOR_BLACK)
        color_ua = {'grey': 'сірий', 'silver': 'срібло', 'black': 'чорний'}[color]
        car_brands = detect_car_brands_from_name(name, cbm)
        params += [
            _p('Розмір', '5575', din_code, din),
            _p('Вид', '51', FRAME_VIEW_FRAME, 'рамка'),
            *[_p('Марка автомобіля', '4866', vc, nu) for vc, nu in car_brands],
            _p('Матеріал', '52', FRAME_MATERIAL_PLASTIC, 'пластик'),
            _p('Базовий колір', '12097', color_code, color_ua),
        ]

    elif cat_code == '2866':
        if 'штатн' in name.lower():
            # Штатна магнітола — специфічний набір атрибутів
            params += [
                _p('Підтримуваний діапазон радіосигналу', '1382', RADIO_FM, 'FM'),
                _p('Налаштування частоти', '1384', FREQ_DIGITAL, 'цифрова'),
                _p('Живлення', '5093', POWER_UNIVERSAL, 'універсальне (мережа або батарейки)'),
                _p('Пульт дистанційного керування', '6187', REMOTE_YES, 'з пультом дистанційного керування'),
                _p('Колір виробника', '78', COLOR_MFR_BLACK, 'чорний'),
                _pf('Потужність', '103', 4),
                _pf('Кількість динаміків', '1386', 4),
            ]
        else:
            # Звичайна автомагнітола 1DIN/2DIN (QIV, Mekede, Teyes тощо)
            din = _detect_din(name)
            din_code = HU_DIN_2 if din == '2 DIN' else (HU_DIN_1 if din == '1 DIN' else HU_DIN_STK)
            car_brands = detect_car_brands_from_name(name, cbm)
            params += [
                *[_p('Марка автомобіля', '4866', vc, nu) for vc, nu in car_brands],
                _p('Тип магнітоли', '6546', HU_TYPE_MULTIMEDIA, 'мультимедіа'),
                _p('Монтажний розмір', '6547', din_code, din),
                _p("Роз'єми", '6534', CONN_USB, 'USB'),
                _p("Роз'єми", '6534', CONN_AUX, 'AUX'),
                _p("Роз'єми", '6534', CONN_ISO, 'ISO'),
                _p("Роз'єми", '6534', CONN_VIDEO_IN, 'відеовхід'),
                _p("Роз'єми", '6534', CONN_CAM_OUT, 'вихід для камери заднього огляду'),
                _p('Бездротові технології', '11263', WIRELESS_BT, 'Bluetooth'),
                _p('Бездротові технології', '11263', WIRELESS_WIFI, 'Wi-Fi'),
                _p('Тип тюнера', '1548', TUNER_DIGITAL, 'цифровий'),
            ]

    elif cat_code == '3729':
        # Камери заднього огляду
        view = _detect_cam_view(name)
        view_code = {'plate': CAM_VIEW_PLATE, 'handle': CAM_VIEW_HANDLE}.get(view, CAM_VIEW_EMBEDDED)
        view_ua   = {'plate': 'рамка номеру', 'handle': 'ручка багажника'}.get(view, 'врізна')
        res = _detect_cam_resolution(name)
        res_map = {
            '1920х1080': 'cafccc0c1fdaad0ac4607a755b066978',
            '1280x720':  '1170fde30dfd911f207e2467bc15419c',
            '800x600':   CAM_RES_800x600,
            '640x480':   CAM_RES_640x480,
        }
        res_code = res_map.get(res, CAM_RES_640x480)
        car_brands = detect_car_brands_from_name(name, cbm)
        params += [
            *[_p('Марка автомобіля', '4866', vc, nu) for vc, nu in car_brands],
            _p('Роздільна здатність екрана', '1514', res_code, res),
            _p('Вид', '11926', view_code, view_ua),
            _p('Тип', '6513', CAM_TYPE_UNIVERSAL, 'універсальна'),
            _p('Паркувальна розмітка', '6510', 'yes', 'так'),
            _p('Автозатемнення', '6564', 'no', 'ні'),
        ]

    elif cat_code == '2821':
        # Кабелі та перехідники
        params += [
            _p('Призначення', '10986', CABLE_PURPOSE_POWER, 'кабелі живлення'),
            _p('Тип', '11971', CABLE_TYPE_ADAPTER, 'перехідники'),
            _p('Довжина', '4857', CABLE_LEN_05M, 'до 0.5 м'),
            _p('Колір виробника', '78', COLOR_MFR_BLACK, 'чорний'),
            _p('Тип кабелю', '826', CABLE_SUBTYPE_EPP, 'Expansion Power Port'),
            _p("Вхідний роз'єм", '5290', CABLE_IN_USB, 'USB'),
            _p("Вихідний роз'єм", '5291', CABLE_OUT_ISO, 'ISO'),
        ]
    # 2848 — тільки float dims (weight/width/height/length), вже є в offer

    return params


def calc_sell_price(rrc: float, cat_code: str) -> float:
    """Ціна продажу = РРЦ gross-up на комісію Єпіцентру, округлення вгору до 10."""
    comm = EPICENTR_COMMISSION.get(cat_code, DEFAULT_COMMISSION)
    return math.ceil(rrc / (1 - comm / 100) / 10) * 10


# ── SpreadsheetML парсер ────────────────────────────────────────────────────

def _cell_value(cell) -> str:
    """Повертає текст клітинки незалежно від namespace. Знімає апостроф Excel-prefix."""
    for tag in (_t('Data'), 'Data'):
        data_el = cell.find(tag)
        if data_el is not None:
            val = (data_el.text or '').strip()
            # Excel зберігає текстові числа з апострофом-префіксом (не видний в UI)
            if val.startswith("'"):
                val = val[1:]
            return val
    return ''


def _row_cells(row) -> list[str]:
    """
    Повертає список значень рядка з врахуванням ss:Index (розріджені рядки).
    ss:Index — 1-based позиція клітинки; пропуски заповнюються порожнім рядком.
    """
    result: list[str] = []
    pos = 0
    cells = row.findall(_t('Cell')) or row.findall('Cell')
    for cell in cells:
        # ss:Index може бути в namespace або без
        idx_attr = cell.get(_t('Index')) or cell.get('ss:Index')
        if idx_attr:
            target = int(idx_attr) - 1  # 0-based
            while pos < target:
                result.append('')
                pos += 1
        result.append(_cell_value(cell))
        pos += 1
    return result


def _find_header_row(rows: list) -> int:
    """
    Знаходить індекс рядка-заголовка: шукає рядок з ≥4 непорожніх клітинок.
    Carvol прайс має 3 рядки-шапки (назва, дата, пустий) перед реальними заголовками.
    """
    for i, row in enumerate(rows[:10]):
        vals = [v for v in _row_cells(row) if v.strip()]
        if len(vals) >= 4:
            return i
    return 0


def parse_spreadsheet_ml(filepath: str) -> list[dict]:
    """
    Парсить SpreadsheetML (Excel XML) файл.
    Автоматично знаходить рядок заголовків (пропускаючи службові рядки шапки).
    Повертає список dict {header_lower: value} для кожного рядка даних.
    """
    logger.info(f"Парсимо SpreadsheetML: {filepath}")
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Перший Worksheet
    ws = root.find(f'.//{_t("Worksheet")}')
    if ws is None:
        ws = root.find('.//Worksheet')
    if ws is None:
        raise ValueError("Worksheet не знайдено в SpreadsheetML")

    table = ws.find(_t('Table'))
    if table is None:
        table = ws.find('Table')
    if table is None:
        raise ValueError("Table не знайдено в Worksheet")

    rows = table.findall(_t('Row'))
    if not rows:
        rows = table.findall('Row')
    logger.info(f"Рядків у файлі: {len(rows)}")

    if not rows:
        return []

    # Автодетекція рядка заголовків
    header_row_idx = _find_header_row(rows)
    logger.info(f"Рядок заголовків: {header_row_idx}")

    headers = [h.lower().strip() for h in _row_cells(rows[header_row_idx])]
    logger.info(f"Заголовки ({len(headers)}): {headers}")

    records: list[dict] = []
    for row in rows[header_row_idx + 1:]:
        vals = _row_cells(row)
        if not any(v.strip() for v in vals):
            continue
        while len(vals) < len(headers):
            vals.append('')
        records.append({headers[i]: vals[i] for i in range(len(headers))})

    logger.info(f"Записів після парсингу: {len(records)}")
    return records


# ── Автодетекція колонок ────────────────────────────────────────────────────

# Шаблони для пошуку потрібних стовпців за назвою заголовка
_COL_PATTERNS: dict[str, list[str]] = {
    'article':  ['артикул', 'код товару', 'код', 'sku', 'article', 'part'],
    'name':     ['найменування', 'назва', 'name', 'наименование', 'товар'],
    'stock':    ['залишок', 'наявність', 'залишки', 'остаток', 'stock', '+/-', 'наліч'],
    # 'роздріб (uah)' — точний формат Carvol прайсу
    'price':    ['роздріб (uah)', 'роздрібна', 'роздріб', 'price uah', 'ціна грн',
                 'прайс', 'ціна роздр', 'rrc', 'ціна'],
    'vendor':   ['бренд', 'виробник', 'brand', 'марка', 'vendor'],
    'category': ['категорія', 'розділ', 'группа', 'group', 'category',
                 'підгрупа', 'тип', 'вид'],
    'model':    ['модель', 'model'],
    'desc':     ['опис', 'description', 'описание', 'характеристик'],
}


def detect_columns(headers: list[str]) -> dict[str, int]:
    """
    Визначає індекси потрібних колонок за ключовими словами.
    Патерни відсортовані від специфічних до загальних — перший збіг виграє.
    """
    mapping: dict[str, int] = {}
    for field, patterns in _COL_PATTERNS.items():
        for pattern in patterns:          # спочатку специфічніші патерни
            for i, h in enumerate(headers):
                if pattern in h:
                    if field not in mapping:
                        mapping[field] = i
                    break
            if field in mapping:
                break
    return mapping


# ── Маппінг категорій Carvol → Єпіцентр ────────────────────────────────────

_epicentr_cats: list[tuple[str, str]] = []
_cat_cache: dict[str, tuple[str, str]] = {}


def _load_epicentr_cats() -> list[tuple[str, str]]:
    global _epicentr_cats
    if _epicentr_cats:
        return _epicentr_cats
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT code, name_ua
        FROM epicentr_categories
        WHERE name_ua IS NOT NULL AND name_ua <> ''
        ORDER BY code
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    _epicentr_cats = [(r['code'], r['name_ua']) for r in rows]
    logger.info(f"Завантажено {len(_epicentr_cats)} категорій Єпіцентру")
    return _epicentr_cats


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').lower().strip())


def _best_match(query: str, candidates: list[tuple[str, str]]) -> tuple[float, str, str]:
    """Повертає (score, code, name) найкращого збігу."""
    q = _norm(query)
    best_score, best_code, best_name = 0.0, '', ''
    for code, name in candidates:
        n = _norm(name)
        raw = SequenceMatcher(None, q, n).ratio()
        # Штраф якщо кандидат містить "зайві" слова (дає хибний збіг "Комплекти"→"DJ-комплекти")
        len_ratio = min(len(q), len(n)) / max(len(q), len(n)) if max(len(q), len(n)) else 1
        score = raw * (0.5 + 0.5 * len_ratio)
        if score > best_score:
            best_score, best_code, best_name = score, code, name
    return best_score, best_code, best_name


_manual_map: dict[str, tuple[str, str]] = {}


def _load_manual_map() -> dict[str, tuple[str, str]]:
    """Завантажує ручний маппінг з таблиці carvol_epicentr_cat_map."""
    global _manual_map
    if _manual_map:
        return _manual_map
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT carvol_cat, epicentr_code, epicentr_name FROM carvol_epicentr_cat_map")
        for r in cur.fetchall():
            _manual_map[r['carvol_cat'].strip()] = (r['epicentr_code'], r['epicentr_name'])
        cur.close(); conn.close()
        logger.info(f"Ручний маппінг: {len(_manual_map)} записів")
    except Exception as e:
        logger.warning(f"carvol_epicentr_cat_map недоступна: {e}")
    return _manual_map


def map_category(carvol_cat: str) -> tuple[str, str]:
    """
    Повертає (epicentr_code, epicentr_name) для категорії Carvol.
    Стратегія (пріоритет зверху вниз):
    1. Ручний маппінг (carvol_epicentr_cat_map) — точний збіг або по кореневій категорії
    2. Точний fuzzy-збіг по epicentr_categories
    3. Матч по листовій категорії (після останнього ' > ')
    4. Матч по повному шляху
    """
    key = (carvol_cat or '').strip()
    if not key:
        return DEFAULT_EPICENTR_CAT

    if key in _cat_cache:
        return _cat_cache[key]

    manual = _load_manual_map()

    # 1a. Точний ручний маппінг
    if key in manual:
        result = manual[key]
        _cat_cache[key] = result
        logger.debug(f"  CAT '{key}' → '{result[1]}' (manual exact)")
        return result

    # 1b. Ручний маппінг по кореню шляху (частина до першого ' > ')
    root_cat = key.split(' > ')[0].strip()
    if root_cat != key and root_cat in manual:
        result = manual[root_cat]
        _cat_cache[key] = result
        logger.debug(f"  CAT '{key}' (root='{root_cat}') → '{result[1]}' (manual root)")
        return result

    candidates = _load_epicentr_cats()

    # 2. Точний fuzzy-збіг
    key_norm = _norm(key)
    for code, name in candidates:
        if _norm(name) == key_norm:
            _cat_cache[key] = (code, name)
            logger.debug(f"  CAT '{key}' → '{name}' (fuzzy exact)")
            return (code, name)

    # 3. Матч по листовій категорії (частина після останнього ' > ')
    leaf = key.split(' > ')[-1].strip()
    if leaf and leaf != key:
        # Спочатку ручний маппінг для листа
        if leaf in manual:
            result = manual[leaf]
            _cat_cache[key] = result
            logger.debug(f"  CAT '{key}' (leaf='{leaf}') → '{result[1]}' (manual leaf)")
            return result
        score, code, name = _best_match(leaf, candidates)
        if score >= 0.72:
            result = (code, name)
            _cat_cache[key] = result
            logger.debug(f"  CAT '{key}' (leaf='{leaf}') → '{name}' (score={score:.2f})")
            return result

    # 4. Матч по повному шляху
    score, code, name = _best_match(key, candidates)
    if score >= 0.72 and code:
        result = (code, name)
        logger.debug(f"  CAT '{key}' → '{name}' (score={score:.2f})")
    else:
        result = DEFAULT_EPICENTR_CAT
        logger.warning(f"  CAT '{key}' не знайдено (best={score:.2f} '{name}') → DEFAULT")

    _cat_cache[key] = result
    return result


# ── Фото з таблиці carvol_products ─────────────────────────────────────────

_pics_cache: dict[str, list[str]] = {}


def _load_pics() -> None:
    if _pics_cache:
        return
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT article, pictures
            FROM carvol_products
            WHERE pictures IS NOT NULL AND pictures <> '[]'
        """)
        for r in cur.fetchall():
            pics = r['pictures']
            if isinstance(pics, str):
                try:
                    pics = json.loads(pics)
                except json.JSONDecodeError:
                    pics = []
            if pics and r['article']:
                _pics_cache[r['article'].upper()] = [p for p in pics if p]
        cur.close(); conn.close()
        logger.info(f"Фото завантажено для {len(_pics_cache)} товарів")
    except Exception as exc:
        logger.warning(f"Не вдалось завантажити фото з БД: {exc}")


def get_pictures(article: str) -> list[str]:
    return _pics_cache.get((article or '').upper(), [])


# ── Дані з Rozetka XML feed (описи, фото, vendor) ──────────────────────────

_feed_cache: dict[str, dict] = {}


def _load_feed_data(feed_file: str) -> None:
    """Завантажує описи, фото і vendor з Prom/Rozetka XML фіду Carvol."""
    if _feed_cache:
        return
    if not os.path.exists(feed_file):
        logger.warning(f"Feed файл не знайдено: {feed_file}")
        return
    try:
        tree = ET.parse(feed_file)
        root = tree.getroot()
        offers = root.findall('.//offer')
        for o in offers:
            art = (o.findtext('article', '') or '').strip()
            if not art:
                continue
            key = art.upper()
            desc = (o.findtext('description_ua', '') or o.findtext('description', '') or '').strip()
            pics = [p.text for p in o.findall('picture') if p.text and p.text.strip()]
            vendor = (o.findtext('vendor', '') or '').strip()
            _feed_cache[key] = {'desc': desc, 'pics': pics, 'vendor': vendor}
        logger.info(f"Feed завантажено: {len(_feed_cache)} товарів з {feed_file}")
    except Exception as exc:
        logger.warning(f"Не вдалось завантажити feed: {exc}")


# ── Бренди Єпіцентру (epicentr_brand_map) ──────────────────────────────────

_brand_map: dict[str, dict] = {}  # key=brand_name.lower()
_unknown_vendors_warned: set[str] = set()


def _load_brand_map() -> dict[str, dict]:
    global _brand_map
    if _brand_map:
        return _brand_map
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT brand_name, valuecode, value_ua FROM epicentr_brand_map")
        for r in cur.fetchall():
            key = (r['brand_name'] or '').lower().strip()
            if key:
                _brand_map[key] = {'valuecode': r['valuecode'], 'value_ua': r['value_ua']}
        cur.close(); conn.close()
        logger.info(f"Бренди Єпіцентру завантажено: {len(_brand_map)} записів")
    except Exception as e:
        logger.warning(f"epicentr_brand_map недоступна: {e}")
    return _brand_map


def get_valid_vendor(vendor_name: str, conn=None) -> dict | None:
    """
    Шукає бренд в epicentr_brand_map (case-insensitive).
    Повертає {'valuecode': ..., 'value_ua': ...} або None якщо не знайдено.
    """
    bmap = _load_brand_map()
    key = (vendor_name or '').lower().strip()
    return bmap.get(key)


# ── Бренди авто Єпіцентру (epicentr_car_brands, attr 4866) ─────────────────

_car_brand_map: dict[str, tuple[str, str]] = {}  # name_lower → (valuecode, name_ua)


def _load_car_brand_map() -> dict[str, tuple[str, str]]:
    global _car_brand_map
    if _car_brand_map:
        return _car_brand_map
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT valuecode, name_ua, name_lower FROM epicentr_car_brands")
        for r in cur.fetchall():
            key = r['name_lower'] or (r['name_ua'] or '').lower()
            if key:
                _car_brand_map[key] = (r['valuecode'], r['name_ua'])
        cur.close(); conn.close()
        logger.info(f"Бренди авто завантажено: {len(_car_brand_map)} записів")
    except Exception as e:
        logger.warning(f"epicentr_car_brands недоступна: {e}")
    return _car_brand_map


def detect_car_brands_from_name(name: str, car_brand_map: dict) -> list[tuple[str, str]]:
    """
    Знаходить марки авто в назві товару по слову (word boundary).
    Повертає список (valuecode, name_ua) — кожен як окремий <param paramcode="4866">.
    Якщо жодного не знайдено — повертає [(CAR_BRAND_UNIVERSAL, 'універсальна')].
    """
    found = []
    name_lower = name.lower()
    for brand_lower, (valuecode, name_ua) in car_brand_map.items():
        pattern = r'\b' + re.escape(brand_lower) + r'\b'
        if re.search(pattern, name_lower):
            found.append((valuecode, name_ua))
    return found if found else [(CAR_BRAND_UNIVERSAL, 'універсальна')]


# ── Хелпери ─────────────────────────────────────────────────────────────────

def escape_xml(text) -> str:
    s = str(text) if text is not None else ''
    return (s
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&apos;'))


def parse_price(raw: str) -> float:
    try:
        return float(re.sub(r'[^\d.,]', '', raw).replace(',', '.'))
    except (ValueError, TypeError):
        return 0.0


# ── Основна функція генерації ────────────────────────────────────────────────

def generate_xml(
    input_file: str = INPUT_FILE,
    output_file: str = OUTPUT_FILE,
    feed_file: str = FEED_FILE,
) -> int:
    # 1. Парсинг SpreadsheetML
    records = parse_spreadsheet_ml(input_file)
    if not records:
        logger.error("Файл порожній або не містить записів")
        return 0

    headers = list(records[0].keys())
    col = detect_columns(headers)
    logger.info(f"Детектовані колонки: { {k: headers[v] for k, v in col.items()} }")

    missing = [f for f in ('article', 'price') if f not in col]
    if missing:
        logger.error(f"Обов'язкові колонки не знайдено: {missing}")
        logger.error(f"Доступні заголовки: {headers}")
        return 0

    # 2. Фільтр залишок: '+' або '++' (є в наявності), '-' = немає
    if 'stock' in col:
        stock_key = headers[col['stock']]
        filtered = [r for r in records if '+' in r.get(stock_key, '').strip()]
        logger.info(f"Залишок містить '+': {len(filtered)} з {len(records)} записів")
    else:
        logger.warning("Колонка 'залишок' не знайдена — беремо всі записи")
        filtered = records

    if not filtered:
        logger.error("Немає товарів з залишком '+'")
        return 0

    # 3. Фото з БД + дані з Rozetka feed (описи, фото, vendor) + бренди Єпіцентру
    _load_pics()
    _load_feed_data(feed_file)
    _load_brand_map()
    car_brand_map = _load_car_brand_map()

    # 4. Генерація XML
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{datetime.now().strftime("%Y-%m-%d %H:%M")}">',
        '<offers>',
    ]

    cnt_total = 0
    cnt_no_price = 0
    cnt_no_article = 0
    cnt_with_pics = 0
    cnt_pics_from_feed = 0
    cnt_desc_from_feed = 0
    cnt_desc_auto = 0
    cnt_vendor_from_feed = 0
    cnt_vendor_default = 0
    cnt_vendor_valid = 0    # знайдено в epicentr_brand_map
    cnt_vendor_other = 0    # не знайдено → Єпіцентр прийме як "Інше"
    vendor_unknown_stats: dict[str, int] = {}
    cat_stats: dict[str, int] = {}
    price_samples: list[tuple] = []  # (article, cat_code, rrc, sell_price)

    for rec in filtered:
        article = rec.get(headers[col['article']], '').strip()
        if not article:
            cnt_no_article += 1
            continue

        price = parse_price(rec.get(headers[col['price']], '') if 'price' in col else '')
        if price <= 0:
            cnt_no_price += 1
            continue

        name    = rec.get(headers[col['name']], '').strip()     if 'name'     in col else ''
        vendor  = rec.get(headers[col['vendor']], '').strip()   if 'vendor'   in col else ''
        model   = rec.get(headers[col['model']], '').strip()    if 'model'    in col else ''
        cat_raw = rec.get(headers[col['category']], '').strip() if 'category' in col else ''
        desc    = rec.get(headers[col['desc']], '').strip()     if 'desc'     in col else ''

        # Feed-дані для fallback
        feed_item = _feed_cache.get(article.upper(), {})

        # Назва: беремо з файлу або складаємо як [Бренд] [Модель] [Артикул]
        if not name:
            parts = [p for p in [vendor, model or article] if p]
            name = ' '.join(parts) or article

        # Vendor: прайс → feed → дефолт
        if not vendor:
            feed_vendor = feed_item.get('vendor', '')
            if feed_vendor:
                vendor = feed_vendor
                cnt_vendor_from_feed += 1
            else:
                vendor = DEFAULT_VENDOR
                cnt_vendor_default += 1

        # Опис: прайс → feed → авто-генерація
        if not desc:
            feed_desc = feed_item.get('desc', '')
            if feed_desc:
                desc = feed_desc
                cnt_desc_from_feed += 1
            else:
                desc = f'<p>{escape_xml(name)} — якісний автоаксесуар для вашого автомобіля.</p>'
                cnt_desc_auto += 1

        cat_code, cat_name = map_category(cat_raw)
        cat_stats[cat_name] = cat_stats.get(cat_name, 0) + 1

        sell_price = calc_sell_price(price, cat_code)
        if len(price_samples) < 5:
            price_samples.append((article, cat_code, price, sell_price))

        # Фото: БД → feed
        pictures = get_pictures(article)
        if pictures:
            cnt_with_pics += 1
        else:
            feed_pics = feed_item.get('pics', [])
            if feed_pics:
                pictures = feed_pics
                cnt_pics_from_feed += 1

        # Пошук бренду в epicentr_brand_map
        brand_info = get_valid_vendor(vendor)
        if brand_info:
            v_code = brand_info['valuecode']
            v_text = brand_info['value_ua']
            cnt_vendor_valid += 1
        else:
            v_code = OTHER_BRAND_CODE
            v_text = 'Інше'
            cnt_vendor_other += 1
            vendor_unknown_stats[vendor] = vendor_unknown_stats.get(vendor, 0) + 1
            if vendor not in _unknown_vendors_warned:
                logger.warning(f"Невідомий бренд → Єпіцентр 'Інше': '{vendor}'")
                _unknown_vendors_warned.add(vendor)

        avail = 'true'

        offer: list[str] = [
            f'  <offer id="{escape_xml(article)}" available="{avail}">',
            f'    <price>{sell_price:.2f}</price>',
            f'    <category code="{escape_xml(cat_code)}">{escape_xml(cat_name)}</category>',
            f'    <attribute_set code="{escape_xml(cat_code)}">{escape_xml(cat_name)}</attribute_set>',
            f'    <name lang="ua">{escape_xml(name)}</name>',
            f'    <name lang="ru">{escape_xml(name)}</name>',
        ]

        for pic_url in pictures[:10]:
            if pic_url:
                offer.append(f'    <picture>{escape_xml(pic_url)}</picture>')

        if desc:
            offer.append(f'    <description lang="ua">{escape_xml(desc)}</description>')

        if v_code:
            brand_param = f'    <param name="Бренд" paramcode="brand" valuecode="{escape_xml(v_code)}">{escape_xml(v_text)}</param>'
        else:
            brand_param = f'    <param name="Бренд" paramcode="brand">{escape_xml(v_text)}</param>'

        extra_params = get_category_params(cat_code, name, car_brand_map)

        offer += [
            f'    <vendor code="{escape_xml(v_code)}">{escape_xml(v_text)}</vendor>',
            f'    <country_of_origin code="{COUNTRY_CODE}">{COUNTRY_NAME}</country_of_origin>',
            '    <param name="Міра виміру" paramcode="measure" valuecode="measure_pcs">шт.</param>',
            '    <param name="Мінімальна кратність товару" paramcode="ratio">1</param>',
            brand_param,
            *extra_params,
            f'    <weight>{DEFAULT_WEIGHT}</weight>',
            f'    <width>{DEFAULT_WIDTH}</width>',
            f'    <height>{DEFAULT_HEIGHT}</height>',
            f'    <length>{DEFAULT_LENGTH}</length>',
            '  </offer>',
        ]

        lines.extend(offer)
        cnt_total += 1

    lines += ['</offers>', '</yml_catalog>']

    # 5. Збереження
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))

    size_kb = os.path.getsize(output_file) // 1024

    # 6. Статистика
    logger.success(f"XML збережено: {output_file} ({cnt_total} офферів, {size_kb} KB)")

    sep = '=' * 52
    print(f'\n{sep}')
    print(f'  Генерація: {output_file}')
    print(sep)
    cnt_no_pics = cnt_total - cnt_with_pics - cnt_pics_from_feed
    print(f'  Записів у файлі:         {len(records)}')
    print(f'  З наявністю "+":         {len(filtered)}')
    print(f'  Згенеровано офферів:     {cnt_total}')
    print(f'  Пропущено (ціна=0):      {cnt_no_price}')
    print(f'  Пропущено (немає арт.):  {cnt_no_article}')
    print(f'  З фото (з БД):           {cnt_with_pics}')
    print(f'  З фото (з feed):         {cnt_pics_from_feed}')
    print(f'  Без фото:                {cnt_no_pics}')
    print(f'  Опис з feed:             {cnt_desc_from_feed}')
    print(f'  Опис авто-генерація:     {cnt_desc_auto}')
    print(f'  Vendor з feed:           {cnt_vendor_from_feed}')
    print(f'  Vendor дефолт (Carvol):  {cnt_vendor_default}')
    print(f'  Vendor code (Єпіцентр):  {cnt_vendor_valid}')
    print(f'  Vendor=Інше (невідомий): {cnt_vendor_other}')
    print(f'  Розмір файлу:            {size_kb} KB')
    print(f'\n  Детектовані колонки:')
    for field, idx in col.items():
        print(f'    {field:12} → [{idx}] "{headers[idx]}"')
    print(f'\n  Топ категорій Єпіцентру:')
    for cat, cnt in sorted(cat_stats.items(), key=lambda x: -x[1])[:15]:
        print(f'    {cnt:5}  {cat}')
    if vendor_unknown_stats:
        print(f'\n  Невідомі бренди (топ-20):')
        for brand, cnt in sorted(vendor_unknown_stats.items(), key=lambda x: -x[1])[:20]:
            print(f'    {cnt:5}  {brand}')
    if price_samples:
        print(f'\n  Приклади ціноутворення (РРЦ → ціна з комісією 15%):')
        print(f'  {"Артикул":<20} {"Кат":>6}  {"РРЦ (uah)":>12}  {"→":>2}  {"Ціна продажу":>12}  {"Надбавка":>8}')
        for art, cat, rrc, sp in price_samples:
            markup = sp - rrc
            print(f'  {art:<20} {cat:>6}  {rrc:>12.2f}  {"→":>2}  {sp:>12.2f}  {markup:>+8.2f}')
    print(sep)

    return cnt_total


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Генератор XML Єпіцентру з прайсу Carvol (SpreadsheetML)'
    )
    parser.add_argument('--input',  default=INPUT_FILE,  help='Шлях до SpreadsheetML файлу')
    parser.add_argument('--output', default=OUTPUT_FILE, help='Шлях для збереження XML')
    parser.add_argument('--feed',   default=FEED_FILE,   help='Шлях до Rozetka XML feed (описи/фото/vendor)')
    args = parser.parse_args()

    total = generate_xml(args.input, args.output, args.feed)
    sys.exit(0 if total > 0 else 1)

````

### `tools/epicentr_postprocess.py` — 56 рядків

````python
import re, os

src = 'exports/carvol_epicentr_new.xml'
dst = 'exports/carvol_epicentr.xml'

with open(src, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Фільтр фото + розбивка на офери
header, rest = content.split('<offers>', 1)
body, footer = rest.rsplit('</offers>', 1)

offers_raw = re.findall(r'<offer[^>]*>.*?</offer>', body, re.DOTALL)
print('Всього офферів:', len(offers_raw))

# 2. Залишаємо тільки з фото
with_photo = [o for o in offers_raw if '<picture>' in o]
print('З фото:', len(with_photo))

# 3. Замінюємо 2874 → 2848
fixed = []
for o in with_photo:
    o = o.replace('code="2874">Автосвітло', 'code="2848">Аксесуари для автосигналізацій')
    fixed.append(o)

# 4. Дедупліація по id
seen_ids = set()
deduped = []
for o in fixed:
    m = re.search(r'<offer id="([^"]+)"', o)
    if m:
        oid = m.group(1)
        if oid not in seen_ids:
            seen_ids.add(oid)
            deduped.append(o)
print('Після дедуп:', len(deduped), '(видалено дублів:', len(fixed) - len(deduped), ')')

# 5. Обрізаємо назви > 150 символів
result = []
for o in deduped:
    def trim_name(m):
        tag, text, close = m.group(1), m.group(2), m.group(3)
        if len(text) > 150:
            text = text[:147] + '...'
        return tag + text + close
    o = re.sub(r'(<name[^>]*>)([^<]{151,})(</name>)', trim_name, o)
    result.append(o)

# 6. Виправляємо подвійне закриття в кінці
new_content = header + '<offers>\n' + '\n'.join(result) + '\n</offers>\n</yml_catalog>'

with open(dst, 'w', encoding='utf-8') as f:
    f.write(new_content)

size_mb = os.path.getsize(dst) / 1024 / 1024
print('Збережено:', dst, '(%d KB)' % (size_mb * 1024))

````

### `tools/epicentr_xml_checker.py` — 418 рядків

````python
#!/usr/bin/env python3
"""
tools/epicentr_xml_checker.py
Повна перевірка XML-файлу Єпіцентру перед імпортом.

Запуск:
    python3 tools/epicentr_xml_checker.py ~/Downloads/carvol_epicentr.xml
"""

import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

# ── Константи ────────────────────────────────────────────────────────────────

VALID_CATS = {'2821', '2848', '2866', '2874', '3729', '8743'}
WARN_CATS  = {'2883', '4907'}   # 4907 → всі йдуть у 2866

REQUIRED_PARAMS: dict[str, list[str]] = {
    '2821': ['10986', '11971', '4857', '5290', '5291', '78', '826', 'measure', 'ratio', 'brand'],
    '2848': ['measure', 'ratio', 'brand'],
    # 2866 regular (1DIN/2DIN/Android)
    '2866': ['11263', '1548', '4866', '6534', '6546', '6547', 'measure', 'ratio', 'brand'],
    # 2866 штатна — визначається за наявністю "штатн" у назві
    '2866s': ['103', '1382', '1384', '1386', '5093', '6187', '78', 'measure', 'ratio', 'brand'],
    '3729': ['11926', '1514', '4866', '6510', '6513', '6564', 'measure', 'ratio', 'brand'],
    '8743': ['12097', '4866', '51', '52', '5575', 'measure', 'ratio', 'brand'],
}

W = 48   # inner width of report box (between ║ and ║)


# ── Хелпери ──────────────────────────────────────────────────────────────────

def _emoji_width(s: str) -> int:
    """Повертає приблизну display-ширину рядка (emoji = 2 cols)."""
    # emoji: ✅ ❌ ⚠️ — кожен займає 2 позиції в терміналі
    extra = sum(1 for ch in s if ch in '✅❌⚠️')
    return len(s) + extra


def _row(text: str) -> str:
    dw = _emoji_width(text)
    inner = f' {text} '
    inner_dw = dw + 2
    if inner_dw < W:
        inner = inner + ' ' * (W - inner_dw)
    elif inner_dw > W:
        # обрізаємо по символах (не по display width)
        inner = inner[:W - 1] + '…'
    return f'║{inner}║'


def _sep() -> str:
    return '╠' + '═' * W + '╣'


def _top() -> str:
    return '╔' + '═' * W + '╗'


def _bot() -> str:
    return '╚' + '═' * W + '╝'


def is_valid_pic_url(url: str) -> bool:
    if not url or not url.startswith('https://'):
        return False
    if len(url) <= 30:
        return False
    if not re.search(r'\d{7,}', url):
        return False
    return True


# ── Основна перевірка ────────────────────────────────────────────────────────

def check_xml(filepath: str) -> dict:
    r: dict = {
        'filepath': filepath,
        'parse_ok': False,
        'parse_error': '',
        'total_offers': 0,
        # дублікати
        'dup_ids': [],
        # назви
        'missing_name_ua': 0,
        'missing_name_ru': 0,
        'long_names': [],       # [(article, length), ...]
        # фото
        'no_pic': [],           # article ids без <picture>
        'bad_pic_count': 0,     # кількість окремих битих URL
        'bad_pic_articles': [], # article ids з хоча б одним битим URL
        # ціна
        'no_price': 0,
        'zero_price': 0,
        # категорії
        'invalid_cats': Counter(),
        'warn_cats': Counter(),
        'cat_stats': Counter(),
        # обов'язкові поля
        'no_vendor_code': 0,
        'no_country': 0,
        'bad_dims': 0,
        # обов'язкові params
        # cat_code → {'ok': n, 'bad': n, 'missing': Counter()}
        'params_by_cat': {c: {'ok': 0, 'bad': 0, 'missing': Counter()}
                          for c in REQUIRED_PARAMS},
    }

    # 1. Парсинг
    try:
        tree = ET.parse(filepath)
    except ET.ParseError as exc:
        r['parse_error'] = str(exc)
        return r

    root = tree.getroot()
    r['parse_ok'] = True

    if root.tag != 'yml_catalog':
        r['parse_error'] = f'корінь: {root.tag!r} (очікується yml_catalog)'

    offers_el = root.find('offers')
    if offers_el is None:
        r['parse_error'] += ' | тег <offers> відсутній'
        return r

    offers = offers_el.findall('offer')
    r['total_offers'] = len(offers)

    seen_ids: set[str] = set()

    for offer in offers:
        article = (offer.get('id') or '').strip()

        # 2. Дублікати
        if article in seen_ids:
            r['dup_ids'].append(article)
        else:
            seen_ids.add(article)

        # 3. Назви
        ua_names = [n for n in offer.findall('name') if n.get('lang') == 'ua']
        ru_names = [n for n in offer.findall('name') if n.get('lang') == 'ru']
        if not ua_names or not (ua_names[0].text or '').strip():
            r['missing_name_ua'] += 1
        else:
            ua_text = ua_names[0].text.strip()
            if len(ua_text) > 150:
                r['long_names'].append((article, len(ua_text)))
        if not ru_names or not (ru_names[0].text or '').strip():
            r['missing_name_ru'] += 1

        # 4. Фото
        pics = offer.findall('picture')
        if not pics:
            r['no_pic'].append(article)
        else:
            bad_in_offer = False
            for p in pics:
                url = (p.text or '').strip()
                if not is_valid_pic_url(url):
                    r['bad_pic_count'] += 1
                    bad_in_offer = True
            if bad_in_offer:
                r['bad_pic_articles'].append(article)

        # 5. Ціна
        price_el = offer.find('price')
        if price_el is None or not (price_el.text or '').strip():
            r['no_price'] += 1
        else:
            try:
                if float(price_el.text.strip()) <= 0:
                    r['zero_price'] += 1
            except ValueError:
                r['zero_price'] += 1

        # 6. Категорія
        cat_el = offer.find('category')
        cat_code = ((cat_el.get('code') or '') if cat_el is not None else '').strip()
        if cat_code:
            if cat_code not in VALID_CATS:
                r['invalid_cats'][cat_code] += 1
            if cat_code in WARN_CATS:
                r['warn_cats'][cat_code] += 1
            r['cat_stats'][cat_code] += 1

        # 7. Обов'язкові поля
        vendor_el = offer.find('vendor')
        if vendor_el is None or not (vendor_el.get('code') or '').strip():
            r['no_vendor_code'] += 1

        if offer.find('country_of_origin') is None:
            r['no_country'] += 1

        bad_dim = False
        for tag in ('weight', 'width', 'height', 'length'):
            el = offer.find(tag)
            if el is None:
                bad_dim = True
                break
            try:
                if float(el.text or '0') <= 0:
                    bad_dim = True
                    break
            except (ValueError, TypeError):
                bad_dim = True
                break
        if bad_dim:
            r['bad_dims'] += 1

        # 8. Обов'язкові params
        if cat_code in REQUIRED_PARAMS:
            # 2866: штатні магнітоли мають інший набір атрибутів ніж 1DIN/2DIN
            if cat_code == '2866':
                offer_name = (ua_names[0].text or '').lower() if ua_names else ''
                check_cat = '2866s' if 'штатн' in offer_name else '2866'
            else:
                check_cat = cat_code
            present = {(p.get('paramcode') or '').strip()
                       for p in offer.findall('param')}
            missing = set(REQUIRED_PARAMS[check_cat]) - present
            c = r['params_by_cat'][check_cat]
            if missing:
                c['bad'] += 1
                for m in missing:
                    c['missing'][m] += 1
            else:
                c['ok'] += 1

    return r


# ── Друк звіту ───────────────────────────────────────────────────────────────

def print_report(r: dict) -> bool:
    """Друкує звіт і повертає True якщо файл готовий до імпорту."""

    errors:   list[str] = []
    warnings: list[str] = []
    check_lines: list[str] = []

    def add(msg: str):
        check_lines.append(msg)
        if msg.startswith('❌'):
            errors.append(msg)
        elif msg.startswith('⚠'):
            warnings.append(msg)

    # 1. Структура XML
    if not r['parse_ok']:
        add(f'❌ Структура XML: {r["parse_error"]}')
    elif r['parse_error']:
        add(f'⚠️  Структура XML: {r["parse_error"]}')
    else:
        add('✅ Структура XML: OK')

    # 2. Дублікати
    dup_cnt = len(r['dup_ids'])
    if dup_cnt:
        add(f'❌ Дублікати: {dup_cnt} offer id')
    else:
        add('✅ Дублікати: 0')

    # 3. Назви
    miss_ua = r['missing_name_ua']
    miss_ru = r['missing_name_ru']
    long_n  = len(r['long_names'])
    if miss_ua or miss_ru or long_n:
        parts = []
        if miss_ua: parts.append(f'{miss_ua} без ua')
        if miss_ru: parts.append(f'{miss_ru} без ru')
        if long_n:  parts.append(f'{long_n} довших 150')
        add('❌ Назви: ' + ', '.join(parts))
    else:
        add('✅ Назви: всі ≤ 150 символів')

    # 4. Фото
    no_pic_cnt  = len(r['no_pic'])
    bad_pic_cnt = r['bad_pic_count']
    if no_pic_cnt or bad_pic_cnt:
        parts = []
        if no_pic_cnt:  parts.append(f'{no_pic_cnt} без фото')
        if bad_pic_cnt: parts.append(f'{bad_pic_cnt} битих URL')
        if no_pic_cnt:
            add('❌ Фото: ' + ', '.join(parts))
        else:
            add('⚠️  Фото: ' + ', '.join(parts))
    else:
        add('✅ Фото: всі валідні')

    # 5. Ціна
    price_bad = r['no_price'] + r['zero_price']
    if price_bad:
        add(f'❌ Ціна: {price_bad} офферів ≤ 0 або відсутня')
    else:
        add('✅ Ціна: всі > 0')

    # 6. Категорії
    invalid_cnt = sum(r['invalid_cats'].values())
    warn_cnt    = sum(r['warn_cats'].values())
    if invalid_cnt:
        add(f'❌ Категорії: {invalid_cnt} офферів з невалідним кодом')
    elif warn_cnt:
        add(f'⚠️  Категорії: {warn_cnt} офферів у 2883 (→ замінити на 2848)')
    else:
        add('✅ Категорії: всі валідні')

    # 7. Обов'язкові поля
    nvc = r['no_vendor_code']
    nc  = r['no_country']
    bd  = r['bad_dims']
    if nvc or nc or bd:
        parts = []
        if nvc: parts.append(f'{nvc} без vendor.code')
        if nc:  parts.append(f'{nc} без country')
        if bd:  parts.append(f'{bd} без dims')
        add('❌ Поля: ' + ', '.join(parts))
    else:
        add('✅ Поля (vendor/country/dims): OK')

    # 8. Обов'язкові params
    for cat_code in sorted(REQUIRED_PARAMS.keys()):
        c = r['params_by_cat'].get(cat_code, {})
        ok_n  = c.get('ok', 0)
        bad_n = c.get('bad', 0)
        total_cat = ok_n + bad_n
        if total_cat == 0:
            continue
        if bad_n:
            pct = int(bad_n / total_cat * 100)
            add(f'❌ Params {cat_code}: {bad_n}/{total_cat} без attrs ({pct}%)')
        else:
            add(f'✅ Params {cat_code}: {ok_n}/{ok_n} OK')

    # ── Друк рамки ──────────────────────────────────────────────────────────
    filepath = r['filepath']
    total    = r['total_offers']

    lines = [
        _top(),
        _row('    EPICENTR XML CHECKER REPORT    '),
        _sep(),
        _row(f'Файл: {os.path.abspath(filepath)}'),
        _row(f'Офферів: {total}'),
        _sep(),
    ]
    for cl in check_lines:
        lines.append(_row(cl))
    lines.append(_sep())

    ready = len(errors) == 0
    if ready:
        lines.append(_row('ГОТОВИЙ ДО ІМПОРТУ: ТАК ✅'))
    else:
        lines.append(_row('ГОТОВИЙ ДО ІМПОРТУ: НІ ❌'))
    lines.append(_bot())

    print('\n'.join(lines))

    # ── Детальна статистика ──────────────────────────────────────────────────
    if r['cat_stats']:
        print('\nСтатистика по категоріях:')
        for cat, cnt in sorted(r['cat_stats'].items(), key=lambda x: -x[1]):
            print(f'  {cat:>6}  {cnt:5}')

    if r['dup_ids']:
        print(f'\nПерші дублікати: {r["dup_ids"][:10]}')

    if r['long_names']:
        print('\nНадто довгі назви (топ-5):')
        for art, ln in r['long_names'][:5]:
            print(f'  {art}: {ln} символів')

    if r['no_pic']:
        print(f'\nАртикули без фото (топ-10): {r["no_pic"][:10]}')

    if r['bad_pic_articles']:
        print(f'\nАртикули з битими фото (топ-10): {r["bad_pic_articles"][:10]}')

    for cat_code in sorted(REQUIRED_PARAMS.keys()):
        c = r['params_by_cat'].get(cat_code, {})
        missing_c: Counter = c.get('missing', Counter())
        if not missing_c:
            continue
        print(f'\nВідсутні params у кат. {cat_code} (топ-5):')
        for param, cnt in missing_c.most_common(5):
            print(f'  paramcode={param!r:<12}  у {cnt} офферів')

    return ready


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(f'Використання: python3 {sys.argv[0]} <path/to/carvol_epicentr.xml>')
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f'Файл не знайдено: {filepath}')
        sys.exit(1)

    size_mb = os.path.getsize(filepath) / 1024 / 1024
    print(f'Перевірка: {filepath} ({size_mb:.1f} MB) ...\n')

    results = check_xml(filepath)
    ready   = print_report(results)
    sys.exit(0 if ready else 1)


if __name__ == '__main__':
    main()

````

### `agents/orders/rozetka_order_agent.py` — 832 рядків

````python
"""
rozetka_order_agent.py v4
=========================
v4:
- set_ttn: POST /orders/add-ttn (primary) з fallback на PATCH /orders/{id}
- process_order: confirm(2) → Excel Carvol → save 'accepted'; TTN окремо через бот
- save_to_db: зберігає phone/recipient/city для match_order_by_ttn_data
- get_orders_by_status: новий хелпер для пошуку за статусом
- set_ttn_and_ship: видалено; set_ttn тепер standalone (тільки TTN, без status)

Послідовність статусів:
  new (4) → підтверджено (2) → TTN додано (61) → передано в доставку (3)
"""
import os, sys, json, time, requests, smtplib, shutil
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import xml.etree.ElementTree as ET
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from loguru import logger
import xlsxwriter
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# === КОНСТАНТИ ===
ROZETKA_API_TOKEN = os.getenv('ROZETKA_API_TOKEN')
ROZETKA_BASE      = 'https://api-seller.rozetka.com.ua'

CARVOL_FEED = (
    'https://carvol.prom.ua/rozetka_feed.xml'
    '?rozetka_hash_tag=2251d0779efad97117ac08d7efd82c2f'
    '&product_ids=&label_ids=28618299&languages=uk%2Cru&group_ids='
)
CARVOL_EMAIL      = os.getenv('CARVOL_SUPPLIER_EMAIL', 'carvolua@gmail.com')
CARVOL_TG_CHAT_ID = os.getenv('CARVOL_TG_CHAT_ID', '')
SUPPLIER_CODE     = os.getenv('CARVOL_SUPPLIER_CODE', '')
SMTP_USER         = os.getenv('SMTP_USER')
SMTP_PASS         = os.getenv('SMTP_PASS')
SMTP_HOST         = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT         = int(os.getenv('SMTP_PORT', '587'))
TG_BOT_TOKEN      = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID        = os.getenv('TG_CHAT_ID')
CABINET_BASE    = 'https://cabinet-seller.rozetka.com.ua'
POLL_INTERVAL     = 300
MARKETPLACE       = 'Розетка'
FORBIDDEN_STATUSES = {40, 49, 6}  # 40=клієнт передумав, 49=небезпечний, 6=скасування

ORDERS_DIR = '/home/tek/agent-system/shared/feeds/orders'


# === TELEGRAM (адмін) ===
def tg(msg: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.warning(f'TG: {e}')


# === ТОКЕН ===
def get_token() -> str:
    if not ROZETKA_API_TOKEN:
        raise Exception('ROZETKA_API_TOKEN не задано в .env!')
    return ROZETKA_API_TOKEN


def rz_headers() -> dict:
    return {
        'Authorization':    f'Bearer {get_token()}',
        'Content-Type':     'application/json',
        'Content-Language': 'uk',
    }


# === ФІД CARVOL ===
_carvol_cache = {'data': {}, 'updated': None}


def get_carvol_feed(force=False) -> dict:
    """Повертає {article: {available, price, qty}} з Carvol фіду."""
    now = datetime.now()
    if (not force and _carvol_cache['updated'] and
            (now - _carvol_cache['updated']).seconds < 3600):
        return _carvol_cache['data']

    logger.info('Завантажуємо Carvol фід...')
    r = requests.get(CARVOL_FEED, timeout=120)
    root = ET.fromstring(r.content)
    offers = root.find('shop').find('offers').findall('offer')

    data = {}
    for offer in offers:
        article_el = offer.find('article')
        if article_el is None:
            continue
        article  = (article_el.text or '').strip()
        price_el = offer.find('price')
        qty_el   = offer.find('stock_quantity')
        qty      = int(qty_el.text or 0) if qty_el is not None else 0
        data[article] = {
            'available': offer.get('available', 'false').lower() == 'true' and qty > 0,
            'price':     float(price_el.text or 0) if price_el is not None else 0,
            'qty':       qty,
        }

    _carvol_cache['data']    = data
    _carvol_cache['updated'] = now
    logger.info(f'Carvol фід: {len(data)} SKU')
    return data


# === РОЗЕТКА API ===

def get_new_orders() -> list:
    """Отримати нові замовлення: types=4 + status=1 + status=26 + status=55 + status=61, без дублів."""
    params_base = {
        'expand': 'purchases,delivery,status_available,payment_type',
        'sort':   '-id',
        'page':   1,
    }
    results = {}

    for extra_key, extra_val in [('types', 4), ('status', 1), ('status', 26), ('status', 55), ('status', 61)]:
        try:
            r = requests.get(
                f'{ROZETKA_BASE}/orders/search',
                headers=rz_headers(),
                verify=False,
                params={**params_base, extra_key: extra_val},
                timeout=30
            )
            if r.status_code == 200 and r.json().get('success'):
                for o in r.json()['content'].get('orders', []):
                    results[o['id']] = o
            else:
                logger.error(f'get_new_orders {extra_key}={extra_val}: {r.text[:200]}')
        except Exception as e:
            logger.error(f'get_new_orders {extra_key}={extra_val}: {e}')

    return list(results.values())


def get_orders_by_status(status: int) -> list:
    """Пошук замовлень за статусом через GET /orders/search?status={status}."""
    try:
        r = requests.get(
            f'{ROZETKA_BASE}/orders/search',
            headers=rz_headers(),
            verify=False,
            params={
                'status': status,
                'expand': 'purchases,delivery,payment_type',
                'sort':   '-id',
                'page':   1,
            },
            timeout=30
        )
        if r.status_code == 200 and r.json().get('success'):
            return r.json()['content'].get('orders', [])
        logger.error(f'get_orders_by_status({status}): {r.text[:200]}')
        return []
    except Exception as e:
        logger.error(f'get_orders_by_status: {e}')
        return []


def get_order_details(order_id: int) -> dict:
    """Отримати повні деталі замовлення."""
    try:
        r = requests.get(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(),
            verify=False,
            params={'expand': 'purchases,delivery,status_available,payment_type'},
            timeout=30
        )
        return r.json().get('content', {}) if r.status_code == 200 else {}
    except Exception as e:
        logger.error(f'get_order_details: {e}')
        return {}


def change_status(order_id: int, status: int) -> bool:
    """Змінити статус замовлення через PATCH /orders/{id}."""
    try:
        r = requests.patch(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(),
            verify=False,
            json={'status': status},
            timeout=15
        )
        data = r.json()
        if data.get('success'):
            logger.success(f'Статус #{order_id} → {status}')
            return True
        logger.warning(f'change_status failed: {data}')
        return False
    except Exception as e:
        logger.error(f'change_status: {e}')
        return False


def set_ttn(order_id: int, ttn: str) -> bool:
    """
    Встановити ТТН для замовлення.
    Після успіху статус автоматично стає 61 (TTN додано).
    Потім викликати change_status(3) для передачі в доставку.

    Пробує:
      1. POST /orders/add-ttn  {"order_id", "ttn", "delivery_service_id": 1}
      2. Fallback: PATCH /orders/{id} {"ttn": ttn}
    """
    # Спроба 1: POST /orders/add-ttn
    try:
        r = requests.post(
            f'{ROZETKA_BASE}/orders/add-ttn',
            headers=rz_headers(),
            verify=False,
            json={'order_id': order_id, 'ttn': ttn, 'delivery_service_id': 1},
            timeout=15
        )
        data = r.json()
        if data.get('success'):
            logger.success(f'ТТН {ttn} додано до #{order_id} (POST add-ttn → статус 61)')
            return True
        logger.warning(f'set_ttn POST add-ttn failed ({data}), trying PATCH fallback...')
    except Exception as e:
        logger.warning(f'set_ttn POST add-ttn exception ({e}), trying PATCH fallback...')

    # Fallback: PATCH /orders/{id}
    try:
        r = requests.patch(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(),
            verify=False,
            json={'ttn': ttn},
            timeout=15
        )
        data = r.json()
        if data.get('success'):
            logger.success(f'ТТН {ttn} додано до #{order_id} (PATCH fallback)')
            return True
        logger.warning(f'set_ttn PATCH fallback failed: {data}')
        return False
    except Exception as e:
        logger.error(f'set_ttn PATCH fallback: {e}')
        return False


def confirm_order(order_id: int) -> bool:
    """Підтвердити замовлення (status=2) — перевіряє доступні переходи."""
    def _safe_patch(target_status: int, label: str) -> bool:
        if target_status in FORBIDDEN_STATUSES:
            logger.error(
                f'confirm_order #{order_id}: відхилено PATCH на {target_status} '
                f'— статус у FORBIDDEN_STATUSES {FORBIDDEN_STATUSES}'
            )
            return False
        rp   = requests.patch(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(), verify=False,
            json={'status': target_status, 'comment': 'Підтверджено'}, timeout=15
        )
        data = rp.json()
        if data.get('success'):
            logger.success(f'Статус #{order_id} → {target_status} ({label})')
            return True
        logger.warning(f'confirm_order PATCH {target_status} failed: {data}')
        return False

    try:
        r = requests.get(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(),
            verify=False,
            params={'expand': 'status_available'},
            timeout=30
        )
        if r.status_code != 200 or not r.json().get('success'):
            logger.error(f'confirm_order GET #{order_id}: {r.text[:200]}')
            return False
        order_data     = r.json().get('content', {})
        current_status = order_data.get('status')
        available_raw  = [s.get('child_id') for s in (order_data.get('status_available') or []) if s.get('child_id')]
        # Ніколи не використовувати заборонені статуси
        available      = [s for s in available_raw if s not in FORBIDDEN_STATUSES]
        if available_raw != available:
            blocked = [s for s in available_raw if s in FORBIDDEN_STATUSES]
            logger.warning(f'confirm_order #{order_id}: заблоковано небезпечні статуси {blocked}')
        logger.info(f'confirm_order #{order_id}: current={current_status}, available={available}')

        if current_status in (2, 55, 61):
            logger.info(f'#{order_id} вже підтверджено (status={current_status})')
            return True

        # Зі статусу 1 дозволено лише переходи на 2 або 55
        allowed_targets = {2, 55} - FORBIDDEN_STATUSES

        if 2 in available and 2 in allowed_targets:
            return _safe_patch(2, 'підтверджено')

        if 55 in available and 55 in allowed_targets:
            if not _safe_patch(55, 'проміжний 55'):
                return False
            logger.info(f'Статус #{order_id} → 55, тепер → 2')
            return _safe_patch(2, 'підтверджено після 55')

        logger.warning(
            f'confirm_order #{order_id}: перехід на 2 недоступний. '
            f'current={current_status}, available={available}'
        )
        if current_status == 1:
            # Спробуємо cabinet-seller PUT як fallback для статусу 1
            logger.info(f'confirm_order #{order_id}: пробуємо cabinet-seller PUT...')
            try:
                rc = requests.put(
                    f"{CABINET_BASE}/orders/{order_id}",
                    headers=rz_headers(),
                    verify=False,
                    json={"status": 55, "ttn": "", "id": order_id},
                    timeout=15
                )
                if rc.json().get("success"):
                    logger.success(f'confirm_order #{order_id}: cabinet-seller 55 OK')
                    return True
            except Exception as ce:
                logger.warning(f'confirm_order cabinet fallback: {ce}')
            return None  # sentinel: потрібне ручне підтвердження
        return False
    except Exception as e:
        logger.error(f'confirm_order: {e}')
        return False


def cancel_order(order_id: int, comment: str = 'Товар відсутній у постачальника') -> bool:
    """Скасувати замовлення (status=6)."""
    try:
        r = requests.patch(
            f'{ROZETKA_BASE}/orders/{order_id}',
            headers=rz_headers(),
            verify=False,
            json={'status': 6, 'comment': comment},
            timeout=15
        )
        data = r.json()
        if data.get('success'):
            logger.success(f'Замовлення #{order_id} скасовано')
            return True
        logger.warning(f'cancel_order failed: {data}')
        return False
    except Exception as e:
        logger.error(f'cancel_order: {e}')
        return False


# === БД ===

def is_already_processed(order_id: int) -> bool:
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS rozetka_processed_orders (
                order_id     BIGINT PRIMARY KEY,
                status       VARCHAR(50),
                total_price  NUMERIC(12,2),
                processed_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        conn.commit()
        cur.execute('SELECT 1 FROM rozetka_processed_orders WHERE order_id = %s', (order_id,))
        exists = cur.fetchone() is not None
        cur.close(); conn.close()
        return exists
    except:
        return False


def get_db_status(order_id: int):
    """Повертає статус замовлення з БД або None якщо не знайдено."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute(
            'CREATE TABLE IF NOT EXISTS rozetka_processed_orders '
            '(order_id BIGINT PRIMARY KEY, status VARCHAR(50), '
            'total_price NUMERIC(12,2), processed_at TIMESTAMP DEFAULT NOW())'
        )
        cur.execute('SELECT status FROM rozetka_processed_orders WHERE order_id = %s', (order_id,))
        row = cur.fetchone()
        cur.close(); conn.close()
        return row["status"] if row else None
    except:
        return None


def delete_from_db(order_id: int):
    """Видаляє замовлення з БД для повторної обробки."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('DELETE FROM rozetka_processed_orders WHERE order_id = %s', (order_id,))
        conn.commit()
        cur.close(); conn.close()
        logger.info(f'#{order_id} видалено з БД для повторної обробки')
    except Exception as e:
        logger.error(f'delete_from_db: {e}')


def _get_db_processed_at(order_id: int):
    """Повертає processed_at для замовлення або None."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('SELECT processed_at FROM rozetka_processed_orders WHERE order_id = %s', (order_id,))
        row = cur.fetchone()
        cur.close(); conn.close()
        return row['processed_at'] if row else None
    except:
        return None


def _update_db_status(order_id: int, status: str):
    """Оновлює тільки статус в БД без зміни processed_at."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('UPDATE rozetka_processed_orders SET status=%s WHERE order_id=%s', (status, order_id))
        conn.commit()
        cur.close(); conn.close()
        logger.debug(f'#{order_id} статус БД → {status}')
    except Exception as e:
        logger.error(f'_update_db_status: {e}')


def save_to_db(order: dict, status: str):
    """Зберігає замовлення в БД включно з phone/recipient/city для TTN-матчингу."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        total = float(order.get('amount_with_discount') or order.get('amount') or 0)

        ri = _order_recipient_info(order) if order.get('id') else {}
        phone     = ri.get('phone', '') or ''
        recipient = ri.get('customer', '') or ''
        city      = ri.get('city', '') or ''

        cur.execute('''
            INSERT INTO rozetka_processed_orders
                (order_id, status, total_price, phone, recipient, city)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (order_id) DO UPDATE
            SET status=EXCLUDED.status,
                total_price=EXCLUDED.total_price,
                phone=COALESCE(EXCLUDED.phone, rozetka_processed_orders.phone),
                recipient=COALESCE(EXCLUDED.recipient, rozetka_processed_orders.recipient),
                city=COALESCE(EXCLUDED.city, rozetka_processed_orders.city),
                processed_at=NOW()
        ''', (order['id'], status, total, phone or None, recipient or None, city or None))
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        logger.error(f'save_to_db: {e}')


# === HELPЕР: дані отримувача ===

def _order_recipient_info(order: dict) -> dict:
    """Повертає {customer, phone, city, warehouse, total, payment_str}."""
    delivery  = order.get('delivery') or {}
    rec_title = delivery.get('recipient_title') or order.get('recipient_title') or order.get('user_title') or {}
    if isinstance(rec_title, dict):
        customer = (
            rec_title.get('full_name', '')
            or f"{rec_title.get('first_name','')} {rec_title.get('last_name','')}".strip()
        )
    else:
        customer = str(rec_title)
    phone     = delivery.get('recipient_phone') or order.get('recipient_phone') or order.get('user_phone', '')
    city_obj  = delivery.get('city') or {}
    city_name = city_obj.get('name_ua') or city_obj.get('name', '')
    warehouse = (
        delivery.get('warehouse_description', '')
        or delivery.get('place_name', '')
        or (f"{delivery.get('place_street','')} {delivery.get('place_number','')}".strip()
            if delivery.get('place_street') else '')
    )
    total        = float(order.get('amount_with_discount') or order.get('amount') or 0)
    payment_type = order.get('payment_type', 'cash')
    payment_str  = 'Накладений платіж' if payment_type in ('cash', 'cod') else f'Передоплата ({payment_type})'
    return dict(customer=customer, phone=phone, city=city_name,
                warehouse=warehouse, total=total, payment_str=payment_str)


# === EXCEL БЛАНК ===

def create_order_excel(order: dict, items_info: list) -> str:
    order_id = order.get('id', 'unknown')
    os.makedirs(ORDERS_DIR, exist_ok=True)
    filename = f'{ORDERS_DIR}/rozetka_order_{order_id}_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'

    wb         = xlsxwriter.Workbook(filename)
    ws         = wb.add_worksheet('Замовлення')
    bold_fmt   = wb.add_format({'bold': True, 'font_size': 11})
    header_fmt = wb.add_format({'bold': True, 'bg_color': '#1F4E79',
                                'font_color': 'white', 'border': 1, 'align': 'center'})
    cell_fmt   = wb.add_format({'border': 1})
    sku_fmt    = wb.add_format({'border': 1, 'bold': True})
    red_bold   = wb.add_format({'bold': True, 'font_color': 'red'})
    wrap_fmt   = wb.add_format({'text_wrap': True})

    ws.set_column('A:A', 5)
    ws.set_column('B:B', 22)
    ws.set_column('C:C', 55)
    ws.set_column('D:D', 14)

    ri = _order_recipient_info(order)

    ws.write('A1', 'Перевозчик', bold_fmt);  ws.write('C1', 'Нова Пошта')
    ws.write('A2', 'Оплата', bold_fmt);      ws.write('C2', f'{ri["payment_str"]} {ri["total"]:.0f} грн')
    ws.write('A3', 'Коментар', bold_fmt)
    ws.write('C3', f'{ri["customer"]}  {ri["phone"]}\n{ri["city"]} {ri["warehouse"]}'.strip(), wrap_fmt)
    ws.set_row(2, 35)
    ws.write('A4', f'Замовлення {MARKETPLACE} #{order_id}')
    ws.write('C4', f'Дата: {datetime.now().strftime("%d.%m.%Y %H:%M")}')
    if SUPPLIER_CODE:
        ws.write('A5', f'Код клієнта: {SUPPLIER_CODE}', red_bold)

    row = 6
    for col, h in enumerate(['№', 'Артикул', 'Найменування', 'Кількість']):
        ws.write(row, col, h, header_fmt)
    row += 1
    for idx, item in enumerate(items_info, 1):
        ws.write(row, 0, idx, cell_fmt)
        ws.write(row, 1, item.get('sku', ''), sku_fmt)
        ws.write(row, 2, item.get('name', '')[:80], cell_fmt)
        ws.write(row, 3, item.get('quantity', 1), cell_fmt)
        row += 1

    wb.close()
    return filename


# === ВІДПРАВКА ПОСТАЧАЛЬНИКУ ===

def send_excel_to_carvol_telegram(excel_path: str, order_id: int,
                                   items_info: list, order: dict) -> bool:
    """Надсилає Excel файл у Telegram чат Carvol."""
    if not CARVOL_TG_CHAT_ID:
        logger.warning('CARVOL_TG_CHAT_ID не задано — Telegram не відправлено')
        return False
    if not TG_BOT_TOKEN:
        logger.warning('TG_BOT_TOKEN не задано — Telegram не відправлено')
        return False

    ri            = _order_recipient_info(order)
    delivery_line = f'{ri["city"]} {ri["warehouse"]}'.strip() or 'Нова Пошта'
    items_text    = '\n'.join(
        f"{i}. {item.get('sku','')} × {item.get('quantity',1)}"
        for i, item in enumerate(items_info, 1)
    )
    caption = (
        f'📦 Замовлення {MARKETPLACE} #{order_id}\n'
        f'👤 {ri["customer"]}  {ri["phone"]}\n'
        f'🏙 {delivery_line}\n'
        f'💳 {ri["payment_str"]}\n'
        f'💰 {ri["total"]:.0f} грн\n'
        f'🔧 {items_text}'
    )

    try:
        with open(excel_path, 'rb') as f:
            r = requests.post(
                f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendDocument',
                data={'chat_id': CARVOL_TG_CHAT_ID, 'caption': caption},
                files={'document': (os.path.basename(excel_path), f,
                                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
                timeout=30,
            )
        resp = r.json()
        if resp.get('ok'):
            logger.success(f'Excel #{order_id} відправлено Carvol (chat {CARVOL_TG_CHAT_ID})')
            return True
        logger.warning(f'Telegram Carvol: {resp}')
        return False
    except Exception as e:
        logger.error(f'send_excel_to_carvol_telegram: {e}')
        return False


def send_to_supplier(order: dict, excel_path: str, items_info: list) -> bool:
    """Fallback: відправка Excel поштою на CARVOL_EMAIL."""
    order_id      = order['id']
    ri            = _order_recipient_info(order)
    delivery_str  = f'{ri["city"]} {ri["warehouse"]}'.strip() or 'Нова Пошта'
    items_text    = '\n'.join(
        f"{i}. {item.get('sku','')} | {item.get('name','')[:50]} | {item.get('quantity',1)} шт."
        for i, item in enumerate(items_info, 1)
    )
    excel_filename = os.path.basename(excel_path)
    excel_url      = f'https://usa1.tail3a617f.ts.net/orders/{excel_filename}'

    body = (
        f"Доброго дня!\n\n"
        f"Замовлення #{order_id} від {datetime.now().strftime('%d.%m.%Y')}\n"
        f"{f'Код клієнта: {SUPPLIER_CODE}' if SUPPLIER_CODE else ''}\n\n"
        f"Товари:\n{items_text}\n\n"
        f"Отримувач: {ri['customer']}\n"
        f"Телефон: {ri['phone']}\n"
        f"Доставка: {delivery_str}\n"
        f"Оплата: {ri['payment_str']} {ri['total']:.0f} грн\n\n"
        f"Excel бланк: {excel_url}\n\n"
        f"З повагою,\nklatch1.shop ({MARKETPLACE})\n"
    )
    if not SMTP_USER or not SMTP_PASS:
        logger.warning('SMTP не налаштовано — email не відправлено')
        return False

    msg = MIMEMultipart()
    msg['From']    = SMTP_USER
    msg['To']      = CARVOL_EMAIL
    msg['Subject'] = f'Замовлення #{order_id} від {datetime.now().strftime("%d.%m.%Y")} ({MARKETPLACE})'
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    with open(excel_path, 'rb') as f:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{excel_filename}"')
        msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.success(f'Email відправлено #{order_id} → {CARVOL_EMAIL}')
        return True
    except Exception as e:
        logger.error(f'Email: {e}')
        return False


# === ОБРОБКА ЗАМОВЛЕННЯ ===

def process_order(order: dict, feed: dict):
    """
    Послідовність:
      new(4) → confirm(2) → Excel до Carvol → save 'accepted'
      TTN приходить окремо через Telegram-бот:
        set_ttn() → статус 61 (автоматично) → change_status(3)
    """
    order_id = order.get('id')
    if not order_id:
        return

    db_status          = get_db_status(order_id)
    skip_payment_check = False   # True коли оплата підтверджена, щоб не повторити waiting_payment
    if db_status == 'pending_manual':
        current = get_order_details(order_id)
        rz_status = current.get('status')
        if rz_status == 1:
            logger.debug(f'#{order_id} pending_manual — статус Розетки ще 1, пропускаємо')
            return
        logger.info(f'#{order_id} pending_manual — статус Розетки змінився на {rz_status}, обробляємо знову')
        delete_from_db(order_id)
    elif db_status in ('waiting_payment', 'waiting_payment_alerted'):
        current = get_order_details(order_id)
        rz_status = current.get('status')
        if rz_status == 26:
            # Замовлення ще не оплачене
            if db_status == 'waiting_payment':
                saved_at = _get_db_processed_at(order_id)
                if saved_at:
                    age_hours = (datetime.now() - saved_at).total_seconds() / 3600
                    if age_hours >= 24:
                        ri = _order_recipient_info(current if current else order)
                        tg(f'⏳⚠️ <b>{MARKETPLACE} #{order_id} — очікує оплату вже {int(age_hours)} год!</b>\n'
                           f'Клієнт: {ri["customer"]} {ri["phone"]}\n'
                           f'💰 {ri["total"]:.0f} грн\nПеревірте статус оплати в кабінеті.')
                        _update_db_status(order_id, 'waiting_payment_alerted')
            logger.debug(f'#{order_id} waiting_payment — статус Розетки ще 26, пропускаємо')
            return
        logger.info(f'#{order_id} waiting_payment — статус змінився на {rz_status}, обробляємо знову')
        delete_from_db(order_id)
        skip_payment_check = True  # payment_type не змінюється, але оплата вже підтверджена статусом
    elif db_status is not None:
        return

    logger.info(f'Обробляємо {MARKETPLACE} #{order_id}')

    details   = get_order_details(order_id) or order
    purchases = details.get('purchases') or order.get('purchases') or []

    if not purchases:
        logger.warning(f'#{order_id} — purchases порожній')
        save_to_db({'id': order_id, 'amount': 0}, 'no_purchases')
        return

    payment_type  = details.get('payment_type', 'cash')
    is_prepaid    = payment_type not in ('cash', 'cod')
    items_info    = []
    all_available = True

    for purchase in purchases:
        offer_id  = (purchase.get('item') or {}).get('article') or purchase.get('article', '')
        sku       = str(offer_id).strip()
        feed_item = feed.get(sku, {})
        available = feed_item.get('available', False)
        qty       = feed_item.get('qty', 0)
        if not available:
            all_available = False
            logger.warning(f'  {sku} — немає в Carvol (qty={qty})')
        items_info.append({
            'sku':       sku,
            'name':      purchase.get('item_name') or purchase.get('name', ''),
            'quantity':  purchase.get('quantity', 1),
            'price':     purchase.get('price', 0),
            'available': available,
            'feed_qty':  qty,
        })

    ri = _order_recipient_info(details)

    # Товар відсутній → скасування
    if not all_available:
        unavailable = [i['sku'] for i in items_info if not i['available']]
        cancel_order(order_id, 'Товар відсутній у постачальника')
        save_to_db(details, 'cancelled_no_stock')
        tg(f'❌ <b>{MARKETPLACE} #{order_id} — товар відсутній!</b>\n'
           f'Клієнт: {ri["customer"]} {ri["phone"]}\n'
           f'Відсутні SKU: {", ".join(unavailable)}\nСкасовано.')
        return

    # Передоплата → чекаємо підтвердження оплати (пропускаємо якщо оплата вже підтверджена)
    if is_prepaid and not skip_payment_check:
        save_to_db(details, 'waiting_payment')
        tg(f'⏳ <b>{MARKETPLACE} #{order_id} — очікує оплату</b>\n'
           f'Клієнт: {ri["customer"]} {ri["phone"]}\n'
           f'Тип: {payment_type} | 💰 {ri["total"]:.0f} грн')
        return

    # Статус 61 — ТТН вже встановлено (раніше оброблено або через бот);
    # якщо є в БД як accepted — пропускаємо; якщо немає — відправляємо Excel і зберігаємо
    if details.get('status') == 61:
        if get_db_status(order_id) == 'accepted':
            logger.debug(f'#{order_id} статус 61, вже в БД як accepted — пропускаємо')
            return
        excel   = create_order_excel(details, items_info)
        tg_sent = send_excel_to_carvol_telegram(excel, order_id, items_info, details)
        save_to_db(details, 'accepted')
        sent_icon = '📲 Telegram' if tg_sent else '❌ не відправлено'
        tg(f'📦 <b>{MARKETPLACE} #{order_id} статус 61 — збережено!</b>\n'
           f'Клієнт: {ri["customer"]}\nТелефон: {ri["phone"]}\n'
           f'💰 {ri["total"]:.0f} грн | Carvol: {sent_icon}')
        logger.info(f'#{order_id} статус 61 — Excel відправлено, збережено як accepted')
        return

    # Підтверджуємо (status=2)
    confirm_result = confirm_order(order_id)
    if confirm_result is None:
        save_to_db(details, 'pending_manual')
        tg(
            f'⚠️ Замовлення <b>#{order_id}</b> потребує ручного підтвердження '
            f'в кабінеті Розетки.\n'
            f'Клієнт: {ri["customer"]} {ri["phone"]} {ri["total"]:.0f} грн\n'
            f'Після підтвердження агент обробить автоматично.'
        )
        return
    if not confirm_result:
        logger.error(f'Не вдалось підтвердити #{order_id}')
        return

    # Відправляємо Excel Carvol (Telegram → fallback email)
    excel      = create_order_excel(details, items_info)
    tg_sent    = send_excel_to_carvol_telegram(excel, order_id, items_info, details)
    email_sent = send_to_supplier(details, excel, items_info) if not tg_sent else False

    # Зберігаємо з phone/recipient/city для подальшого TTN-матчингу
    save_to_db(details, 'accepted')

    sent_icon = '📲 Telegram' if tg_sent else ('📧 Email' if email_sent else '❌')
    tg(f'📦 <b>{MARKETPLACE} #{order_id} прийнято!</b>\n'
       f'Клієнт: {ri["customer"]}\nТелефон: {ri["phone"]}\n'
       f'Товарів: {len(items_info)} | 💰 {ri["total"]:.0f} грн\n'
       f'Carvol: {sent_icon}\n'
       f'⏳ Чекаємо PDF з ТТН від Carvol')


# === ГОЛОВНИЙ ЦИКЛ ===

def main():
    logger.add('/tmp/rozetka_order_agent.log', rotation='10 MB', level='INFO')
    logger.info(f'=== {MARKETPLACE} Order Agent v4 запущено ===')
    os.makedirs(ORDERS_DIR, exist_ok=True)

    if not ROZETKA_API_TOKEN:
        logger.error('ROZETKA_API_TOKEN не задано в .env!')
        tg(f'❌ {MARKETPLACE} Order Agent: немає API токену')
        return

    tg(f'🚀 <b>{MARKETPLACE} Order Agent v4 запущено</b>')

    while True:
        try:
            feed   = get_carvol_feed()
            orders = get_new_orders()
            if orders:
                logger.info(f'Знайдено {len(orders)} нових замовлень')
                for order in orders:
                    process_order(order, feed)
            else:
                logger.debug('Нових замовлень немає')
        except Exception as e:
            logger.error(f'Помилка циклу: {e}')
            tg(f'⚠️ <b>{MARKETPLACE} Order Agent помилка:</b> {e}')

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()

````

### `agents/orders/rozetka_price_manager.py` — 294 рядків

````python
"""
agents/orders/rozetka_price_manager.py
=======================================
Управління цінами Розетки через XML + CSV.

РЕЖИМ 1: python3 agents/orders/rozetka_price_manager.py --generate
  - Питає корекцію % від РРЦ
  - Читає живий фід Carvol (або data/carvol_feed.xml якщо є)
  - Зберігає data/rozetka_prices.csv

РЕЖИМ 2: python3 agents/orders/rozetka_price_manager.py --apply
  - Читає data/rozetka_prices.csv (може бути відредагований вручну)
  - Оновлює data/carvol_rozetka.xml (тег <price> по <article>)
  - Git commit + push
"""

import os, sys, csv, math, argparse, subprocess
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / '.env')

CARVOL_FEED = (
    'https://carvol.prom.ua/rozetka_feed.xml'
    '?rozetka_hash_tag=2251d0779efad97117ac08d7efd82c2f'
    '&product_ids=&label_ids=28618299&languages=uk%2Cru&group_ids='
)
XML_PATH   = BASE_DIR / 'data' / 'carvol_rozetka.xml'
CSV_PATH   = BASE_DIR / 'data' / 'rozetka_prices.csv'
FEED_CACHE = BASE_DIR / 'data' / 'carvol_feed.xml'
REPO_PATH  = str(BASE_DIR)

# Комісії Розетки по categoryId (ступінчасті: sell_price тир → rate)
CPA_RULES = {
    '1':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '2':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '3':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '4':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '5':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '6':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '7':  [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '8':  [(0,2999,0.13),(3000,9999,0.07),(10000,19999,0.05),(20000,9e9,0.03)],
    '9':  [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '10': [(0,2999,0.13),(3000,9999,0.07),(10000,19999,0.05),(20000,9e9,0.03)],
    '12': [(0,2999,0.13),(3000,9999,0.07),(10000,19999,0.05),(20000,9e9,0.03)],
    '14': [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '15': [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '16': [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
}


def calc_sell_price(rrc: float, cat_id: str) -> tuple:
    """
    Gross-up: sell = ceil(rrc / (1 - rate) / 10) * 10.
    Tier-crossing: якщо breakeven виходить за межі тира — переходимо до наступного.
    Повертає (sell_price, commission_rate).
    """
    rules = sorted(CPA_RULES.get(str(cat_id), [(0, 9e9, 0.18)]), key=lambda x: x[0])
    for low, high, rate in rules:
        breakeven = math.ceil(rrc / (1 - rate) / 10) * 10
        if breakeven <= high:
            sell = max(breakeven, math.ceil(low / 10) * 10)
            return sell, rate
    _, _, rate = rules[-1]
    return math.ceil(rrc / (1 - rate) / 10) * 10, rate


def load_xml_cat_map() -> dict:
    """Повертає {article: cat_id} з carvol_rozetka.xml."""
    if not XML_PATH.exists():
        print(f'[warn] {XML_PATH} не знайдено — категорії за замовчуванням 1')
        return {}
    tree = ET.parse(XML_PATH)
    root = tree.getroot()
    shop = root.find('shop')
    if shop is None:
        shop = root
    offers_el = shop.find('offers')
    if offers_el is None:
        offers_el = root
    result = {}
    for offer in offers_el.findall('offer'):
        art_el = offer.find('article')
        cat_el = offer.find('categoryId')
        if art_el is not None and art_el.text:
            art = art_el.text.strip()
            cat = (cat_el.text or '1').strip() if cat_el is not None else '1'
            result[art] = cat
    print(f'XML cat_map: {len(result)} артикулів')
    return result


def fetch_feed() -> dict:
    """Повертає {article: rrc} з фіду (кеш або живий)."""
    if FEED_CACHE.exists():
        print(f'Читаємо кешований фід: {FEED_CACHE}')
        content = FEED_CACHE.read_bytes()
    else:
        print('Завантажуємо живий фід Carvol...')
        r = requests.get(CARVOL_FEED, timeout=120)
        content = r.content

    root = ET.fromstring(content)
    shop = root.find('shop')
    if shop is None:
        shop = root
    offers_el = shop.find('offers')
    if offers_el is None:
        offers_el = root

    feed = {}
    for offer in offers_el.findall('offer'):
        art_el   = offer.find('article')
        price_el = offer.find('price')
        if art_el is None or not art_el.text:
            continue
        art   = art_el.text.strip()
        price = float(price_el.text or 0) if price_el is not None else 0.0
        if art and price > 0:
            feed[art] = price

    print(f'Фід: {len(feed)} товарів з ціною')
    return feed


def cmd_generate():
    raw = input('РРЦ корекція % (+ або -, Enter = 0): ').strip()
    try:
        pct = float(raw) if raw else 0.0
    except ValueError:
        print(f'Некоректне значення "{raw}" → використовую 0%')
        pct = 0.0

    print(f'Корекція: {pct:+.1f}%\n')

    feed    = fetch_feed()
    cat_map = load_xml_cat_map()

    rows = []
    for article, rrc in feed.items():
        cat_id       = cat_map.get(article, '1')
        rrc_adjusted = rrc * (1 + pct / 100)
        sell_price, rate = calc_sell_price(rrc_adjusted, cat_id)
        commission   = round(sell_price * rate, 2)
        margin       = round(sell_price - commission - rrc, 2)
        rows.append({
            'article':         article,
            'rrc':             rrc,
            'rrc_adjusted':    round(rrc_adjusted, 2),
            'sell_price':      int(sell_price),
            'commission_rate': rate,
            'commission':      commission,
            'margin_vs_rrc':   margin,
        })

    rows.sort(key=lambda x: x['sell_price'], reverse=True)

    fields = ['article', 'rrc', 'rrc_adjusted', 'sell_price',
              'commission_rate', 'commission', 'margin_vs_rrc']
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f'\nЗбережено: {CSV_PATH}  ({len(rows)} рядків)')
    print(f'\n{"Артикул":<30} {"РРЦ":>8} {"Корр":>8} {"Продаж":>8} {"Ставка":>7} {"Комісія":>9} {"Маржа":>9}')
    print('─' * 86)
    for r in rows[:10]:
        sign = '+' if r['margin_vs_rrc'] >= 0 else ''
        print(f'{r["article"][:29]:<30} {r["rrc"]:>8.0f} {r["rrc_adjusted"]:>8.0f} '
              f'{r["sell_price"]:>8d} {r["commission_rate"]*100:>6.0f}%  '
              f'{r["commission"]:>9.0f} {sign}{r["margin_vs_rrc"]:>8.0f}')
    if len(rows) > 10:
        print(f'  … ще {len(rows) - 10} рядків')

    neg   = sum(1 for r in rows if r['margin_vs_rrc'] < 0)
    avg_m = sum(r['margin_vs_rrc'] for r in rows) / len(rows) if rows else 0
    print(f'\nСтатистика: всього {len(rows)}, нижче РРЦ: {neg}, середня маржа: {avg_m:+.0f} грн')
    print(f'\nВідредагуй sell_price у CSV і запусти --apply щоб оновити XML.')


def cmd_apply():
    if not CSV_PATH.exists():
        sys.exit(f'Файл не знайдено: {CSV_PATH}')
    if not XML_PATH.exists():
        sys.exit(f'XML не знайдено: {XML_PATH}')

    prices: dict[str, int] = {}
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                prices[row['article']] = int(float(row['sell_price']))
            except (KeyError, ValueError):
                pass
    print(f'CSV: {len(prices)} цін')

    tree = ET.parse(XML_PATH)
    root = tree.getroot()
    root.set('date', datetime.now().strftime('%Y-%m-%d %H:%M'))
    shop = root.find('shop')
    if shop is None:
        shop = root
    offers_el = shop.find('offers')
    if offers_el is None:
        offers_el = root

    updated, not_found, changed, examples = 0, 0, 0, []

    for offer in offers_el.findall('offer'):
        art_el = offer.find('article')
        if art_el is None or not art_el.text:
            continue
        article   = art_el.text.strip()
        new_price = prices.get(article)

        if new_price is None:
            not_found += 1
            continue

        price_el = offer.find('price')
        if price_el is None:
            continue

        old_price_str = price_el.text or '0'
        try:
            old_price = int(float(old_price_str))
        except ValueError:
            old_price = 0

        price_el.text = str(new_price)
        updated += 1
        if old_price != new_price:
            changed += 1
            if len(examples) < 12:
                examples.append((article, old_price, new_price))

    tree.write(str(XML_PATH), encoding='unicode', xml_declaration=False)
    with open(XML_PATH, 'r+', encoding='utf-8') as f:
        content = f.read()
        f.seek(0)
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + content)

    print(f'\nОновлено: {updated}, змінилось цін: {changed}, не знайдено: {not_found}')

    if examples:
        print(f'\n{"Артикул":<30} {"Стара":>8} {"Нова":>8} {"Різниця":>9}')
        print('─' * 60)
        for art, old, new in examples:
            diff = new - old
            sign = '+' if diff >= 0 else ''
            print(f'{art[:29]:<30} {old:>8d} {new:>8d} {sign}{diff:>8d}')

    # git commit + push
    ts  = datetime.now().strftime('%Y-%m-%d %H:%M')
    msg = f'prices: rozetka apply {ts}'
    print(f'\nGit: {msg}')
    for cmd in [
        ['git', 'add', 'data/carvol_rozetka.xml', 'data/rozetka_prices.csv'],
        ['git', 'commit', '-m', msg],
        ['git', 'pull', '--rebase'],
        ['git', 'push'],
    ]:
        r = subprocess.run(cmd, cwd=REPO_PATH, capture_output=True, text=True)
        if r.returncode != 0:
            if 'nothing to commit' in r.stdout + r.stderr:
                print('Git: немає змін')
                return
            print(f'Git {cmd[1]} error: {r.stderr[:200]}')
            return
    print('Git push ✅')


def main():
    parser = argparse.ArgumentParser(description='Rozetka Price Manager')
    parser.add_argument('--generate', action='store_true',
                        help='Генерувати data/rozetka_prices.csv з живого фіду')
    parser.add_argument('--apply', action='store_true',
                        help='Застосувати ціни з CSV → оновити XML + git push')
    args = parser.parse_args()

    if args.generate:
        cmd_generate()
    elif args.apply:
        cmd_apply()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()

````

### `agents/orders/rozetka_price_corrector.py` — 174 рядків

````python
"""
agents/orders/rozetka_price_corrector.py
==========================================
Читає data/margin_analysis_6k.csv і оновлює ціни на Rozetka через API.

Використання:
  python3 agents/orders/rozetka_price_corrector.py --dry-run   # показати без змін
  python3 agents/orders/rozetka_price_corrector.py             # застосувати

API:
  GET  /items/search?article={article}          → owox_id
  PUT  /items/update-price-stock/{owox_id}      → оновити ціну
"""

import os, sys, csv, time, argparse
import requests
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / '.env')

API_BASE  = 'https://api-seller.rozetka.com.ua'
TOKEN     = os.getenv('ROZETKA_API_TOKEN', '')
CSV_PATH  = BASE_DIR / 'data' / 'margin_analysis_6k.csv'
XML_PATH  = BASE_DIR / 'data' / 'carvol_rozetka.xml'

HEADERS = {
    'Authorization': f'Bearer {TOKEN}',
    'Content-Type': 'application/json',
}


def api(method, path, **kwargs):
    url = API_BASE + path
    r = getattr(requests, method)(url, headers=HEADERS, verify=False, timeout=15, **kwargs)
    return r.status_code, r.json() if r.content else {}


def get_owox_id(article: str) -> str | None:
    """Знаходить owox_id товару за артикулом."""
    status, data = api('get', f'/items/search?article={requests.utils.quote(article)}')
    if status != 200:
        return None
    items = data.get('content', {}).get('items', [])
    if not items:
        return None
    return str(items[0].get('id') or items[0].get('owox_id') or '')


def update_price(owox_id: str, price: float) -> bool:
    """Оновлює ціну товару."""
    status, data = api('put', f'/items/update-price-stock/{owox_id}',
                       json={'price': price})
    return status == 200 and data.get('success', False)


def load_current_prices() -> dict:
    """Читає поточні ціни з Rozetka XML {article: price}."""
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(XML_PATH)
        root = tree.getroot()
        shop = root.find('shop')
        offers_el = (shop.find('offers') if shop is not None else None) or root.find('offers') or root
        prices = {}
        for offer in offers_el.findall('offer'):
            art = None
            for tag in ('vendorCode', 'article'):
                el = offer.find(tag)
                if el is not None and el.text:
                    art = el.text.strip(); break
            pe = offer.find('price')
            if art and pe is not None and pe.text:
                try: prices[art] = float(pe.text.strip())
                except: pass
        return prices
    except Exception as e:
        print(f'[warn] Не вдалось прочитати XML: {e}')
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Показати зміни без застосування')
    parser.add_argument('--limit', type=int, default=0, help='Ліміт оновлень (0=всі)')
    parser.add_argument('--min-diff', type=float, default=10, help='Мін. різниця цін для оновлення (грн)')
    args = parser.parse_args()

    if not TOKEN:
        sys.exit('ROZETKA_API_TOKEN не встановлено в .env')

    if not CSV_PATH.exists():
        sys.exit(f'Файл не знайдено: {CSV_PATH}')

    # Поточні ціни з XML (швидка перевірка без API)
    current_prices = load_current_prices()
    print(f'Поточні ціни з XML: {len(current_prices)} артикулів')

    # Читаємо CSV
    rows = []
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            rows.append(row)
    print(f'CSV: {len(rows)} рядків')

    # Знаходимо товари де ціна відрізняється
    to_update = []
    for row in rows:
        article = row['article']
        csv_price = float(row['sell_price'])
        xml_price = current_prices.get(article)
        if xml_price is None:
            continue
        if abs(csv_price - xml_price) > args.min_diff:
            to_update.append({
                'article': article,
                'csv_price': csv_price,
                'xml_price': xml_price,
                'diff': csv_price - xml_price,
                'margin': float(row['margin_uah']),
            })

    to_update.sort(key=lambda x: abs(x['diff']), reverse=True)
    if args.limit:
        to_update = to_update[:args.limit]

    print(f'\nПотребують оновлення: {len(to_update)} товарів')
    print(f'{"Артикул":<28} {"XML_ціна":>10} {"CSV_ціна":>10} {"Різниця":>10} {"Маржа":>10}')
    print('-' * 72)
    for item in to_update[:20]:
        print(f'{item["article"][:27]:<28} {item["xml_price"]:>10.0f} {item["csv_price"]:>10.0f} '
              f'{item["diff"]:>+10.0f} {item["margin"]:>+10.0f}')
    if len(to_update) > 20:
        print(f'  ... та ще {len(to_update) - 20}')

    if args.dry_run:
        print('\n[dry-run] Зміни не застосовано.')
        return

    if not to_update:
        print('\nНемає товарів для оновлення.')
        return

    print(f'\nОновлюємо {len(to_update)} цін через Rozetka API...')
    ok, fail, skip = 0, 0, 0

    for i, item in enumerate(to_update, 1):
        article = item['article']
        new_price = item['csv_price']

        owox_id = get_owox_id(article)
        if not owox_id:
            print(f'  [{i}/{len(to_update)}] {article}: owox_id не знайдено — пропуск')
            skip += 1
            time.sleep(0.3)
            continue

        success = update_price(owox_id, new_price)
        status = '✅' if success else '❌'
        print(f'  [{i}/{len(to_update)}] {article} owox={owox_id}: {item["xml_price"]:.0f}→{new_price:.0f} {status}')
        if success:
            ok += 1
        else:
            fail += 1
        time.sleep(0.5)  # rate limit

    print(f'\nРезультат: OK={ok} FAIL={fail} SKIP={skip}')


if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings()
    main()

````

### `agents/orders/katran_xml_generator.py` — 293 рядків

````python
import os, sys, re, math, requests, zipfile, io
from datetime import datetime
from xml.etree import ElementTree as ET
from dotenv import load_dotenv
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

SHOP_NAME = "HYPER_STORE"
SHOP_URL = "https://seller.rozetka.com.ua/"
DEFAULT_COMMISSION = 7.0
DEFAULT_RZ_ID = "25636737"  # Ручний інструмент
DEFAULT_CAT_NAME = "Інструменти"

OUTPUT_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../data/katran_rozetka.xml")
)


def get_katran_feed() -> ET.Element:
    url = os.getenv("KATRAN_FEED_URL_STOCK")
    if not url:
        raise ValueError("KATRAN_FEED_URL_STOCK не встановлено в .env")

    logger.info(f"[Katran] Завантажую фід: {url}")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not xml_names:
            raise ValueError("XML не знайдено в ZIP архіві")
        xml_name = xml_names[0]
        logger.info(f"[Katran] Файл в архіві: {xml_name}")
        with zf.open(xml_name) as f:
            return ET.parse(f).getroot()


def get_category_map() -> dict:
    """Повертає {katran_category_id: {rz_id, name, commission}}. При помилці — {}."""
    try:
        from shared.utils.db import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, rozetka_category, rozetka_rz_id, commission_pct
            FROM katran_categories
            WHERE rozetka_rz_id IS NOT NULL
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = {}
        for r in rows:
            result[str(r["id"])] = {
                "rz_id": str(r["rozetka_rz_id"]),
                "name": r["rozetka_category"] or DEFAULT_CAT_NAME,
                "commission": float(r["commission_pct"]),
            }
        logger.info(f"[Katran] Категорій з БД: {len(result)}")
        return result
    except Exception as e:
        logger.warning(f"[Katran] БД недоступна, використовую defaults: {e}")
        return {}


def calc_price(price_rrc: float, commission_pct: float) -> int:
    """ceil(price_rrc * (1 + commission_pct/100) / 10) * 10"""
    if price_rrc <= 0:
        return 0
    raw = price_rrc * (1 + commission_pct / 100)
    return int(math.ceil(raw / 10) * 10)


def is_in_stock(stock_str: str) -> bool:
    if not stock_str:
        return False
    s = stock_str.lower().strip()
    # "есть" / "є" — в наявності; "в резервах" — не включаємо
    return s.startswith("е") or s.startswith("є")


def parse_float(text: str) -> float:
    try:
        return float((text or "0").replace(",", ".").strip())
    except ValueError:
        return 0.0


def clean_text(text: str) -> str:
    return (text or "").strip()


def fix_name(name: str, artikul: str) -> str:
    if not name:
        return artikul
    name = re.sub(r'^[!@#$%^&*()\[\]{}\-_=+|\\/<>\'"`~]+\s*', '', name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return artikul
    return name[:255]


def xml_escape(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def generate_xml(output_file: str = None) -> tuple:
    if not output_file:
        output_file = OUTPUT_FILE

    root = get_katran_feed()
    cat_map = get_category_map()

    # Структура фіду: <price><products><product>
    products_el = root.find("products")
    if products_el is None:
        products_el = root
    all_products = products_el.findall("product")
    logger.info(f"[Katran] Товарів у фіді: {len(all_products)}")

    categories_used = {}
    offers_data = []
    seen_artikuls = set()
    skipped_stock = 0
    skipped_price = 0
    skipped_name = 0
    skipped_dup = 0

    for p in all_products:
        code = clean_text(p.findtext("code") or "")
        artikul = clean_text(p.findtext("artikul") or code)
        name = fix_name(p.findtext("name") or "", artikul)
        description = clean_text(p.findtext("description") or "")
        category_id = clean_text(p.findtext("categoryId") or "")
        vendor = clean_text(p.findtext("vendor") or "")
        if not vendor or vendor.lower() in ("no name", "noname", "no-name", "unknown"):
            vendor = "Без бренду"
        warranty = clean_text(p.findtext("warranty") or "")
        stock_str = clean_text(p.findtext("stock") or "")
        stock_qty = max(int(parse_float(p.findtext("stock_quantity") or "0")), 0)
        price_rrc = parse_float(p.findtext("price_rrc") or "0")

        if not name or len(name) < 3:
            skipped_name += 1
            continue

        if not is_in_stock(stock_str):
            skipped_stock += 1
            continue

        if artikul in seen_artikuls:
            skipped_dup += 1
            continue
        seen_artikuls.add(artikul)

        cat_info = cat_map.get(category_id, {})
        rz_id = cat_info.get("rz_id", DEFAULT_RZ_ID)
        cat_name = cat_info.get("name", DEFAULT_CAT_NAME)
        commission = cat_info.get("commission", DEFAULT_COMMISSION)

        price = calc_price(price_rrc, commission)
        if price <= 0:
            skipped_price += 1
            continue

        # Фото
        pictures = []
        images_el = p.find("images")
        if images_el is not None:
            for img in images_el.findall("image"):
                url = (img.text or img.get("url") or "").strip()
                if url.startswith("http") and len(url) < 500:
                    pictures.append(url)

        if rz_id not in categories_used:
            categories_used[rz_id] = cat_name

        offers_data.append({
            "artikul": artikul,
            "name": name,
            "description": description,
            "rz_id": rz_id,
            "vendor": vendor,
            "warranty": warranty,
            "stock_qty": max(stock_qty, 1),
            "price": price,
            "pictures": pictures,
        })

    logger.info(f"[Katran] Готово до XML: {len(offers_data)} товарів")
    logger.info(
        f"[Katran] Пропущено — без наявності: {skipped_stock}, "
        f"без ціни: {skipped_price}, без назви: {skipped_name}, дублікатів: {skipped_dup}"
    )

    # Збираємо XML
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{datetime.now().strftime("%Y-%m-%d %H:%M")}">',
        "  <shop>",
        f"    <name>{SHOP_NAME}</name>",
        "    <company>FOP Oliinyk Serhii</company>",
        f"    <url>{SHOP_URL}</url>",
        "    <currencies>",
        '      <currency id="UAH" rate="1"/>',
        "    </currencies>",
        "    <categories>",
    ]

    for rz_id, cat_name in categories_used.items():
        lines.append(f'      <category id="{rz_id}">{cat_name}</category>')

    lines.extend(["    </categories>", "    <offers>"])

    for o in offers_data:
        offer_id = xml_escape(o["artikul"])
        desc_escaped = xml_escape(o["description"])

        offer = [f'      <offer id="{offer_id}" available="true">']
        offer.append(f'        <price>{o["price"]}</price>')
        offer.append("        <currencyId>UAH</currencyId>")
        offer.append(f'        <categoryId>{o["rz_id"]}</categoryId>')

        for pic_url in o["pictures"][:10]:
            offer.append(f"        <picture>{pic_url}</picture>")
        if not o["pictures"]:
            offer.append(f"        <!-- no pictures for {offer_id} -->")

        offer.append(f'        <vendor>{xml_escape(o["vendor"])}</vendor>')
        offer.append(f'        <article>{xml_escape(o["artikul"])}</article>')
        offer.append(f'        <stock_quantity>{o["stock_qty"]}</stock_quantity>')
        offer.append(f'        <name_ua>{xml_escape(o["name"])}</name_ua>')
        offer.append(
            f'        <description_ua><![CDATA[<p>{desc_escaped}</p>]]></description_ua>'
        )

        offer.append(f'        <param name="Бренд">{xml_escape(o["vendor"])}</param>')
        if o["warranty"] and o["warranty"] != "0":
            offer.append(f'        <param name="Гарантія">{xml_escape(o["warranty"])} міс</param>')
        offer.append(f'        <param name="Артикул">{xml_escape(o["artikul"])}</param>')

        offer.append("      </offer>")
        lines.extend(offer)

    lines.extend(["    </offers>", "  </shop>", "</yml_catalog>"])

    xml_content = "\n".join(lines)
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(xml_content)

    logger.success(f"[Katran] XML збережено: {output_file}")
    stats = {
        "total": len(all_products),
        "in_stock": len(offers_data),
        "skipped_stock": skipped_stock,
        "skipped_price": skipped_price,
        "skipped_name": skipped_name,
        "skipped_dup": skipped_dup,
        "categories": len(categories_used),
    }
    return output_file, len(offers_data), stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Генератор XML Розетки з фіду Катрана")
    parser.add_argument("--output", type=str, default=None, help="Вихідний XML файл")
    args = parser.parse_args()

    try:
        file, count, stats = generate_xml(output_file=args.output)
        print(f"\n✅ XML Катран готовий!")
        print(f"   Файл    : {file}")
        print(f"   Офферів : {count}")
        print(f"   ─────────────────────────────")
        print(f"   Всього в фіді     : {stats['total']}")
        print(f"   В наявності       : {stats['in_stock']}")
        print(f"   Немає в наявності : {stats['skipped_stock']}")
        print(f"   Без ціни          : {stats['skipped_price']}")
        print(f"   Без назви         : {stats['skipped_name']}")
        print(f"   Дублікати артикул : {stats['skipped_dup']}")
        print(f"   Категорій         : {stats['categories']}")
    except Exception as e:
        logger.error(f"[Katran] Критична помилка: {e}")
        sys.exit(1)

````

### `agents/orders/epicentr_order_agent.py` — 487 рядків

````python
"""
Агент обробки замовлень Єпіцентру — дропшипінг TOPTUL
======================================================
Цикл:
1. Отримати нові замовлення з Єпіцентр OMS API
2. Перевірити наявність у фіді TOPTUL (реальний час)
3. Підтвердити замовлення на Єпіцентрі
4. Сформувати Excel бланк → відправити на opt@grandinstrument.ua
5. Сповістити в Telegram
"""
import os, sys, json, time, requests, smtplib, asyncio
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from loguru import logger
import xlsxwriter
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# === КОНСТАНТИ ===
EPICENTR_TOKEN  = os.getenv('EPICENTR_TOKEN')
EPICENTR_BASE   = 'https://merchant-api.epicentrm.com.ua'
EPICENTR_HEADERS = {
    'Authorization': f'Bearer {EPICENTR_TOKEN}',
    'Content-Type':  'application/json',
}
TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)
SUPPLIER_EMAIL = 'opt@grandinstrument.ua'
SUPPLIER_CODE  = '000160594'
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASS = os.getenv('SMTP_PASS')
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID   = os.getenv('TG_CHAT_ID')
POLL_INTERVAL = 300  # 5 хвилин
MARKETPLACE   = 'Єпіцентр'

# === УТИЛІТИ ===

def tg(msg: str):
    """Відправити повідомлення в Telegram."""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.warning(f'TG помилка: {e}')


def parse_price(val) -> float:
    """Парсить ціну з будь-якого формату."""
    if val is None:
        return 0.0
    import re
    s = str(val).replace(' грн', '').replace('грн', '')
    s = s.replace('\xa0', '').replace('\u00a0', '')
    s = re.sub(r'(\d)\s+(\d)', r'\1\2', s)
    s = s.replace(',', '.').strip()
    match = re.search(r'[\d]+(?:\.[\d]+)?', s)
    return float(match.group()) if match else 0.0


# === ФІД TOPTUL ===

_feed_cache = {'data': {}, 'updated': None}

def get_feed_data(force=False) -> dict:
    """Повертає словник {sku: {available, price, name}} з фіду TOPTUL."""
    now = datetime.now()
    if (not force and _feed_cache['updated'] and
            (now - _feed_cache['updated']).seconds < 3600):
        return _feed_cache['data']
    try:
        r = requests.get(TOPTUL_FEED, timeout=120)
        root = ET.fromstring(r.content)
        offers = root.find('shop').find('offers').findall('offer')
        data = {}
        for offer in offers:
            sku_el = offer.find('vendorCode')
            if sku_el is None:
                continue
            sku = (sku_el.text or '').strip().upper()
            price_el = offer.find('price')
            name_el  = offer.find('name_ua') or offer.find('name')
            data[sku] = {
                'available': offer.get('available','false').lower() == 'true',
                'price':     float(price_el.text or 0) if price_el is not None else 0,
                'name':      (name_el.text or '') if name_el is not None else '',
            }
        _feed_cache['data']    = data
        _feed_cache['updated'] = now
        logger.info(f'Фід TOPTUL: {len(data)} SKU')
        return data
    except Exception as e:
        logger.error(f'Помилка фіду: {e}')
        return _feed_cache['data']


# === ЄПІЦЕНТР OMS API ===

def get_new_orders() -> list:
    """Отримати нові замовлення (статус new)."""
    try:
        r = requests.get(
            f'{EPICENTR_BASE}/v3/oms/orders',
            headers=EPICENTR_HEADERS,
            params={'statusCode': 'new', 'limit': 50},
            timeout=30
        )
        if r.status_code != 200:
            logger.error(f'OMS помилка {r.status_code}: {r.text[:200]}')
            return []
        return r.json().get('items', [])
    except Exception as e:
        logger.error(f'get_new_orders: {e}')
        return []


def get_order_details(order_id: str) -> dict:
    """Отримати повні деталі замовлення."""
    try:
        r = requests.get(
            f'{EPICENTR_BASE}/v5/oms/orders/{order_id}',
            headers=EPICENTR_HEADERS,
            timeout=30
        )
        return r.json() if r.status_code == 200 else {}
    except Exception as e:
        logger.error(f'get_order_details: {e}')
        return {}


def accept_order(order_id: str) -> bool:
    """Підтвердити замовлення (new → confirmed_by_merchant)."""
    try:
        # 1. Перевіряємо дозволені статуси
        r = requests.get(
            f'{EPICENTR_BASE}/v2/oms/orders/{order_id}/allowed-statuses',
            headers=EPICENTR_HEADERS, timeout=15
        )
        if r.status_code == 200:
            allowed = [s.get('code') for s in r.json().get('items', [])]
            if 'confirmed_by_merchant' not in allowed:
                logger.warning(f'Статус confirmed_by_merchant недоступний для {order_id}')
                return False
        # 2. Змінюємо статус
        r2 = requests.post(
            f'{EPICENTR_BASE}/v2/oms/orders/{order_id}/change-status/to/confirmed_by_merchant',
            headers=EPICENTR_HEADERS,
            json={'comment': 'Прийнято автоматично'},
            timeout=15
        )
        return r2.status_code in (200, 202, 204)
    except Exception as e:
        logger.error(f'accept_order: {e}')
        return False


def cancel_order(order_id: str, reason: str = 'customer_not_timely_confirmation_of_the_availability_of_goods') -> bool:
    """Скасувати замовлення (товар відсутній)."""
    try:
        r = requests.post(
            f'{EPICENTR_BASE}/v2/oms/orders/{order_id}/change-status/to/canceled_by_merchant',
            headers=EPICENTR_HEADERS,
            json={'reason_code': reason, 'comment': 'Товар відсутній у постачальника'},
            timeout=15
        )
        return r.status_code in (200, 202, 204)
    except Exception as e:
        logger.error(f'cancel_order: {e}')
        return False


def save_to_db(order: dict, status: str):
    """Зберегти замовлення в БД."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS epicentr_processed_orders (
                order_id    VARCHAR(100) PRIMARY KEY,
                ext_id      VARCHAR(100),
                status      VARCHAR(50),
                total_price NUMERIC(12,2),
                items       JSONB,
                processed_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        items = json.dumps(order.get('items', []), ensure_ascii=False)
        total = sum(i.get('subtotal', 0) for i in order.get('items', []))
        cur.execute('''
            INSERT INTO epicentr_processed_orders
                (order_id, ext_id, status, total_price, items)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (order_id) DO UPDATE
            SET status=EXCLUDED.status, processed_at=NOW()
        ''', (order.get('id'), order.get('externalId'), status, total, items))
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        logger.error(f'save_to_db: {e}')


def is_already_processed(order_id: str) -> bool:
    """Перевірити чи замовлення вже оброблялось."""
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('''
            SELECT 1 FROM epicentr_processed_orders
            WHERE order_id = %s
        ''', (order_id,))
        exists = cur.fetchone() is not None
        cur.close(); conn.close()
        return exists
    except:
        return False


# === EXCEL БЛАНК ===

def create_order_excel(order: dict, items_info: list) -> str:
    """Формат бланку Гранд Інструмент (аналог Prom)."""
    order_id = order.get('id', 'unknown')[:8]
    filename = f'/tmp/epicentr_order_{order_id}_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'

    wb = xlsxwriter.Workbook(filename)
    ws = wb.add_worksheet('Замовлення')

    bold       = wb.add_format({'bold': True, 'font_size': 11})
    header_fmt = wb.add_format({'bold': True, 'bg_color': '#1F4E79',
                                'font_color': 'white', 'border': 1, 'align': 'center'})
    cell_fmt   = wb.add_format({'border': 1})
    sku_fmt    = wb.add_format({'border': 1, 'bold': True})
    red_bold   = wb.add_format({'bold': True, 'font_color': 'red'})
    wrap_fmt   = wb.add_format({'text_wrap': True})

    ws.set_column('A:A', 5)
    ws.set_column('B:B', 22)
    ws.set_column('C:C', 55)
    ws.set_column('D:D', 14)

    # Дані замовлення
    addr    = order.get('address') or {}
    ship    = addr.get('shipment') or {}
    customer = f"{addr.get('lastName','')} {addr.get('firstName','')}".strip()
    phone    = addr.get('phone', '')
    city_id  = ship.get('settlementId', '')
    office_n = ship.get('number', '')
    delivery_str = f'Нова Пошта {office_n}'.strip() if office_n else 'Нова Пошта'

    total = sum(i.get('subtotal', 0) for i in order.get('items', []))

    # Шапка
    ws.write('A1', 'Перевозчик', bold)
    ws.write('C1', 'Новая Почта')
    ws.write('A2', 'Оплата', bold)
    ws.write('C2', f'Наложенным платежом {total:.0f} грн')
    ws.write('A3', 'Комментарий', bold)
    ws.write('C3', f'{customer}  {phone}\n{delivery_str}', wrap_fmt)
    ws.set_row(2, 35)
    ws.write('A4', f'Замовлення {MARKETPLACE} #{order.get("externalId") or order_id}')
    ws.write('C4', f'Дата: {datetime.now().strftime("%d.%m.%Y %H:%M")}')
    ws.write('A5', f'Код клієнта: {SUPPLIER_CODE}', red_bold)

    # Заголовки
    row = 6
    for col, h in enumerate(['№', 'Артикул', 'Наименование', 'Количество']):
        ws.write(row, col, h, header_fmt)
    row += 1

    # Товари
    for idx, item in enumerate(items_info, 1):
        ws.write(row, 0, idx, cell_fmt)
        ws.write(row, 1, item.get('sku', ''), sku_fmt)
        ws.write(row, 2, item.get('title', '')[:80], cell_fmt)
        ws.write(row, 3, item.get('quantity', 1), cell_fmt)
        row += 1

    wb.close()
    logger.info(f'Excel: {filename}')
    return filename


def send_to_supplier(order: dict, excel_path: str, items_info: list):
    """Відправити бланк замовлення на пошту постачальника."""
    addr     = order.get('address') or {}
    customer = f"{addr.get('lastName','')} {addr.get('firstName','')}".strip()
    phone    = addr.get('phone', '')
    ship     = addr.get('shipment') or {}
    office_n = ship.get('number', '')
    delivery_str = f'Нова Пошта відд.{office_n}' if office_n else 'Нова Пошта'
    total    = sum(i.get('subtotal', 0) for i in order.get('items', []))
    order_id = order.get('externalId') or order.get('id', '')[:8]

    items_text = '\n'.join(
        f"{i}. {item.get('sku','')} | {item.get('title','')[:50]} | {item.get('quantity',1)} шт."
        for i, item in enumerate(items_info, 1)
    )

    body = f"""Добрый день!

Заказ #{order_id} от {datetime.now().strftime('%d.%m.%Y')}
Код клиента: {SUPPLIER_CODE}

Товары:
{items_text}

Получатель: {customer}
Телефон: {phone}
Доставка: {delivery_str}
Оплата: Наложенным платежом {total:.0f} грн

Детали в приложении (Excel).

С уважением,
klatch1.shop
"""
    msg = MIMEMultipart()
    msg['From']    = SMTP_USER
    msg['To']      = SUPPLIER_EMAIL
    msg['Subject'] = f'Заказ #{order_id} от {datetime.now().strftime("%d.%m.%Y")} ({MARKETPLACE})'
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    with open(excel_path, 'rb') as f:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition',
                        f'attachment; filename="{os.path.basename(excel_path)}"')
        msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.success(f'Email відправлено: {order_id}')
        return True
    except Exception as e:
        logger.error(f'Email помилка: {e}')
        return False


# === ОБРОБКА ЗАМОВЛЕННЯ ===

def process_order(order: dict, feed: dict):
    """Обробити одне замовлення."""
    order_id  = order.get('id', '')
    ext_id    = order.get('externalId') or order_id[:8]

    if is_already_processed(order_id):
        return

    logger.info(f'Обробляємо {MARKETPLACE} замовлення #{ext_id}')

    # Деталі замовлення
    details = get_order_details(order_id)
    if not details:
        logger.error(f'Не вдалось отримати деталі {order_id}')
        return

    items = details.get('items', [])
    if not items:
        logger.warning(f'Замовлення {ext_id} — немає товарів')
        return

    # Перевіряємо наявність кожного товару
    items_info   = []
    all_available = True

    for item in items:
        # SKU береться з productExternalId або з маппінгу
        product_ext_id = item.get('productExternalId') or item.get('sku', '')
        sku = product_ext_id.upper()

        # Шукаємо наш SKU через epicentr_sku_mapping
        our_sku = sku
        try:
            conn = get_connection()
            cur  = conn.cursor()
            cur.execute(
                'SELECT our_sku FROM epicentr_sku_mapping WHERE epicentr_article = %s',
                (product_ext_id,)
            )
            row = cur.fetchone()
            if row:
                our_sku = row['our_sku'].upper()
            cur.close(); conn.close()
        except:
            pass

        feed_item = feed.get(our_sku, {})
        available = feed_item.get('available', False)

        if not available:
            all_available = False
            logger.warning(f'  {our_sku} — відсутній у фіді')

        items_info.append({
            'sku':       our_sku,
            'title':     item.get('title', ''),
            'quantity':  item.get('quantity', 1),
            'price':     item.get('price', 0),
            'subtotal':  item.get('subtotal', 0),
            'available': available,
        })

    total = sum(i.get('subtotal', 0) for i in items)
    addr  = details.get('address') or {}
    customer = f"{addr.get('lastName','')} {addr.get('firstName','')}".strip()
    phone    = addr.get('phone', '')

    if not all_available:
        # Скасовуємо
        unavailable = [i['sku'] for i in items_info if not i['available']]
        cancel_order(order_id)
        save_to_db(details, 'cancelled_no_stock')
        tg(f"""❌ <b>{MARKETPLACE} замовлення #{ext_id} — товар відсутній!</b>
Клієнт: {customer} {phone}
Відсутні: {', '.join(unavailable)}
Замовлення скасовано автоматично.""")
        logger.warning(f'Замовлення #{ext_id} скасовано — немає товару')
        return

    # Підтверджуємо
    if accept_order(order_id):
        logger.success(f'Замовлення #{ext_id} підтверджено на {MARKETPLACE}')
    else:
        logger.error(f'Не вдалось підтвердити #{ext_id}')
        return

    # Формуємо Excel і відправляємо
    excel = create_order_excel(details, items_info)
    email_sent = send_to_supplier(details, excel, items_info)

    save_to_db(details, 'accepted')

    tg(f"""📧 <b>{MARKETPLACE} замовлення #{ext_id} відправлено постачальнику</b>
Клієнт: {customer} {phone}
Товарів: {len(items_info)}
💰 Сума: {total:.0f} грн
📧 Email: {'✅' if email_sent else '❌'}""")


# === ГОЛОВНИЙ ЦИКЛ ===

def main():
    logger.add('/tmp/epicentr_order_agent.log', rotation='10 MB', level='INFO')
    logger.info(f'{MARKETPLACE} Order Agent запущено')
    tg(f'🚀 <b>{MARKETPLACE} Order Agent запущено</b>')

    while True:
        try:
            logger.info('Перевіряємо нові замовлення...')
            feed   = get_feed_data()
            orders = get_new_orders()

            if orders:
                logger.info(f'Знайдено {len(orders)} нових замовлень')
                for order in orders:
                    process_order(order, feed)
            else:
                logger.debug('Нових замовлень немає')

        except Exception as e:
            logger.error(f'Помилка циклу: {e}')
            tg(f'⚠️ <b>{MARKETPLACE} Order Agent помилка:</b> {e}')

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()

````

### `tools/prom_xml_generator.py` — 293 рядків

````python
#!/usr/bin/env python3
"""
tools/prom_xml_generator.py — універсальний генератор Prom XML для авторозбірки.

Запуск:
  python3 tools/prom_xml_generator.py \
    --file /home/tekken/Downloads/catalog.xlsx \
    --category "Шланг системы охлаждения" \
    --portal-cat-id 13100650 \
    --name-ua "Шланг системи охолодження" \
    --out exports/prom_shlang_ohlagennya.xml
"""

import argparse
import os
import sys
from html import escape
from pathlib import Path

from openpyxl import load_workbook

# ── індекси колонок (0-based) ─────────────────────────────────────────────────
COL_ID         = 0
COL_PHOTO      = 1
COL_PART       = 2
COL_BRAND      = 3   # Марка авто
COL_MODEL      = 4   # Модель авто
COL_BODY       = 5   # Кузов
COL_ENGINE     = 6   # Двигатель
COL_YEAR       = 7   # Год выпуска
COL_FRONT_REAR = 8   # Передний/Задний
COL_LEFT_RIGHT = 9   # Левый/Правый
COL_PRICE      = 11  # Цена
COL_COLOR      = 13  # Цвет
COL_COMMENT    = 14  # Комментарий
COL_VENDOR     = 15  # Производитель (виробник деталі)
COL_PART_NUM   = 16  # Номер производителя
COL_CROSS      = 17  # Кросс-номера
COL_AVAIL      = 21  # Украина (свободно)

# ── виправлення брендів ───────────────────────────────────────────────────────
BRAND_FIX = {
    "aud":       "Audi",
    "volkswgen": "Volkswagen",
    "vag":       "Volkswagen",
    "china":     "Без бренда",
}


def fix_brand(val: str) -> str:
    if not val:
        return val
    fixed = BRAND_FIX.get(val.strip().lower())
    return fixed if fixed else val.strip()


def cell(row: tuple, idx: int, default: str = "") -> str:
    if idx >= len(row) or row[idx] is None:
        return default
    return str(row[idx]).strip()


def build_name(name_ua: str, brand: str, model: str, year: str,
               left_right: str, part_num: str = "", max_len: int = 110) -> str:
    parts = [p for p in [name_ua, brand, model, year, left_right] if p]
    name = " ".join(parts)
    if part_num:
        name = f"{name} {part_num}"
    return name[:max_len]


def build_description(row: tuple) -> str:
    fields = [
        ("Марка",            fix_brand(cell(row, COL_BRAND))),
        ("Модель",           cell(row, COL_MODEL)),
        ("Рік випуску",      cell(row, COL_YEAR)),
        ("Двигун",           cell(row, COL_ENGINE)),
        ("Кузов",            cell(row, COL_BODY)),
        ("Передній/Задній",  cell(row, COL_FRONT_REAR)),
        ("Лівий/Правий",     cell(row, COL_LEFT_RIGHT)),
        ("Колір",            cell(row, COL_COLOR)),
        ("Виробник",         cell(row, COL_VENDOR)),
        ("Номер виробника",  cell(row, COL_PART_NUM)),
        ("Кросс-номери",     cell(row, COL_CROSS)),
        ("Коментар",         cell(row, COL_COMMENT)),
    ]
    parts = [f"{label}: {val}" for label, val in fields if val]
    return ". ".join(parts) + ". Б/В запчастина зі розбірки."


def x(val: str) -> str:
    return escape(val, quote=False)


def generate_xml(rows: list, category_name: str, cat_id_local: int,
                 portal_cat_id: int, name_ua: str, no_filter: bool = False) -> tuple[str, dict]:

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<yml_catalog>',
        '  <shop>',
        '    <categories>',
        f'      <category id="{cat_id_local}">{x(category_name)}</category>',
        '    </categories>',
        '    <offers>',
    ]

    is_door = "двер" in name_ua.lower()

    stats = {
        "total_in":    0,
        "skip_photo":  0,
        "skip_avail":  0,
        "skip_filter": 0,
        "generated":   0,
    }

    for row in rows:
        stats["total_in"] += 1

        # фото
        photo_raw = cell(row, COL_PHOTO)
        photos = [p.strip() for p in photo_raw.split(",") if p.strip()]
        if not photos:
            stats["skip_photo"] += 1
            continue

        # наявність
        try:
            avail = int(float(row[COL_AVAIL] or 0)) if COL_AVAIL < len(row) else 0
        except (ValueError, TypeError):
            avail = 0
        if avail == 0:
            stats["skip_avail"] += 1
            continue

        # поля
        offer_id   = cell(row, COL_ID)
        brand      = fix_brand(cell(row, COL_BRAND))
        model      = cell(row, COL_MODEL)
        year       = cell(row, COL_YEAR)
        engine     = cell(row, COL_ENGINE)
        body       = cell(row, COL_BODY)
        front_rear = cell(row, COL_FRONT_REAR)
        left_right = cell(row, COL_LEFT_RIGHT)
        vendor     = cell(row, COL_VENDOR)
        part_num   = cell(row, COL_PART_NUM)
        cross      = cell(row, COL_CROSS)

        try:
            price = int(float(row[COL_PRICE] or 0)) if COL_PRICE < len(row) else 0
        except (ValueError, TypeError):
            price = 0

        oem = cell(row, COL_PART_NUM)
        if not no_filter and (not oem or price <= 1):
            stats["skip_filter"] += 1
            continue

        name = build_name(name_ua, brand, model, year, left_right, part_num)
        desc = build_description(row)

        lines.append(f'      <offer id="{x(offer_id)}" available="true" type="vendor.model">')
        lines.append(f'        <article>{x(str(offer_id))}</article>')
        lines.append(f'        <name>{x(name)}</name>')
        lines.append(f'        <name_ua>{x(name)}</name_ua>')
        photos = photos[:10]
        for photo in photos:
            lines.append(f'        <picture>{x(photo)}</picture>')
        lines.append(f'        <price>{price}</price>')
        lines.append(f'        <currencyId>USD</currencyId>')
        lines.append(f'        <categoryId>{cat_id_local}</categoryId>')
        lines.append(f'        <portal_category_id>{portal_cat_id}</portal_category_id>')
        if vendor:
            lines.append(f'        <vendor>{x(vendor)}</vendor>')
        model_val = part_num if part_num else model
        if model_val:
            lines.append(f'        <model>{x(model_val)}</model>')
        if part_num:
            lines.append(f'        <vendorCode>{x(part_num)}</vendorCode>')
        lines.append(f'        <description>{x(desc)}</description>')
        lines.append(f'        <description_ua>{x(desc)}</description_ua>')
        lines.append(f'        <selling_type>retail</selling_type>')
        lines.append(f'        <condition>used</condition>')

        # params
        if engine:
            lines.append(f'        <param name="Двигун">{x(engine)}</param>')
        if body:
            lines.append(f'        <param name="Кузов">{x(body)}</param>')
        if front_rear:
            lines.append(f'        <param name="Передній/Задній">{x(front_rear)}</param>')
        if left_right:
            lines.append(f'        <param name="Лівий/Правий">{x(left_right)}</param>')
        if cross:
            lines.append(f'        <param name="Кросс-номери">{x(cross)}</param>')
        if part_num:
            lines.append(f'        <param name="Код запчастини">{x(part_num)}</param>')
        if brand:
            lines.append(f'        <param name="Сумісність з маркою">{x(brand)}</param>')
        if model:
            lines.append(f'        <param name="Сумісність з моделлю">{x(model)}</param>')
        if year:
            lines.append(f'        <param name="Рік випуску автомобіля">{x(year)}</param>')
        lines.append(f'        <param name="Стан">Б/в</param>')

        if is_door:
            front_back = "Передня" if "Передн" in front_rear else "Задня"
            if "Лев" in left_right:
                side = "ліва"
            elif "Прав" in left_right:
                side = "права"
            else:
                side = ""
            location = f"{front_back} {side}".strip() if side else front_back
            lines.append(f'        <param name="Місце встановлення">{x(location)}</param>')
            lines.append(f'        <param name="Фарбування">Потрібно</param>')
            color = cell(row, COL_COLOR)
            if color:
                lines.append(f'        <param name="Колір">{x(color)}</param>')

        lines.append(f'      </offer>')

        stats["generated"] += 1

    lines += ['    </offers>', '  </shop>', '</yml_catalog>']
    return "\n".join(lines), stats


def main():
    parser = argparse.ArgumentParser(description="Prom XML generator для авторозбірки")
    parser.add_argument("--file",          required=True, help="Вхідний XLSX файл")
    parser.add_argument("--category",      required=True, help="Запчасть (рос.) для фільтру col[2]")
    parser.add_argument("--portal-cat-id", required=True, type=int, dest="portal_cat_id",
                        help="ID категорії Prom.ua (portal_category_id)")
    parser.add_argument("--name-ua",       required=True, dest="name_ua",
                        help="Назва категорії укр. (для заголовку товару)")
    parser.add_argument("--out",           required=True, help="Вихідний XML файл")
    parser.add_argument("--no-filter",     action="store_true", dest="no_filter", help="Без фільтру OEM/ціни")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        sys.exit(f"Файл не знайдено: {args.file}")

    print(f"Читаємо: {args.file}")
    wb = load_workbook(args.file, read_only=True, data_only=True)
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    print(f"Всього рядків у файлі: {len(all_rows) - 1}")

    cat_lower = args.category.strip().lower()
    filtered = [
        r for r in all_rows[1:]
        if r[COL_PART] is not None and str(r[COL_PART]).strip().lower() == cat_lower
    ]
    print(f"Знайдено '{args.category}': {len(filtered)} рядків")

    if not filtered:
        # показати унікальні категорії для діагностики
        cats = sorted({str(r[COL_PART]).strip() for r in all_rows[1:]
                       if r[COL_PART] and args.category[:5].lower() in str(r[COL_PART]).lower()})
        if cats:
            print("Схожі категорії в файлі:")
            for c in cats[:10]:
                print(f"  {c}")
        sys.exit("Нічого не знайдено — перевірте --category")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    xml_content, stats = generate_xml(
        rows=filtered,
        category_name=args.name_ua,
        cat_id_local=1,
        portal_cat_id=args.portal_cat_id,
        name_ua=args.name_ua,
        no_filter=args.no_filter,
    )

    out_path.write_text(xml_content, encoding="utf-8")

    print()
    print("─" * 50)
    print(f"Знайдено в категорії          : {stats['total_in']}")
    print(f"Пропущено (без фото)          : {stats['skip_photo']}")
    print(f"Пропущено (наявність=0)       : {stats['skip_avail']}")
    print(f"Пропущено (OEM пустий/ціна≤1) : {stats['skip_filter']}")
    print(f"Згенеровано товарів           : {stats['generated']}")
    print(f"Збережено → {out_path}")


if __name__ == "__main__":
    main()

````

### `agents/orders/ttn_pdf_parser.py` — 160 рядків

````python
import re
import sys
import os
import pdfplumber
from difflib import SequenceMatcher

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from shared.utils.db import get_connection


def normalize_phone(phone: str) -> str:
    """Normalize +380XXXXXXXXX or 380XXXXXXXXX to 0XXXXXXXXX."""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("380") and len(digits) == 12:
        return "0" + digits[3:]
    if digits.startswith("80") and len(digits) == 11:
        return "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        return digits
    return digits


def _extract_ttn(text: str):
    # NP TTN format: XX XXXX XXXX XXXX (14 digits, possibly space-separated)
    m = re.search(r"\b(\d{2})\s+(\d{4})\s+(\d{4})\s+(\d{4})\b", text)
    if m:
        return m.group(1) + m.group(2) + m.group(3) + m.group(4)
    # Fallback: 14 consecutive digits
    m = re.search(r"\b(\d{14})\b", text)
    if m:
        return m.group(1)
    return None


def _extract_recipient_block(text: str):
    """
    NP waybill: pdfplumber merges two columns left-to-right per line.
    Layout per line: <sender_token>  <recipient_token>
    After "КОМУ:" header, right-column tokens are the recipient.
    Heuristic: find standalone mixed-case Cyrillic full name on its own line.
    """
    lines = text.splitlines()

    # Find index of line containing "КОМУ"
    kому_idx = next(
        (i for i, l in enumerate(lines) if "КОМУ" in l.upper()), None
    )

    recipient = None
    city = None

    # Full name pattern: "Прізвище Ім'я По-батькові" in mixed case (not ALL CAPS)
    name_re = re.compile(
        r"^[А-ЯІЇЄ][а-яіїє']+\s+[А-ЯІЇЄ][а-яіїє']+(?:\s+[А-ЯІЇЄ][а-яіїє']+)?$"
    )

    # City from "Місто, Відділення" pattern (first occurrence = destination)
    city_branch_re = re.compile(
        r"([А-ЯІЇЄ][а-яіїє'\-]+(?:\s[А-ЯІЇЄ][а-яіїє'\-]+)*),\s*(?:Відділення|вул\.|відд)"
    )

    # Large destination city at top (ALL CAPS standalone line)
    dest_re = re.compile(r"^([А-ЯІЇЄ\-]{3,30})$")

    for i, line in enumerate(lines):
        line = line.strip()

        # Destination city — first ALL CAPS Cyrillic line
        if city is None and dest_re.match(line):
            city = line.capitalize()

        # Mixed-case full name after КОМУ block
        if kому_idx is not None and i > kому_idx and name_re.match(line):
            if recipient is None:
                recipient = line

        # City from "Місто, Відділення" (prefer first match = destination branch)
        if city is None:
            cm = city_branch_re.search(line)
            if cm:
                city = cm.group(1)

    return recipient, city


def parse_ttn_pdf(pdf_path: str) -> dict:
    """Parse Nova Poshta waybill PDF, extract TTN, phone, recipient, city."""
    result = {"ttn": None, "phone": None, "recipient": None, "city": None}

    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    result["ttn"] = _extract_ttn(text)

    # Phone: first Ukrainian phone in text (recipient side — left column for dest-city wbs)
    phones = re.findall(
        r"(?:\+?380|0)\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", text
    )
    if phones:
        result["phone"] = normalize_phone(phones[0])

    result["recipient"], result["city"] = _extract_recipient_block(text)

    return result


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def match_order_by_ttn_data(parsed: dict) -> list:
    """
    Search rozetka_processed_orders for orders matching parsed TTN data.
    Returns list of dicts with order_id and score.
    """
    phone = parsed.get("phone")
    recipient = parsed.get("recipient")
    city = parsed.get("city")
    matches = []

    try:
        conn = get_connection()
        cur = conn.cursor()

        if phone:
            cur.execute(
                "SELECT order_id, recipient, city FROM rozetka_processed_orders WHERE phone = %s",
                (phone,),
            )
            rows = cur.fetchall()
            for row in rows:
                score = 1.0
                if recipient and row["recipient"]:
                    score = max(score, _similarity(recipient, row["recipient"]))
                matches.append({"order_id": row["order_id"], "score": round(score, 3)})

        if not matches and (recipient or city):
            cur.execute(
                "SELECT order_id, recipient, city FROM rozetka_processed_orders "
                "WHERE recipient IS NOT NULL OR city IS NOT NULL"
            )
            rows = cur.fetchall()
            for row in rows:
                r_score = _similarity(recipient, row["recipient"]) if recipient else 0.0
                c_score = _similarity(city, row["city"]) if city else 0.0
                combined = (r_score + c_score) / 2
                if combined >= 0.6:
                    matches.append(
                        {"order_id": row["order_id"], "score": round(combined, 3)}
                    )
            matches.sort(key=lambda x: x["score"], reverse=True)

        cur.close()
        conn.close()
    except Exception as e:
        print(f"match_order_by_ttn_data error: {e}", file=sys.stderr)

    return matches

````

### `agents/orders/np_api.py` — 192 рядків

````python
import os
import sys
import requests
from difflib import SequenceMatcher

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))
from shared.utils.db import get_connection

NP_API_KEY = os.getenv("NP_API_KEY", "")
NP_API_URL = "https://api.novaposhta.ua/v2.0/json/"


def _normalize_phone(phone: str) -> str:
    import re
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("380") and len(digits) == 12:
        return "0" + digits[3:]
    if digits.startswith("80") and len(digits) == 11:
        return "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        return digits
    return digits


def get_ttn_info(ttn: str, phone: str = "") -> dict:
    """
    Track a Nova Poshta waybill via TrackingDocument/getStatusDocuments.
    Returns: recipient_name, recipient_phone, city, warehouse, cod_sum, status
    """
    result = {
        "ttn": ttn,
        "recipient_name": None,
        "recipient_phone": None,
        "city": None,
        "warehouse": None,
        "cod_sum": None,
        "status": None,
        "status_code": None,
        "raw": {},
    }

    if not NP_API_KEY:
        result["error"] = "NP_API_KEY not set in .env"
        return result

    payload = {
        "apiKey": NP_API_KEY,
        "modelName": "TrackingDocument",
        "calledMethod": "getStatusDocuments",
        "methodProperties": {
            "Documents": [{"DocumentNumber": ttn, "Phone": phone or ""}]
        },
    }

    try:
        r = requests.post(NP_API_URL, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        result["error"] = str(e)
        return result

    if not data.get("success"):
        result["error"] = "; ".join(data.get("errors", ["unknown error"]))
        return result

    docs = data.get("data", [])
    if not docs:
        result["error"] = "No data returned for this TTN"
        return result

    doc = docs[0]
    result["raw"] = doc
    result["recipient_name"]  = (doc.get("RecipientFullName") or "").strip() or None
    phone_r = doc.get("PhoneRecipient") or ""
    result["recipient_phone"] = _normalize_phone(phone_r) if phone_r else None
    result["city"]            = doc.get("CityRecipient") or None
    result["warehouse"]       = doc.get("WarehouseRecipient") or None
    result["status"]          = doc.get("Status") or None
    result["status_code"]     = doc.get("StatusCode") or None

    cod_raw = doc.get("CashPaymentAmount") or doc.get("AnnouncedPrice") or 0
    try:
        result["cod_sum"] = float(cod_raw)
    except (ValueError, TypeError):
        result["cod_sum"] = None

    return result


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _price_score(actual: float, expected: float) -> float:
    if not expected:
        return 0.0
    diff = abs(actual - expected)
    if diff > expected * 0.05:
        return 0.0
    return round(1.0 - diff / expected, 3)


def match_order_by_np_data(ttn_info: dict) -> list:
    """
    Search rozetka_processed_orders with 3-level priority:
      1. exact phone                       -> score 1.0,      match_by='phone'
      2. name similarity (>=0.6) + price   -> weighted score, match_by='name+price'
      3. price only (within +-5%)          -> price score,    match_by='price'
    Returns immediately when matches found at any level.
    """
    phone   = ttn_info.get("recipient_phone")
    cod_sum = ttn_info.get("cod_sum")
    name    = ttn_info.get("recipient_name")
    matches = []

    try:
        conn = get_connection()
        cur  = conn.cursor()

        # Level 1: exact phone
        if phone:
            cur.execute(
                "SELECT order_id, total_price, phone, recipient"
                " FROM rozetka_processed_orders WHERE phone = %s",
                (phone,),
            )
            for row in cur.fetchall():
                matches.append({
                    "order_id": row["order_id"],
                    "score":    1.0,
                    "match_by": "phone",
                })

        if matches:
            cur.close(); conn.close()
            return matches

        # Level 2: name similarity (>=0.6) + price within 5%
        if name and cod_sum and cod_sum > 0:
            margin = cod_sum * 0.05
            cur.execute(
                "SELECT order_id, total_price, recipient"
                " FROM rozetka_processed_orders"
                " WHERE total_price BETWEEN %s AND %s AND recipient IS NOT NULL",
                (cod_sum - margin, cod_sum + margin),
            )
            for row in cur.fetchall():
                n_score = _similarity(name, row["recipient"])
                if n_score < 0.6:
                    continue
                p_score  = _price_score(float(row["total_price"]), cod_sum)
                combined = round(n_score * 0.7 + p_score * 0.3, 3)
                matches.append({
                    "order_id": row["order_id"],
                    "score":    combined,
                    "match_by": "name+price",
                })
            matches.sort(key=lambda x: x["score"], reverse=True)

        if matches:
            cur.close(); conn.close()
            return matches

        # Level 3: price only within 5%
        if cod_sum and cod_sum > 0:
            margin = cod_sum * 0.05
            cur.execute(
                "SELECT order_id, total_price"
                " FROM rozetka_processed_orders"
                " WHERE total_price BETWEEN %s AND %s",
                (cod_sum - margin, cod_sum + margin),
            )
            for row in cur.fetchall():
                p_score = _price_score(float(row["total_price"]), cod_sum)
                matches.append({
                    "order_id": row["order_id"],
                    "score":    p_score,
                    "match_by": "price",
                })
            matches.sort(key=lambda x: x["score"], reverse=True)

        cur.close()
        conn.close()
    except Exception as e:
        print(f"match_order_by_np_data error: {e}", file=sys.stderr)

    return matches

````

### `tg_dispatcher/main.py` — 511 рядків

````python
"""
tg_dispatcher/main.py
=======================
Telegram ШІ-Диспетчер — головна точка входу.

Стек:
- aiogram 3.x — асинхронний Telegram фреймворк
- faster-whisper — локальний STT (голос→текст) на GPU/CPU
- LangGraph — оркестратор агента з інструментами
- Qdrant — векторна БД для /learn правил

Безпека: бот відповідає ТІЛЬКИ ADMIN_ID з .env

Запуск:
    cd /home/tek/agent-system/tg_dispatcher
    python3 main.py

Як сервіс:
    systemctl --user start tg-dispatcher
"""

import os, sys, asyncio, logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, Voice
from aiogram.filters import CommandStart, Command
from aiogram.utils.markdown import bold, italic

# Завантажуємо .env з agent-system
load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))

TOKEN    = os.getenv('TELEGRAM_BOT_TOKEN', '')
ADMIN_ID         = int(os.getenv('TELEGRAM_ADMIN_ID', '0'))
CARVOL_TG_CHAT_ID = int(os.getenv('CARVOL_TG_CHAT_ID', '0'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp  = Dispatcher()

sys.path.insert(0, '/home/tek/agent-system')


# =============================================
# МІДЛВАР БЕЗПЕКИ — відхиляє всіх крім ADMIN
# =============================================

@dp.message.outer_middleware()
async def security_middleware(handler, event, data):
    user_id = event.from_user.id
    if user_id == ADMIN_ID:
        return await handler(event, data)
    # Carvol може надсилати тільки document (PDF накладні)
    if CARVOL_TG_CHAT_ID and user_id == CARVOL_TG_CHAT_ID:
        if getattr(event, 'document', None):
            return await handler(event, data)
        return  # всі інші типи від Carvol — мовчки ігноруємо
    logger.warning(f'Відхилено доступ від ID: {user_id} (@{event.from_user.username})')


# =============================================
# КОМАНДИ
# =============================================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f'👋 Привіт, босс!\n\n'
        f'Я твій ШІ-диспетчер агентної системи.\n\n'
        f'<b>Команди:</b>\n'
        f'/status — статус системи\n'
        f'/prices — цінові алерти\n'
        f'/orders — нові замовлення\n'
        f'/learn [текст] — навчити агента правилу\n\n'
        f'Або пиши/говори вільним текстом:\n'
        f'«Онови ціни в Єпіцентрі»\n'
        f'«Скільки замовлень сьогодні?»\n'
        f'«Знайди ціни конкурентів на BAEA1217»\n\n'
        f'📄 Надішли PDF накладну НП — автоматично встановлю ТТН.',
        parse_mode='HTML'
    )


@dp.message(Command('status'))
async def cmd_status(message: Message):
    """Статус системи з БД."""
    try:
        from shared.utils.db import get_connection
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('''
            SELECT
                (SELECT COUNT(*) FROM my_products WHERE price_our > 0) as products,
                (SELECT COUNT(*) FROM price_history WHERE date = CURRENT_DATE) as prices_today,
                (SELECT COUNT(*) FROM orders WHERE created_at >= NOW() - INTERVAL '24 hours') as orders_today,
                (SELECT COUNT(*) FROM my_products WHERE epicentr_category_id IS NULL AND price_our > 0) as drafts,
                (SELECT COUNT(*) FROM my_products WHERE epicentr_confidence = 'high') as classified_high
        ''')
        s = dict(cur.fetchone())
        cur.close(); conn.close()

        await message.answer(
            f'📊 <b>Статус системи</b>\n\n'
            f'📦 Товарів з ціною: {s["products"]}\n'
            f'💰 Цін оновлено сьогодні: {s["prices_today"]}\n'
            f'🛒 Замовлень за 24г: {s["orders_today"]}\n'
            f'📝 Чернеток без категорії: {s["drafts"]}\n'
            f'✅ Класифіковано (high): {s["classified_high"]}',
            parse_mode='HTML'
        )
    except Exception as e:
        await message.answer(f'❌ Помилка БД: {e}')


@dp.message(Command('prices'))
async def cmd_prices(message: Message):
    """Цінові алерти за сьогодні."""
    try:
        from shared.utils.db import get_connection
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('''
            SELECT sku, our_price, prev_our_price, our_diff_pct, alert_reason
            FROM price_history
            WHERE date = CURRENT_DATE AND is_alert = TRUE AND ABS(our_diff_pct) >= 10
            ORDER BY ABS(our_diff_pct) DESC LIMIT 10
        ''')
        rows = cur.fetchall()
        cur.close(); conn.close()

        if not rows:
            await message.answer('✅ Значних змін цін сьогодні немає')
            return

        text = f'⚠️ <b>Цінові алерти сьогодні</b>:\n\n'
        for r in rows:
            emoji = '📈' if r['our_diff_pct'] > 0 else '📉'
            text += f'{emoji} <code>{r["sku"]}</code>: {r["prev_our_price"]:.0f}→{r["our_price"]:.0f} ({r["our_diff_pct"]:+.1f}%)\n'
        await message.answer(text, parse_mode='HTML')
    except Exception as e:
        await message.answer(f'❌ Помилка: {e}')


@dp.message(Command('orders'))
async def cmd_orders(message: Message):
    """Замовлення за останні 24 години."""
    try:
        from shared.utils.db import get_connection
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute('''
            SELECT prom_order_id, epicentr_order_id, status, customer_name, total_price, created_at
            FROM orders
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC LIMIT 10
        ''')
        rows = cur.fetchall()
        cur.close(); conn.close()

        if not rows:
            await message.answer('📭 Замовлень за останні 24г немає')
            return

        text = f'🛒 <b>Замовлення за 24г</b> ({len(rows)}):\n\n'
        for r in rows:
            order_id = r['prom_order_id'] or r['epicentr_order_id'] or '?'
            text += f'#{order_id} — {r["customer_name"] or "?"} — {r["total_price"]} грн ({r["status"]})\n'
        await message.answer(text, parse_mode='HTML')
    except Exception as e:
        await message.answer(f'❌ Помилка: {e}')


@dp.message(Command('learn'))
async def cmd_learn(message: Message):
    """Навчити агента новому правилу."""
    instruction = message.text.replace('/learn', '').strip()
    if not instruction:
        await message.answer(
            '📚 Використання:\n'
            '/learn [опис зміни]\n\n'
            'Приклад:\n'
            '/learn Єпіцентр змінив кнопку export. Тепер вона в меню Товари → Вивантажити'
        )
        return

    try:
        from agents.interfaces.instruction_parser import InstructionParser
        parser = InstructionParser()
        result = await parser.apply_instruction(instruction, message.from_user.id)

        if result['success']:
            await message.answer(
                f'✅ Правило збережено!\n\n'
                f'📝 Файл: {result["skill_file"]}'
            )
        else:
            await message.answer(f'❌ Помилка: {result["error"]}')
    except Exception as e:
        await message.answer(f'❌ Помилка: {e}')


# =============================================
# PDF НАКЛАДНІ (ТТН від Carvol) — повністю автоматично
# =============================================

def _fmt_source_info(ttn: str, data_source: str,
                     ttn_info: dict | None, parsed: dict) -> str:
    """Формує блок з даними для повідомлення адміну."""
    # Беремо поля з НП API якщо є, інакше з PDF
    np = ttn_info or {}
    recipient = np.get('recipient_name') or parsed.get('recipient') or 'не знайдено'
    phone     = np.get('recipient_phone') or parsed.get('phone')     or 'не знайдено'
    city      = np.get('city')           or parsed.get('city')       or 'не знайдено'
    warehouse = np.get('warehouse') or ''
    city_line = f'{city} {warehouse}'.strip() if warehouse else city

    source_icon = '🌐 НП API' if 'НП API' in data_source else '📄 PDF'
    return (
        f'📋 <b>Дані ({source_icon}):</b>\n'
        f'ТТН: <code>{ttn}</code>\n'
        f'Отримувач: {recipient}\n'
        f'Телефон: <code>{phone}</code>\n'
        f'Місто: {city_line}'
    )


@dp.message(F.document)
async def handle_document(message: Message):
    """PDF накладна НП від Carvol або адміна — автоматичне встановлення ТТН."""
    from_carvol    = CARVOL_TG_CHAT_ID and message.from_user.id == CARVOL_TG_CHAT_ID
    target_chat_id = ADMIN_ID if from_carvol else message.chat.id

    doc = message.document
    if not doc.mime_type or 'pdf' not in doc.mime_type.lower():
        if not from_carvol:
            await bot.send_message(target_chat_id, '📎 Підтримуються тільки PDF файли (накладні НП).')
        return

    label      = '📄 Carvol надіслав накладну — обробляю...' if from_carvol else '📄 Обробляю PDF накладну...'
    status_msg = await bot.send_message(target_chat_id, label)
    pdf_path   = f'/tmp/ttn_{message.message_id}.pdf'

    try:
        file = await bot.get_file(doc.file_id)
        await bot.download_file(file.file_path, destination=pdf_path)

        from agents.orders.ttn_pdf_parser import parse_ttn_pdf, match_order_by_ttn_data
        from agents.orders.np_api import get_ttn_info, match_order_by_np_data
        from agents.orders.rozetka_order_agent import set_ttn, change_status, get_order_details

        # --- Крок 1: парсинг PDF ---
        parsed = await asyncio.to_thread(parse_ttn_pdf, pdf_path)
        ttn    = parsed.get('ttn')

        if not ttn:
            info = _fmt_source_info('не знайдено', 'PDF', None, parsed)
            await status_msg.edit_text(
                f'⚠️ <b>ТТН не знайдено в PDF</b>\n\n{info}\n\n'
                f'Вкажи вручну: /ttn ORDER_ID НОМЕР_ТТН',
                parse_mode='HTML',
            )
            return

        pdf_url = f"https://api.novaposhta.ua/v2.0/print/orders/?orders[]={ttn}&type=pdf"

        # --- Крок 2: НП API для уточнення даних ---
        await status_msg.edit_text(
            f'📄 ТТН <code>{ttn}</code> — перевіряю в НП API...',
            parse_mode='HTML',
        )

        ttn_info    = await asyncio.to_thread(get_ttn_info, ttn, parsed.get('phone') or '')
        np_ok       = not ttn_info.get('error') and (
            ttn_info.get('recipient_name') or ttn_info.get('recipient_phone')
        )
        data_source = 'НП API' if np_ok else 'PDF'
        source_info = _fmt_source_info(ttn, data_source, ttn_info if np_ok else None, parsed)

        if ttn_info.get('error'):
            logger.warning(f'НП API error для {ttn}: {ttn_info["error"]}')

        # --- Крок 3: матчинг замовлення ---
        matches = []
        match_source = data_source

        if np_ok:
            matches = await asyncio.to_thread(match_order_by_np_data, ttn_info)
            if not matches:
                # fallback на PDF-дані
                matches = await asyncio.to_thread(match_order_by_ttn_data, parsed)
                match_source = 'PDF (fallback)'

        if not matches:
            matches = await asyncio.to_thread(match_order_by_ttn_data, parsed)
            match_source = 'PDF'

        if not matches:
            await status_msg.edit_text(
                f'❌ <b>Замовлення не знайдено</b>\n\n{source_info}\n\n'
                f'Джерело матчингу: {match_source}\n\n'
                f'Вкажи вручну:\n<code>/ttn ORDER_ID {ttn}</code>',
                parse_mode='HTML',
            )
            return

        # --- Кілька збігів — список без кнопок ---
        if len(matches) > 1:
            lines = '\n'.join(
                f'  #{m["order_id"]} ({m["score"]:.0%}, by {m.get("match_by","?")})'
                for m in matches[:5]
            )
            await status_msg.edit_text(
                f'🔍 <b>Знайдено {len(matches)} збігів</b> [{match_source}]\n\n'
                f'{source_info}\n\n'
                f'Збіги:\n{lines}\n\n'
                f'Вкажи вручну:\n<code>/ttn ORDER_ID {ttn}</code>',
                parse_mode='HTML',
            )
            return

        # --- Один збіг — автоматично ---
        order_id = matches[0]['order_id']
        score    = matches[0]['score']
        match_by = matches[0].get('match_by', '?')

        await status_msg.edit_text(
            f'{source_info}\n\n'
            f'⏳ #{order_id} (score {score:.0%}, by {match_by}) [{match_source}]\n'
            f'Встановлюю ТТН...',
            parse_mode='HTML',
        )

        # --- Крок 4: set_ttn + change_status(3) ---
        ok_ttn    = await asyncio.to_thread(set_ttn, order_id, ttn)
        ok_status = await asyncio.to_thread(change_status, order_id, 3) if ok_ttn else False

        if ok_ttn:
            try:
                from shared.utils.db import get_connection
                conn = get_connection()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE rozetka_processed_orders SET ttn=%s, status='shipped' WHERE order_id=%s",
                    (ttn, order_id)
                )
                conn.commit()
                cur.close(); conn.close()
            except Exception as db_err:
                logger.error(f'DB update TTN failed for #{order_id}: {db_err}')

        # --- Крок 5: верифікація GET /orders/{id} ---
        await asyncio.sleep(2)
        order_data   = await asyncio.to_thread(get_order_details, order_id)
        actual_ttn   = (order_data.get('ttn') or '').strip()
        ttn_verified = (actual_ttn == ttn)

        if ok_ttn and ok_status and ttn_verified:
            await status_msg.edit_text(
                f'{source_info}\n\n'
                f'✅ <b>Готово!</b>\n'
                f'Замовлення: <b>#{order_id}</b>\n'
                f'ТТН <code>{ttn}</code> — встановлено та підтверджено (GET)\n'
                f'Статус → «Передано в доставку»\n'
                f'📄 <a href="{pdf_url}">PDF накладна</a>',
                parse_mode='HTML',
            )
        elif ok_ttn and ok_status and not ttn_verified:
            await status_msg.edit_text(
                f'🚨 <b>ALARM! ТТН не збереглось у Розетці</b>\n\n'
                f'{source_info}\n\n'
                f'Замовлення: <b>#{order_id}</b>\n'
                f'set_ttn: ✅  |  change_status: ✅\n'
                f'Верифікація GET: ❌ поле ttn = <code>{actual_ttn or "порожньо"}</code>\n\n'
                f'Встанови вручну:\n<code>/ttn {order_id} {ttn}</code>\n'
                f'📄 <a href="{pdf_url}">PDF накладна</a>',
                parse_mode='HTML',
            )
        elif ok_ttn and not ok_status:
            v_icon = '✅' if ttn_verified else '❌'
            await status_msg.edit_text(
                f'⚠️ <b>ТТН встановлено, статус НЕ змінився</b>\n\n'
                f'Замовлення: <b>#{order_id}</b>\n'
                f'ТТН <code>{ttn}</code>: {v_icon} (GET)\n'
                f'Статус → 3: ❌ помилка API\n\nПеревір вручну.',
                parse_mode='HTML',
            )
        else:
            await status_msg.edit_text(
                f'🚨 <b>ALARM! Не вдалось встановити ТТН</b>\n\n'
                f'{source_info}\n\n'
                f'Замовлення: <b>#{order_id}</b>\n'
                f'set_ttn: ❌\n\n'
                f'Встанови вручну:\n<code>/ttn {order_id} {ttn}</code>\n'
                f'📄 <a href="{pdf_url}">PDF накладна</a>',
                parse_mode='HTML',
            )

    except Exception as e:
        logger.error(f'handle_document error: {e}', exc_info=True)
        await status_msg.edit_text(f'❌ Помилка обробки PDF: {e}')
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


# =============================================
# ГОЛОСОВІ ПОВІДОМЛЕННЯ
# =============================================

@dp.message(F.voice)
async def handle_voice(message: Message):
    """Приймає голосове → STT → обробляє як текст."""
    status_msg = await message.answer('🎤 Розшифровую аудіо...')

    file_path = f'/tmp/voice_{message.message_id}.ogg'
    try:
        file = await bot.get_file(message.voice.file_id)
        await bot.download_file(file.file_path, destination=file_path)

        try:
            from ai_brain.voice_handler import transcribe_audio_async
            text = await transcribe_audio_async(file_path)

            if text:
                await status_msg.edit_text(f'📝 Почув:\n<i>{text}</i>', parse_mode='HTML')
                message.text = text
                await handle_text(message)
            else:
                await status_msg.edit_text('❌ Не вдалось розпізнати. Спробуй чіткіше.')
        except ImportError:
            await status_msg.edit_text(
                '⚠️ faster-whisper не встановлено.\n'
                'Встанови: pip install faster-whisper'
            )
    except Exception as e:
        logger.error(f'Voice error: {e}')
        await status_msg.edit_text(f'🔧 Помилка обробки аудіо: {e}')
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


# =============================================
# ТЕКСТОВІ КОМАНДИ (вільний текст)
# =============================================

@dp.message(F.text)
async def handle_text(message: Message):
    """Роутить вільний текст до відповідного агента."""
    text = message.text.lower().strip()

    if any(w in text for w in ['єпіцентр', 'епіцентр', 'epicentr']):
        await route_epicentr(message, text)
    elif any(w in text for w in ['розетка', 'rozetka']):
        await message.answer('🏬 Розетка — перевіряю... [в розробці]')
    elif any(w in text for w in ['prom', 'пром', 'ціни', 'price']):
        await cmd_prices(message)
    elif any(w in text for w in ['замовлення', 'order']):
        await cmd_orders(message)
    elif any(w in text for w in ['статус', 'status', 'стан']):
        await cmd_status(message)
    elif any(w in text for w in ['конкурент', 'competitor']):
        await message.answer('🔍 Моніторинг конкурентів — в розробці')
    else:
        await message.answer(
            f'🤔 Не зрозумів: «{message.text[:50]}»\n\n'
            f'Спробуй:\n'
            f'• /status — статус системи\n'
            f'• /prices — цінові алерти\n'
            f'• /orders — замовлення\n'
            f'• «Єпіцентр XLS» — скачати товари\n'
            f'• «ціни конкурентів SKU» — перевірка\n'
            f'• 📄 PDF накладна — встановити ТТН'
        )


async def route_epicentr(message: Message, text: str):
    if any(w in text for w in ['xls', 'скачай', 'вивантаж', 'export']):
        await message.answer('⏳ Скачую XLS товарів Єпіцентру...\n[Playwright запускається]')
    elif any(w in text for w in ['ціни', 'оновити', 'import', 'завантаж']):
        await message.answer('⏳ Генерую XLS цін і завантажую в Єпіцентр...')
    elif any(w in text for w in ['api', 'endpoint']):
        await message.answer('⏳ Перехоплюю API endpoints...')
    elif any(w in text for w in ['замовлення', 'order']):
        await cmd_orders(message)
    else:
        await message.answer(
            '🏪 <b>Єпіцентр</b> — що зробити?\n\n'
            '• «Єпіцентр XLS» — скачати товари\n'
            '• «Єпіцентр ціни» — оновити ціни\n'
            '• «Єпіцентр API» — знайти endpoints',
            parse_mode='HTML'
        )


# =============================================
# ЗАПУСК
# =============================================

async def main():
    logger.info('=== Telegram ШІ-Диспетчер запуск ===')
    logger.info(f'Admin ID: {ADMIN_ID}')
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == '__main__':
    asyncio.run(main())

````

### `shared/utils/db.py` — 67 рядків

````python
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from loguru import logger

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", 5432),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        cursor_factory=RealDictCursor
    )

def log_event(agent_name: str, level: str, message: str, metadata: dict = None):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM agents WHERE name = %s", (agent_name,)
        )
        row = cur.fetchone()
        agent_id = row["id"] if row else None
        cur.execute(
            """INSERT INTO event_logs (agent_id, level, message, metadata)
               VALUES (%s, %s, %s, %s)""",
            (agent_id, level, message, psycopg2.extras.Json(metadata or {}))
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"DB log error: {e}")

def create_alert(source: str, title: str, message: str, level: str = "INFO"):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO alerts (source, title, message, level)
               VALUES (%s, %s, %s, %s)""",
            (source, title, message, level)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Alert error: {e}")

def update_agent_status(agent_name: str, status: str):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """UPDATE agents SET status = %s, updated_at = NOW()
               WHERE name = %s""",
            (status, agent_name)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Status update error: {e}")

````
