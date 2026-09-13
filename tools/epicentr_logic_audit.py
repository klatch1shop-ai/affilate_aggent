#!/usr/bin/env python3
"""
tools/epicentr_logic_audit.py
==============================
Перехресна перевірка картки на логічні суперечності між полями.

ЧОМУ ОКРЕМО ВІД ВАЛІДАТОРА. Валідатор перевіряє поля **поодинці**: чи
заповнене, чи є в довіднику, чи в межах довжини. Цього достатньо для
синтаксису й недостатньо для сенсу. Ось картка, яка проходила всі формальні
перевірки й була відхилена імпортом:

    Анальний лубрикант Fleshlube Slide 100 мл
        категорія: Збуджуючі засоби
        Форма      = «класична конусна»
        Тип товару = «класична анальна пробка»

Рідина не має конусної форми. Людина бачить це за секунду — «в назві
міліметри й мілілітри, а в атрибутах геометрія твердого тіла». Скрипт не
бачив, бо кожне поле окремо було валідним.

Тут перевіряються **звʼязки**, а не поля:
  * рідина не може мати форму, діаметр чи конструкцію;
  * скло й метал не бувають гнучкими;
  * товар без мотора не має режимів вібрації;
  * матеріал у назві має збігатися з матеріалом в атрибутах.

Правило одне: інструмент **не виправляє**, а позначає. Суперечність означає,
що ми не знаємо, яке з двох полів бреше, — а вгадувати тут дорожче, ніж
винести на розгляд.

    python3 tools/epicentr_logic_audit.py --src f.xml
    python3 tools/epicentr_logic_audit.py --src f.xml --out clean.xml --drop
"""
import os, re, sys, argparse, collections
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Ознаки рідкого/сипкого товару — за назвою, не за категорією: категорія
# буває помилковою, а «100 мл» у назві пише постачальник.
LIQUID = re.compile(r'\b\d+\s*(?:мл|ml|г|гр|грам)\b|лубрикант|мастил|гель|олі[яї]|'
                    r'спрей|крем|сироватк|бальзам|пудр|сіль\b|піна|шампун|'
                    r'парфум|аромат|свічк', re.I)
# Атрибути, які описують геометрію твердого тіла
SOLID_ATTRS = {'Форма', 'Діаметр', 'Довжина', 'Конструкція', 'Тип приладу',
               'Ввідна довжина', 'Робоча довжина', 'Кількість граней'}
# Матеріали, які фізично не гнуться
RIGID = re.compile(r'скло|боросилікат|метал|нержавіюч|алюміні|сталь', re.I)
FLEXIBLE = re.compile(r'гнучк|згинаєтьс|еластичн|мʼяк|м\'як|тягнетьс', re.I)
MOTOR = re.compile(r'вібр|мотор|пульсац|обертан|двигун|режим', re.I)


def txt(o, tag, lang='ua'):
    for e in o.findall(tag):
        if e.get('lang') in (lang, None):
            return ''.join(e.itertext()).strip()
    return ''


def check(offer):
    """[(правило, пояснення)] — усе, що виглядає суперечливо."""
    out = []
    name = txt(offer, 'name')
    desc = txt(offer, 'description')
    prm = {p.get('name'): (p.text or '').strip() for p in offer.findall('param')}
    full = f'{name} {desc[:800]}'

    if LIQUID.search(name):
        solid = [k for k in prm if k in SOLID_ATTRS]
        if solid:
            out.append(('рідина з геометрією твердого тіла',
                        f'назва каже про рідину, а є атрибути: {", ".join(solid)}'))

    mat = ' '.join(v for k, v in prm.items() if 'атеріал' in k)
    if RIGID.search(mat) and FLEXIBLE.search(full):
        out.append(('жорсткий матеріал названо гнучким',
                    f'матеріал «{mat}», а в тексті йдеться про гнучкість'))

    modes = next((v for k, v in prm.items() if k.startswith('Кількість режим')), '')
    if modes and str(modes).strip().isdigit() and int(modes) > 1 \
            and not MOTOR.search(full):
        out.append(('режими без мотора',
                    f'{modes} режимів, але ні назва, ні опис не згадують вібрацію'))

    # Матеріал у назві проти матеріалу в атрибуті. Два винятки, без яких
    # правило дає більше хибних спрацювань, ніж знахідок:
    #   • «Боді монокіні ПІД латекс» — це імітація, тканина, а не латекс;
    #   • атрибут «комбінований» законно поєднує кілька матеріалів, тож
    #     згадка шкіри в назві йому не суперечить.
    if mat and 'комбінован' not in mat.lower():
        for word in ('силікон', 'скло', 'метал', 'латекс', 'шкір'):
            m = re.search(rf'(\S+\s+)?{word}', name, re.I)
            if not m or word in mat.lower():
                continue
            before = (m.group(1) or '').lower()
            if re.search(r'під|імітац|стиліз|\bяк\b|look|ефект', before):
                continue                      # «під латекс» — це не латекс
            out.append(('матеріал у назві не збігається з атрибутом',
                        f'назва каже «{word}», атрибут — «{mat}»'))
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out')
    ap.add_argument('--drop', action='store_true',
                    help='видаляти суперечливі атрибути (за замовчуванням лише звіт)')
    ap.add_argument('--list', type=int, default=8)
    a = ap.parse_args()

    tree = ET.parse(a.src); root = tree.getroot()
    offers = root.findall('.//offer')
    tally = collections.Counter(); flagged = []
    for o in offers:
        issues = check(o)
        if not issues:
            continue
        flagged.append((o.get('id'), txt(o, 'name'), issues))
        for rule, _ in issues:
            tally[rule] += 1
        if a.drop:
            for p in list(o.findall('param')):
                if p.get('name') in SOLID_ATTRS and \
                        any(r == 'рідина з геометрією твердого тіла' for r, _ in issues):
                    o.remove(p)

    print(f'офферів: {len(offers)} | з суперечностями: {len(flagged)}')
    for k, v in tally.most_common():
        print(f'  {v:5}  {k}')
    if flagged:
        print(f'\nприклади:')
        for sku, nm, issues in flagged[:a.list]:
            print(f'  {sku}  {nm[:66]}')
            for r, why in issues:
                print(f'      · {r}: {why[:88]}')
    if a.out:
        tree.write(a.out, encoding='utf-8', xml_declaration=True)
        print(f'\nзаписано: {a.out}')


if __name__ == '__main__':
    main()
