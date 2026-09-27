"""Звіряє КОЖЕН valuecode у файлі з чинним довідником майданчика й виправляє.

Три імпорти 27.09.2026 показали, що на слово вірити не можна нікому:

  * генератор писав `valuecode` рівним коду характеристики (495 параметрів);
  * опубліковані картки зберігають ВИДАЛЕНІ значення (`deleted: true`) —
    навчання на них давало коди, які новий імпорт відхиляє;
  * ендпойнт `/options` під навантаженням повертає порожній список, і та сама
    пара (набір, атрибут) то дає 5 значень, то жодного.

Тому довідники беруться з файлу, зібраного окремо зі стійкими повторами
(`exports/epicentr_dicts.json`), а перевірка йде офлайн — детерміновано й
повторювано.

Порядок для кожного параметра:
  1. код уже в довіднику → не чіпаємо;
  2. назву значення знайдено в довіднику → підставляємо правильний код;
  3. сире значення зводиться до категорії довідника → підставляємо її;
  4. нічого → параметр вилучається, картка йде у звіт.

    venv/bin/python tools/epicentr_xml_validate.py --xml <in> --out <out>
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

DICTS = os.path.join(BASE, 'exports', 'epicentr_dicts.json')
# Атрибути без довідника: число або вільний текст, значення йде як є.
PLAIN = {'measure', 'ratio', 'brand', 'country_of_origin', 'weight', 'width',
         'height', 'length', 'description'}

# Сире значення постачальника → категорія довідника. Складено з того, що
# справді трапилось у файлі; вигадувати синоніми наосліп не можна.
TO_CATEGORY = {
    'нейлон': 'тканина', 'поліестер': 'тканина', 'поліамід': 'тканина',
    'еластан': 'тканина', 'спандекс': 'тканина', 'бавовн': 'тканина',
    'віскоз': 'тканина', 'мереж': 'тканина', 'сітк': 'тканина',
    'мікрофібр': 'тканина', 'атлас': 'тканина', 'сатин': 'тканина',
    'шифон': 'тканина', 'велюр': 'тканина', 'шовк': 'тканина',
    'синтетичне волокно': 'тканина', 'текстиль': 'тканина', 'льон': 'тканина',
    'латекс': 'латекс', 'гума': 'латекс',
    'екошкір': 'екошкіра', 'штучна шкіра': 'екошкіра', 'шкірзам': 'екошкіра',
    'натуральна шкіра': 'натуральна шкіра',
    # Ці категорії з довідника білизни ВИДАЛЕНІ, тож виріб із такими
    # вставками чесніше позначити комбінованим, ніж лишити без матеріалу.
    'силікон': 'комбінований', 'метал': 'комбінований', 'сталь': 'комбінований',
    'пластик': 'комбінований', 'pvc': 'комбінований', 'абс': 'комбінований',
    'tpe': 'комбінований', 'tpr': 'комбінований', 'стразі': 'комбінований',
}


def to_category(raw, options):
    lowered = (raw or '').casefold()
    hits = sorted((lowered.find(w), target) for w, target in TO_CATEGORY.items()
                  if lowered.find(w) >= 0 and target in options)
    return hits[0][1] if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--xml', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--dicts', default=DICTS)
    ap.add_argument('--report', default=os.path.join(BASE, 'exports', 'validate_report.csv'))
    a = ap.parse_args()

    raw = json.load(open(a.dicts, encoding='utf-8'))
    # {(набір, атрибут): {назва_у_нижньому_регістрі: код}} і множина чинних кодів
    names, valid = {}, {}
    for key, options in raw.items():
        set_code, _, attr = key.partition('|')
        names[(set_code, attr)] = {k.strip().casefold(): v for k, v in options.items() if k}
        valid[(set_code, attr)] = set(options.values())

    text = open(a.xml, encoding='utf-8').read()
    stats = collections.Counter()
    dropped = []

    def fix_offer(match):
        offer = match.group(0)
        sku = re.search(r'<offer id="([^"]+)"', offer)
        sku = sku.group(1) if sku else '?'
        set_code = re.search(r'<attribute_set code="(\d+)"', offer)
        set_code = set_code.group(1) if set_code else ''

        def fix_param(pm):
            whole, name, code, current, value = (pm.group(0), pm.group(1), pm.group(2),
                                                 pm.group(3), pm.group(4))
            if code in PLAIN or not code.isdigit():
                stats['без довідника'] += 1
                return whole
            key = (set_code, code)
            if key not in valid:
                stats['довідник невідомий — лишаємо'] += 1
                return whole
            if not valid[key]:
                stats['довідник порожній — лишаємо'] += 1
                return whole
            if current and current in valid[key]:
                stats['уже правильний'] += 1
                return whole
            table = names[key]
            correct = table.get((value or '').strip().casefold())
            if correct:
                stats['виправлено за назвою'] += 1
                return (f'<param name="{name}" paramcode="{code}" '
                        f'valuecode="{correct}">{value}</param>')
            category = to_category(value, table)
            if category:
                stats['зведено до категорії'] += 1
                return (f'<param name="{name}" paramcode="{code}" '
                        f'valuecode="{table[category]}">{category}</param>')
            stats['вилучено'] += 1
            dropped.append({'sku': sku, 'набір': set_code, 'характеристика': name,
                            'значення': value})
            return ''

        fixed = re.sub(r'<param name="([^"]+)" paramcode="([^"]+)"'
                       r'(?: valuecode="([^"]*)")?>([^<]*)</param>', fix_param, offer)
        return re.sub(r'\n\s*\n', '\n', fixed)

    out = re.sub(r'  <offer .*?  </offer>', fix_offer, text, flags=re.DOTALL)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(out)

    for key, n in stats.most_common():
        print(f'  {n:>6}  {key}')
    with open(a.report, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['sku', 'набір', 'характеристика', 'значення'])
        writer.writeheader()
        writer.writerows(dropped)
    print(f'\nвилучено параметрів: {len(dropped)}')
    print(f'→ {a.out}\n→ {a.report}')


if __name__ == '__main__':
    main()
