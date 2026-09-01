#!/usr/bin/env python3
"""
tools/noire_classifier.py
Класифікаційні атрибути Єпіцентру: regex по назві/опису → valuecode.

Атрибути що НЕ витягуються парсером описів, але визначаються за паттернами:
  3103  Тип приладу          (9466, 9482)
  3106  Вид                  (9466, 9472)
  3369  Призначення          (9466, 9476, 9470)
  13037 Конструкція          (9466, 9480, 9482, 9474, 9470)
  13039 Вид                  (9480, 9482, 9474)
  12891 Форма                (9484)
  13948 Тип товару           (7216, 9458, 9484)
  13949 Призначення білизна  (7216)
  5249  Тип помпи            (9476)
  437   Тип кріплення        (9482)
  7192  Текстура поверхні    (9474)
  7215  Тип насадки          (9474)
  9695  Тип кільця           (9470)
  9698  Текстура поверхні    (9470)
  13954 Тип товару           (9478)
  13948 Тип товару           (9460)
  15743 Стать                (9628, 9630, 9632)
  15763 Тип продукту         (9628)
  15765 Смак                 (9628)
  15766 Аромат               (9628)
  15744 Аромат               (9630, 9632)
  15762 Тип воску            (9630)
  15774 Тип упаковки         (9628)

Запуск:
    cd /home/tekken/agent-system && source venv/bin/activate
    python3 tools/noire_classifier.py --dry-run
    python3 tools/noire_classifier.py
    python3 tools/noire_classifier.py --sku AD108735 SO6627
"""

import argparse, os, re, sys
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, '.env'))

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

DB = dict(host='192.168.3.28', port=5432, dbname='agentdb', user='agentadmin', password='1')


# ── Структура правила ─────────────────────────────────────────────────────────
# (regex_pattern, valuecode, label_ua)
# Правила перевіряються по черзі; перше спрацьоване — результат.
# Якщо жодне — перевіряється default (останній рядок у списку з pattern=None).

class Rule:
    __slots__ = ('pat', 'valuecode', 'label')
    def __init__(self, pattern, valuecode, label):
        self.pat      = re.compile(pattern, re.I) if pattern else None
        self.valuecode = valuecode
        self.label    = label

    def match(self, text: str) -> bool:
        return self.pat is None or bool(self.pat.search(text))


def classify(text: str, rules: list[Rule]) -> Rule | None:
    for rule in rules:
        if rule.match(text):
            return rule
    return None


# ── 3103 Тип приладу (9466 Вібратори) ────────────────────────────────────────

VIBRATOR_TYPE_RULES: list[Rule] = [
    Rule(r'вакуум|air.?pulse|airwave|air.?stimul|пульсатор.повітр|безконтактн',
         'b960b5ea61578c4cf51ad4b3b1ef2a9a', 'вакуумний стимулятор'),
    Rule(r'для сосків|nipple.?vibrat|сосок.*стимул',
         'a25e2667ea28bab67f6119990c31ed76', 'вібратор для сосків'),
    Rule(r'набір (?:іграшок|вібраторів|приладів|секс)',
         '28b7fb2873e7f42393d50eaaef086cee', 'набір приладів'),
    Rule(r'яйц[еяьо]\b|egg(?!.{0,5}cup)|виброяйц|віброяйц',
         '6f1521062d0bbce3a0427bb8c87c4bd9', 'віброяйця'),
    Rule(r'трусик[аи]|panty|panties|вібротрус',
         'e2ecded735558cec666b81b5f99e0e04', 'вібротрусики'),
    Rule(r'для пар|couples?\b|partner|remote.{0,30}vibrat|vibrat.{0,30}remote|дистанційн.*пар',
         'ee2bfc875647653c3a86e52c02c44793', 'вібратор для пар'),
    Rule(r'куля\b|кулі\b|bullet.*vibrat|vibro.*bullet|mini.*bullet|куль',
         '675745be6eca3a513a24eec02744ff17', 'віброкулі'),
    Rule(r'пульсатор|thrusting|thrust|поршн|telescop.*vibrat|reciprocat',
         '9da6fa7bf9a8dc8262add17020f2c357', 'вібратор-пульсатор'),
    Rule(r'кролик|rabbit\b|bunny|вушк.*стимул',
         '10b744fc450b41eee20339bb9cc81591', 'вібратор-кролик'),
    Rule(r'палець|пальц[іе]|finger.?ring|finger.?vibrat|насадка на палець',
         'ed00e2273d2ace99946232a51a48be6f', 'вібратор-насадка на палець'),
    Rule(r'насадк[аи] (?:до|на|для) (?:члена|пеніса)|penis.?sleeve|cock.?sleeve|sleeve.?vibrat',
         'c669732169c88a37baa8d06a81077417', 'насадки до вібратора'),
    Rule(r'оро.?імітатор|орал\b|lick|язич|oral.?vibrat|tongue',
         '195adb4b4b3ba0a7fdb2c9d9eec313ea', 'ороімітатор'),
    Rule(r'звуков|sonic\b|ультразвук|ultrasonic',
         '91c5ea2223d5c66ba0c0d787ef439794', 'звуковий стимулятор'),
    Rule(r'мікрофон|magic.?wand|wand.?massag',
         'fbd062702248e58fcbe08ee991679be0', 'вібратор-мікрофон'),
    Rule(r'точков.*вібр|точка.?g\b|g.?spot|g.?точк|clitoral.*g.?spot',
         'eba6c3fe46103d625d7b9f947253b929', 'точковий вібратор'),
    Rule(r'нестандартн|unusual|special.*shape',
         '56c84cae1d1a2c5f5a13a97e5dc08f93', 'нестандартний вібратор'),
    Rule(r'реалістичн.*вібр|vibrating.*dildo|vibro.*dildo',
         '71e5ad59d9cc1d02af91172070b9a57b', 'віброчлен'),
    # міні — після специфічних
    Rule(r'\bміні.?вібр|mini.?vibrat|\bпочатківц|\bstarter\b',
         'ca5ff945a7fb475808ad8995b2d34ec0', 'міні-вібратор'),
    # default: класичний вібратор
    Rule(None, '16723aa41fdd0a83e91ce200a353b73e', 'класичний вібратор'),
]


# ── 3106 / 13039 Вид (реалістичні / нереалістичні) ───────────────────────────

REALISTIC_RULES: list[Rule] = [
    Rule(r'реалістичн|realistic|ultraskin|ultraskyn|cyberskin|UR3\b|фалос.*пеніс|пеніс.*форм',
         'fec4f80a1e018a6dab1eb0827d51745c', 'реалістичні'),
    Rule(None, '5ccb1599b2d64697e938d9dba03a6de0', 'нереалістичні'),
]

DILDO_REALISTIC_RULES: list[Rule] = [
    Rule(r'реалістичн|realistic|ultraskin|ultraskyn|cyberskin|UR3\b|форм[аи] пеніс|cock',
         '1d22f893932403acca074d66ff7c6791', 'реалістичні'),
    Rule(None, '87a38d182c108a017215f17ac230371c', 'нереалістичні'),
]


# ── 3369 Призначення (9466 Вібратори) ────────────────────────────────────────

PURPOSE_VIBRATOR_RULES: list[Rule] = [
    Rule(r'3 в 1|3-in-1|triple.*stimul|потрійн.*стимул|вагін.*кліт.*анальн|clit.{0,15}g.spot.{0,15}anal',
         'ce6a4d5ef301bd4d5886f4c17bbcd5e3', 'стимуляція 3 в 1'),
    Rule(r'для точки\s*g\b|g.?spot|g.?точк|стимуляція.*g\b',
         '67b290628f48f3e61a4f1a20438acd19', 'для точки G'),
    Rule(r'вагін.*анал|анал.*вагін|вагінально.?анальн|anal.{0,15}vaginal',
         'b39aefc1246c5639fe1ccd4a8ebd58d8', 'вагінально-анальні'),
    Rule(r'вагін.*кліт|кліт.*вагін|rabbit|кролик|вагінально.?кліторн',
         '24838043e73651b5feb8c35d019dd2fb', 'вагінально-кліторні'),
    Rule(r'анальн|анальн.*вібр|anal.*vibrat|butt.*plug.*vibrat',
         '52abbc42ff3aa782532d7772cc080248', 'анальні'),
    Rule(r'кліторн|клітор[а-я]*|clit(?:oral)?|external.*stimul',
         'f0398e75966a489d608a8ea1770a2638', 'кліторні'),
    # default: вагінальні
    Rule(None, '5fa1044eac4a17aea732a14f610c915b', 'вагінальні'),
]


# ── 13037 Конструкція (вібратори та фалоімітатори) ────────────────────────────

CONSTRUCTION_RULES: list[Rule] = [
    Rule(r'двосторонн|double.?end|two.?head|з двох боків',
         '2860864ebd558e70cb142e9729576086', 'двосторонні'),
    Rule(r'подвійн|double.?penetrat|double.?dildo|\bDP\b',
         '0fba418bedb2dbb9ca04d9e368d434cb', 'подвійні'),
    Rule(r'мошонк|balls?|яєчк|testicle',
         'e42be680e4fce1db661201e4a19ee163', 'з мошонкою'),
    Rule(None, '8d32bd5d1a1f4bd8f7527e748f7df76d', 'односторонні'),
]


# ── 12891 Форма анальні пробки ────────────────────────────────────────────────

ANAL_SHAPE_RULES: list[Rule] = [
    Rule(r'ялинк|christmas.?tree|beaded|намиста|рябч',
         '21045a0b4f280f281560ed2b2cb29d4e', 'анальна пробка-ялинка'),  # not in our 3 options; use фігурна
    Rule(r'фаліч|фалос|penis.?shape|cock.?shape|реалістичн.*анальн|анальний.*фалос',
         '6d3f4649980e79192f67254fc6971b2b', 'фалос'),
    Rule(r'фігурн|незвичайн|figure|unusual|special.*shape',
         '8368a46feb454e683dc5c491e65caf5f', 'фігурна'),
    Rule(None, '6dd869b40143c4d29474658156fe15d8', 'класична конусна'),
]


# ── 13948 Тип товару (білизна 7216) ──────────────────────────────────────────
# Розбиваємо на підтаблиці по категорії

LINGERIE_TYPE_RULES: list[Rule] = [
    Rule(r'бодістокінг|bodystocking',   'e02fa6f9dadbe471f2c210428d586e92', 'бодістокінг'),
    Rule(r'\bбоді\b|bodysuit',          '6d35224007856fb945bd731e61da562e', 'боді'),
    Rule(r'корсет|bustier|corset',      '0c633a64ca6b379fe300ea67c985cd4b', 'корсет'),
    Rule(r'пеньюар|peignoir|babydoll',  '8cdd0d60413e285a9b4efa8985c9da2f', 'пеньюар'),
    Rule(r'комбінезон|jumpsuit|playsuit','1f08dcbd0f926d93e3575a4db1b885f4', 'комбінезон'),
    Rule(r'сукн[яи]|dress\b',           '7622c904cc3f2a2e0e55b1662d6fb8b6', 'сукня'),
    Rule(r'панчохи|stockings?',         '2f28288483471e27d49a24d09dff8a38', 'панчохи'),
    Rule(r'колготки|легінс|tights?|legging','d71825c8609b574adb7665c9883c4c03', 'колготки та легінси'),
    Rule(r'бюстгальтер|бюст|bra\b|топ\b|top\b','59f8640461cd0554e8c0ef48345e9515', 'бюстгальтер та топи'),
    Rule(r'пояс (?:для )?панчох|garter.?belt','e75d4a283ecc3056f518f8317eb69bcc', 'пояси для панчох'),
    Rule(r'рукавич|gloves?',            'c41231894236402662574c55e030347e', 'рукавички'),
    Rule(r'гартер|garter\b',            '07ebd26ae4d6f68bb32927b88a47e2b1', 'гартери'),
    Rule(r'халатик|халат|robe\b',       'ef171afa152c9d38a7e872fdfa0eaacd', 'халатик'),
    Rule(r'шортики|short[sи]',          '8e7374e4a971916aaa1c1d0b74d56168', 'шортики'),
    Rule(r'комбідрес|комбі.дрес',       '037f0db5c8eecbb0aeec342febf08627', 'комбідрес'),
    Rule(r'трусики|труси|panties|thong|стрінги|стрінг|стреп.трусики|g-string',
         'd531ac32034e6c121872a457d3c84fe3', 'трусики'),
    Rule(r'комплект|set\b|набір.*білизни|lingerie.*set',
         '76aac5ba18403f8886f646a17983c2ad', 'комплект білизни'),
    # default
    Rule(None, '76aac5ba18403f8886f646a17983c2ad', 'комплект білизни'),
]

BDSM_TYPE_RULES: list[Rule] = [
    Rule(r'наручники|handcuff|wrist.*restraint',    '6b9ac6fbb995b98c0f11bdb0b5d455b9', 'наручники'),
    Rule(r'маска.*обличч|face.?mask|hood\b',        '8205d2da696832e1b91235d940046a17', 'маска для обличчя'),
    Rule(r"пов'язка на оч|blindfold|eye.?mask",     '1db36a28a0679ea0d595a9bde475b248', "пов'язка на очі"),
    Rule(r'кляп|gag\b',                             '35b220f73f1db9a37e66db65651c84e5', 'кляп'),
    Rule(r'батіг|флогер|flogger|whip\b',            'e6e6de9dd99aa4a63f24c9d3d0ee511f', 'батіг/флогер'),
    Rule(r'ляпалка|tawse|paddle\b',                 'e6af08edf57d25863c561152a9dcd2cb', 'ляпалка/тоуза'),
    Rule(r'стек\b|crop\b|riding.?crop',             '7f4bb02cc3e666aa81143d8d5046a57d', 'стек'),
    Rule(r'нашийник|collar\b|choker\b',             '985a8aaba212c9617a107b8e391fa4d8', 'нашийник'),
    Rule(r'повідець|leash\b',                       'f1b69bc9e325ebf6a9f47add6ddc1e50', 'повідець'),
    Rule(r'портупея|збруя|harness\b',               'd3b1441b45c1d6d510538a0dd0661b82', 'портупея/збруя'),
    Rule(r'пояс вірності|chastity',                 'ac9e8a36d5c6d152c7ab644bb9c08544', 'пояс вірності'),
    Rule(r'бандаж|фіксатор|restraint|bondage|tie\b','2fd3ff25d120b88dc12050794a97f39c', 'бандаж/фіксатор'),
    Rule(r'мотузк|rope\b',                          'a44aca161e27984fb8083c67bf09606f', 'мотузка бандажна'),
    Rule(r'розпірка|spreader|spider.?gag',          '4c383d5a41b75df954c716bfad04e724', 'розпірка'),
    Rule(r'свічк.*низькот|low.?temp.*candle|wax.?candle','21af507d88ac063c5d10bf0f24296ad9', 'свічки низькотемпературні'),
    Rule(r'колесо вартенберга|wartenberg',          '49cd3cf786fcb65ac7ed7a9904c79269', 'колесо вартенберга'),
    Rule(r'лоскоталка|feather.?tickler|tickler\b',  '4afb496ad33f1a33addbd028f485ddac', 'лоскоталка'),
    Rule(r'затискач.*сосків|nipple.?clamp',         'f1972fc2a926191774e9ea33aed47a72', 'затискач для сосків та клітора'),
    Rule(r'поножі|leg.*cuff|ankle.*restraint',      '40b5d04620efe63663575a2b5255616e', 'поножі'),
    Rule(r'рукавичка.*стимул|stimulation.?glove',   'ff48f176db1732678c90f7215fa9589b', 'рукавичка для стимуляції'),
    Rule(r'електростимул|electric.*stimul|e.?stim\b','ac425d182d669fa337ae89f088d7414a', 'електростимулятори'),
    Rule(r'набір.*bdsm|bdsm.*kit|bdsm.*набір|набір.*зв\'яз','a1142b235b279ca1b7b54a5f79d586ea', 'набір речей'),
    Rule(None, '2fd3ff25d120b88dc12050794a97f39c', 'бандаж/фіксатор'),
]

ANAL_TYPE_RULES: list[Rule] = [
    Rule(r'смарт.?пробка|smart.*plug|bluetooth.*plug|app.*plug',
         '7661e625d2b5b92869c8c9534e0814c2', 'анальна смарт-пробка'),
    Rule(r'ялинк|christmas.?tree|beaded.*plug|xmas',
         '21045a0b4f280f281560ed2b2cb29d4e', 'анальна пробка-ялинка'),
    Rule(r'розширювач|expander|tunnel\b|дилятатор',
         '19f43b6db2c945621d1bbf4160755a2e', 'анальний розширювач'),
    Rule(r'тунель|anal.?tunnel|tunnel.?butt',
         '99ec19f29f58b1741074b5ae693cf702', 'анальний тунель'),
    Rule(r'фістинг|fisting',                         '0f9ce3349647beb6f3401849e44d46a8', 'іграшки для фістингу'),
    Rule(r'душ|enema|douche\b',                      'cda234f155b08983cdd8039c8231970f', 'анальний душ'),
    Rule(r'гак|hook\b',                              'e5299e794e7f73c9e7c7622eb062ca52', 'анальний гак'),
    Rule(r'набір.*анальн|anal.*kit|anal.*set',        '085b4d2de7b7959b32194f2fe97ea806', 'набір'),
    Rule(None, 'f48421e09fd29eea23eaa68bd3ea5ce6', 'класична анальна пробка'),
]


# ── 13949 Призначення (7216 Еротична білизна) ─────────────────────────────────

LINGERIE_PURPOSE_RULES: list[Rule] = [
    Rule(r'чоловіч|чолов[иі]к|men[\'s]*\b|male\b|для нього|boy',
         '3bfb52d4533ffb8a66ab41d07facbfd9', 'для чоловіків'),
    Rule(None, '2df60ee4b4ae7a7ce424886357dcd1f1', 'для жінок'),
]


# ── 5249 Тип помпи (9476 Помпи) ───────────────────────────────────────────────

PUMP_TYPE_RULES: list[Rule] = [
    Rule(r'електрична|автоматична|electronic|auto.?pump|electric',
         '83a176bd806d7459c8ed6b69479a6cec', 'автоматична (електрична)'),
    Rule(None, '58d2f532e79f09a39bfc76c250b4e4f6', 'ручна'),
]


# ── 3369 Призначення (9476 Помпи) ─────────────────────────────────────────────

PURPOSE_PUMP_RULES: list[Rule] = [
    Rule(r'тренування|kegel|тренаж',
         '41e42da18100c9346f99630a37c8471a', 'для тренування'),
    Rule(r'збільшення|enlarg|збільш.*член',
         '8e358fe1181b2e9ebde8d54c32db45de', 'для збільшення члена'),
    Rule(r'корекція|peyronie|викривлення',
         '71cd6cee6e2ac56a8dc1257572879ad8', 'для корекції викривлення'),
    Rule(r'груд|breast|для жінок|сосків',
         '392e33a4b4d4d64761d80953c7069e94', 'для стимуляції грудей'),
    Rule(r'вульв|клітор|vagina|стимуляці[яї].*жін',
         '97dd299c4bb7b66f4d7ace76a9efe464', 'для стимуляції вульви'),
    Rule(None, 'ce5d7b6ce5d8db888c530783868852f1', 'для покращення ерекції'),
]


# ── 3369 Призначення (9470 Ерекційні кільця) ──────────────────────────────────

PURPOSE_RING_RULES: list[Rule] = [
    Rule(r'продовж|тривалість|delay|last.?long',
         '69eacd63ddd33d1c2ace3c76e1bc0404', 'продовження статевого акту'),
    Rule(r'посилення відчуттів|sensation|stimulat',
         '7195622b611090721641472f3a4a5eba', 'посилення відчуттів'),
    Rule(r'стимуляція партнера|партнер.*стимул|couples?',
         '9d01a583ae15b7ae3fd8e458398f98c7', 'стимуляція партнера'),
    Rule(None, '5c87ea053911007199e66915d9060bec', 'підтримка ерекції'),
]


# ── 437 Тип кріплення (9482 Страпони) ────────────────────────────────────────

STRAPON_MOUNT_RULES: list[Rule] = [
    Rule(r'без ремен|внутрішн|strapless|backless',
         '38a909f5959d4e98dbe6f55ae3255782', 'без ременів (внутрішній)'),
    Rule(None, 'ae03241633b64d5311c3077f909e6bc1', 'на ременях'),
]


# ── 3103 Тип приладу (9482 Страпони) ─────────────────────────────────────────

STRAPON_TYPE_RULES: list[Rule] = [
    Rule(r'вібратор|вібр|vibrat',
         '56c84cae1d1a2c5f5a13a97e5dc08f93', 'нестандартний вібратор'),
    Rule(None, 'ea170a0be975f6ae1e73dcd845248743', 'ручний'),
]


# ── 13037 Конструкція (9482 Страпони) ────────────────────────────────────────

STRAPON_CONSTRUCTION_RULES: list[Rule] = [
    Rule(r'подвійн|double',
         '0fba418bedb2dbb9ca04d9e368d434cb', 'подвійні'),
    Rule(r'вагінальн.*насадк|з насадк',
         '9315ec8361f1dc5713ed3a7252c551d1', 'з вагінальною насадкою'),
    Rule(None, '5de36749ccc12ecf67b1e14f626b5d6a', 'одинарні'),
]


# ── 13037 Конструкція (9474 Насадки) ─────────────────────────────────────────

ATTACHMENT_CONSTRUCTION_RULES: list[Rule] = [
    Rule(r'подвійн.*проникнення|double.*penetrat|\bDP\b',
         'c6db38b5a5c9b6f5e5332a61ce5de108', 'для подвійного проникнення'),
    Rule(r'подвійн|double',
         '0fba418bedb2dbb9ca04d9e368d434cb', 'подвійні'),
    Rule(r'анальн.*пробк|with.*plug',
         '2b4a8e775cdf8e491679ea56e591dcf8', 'з анальною пробкою'),
    Rule(r'ерекційн.*кільц|cock.?ring',
         '2f64d84da01369f43371350974fb0e3d', 'з ерекційним кільцем'),
    Rule(r'мошонк|balls?|яєчк',
         '81cbe5ed7ceb6baf2cd256b381ce3bb3', 'з отвором для машонки'),
    Rule(None, '5de36749ccc12ecf67b1e14f626b5d6a', 'одинарні'),
]


# ── 13037 Конструкція (9470 Ерекційні кільця) ────────────────────────────────

RING_CONSTRUCTION_RULES: list[Rule] = [
    Rule(r'подвійн.*проникнення|double.*penetrat|\bDP\b',
         'c6db38b5a5c9b6f5e5332a61ce5de108', 'для подвійного проникнення'),
    Rule(r'потрійн|triple',
         'ec1178233b1e93703f97fe955518c934', 'потрійні'),
    Rule(r'подвійн|double',
         '0fba418bedb2dbb9ca04d9e368d434cb', 'подвійні'),
    Rule(r'анальн.*пробк|butt.*plug',
         '2b4a8e775cdf8e491679ea56e591dcf8', 'з анальною пробкою'),
    Rule(None, '5de36749ccc12ecf67b1e14f626b5d6a', 'одинарні'),
]


# ── 7215 Тип насадки (9474) ───────────────────────────────────────────────────

ATTACHMENT_TYPE_RULES: list[Rule] = [
    Rule(r'потовщ|thicken|enlarging',
         '680c632d3d7a4fa3f64a69d2b2341694', 'потовщуюча'),
    Rule(r'обмежув|restrict|delay|продовж',
         '330e7f14661d81722f39b88f453a93ea', 'обмежувальна'),
    Rule(None, '513b69aa32e21d66822c4ac952e8d0c2', 'подовжуюча'),
]


# ── 7192 Текстура поверхні (9474 Насадки) ────────────────────────────────────

ATTACHMENT_TEXTURE_RULES: list[Rule] = [
    Rule(r'вусик|antennae|ribs?',
         '118d5e38817134f079400d9a72cfcf3b', 'з вусиками'),
    Rule(r'язич|tongue',
         '85a814e4cb141f9bf1a799a245915d59', 'з язичком'),
    Rule(r'шипи|шипуват|spike',
         'f670ab31757e8ed86e019f078da161d3', 'з шипами'),
    Rule(r'рельєф|ribbed|nub',
         '9eb625e119ca4b3a633eb80658316169', 'з рельєфом'),
    Rule(None, '76b77d596b79601ffc09f67f40b01e47', 'гладка'),
]


# ── 9695 Тип кільця (9470) ────────────────────────────────────────────────────

RING_TYPE_RULES: list[Rule] = [
    Rule(r'петля|lasso|loop',
         '3a6c1519920ca1681dc3fad26bb981d6', 'петля'),
    Rule(r'з фалосом|з вібратором.*кільц|фалос.*кільц',
         '5cd9b73215df132b7bf04070be4f3d81', 'кільце з додатковим фалосом'),
    Rule(r'набір|set.*ring|ring.*set',
         '27e826161d9625f69453963c5202b257', 'набір'),
    Rule(None, '5e54c648c3fef9b78719eccac963f0f6', 'кільце'),
]


# ── 9698 Текстура поверхні (9470 Кільця) ─────────────────────────────────────

RING_TEXTURE_RULES: list[Rule] = [
    Rule(r'вусик|antennae|ribs?',
         '9bc798386758cc5e66f2ad436acad5e9', 'з вусиками'),
    Rule(r'язич|tongue',
         'dc7df84e9e3eca8e5363afc3b9aed960', 'з язичком'),
    Rule(r'шипи|шипуват|spike',
         'e9e84a451c11406bf55b38b7d957025a', 'з шипами'),
    Rule(r'рельєф|ribbed|nub',
         'a77f5bc4b6ae1e0d9ccecb5e8adc11e2', 'з рельєфом'),
    Rule(None, '0094a04f4321daee94111dda8b152396', 'гладка'),
]


# ── 13948 Тип товару (9460 Приколи) ──────────────────────────────────────────

PRANK_TYPE_RULES: list[Rule] = [
    Rule(r'\bмило\b|soap\b',
         '596dc71c49bfd3ed32b6ca944d29c0ce', 'мило'),
    Rule(r'еротична гра|секс.*гра|гра.*кубик|кубик.*гра|dice|еротичн.*ігр',
         '59c302707067e3a7675a89142fca9034', 'еротичні ігри'),
    Rule(r'антистрес|anti.?stress',
         '983fd6a1379e40575f9f7f59e3fd9e2c', 'антистрес'),
    Rule(r'наліпк|пестис|pasties|nipple.pad',
         'bcc59e00b42e18efa339b69e5fca85cd', 'наліпки'),
    Rule(r'фігурк|figurine|статуетк',
         'f70fccdfc96d66897f69f325e7957156', 'фігурка'),
    Rule(r'картина|poster|плакат|picture',
         '2730e5dde7f7ebfe74a325b0770eb147', 'картина'),
    Rule(r'декор\b|decoration',
         '356e8f6b4e33031c609637266d60341e', 'декор'),
    Rule(r"м'яка іграшка|плюш|stuffed|toy\b",
         '51e6a82b2b01b2c1dd9749c8387467f1', "м'яка іграшка"),
    Rule(r'посуд|чашк|кружка|mug\b|стакан',
         'e6ffd04fcf0c1543ed43db91c02f7909', 'посуд'),
    Rule(r'фартух|apron',
         '8f80abc313ec9ab337903d16ffd66496', 'фартух'),
    Rule(None, '085b4d2de7b7959b32194f2fe97ea806', 'набір'),
]


# ── 13954 Тип товару (9478 Кульки) ───────────────────────────────────────────

BALLS_TYPE_RULES: list[Rule] = [
    Rule(r'намисто|beads?\b|anal.*bead|вагінальн.*намист',
         '0cba9a973d0242699d99eb3c08e81cd8', 'намисто'),
    Rule(r'тренажер|kegel|тренув',
         '7839cb8acdf115292e097580e4a733af', 'тренажер'),
    Rule(None, '59dca8ccd16502db50525f1b9d274f78', 'кульки'),
]


# ── 15743 Стать (9628/9630/9632) ─────────────────────────────────────────────

GENDER_RULES: list[Rule] = [
    Rule(r'для чоловіків|чоловіч|men[\'s]*\b|male\b|для нього',
         '589e7a59764295be9e3763bb14cfec3d', 'для чоловіків'),
    Rule(r'для жінок|жіноч|women|female|для неї',
         '20fd9bd461d8f2a4c634e2aba51d2222', 'для жінок'),
    Rule(None, 'afe256eeeee25b956f76e3a4707eb373', 'унісекс'),
]


# ── 15763 Тип продукту (9628 Оральні засоби) ─────────────────────────────────

ORAL_TYPE_RULES: list[Rule] = [
    Rule(r'бальзам для губ|lip.*balm',
         '59c049c2730c09a70f68ed90b39e1c48', 'бальзам для губ'),
    Rule(r'льодяник|леденец|lollipop|candy',
         '1c5fc3665728d4fa8e4532bc96f50b38', 'льодяники'),
    Rule(r'спрей|spray',
         'ccfd04b999bb00160911cfca28877a55', 'спрей'),
    Rule(r'крем\b|cream',
         'eb130c2013437f6941dae062dd146893', 'крем'),
    Rule(r'олія\b|oil\b',
         '8fe5fd8a48d30a04cb19894c3cf7dc2e', 'олія'),
    Rule(None, '22c158a4f13d2716e3c06c3ef398e364', 'гель'),
]


# ── 15765 Смак (9628 Оральні засоби) ─────────────────────────────────────────

TASTE_RULES: list[Rule] = [
    Rule(r'шоколад.*кокос|choco.*coco',
         '52435160e489ef85e58651921183b9a8', 'шоколад-кокос'),
    Rule(r"шоколад.*м'ят|choco.*mint",
         '3de9d71fddbf0eba4ab58520920471f4', "шоколад-м'ята"),
    Rule(r'солона карамель|salted caramel',
         '9b15f71d343a6db611076aa19648abab', 'солона карамель'),
    Rule(r'солодкий ром|sweet rum',
         '60480df0e7202d61325d0c64d39a3d4f', 'солодкий ром'),
    Rule(r'цукрова вата|cotton candy',
         '35fb483fd97dd3b9487b36a4b14b9db9', 'цукрова вата'),
    Rule(r'кориця|cinnamon',
         '8c8ae475a7dbdbb2a28b25a85e04145d', 'кориця'),
    Rule(r'карамел|caramel',
         '40192269ed283d803210b006107195fb', 'карамель'),
    Rule(r'шоколад|chocolate',
         '63ff7ca57a6edd2f1cb05246f72a0fef', 'шоколад'),
    Rule(r'гранат|pomegranate',
         '9692da0a18b6986c227a3dce79f2b836', 'гранат'),
    Rule(r'кавун|watermelon',
         'e5f67e2224292f2162b6047f44b321b3', 'кавун'),
    Rule(r'банан|banana',
         'b2559acd776ecd29e5b92ddb060b05af', 'банан'),
    Rule(r'вишн|cherry',
         'b820ab8441af6f733527dd7b40bdb781', 'вишня'),
    Rule(r'полуниц|strawberry',
         '4e52de5698e45d7477ecb0ec77dc1bc3', 'полуниця'),
    Rule(r"м'ят.*жуйк|mint.?gum|spearmint",
         '239ab87ec9412001013342b58c8b38d9', "м'ятна жуйка"),
    Rule(r"м'ят|mint",
         '239ab87ec9412001013342b58c8b38d9', "м'ятна жуйка"),
    Rule(r'ваніль|vanilla',
         'cce73c0012a1cab0f3de154e1832d2c9', 'ваніль'),
    Rule(r'персик|peach',
         '3e502d8c94066e00e4c14527babde161', 'персик'),
    Rule(None, 'cfb19aa8dfaeff042e17f6567cc22764', 'без смаку'),
]


# ── 15766 Аромат (9628) / 15744 Аромат (9630/9632) ───────────────────────────

AROMA_ORAL_RULES: list[Rule] = [
    Rule(r"шоколад.*м'ят|choco.*mint",
         'a6c9692b3d877df346c8b0ee69092719', "шоколад-м'ята"),
    Rule(r'шоколад.*кокос|choco.*coco',
         '06437f6199c0bc00cbad2b33827d3fe0', 'шоколад-кокос'),
    Rule(r'солона карамель|salted caramel',
         '5fa53a365e4e6894e9a04a3c63f1ca8a', 'солона карамель'),
    Rule(r'солодкий ром|sweet rum',
         '79778057259e0ce5f55b997f75674680', 'солодкий ром'),
    Rule(r'цукрова вата|cotton candy',
         '2d0fe25d50e601c57f77845aef08c948', 'цукрова вата'),
    Rule(r'кориця|cinnamon',
         '6adfbee1d72e95f1de012912fe2bde23', 'кориця'),
    Rule(r'карамел|caramel',
         'bbcefa1d65fb063adbff0ae65d60d603', 'карамельний'),
    Rule(r'шоколад|chocolate',
         'e8a72db9ded990db41fb385dead2135e', 'шоколадний'),
    Rule(r'кав|coffee',
         '257e9edd80bf2ea5736c21742cc81ccd', 'кавовий'),
    Rule(r'кавун|watermelon',
         'bc9bfb310191577ba21bdf815a2eca80', 'фруктовий'),
    Rule(r'ягід|berry|черниц|малин',
         '1fe614445688c332d6e519581273581c', 'ягідний'),
    Rule(r'фрукт|fruit|цитрус|lemon|апельсин|orange',
         '63ca8d16ffe373132c8a07b0a1762c7b', 'цитрусовий'),
    Rule(r'квіт|floral|rose|троянд|жасмин',
         '1acdb9c57e0ddd8f4ad8461baf08d155', 'квітковий'),
    Rule(r"м'ят.*жуйк|mint.?gum",
         'c84bc08c2eec15809f3841730501c20e', "м'ятна жуйка"),
    Rule(r"м'ят|mint",
         'a8de4145d9acf606020dcd3a8de46331', "м'ятний"),
    Rule(r'ваніль|vanilla',
         '1bef258ffa9282447895281783067577', 'ванільний'),
    Rule(None, '1f6ae763bba2e0b4f93b953b98f6a279', 'без аромату'),
]

AROMA_OIL_RULES: list[Rule] = [
    Rule(r'вишн|cherry',
         '83bb2a1d528cb956e5626d9d62c7dab9', 'вишня'),
    Rule(r'троянд|rose',
         '39a3610238b44a979563fc505608c2fe', 'троянда'),
    Rule(r'кокос|coconut',
         'bf050931e55813c1bae0b43ecede2340', 'кокос'),
    Rule(r'ваніль|vanilla',
         '0177795c5f65978121724dbe39a6d354', 'ваніль'),
    Rule(r'полуниц|strawberry',
         '82866d9b49603a3ca46012868d7cc071', 'полуниця'),
    Rule(r'шоколад|chocolate',
         '76158842fefb55877710d34a7d703431', 'шоколад'),
    Rule(r'кавун|watermelon',
         'e2a11898f91a71dccd2ea0ccea271ec5', 'кавун'),
    Rule(r'мікс|mix|assort',
         '32945736a530b2c17cc615293ef4f630', 'мікс'),
    Rule(None, '0e3b32475885f780ea9c3728fd587c3e', 'без аромату'),
]


# ── 15762 Тип воску (9630 Свічки) ────────────────────────────────────────────

WAX_TYPE_RULES: list[Rule] = [
    Rule(r'соєвий|soy',
         '9dfc0cf71c1376cc61a97e768ae9da4d', 'соєвий'),
    Rule(r'кокосовий|coconut',
         '5f27bd641640ba262d0944172f65c833', 'кокосовий'),
    Rule(r'бджолиний|beeswax',
         '1b13399009d2c5d067ff178d30f74841', 'бджолиний'),
    Rule(r'парафін|paraffin',
         '0df8c8e1e62a63a084c74ccb3a18d81d', 'парафін (рафінований косметичний)'),
    Rule(None, 'b9adcb5f98fa19e8378374317642f428', 'комбінований'),
]


# ── 15774 Тип упаковки (9628 Оральні засоби) ─────────────────────────────────

ORAL_PACKAGE_RULES: list[Rule] = [
    Rule(r'тюбик|tube\b',
         '986e24d01dff31cf5446d798d0dfef65', 'тюбик'),
    Rule(r'розпил|спрей|spray',
         '21db6d2090bf107fb8fa3c3144bfaf9c', 'пляшка з розпилювачем'),
    Rule(None, 'a597b26c4832259448357f0b1ccf531c', 'пляшка з дозатором'),
]


# ── 15761 Час горіння (9630 Свічки) ──────────────────────────────────────────

CANDLE_BURN_RULES: list[Rule] = [
    Rule(r'10\+\s*год|більше\s+10|понад\s+10|over\s+10\s*h',
         'ca0b7a247c89d9c920bbf42048c3fb80', '10+ годин'),
    Rule(r'[6-9]\s*-\s*10\s*год|від\s+6\s+до\s+10|6.{0,5}10\s*h',
         'c217c9f0ccea2d5528a840029c491830', '6-10 годин'),
    Rule(r'[3-5]\s*-\s*6\s*год|від\s+3\s+до\s+[56]|3.{0,5}6\s*h',
         '081d8cd619fa1bdc4f4bfa1399a2633a', '3-6 годин'),
    Rule(None, 'f3586e6130f87c9615776bf4dd4cc096', 'до 3 годин'),
]


# ── Тип аксесуара (9526/9616/9620) ───────────────────────────────────────────

ACCESSORY_TYPE_9526_RULES: list[Rule] = [
    Rule(r'пульт|controller|remote',
         '9f51557047ec89e5743e26107e0d4864', 'пульт керування'),
    Rule(r'нагрівач|warmer|heater',
         'cca0882a14b8903c1e7d20cdcda2fe61', 'нагрівач'),
    Rule(r'зарядн.*кабель|charging.*cable|usb.*cable',
         'a06b51081b6beb43e8ac80a1ae66cc2f', 'зарядний кабель'),
    Rule(r'зарядн|charger|зарядка',
         'f7a96ed34dbf7073bd5523464817c4c8', 'зарядний пристрій'),
    Rule(r'чохол|сумка|pouch|bag\b|carrying.*case',
         'e03456dd90ea3d00b2ff8ef4599ccd7d', 'чохол для зберігання'),
    Rule(r'адаптер|adapter',
         '396ea72ba53626d5f7b23c94450e9f48', 'адаптер'),
    Rule(r'магнітний замок|magnetic.*lock',
         'beb852c6f172722ca00fe1a376bb3238', 'магнітний замок для вібратора'),
    Rule(r'аплікатор|applicator',
         '55f2ef8df84e6656f16b41de755c6a8a', 'аплікатор для введення лубриканту'),
    Rule(r'підставка|stand\b',
         '2a66bea39390abe3fda0443bd0c39d63', 'підставка'),
    Rule(r'тримач|holder',
         '2ae39556fea85ebcd49e007371866613', 'тримач'),
    Rule(r'фіксатор|fixator|clip\b',
         '5f2ed24690c4e02491a0dced62b3f011', 'фіксатор'),
    Rule(r'dok.?stanciya|dok.?станція',
         '96256be23dc4b0197f3ba8a6c41411bb', 'док-станція'),
    Rule(None, '81514b591c7a1bbf74c43f5522d66c79', 'насадка'),
]

ACCESSORY_TYPE_9616_RULES: list[Rule] = [
    Rule(r'адаптер|adapter',
         'd8adbcd2f3981e4d3d7e014888f34f5d', 'адаптер'),
    Rule(r'набір|kit\b|set\b',
         '360795787116b5636e333e5e79fe8cb8', 'набір'),
    Rule(r'o.ring|о-ринг|кільце.*ремін',
         'd8f84c79dafb127614087f31af9fc132', 'кільце O-ring'),
    Rule(r'трусики|harness.*pantie|underwear',
         '6733002e5bc542ad8e2a5b12bd2ed83c', 'трусики'),
    Rule(r'ремінь|strap|belt\b',
         '234138e68fd74b6fbd375a6823d69ed0', 'ремінь'),
    Rule(None, 'a6cedddb3dd9801b9eb58a25240ecfd1', 'насадка'),
]

ACCESSORY_TYPE_9620_RULES: list[Rule] = [
    Rule(r'набір|kit\b|set\b',
         'f05569b201fede6b0a0766dcf1eecd15', 'набір'),
    Rule(r'рукав|sleeve',
         '40c6f7ebcf54be3ff5b390b83fe225c0', 'рукав'),
    Rule(r'кріплення|mount|attachment',
         'ad9112002634690f5e5432d9722ca6b7', 'кріплення'),
    Rule(r'нагрівач|warmer|heater',
         '9166dee182aef89f09c8ce907cc37b55', 'нагрівач'),
    Rule(r'кабель|cable',
         '9bbced3c73e873177027add3ad13290c', 'кабель'),
    Rule(r'ремінь.тримач|strap.*holder',
         'f34f2ca3e1f239c1747b7e821fb3f4bb', 'ремінь-тримач'),
    Rule(r'сушарка|dryer',
         'd78ac4a07e2cbdab7ab541c0bca156e1', 'сушарка'),
    Rule(r'кейс|case\b',
         'b4a3d1ec0a8b89f04334dbb18615f14f', 'кейс для зберігання'),
    Rule(r'адаптер|adapter',
         'aa200ed0b821627f831f44af9da2f3f2', 'адаптер'),
    Rule(r'підставка|stand\b',
         '71e9869f23aae1f559ad9c93ccda442e', 'підставка'),
    Rule(None, 'f05569b201fede6b0a0766dcf1eecd15', 'набір'),
]


# ── 14024 Тип засобу (9448 Догляд за секс-іграшками) ────────────────────────

TOY_CARE_TYPE_RULES: list[Rule] = [
    Rule(r'стік|stick\b|абсорб',
         '4cb2bc85b04b367161d954541255bc45', 'абсорбуючий стік'),
    Rule(r'гель|gel\b',
         '65ea800b6e18ada136f057176ddcf904', 'гель'),
    Rule(r'порошок|powder',
         '2a6365d78c2a145a22cfab59c24e499e', 'порошок'),
    Rule(None, '882d38d32484b266598b0b5df6bd044f', 'спрей'),
]


# ── 14036 Дія (9448 Догляд за секс-іграшками) ───────────────────────────────

TOY_CARE_ACTION_RULES: list[Rule] = [
    Rule(r'догляд|відновлен|кондиціон|latexpflege|shine|polish|полегшен|блиск',
         '55ebe1954182bff03acb2500ee138344', 'догляд та відновлення'),
    Rule(r'антибактер|дезінфекц|дезинфекц|antibacterial|disinfect|antiseptic',
         '2cdd05843b09b9dc82717252eeffdf96', 'антибактеріальна дезінфекція'),
    Rule(None, '24bcf344a8598793d5f12d97ce1db671', 'очищення'),
]


# ── 15764 Основа засобу (9636 Пролонгатори) ─────────────────────────────────

PROLONGER_BASE_RULES: list[Rule] = [
    Rule(r'гібридн|hybrid',
         '04470539484fff0f1ab35238861bfe42', 'гібридна'),
    Rule(r'силікон|silicone',
         '5482fc20c96bf79efe33edd12f7aa41d', 'силіконова'),
    Rule(r'олі[ї]|oil.based|olii|рослинн.*олі',
         '374b671d69f63d56c50cb6778517b3ec', 'олійна'),
    Rule(None, '655aee74a9bc18e095a36e0ace285957', 'водна'),
]


# ── 15780 Тип (9636 Пролонгатори) ───────────────────────────────────────────

PROLONGER_TYPE_RULES: list[Rule] = [
    Rule(r'крем|cream',
         '3a232c7fc6ddb26fe542b71698a0262b', 'крем'),
    Rule(r'краплі|drops?\b',
         '37a54a478ba5211989f1592340096d72', 'краплі'),
    Rule(r'олі[яї]\b|oil\b',
         'cd4ff5cb20d1630e64ff8ca6160ba22c', 'олія'),
    Rule(r'гель|gel\b',
         '2081780bd863198da7f5bc178588ab25', 'гель'),
    Rule(r'сироватк|serum',
         'bf7ce4b60a6236a3af32db79396b942d', 'сироватка'),
    Rule(None, '67d3b0873c3cffbd68b4dd56046ed66a', 'спрей'),
]


# ── 15719 Тип (9578 Меблі для сексу) ────────────────────────────────────────

SEX_FURNITURE_TYPE_RULES: list[Rule] = [
    Rule(r'гойдалк|swing',
         '1759981ee27701a2a322e2bb1fa1d3eb', 'секс-гойдалка'),
    Rule(r'матрац|mattress',
         '80483e070f6410be0910d6e6917a65d6', 'секс-матрац'),
    Rule(r'пуф|pouf|пуфик',
         '0e2e8e4271fd8a781e8e7e64f6f03604', 'секс-пуф'),
    Rule(r'тантричн|tantr',
         'a2977a7c566632142fa821209e95f472', 'тантричне крісло'),
    Rule(r'подушк|pillow|cushion',
         'acc6d61ded731af66ad2439e421b354c', 'позиційна подушка'),
    Rule(r'лав[аи]|bench|клітк|cage|хрест|cross|конструкц|фіксатор|розтяжк|поруч|підвіс|стілець|chair',
         '3773bd81a7eab2643bc4978752ed50ae', 'секс-стілець'),
    Rule(None, 'acc6d61ded731af66ad2439e421b354c', 'позиційна подушка'),
]


# ── 15720 Основний матеріал (9578 Меблі для сексу) ──────────────────────────

SEX_FURNITURE_MATERIAL_RULES: list[Rule] = [
    Rule(r'натуральна шкіра|genuine leather|real leather',
         '1f7a4ffa0218e37397f1c844ee49c22c', 'натуральна шкіра'),
    Rule(r'екошкіра|eco.?leather|pu.?leather|штучна шкіра|faux leather',
         '1804a21bf7692f29c286a2fccd5695a0', 'екошкіра'),
    Rule(None, '4c956983cc191fb2b06a0d2425ead871', 'текстиль'),
]


# ── 14806 Тип анального душу (9550 Анальний душ) ────────────────────────────

ANAL_DOUCHE_TYPE_RULES: list[Rule] = [
    Rule(r'душов.*насадк|shower.*nozzle|насадк.*для.*душу',
         '2eb11633c7413349e6a9b6a16da16448', 'душова насадка'),
    Rule(r'дорожн|travel',
         '610a20af7843f6d0d07fbf4038edaf02', 'дорожній набір'),
    Rule(None, 'c75047fb0691e99395f7a5e929db8a15', 'система з резервуаром'),
]


# ── 14807 Тип використання (9550) ───────────────────────────────────────────

ANAL_DOUCHE_USAGE_RULES: list[Rule] = [
    Rule(r'стаціонарн|стаціонар|fixed|wall',
         'cdd79646e41a469bb050f4225934c5e3', 'стаціонарний'),
    Rule(r'портативн|portable|compact',
         '3b1dff36aba9a09d812c2c1ac2f789f8', 'портативний'),
    Rule(None, '177ff13eef8aed67d49d0ef27ef824f8', 'ручний'),
]


# ── 14808 Тип підключення (9550) ─────────────────────────────────────────────

ANAL_DOUCHE_CONNECT_RULES: list[Rule] = [
    Rule(r'до душ|до шланг|shower.*hose|hose.*connect',
         '3a3c771cf03236fdee9b277d246064fa', 'до душового шланга'),
    Rule(r'до змішув|до крану|to.*tap|faucet',
         'b6c07b77a366ca9b4c73075a97b99ad4', 'до змішувача'),
    Rule(None, '5c0ab583c01187b1ad175973f1595432', 'автономний резервуар'),
]


# ── 14810 Тип наконечника (9550) ────────────────────────────────────────────

ANAL_DOUCHE_TIP_RULES: list[Rule] = [
    Rule(r'вигнут|curved|кривий',
         'b0e3c25021879f9280da0be2ba4d8687', 'вигнутий'),
    Rule(r'конічн|conic|conical',
         '08a59d3de47f3c1ddfab185e3c04113e', 'конічний'),
    Rule(r'анатомічн|anatomic',
         '7149fd8fda0f8b4863316f2a8e1e8c33', 'анатомічний'),
    Rule(None, '1596b7a56ad1279a59b0fff02d1468f2', 'прямий'),
]


# ── 13008 Матеріал наконечника (9550) ────────────────────────────────────────

ANAL_DOUCHE_TIP_MAT_RULES: list[Rule] = [
    Rule(r'силікон|silicone',
         '932516ad62ca6bcb4c3da00024655ee9', 'силікон'),
    Rule(r'сталь|steel|метал|metal',
         '890c7f017ec0f40229fcce7d295b45d4', 'сталь'),
    Rule(r'скло|glass',
         '7fa98c083d0b33f3374624ddb5a543cc', 'скло'),
    Rule(r'pvc|пвх|полівіній',
         '5030098e32611d456547c01305446e61', 'PVC'),
    Rule(r'пластик|plastic',
         'd40d23bea41b84acfa48a002a19ddddb', 'ABS пластик'),
    Rule(None, '932516ad62ca6bcb4c3da00024655ee9', 'силікон'),
]


# ── 2839 Матеріал шланга (9550) ──────────────────────────────────────────────

ANAL_DOUCHE_HOSE_MAT_RULES: list[Rule] = [
    Rule(r'силікон|silicone',
         '73dbdc4b75148d202d80de7da41d639f', 'силікон'),
    Rule(r'гума|rubber|каучук',
         '23c6a24a312cf21727a7071ca9866377', 'гума'),
    Rule(r'нержавіюч|stainless',
         'f8d6840ed619f1b27f780094aa84f02d', 'нержавіюча сталь'),
    Rule(None, '495129865b568d6bf5a81a526111efbb', 'пвх'),
]


# ── 3369 Призначення (9550 Анальний душ) ─────────────────────────────────────

ANAL_DOUCHE_PURPOSE_RULES: list[Rule] = [
    Rule(None, '52abbc42ff3aa782532d7772cc080248', 'анальні'),
]


# ── 9468 Секс-ляльки ──────────────────────────────────────────────────────────

DOLL_GENDER_RULES: list[Rule] = [
    Rule(r'\bjames\b|\bчоловіч', '17be150f785456064909af49f6adc9a4', 'чоловіча'),
    Rule(None,                   '94764ca42ce35e998df6226ff4706a84', 'жіноча'),
]

DOLL_HAIR_RULES: list[Rule] = [
    Rule(r'redhead|red.head|рудий',        'cbfe098602ee0b1f9af6e8dbf1daaa3c', 'рудий'),
    Rule(r'blonde|blond\b|блонд',          'bff8f0f023eb1f0295a6ed3f0fb64bae', 'блонд'),
    Rule(r'brunette|brune[t]|брюнет',      '51e7a740cec0c8a57bae144b0be378b5', 'брюнет'),
    Rule(r'bald|без волосся|лисий',        '8add402e4714937a9d55942c21e8dd48', 'без волосся'),
    Rule(r'рожев|pink.hair',               '0e3618c68297fcad48c41b1f27086c3a', 'рожевий'),
    Rule(None,                             '266c3b842eddcb72d5ea2eee7e0ca272', 'шатен'),
]

DOLL_TYPE_RULES: list[Rule] = [
    Rule(r'торс|torso',                    'f49bc54e184a3395e79686b53ded32dc', 'торс'),
    Rule(r'частина тіла|body.part',        '629e548dc63fa18b2ed91ee507b6e758', 'частина тіла'),
    Rule(None,                             '002568ed73679bcbb17e2e12157a3a85', 'тіло повністю'),
]

DOLL_FIGURE_RULES: list[Rule] = [
    Rule(r'спортив|athletic|sport\b',      '89ff0d5e51686481c0017b7825ed82cc', 'спортивна'),
    Rule(r'plus.siz|плюс.сайз|curvy',     '14483a2fc1052b008a2eb0ec43339469', 'плюс-сайз'),
    Rule(r'худорлява|thin|slim\b',         '90c246c91f496abbe99a8611801caa70', 'худорлява'),
    Rule(None,                             '4b744e43b7254c48283119dc2b904869', 'середня'),
]

DOLL_POSE_RULES: list[Rule] = [
    Rule(r'сидяч|sitting|seated',          'f4f567b3df597f712b4f26112ba7029d', 'сидяча'),
    Rule(r'стояч|standing',               '295ad0c441121be2307ae89a10ea98ff', 'стояча'),
    Rule(r'гнучк|flex|posable',           '95a6aa6096b5681a5575f5f91d9d04a1', 'гнучка'),
    Rule(r'змінна|multiple|various|різн', 'd1f46868de9c55bcd32f521ab44ed7d1', 'змінна поза'),
    Rule(None,                            'd7046f943855e86277ac395a413fcd1e', 'лежача'),
]


# ── 11932 Рівень жорсткості (9548 Анальні розширювачі) ───────────────────────

PLUG_HARDNESS_RULES: list[Rule] = [
    Rule(r'дуже м.який|ultra.*soft|super.*soft|xtra.*soft',
         '979d47b117067d862aa9cfc9b9b1d2e5', 'дуже м\'який'),
    Rule(r'м.який|soft\b',
         '334f80efeb8fe835bd1a6c5b65bcfdb1', 'м\'який'),
    Rule(r'середн|medium',
         'a9a8b3cbb8b8662651257460e540b322', 'середній'),
    Rule(r'дуже твердий|ultra.*hard|extra.*hard|extremely.*hard',
         '33553a7a51c3c2749fa1ccefac64ed70', 'дуже твердий'),
    Rule(r'твердий|hard\b|firm\b|rigid|метал|metal|сталь|steel|скло|glass|алюміній',
         'eb355951b1990d976158bb90b458dade', 'твердий'),
    Rule(None, 'a9a8b3cbb8b8662651257460e540b322', 'середній'),
]


# ── 14795 Призначення (9548 Анальні розширювачі) ─────────────────────────────

PLUG_PURPOSE_RULES: list[Rule] = [
    Rule(r'профес|professional|expert|extreme',
         'cd539880a04334c5e975428c74135bf8', 'професійний'),
    Rule(r'досвідчен|experienced|advanced|large|великий|grand',
         '76c92bb128db55bd7c69ec734d1a8147', 'для досвідчених'),
    Rule(r'тренув|training|practice',
         '8ab8f5258976bb0de21cf243621a5a0c', 'тренувальний'),
    Rule(r'початківц|beginner|starter|first.*time|small|маленьк',
         '111bf9771875d5f4a0463acb693d1033', 'для початківців'),
    Rule(None, '8ab8f5258976bb0de21cf243621a5a0c', 'тренувальний'),
]


# ── 14796 Формат продажу (9548) ───────────────────────────────────────────────

PLUG_FORMAT_RULES: list[Rule] = [
    Rule(r'набір|kit\b|set\b|комплект|\d+\s*шт',
         '61a3093d9139b93675abc8febef0690d', 'набір'),
    Rule(None, '33d8e077653d78a82a47d8ccc7140263', 'один товар'),
]


# ── 14797 Матеріал покриття (9548) ────────────────────────────────────────────

PLUG_COATING_RULES: list[Rule] = [
    Rule(r'силікон.*покрит|silicone.*coat',
         '3c2464a37c8fd25ef861c7656bf162eb', 'силіконове'),
    Rule(r'оксамит|velvet',
         'e61b00b9b4fe91910738073cc2d656aa', 'оксамитове'),
    Rule(None, '6413c216e457e05c28bc451b7e224f0d', 'без покриття'),
]


# ── 14798 Текстура поверхні (9548) ────────────────────────────────────────────

PLUG_TEXTURE_RULES: list[Rule] = [
    Rule(r'кульк|bead|ball.*shaped',
         '7d1dde94366100621767dbc34385ad2b', 'кулькова'),
    Rule(r'хвиляст|wavy|wave',
         'cede8bec68c9ae7a815221fab04dfef5', 'хвиляста'),
    Rule(r'ребрист|ribbed|ridge',
         '7fa9ac1a311c315bb87b3495f3aa74b7', 'ребриста'),
    Rule(r'спірал|spiral|screw|helix',
         'dc2ba819faa7ab00ae22dd6310515d1d', 'спіральна'),
    Rule(None, '90d03ccc905c2b3f8ad64ed95365f0cf', 'гладка'),
]


# ── 5358 Форма (9548) ─────────────────────────────────────────────────────────

PLUG_SHAPE_RULES: list[Rule] = [
    Rule(r'сегментован|segmented|bead',
         '86734b796c4b2b7a50ed1f93b76c22cd', 'сегментована'),
    Rule(r'краплеподібн|teardrop|pear.shaped|drop',
         '22545e3f40f5af31bfb83983d4ff196f', 'краплеподібна'),
    Rule(r'анатомічн|anatomic',
         'b59ae5f7aae4c1008f8745cd174d79ac', 'анатомічна'),
    Rule(r'циліндр|cylindric|cylinder',
         '82e2d983bd751bf0e356a60b6403ea22', 'циліндрична'),
    Rule(r'овальн|oval',
         '8ce382cba879ca12829e7420a19c9c6f', 'овальна'),
    Rule(None, '717cda7edb3a34cf7c394cb658c0bb72', 'конусна'),
]


# ── Головна таблиця: (cat_code, attr_code) → (attr_name, rules) ──────────────

CAT_ATTR_RULES: dict[tuple[str, str], tuple[str, list[Rule]]] = {
    ('9466', '3103'):  ('Тип приладу',           VIBRATOR_TYPE_RULES),
    ('9466', '3106'):  ('Вид',                   REALISTIC_RULES),
    ('9472', '3106'):  ('Вид',                   REALISTIC_RULES),
    ('9466', '3369'):  ('Призначення',            PURPOSE_VIBRATOR_RULES),
    ('9466', '13037'): ('Конструкція',            CONSTRUCTION_RULES),
    ('9480', '13037'): ('Конструкція',            CONSTRUCTION_RULES),
    ('9480', '13039'): ('Вид',                   DILDO_REALISTIC_RULES),
    ('9484', '12891'): ('Форма',                 ANAL_SHAPE_RULES),
    ('7216', '13948'): ('Тип товару',            LINGERIE_TYPE_RULES),
    ('9458', '13948'): ('Тип товару',            BDSM_TYPE_RULES),
    ('9484', '13948'): ('Тип товару',            ANAL_TYPE_RULES),
    ('7216', '13949'): ('Призначення',            LINGERIE_PURPOSE_RULES),
    # New categories
    ('9476', '5249'):  ('Тип помпи',             PUMP_TYPE_RULES),
    ('9476', '3369'):  ('Призначення',            PURPOSE_PUMP_RULES),
    ('9470', '3369'):  ('Призначення',            PURPOSE_RING_RULES),
    ('9482', '437'):   ('Тип кріплення',          STRAPON_MOUNT_RULES),
    ('9482', '3103'):  ('Тип приладу',            STRAPON_TYPE_RULES),
    ('9482', '13037'): ('Конструкція',            STRAPON_CONSTRUCTION_RULES),
    ('9482', '13039'): ('Вид',                   DILDO_REALISTIC_RULES),
    ('9474', '7215'):  ('Тип',                   ATTACHMENT_TYPE_RULES),
    ('9474', '7192'):  ('Текстура поверхні',      ATTACHMENT_TEXTURE_RULES),
    ('9474', '13037'): ('Конструкція',            ATTACHMENT_CONSTRUCTION_RULES),
    ('9474', '13039'): ('Вид',                   DILDO_REALISTIC_RULES),
    ('9470', '9695'):  ('Тип',                   RING_TYPE_RULES),
    ('9470', '9698'):  ('Текстура поверхні',      RING_TEXTURE_RULES),
    ('9470', '13037'): ('Конструкція',            RING_CONSTRUCTION_RULES),
    ('9460', '13948'): ('Тип товару',            PRANK_TYPE_RULES),
    ('9478', '13954'): ('Тип товару',            BALLS_TYPE_RULES),
    ('9628', '15743'): ('Стать',                 GENDER_RULES),
    ('9630', '15743'): ('Стать',                 GENDER_RULES),
    ('9632', '15743'): ('Стать',                 GENDER_RULES),
    ('9628', '15763'): ('Тип',                   ORAL_TYPE_RULES),
    ('9628', '15765'): ('Смак',                  TASTE_RULES),
    ('9628', '15766'): ('Аромат',                AROMA_ORAL_RULES),
    ('9630', '15744'): ('Аромат',                AROMA_OIL_RULES),
    ('9632', '15744'): ('Аромат',                AROMA_OIL_RULES),
    ('9630', '15762'): ('Тип воску',             WAX_TYPE_RULES),
    ('9628', '15774'): ('Тип упаковки',          ORAL_PACKAGE_RULES),
    ('9630', '15761'): ('Час горіння',           CANDLE_BURN_RULES),
    # Accessory categories
    ('9526', '14746'): ('Тип аксесуара',          ACCESSORY_TYPE_9526_RULES),
    ('9616', '15302'): ('Тип аксесуару',          ACCESSORY_TYPE_9616_RULES),
    ('9620', '15298'): ('Тип аксесуару',          ACCESSORY_TYPE_9620_RULES),
    # Toy care
    ('9448', '14024'): ('Тип засобу',             TOY_CARE_TYPE_RULES),
    ('9448', '14036'): ('Дія',                    TOY_CARE_ACTION_RULES),
    # Prolongers
    ('9636', '15764'): ('Основа засобу',          PROLONGER_BASE_RULES),
    ('9636', '15780'): ('Тип',                    PROLONGER_TYPE_RULES),
    # Sex furniture
    ('9578', '15719'): ('Тип',                    SEX_FURNITURE_TYPE_RULES),
    ('9578', '15720'): ('Основний матеріал',       SEX_FURNITURE_MATERIAL_RULES),
    # Anal douche
    ('9550', '14806'): ('Тип анального душу',     ANAL_DOUCHE_TYPE_RULES),
    ('9550', '14807'): ('Тип використання',       ANAL_DOUCHE_USAGE_RULES),
    ('9550', '14808'): ('Тип підключення',        ANAL_DOUCHE_CONNECT_RULES),
    ('9550', '14810'): ('Тип наконечника',        ANAL_DOUCHE_TIP_RULES),
    ('9550', '13008'): ('Матеріал наконечника',   ANAL_DOUCHE_TIP_MAT_RULES),
    ('9550', '2839'):  ('Матеріал шланга',        ANAL_DOUCHE_HOSE_MAT_RULES),
    ('9550', '3369'):  ('Призначення',             ANAL_DOUCHE_PURPOSE_RULES),
    # Sex dolls
    ('9468', '6151'): ('Стать ляльки',             DOLL_GENDER_RULES),
    ('9468', '5262'): ('Колір волосся',             DOLL_HAIR_RULES),
    ('9468', '6303'): ('Тип ляльки',               DOLL_TYPE_RULES),
    ('9468', '5414'): ('Тип фігури',               DOLL_FIGURE_RULES),
    ('9468', '6092'): ('Позиція тіла',             DOLL_POSE_RULES),
    # Anal plugs/expanders
    ('9548', '11932'): ('Рівень жорсткості',       PLUG_HARDNESS_RULES),
    ('9548', '14795'): ('Призначення',             PLUG_PURPOSE_RULES),
    ('9548', '14796'): ('Формат продажу',          PLUG_FORMAT_RULES),
    ('9548', '14797'): ('Матеріал покриття',       PLUG_COATING_RULES),
    ('9548', '14798'): ('Текстура поверхні',       PLUG_TEXTURE_RULES),
    ('9548', '5358'):  ('Форма',                   PLUG_SHAPE_RULES),
}


# ── Класифікація одного продукту ──────────────────────────────────────────────

def classify_product(sku: str, name: str, desc_html: str,
                     cat_code: str) -> dict[str, tuple[str, str, str]]:
    """
    Повертає {attr_code: (attr_name, valuecode, label_ua)} для всіх застосовних атрибутів.
    """
    text  = (name or '') + ' ' + re.sub(r'<[^>]+>', ' ', desc_html or '')
    result: dict[str, tuple[str, str, str]] = {}

    for (cc, attr_code), (attr_name, rules) in CAT_ATTR_RULES.items():
        if cc != cat_code:
            continue
        match = classify(text, rules)
        if match:
            result[attr_code] = (attr_name, match.valuecode, match.label)

    return result


# ── БД ────────────────────────────────────────────────────────────────────────

def get_connection():
    return psycopg2.connect(**DB, cursor_factory=RealDictCursor)


def run_classification(dry_run: bool = False, filter_skus: list[str] | None = None) -> dict:
    conn = get_connection()
    cur  = conn.cursor()

    if filter_skus:
        cur.execute("""
            SELECT DISTINCT ON (p.sku) p.sku, p.name, p.description_html,
                   m.epicentr_category_code
            FROM sexopt_products p
            JOIN epicentr_category_mapping m ON m.sexopt_category_id = p.category_id::text
            WHERE p.sku = ANY(%s)
            ORDER BY p.sku
        """, (filter_skus,))
    else:
        cur.execute("""
            SELECT DISTINCT ON (p.sku) p.sku, p.name, p.description_html,
                   m.epicentr_category_code
            FROM sexopt_products p
            JOIN epicentr_category_mapping m ON m.sexopt_category_id = p.category_id::text
            ORDER BY p.sku
        """)

    products = cur.fetchall()
    print(f"Продуктів: {len(products)}", flush=True)

    batch: list[tuple] = []
    stats: Counter = Counter()
    stats_label: Counter = Counter()
    cat_stats: dict[str, Counter] = {}

    for p in products:
        cat = p['epicentr_category_code']
        classifications = classify_product(p['sku'], p['name'] or '',
                                           p['description_html'] or '', cat)
        for attr_code, (attr_name, valuecode, label) in classifications.items():
            batch.append((p['sku'], attr_name, attr_code, label, 'classification_regex'))
            stats[attr_name] += 1
            stats_label[f"{attr_name}:{label}"] += 1
            if cat not in cat_stats:
                cat_stats[cat] = Counter()
            cat_stats[cat][f"{attr_name}={label}"] += 1

        if len(batch) >= 2000 and not dry_run:
            _upsert(conn, batch)
            batch.clear()

    if batch and not dry_run:
        _upsert(conn, batch)

    conn.close()
    return {'total': len(products), 'stats': stats,
            'stats_label': stats_label, 'cat_stats': cat_stats}


def _upsert(conn, rows):
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO sexopt_extracted_params
                (sku, param_name, param_code, param_value, source)
            VALUES %s
            ON CONFLICT (sku, param_name) DO UPDATE
                SET param_value  = EXCLUDED.param_value,
                    param_code   = EXCLUDED.param_code,
                    source       = EXCLUDED.source,
                    extracted_at = NOW()
        """, [(r[0], r[1], r[2], r[3], r[4]) for r in rows])
    conn.commit()


# ── Звіт ──────────────────────────────────────────────────────────────────────

def report(result: dict):
    total  = result['total']
    stats  = result['stats']
    labels = result['stats_label']
    cats   = result['cat_stats']

    print()
    print('═' * 70)
    print('  NOIRE CLASSIFIER — ПІДСУМОК')
    print('═' * 70)
    print(f'  Продуктів оброблено: {total}')
    print()

    print(f'  {"Атрибут":<35} {"К-ть":>7}  {"% від total":>11}')
    print('  ' + '-' * 58)
    for attr, cnt in stats.most_common():
        print(f'  {attr:<35} {cnt:>7}  {100*cnt//total:>10}%')

    print()
    print('  Розподіл по значеннях (топ-20):')
    print(f'  {"Атрибут:Значення":<55} {"К-ть":>7}')
    print('  ' + '-' * 65)
    for key, cnt in labels.most_common(20):
        attr, label = key.split(':', 1)
        print(f'  {attr:<30} {label:<25} {cnt:>7}')

    print()
    print('  Розподіл по категоріях:')
    for cat in sorted(cats.keys()):
        print(f'\n  [{cat}]')
        for kv, cnt in cats[cat].most_common(8):
            print(f'    {kv:<55} {cnt:>6}')

    print()
    print('═' * 70)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--sku', nargs='+')
    args = parser.parse_args()
    result = run_classification(dry_run=args.dry_run, filter_skus=args.sku)
    report(result)


if __name__ == '__main__':
    main()
