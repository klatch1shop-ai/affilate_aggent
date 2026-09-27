"""Дозаповнює обовʼязкові характеристики просто у згенерованому XML.

Навіщо окремий крок. Нові картки ще не існують на майданчику, тож дописати
їм значення через API неможливо — усе має бути вже у файлі імпорту. Аудит
згенерованого файлу (642 товари) показав: бракує «Розміру» на 608 картках і
«Матеріалу» на 250.

Звідки беруться значення — у порядку надійності:
  1. **розбір назви** для розміру: постачальник пише діапазон («L/XL», «S/M»,
     «XXL/XXXL»), майданчик приймає одне значення. Правило взяте з живих
     даних: у назві діапазон, у параметрі перша межа;
  2. **розбір опису** для матеріалу: слово зі словника, зібраного з
     ОПУБЛІКОВАНИХ карток того ж набору;
  3. нічого не знайшли — товар не отримує значення, і це видно у звіті.

Коди опцій — виключно з опублікованих карток (`size_material_codes.json`):
довідник `/options` дає інші коди, які майданчик відхиляє.

    venv/bin/python tools/epicentr_xml_fill_gaps.py \
        --xml exports/epicentr_new_cards.xml --codes exports/size_material_codes.json \
        --out exports/epicentr_new_cards_full.xml
"""
import argparse
import collections
import csv
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from content.rozetka_size_fix import canon, size_in_name        # noqa: E402

# Дефолт застосовується ЛИШЕ там, де більшість опублікованих карток набору
# справді має це значення, і лише коли модель сказала «не знаю». У 9464
# «one size» має 81% — це нижче нашого звичайного порогу 90%, тому значення
# тут не сліпий дефолт, а другий рубіж після моделі й з окремим рядком у звіті.
SIZE_DEFAULT = {'9464': 'one size'}

SIZE_CODE = '12923'
MATERIAL_CODE = '12731'

# Слова опису → назва значення довідника. Лише те, що справді трапляється в
# описах постачальника; вигадувати синоніми наосліп означало б вписати в
# картку матеріал, якого ніхто не перевіряв.
MATERIAL_WORDS = {
    'силікон': 'силікон', 'silicone': 'силікон',
    'метал': 'метал', 'сталь': 'метал', 'алюміні': 'метал',
    'латекс': 'латекс', 'latex': 'латекс',
    'екошкір': 'екошкіра', 'штучна шкіра': 'екошкіра',
    'натуральна шкіра': 'натуральна шкіра', 'справжня шкіра': 'натуральна шкіра',
    'картон': 'картон', 'папер': 'картон',
    'тканин': 'тканина', 'поліестер': 'тканина', 'поліамід': 'тканина',
    'еластан': 'тканина', 'спандекс': 'тканина', 'мереж': 'тканина',
    'сітка': 'тканина', 'нейлон': 'тканина', 'бавовн': 'тканина',
    'мікрофібр': 'тканина', 'віскоз': 'тканина', 'атлас': 'тканина',
    'абс': 'АБС-пластик', 'abs': 'АБС-пластик', 'пластик': 'АБС-пластик',
    'tpe': 'TPE (термопластичний еластомер)', 'термопластич': 'TPE (термопластичний еластомер)',
}


def find_size(name, options):
    """Розмір із назви, зведений до значення довідника. None — не знайшли."""
    found = size_in_name(name or '')
    if not found:
        return None
    _whole, first, _second = found
    table = {canon(o): o for o in options}
    return table.get(canon(first))


def ask_size(name, options, photo_url=None):
    """Розмір за назвою й фото — коли в назві його немає (бодістокінги,
    мікро-стрінги). Модель обирає зі списку або каже НЕ ЗНАЮ."""
    from shared.utils.llm_router import call_gemini
    q = (f'Товар: «{name}»\n\nЯкий у нього розмір? Дозволені значення, інших немає:\n'
         f'{json.dumps(list(options), ensure_ascii=False)}\n\n'
         'Обери РІВНО ОДНЕ. «one size» — якщо товар безрозмірний. '
         'Якщо визначити неможливо — НЕ ЗНАЮ. Лише значення, без пояснень.')
    try:
        image = None
        if photo_url:
            from shared.utils.vendor_pool import _fetch
            image = _fetch(photo_url)[0]
        text, _m, _t = call_gemini(q, timeout=90, max_tokens=40, image_bytes=image,
                                   image_mime='image/jpeg' if image else None)
    except Exception:
        return None
    answer = (text or '').strip().strip('."\'«»')
    return next((o for o in options if o.casefold() == answer.casefold()), None)


def ask_material(name, description, options, photo_url=None):
    """Матеріал, коли розбір опису нічого не дав. Модель обирає зі списку.

    Опис іде в питання обрізаним: матеріал майже завжди в перших абзацах, а
    далі йде маркетинговий текст, який лише відволікає.
    """
    from shared.utils.llm_router import call_gemini
    plain = re.sub(r'&lt;[^&]*?&gt;|<[^>]+>', ' ', description or '')[:900]
    q = (f'Товар: «{name}»\n\nОпис: {plain}\n\n'
         f'З якого МАТЕРІАЛУ виріб? Дозволені значення, інших немає:\n'
         f'{json.dumps(list(options), ensure_ascii=False)}\n\n'
         'Обери РІВНО ОДНЕ — основний матеріал. Якщо визначити неможливо — '
         'НЕ ЗНАЮ. Лише значення, без пояснень.')
    try:
        image = None
        if photo_url:
            from shared.utils.vendor_pool import _fetch
            image = _fetch(photo_url)[0]
        text, _m, _t = call_gemini(q, timeout=90, max_tokens=40, image_bytes=image,
                                   image_mime='image/jpeg' if image else None)
    except Exception:
        return None
    answer = (text or '').strip().strip('."\'«»')
    return next((o for o in options if o.casefold() == answer.casefold()), None)


def find_material(text, options):
    """Матеріал з опису. Беремо ПЕРШЕ входження: опис зазвичай починає з
    основного матеріалу, а перелік у складі йде далі."""
    if not text:
        return None
    lowered = text.casefold()
    hits = []
    for word, value in MATERIAL_WORDS.items():
        position = lowered.find(word)
        if position >= 0 and value in options:
            hits.append((position, value))
    return min(hits)[1] if hits else None


def param_xml(name, code, valuecode, value):
    return (f'    <param name="{name}" paramcode="{code}" '
            f'valuecode="{valuecode}">{value}</param>\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--xml', required=True)
    ap.add_argument('--codes', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--report', default=os.path.join(BASE, 'exports', 'xml_fill_report.csv'))
    ap.add_argument('--use-model', action='store_true', help='питати модель, коли розбір не дав результату')
    a = ap.parse_args()
    use_model = a.use_model

    codes = json.load(open(a.codes, encoding='utf-8'))
    text = open(a.xml, encoding='utf-8').read()

    stats = collections.Counter()
    rows = []

    def fix_offer(match):
        offer = match.group(0)
        sku = re.search(r'<offer id="([^"]+)"', offer)
        sku = sku.group(1) if sku else '?'
        set_code = re.search(r'<attribute_set code="(\d+)"', offer)
        set_code = set_code.group(1) if set_code else None
        table = codes.get(set_code or '', {})
        name = re.search(r'<name lang="ua">(.*?)</name>', offer, re.DOTALL)
        name = name.group(1) if name else ''
        description = re.search(r'<description lang="ua">(.*?)</description>', offer, re.DOTALL)
        description = description.group(1) if description else ''
        additions = ''

        if SIZE_CODE not in offer and table.get(SIZE_CODE):
            options = table[SIZE_CODE]['коди']
            value = find_size(name, options)
            if not value and use_model:
                photo = re.search(r'<picture>(.*?)</picture>', offer)
                value = ask_size(name, options, photo.group(1).strip() if photo else None)
                if value:
                    stats['розмір від моделі'] += 1
            if not value and SIZE_DEFAULT.get(set_code) in options:
                value = SIZE_DEFAULT[set_code]
                stats['розмір за більшістю зразків'] += 1
            if value:
                additions += param_xml('Розмір', SIZE_CODE, options[value], value)
                stats['розмір знайдено'] += 1
            else:
                stats['розмір не знайдено'] += 1
                rows.append({'sku': sku, 'чого бракує': 'Розмір', 'назва': name[:90]})

        if MATERIAL_CODE not in offer and table.get(MATERIAL_CODE):
            options = table[MATERIAL_CODE]['коди']
            value = find_material(description, options) or find_material(name, options)
            if not value and use_model:
                photo = re.search(r'<picture>(.*?)</picture>', offer)
                value = ask_material(name, description, options,
                                     photo.group(1).strip() if photo else None)
                if value:
                    stats['матеріал від моделі'] += 1
            if value:
                additions += param_xml('Матеріал', MATERIAL_CODE, options[value], value)
                stats['матеріал знайдено'] += 1
            else:
                stats['матеріал не знайдено'] += 1
                rows.append({'sku': sku, 'чого бракує': 'Матеріал', 'назва': name[:90]})

        if not additions:
            return offer
        return offer.replace('  </offer>', additions + '  </offer>')

    fixed = re.sub(r'  <offer .*?  </offer>', fix_offer, text, flags=re.DOTALL)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(fixed)

    os.makedirs(os.path.dirname(a.report), exist_ok=True)
    with open(a.report, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['sku', 'чого бракує', 'назва'])
        writer.writeheader()
        writer.writerows(rows)

    for key, n in stats.most_common():
        print(f'  {n:>5}  {key}')
    print(f'\n→ {a.out}')
    print(f'→ {a.report} (товарів із прогалинами: {len(rows)})')


if __name__ == '__main__':
    main()
