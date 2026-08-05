#!/usr/bin/env python3
"""
tools/noire_epicentr_generator.py
===================================
Генератор Єпіцентр XML для проекту NOIRE (sexopt_products).

Джерела даних:
  - sexopt_products           — товари, ціни, описи, фото
  - epicentr_category_mapping — sexopt_category_id → epicentr_category_code
  - epicentr_default_dimensions — габарити/вага за категорією (per-category, не глобальний дефолт)
  - epicentr_brand_map        — valuecode бренду для <vendor code="...">

Запуск:
    cd /home/tekken/agent-system && source venv/bin/activate
    python3 tools/noire_epicentr_generator.py
    python3 tools/noire_epicentr_generator.py --output exports/noire_epicentr_20260718.xml
    python3 tools/noire_epicentr_generator.py --category 9466
    python3 tools/noire_epicentr_generator.py --limit 100 --output /tmp/noire_test.xml
    python3 tools/noire_epicentr_generator.py --all-available
"""

import argparse, math, os, re, sys
from html import unescape
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, '.env'))

from loguru import logger
from shared.utils.db import get_connection

# ── Вихідний файл за замовчуванням ─────────────────────────────────────────

OUTPUT_FILE = os.path.join(BASE_DIR, 'exports', 'noire_epicentr.xml')

# ── Комісія Єпіцентру (%) та надбавка продавця ─────────────────────────────
# Скоригуй MARKUP під власну маржу перед першим реальним імпортом.
# За замовчуванням 1.0 = ціна постачальника без додаткової надбавки.

MARKUP = 1.0

# Джерело: epicentr_cpa_rates. Ставка залежить від КОРЕНЕВОЇ гілки, а не від
# конкретної категорії:
#   3274 Інтимні товари  → 10%
#   7231 Медичні товари  → 15%   (сюди веде 3256 Домашня аптека → 3275 Презервативи)
# Тому ставку не можна брати єдину на весь фід: товари з аптечної гілки
# потребують більшого gross-up, інакше маржа з'їдається різницею в 5 п.п.
EPICENTR_COMMISSION: dict[str, float] = {
    '3275': 15.0,   # Презервативи (гілка Медичні товари)
    '7715': 15.0,   # Інтимні змазки — та сама гілка, на випадок переїзду
}
DEFAULT_COMMISSION = 10.0

# ── Fallback-габарити якщо категорія відсутня в epicentr_default_dimensions ─
FALLBACK_DIM = {'weight_g': 300, 'width_mm': 150, 'height_mm': 100, 'length_mm': 150}

# ── Бренд-код Єпіцентру для невідомих брендів ──────────────────────────────
OTHER_BRAND_CODE = '827b4a70220f11ea918e001e67ecc97b'

# ── Valuecodes для bool-атрибутів (так/ні) ───────────────────────────────────
# Джерело: GET /v2/pim/attribute-sets/{cat}/attributes/{code}/options (2026-07-18)
BOOL_VALUECODES: dict[str, tuple[str, str, str, str]] = {
    # attr_code: (attr_name, paramcode, ні_valuecode, так_valuecode)
    '10173': ('Підігрів',                  '10173',
              '3768c4769c222a781cbdf9250ce732f4',
              'e63c2e762f767ebd4e47c4a85712fb8e'),
    '11953': ('Водонепроникний',            '11953',
              '2dc3b994d8e44e506c5b35afeb4caf83',
              'f66982870e511e6b37c96ec49924424f'),
    '11579': ('Вібрація',                  '11579',
              '8cbc536e7dd022c64f0dcc967779f19a',
              'e42394421a4adcea73716be8198b274c'),
    '11367': ('Телескопічний',             '11367',
              'f123af871c276119b63fb5425dbd9949',
              '911d08bdb26f0a4b59af332d83ce98f9'),
    '11988': ('Кріплення на присоску',     '11988',
              'a0635ddafb274c18b3d20496cd102142',
              '70fbdadf21b4580881415413f2fab3fc'),
    '9977':  ('Кілька насадок',            '9977',
              '2c1fa955a0c699e22c28676c43d05c63',
              'c1b13316e466ce2b8a0d1b9b2dd3b744'),
    '10210': ('Керування через застосунок', '10210',
              '795f3166fa7d8d09124f5dd793e91910',
              '5e406ffa3c830475694abf2f5c8aae43'),
    # New bool attrs
    '4801':  ('Манометр',                  '4801',
              '319a2874bce2ff7419043c6255debb35',
              '55149546e7e582816d5ac46133727475'),
    '4758':  ('Вакуумна стимуляція',        '4758',
              'd9cc964219805f642119d9ea2b3c1aa7',
              'b97c968e9fb23b9a3331ec9df9ca17ce'),
    '4592':  ('Знімний фалос',             '4592',
              'b60e8126a8a093c3918cb646dfb97442',
              '98f91f08fc31b5ab579d5560278bcaa3'),
    '4700':  ('Регульовані ремені',         '4700',
              '156d0bda9a3dd044230d772e0454e8ac',
              'ddca016734e6270951b391a635a7b32d'),
    '4738':  ('Ротація',                   '4738',
              '249c9c34005bcb5535d1f2d2474c085a',
              '765a5f8350dab16e094f972599c79775'),
    '7267':  ('Регулювання діаметра',       '7267',
              'c1fef94c7071f78218c33ef5389d82bd',
              '1a76fdbe9dc1d503d915f25839a56740'),
    # 9468 Секс-ляльки
    '4251':  ('Сенсорне реагування',       '4251',
              'd9a58c0f4d16cc8c1bdbd382e16408c2',
              '26a9448f9797fbcd14ff86e436547161'),
    '4793':  ('Звукові ефекти',            '4793',
              '3c02181c215365743723b9d158d8536a',
              '094b5fefcdf09c0f1180f746062a9d07'),
    '5024':  ('Сумісність з VR',           '5024',
              '71bc47434cdf240f6d0b7cfdf8864f66',
              'a320163dc7d818646f026a1def1f722b'),
    '5181':  ('Статевий член',             '5181',
              '446c45edc56f67e950b479c414f765f9',
              'e193ef1d7a911d6d0ce306ea3319a639'),
    '5197':  ('Оральний отвір',            '5197',
              'e5aae4944bc94b5668fac51f84c4c676',
              'b46da99f65b91cf72ecdf9ca5f1f9650'),
    '5223':  ('Анальний отвір',            '5223',
              '9ce4e3186627319de14064e24686f3be',
              '5d853387252804395587071d02afde75'),
    '5255':  ('Вагінальний отвір',         '5255',
              '5ae1d2b8e4b74a16f351b48be95f05d4',
              'a562464e4abf950ea7dc62104c19b1cb'),
}

# Атрибути нового типу (15xxx): valuecode = 'yes'/'no' (рядок, не UUID)
NEW_BOOL_ATTR_CODES: set[str] = {
    '15745', '15746', '15747', '15748', '15749', '15750',
    '15752', '15753', '15754', '15755', '15756', '15757',
    '15758', '15759', '15768', '15769', '15770', '15771',
    '15772', '15773',
    '15784', '15785',
    # 9578 sex furniture bools
    '15723', '15724', '15728', '15729', '15730', '15731', '15732', '15733',
    # 9550 anal douche bools
    '14209', '14813', '14817', '14822', '14823',
    # 9548 anal expander bools
    '14799', '14800', '14801', '14802', '14803', '14804', '14805',
}

# Обов'язкові bool-атрибути по категорії — для default=ні якщо не знайдено
# Код 11098 (Тип живлення) — не bool, але для 9484 обов'язковий; окремо обробляємо нижче
CAT_REQUIRED_BOOL: dict[str, list[str]] = {
    '9460': ['10173', '11953', '11579', '10210'],
    '9462': ['10173', '11953', '11367', '11988', '9977', '10210'],
    '9464': ['10173', '11953', '11579', '11988', '9977', '10210'],
    '9466': ['10173', '11953', '11367', '11988', '9977', '10210'],
    '9470': ['10173', '11579', '10210', '7267'],
    '9472': ['10173', '11953', '11579', '10210'],
    '9474': ['10173', '11579', '10210'],
    '9476': ['4801'],
    '9478': ['10173', '11579'],
    '9480': ['11953', '11579', '11988'],
    '9482': ['10173', '11579', '10210', '4758', '4592', '4700', '4738'],
    '9484': ['10173', '11579'],
    '9488': ['10173', '10210'],
    '9468': ['10173', '11579', '10210', '4251', '4793', '5024'],
}

# Обов'язкові "yes/no" bool-атрибути по категорії (15xxx-серія, valuecode = 'yes'/'no')
CAT_REQUIRED_NEW_BOOL: dict[str, list[tuple[str, str]]] = {
    '9628': [  # Оральні засоби
        ('15745', 'Зігріваючий'), ('15746', 'Охолоджуючий'), ('15747', 'Розслаблюючий'),
        ('15749', 'Збуджуючий'), ('15750', 'Зволожуючий'), ('15754', 'Їстівна формула'),
        ('15768', 'Посилення чутливості'), ('15769', 'Посилення слиновиділення'),
        ('15770', 'Віброефект'), ('15771', 'Сумісність з презервативами'),
        ('15772', 'Сумісність з секс-іграшками'), ('15773', 'Веганський'),
    ],
    '9632': [  # Олія
        ('15745', 'Зігріваючий'), ('15746', 'Охолоджуючий'), ('15747', 'Розслаблюючий'),
        ('15748', 'Тонізуючий'), ('15749', 'Збуджуючий'), ('15750', 'Зволожуючий'),
        ('15752', "Пом'якшуючий"), ('15753', 'Антистресовий'), ('15754', 'Їстівна формула'),
        ('15755', 'Органічний продукт'), ('15756', 'Без парабенів'),
        ('15757', 'Без гліцерину'), ('15758', 'Без ароматизаторів'), ('15759', 'З феромонами'),
    ],
    '9630': [  # Свічки
        ('15745', 'Зігріваючий'), ('15747', 'Розслаблюючий'),
        ('15750', 'Зволожуючий'), ('15752', "Пом'якшуючий"),
    ],
    '9636': [  # Пролонгатори
        ('15745', 'Зігріваючий'), ('15746', 'Охолоджуючий'),
        ('15748', 'Тонізуючий'), ('15750', 'Зволожуючий'),
        ('15768', 'Посилення чутливості'), ('15771', 'Сумісність з презервативами'),
        ('15772', 'Сумісність з секс-іграшками'),
        ('15784', 'Посилення ерекції'), ('15785', 'Подовження статевого акту'),
    ],
    '9578': [  # Меблі для сексу
        ('15723', 'Вібрація'), ('15724', 'Підігрів'),
        ('15728', 'Ремені для фіксації'), ('15729', 'Дзеркальні елементи'),
        ('15730', 'Колеса для переміщення'), ('15731', 'Складана конструкція'),
        ('15732', 'Сумісність з аксесуарами'), ('15733', 'Нековзкі ніжки'),
    ],
    '9550': [  # Анальний душ
        ('14209', 'Водонепроникність'), ('14813', 'Регулювання тиску води'),
        ('14817', 'Регулювання потоку'), ('14822', 'Знімний наконечник'),
        ('14823', 'Гнучкий шланг'),
    ],
    '9548': [  # Анальні розширювачі
        ('14799', 'Вібрація'), ('14800', 'З можливістю накачування'),
        ('14801', 'Можна використовувати у воді'), ('14802', 'Наявність шийки'),
        ('14803', 'Пульт керування'), ('14804', 'Мобільний додаток'),
        ('14805', 'Без фталатів'),
    ],
}

# Категорії, де country_of_origin та brand є обов'язковими як param-елементи
CAT_COUNTRY_BRAND_REQUIRED = {'3275', '7216', '9458', '9460', '9466', '9472',
                              '9480', '9484'}

# Маппінг витягнутого значення → (valuecode, display_ua) для Матеріал
MATERIAL_VALUECODE: dict[str, tuple[str, str]] = {
    'силікон':             ('063a479f96ed369ac655b2d6e90f216b', 'силікон'),
    'силіконовий':         ('063a479f96ed369ac655b2d6e90f216b', 'силікон'),
    'silicone':            ('063a479f96ed369ac655b2d6e90f216b', 'силікон'),
    'abs':                 ('35d73f60d46d4a4871e86947088e318c', 'АБС-пластик'),
    'абс':                 ('35d73f60d46d4a4871e86947088e318c', 'АБС-пластик'),
    'пластик':             ('35d73f60d46d4a4871e86947088e318c', 'АБС-пластик'),
    # TPE і TPR — різні valuecodes, cat-aware fallback нижче
    'tpe':                 ('36ead368e43d489285c7031a730ff31d', 'TPE (термопластичний еластомер)'),
    'tpr':                 ('8c64e0f6c6e6e47cddf4249588d6e260', 'TPR (термопластична гума)'),
    'термопластичний':     ('8c64e0f6c6e6e47cddf4249588d6e260', 'TPR (термопластична гума)'),
    'ultraskyn':           ('8c64e0f6c6e6e47cddf4249588d6e260', 'TPR (термопластична гума)'),
    'ur3':                 ('8c64e0f6c6e6e47cddf4249588d6e260', 'TPR (термопластична гума)'),
    'cyberskin':           ('107049ee3bce3a3a62e14648ea19260f', 'кібершкіра'),
    'кібершкіра':          ('107049ee3bce3a3a62e14648ea19260f', 'кібершкіра'),
    'кіберскін':           ('107049ee3bce3a3a62e14648ea19260f', 'кібершкіра'),
    'superskin':           ('8c64e0f6c6e6e47cddf4249588d6e260', 'TPR (термопластична гума)'),
    'sensafeel':           ('8c64e0f6c6e6e47cddf4249588d6e260', 'TPR (термопластична гума)'),
    'реалfeel':            ('8c64e0f6c6e6e47cddf4249588d6e260', 'TPR (термопластична гума)'),
    'pvc':                 ('be10ef08d4f42f41065fabbedbb921dc', 'PVC (полівінілхлорид)'),
    'пвх':                 ('be10ef08d4f42f41065fabbedbb921dc', 'PVC (полівінілхлорид)'),
    'вінілхлорид':         ('be10ef08d4f42f41065fabbedbb921dc', 'PVC (полівінілхлорид)'),
    'вініл':               ('161c20a3e1ce3e30855cce8da204ad98', 'вініл'),
    'скло':                ('476c96bb8b8e87925844f98b5ab74ee8', 'скло'),
    'glass':               ('476c96bb8b8e87925844f98b5ab74ee8', 'скло'),
    'метал':               ('8b5e660fffad73a4d5e5f4b384041dfe', 'метал'),
    'metal':               ('8b5e660fffad73a4d5e5f4b384041dfe', 'метал'),
    'алюміній':            ('8b5e660fffad73a4d5e5f4b384041dfe', 'метал'),
    'нержавіюча сталь':    ('8b5e660fffad73a4d5e5f4b384041dfe', 'метал'),
    'сталь':               ('8b5e660fffad73a4d5e5f4b384041dfe', 'метал'),
    'поліестер':           ('df250c824a8daabedef91dde31b7b69a', 'поліестер'),
    'polycarbonate':       ('d0912b99effd217c41269698e9d71e2d', 'полікарбонат'),
    'полікарбонат':        ('d0912b99effd217c41269698e9d71e2d', 'полікарбонат'),
    'латекс':              ('918c935eacc637e6f2af3ebb9d6542c3', 'латекс'),
    'нейлон':              ('7f2e25e7a0887e92bc6cac4ea8e5ca49', 'нейлон'),
    'nylon':               ('7f2e25e7a0887e92bc6cac4ea8e5ca49', 'нейлон'),
    'тканина':             ('de9da78728b8771e050b3332f862fc94', 'тканина'),
    'текстиль':            ('0bf2113cdcec873ff94a6a9be9c2bd4b', 'текстиль'),
    'сатин':               ('de9da78728b8771e050b3332f862fc94', 'тканина'),
    'шовк':                ('de9da78728b8771e050b3332f862fc94', 'тканина'),
    'silk':                ('de9da78728b8771e050b3332f862fc94', 'тканина'),
    'бавовна':             ('de9da78728b8771e050b3332f862fc94', 'тканина'),
    'cotton':              ('de9da78728b8771e050b3332f862fc94', 'тканина'),
    'екошкіра':            ('8c7c16c10e2d7b8217454c78b79ce323', 'екошкіра'),
    'еко-шкіра':           ('8c7c16c10e2d7b8217454c78b79ce323', 'екошкіра'),
    'натуральна шкіра':    ('7e2af5aab9cd84e01560c7e1cc43f6c8', 'натуральна шкіра'),
    'шкіра':               ('7e2af5aab9cd84e01560c7e1cc43f6c8', 'натуральна шкіра'),
    'leather':             ('7e2af5aab9cd84e01560c7e1cc43f6c8', 'натуральна шкіра'),
    'каучук':              ('f3b2146194dbc5a8931b32586ae400ea', 'каучук'),
    'rubber':              ('f3b2146194dbc5a8931b32586ae400ea', 'каучук'),
    'гума':                ('f3b2146194dbc5a8931b32586ae400ea', 'каучук'),
}

# Категорії з тільки TPR (не мають TPE), і навпаки — тільки TPE
_CAT_TPR_ONLY = {'9466'}
_CAT_TPE_ONLY = {'9480', '9484'}

# Маппінг для Кількість режимів роботи (4212)
MODES_VALUECODE: dict[str, str] = {
    '1': '960f1d94463c02461c34bf5b65f00e0a', '2': 'ade6a163e5fc275f3d7324a8f5147893',
    '3': '0852a7816b4513e81871450d6befe90f', '4': 'c5d521dd5194af6dfcd59df890a8117b',
    '5': 'dc93ecd725ca2d24563df72cd9b4be2a', '6': 'b55ef2a2048836eb2bce9ba57780aa21',
    '7': '8a98a643fa65a3e3e1b0158192948ba0', '8': 'da250f939ed94cb054ce4a5092fb7b58',
    '9': '984bdc1cf741839d7cb8f54d5ebf0a8a', '10': '7ec5829b98c8884fdb45f626bb0ab4f5',
    '11': '740bb4b8d2f618f827c89308441c7672', '12': '1f8c60d0c3f95a0946459a5abcd4b8e1',
    '13': '9f7b7b354233dedc48697e811bb4e7eb', '14': '0a6558ff67bac93d1ef94ade3508acae',
    '15': 'd59ba98274235c01979be49412664b93', '16': 'bd64bce2547c17e37f9ebd8702bba024',
    '18': '1a6601fdc90053720a4f99113a41bb2d', '19': 'cda66953d0e648ad3a4482666752a7fc',
    '20': '4de52f455d5ce2b74a9c690e3cc4e187', '21': 'a0cd6d655bbd3ea4a2ef5bd671363c9c',
    '23': 'd3e81867fab3ea935819f21ca279b6a3', '24': '76533fc7d1466207ea8037b42ba8ab2f',
    '30': '672d64a0182740aebeb8ee33c9b2677c',
}

# ── Тип товару (13948) для 9458 Фетиш та BDSM ──────────────────────────────
# Valuecodes звірені з PIM: attribute-sets/9458/attributes/13948/options
BDSM_TYPE_RULES: list[tuple[str, str, str]] = [
    (r'електростимул',                 'ac425d182d669fa337ae89f088d7414a', 'електростимулятори'),
    (r'розпірк|spreader',              '4c383d5a41b75df954c716bfad04e724', 'розпірка'),
    (r'кляп|ball gag|\bgag\b',         '35b220f73f1db9a37e66db65651c84e5', 'кляп'),
    (r'наручник|handcuff',             '6b9ac6fbb995b98c0f11bdb0b5d455b9', 'наручники'),
    (r'поножі|anklecuff',              '40b5d04620efe63663575a2b5255616e', 'поножі'),
    (r'повід|leash',                   'f1b69bc9e325ebf6a9f47add6ddc1e50', 'повідець'),
    (r'нашийник|\bcollar\b',           '985a8aaba212c9617a107b8e391fa4d8', 'нашийник'),
    (r'чокер|choker',                  'd13f4b4d49e8a15d2c862cd5549420f1', 'чокер'),
    (r'портупе|harness|збруя',         'd3b1441b45c1d6d510538a0dd0661b82', 'портупея/збруя'),
    (r'пов.язка на очі|blindfold',     '1db36a28a0679ea0d595a9bde475b248', "пов'язка на очі"),
    (r'маска',                         '8205d2da696832e1b91235d940046a17', 'маска для обличчя'),
    (r'батіг|флогер|whip|flogger',     'e6e6de9dd99aa4a63f24c9d3d0ee511f', 'батіг/флогер'),
    (r'стек|\bcrop\b',                 '7f4bb02cc3e666aa81143d8d5046a57d', 'стек'),
    (r'паддл|ляпалк|шльопалк|paddle',  'e6af08edf57d25863c561152a9dcd2cb', 'ляпалка/тоуза'),
    (r'затискач|clamp',                'f1972fc2a926191774e9ea33aed47a72', 'затискач для сосків та клітора'),
    (r'мотузк|шибарі|\brope\b',        'a44aca161e27984fb8083c67bf09606f', 'мотузка бандажна'),
    (r'лоскіт|тиклер|tickler',         '4afb496ad33f1a33addbd028f485ddac', 'лоскоталка'),
    (r'колесо вартенберга|pinwheel',   '49cd3cf786fcb65ac7ed7a9904c79269', 'колесо вартенберга'),
    (r'анальний гак|anal hook',        'e5299e794e7f73c9e7c7622eb062ca52', 'анальний гак'),
    (r'уретральн',                     'a0f69b23235b56731a27abc7dda2f8d3', 'уретральні вставки'),
    (r'пояс вірності|chastity',        'ac9e8a36d5c6d152c7ab644bb9c08544', 'пояс вірності'),
    (r'фіксатор|бандаж|restraint|хрестовин|hog.?tie',
                                       '2fd3ff25d120b88dc12050794a97f39c', 'бандаж/фіксатор'),
    (r'меблі|sling|гойдалк',           '20b927288b7b60b683805a11fb531c5b', 'меблі для сексу'),
    (r'свічк',                         '21af507d88ac063c5d10bf0f24296ad9', 'свічки низькотемпературні'),
]
BDSM_TYPE_DEFAULT = ('a1142b235b279ca1b7b54a5f79d586ea', 'набір речей')

# Конструкція (13037) для 9480 Фалоімітатори
DILDO_CONSTRUCTION_RULES: list[tuple[str, str, str]] = [
    (r'двосторон|double dong|double do\b|two cocks',
                       '2860864ebd558e70cb142e9729576086', 'двосторонні'),
    (r'подвійн|double|подвійного проникнення',
                       '0fba418bedb2dbb9ca04d9e368d434cb', 'подвійні'),
    (r'з мошонкою|with balls|мошонк',
                       'e42be680e4fce1db661201e4a19ee163', 'з мошонкою'),
]
DILDO_CONSTRUCTION_DEFAULT = ('8d32bd5d1a1f4bd8f7527e748f7df76d', 'односторонні')

# Тип товару (13948) для 9484 Анальні пробки
PLUG_TYPE_RULES: list[tuple[str, str, str]] = [
    (r'набір|\bset\b|kit',        '085b4d2de7b7959b32194f2fe97ea806', 'набір'),
    (r'розширювач|dilator',       '19f43b6db2c945621d1bbf4160755a2e', 'анальний розширювач'),
    (r'душ|douche|enema',         'cda234f155b08983cdd8039c8231970f', 'анальний душ'),
    (r'ялинк|beads|ялинка',       '21045a0b4f280f281560ed2b2cb29d4e', 'анальна пробка-ялинка'),
    (r'тунель|tunnel|hollow',     '99ec19f29f58b1741074b5ae693cf702', 'анальний тунель'),
    (r'фістинг|fisting',          '0f9ce3349647beb6f3401849e44d46a8', 'іграшки для фістингу'),
    (r'смарт|smart|додаток|\bapp\b', '7661e625d2b5b92869c8c9534e0814c2', 'анальна смарт-пробка'),
]
PLUG_TYPE_DEFAULT = ('f48421e09fd29eea23eaa68bd3ea5ce6', 'класична анальна пробка')

# Форма (12891) для 9484 Анальні пробки
PLUG_SHAPE_DEFAULT = ('6dd869b40143c4d29474658156fe15d8', 'класична конусна')


# ── Універсальні дефолти обов'язкових атрибутів по категоріях ──────────────
# Формат: cat_code → [(attr_code, attr_name, [(regex, valuecode, display)], default)]
# Правила перевіряються по назві товару, перший збіг виграє; якщо жодне не
# спрацювало — береться default. Усі valuecodes звірені з PIM.
CATEGORY_ATTR_DEFAULTS: dict[str, list] = {
    '9466': [
        ('3103', 'Тип приладу', [
            (r'кролик|rabbit',        '10b744fc450b41eee20339bb9cc81591', 'вібратор-кролик'),
            (r'віброяйц|egg',         '6f1521062d0bbce3a0427bb8c87c4bd9', 'віброяйця'),
            (r'віброкул|bullet',      '675745be6eca3a513a24eec02744ff17', 'віброкулі'),
            (r'для пар|couple',       'ee2bfc875647653c3a86e52c02c44793', 'вібратор для пар'),
            (r'набір|\bset\b|kit',    '28b7fb2873e7f42393d50eaaef086cee', 'набір приладів'),
            (r'міні|mini',            'ca5ff945a7fb475808ad8995b2d34ec0', 'міні-вібратор'),
        ], ('56c84cae1d1a2c5f5a13a97e5dc08f93', 'нестандартний вібратор')),
        ('3106', 'Вид', [
            (r'реалістич|realistic',  'fec4f80a1e018a6dab1eb0827d51745c', 'реалістичні'),
        ], ('5ccb1599b2d64697e938d9dba03a6de0', 'нереалістичні')),
        ('3369', 'Призначення', [
            (r'анальн',               '52abbc42ff3aa782532d7772cc080248', 'анальні'),
            (r'клітор',               'f0398e75966a489d608a8ea1770a2638', 'кліторні'),
        ], ('5fa1044eac4a17aea732a14f610c915b', 'вагінальні')),
        ('13037', 'Конструкція', [], ('8d32bd5d1a1f4bd8f7527e748f7df76d', 'односторонні')),
    ],
    '9470': [
        ('9695', 'Тип', [
            (r'набір|\bset\b|kit',    '27e826161d9625f69453963c5202b257', 'набір'),
        ], ('5e54c648c3fef9b78719eccac963f0f6', 'кільце')),
        ('9698', 'Текстура поверхні', [
            (r'рельєф|ребр|textur',   'a77f5bc4b6ae1e0d9ccecb5e8adc11e2', 'з рельєфом'),
        ], ('0094a04f4321daee94111dda8b152396', 'гладка')),
    ],
    '9472': [
        ('3106', 'Вид', [
            (r'реалістич|realistic|зі зліпка', 'fec4f80a1e018a6dab1eb0827d51745c', 'реалістичні'),
        ], ('5ccb1599b2d64697e938d9dba03a6de0', 'нереалістичні')),
    ],
    '9476': [
        ('3369', 'Призначення', [
            (r'вульв|клітор|вагін',   '97dd299c4bb7b66f4d7ace76a9efe464', 'для стимуляції вульви'),
            (r'ерекц',                'ce5d7b6ce5d8db888c530783868852f1', 'для покращення ерекції'),
        ], ('41e42da18100c9346f99630a37c8471a', 'для тренування')),
        ('5249', 'Тип помпи', [
            (r'автоматичн|електричн|automatic', '83a176bd806d7459c8ed6b69479a6cec', 'автоматична (електрична)'),
        ], ('58d2f532e79f09a39bfc76c250b4e4f6', 'ручна')),
    ],
    '9526': [
        ('14746', 'Тип аксесуара', [], ('e03456dd90ea3d00b2ff8ef4599ccd7d', 'чохол для зберігання')),
    ],
    '9468': [
        ('6151', 'Стать ляльки', [
            (r'\bmale\b|чоловіч',     '17be150f785456064909af49f6adc9a4', 'чоловіча'),
        ], ('94764ca42ce35e998df6226ff4706a84', 'жіноча')),
        ('6303', 'Тип ляльки', [
            (r'торс|torso',           'f49bc54e184a3395e79686b53ded32dc', 'торс'),
        ], ('002568ed73679bcbb17e2e12157a3a85', 'тіло повністю')),
        ('5262', 'Колір волосся', [], ('8add402e4714937a9d55942c21e8dd48', 'без волосся')),
        ('5414', 'Тип фігури', [], ('4b744e43b7254c48283119dc2b904869', 'середня')),
        ('6092', 'Позиція тіла', [], ('d7046f943855e86277ac395a413fcd1e', 'лежача')),
    ],
}


# ── Презервативи (3275, гілка Медичні товари → Домашня аптека) ─────────────
# Категорія відкрита для маркетплейс-продавців: на вітрині є картки з
# префіксом mplc- від сторонніх продавців, вимог щодо ліцензії немає.
CONDOM_MATERIAL = [
    (r'безлатекс|non.?latex|поліізопрен|polyisoprene|\bskyn\b',
                            '1f41890b00e3e9aa97a73705999af0d3', 'поліізопрен'),
]
CONDOM_MATERIAL_DEFAULT = ('d47b6f71a8365dfb4e5d28d078117ea6', 'латекс')
CONDOM_TEXTURE = [
    (r'(пухирц|крапк|точков|dotted).{0,25}(ребр|ribbed)|(ребр|ribbed).{0,25}(пухирц|крапк|dotted)',
                            '25db7847660c7f00dcd94ef97d63b00a', 'комбіновані'),
    (r'пухирц|крапк|точков|dotted|studs',
                            '90e91f3a5163e9a19e48c205314dbebc', 'з крапками'),
    (r'ребр|ribbed|спіраль',  '1faf26e7eac0040c0bf07f306fd24e6e', 'ребристі'),
]
CONDOM_TEXTURE_DEFAULT = ('810c44f4b48b48174d9605d56a7c574d', 'гладкі')
# ширина в мм → розмірна градація Єпіцентру
CONDOM_SIZE_BANDS = [
    (0,  47, 'ee8d7eda1399fadfe2fa64be984cc81a', 'XS (44-47 мм)'),
    (47, 51, '4ca1446453d1c1b550efca9671838327', 'S (47-50 мм)'),
    (51, 55, '9d7de7eb26c93d968b039e1b56162ca2', 'M (51-54 мм)'),
    (55, 59, '14daa1955a1cbbcdfaaebce48ccbb000', 'L (55-58 мм)'),
    (59, 65, 'a0112f429c16a4aea7ab3fea2c6b446b', 'XL (59-64 мм)'),
    (65, 999,'0a23443d279739ac5252e4c336627be7', 'XXL (65+ мм)'),
]
CONDOM_SIZE_DEFAULT = ('9d7de7eb26c93d968b039e1b56162ca2', 'M (51-54 мм)')


# ── Точкові виправлення категорії для окремих SKU ──────────────────────────
# Використовується там, де САМА sexopt-категорія змаплена правильно, але
# постачальник поклав у неї товар іншого типу. Виправляти маппінг категорії
# тут не можна — постраждають решта товарів. Тому перевизначаємо адресно.
SKU_CATEGORY_OVERRIDE: dict[str, str] = {
    # набори фіксації, покладені в «Пробки, плаги» (4803 → 9484)
    'SX2844': '9458',   # Bed Restraint set
    'SX2845': '9458',   # Doggy Style Saddle set
    'SX2846': '9458',   # Forced Nadu pose correction set
    'SX2847': '9458',   # Door Swing & Leg Spreader Bondage set
    # анальні пробки в «Стимуляторах з ерекційним кільцем» (6461 → 9470)
    'SX3713': '9484',   # Fun Factory Bootie Vibe Bottle Green
    'SX3714': '9484',   # Fun Factory Bootie Vibe Black
    # фіксатори у «Меблях для сексу» (4793 → 9578): це спорядження, не меблі.
    # Самі меблі (гойдалки, лава, клітка, хрест, крісла) лишаються в 9578.
    'SX3911': '9458',   # Rosy Gold Under-Mattress Restraint Set
    'SO3743': '9458',   # Fetish Tentation Ankle and Wrist Straps
    'SO5149': '9458',   # Art of Sex BDSM Stretching Love
    'SO5157': '9458',   # Art of Sex No pain - No game
    'SO5181': '9458',   # Art of Sex Hand Cuffs For Suspension
    'SO5182': '9458',   # Art of Sex Leg Cuffs For Suspension
    'SO5183': '9458',   # Art of Sex Kinky Hand Cuffs For Suspension
    'SO8810': '9458',   # Bedroom Fantasies Under the bed
    'SO9511': '9458',   # Liebe Seele Temptation Underbed Restraint
    'SO9796': '9458',   # Art of Sex BDSM Slave Game
    'SX0856': '9458',   # LOCKINK Adjustable Bed Restraint Kit
    'SX1182': '9458',   # Master Series Interlace Bed Restraint Set
    # чохли та засоби чищення в «Аксесуарах для помп» (4848 → 9476):
    # це не помпова оснастка, а зберігання й догляд
    'BM-080': '9526',   # чохол Bathmate Hercules
    'BM-081': '9526',   # чохол Bathmate Goliath
    'BM-230': '9526',   # набір для чищення та зберігання
    'BSH-02': '9526',   # щітка для чищення
    'SX3931': '9526',   # Bathmate Cleaning Kit
}


# ── Дефолти Матеріал (12731), коли матеріал не витягнуто з назви ────────────
# Valuecodes звірені з PIM API: attribute-sets/<cat>/attributes/12731/options.
# Набір валідних опцій відрізняється між категоріями (напр. у 9466 немає TPE,
# у 9460 немає воску), тому дефолт задається окремо для кожної.
_M_SILICONE = ('063a479f96ed369ac655b2d6e90f216b', 'силікон')
_M_TPE      = ('36ead368e43d489285c7031a730ff31d', 'TPE (термопластичний еластомер)')
_M_ECOLEATH = ('8c7c16c10e2d7b8217454c78b79ce323', 'екошкіра')
_M_METAL    = ('8b5e660fffad73a4d5e5f4b384041dfe', 'метал')
_M_SOAP     = ('85ac300f0bf24900aae2893e431af259', 'мило')
_M_WOOD     = ('6421a1cec2caed62717db94aa1c85bc3', 'дерево')
_M_CARDB    = ('ae8443faf516d307fd997bb004bbaf79', 'картон')
_M_PAPER    = ('cde2abe54cadbbc0751a3db0d57a3b29', 'папір')
_M_FABRIC   = ('de9da78728b8771e050b3332f862fc94', 'тканина')

# cat_code → ([(regex по назві, значення)], значення_за_замовчуванням)
# значення None → атрибут свідомо не проставляється (валідної опції немає)
MATERIAL_DEFAULT_BY_CAT: dict[str, tuple[list, tuple | None]] = {
    '9466': ([], _M_SILICONE),   # Вібратори
    '9480': ([], _M_SILICONE),   # Фалоімітатори
    '9470': ([], _M_SILICONE),   # Ерекційні кільця
    '9478': ([], _M_SILICONE),   # Вагінальні кульки та тренажери
    '9482': ([], _M_SILICONE),   # Страпони
    '9484': ([], _M_SILICONE),   # Анальні пробки
    '9488': ([], _M_SILICONE),   # Масажери простати
    '9472': ([], _M_TPE),        # Мастурбатори (Kokos та ін. — TPE)
    '9474': ([], _M_TPE),        # Насадки на член
    '9458': ([                   # Фетиш та BDSM — переважно екошкіра
        (r'кляп|gag|пробк|дилдо|dildo', _M_SILICONE),
        (r'наручник|ланцюг|метал|steel|сталь', _M_METAL),
    ], _M_ECOLEATH),
    '9460': ([                   # Еротичні приколи та сувеніри — різнорідні
        (r'свічк|віск|candle', None),        # воску немає серед опцій 9460
        (r'мило|soap', _M_SOAP),
        (r"дерев|кубик", _M_WOOD),
        (r'книж|книг|блокнот|плакат|чек', _M_PAPER),
        (r'\bгра\b|гра |карт|лото|фант|квест', _M_CARDB),
        (r'брелок', _M_METAL),
        (r'пестіс|наклейк|стікер', _M_FABRIC),
    ], _M_CARDB),
}

# Категорії-розхідники, де атрибута «Матеріал» немає в наборі взагалі
# (звірено з epicentr_required_attrs_sexopt: жодна з них не має 12731/14747)
MATERIAL_FORBIDDEN_CATS = {'9448', '9450', '9452', '9628', '9630', '9632', '9636'}

# Категорії, де обов'язковий не «Матеріал», а «Основний матеріал» з іншим кодом
# cat_code → (attr_code, valuecode, display)
MAIN_MATERIAL_DEFAULT: dict[str, tuple[str, str, str]] = {
    '9526': ('14747', 'b5abe45f44d750029852164815558b26', 'силікон'),
    '9616': ('15304', '66eaee105a13fcd2faeb5c257c8dc2c0', 'силікон'),
    '9620': ('15300', 'ca0fea973c6bfd249898958eda0fc533', 'силікон'),
}

# Маппінг для Тип живлення (11098)
POWER_VALUECODE: dict[str, tuple[str, str]] = {
    'USB':             ('8294dba5410453cfcee202a5b467449c', 'акумулятор'),
    'акумулятор':      ('8294dba5410453cfcee202a5b467449c', 'акумулятор'),
    'Батарейки ААА':   ('32b22e808e7a51fd9cbf96ba38b35abe', 'одноразові батарейки'),
    'Батарейки АА':    ('32b22e808e7a51fd9cbf96ba38b35abe', 'одноразові батарейки'),
    'Батарейки LR44':  ('32b22e808e7a51fd9cbf96ba38b35abe', 'одноразові батарейки'),
    'батарейки':       ('32b22e808e7a51fd9cbf96ba38b35abe', 'одноразові батарейки'),
}


# ── Хелпери ──────────────────────────────────────────────────────────────────

def escape_xml(text) -> str:
    s = str(text) if text is not None else ''
    return (s
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&apos;'))


def calc_sell_price(retail: float, cat_code: str) -> float:
    """Ціна продажу = ціна постачальника × MARKUP, gross-up на комісію Єпіцентру, округлення вгору до 10 грн."""
    comm = EPICENTR_COMMISSION.get(cat_code, DEFAULT_COMMISSION)
    return math.ceil(retail * MARKUP / (1 - comm / 100) / 10) * 10


# Різне написання тієї самої країни в даних постачальника → назва в довіднику
COUNTRY_ALIASES: dict[str, str] = {
    'великобританія':  'велика британія',
    'великобритания':  'велика британія',
    'англія':          'велика британія',
    'uk':              'велика британія',
    'корея':           'південна корея',
    'south korea':     'південна корея',
    'usa':             'сша',
    'us':              'сша',
    'china':           'китай',
    'ukraine':         'україна',
    'germany':         'німеччина',
    'poland':          'польща',
    'spain':           'іспанія',
    'france':          'франція',
    'italy':           'італія',
    'japan':           'японія',
    'canada':          'канада',
    'netherlands':     'нідерланди',
    'czech':           'чехія',
    'israel':          'ізраїль',
    'austria':         'австрія',

    # нідерландські назви (джерело EasyToys, поле Herkomst)
    'china'                           : 'китай',
    'duitsland'                       : 'німеччина',
    'spanje'                          : 'іспанія',
    'japan'                           : 'японія',
    'taiwan'                          : 'тайвань',
    'portugal'                        : 'португалія',
    'mexico'                          : 'мексика',
    'frankrijk'                       : 'франція',
    'italie'                          : 'італія',
    'italië'                          : 'італія',
    'polen'                           : 'польща',
    'nederland'                       : 'нідерланди',
    'verenigde staten'                : 'сша',
    'verenigde staten van amerika'    : 'сша',
    'vs'                              : 'сша',
    'verenigd koninkrijk'             : 'велика британія',
    'groot-brittannie'                : 'велика британія',
    'groot-brittannië'                : 'велика британія',
    'engeland'                        : 'велика британія',
    'zuid-korea'                      : 'південна корея',
    'zuid korea'                      : 'південна корея',
    'maleisie'                        : 'малайзія',
    'maleisië'                        : 'малайзія',
    'thailand'                        : 'таїланд',
    'vietnam'                         : "в'єтнам",
    'denemarken'                      : 'данія',
    'canada'                          : 'канада',
    'zweden'                          : 'швеція',
    'oostenrijk'                      : 'австрія',
    'tsjechie'                        : 'чехія',
    'tsjechië'                        : 'чехія',
    'israel'                          : 'ізраїль',
    'israël'                          : 'ізраїль',
    'india'                           : 'індія',
    'indonesie'                       : 'індонезія',
    'indonesië'                       : 'індонезія',
    'turkije'                         : 'туреччина',
    'hongarije'                       : 'угорщина',
    'litouwen'                        : 'литва',
    'letland'                         : 'латвія',
    'roemenie'                        : 'румунія',
    'roemenië'                        : 'румунія',
    'bulgarije'                       : 'болгарія',
    'brazilie'                        : 'бразилія',
    'brazilië'                        : 'бразилія',
    'oekraine'                        : 'україна',
    'oekraïne'                        : 'україна',
    'zwitserland'                     : 'швейцарія',
    'belgie'                          : 'бельгія',
    'belgië'                          : 'бельгія',
    'finland'                         : 'фінляндія',
    'noorwegen'                       : 'норвегія',
    'ierland'                         : 'ірландія',
    'griekenland'                     : 'греція',
    'slowakije'                       : 'словаччина',
    'slovenie'                        : 'словенія',
    'slovenië'                        : 'словенія',
    'estland'                         : 'естонія',
    'hongkong'                        : 'гонконг',
    'hong kong'                       : 'гонконг',
    'pakistan'                        : 'пакистан',
    'luxemburg'                       : 'люксембург',
}


# Бренди, для яких країна виробництва документально підтверджена на
# офіційному сайті. Застосовується ТІЛЬКИ якщо постачальник не вказав країну.
# Не додавати бренд без прямого "made in"/"manufactured in" від виробника —
# "British brand"/"Swedish design"/"founded in" підтвердженням НЕ є.
BRAND_COUNTRY_OVERRIDE: dict[str, str] = {
    # sensuva.com/about-sensuva: "hand-crafted in the USA",
    # власне виробництво Valencia Naturals, Chatsworth CA (перевірено 2026-07-27)
    'sensuva': 'США',
}


def _norm_country(s: str) -> str:
    """Нормалізація назви: регістр, апострофи, HTML-сутності, пробіли."""
    s = unescape(s or '')
    s = s.replace('’', "'").replace('ʼ', "'").replace('`', "'").replace('´', "'")
    return re.sub(r'\s+', ' ', s).strip().lower()


def country_code(country_name: str | None,
                 country_map: dict[str, str] | None = None) -> str | None:
    """Назва країни → valuecode з довідника Єпіцентру (country_of_origin).

    Повертає None, якщо країну не розпізнано. Fallback на 'ukr' навмисно
    прибрано: краще не вказати країну взагалі, ніж заявити українське
    походження для імпортного товару. Виклик логує SKU і пропускає тег.
    """
    if not country_name or not country_map:
        return None
    key = _norm_country(country_name.split('(')[0])
    if key in country_map:
        return country_map[key]
    alias = COUNTRY_ALIASES.get(key)
    if alias and alias in country_map:
        return country_map[alias]
    return None


def load_country_lookup(conn) -> dict[str, str]:
    """sku → назва країни, знайдена на зовнішньому джерелі (EasyToys).

    Береться ЛИШЕ match_type='exact' — точний збіг моделі. Частковий збіг
    ("той самий бренд, інша модель" чи "той самий гель, інший смак")
    свідомо не використовується.
    """
    try:
        cur = conn.cursor()
        cur.execute("SELECT sku, herkomst FROM sexopt_country_lookup "
                    "WHERE match_type = 'exact' AND herkomst IS NOT NULL "
                    "AND TRIM(herkomst) <> ''")
        result = {r['sku']: r['herkomst'].strip() for r in cur.fetchall()}
        cur.close()
        return result
    except Exception as e:
        conn.rollback()
        logger.warning(f"sexopt_country_lookup недоступна ({e})")
        return {}


# ── Оціночні дефолти країни (НЕ факт, а припущення) ────────────────────────
# Застосовуються ОСТАННІМИ, лише коли немає ні даних постачальника, ні
# точного збігу EasyToys, ні документованого бренд-override.
# Політика задана нижче: для брендів із зібраними доказами — своя країна,
# для решти — галузевий дефолт.
# Кожне значення пишеться в sexopt_country_lookup з source='estimated_default',
# тому вибирається й прибирається одним запитом:
#   DELETE FROM sexopt_country_lookup WHERE source = 'estimated_default';
COUNTRY_DEFAULT_FALLBACK: dict[str, str] = {
    'doc johnson': 'Мексика',    # підтвердження постачальника
    'tenga':       'Японія',     # ISO 9001, виробничий підрозділ у Японії
    'mystim':      'Німеччина',  # завод у Мембрісі; Herkomst=Duitsland на картці EasyToys
    '*':           'Китай',      # галузевий дефолт
}


def load_country_estimated(conn) -> dict[str, str]:
    """sku → оціночна країна (source='estimated_default').

    Свідомо тримається окремо від load_country_lookup(), який віддає лише
    точні збіги. Змішувати їх не можна: там факт, тут припущення.
    """
    try:
        cur = conn.cursor()
        cur.execute("SELECT sku, herkomst FROM sexopt_country_lookup "
                    "WHERE source = 'estimated_default' "
                    "AND herkomst IS NOT NULL AND TRIM(herkomst) <> ''")
        result = {r['sku']: r['herkomst'].strip() for r in cur.fetchall()}
        cur.close()
        return result
    except Exception as e:
        conn.rollback()
        logger.warning(f"оціночні країни недоступні ({e})")
        return {}


def load_country_map(conn) -> dict[str, str]:
    """нормалізована назва країни → valuecode.

    Джерело — довідник Єпіцентру, вивантажений з PIM API
    (/v2/pim/attribute-sets/<any>/attributes/country_of_origin/options)
    і закешований у epicentr_attr_options з attr_code='country_of_origin'.
    """
    try:
        cur = conn.cursor()
        cur.execute("SELECT valuecode, name_ua FROM epicentr_attr_options "
                    "WHERE attr_code = 'country_of_origin'")
        result = {_norm_country(r['name_ua']): r['valuecode']
                  for r in cur.fetchall()}
        cur.close()
        return result
    except Exception as e:
        conn.rollback()
        logger.error(f"Довідник країн недоступний ({e}) — "
                     f"country_of_origin не буде проставлено")
        return {}


# ── Завантаження довідників з БД ─────────────────────────────────────────────

def load_category_mapping(cur) -> dict[str, tuple[str, str]]:
    """sexopt_category_id → (epicentr_category_code, epicentr_category_name)"""
    cur.execute('''
        SELECT m.sexopt_category_id, m.epicentr_category_code, e.name_ua
        FROM epicentr_category_mapping m
        JOIN epicentr_intimate_categories e ON e.code = m.epicentr_category_code
        WHERE COALESCE(m.confidence, 1) > 0
    ''')
    return {r['sexopt_category_id']: (r['epicentr_category_code'], r['name_ua'])
            for r in cur.fetchall()}


def load_dimensions(cur) -> dict[str, dict]:
    """epicentr_category_code → {weight_g, width_mm, height_mm, length_mm, source}"""
    cur.execute('SELECT * FROM epicentr_default_dimensions')
    return {r['epicentr_category_code']: dict(r) for r in cur.fetchall()}


def load_extracted_params(conn) -> dict[str, dict[str, tuple[str, str]]]:
    """
    SKU → {param_name: (param_code, param_value)}

    Пріоритет: classification_regex > regex_description (не перезаписуємо кращий джерело).
    param_code для class. params — це valuecode (UUID з epicentr_attr_options).
    param_code для regex params — це код атрибуту Єпіцентру (напр. '12731').
    """
    source_priority = {'classification_regex': 1, 'regex_description': 2}
    cur = conn.cursor()
    cur.execute("""
        SELECT sku, param_name, param_code, param_value, source
        FROM sexopt_extracted_params
        ORDER BY sku, id
    """)
    result: dict[str, dict[str, tuple[str, str, str]]] = {}
    for r in cur.fetchall():
        sku, name = r['sku'], r['param_name']
        prio = source_priority.get(r['source'], 9)
        if sku not in result:
            result[sku] = {}
        existing = result[sku].get(name)
        if existing is None or source_priority.get(existing[2], 9) > prio:
            result[sku][name] = (r['param_code'] or '', r['param_value'], r['source'])
    cur.close()
    # strip source from final value
    return {sku: {nm: (code, val) for nm, (code, val, _) in params.items()}
            for sku, params in result.items()}


# Відображення param_name → epicentr_attribute_code для select-атрибутів
# Ці коди використовуються в paramcode="" для regex-extracted params
PARAM_ATTR_CODES: dict[str, str] = {
    'Матеріал':                           '12731',
    'Водонепроникний':                    '11953',
    'Підігрів':                           '10173',
    'Вібрація':                           '11579',
    'Кількість режимів роботи':           '4212',
    'Кілька насадок':                     '9977',
    'Телескопічний':                      '11367',
    'Кріплення на присоску':              '11988',
    'Керування через застосунок':         '10210',
    'Тип живлення':                       '11098',
    'Розмір':                             '12923',
    'Довжина (мм)':                       '12734',
    'Діаметр (мм)':                       '12736',
    'Колір':                              '12730',
    # classification attrs: param_code вже є valuecode, paramcode = attr_code
    'Тип приладу':                        '3103',
    'Вид':                                '3106',
    'Призначення':                        '3369',
    'Конструкція':                        '13037',
    'Форма':                              '12891',
    'Тип товару':                         '13948',
    # New bool attrs (UUID-based)
    'Манометр':                           '4801',
    'Вакуумна стимуляція':                '4758',
    'Знімний фалос':                      '4592',
    'Регульовані ремені':                 '4700',
    'Ротація':                            '4738',
    'Регулювання діаметра':               '7267',
    # New bool attrs (yes/no string valuecodes)
    'Зігріваючий':                        '15745',
    'Охолоджуючий':                       '15746',
    'Розслаблюючий':                      '15747',
    'Тонізуючий':                         '15748',
    'Збуджуючий':                         '15749',
    'Зволожуючий':                        '15750',
    "Пом'якшуючий":                       '15752',
    'Антистресовий':                      '15753',
    'Їстівна формула':                    '15754',
    'Органічний продукт':                 '15755',
    'Без парабенів':                      '15756',
    'Без гліцерину':                      '15757',
    'Без ароматизаторів':                 '15758',
    'З феромонами':                       '15759',
    'Посилення чутливості':               '15768',
    'Посилення слиновиділення':           '15769',
    'Віброефект':                         '15770',
    'Сумісність з презервативами':        '15771',
    'Сумісність з секс-іграшками':        '15772',
    'Веганський':                         '15773',
    # New classification attrs
    'Тип помпи':                          '5249',
    'Тип кріплення':                      '437',
    'Стать':                              '15743',
    'Смак':                               '15765',
    'Аромат':                             '15766',
    'Тип воску':                          '15762',
    'Тип упаковки':                       '15774',
    'Тип аксесуара':                      '14746',
    'Тип аксесуару':                      '14746',
    'Час горіння':                        '15761',
    # 9636 prolonger bool attrs (yes/no)
    'Посилення ерекції':                  '15784',
    'Подовження статевого акту':          '15785',
    # 9448 toy care classification attrs
    'Тип засобу':                         '14024',
    'Дія':                                '14036',
    # 9636 prolonger classification attrs
    'Основа засобу':                      '15764',
    # 9578 sex furniture classification attrs
    'Основний матеріал (9578)':           '15720',
    # 9550 anal douche bools
    'Водонепроникність':                  '14209',
    'Регулювання тиску води':             '14813',
    'Регулювання потоку':                 '14817',
    'Знімний наконечник':                 '14822',
    'Гнучкий шланг':                      '14823',
    # 9548 anal expander bools
    'З можливістю накачування':           '14800',
    'Можна використовувати у воді':       '14801',
    'Наявність шийки':                    '14802',
    'Пульт керування':                    '14803',
    'Мобільний додаток':                  '14804',
    'Без фталатів':                       '14805',
    # 9548 classification attrs
    'Рівень жорсткості':                  '11932',
    'Формат продажу':                     '14796',
    'Матеріал покриття':                  '14797',
    # 9550 anal douche classification attrs
    'Тип анального душу':                 '14806',
    'Тип використання':                   '14807',
    'Тип підключення':                    '14808',
    'Тип наконечника':                    '14810',
    'Матеріал наконечника':               '13008',
    'Матеріал шланга':                    '2839',
    # Conflicting names (resolved via CAT_PARAM_ATTR_CODE)
    'Тип':                                '7215',
    'Текстура поверхні':                  '7192',
}

# (cat_code, param_name) → attribute_code for <param paramcode="...">
CAT_PARAM_ATTR_CODE: dict[tuple[str, str], str] = {
    ('9466', 'Тип приладу'):      '3103',
    ('9482', 'Тип приладу'):      '3103',
    ('9466', 'Вид'):              '3106',
    ('9472', 'Вид'):              '3106',
    ('9480', 'Вид'):              '13039',
    ('9482', 'Вид'):              '13039',
    ('9474', 'Вид'):              '13039',
    ('9466', 'Призначення'):      '3369',
    ('9476', 'Призначення'):      '3369',
    ('9470', 'Призначення'):      '3369',
    ('9466', 'Конструкція'):      '13037',
    ('9480', 'Конструкція'):      '13037',
    ('9482', 'Конструкція'):      '13037',
    ('9474', 'Конструкція'):      '13037',
    ('9470', 'Конструкція'):      '13037',
    ('9484', 'Форма'):            '12891',
    ('7216', 'Тип товару'):       '13948',
    ('9458', 'Тип товару'):       '13948',
    ('9484', 'Тип товару'):       '13948',
    ('9460', 'Тип товару'):       '13948',
    ('9478', 'Тип товару'):       '13954',
    ('7216', 'Призначення'):      '13949',
    ('9476', 'Тип помпи'):        '5249',
    ('9482', 'Тип кріплення'):    '437',
    ('9474', 'Тип'):              '7215',
    ('9474', 'Текстура поверхні'):'7192',
    ('9470', 'Тип'):              '9695',
    ('9470', 'Текстура поверхні'):'9698',
    ('9526', 'Тип аксесуара'):    '14746',
    ('9616', 'Тип аксесуару'):    '15302',
    ('9620', 'Тип аксесуару'):    '15298',
    ('9628', 'Стать'):            '15743',
    ('9630', 'Стать'):            '15743',
    ('9632', 'Стать'):            '15743',
    ('9628', 'Тип'):              '15763',
    ('9628', 'Смак'):             '15765',
    ('9628', 'Аромат'):           '15766',
    ('9630', 'Аромат'):           '15744',
    ('9632', 'Аромат'):           '15744',
    ('9630', 'Тип воску'):        '15762',
    ('9630', 'Час горіння'):      '15761',
    ('9628', 'Тип упаковки'):     '15774',
    ('9526', 'Колір'):            '2845',
    # 9448 toy care
    ('9448', 'Тип засобу'):       '14024',
    ('9448', 'Дія'):              '14036',
    # 9636 prolonger
    ('9636', 'Тип'):              '15780',
    ('9636', 'Основа засобу'):    '15764',
    # 9578 sex furniture
    ('9578', 'Тип'):              '15719',
    ('9578', 'Основний матеріал'): '15720',
    # 9550 anal douche
    ('9550', 'Тип анального душу'): '14806',
    ('9550', 'Тип використання'):  '14807',
    ('9550', 'Тип підключення'):   '14808',
    ('9550', 'Тип наконечника'):   '14810',
    ('9550', 'Матеріал наконечника'): '13008',
    ('9550', 'Матеріал шланга'):   '2839',
    ('9550', 'Призначення'):       '3369',
    # 9548 anal expander
    ('9548', 'Рівень жорсткості'):  '11932',
    ('9548', 'Призначення'):        '14795',
    ('9548', 'Формат продажу'):     '14796',
    ('9548', 'Матеріал покриття'):  '14797',
    ('9548', 'Текстура поверхні'):  '14798',
    ('9548', 'Форма'):              '5358',
    ('9548', 'Діаметр (мм)'):       '1892',  # redirect to Максимальний діаметр
}

# Valuecodes для Базовий колір (12097) у 9630 → mapped from extracted color name
CANDLE_COLOR_VALUECODE: dict[str, tuple[str, str]] = {
    'чорний':       ('3ec160321d45b95cf3a540ad3a2bf896', 'чорний'),
    'білий':        ('cb8a8dc6861023bc621f964a491c94d4', 'білий'),
    'рожевий':      ('af5820f4d82201e791b5ec6b99869faf', 'рожевий'),
    'фіолетовий':   ('57d9544692d9901c663d9372664e0288', 'фіолетовий'),
    'червоний':     ('c0ac579117df213cfe2a942ace8f1eca', 'червоний'),
    'синій':        ('7474159555fd1f85a1773df29241afbb', 'синій'),
    'прозорий':     ('b633f5f7a9520a741a27545590361885', 'прозорий'),
    'золотий':      ('19065f9e37ca53ebf067c60a7881edcc', 'золото'),
    'срібний':      ('cda97fb08eda186db32c35530a77c169', 'срібло'),
    'бежевий':      ('09a334800e7d6ccc7d54827f16cf4df2', 'бежевий'),
    'тілесний':     ('09a334800e7d6ccc7d54827f16cf4df2', 'бежевий'),
    'бірюзовий':    ('a44a75b549f8063e80bb51dbb0b04cf0', 'бірюзовий'),
    'оранжевий':    ('0820c9c4601c3f21afd927638b26c101', 'помаранчевий'),
    'помаранчевий': ('0820c9c4601c3f21afd927638b26c101', 'помаранчевий'),
    'зелений':      ('4f06e3a687481542b424687ecf8d0e8e', 'зелений'),
    'коричневий':   ('2e96b43de658554c4bcc7b6edae777c2', 'коричневий'),
    'сірий':        ('59474de51f852', 'сірий'),
}

# Fallback для classification attrs без категорії в CAT_PARAM_ATTR_CODE
CLASSIFICATION_ATTR_CODES: dict[str, str] = {
    'Тип приладу':     '3103',
    'Вид':             '3106',
    'Призначення':     '3369',
    'Конструкція':     '13037',
    'Форма':           '12891',
    'Тип товару':      '13948',
    'Тип помпи':       '5249',
    'Тип кріплення':   '437',
    'Тип':             '7215',
    'Текстура поверхні': '7192',
    'Тип аксесуара':   '14746',
    'Тип аксесуару':   '14746',
    'Час горіння':     '15761',
    'Стать':           '15743',
    'Смак':            '15765',
    'Аромат':          '15766',
    'Тип воску':       '15762',
    'Тип упаковки':    '15774',
    'Тип засобу':              '14024',
    'Дія':                     '14036',
    'Основа засобу':           '15764',
    'Тип анального душу':      '14806',
    'Тип використання':        '14807',
    'Тип підключення':         '14808',
    'Тип наконечника':         '14810',
    'Матеріал наконечника':    '13008',
    'Матеріал шланга':         '2839',
    'Рівень жорсткості':       '11932',
    'Формат продажу':          '14796',
    'Матеріал покриття':       '14797',
}

# Маппінг матеріал → (attr_code, {key: (valuecode, display)}) для кат. з Основний матеріал
MAIN_MATERIAL_CAT_MAP: dict[str, tuple[str, dict[str, tuple[str, str]]]] = {
    '9526': ('14747', {
        'силікон':        ('b5abe45f44d750029852164815558b26', 'силікон'),
        'abs':            ('08ccf26f9ae41f8bdde81ca4eee24ef4', 'ABS пластик'),
        'абс':            ('08ccf26f9ae41f8bdde81ca4eee24ef4', 'ABS пластик'),
        'пластик':        ('08ccf26f9ae41f8bdde81ca4eee24ef4', 'ABS пластик'),
        'tpe':            ('39662f46dc7f3ab96ebc5b3afa66d286', 'TPE'),
        'tpr':            ('fb403c6ea5f452c411489784d45d553c', 'TPR'),
        'метал':          ('a228d2540d6c889148a2c3b52d938b2d', 'метал'),
        'нейлон':         ('c844766f0b0d38276030c024e6b50bd5', 'нейлон'),
        'поліестер':      ('96a685cce1f7ad755896217c448baf81', 'поліестер'),
        'скло':           ('9157447d62f641c2ae9ede506a7fc17b', 'скло'),
        'пвх':            ('7b98aa212e3b5d0decd414f46817197b', 'PVC'),
        'латекс':         ('7b98aa212e3b5d0decd414f46817197b', 'PVC'),
    }),
    '9616': ('15304', {
        'силікон':        ('66eaee105a13fcd2faeb5c257c8dc2c0', 'силікон'),
        'tpe':            ('29fed6963f8bb5b6f55b12df1ddd03b2', 'TPE'),
        'tpr':            ('29fed6963f8bb5b6f55b12df1ddd03b2', 'TPE'),
        'abs':            ('fe02a27e8a4c5979894f47fcc8868235', 'ABS-пластик'),
        'абс':            ('fe02a27e8a4c5979894f47fcc8868235', 'ABS-пластик'),
        'пластик':        ('fe02a27e8a4c5979894f47fcc8868235', 'ABS-пластик'),
        'метал':          ('2239893db04da7c680e2b43714f35da7', 'метал'),
        'натуральна шкіра': ('63f9bb64ce1f2bc9f49983f00faa166a', 'натуральна шкіра'),
        'шкіра':          ('63f9bb64ce1f2bc9f49983f00faa166a', 'натуральна шкіра'),
        'екошкіра':       ('6acc2e66915b60612cb895565a71f307', 'екошкіра'),
        'латекс':         ('0b530334237fd991f4791fce29bfb317', 'латекс'),
        'тканина':        ('12785e8cb09bc5873dc332a496fbe383', 'текстиль'),
        'текстиль':       ('12785e8cb09bc5873dc332a496fbe383', 'текстиль'),
        'нейлон':         ('12785e8cb09bc5873dc332a496fbe383', 'текстиль'),
    }),
    '9620': ('15300', {
        'силікон':        ('ca0fea973c6bfd249898958eda0fc533', 'силікон'),
        'tpe':            ('a10aca0842b396090d4986e79c87dd86', 'TPE'),
        'tpr':            ('a10aca0842b396090d4986e79c87dd86', 'TPE'),
        'abs':            ('c8133fc5dec189a4d06b550a5cf99862', 'пластик (ABS)'),
        'абс':            ('c8133fc5dec189a4d06b550a5cf99862', 'пластик (ABS)'),
        'пластик':        ('c8133fc5dec189a4d06b550a5cf99862', 'пластик (ABS)'),
        'скло':           ('1ceabcac3415dd1c89d33bab204c25f9', 'скло'),
        'метал':          ('9f2e49a0bb47a71c23e30fe38f16af2a', 'метал'),
        'гума':           ('97c1649d489c1c868921889e0cd2c7a5', 'гума'),
        'тканина':        ('e5621216aa59b588abf104ba363ea5a5', 'текстиль'),
        'текстиль':       ('e5621216aa59b588abf104ba363ea5a5', 'текстиль'),
    }),
    '9548': ('14747', {
        'медичний силікон':  ('33c9d0be70ee5bfcbc1bee874949c7c4', 'медичний силікон'),
        'силікон':           ('b5abe45f44d750029852164815558b26', 'силікон'),
        'нержавіюч':         ('63e0a08999204c3276339e7e144229f0', 'нержавіюча сталь'),
        'алюміній':          ('fceb06d1c9e7e63ae27c70575d8a62cf', 'алюміній'),
        'боросилікат':       ('46a59488c891972f070bf7b5b4e58db5', 'боросилікатне скло'),
        'скло':              ('9157447d62f641c2ae9ede506a7fc17b', 'скло'),
        'метал':             ('a228d2540d6c889148a2c3b52d938b2d', 'метал'),
        'tpe':               ('39662f46dc7f3ab96ebc5b3afa66d286', 'TPE'),
        'tpr':               ('fb403c6ea5f452c411489784d45d553c', 'TPR'),
        'tpu':               ('8c4abaeaa692e897364bde6139689993', 'TPU'),
        'пвх':               ('7b98aa212e3b5d0decd414f46817197b', 'PVC'),
        'pvc':               ('7b98aa212e3b5d0decd414f46817197b', 'PVC'),
        'abs':               ('08ccf26f9ae41f8bdde81ca4eee24ef4', 'ABS пластик'),
        'абс':               ('08ccf26f9ae41f8bdde81ca4eee24ef4', 'ABS пластик'),
        'пластик':           ('08ccf26f9ae41f8bdde81ca4eee24ef4', 'ABS пластик'),
        'нейлон':            ('c844766f0b0d38276030c024e6b50bd5', 'нейлон'),
        'полікарбонат':      ('328dc09b9ac64c5aaa4770c7afd570f5', 'полікарбонат'),
        'поліестер':         ('96a685cce1f7ad755896217c448baf81', 'поліестер'),
    }),
}


# Тип живлення valuecodes for 9548 (attr 5260, different from 11098)
POWER_9548_VALUECODE: dict[str, tuple[str, str]] = {
    'без живлення': ('44350dc7e0e5dbb518fc47f99e65bfdd', 'без живлення'),
    'батарейки':    ('20b43a2e90ddf84edcd7696f9aefc14b', 'батарейки'),
    'акумулятор':   ('e116e882e332a805c66d1b4c97c1bc64', 'акумулятор'),
}


def load_brand_map(conn) -> dict[tuple[str, str], tuple[str, str]]:
    """(vendor_name_lower, atset_code) → (valuecode, value_ua)

    Ключ складений: той самий бренд може мати різний valuecode у різних
    наборах атрибутів (atset_code == epicentr_category_code).
    """
    try:
        cur = conn.cursor()
        cur.execute('SELECT brand_name, atset_code, valuecode, value_ua '
                    'FROM epicentr_brand_map')
        result = {((r['brand_name'] or '').strip().lower(),
                   str(r['atset_code'])): (r['valuecode'],
                                           r['value_ua'] or r['brand_name'])
                  for r in cur.fetchall()}
        cur.close()
        return result
    except Exception as e:
        conn.rollback()
        logger.warning(f"epicentr_brand_map недоступна ({e}) — пропускаємо")
        return {}


def load_brand_cache(conn) -> dict[str, tuple[str, str]]:
    """vendor_name_lower → (valuecode, value_ua) з глобального довідника
    брендів Єпіцентру (epicentr_brand_cache). Використовується як fallback,
    коли для пари (бренд, набір атрибутів) немає запису в epicentr_brand_map.
    """
    try:
        cur = conn.cursor()
        cur.execute('SELECT valuecode, value_ua FROM epicentr_brand_cache '
                    'WHERE value_ua IS NOT NULL')
        result: dict[str, tuple[str, str]] = {}
        for r in cur.fetchall():
            key = (r['value_ua'] or '').strip().lower()
            if key and key not in result:
                result[key] = (r['valuecode'], r['value_ua'])
        cur.close()
        return result
    except Exception as e:
        conn.rollback()
        logger.warning(f"epicentr_brand_cache недоступна ({e})")
        return {}


# ── Основна функція генерації ─────────────────────────────────────────────────

def generate_xml(
    output_file: str = OUTPUT_FILE,
    filter_category: str | None = None,
    limit: int | None = None,
    all_available: bool = False,
    exclude_categories: list[str] | None = None,
) -> int:
    conn = get_connection()
    cur = conn.cursor()

    cat_map      = load_category_mapping(cur)
    ep_names     = {c: n for c, n in cat_map.values()}
    dim_map      = load_dimensions(cur)
    brand_map    = load_brand_map(conn)
    brand_cache  = load_brand_cache(conn)
    country_map  = load_country_map(conn)
    country_lookup = load_country_lookup(conn)
    country_estim  = load_country_estimated(conn)
    ext_params   = load_extracted_params(conn)

    logger.info(f"Маппінгів категорій: {len(cat_map)}")
    logger.info(f"Категорій у dim_map: {len(dim_map)}")
    logger.info(f"Записів у brand_map (бренд×набір): {len(brand_map)}")
    logger.info(f"Брендів у довіднику Єпіцентру: {len(brand_cache)}")
    logger.info(f"Країн у довіднику Єпіцентру: {len(country_map)}")
    logger.info(f"SKU з країною від EasyToys (exact): {len(country_lookup)}")
    logger.info(f"SKU з ОЦІНОЧНОЮ країною (estimated): {len(country_estim)}")
    logger.info(f"SKU з extracted params: {len(ext_params)}")

    # Fallback-категорії без dim_map → попереджуємо одразу
    missing_dims = sorted(set(v[0] for v in cat_map.values()) - set(dim_map.keys()))
    if missing_dims:
        logger.warning(f"Відсутні в epicentr_default_dimensions (буде FALLBACK_DIM): {missing_dims}")

    # Запит товарів
    where_parts = []
    params: list = []

    # Товари, свідомо відкладені на наступний цикл (див. sexopt_products.phase)
    where_parts.append("(phase IS NULL OR phase <> 'deferred_aroma')")

    if not all_available:
        # За замовчуванням: available=true або available IS NULL (не відомо = доступний)
        where_parts.append('(available IS TRUE OR available IS NULL)')

    if filter_category:
        # Фільтр по epicentr_category_code: знаходимо відповідні sexopt_category_id
        sexopt_cat_ids = [sid for sid, (ec, _) in cat_map.items() if ec == filter_category]
        if not sexopt_cat_ids:
            logger.error(f"Категорія {filter_category} не знайдена в маппінгу")
            conn.close()
            return 0
        where_parts.append(f"category_id = ANY(%s)")
        params.append(sexopt_cat_ids)

    if exclude_categories:
        # Виключення по epicentr_category_code (напр. 7216, 9464)
        excl_ids = [sid for sid, (ec, _) in cat_map.items()
                    if ec in exclude_categories]
        logger.info(f"Виключено Epicentr-категорій {exclude_categories}: "
                    f"{len(excl_ids)} sexopt_category_id")
        if excl_ids:
            where_parts.append('category_id <> ALL(%s)')
            params.append(excl_ids)

    where_sql = ('WHERE ' + ' AND '.join(where_parts)) if where_parts else ''
    limit_sql = f'LIMIT {limit}' if limit else ''

    cur.execute(f'''
        SELECT sku, category_id, name, description_html,
               price_retail, vendor, pictures, country
        FROM sexopt_products
        {where_sql}
        ORDER BY sku
        {limit_sql}
    ''', params if params else None)
    products = cur.fetchall()
    conn.close()

    logger.info(f"Товарів для генерації: {len(products)}")
    if not products:
        logger.error("Немає товарів")
        return 0

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{datetime.now().strftime("%Y-%m-%d %H:%M")}">',
        '<offers>',
    ]

    cnt_total = cnt_skip_no_map = cnt_skip_no_price = cnt_fallback_dim = 0
    cnt_vendor_valid = cnt_vendor_cache = cnt_vendor_other = 0
    cnt_default_material = cnt_default_modes = cnt_country_unknown = 0
    cnt_country_by_brand = cnt_country_scraped = cnt_country_estimated = 0
    cnt_cat_override = 0
    unknown_countries: dict[str, list] = {}
    missing_brands: dict[str, int] = {}
    cat_stats: dict[str, int] = {}

    for p in products:
        sku      = p['sku'] or ''
        price    = float(p['price_retail'] or 0)
        name     = (p['name'] or '').strip()
        desc     = (p['description_html'] or '').strip()
        vendor   = (p['vendor'] or '').strip()
        pictures = p['pictures'] or []
        cntry    = p['country']

        if not price:
            cnt_skip_no_price += 1
            continue

        # Категорія
        mapping = cat_map.get(str(p['category_id']))
        if not mapping:
            cnt_skip_no_map += 1
            continue
        cat_code, cat_name = mapping
        if cat_code == '3275':
            # У 3275 свої коди для Матеріалу (5410), Текстури (5412) і
            # Розміру (5413). Значення, витягнуті під коди інтимного дерева,
            # тут не валідні — прибираємо, щоб спрацював блок нижче.
            sku_params = {k: v for k, v in sku_params.items()
                          if k not in ('Матеріал', 'Текстура', 'Розмір')}
        if sku in SKU_CATEGORY_OVERRIDE:
            new_code = SKU_CATEGORY_OVERRIDE[sku]
            new_name = ep_names.get(new_code)
            if new_name:
                cat_code, cat_name = new_code, new_name
                cnt_cat_override += 1

        # Габарити
        dim = dim_map.get(cat_code)
        if dim:
            w_g   = dim['weight_g']
            wi_mm = dim['width_mm']
            h_mm  = dim['height_mm']
            l_mm  = dim['length_mm']
        else:
            w_g   = FALLBACK_DIM['weight_g']
            wi_mm = FALLBACK_DIM['width_mm']
            h_mm  = FALLBACK_DIM['height_mm']
            l_mm  = FALLBACK_DIM['length_mm']
            cnt_fallback_dim += 1

        sell_price = calc_sell_price(price, cat_code)
        cat_stats[cat_name] = cat_stats.get(cat_name, 0) + 1

        # Бренд: спершу точна пара (бренд, набір атрибутів), потім глобальний
        # довідник Єпіцентру, і лише тоді — 'Інше'
        vendor_key = re.split(r'\s*[\(\[,]', vendor)[0].strip().lower()
        brand_info = brand_map.get((vendor_key, str(cat_code)))
        if brand_info:
            v_code, v_text = brand_info
            cnt_vendor_valid += 1
        elif brand_cache.get(vendor_key):
            v_code, v_text = brand_cache[vendor_key]
            cnt_vendor_cache += 1
        else:
            v_code, v_text = OTHER_BRAND_CODE, 'Інше'
            cnt_vendor_other += 1
            if vendor_key:
                missing_brands[vendor_key] = missing_brands.get(vendor_key, 0) + 1

        iso = country_code(cntry, country_map)
        cntry_display = (cntry or '').split('(')[0].strip()
        # Бренд із документально підтвердженою країною виробництва —
        # підстановка лише коли постачальник країну не вказав узагалі
        if iso is None and sku in country_lookup:
            lk_iso = country_code(country_lookup[sku], country_map)
            if lk_iso:
                iso, cntry_display = lk_iso, country_lookup[sku]
                cnt_country_scraped += 1
        if iso is None and vendor_key in BRAND_COUNTRY_OVERRIDE:
            ovr = BRAND_COUNTRY_OVERRIDE[vendor_key]
            ovr_iso = country_code(ovr, country_map)
            if ovr_iso:
                iso, cntry_display = ovr_iso, ovr
                cnt_country_by_brand += 1
        if iso is None and sku in country_estim:
            est_iso = country_code(country_estim[sku], country_map)
            if est_iso:
                iso, cntry_display = est_iso, country_estim[sku]
                cnt_country_estimated += 1
        if iso is None:
            # Політика оціночних дефолтів застосовується напряму, а не лише
            # з таблиці: інакше товар, який щойно повернувся у продаж або
            # зʼявився в постачальника, випадає з фіду через відсутню країну.
            pol = COUNTRY_DEFAULT_FALLBACK.get(vendor_key,
                                               COUNTRY_DEFAULT_FALLBACK.get('*'))
            pol_iso = country_code(pol, country_map) if pol else None
            if pol_iso:
                iso, cntry_display = pol_iso, pol
                cnt_country_estimated += 1
        if iso is None:
            cnt_country_unknown += 1
            unknown_countries.setdefault(cntry or '(порожньо)', []).append(sku)

        offer: list[str] = [
            f'  <offer id="{escape_xml(sku)}" available="true">',
            f'    <price>{sell_price:.2f}</price>',
            f'    <category code="{escape_xml(cat_code)}">{escape_xml(cat_name)}</category>',
            f'    <attribute_set code="{escape_xml(cat_code)}">{escape_xml(cat_name)}</attribute_set>',
            f'    <name lang="ua">{escape_xml(name)}</name>',
            f'    <name lang="ru">{escape_xml(name)}</name>',
        ]

        for pic_url in (pictures or [])[:10]:
            if pic_url:
                offer.append(f'    <picture>{escape_xml(pic_url)}</picture>')

        if desc:
            offer.append(f'    <description lang="ua">{escape_xml(desc)}</description>')

        offer.append(
            f'    <vendor code="{escape_xml(v_code)}">{escape_xml(v_text)}</vendor>')
        # Країна вказується лише коли її розпізнано в довіднику Єпіцентру
        if iso:
            offer.append(f'    <country_of_origin code="{iso}">'
                         f'{escape_xml(cntry_display)}</country_of_origin>')

        offer += [
            '    <param name="Міра виміру" paramcode="measure" valuecode="measure_pcs">шт.</param>',
            '    <param name="Мінімальна кратність товару" paramcode="ratio">1</param>',
            f'    <param name="Бренд" paramcode="brand" valuecode="{escape_xml(v_code)}">{escape_xml(v_text)}</param>',
            f'    <weight>{w_g}</weight>',
            f'    <width>{wi_mm}</width>',
            f'    <height>{h_mm}</height>',
            f'    <length>{l_mm}</length>',
        ]

        # ── Extracted + classification params ────────────────────────────────
        sku_params = ext_params.get(sku, {})
        if cat_code == '3275':
            # У 3275 свої коди для Матеріалу (5410), Текстури (5412) і
            # Розміру (5413). Значення, витягнуті під коди інтимного дерева,
            # тут не валідні — прибираємо, щоб спрацював блок нижче.
            sku_params = {k: v for k, v in sku_params.items()
                          if k not in ('Матеріал', 'Текстура', 'Розмір')}
        if sku in SKU_CATEGORY_OVERRIDE:
            # Категорію перевизначено адресно, тому класифікаційні атрибути,
            # витягнуті під СТАРУ категорію, більше не валідні: 'Тип товару'
            # для набору фіксації не може лишатись 'класична анальна пробка'.
            sku_params = {k: v for k, v in sku_params.items()
                          if k not in ('Тип товару', 'Тип', 'Вид')}
        SKIP_PARAMS = {'Бренд', 'Міра виміру', 'Мінімальна кратність товару'}

        # Трекер: які param_name вже додані (щоб не дублювати)
        added_params: set[str] = set()

        def _add_param(name, attr_code, valuecode, display):
            if not display:
                return
            vc_attr = f' valuecode="{escape_xml(valuecode)}"' if valuecode else ''
            offer.append(
                f'    <param name="{escape_xml(name)}"'
                f' paramcode="{escape_xml(attr_code)}"'
                f'{vc_attr}>{escape_xml(display)}</param>'
            )
            added_params.add(name)

        for param_name, (stored_code, param_value) in sorted(sku_params.items()):
            if param_name in SKIP_PARAMS or not param_value:
                continue

            if param_name in CLASSIFICATION_ATTR_CODES or \
               CAT_PARAM_ATTR_CODE.get((cat_code, param_name)):
                attr_code = (CAT_PARAM_ATTR_CODE.get((cat_code, param_name))
                             or CLASSIFICATION_ATTR_CODES.get(param_name, ''))
                _add_param(param_name, attr_code, stored_code, param_value)

            elif param_name == 'Матеріал' and cat_code in MATERIAL_FORBIDDEN_CATS:
                # Розхідники (лубриканти, олії, свічки, спреї): Матеріал не
                # входить у набір атрибутів цих категорій — звірено з
                # epicentr_required_attrs_sexopt. Екстрактор давав тут хибні
                # значення ('тканина' з Cotton Candy, 'натуральна шкіра' з
                # догляду за шкірою), тому атрибут не проставляється взагалі.
                pass

            elif param_name == 'Матеріал':
                # For categories with Основний матеріал (different attr code + valuecodes)
                mm_info = MAIN_MATERIAL_CAT_MAP.get(cat_code)
                if mm_info:
                    mm_attr_code, mm_map = mm_info
                    key = param_value.lower()
                    vc_info = next((v for k, v in mm_map.items() if k in key), None)
                    if vc_info:
                        _add_param('Основний матеріал', mm_attr_code, vc_info[0], vc_info[1])
                    else:
                        _add_param('Основний матеріал', mm_attr_code, '', param_value)
                else:
                    key = param_value.lower()
                    vc_info = next((v for k, v in MATERIAL_VALUECODE.items() if k in key), None)
                    if vc_info:
                        vc, disp = vc_info
                        if vc == MATERIAL_VALUECODE['tpr'][0] and cat_code in _CAT_TPE_ONLY:
                            vc, disp = MATERIAL_VALUECODE['tpe']
                        elif vc == MATERIAL_VALUECODE['tpe'][0] and cat_code in _CAT_TPR_ONLY:
                            vc, disp = MATERIAL_VALUECODE['tpr']
                        _add_param(param_name, '12731', vc, disp)
                    else:
                        _add_param(param_name, '12731', '', param_value)

            elif param_name == 'Кількість режимів роботи':
                vc = MODES_VALUECODE.get(str(param_value).strip())
                _add_param(param_name, '4212', vc or '', param_value)

            elif param_name == 'Тип живлення':
                if cat_code == '9548':
                    vc_info = POWER_9548_VALUECODE.get(
                        param_value.strip().lower(),
                        POWER_9548_VALUECODE['без живлення'])
                    _add_param(param_name, '5260', vc_info[0], vc_info[1])
                else:
                    vc_info = POWER_VALUECODE.get(param_value.strip())
                    if vc_info:
                        _add_param(param_name, '11098', vc_info[0], vc_info[1])
                    else:
                        _add_param(param_name, '11098', '', param_value)

            elif PARAM_ATTR_CODES.get(param_name) in BOOL_VALUECODES:
                # UUID-based bool attrs
                attr_code = PARAM_ATTR_CODES[param_name]
                _, _, ні_vc, так_vc = BOOL_VALUECODES[attr_code]
                val_lower = str(param_value).lower()
                if val_lower in ('так', 'true', '1', 'yes', 'ipx6', 'ipx7'):
                    vc = так_vc
                    display = 'так'
                    if param_name == 'Водонепроникний' and val_lower in ('ipx7', 'ipx6'):
                        display = param_value
                else:
                    vc = ні_vc
                    display = 'ні'
                _add_param(param_name, attr_code, vc, display)

            elif PARAM_ATTR_CODES.get(param_name) in NEW_BOOL_ATTR_CODES:
                # yes/no string bool attrs (15xxx series)
                attr_code = PARAM_ATTR_CODES[param_name]
                val_lower = str(param_value).lower()
                vc = 'yes' if val_lower in ('так', 'true', '1', 'yes') else 'no'
                display = 'так' if vc == 'yes' else 'ні'
                _add_param(param_name, attr_code, vc, display)

            elif param_name in ('Колір виробника',):
                _add_param(param_name, '78', '', param_value)

            elif param_name == 'Об\'єм':
                _add_param(param_name, '15742', '', param_value)

            elif param_name == 'Кількість':
                _add_param(param_name, '15741', '', param_value)

            else:
                attr_code = stored_code or PARAM_ATTR_CODES.get(param_name, '')
                _add_param(param_name, attr_code, '', param_value)

        # ── Default "ні" для обов'язкових UUID bool-атрибутів категорії ────────
        for attr_code in CAT_REQUIRED_BOOL.get(cat_code, []):
            attr_name, paramcode, ні_vc, _ = BOOL_VALUECODES[attr_code]
            if attr_name not in added_params:
                _add_param(attr_name, paramcode, ні_vc, 'ні')

        # ── Default "no" для обов'язкових yes/no bool-атрибутів категорії ─────
        for attr_code, attr_name in CAT_REQUIRED_NEW_BOOL.get(cat_code, []):
            if attr_name not in added_params:
                _add_param(attr_name, attr_code, 'no', 'ні')

        # ── Default Тип живлення для категорій де потрібен ───────────────────
        if cat_code in ('9484', '9482', '9478') and 'Тип живлення' not in added_params:
            vib_val = (sku_params.get('Вібрація') or ('', 'ні'))[1].lower()
            heat_val = (sku_params.get('Підігрів') or ('', 'ні'))[1].lower()
            if vib_val == 'так' or heat_val == 'так':
                _add_param('Тип живлення', '11098', '8294dba5410453cfcee202a5b467449c', 'акумулятор')
            else:
                _add_param('Тип живлення', '11098', '5c3b825174d971f86e3017a106a74295', 'без живлення')

        # ── Колір виробника та Колір для аксесуарних та кольорових категорій ───
        if cat_code in ('9526', '9616', '9620', '9550'):
            color_val = (sku_params.get('Колір') or ('', ''))[1] or 'Чорний'
            if 'Колір виробника' not in added_params:
                _add_param('Колір виробника', '78', '', color_val)
        # 9526: Колір (attr 2845) is required — default if not extracted
        if cat_code == '9526' and 'Колір' not in added_params:
            color_val = (sku_params.get('Колір') or ('', ''))[1] or 'Чорний'
            _add_param('Колір', '2845', '', color_val)
        # 9550: Базовий колір (attr 12097) — map extracted color → valuecode, default black
        if cat_code == '9550' and 'Базовий колір' not in added_params:
            color_val = (sku_params.get('Колір') or ('', ''))[1]
            vc_info = CANDLE_COLOR_VALUECODE.get(color_val.lower()) if color_val else None
            if vc_info:
                _add_param('Базовий колір', '12097', vc_info[0], vc_info[1])
            else:
                _add_param('Базовий колір', '12097',
                           '3ec160321d45b95cf3a540ad3a2bf896', 'чорний')

        # ── Презервативи (3275) ──────────────────────────────────────────────
        if cat_code == '3275':
            if 'Матеріал' not in added_params:
                vc, disp = CONDOM_MATERIAL_DEFAULT
                for rx, v, d in CONDOM_MATERIAL:
                    if re.search(rx, name, re.I):
                        vc, disp = v, d
                        break
                _add_param('Матеріал', '5410', vc, disp)
            if 'Текстура' not in added_params:
                vc, disp = CONDOM_TEXTURE_DEFAULT
                for rx, v, d in CONDOM_TEXTURE:
                    if re.search(rx, name, re.I):
                        vc, disp = v, d
                        break
                _add_param('Текстура', '5412', vc, disp)
            if 'Розмір' not in added_params:
                vc, disp = CONDOM_SIZE_DEFAULT
                mm = re.search(r'(\d{2})\s*мм', name)
                if mm:
                    w = int(mm.group(1))
                    for lo, hi, v, d in CONDOM_SIZE_BANDS:
                        if lo <= w < hi:
                            vc, disp = v, d
                            break
                _add_param('Розмір', '5413', vc, disp)
            if 'Кількість в упаковці' not in added_params:
                q = re.search(r'(\d+)\s*шт', name)
                _add_param('Кількість в упаковці', '2847', '', q.group(1) if q else '1')

        # ── Універсальні дефолти обов'язкових атрибутів ──────────────────────
        for a_code, a_name, rules, dflt in CATEGORY_ATTR_DEFAULTS.get(cat_code, []):
            if a_name in added_params:
                continue
            vc, disp = dflt
            for rx, v, d in rules:
                if re.search(rx, name, re.I):
                    vc, disp = v, d
                    break
            _add_param(a_name, a_code, vc, disp)

        # ── Тип товару (13948) для 9458 ──────────────────────────────────────
        if cat_code == '9458' and 'Тип товару' not in added_params:
            vc, disp = BDSM_TYPE_DEFAULT
            for rx, v, d in BDSM_TYPE_RULES:
                if re.search(rx, name, re.I):
                    vc, disp = v, d
                    break
            _add_param('Тип товару', '13948', vc, disp)

        # ── Конструкція (13037) для 9480 ─────────────────────────────────────
        if cat_code == '9480' and 'Конструкція' not in added_params:
            vc, disp = DILDO_CONSTRUCTION_DEFAULT
            for rx, v, d in DILDO_CONSTRUCTION_RULES:
                if re.search(rx, name, re.I):
                    vc, disp = v, d
                    break
            _add_param('Конструкція', '13037', vc, disp)

        # ── Форма (12891) і Тип товару (13948) для 9484 ──────────────────────
        if cat_code == '9484':
            if 'Форма' not in added_params:
                _add_param('Форма', '12891', *PLUG_SHAPE_DEFAULT)
            if 'Тип товару' not in added_params:
                vc, disp = PLUG_TYPE_DEFAULT
                for rx, v, d in PLUG_TYPE_RULES:
                    if re.search(rx, name, re.I):
                        vc, disp = v, d
                        break
                _add_param('Тип товару', '13948', vc, disp)

        # ── Дефолт Матеріал (12731) ──────────────────────────────────────────
        # Спрацьовує лише коли матеріал не витягнуто з назви товару.
        # Усі valuecodes звірені з PIM API:
        #   /v2/pim/attribute-sets/<cat>/attributes/12731/options
        if cat_code in MATERIAL_DEFAULT_BY_CAT and 'Матеріал' not in added_params:
            rules, fallback = MATERIAL_DEFAULT_BY_CAT[cat_code]
            chosen = fallback
            for rx, val in rules:
                if re.search(rx, name, re.I):
                    chosen = val
                    break
            if chosen:   # None → свідомо не ставимо (немає валідної опції)
                _add_param('Матеріал', '12731', chosen[0], chosen[1])
                cnt_default_material += 1

        # ── Дефолт Основний матеріал для категорій-аксесуарів ────────────────
        if cat_code in MAIN_MATERIAL_DEFAULT and 'Основний матеріал' not in added_params:
            a_code, vc, disp = MAIN_MATERIAL_DEFAULT[cat_code]
            _add_param('Основний матеріал', a_code, vc, disp)
            cnt_default_material += 1

        # ── Дефолт Кількість режимів роботи (4212) ───────────────────────────
        # '1' — мінімально прийнятне значення для пристрою без даних про режими
        if cat_code == '9466' and 'Кількість режимів роботи' not in added_params:
            _add_param('Кількість режимів роботи', '4212',
                       MODES_VALUECODE['1'], '1')
            cnt_default_modes += 1

        # ── Дефолти для 9548 (Анальні розширювачі) ───────────────────────────
        if cat_code == '9548':
            # Основний матеріал (14747) — default силікон якщо Матеріал не витягнуто
            if 'Основний матеріал' not in added_params:
                _add_param('Основний матеріал', '14747',
                           'b5abe45f44d750029852164815558b26', 'силікон')
            # Тип живлення з attr 5260 (замість 11098)
            if 'Тип живлення' not in added_params:
                _add_param('Тип живлення', '5260',
                           '44350dc7e0e5dbb518fc47f99e65bfdd', 'без живлення')
            # Максимальний діаметр (1892) — default 30 якщо Діаметр не витягнуто
            if 'Діаметр (мм)' not in added_params:
                _add_param('Діаметр (мм)', '1892', '', '30')
            # Мінімальний діаметр = той самий що максимальний
            if 'Мінімальний діаметр' not in added_params:
                diam_val = (sku_params.get('Діаметр (мм)') or ('', ''))[1] or '30'
                _add_param('Мінімальний діаметр', '8999', '', diam_val)
            # Базовий колір (12097)
            if 'Базовий колір' not in added_params:
                color_val = (sku_params.get('Колір') or ('', ''))[1]
                vc_info = CANDLE_COLOR_VALUECODE.get(color_val.lower()) if color_val else None
                if vc_info:
                    _add_param('Базовий колір', '12097', vc_info[0], vc_info[1])
                else:
                    _add_param('Базовий колір', '12097',
                               '3ec160321d45b95cf3a540ad3a2bf896', 'чорний')
            # Колір виробника (78)
            if 'Колір виробника' not in added_params:
                color_val = (sku_params.get('Колір') or ('', ''))[1] or 'Чорний'
                _add_param('Колір виробника', '78', '', color_val)

        # ── Дефолти для 9468 (Секс-ляльки) ──────────────────────────────────────
        if cat_code == '9468':
            # Матеріал (12731) — default ПВХ для надувних ляльок
            if 'Матеріал' not in added_params:
                _add_param('Матеріал', '12731',
                           'be10ef08d4f42f41065fabbedbb921dc', 'PVC (полівінілхлорид)')
            # Стать ляльки визначає бінарні атрибути
            gender_val = (sku_params.get('Стать ляльки') or ('', ''))[1].lower()
            is_male = 'чоловіч' in gender_val
            # Оральний отвір — так для всіх ляльок
            if 'Оральний отвір' not in added_params:
                _add_param('Оральний отвір', '5197',
                           'b46da99f65b91cf72ecdf9ca5f1f9650', 'так')
            # Анальний отвір — так для всіх ляльок
            if 'Анальний отвір' not in added_params:
                _add_param('Анальний отвір', '5223',
                           '5d853387252804395587071d02afde75', 'так')
            # Статевий член — так для чоловічих, ні для жіночих
            if 'Статевий член' not in added_params:
                if is_male:
                    _add_param('Статевий член', '5181',
                               'e193ef1d7a911d6d0ce306ea3319a639', 'так')
                else:
                    _add_param('Статевий член', '5181',
                               '446c45edc56f67e950b479c414f765f9', 'ні')
            # Вагінальний отвір — ні для чоловічих, так для жіночих
            if 'Вагінальний отвір' not in added_params:
                if is_male:
                    _add_param('Вагінальний отвір', '5255',
                               '5ae1d2b8e4b74a16f351b48be95f05d4', 'ні')
                else:
                    _add_param('Вагінальний отвір', '5255',
                               'a562464e4abf950ea7dc62104c19b1cb', 'так')

        # ── Дефолти для олій/свічок ───────────────────────────────────────────
        if cat_code in ('9632', '9630'):
            if 'Кількість' not in added_params:
                _add_param('Кількість', '15741', '', '1')
            if "Об'єм" not in added_params:
                vol_val = (sku_params.get("Об'єм") or ('', ''))[1] or '50'
                _add_param("Об'єм", '15742', '', vol_val)

        if cat_code == '9630':
            # Час горіння — default "до 3 годин"
            if 'Час горіння' not in added_params:
                _add_param('Час горіння', '15761',
                           'f3586e6130f87c9615776bf4dd4cc096', 'до 3 годин')
            # Базовий колір — map extracted color to 12097 valuecodes
            if 'Базовий колір' not in added_params:
                color_val = (sku_params.get('Колір') or ('', ''))[1]
                vc_info = CANDLE_COLOR_VALUECODE.get(color_val.lower()) if color_val else None
                if vc_info:
                    _add_param('Базовий колір', '12097', vc_info[0], vc_info[1])
                else:
                    _add_param('Базовий колір', '12097',
                               '3ec160321d45b95cf3a540ad3a2bf896', 'чорний')

        # ── country_of_origin + brand як param для категорій де is_required ──
        if cat_code in CAT_COUNTRY_BRAND_REQUIRED:
            if iso and 'Країна-виробник' not in added_params:
                _add_param('Країна-виробник', 'country_of_origin', iso, cntry_display)
            # brand вже є через постійний param вище, але на випадок пропуску:
            if 'Бренд' not in added_params:
                _add_param('Бренд', 'brand', v_code, v_text)

        offer.append('  </offer>')

        lines.extend(offer)
        cnt_total += 1

    lines += ['</offers>', '</yml_catalog>']

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))

    size_kb = os.path.getsize(output_file) // 1024

    logger.info('─' * 60)
    logger.info(f"Згенеровано офферів : {cnt_total}")
    logger.info(f"Категорію перевизначено адресно : {cnt_cat_override}")
    logger.info(f"Без маппінгу (skip) : {cnt_skip_no_map}")
    logger.info(f"Без ціни (skip)     : {cnt_skip_no_price}")
    logger.info(f"Fallback-габарити   : {cnt_fallback_dim}")
    logger.info(f"Країна з EasyToys (точний збіг)       : {cnt_country_scraped}")
    logger.info(f"Країна з підтвердженого бренду        : {cnt_country_by_brand}")
    logger.info(f"Країна ОЦІНОЧНА (estimated_default)  : {cnt_country_estimated}")
    logger.info(f"Країна не розпізнана (тег пропущено) : {cnt_country_unknown}")
    for cname, skus in sorted(unknown_countries.items(), key=lambda x: -len(x[1])):
        logger.warning(f"   НЕРОЗПІЗНАНА КРАЇНА '{cname}': {len(skus)} SKU — "
                       f"{', '.join(skus[:25])}{' …' if len(skus) > 25 else ''}")
    logger.info(f"Дефолт Матеріал проставлено          : {cnt_default_material}")
    logger.info(f"Дефолт Кількість режимів проставлено : {cnt_default_modes}")
    logger.info(f"Бренд з brand_map (пара бренд×набір) : {cnt_vendor_valid}")
    logger.info(f"Бренд з довідника Єпіцентру           : {cnt_vendor_cache}")
    logger.info(f"Бренд 'Інше' (немає в довіднику)      : {cnt_vendor_other}")
    if missing_brands:
        logger.info(f"Брендів відсутніх у довіднику: {len(missing_brands)}")
        for b, n in sorted(missing_brands.items(), key=lambda x: -x[1]):
            logger.info(f"   ВІДСУТНІЙ БРЕНД  {n:>5}  {b}")
    logger.info(f"Файл: {output_file} ({size_kb} КБ)")
    logger.info('─' * 60)
    logger.info("Розподіл по категоріях:")
    for name, cnt in sorted(cat_stats.items(), key=lambda x: -x[1]):
        logger.info(f"  {cnt:>5}  {name}")

    return cnt_total


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NOIRE → Єпіцентр XML генератор")
    parser.add_argument('--output', '-o', default=OUTPUT_FILE, help='Вихідний XML-файл')
    parser.add_argument('--category', '-c', help='Фільтр по epicentr_category_code (напр. 9466)')
    parser.add_argument('--limit', '-l', type=int, help='Максимум товарів (для тестів)')
    parser.add_argument('--all-available', action='store_true',
                        help='Включати товари з available=false (за замовчуванням виключаються)')
    parser.add_argument('--exclude-category', '-x', default='',
                        help='Виключити epicentr_category_code через кому (напр. 7216,9464)')
    args = parser.parse_args()

    cnt = generate_xml(
        output_file=args.output,
        filter_category=args.category,
        limit=args.limit,
        all_available=args.all_available,
        exclude_categories=[c.strip() for c in args.exclude_category.split(',')
                            if c.strip()],
    )
    exit(0 if cnt > 0 else 1)


if __name__ == '__main__':
    main()
