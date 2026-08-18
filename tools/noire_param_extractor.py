#!/usr/bin/env python3
"""
tools/noire_param_extractor.py
Витягує структуровані параметри з description_html + name в sexopt_products
і зберігає в sexopt_extracted_params.

Запуск:
    cd /home/tekken/agent-system && source venv/bin/activate
    python3 tools/noire_param_extractor.py            # всі товари з маппінгу
    python3 tools/noire_param_extractor.py --dry-run  # без запису в БД
    python3 tools/noire_param_extractor.py --sku SO6627 SO2818  # конкретні SKU
    python3 tools/noire_param_extractor.py --report-only        # тільки звіт
"""

import argparse, os, re, sys
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, '.env'))

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

# ── Маппінг: назва параметра → epicentr paramcode ─────────────────────────────
# Джерело: epicentr_required_attrs_sexopt (заповнений fetch_sexopt_attr_sets.py)
PARAM_CODE = {
    'Матеріал':                         '12731',
    'Водонепроникний':                  '11953',
    'Підігрів':                         '10173',
    'Вібрація':                         '11579',
    'Кількість режимів роботи':         '4212',
    'Кілька насадок':                   '9977',
    'Телескопічний':                    '11367',
    'Кріплення на присоску':            '11988',
    'Керування через застосунок':       '10210',
    'Тип живлення':                     '11098',
    'Розмір':                           '12923',
    'Колір':                            None,
    'Манометр':                         '4801',
    "Об'єм":                            '15742',
    'Кількість':                        '15741',
    'Зігріваючий':                      '15745',
    'Охолоджуючий':                     '15746',
    'Розслаблюючий':                    '15747',
    'Тонізуючий':                       '15748',
    'Збуджуючий':                       '15749',
    'Зволожуючий':                      '15750',
    "Пом'якшуючий":                     '15752',
    'Антистресовий':                    '15753',
    'Їстівна формула':                  '15754',
    'Органічний продукт':               '15755',
    'Без парабенів':                    '15756',
    'Без гліцерину':                    '15757',
    'Без ароматизаторів':               '15758',
    'З феромонами':                     '15759',
    'Посилення чутливості':             '15768',
    'Посилення слиновиділення':         '15769',
    'Віброефект':                       '15770',
    'Сумісність з презервативами':      '15771',
    'Сумісність з секс-іграшками':      '15772',
    'Веганський':                       '15773',
}

# Атрибути що НЕ витягуються з тексту (класифікаційні — потребують ручного/окремого маппінгу)
NON_EXTRACTABLE = {
    '3103': 'Тип приладу',
    '3106': 'Вид',
    '3369': 'Призначення',
    '13037': 'Конструкція',
    '13039': 'Вид (фалоімітатори)',
    '12891': 'Форма',
    '13948': 'Тип товару',
    '13949': 'Призначення (білизна)',
}


# ── Парсинг HTML ───────────────────────────────────────────────────────────────

def strip_html(html: str) -> str:
    """HTML → plain text, normalize whitespace."""
    text = re.sub(r'<[^>]+>', ' ', html or '')
    text = re.sub(r'&(?:nbsp|ensp|emsp|thinsp);', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


# ── Матеріал ──────────────────────────────────────────────────────────────────

# Порядок важливий: перші — специфічні, далі — загальні
_MATERIALS = [
    # TPE / Elastomer / SuperSkin
    (r'термопластичний\s*еластомер|термопластичн(?:ого|ому|ий)\s*еластомер|TPE\b|ТПЕ\b', 'TPE'),
    (r'SuperSkin|super.?skin|Super\s*Skin|SuperSKIN', 'SuperSkin'),
    (r'Real\s*Feel\s*Super\s*Sk|RealFeel|real.?feel|натуральн(?:е|ий)\s*відчуття', 'SuperSkin'),
    (r'\belastomer\b|еластомер', 'TPE'),
    (r'SENSA\s*FEEL|Sensa\s*Feel', 'SensaFeel'),
    # UltraSKYN / cyberskin
    (r'UltraSKYN|ULTRASKYN|ultraskin', 'UltraSKYN'),
    (r'CyberSkin|cyberskin|кібершкіра|кіберскін', 'CyberSkin'),
    (r'UR3\b', 'UR3'),
    # Silicone
    (r'силікон|\bSilicone\b|\bsilicone\b', 'Силікон'),
    # ABS plastic
    (r'АБС-пластик|ABS-пластик|АБС\s*пластик|ABS\s*пластик|\bABS\b|\bАБС\b', 'АБС-пластик'),
    # Acrylic / polycarbonate / polypropylene
    (r'акрил', 'Акрил'),
    (r'полікарбонат', 'Полікарбонат'),
    (r'поліпропілен', 'Поліпропілен'),
    (r'поліуретан', 'Поліуретан'),
    # Metal / glass
    (r'нержавіюч(?:а|ій|ого|ому)\s*сталь|нержавійка', 'Нержавіюча сталь'),
    (r'алюміній|алюміні(?:єв|й)', 'Алюміній'),
    (r'метал(?:ев)?', 'Метал'),
    (r'боросилікатне\s*скло|медичне\s*скло|скляний|скло', 'Скло'),
    # Leather / fabric
    (r'натуральна\s*шкіра|natural\s*leather', 'Натуральна шкіра'),
    (r'еко(?:-|\s*)шкіра|штучна\s*шкіра|PU\s*шкіра|faux\s*leather|eco.?leather', 'Еко-шкіра'),
    (r'шкіра(?:ний|н(?:ого|ому))?|leather', 'Шкіра'),
    (r'сатин|satin', 'Тканина'),
    (r'шовк(?:ов)?|silk(?:y)?', 'Тканина'),
    (r'нейлон|nylon', 'Нейлон'),
    (r'поліестер|polyester', 'Поліестер'),
    (r'бавовн|cotton', 'Бавовна'),
    (r'тканин|ткань|textile|текстиль', 'Тканина'),
    # Latex / rubber / vinyl
    (r'латекс', 'Латекс'),
    (r'нітрил', 'Нітрил'),
    (r'неопрен', 'Неопрен'),
    (r'ПВХ|PVC\b', 'ПВХ'),
    (r'гума\b|гумов', 'Гума'),
]
_MATERIAL_RE = [(re.compile(p, re.I), name) for p, name in _MATERIALS]


def extract_material(text: str) -> str | None:
    """
    Шукає матеріал у тексті.
    Якщо є явна секція 'Матеріал: X' — бере звідти.
    Інакше — перший знайдений матеріал з _MATERIALS.
    Повертає рядок (може бути кілька через ', ') або None.
    """
    # Явна секція
    labeled = re.search(
        r'Матеріал\s*[:\-–]\s*([^\.\n\r]{3,80})',
        text, re.I
    )
    if labeled:
        raw = labeled.group(1).strip().rstrip(',;')
        found = []
        for pat, name in _MATERIAL_RE:
            if pat.search(raw):
                if name not in found:
                    found.append(name)
        if found:
            return ', '.join(found)
        # fallback: clean raw text
        cleaned = re.sub(r'\s+', ' ', raw)[:80]
        if len(cleaned) > 3:
            return cleaned

    # Scan whole text — collect all unique hits
    found = []
    for pat, name in _MATERIAL_RE:
        if pat.search(text):
            if name not in found:
                found.append(name)
    return ', '.join(found) if found else None


# ── Розміри ───────────────────────────────────────────────────────────────────

_NUM = r'(\d+(?:[.,]\d+)?)'
_UNIT = r'(?:\s*(?:мм|mm|см|cm|сантим\w*))'


def _to_mm(value_str: str, unit: str) -> int | None:
    """Конвертує рядок числа + одиницю в мм (int)."""
    try:
        val = float(value_str.replace(',', '.'))
        if re.search(r'\bсм\b|\bcm\b|сантим', unit, re.I):
            val *= 10
        return round(val)
    except ValueError:
        return None


def _find_dim(text: str, keywords: list[str]) -> int | None:
    """
    Шукає 'keyword ... NUMBER UNIT' або 'NUMBER UNIT ... keyword'.
    Повертає значення в мм.
    """
    kw_pat = '|'.join(keywords)
    # forward: "довжина: 9 см" / "довжина 150 мм"
    m = re.search(
        rf'(?:{kw_pat})\s*[:\-–]?\s*{_NUM}\s*({_UNIT[2:-1]})',  # strip non-capturing groups
        text, re.I
    )
    if not m:
        # forward variant without unit suffix pattern
        m = re.search(
            rf'(?:{kw_pat})\s*[:\-–]?\s*{_NUM}\s*(мм|mm|см|cm)',
            text, re.I
        )
    if m:
        return _to_mm(m.group(1), m.group(2))

    # backward: "9 см в довжину" / "9 см довжиною"
    m = re.search(
        rf'{_NUM}\s*(мм|mm|см|cm)\s+(?:в\s+)?(?:{kw_pat})',
        text, re.I
    )
    if m:
        return _to_mm(m.group(1), m.group(2))
    return None


def extract_length_mm(text: str) -> int | None:
    keywords = [r'довжин\w*', r'глибин\w*', r'вводимо?а?\s*(?:довжина|частина)', r'insert']
    return _find_dim(text, keywords)


def extract_diameter_mm(text: str) -> int | None:
    keywords = [r'діаметр\w*', r'макс\.?\s*діаметр', r'максимальний\s+діаметр']
    return _find_dim(text, keywords)


# ── Вібрація ──────────────────────────────────────────────────────────────────

def extract_vibration(text: str, name: str) -> str | None:
    """'Так', 'Ні' або None якщо невизначено."""
    combined = (name + ' ' + text).lower()

    # Явне "вібрація: ні" або "без вібрації"
    if re.search(r'вібрація\s*[:\-]\s*ні|без\s+вібрації|non.?vibrating', combined):
        return 'Ні'
    # "Вибрация: есть" / "з вібрацією"
    if re.search(r'з\s+вібрацією|вібрація\s*[:\-]\s*(?:так|є|yes)', combined):
        return 'Так'
    # Наявність вібрації за загальним контекстом
    if re.search(r'вібратор|вібру(?:є|ють)|вібраційн|режими?\s+вібрації|рівні?\s+вібрації', combined):
        return 'Так'
    return None


# ── Водонепроникний ───────────────────────────────────────────────────────────

def extract_waterproof(text: str) -> str | None:
    """'IPX7', 'IPX6', 'Так', 'Ні' або None."""
    # Конкретний рівень
    m = re.search(r'IPX\s*([4-9])', text, re.I)
    if m:
        return f'IPX{m.group(1)}'
    # Загальне підтвердження
    if re.search(r'водонепроникн|водостійк|waterproof|water.?resistant|можна\s+(?:занурювати|використовувати.{0,20}воді?|мити)', text, re.I):
        return 'Так'
    # Заперечення
    if re.search(r'не\s+(?:водо|підходить?\s+для\s+води|занурюй)', text, re.I):
        return 'Ні'
    return None


# ── Тип живлення ──────────────────────────────────────────────────────────────

def extract_power_type(text: str) -> str | None:
    t = text.lower()
    # Зарядка USB / built-in акумулятор
    if re.search(r'usb.{0,15}зарядк|зарядк.{0,15}usb|micro.?usb|type-?c|через\s+usb|usb.charging', t):
        return 'USB'
    if re.search(r'вбудован\w+\s+акумулятор|акумулятор\s+вбудован|rechargeable|li.?ion', t):
        return 'USB'
    # Батарейки (порядок важливий: ААА перед АА)
    if re.search(r'батарейк\w+\s+ааа|батарейк\w+\s+aaa|ааа|aaa|\bааа\b|\baaa\b', t):
        return 'Батарейки ААА'
    if re.search(r'батарейк\w+\s+аа\b|батарейк\w+\s+aa\b|\baa\b\s+батарейк|\bаа\b\s+батарейк', t):
        return 'Батарейки АА'
    if re.search(r'батарейк\w+\s+lr44|lr44|батарейк\w+\s+ag13', t):
        return 'Батарейки LR44'
    if re.search(r'батарейк', t):
        return 'Батарейки'
    if re.search(r'\busb\b', t):
        return 'USB'
    return None


# ── Кількість режимів роботи ──────────────────────────────────────────────────

def extract_mode_count(text: str) -> str | None:
    """Повертає число режимів/рівнів як рядок."""
    # "10 режимів вібрації" / "10 рівнів інтенсивності" / "12 різних режимів"
    for m in re.finditer(r'(\d{1,3})\s+(?:режим\w*|рівн\w*)', text, re.I):
        n = int(m.group(1))
        if 2 <= n <= 200:  # фільтр нерелевантних чисел
            return str(n)
    return None


# ── Булеві ознаки ─────────────────────────────────────────────────────────────

# «Підігрів» у Prom і Епіцентрі означає ЖИВЛЕНУ функцію приладу, а не
# можливість зігріти річ самотужки. Старе правило ловило «нагрів» будь-де й
# приписало функцію 391 картці, з них 286 хибно: опис скляної пробки каже
# «можна охолоджувати або нагрівати для температурних ігор» — тобто гріє
# користувач у воді. Це та сама «розбіжність даних», за яку Rozetka знімає
# картку з публікації, тільки створена нами, а не постачальником.
HEAT_YES = re.compile(
    r'функці[яї]\s+підігрів|з\s+підігрівом|автопідігрів|підігрів\s+до|'
    r'нагріва(?:ється|є)\s+до\s*\d|heating\s+function|self.?heating', re.I)
HEAT_NO = re.compile(
    r'можна\s+(?:\w+\s+){0,2}(?:на|під)?грі|'
    r'(?:на|під)грі\w*\s+(?:у|в|під)\s+(?:вод|теплій|душі)|'
    r'від\s+тепла\s+тіла|температурн\w+\s+ігор', re.I)


def has_heating(text: str) -> bool:
    return bool(HEAT_YES.search(text)) and not HEAT_NO.search(text)


def has_telescopic(text: str) -> bool:
    return bool(re.search(r'телескопічн|telescop', text, re.I))


def has_suction_cup(text: str) -> bool:
    return bool(re.search(r'присосок|присоску|присосн|suction.?cup', text, re.I))


def has_smart_control(text: str) -> bool:
    return bool(re.search(r'застосунок|додат[ко]+[уі]\b|bluetooth|wi.?fi|app\b|смартфон', text, re.I))


def has_multiple_attachments(text: str) -> bool:
    return bool(re.search(r'насадк(?:и|а|ою)|набір\s+насадок|кілька\s+насадок', text, re.I))


# ── Манометр (9476 Помпи) ─────────────────────────────────────────────────────

def has_pressure_gauge(text: str) -> bool:
    return bool(re.search(r'манометр|індикатор\s+тиску|pressure\s+gauge', text, re.I))


# ── Булеві ознаки косметичних продуктів (9628/9630/9632) ─────────────────────

def has_warming_effect(text: str) -> bool:
    return bool(re.search(r'зігрів|розігрів|нагрів(?!ач)|warming|warm.{0,10}effect|гарячий', text, re.I))

def has_cooling_effect(text: str) -> bool:
    return bool(re.search(r'охолоджуюч|охолодж|cooling|cool.{0,10}effect|ментол\b|menthol', text, re.I))

def has_arousing_effect(text: str) -> bool:
    return bool(re.search(r'збуджуюч|афродизіак|arousing|aphrodisiac', text, re.I))

def has_moisturizing(text: str) -> bool:
    return bool(re.search(r'зволожуюч|зволожувальн|moisturiz|hydrat', text, re.I))

def has_relaxing(text: str) -> bool:
    return bool(re.search(r'розслаблюч|релакс|relax', text, re.I))

def has_pheromones(text: str) -> bool:
    return bool(re.search(r'феромон|pheromone', text, re.I))

def has_organic(text: str) -> bool:
    return bool(re.search(r'органічн|organic', text, re.I))

def has_no_parabens(text: str) -> bool:
    return bool(re.search(r'без парабен|paraben.free', text, re.I))

def has_no_glycerin(text: str) -> bool:
    return bool(re.search(r'без гліцерин|glycerin.free|glycerol.free', text, re.I))

def has_no_fragrance(text: str) -> bool:
    return bool(re.search(r'без аромат|без запах|fragrance.free|unscented', text, re.I))

def has_edible(text: str) -> bool:
    return bool(re.search(r'їстівн|можна\s+їсти|edible|їжа\b', text, re.I))

def has_vegan(text: str) -> bool:
    return bool(re.search(r'веган|vegan', text, re.I))

def has_toning(text: str) -> bool:
    return bool(re.search(r'тонізуюч|toning|invigorat', text, re.I))

def has_softening(text: str) -> bool:
    return bool(re.search(r"пом'якшуюч|пом'якшувальн|softening|emollient", text, re.I))

def has_antistress(text: str) -> bool:
    return bool(re.search(r'антистрес|anti.?stress', text, re.I))

def has_vibro_effect(text: str) -> bool:
    return bool(re.search(r'віброефект|вібрац.*ефект|tingling|effervesc', text, re.I))

def has_saliva_boost(text: str) -> bool:
    return bool(re.search(r'слиновид|слино.*утворен|saliva.*production', text, re.I))

def has_sensitivity_boost(text: str) -> bool:
    return bool(re.search(r'посилення чутливості|підвищ.*чутливість|sensitiv.*boost|sensitiz', text, re.I))

def has_condom_compatible(text: str) -> bool:
    return bool(re.search(r'сумісн.*презерват|latex.safe|condom.safe|condom.compatible', text, re.I))

def has_toy_compatible(text: str) -> bool:
    return bool(re.search(r'сумісн.*(?:іграшк|vibrat|toy)', text, re.I))


# ── Об'єм (мл) ───────────────────────────────────────────────────────────────

def extract_volume_ml(text: str) -> str | None:
    """Шукає об'єм у мл/ml з назви або опису."""
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:мл|ml)\b', text, re.I)
    if m:
        val = m.group(1).replace(',', '.')
        return val
    return None


# ── Кількість (штук у наборі) ─────────────────────────────────────────────────

def extract_quantity(text: str) -> str | None:
    """Шукає кількість товарів у наборі."""
    m = re.search(r'(\d+)\s*(?:шт\.|штук|pcs|pieces|pack)', text, re.I)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 100:
            return str(n)
    return None


# ── Колір з назви ─────────────────────────────────────────────────────────────

_COLORS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\b(?:black|чорний|чорна|чорне|black\.)\b', re.I), 'Чорний'),
    (re.compile(r'\b(?:white|білий|біла|біле|white\.)\b', re.I), 'Білий'),
    (re.compile(r'\b(?:red|червоний|червона|червоне)\b', re.I), 'Червоний'),
    (re.compile(r'\b(?:pink|рожевий|рожева|рожеве)\b', re.I), 'Рожевий'),
    (re.compile(r'\b(?:purple|violet|фіолетовий|фіолетова|фіолетове)\b', re.I), 'Фіолетовий'),
    (re.compile(r'\b(?:blue|синій|синя|синє|блакитний)\b', re.I), 'Синій'),
    (re.compile(r'\b(?:green|зелений|зелена|зелене)\b', re.I), 'Зелений'),
    (re.compile(r'\b(?:gold|gold\.?|золотий|золота|golden)\b', re.I), 'Золотий'),
    (re.compile(r'\b(?:silver|срібний|срібна|silver\.?)\b', re.I), 'Срібний'),
    (re.compile(r'\b(?:nude|flesh|тілесний|тілесна|skin)\b', re.I), 'Тілесний'),
    (re.compile(r'\b(?:beige|бежевий|бежева)\b', re.I), 'Бежевий'),
    (re.compile(r'\b(?:brown|коричневий|коричнева)\b', re.I), 'Коричневий'),
    (re.compile(r'\b(?:grey|gray|сірий|сіра)\b', re.I), 'Сірий'),
    (re.compile(r'\b(?:transparent|clear|прозорий|прозора)\b', re.I), 'Прозорий'),
    (re.compile(r'\b(?:orange|оранжевий|помаранчевий)\b', re.I), 'Оранжевий'),
    (re.compile(r'\b(?:turquoise|бірюзовий)\b', re.I), 'Бірюзовий'),
]


def extract_color(name: str) -> str | None:
    for pat, color_name in _COLORS:
        if pat.search(name):
            return color_name
    return None


# ── Розмір одягу/білизни ──────────────────────────────────────────────────────

_SIZE_PAT = re.compile(
    # Комбіновані (слеш) — найспецифічніші, на початку
    r'\b(XXS/XS|XS/S|S/M|M/L|L/XL|XL/XXL|XXL/XXXL|XXXL/XXXXL'
    # Одиночні літерні розміри — тільки разом зі стандартними позначеннями
    r'|(?<![A-Za-z])XXXXL|XXXL|XXL|XL(?!ENT|SKYN)|XS(?!TRA)'
    # Число лише з явним суфіксом розміру (EU/UK/US/size)
    r'|(?:розмір\w*\s+)\d{2,3}(?:\s*-\s*\d{2,3})?\s*(?:EU|UK|US)?'
    r'|\d{2,3}(?:\s*-\s*\d{2,3})?\s*(?:EU|UK|US)'
    r'|One\s*Size|OS(?=\b))\b',
    re.I
)


def extract_clothing_size(name: str) -> str | None:
    m = _SIZE_PAT.search(name)
    if m:
        return m.group(0).strip().upper()
    return None


# ── Головна функція екстракції ────────────────────────────────────────────────

def extract_all_params(sku: str, name: str, description_html: str) -> dict[str, str]:
    """
    Повертає {param_name: value} для одного товару.
    Ключ — ім'я параметра (key у PARAM_CODE dict або кастомне).
    """
    desc = strip_html(description_html)
    full = name + ' ' + desc
    result: dict[str, str] = {}

    # Матеріал
    v = extract_material(full)
    if v:
        result['Матеріал'] = v

    # Довжина (шукаємо і в описі, і в назві)
    v = extract_length_mm(full)
    if v is not None:
        result['Довжина (мм)'] = str(v)

    # Діаметр (шукаємо і в описі, і в назві)
    v = extract_diameter_mm(full)
    if v is not None:
        result['Діаметр (мм)'] = str(v)

    # Вібрація
    v = extract_vibration(desc, name)
    if v is not None:
        result['Вібрація'] = v

    # Водонепроникний
    v = extract_waterproof(desc)
    if v is not None:
        result['Водонепроникний'] = v

    # Тип живлення
    v = extract_power_type(desc)
    if v is not None:
        result['Тип живлення'] = v

    # Кількість режимів роботи
    v = extract_mode_count(desc)
    if v is not None:
        result['Кількість режимів роботи'] = v

    # Колір (з назви)
    v = extract_color(name)
    if v is not None:
        result['Колір'] = v

    # Розмір (з назви, для білизни)
    v = extract_clothing_size(name)
    if v is not None:
        result['Розмір'] = v

    # Булеві ознаки (тільки Так — Ні не зберігаємо щоб не засмічувати)
    if has_heating(full):
        result['Підігрів'] = 'Так'
    if has_telescopic(full):
        result['Телескопічний'] = 'Так'
    if has_suction_cup(full):
        result['Кріплення на присоску'] = 'Так'
    if has_smart_control(full):
        result['Керування через застосунок'] = 'Так'
    if has_multiple_attachments(full):
        result['Кілька насадок'] = 'Так'

    # Манометр (для помп)
    if has_pressure_gauge(full):
        result['Манометр'] = 'Так'

    # Об'єм та кількість (для олій/свічок/оральних)
    v = extract_volume_ml(full)
    if v:
        result["Об'єм"] = v
    v = extract_quantity(full)
    if v:
        result['Кількість'] = v

    # Булеві ознаки косметичних продуктів (перевіряємо для всіх, генератор вирішить per-cat)
    if has_warming_effect(full):
        result['Зігріваючий'] = 'Так'
    if has_cooling_effect(full):
        result['Охолоджуючий'] = 'Так'
    if has_arousing_effect(full):
        result['Збуджуючий'] = 'Так'
    if has_moisturizing(full):
        result['Зволожуючий'] = 'Так'
    if has_relaxing(full):
        result['Розслаблюючий'] = 'Так'
    if has_pheromones(full):
        result['З феромонами'] = 'Так'
    if has_organic(full):
        result['Органічний продукт'] = 'Так'
    if has_no_parabens(full):
        result['Без парабенів'] = 'Так'
    if has_no_glycerin(full):
        result['Без гліцерину'] = 'Так'
    if has_no_fragrance(full):
        result['Без ароматизаторів'] = 'Так'
    if has_edible(full):
        result['Їстівна формула'] = 'Так'
    if has_vegan(full):
        result['Веганський'] = 'Так'
    if has_toning(full):
        result['Тонізуючий'] = 'Так'
    if has_softening(full):
        result["Пом'якшуючий"] = 'Так'
    if has_antistress(full):
        result['Антистресовий'] = 'Так'
    if has_vibro_effect(full):
        result['Віброефект'] = 'Так'
    if has_saliva_boost(full):
        result['Посилення слиновиділення'] = 'Так'
    if has_sensitivity_boost(full):
        result['Посилення чутливості'] = 'Так'
    if has_condom_compatible(full):
        result['Сумісність з презервативами'] = 'Так'
    if has_toy_compatible(full):
        result['Сумісність з секс-іграшками'] = 'Так'

    return result


# ── БД ────────────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS sexopt_extracted_params (
    id           SERIAL PRIMARY KEY,
    sku          VARCHAR(50)  NOT NULL,
    param_name   VARCHAR(100) NOT NULL,
    param_code   VARCHAR(50),
    param_value  TEXT         NOT NULL,
    source       TEXT         NOT NULL DEFAULT 'regex_description',
    extracted_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    UNIQUE(sku, param_name)
);
CREATE INDEX IF NOT EXISTS idx_sep_sku ON sexopt_extracted_params(sku);
CREATE INDEX IF NOT EXISTS idx_sep_param_name ON sexopt_extracted_params(param_name);
"""


def ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def upsert_params(conn, rows: list[tuple]):
    """rows = [(sku, param_name, param_code, param_value, source), ...]"""
    if not rows:
        return 0
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
    return len(rows)


# ── Основна обробка ───────────────────────────────────────────────────────────

def get_connection():
    return psycopg2.connect(
        host='192.168.3.28', port=5432,
        dbname='agentdb', user='agentadmin', password='1',
        cursor_factory=RealDictCursor,
    )


def run_extraction(
    dry_run: bool = False,
    filter_skus: list[str] | None = None,
) -> dict:
    conn = get_connection()
    cur  = conn.cursor()

    if not dry_run:
        ensure_table(conn)

    # Завантажуємо товари з маппінгу
    if filter_skus:
        cur.execute("""
            SELECT p.sku, p.name, p.description_html, m.epicentr_category_code
            FROM sexopt_products p
            JOIN epicentr_category_mapping m ON m.sexopt_category_id = p.category_id::text
            WHERE p.sku = ANY(%s)
            GROUP BY p.sku, p.name, p.description_html, m.epicentr_category_code
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
    print(f"Товарів для обробки: {len(products)}", flush=True)

    batch: list[tuple] = []
    stats: Counter = Counter()
    prod_with_params = 0
    cat_param_coverage: dict[str, Counter] = defaultdict(Counter)

    for p in products:
        sku  = p['sku']
        name = p['name'] or ''
        desc = p['description_html'] or ''
        cat  = p['epicentr_category_code']

        params = extract_all_params(sku, name, desc)
        if params:
            prod_with_params += 1

        for pname, pvalue in params.items():
            pcode = PARAM_CODE.get(pname)
            batch.append((sku, pname, pcode, pvalue, 'regex_description'))
            stats[pname] += 1
            cat_param_coverage[cat][pname] += 1

        if len(batch) >= 2000 and not dry_run:
            upsert_params(conn, batch)
            batch.clear()

    if batch and not dry_run:
        upsert_params(conn, batch)

    conn.close()
    return {
        'total_products': len(products),
        'products_with_params': prod_with_params,
        'param_counts': stats,
        'cat_coverage': cat_param_coverage,
    }


# ── Звіт покриття ─────────────────────────────────────────────────────────────

def report_coverage(result: dict):
    total    = result['total_products']
    with_any = result['products_with_params']
    stats    = result['param_counts']
    cat_cov  = result['cat_coverage']

    print()
    print('═' * 70)
    print('  NOIRE PARAM EXTRACTOR — ПІДСУМОК')
    print('═' * 70)
    print(f'  Товарів оброблено      : {total:>6}')
    print(f'  Товарів з ≥1 параметром: {with_any:>6}  ({100*with_any//total if total else 0}%)')
    print()

    # Загальна статистика по параметрах
    print('  Розподіл по типах параметрів:')
    print(f"  {'Параметр':<40} {'Кількість':>9}  {'%':>5}  Epicentr code")
    print('  ' + '-' * 65)
    for pname, cnt in stats.most_common():
        pcode = PARAM_CODE.get(pname, '—')
        pct   = 100 * cnt // total if total else 0
        print(f"  {pname:<40} {cnt:>9}  {pct:>4}%  {pcode or '—'}")

    # Покриття по 8 тестових категоріях
    conn = get_connection()
    cur  = conn.cursor()
    TEST_CATS = ['9466', '9480', '7216', '9458', '9484', '9450', '9454', '9472']

    cur.execute("""
        SELECT attribute_set_code, attribute_code, attribute_name
        FROM epicentr_required_attrs_sexopt
        WHERE attribute_set_code = ANY(%s) AND is_required = TRUE
    """, (TEST_CATS,))
    required_rows = cur.fetchall()

    cur.execute("""
        SELECT e.code, e.name_ua,
               COUNT(DISTINCT m.sexopt_category_id) AS mapping_cnt,
               COUNT(DISTINCT p.sku) AS product_cnt
        FROM epicentr_intimate_categories e
        JOIN epicentr_category_mapping m ON m.epicentr_category_code = e.code
        JOIN sexopt_products p ON p.category_id::text = m.sexopt_category_id
        WHERE e.code = ANY(%s)
        GROUP BY e.code, e.name_ua
    """, (TEST_CATS,))
    cat_info = {r['code']: r for r in cur.fetchall()}
    conn.close()

    # Группуємо required по категорії
    req_by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in required_rows:
        req_by_cat[r['attribute_set_code']].append(r)

    # Логістичні коди — вже перевіряються як XML-теги
    LOGISTICS = {'weight', 'width', 'height', 'length'}
    # Завжди у генераторі
    ALWAYS_IN_GENERATOR = {'brand', 'country_of_origin', 'ratio', 'measure'}

    print()
    print('═' * 100)
    print('  ПОКРИТТЯ REQUIRED PARAMS ПО КАТЕГОРІЯХ (8 тестових)')
    print('═' * 100)

    # Mapping: epicentr param_code → extracted param_name
    code_to_extracted = {v: k for k, v in PARAM_CODE.items() if v}

    for cat in TEST_CATS:
        info = cat_info.get(cat)
        cat_name = info['name_ua'] if info else cat
        cat_products = info['product_cnt'] if info else 0
        req_attrs = [r for r in req_by_cat.get(cat, [])
                     if r['attribute_code'] not in LOGISTICS | ALWAYS_IN_GENERATOR]

        extracted_cover = []
        non_extractable_list = []
        for attr in req_attrs:
            acode = attr['attribute_code']
            aname = attr['attribute_name']
            if acode in code_to_extracted:
                extracted_cover.append(f"{aname}({acode})")
            elif acode in NON_EXTRACTABLE:
                non_extractable_list.append(f"{aname}({acode})")
            else:
                non_extractable_list.append(f"{aname}({acode})*")

        total_req = len(req_attrs)
        covered   = len(extracted_cover)
        pct       = 100 * covered // total_req if total_req else 0

        print()
        print(f"  {cat}  {cat_name}  ({cat_products} товарів, {total_req} required attrs excl. logistics)")
        print(f"  ✅ Покрито екстракцією ({covered}/{total_req}, {pct}%): "
              + (', '.join(extracted_cover) if extracted_cover else '—'))
        print(f"  ❌ Потребує ручного/класифікаційного: "
              + (', '.join(non_extractable_list) if non_extractable_list else '—'))

        # Фактичне покриття по вибірці категорії
        cat_extracted = cat_cov.get(cat, Counter())
        if cat_extracted and cat_products:
            top_extracted = ', '.join(f'{pn}:{cnt}' for pn, cnt in cat_extracted.most_common(5))
            print(f"  📊 Реально витягнуто для цієї категорії: {top_extracted}")

    print()
    print('═' * 100)
    print()
    print('  НЕ ПОКРИТІ НІЧИМ (потребують ручного заповнення або XLS-фіду від SexOpt):')
    ne_set = set()
    for cat in TEST_CATS:
        for attr in req_by_cat.get(cat, []):
            acode = attr['attribute_code']
            if acode not in LOGISTICS | ALWAYS_IN_GENERATOR and acode not in code_to_extracted:
                ne_set.add(f"  {acode:<10} {attr['attribute_name']}")
    for item in sorted(ne_set):
        print(item)
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='NOIRE param extractor: description_html → sexopt_extracted_params')
    parser.add_argument('--dry-run', action='store_true', help='Не писати в БД, тільки статистика')
    parser.add_argument('--report-only', action='store_true', help='Тільки звіт по вже записаних даних')
    parser.add_argument('--sku', nargs='+', help='Обробити тільки ці SKU')
    args = parser.parse_args()

    if args.report_only:
        # Read existing data from DB for report
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(DISTINCT sku) FROM sexopt_extracted_params")
        prod_cnt = cur.fetchone()['count']
        cur.execute("SELECT param_name, param_code, COUNT(*) as cnt FROM sexopt_extracted_params GROUP BY param_name, param_code ORDER BY cnt DESC")
        rows = cur.fetchall()
        conn.close()
        print(f'\nВже в БД: {prod_cnt} SKU з параметрами')
        print(f'{"Параметр":<40} {"Кількість":>9}  Epicentr code')
        print('-' * 65)
        for r in rows:
            print(f"  {r['param_name']:<38} {r['cnt']:>9}  {r['param_code'] or '—'}")
        return

    print(f'Режим: {"dry-run" if args.dry_run else "запис у БД"}', flush=True)
    result = run_extraction(dry_run=args.dry_run, filter_skus=args.sku)
    report_coverage(result)


if __name__ == '__main__':
    main()
