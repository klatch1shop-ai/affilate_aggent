#!/usr/bin/env python3
"""
tools/prom_params_fill.py
==========================
Крок 2 плану: категорія й характеристики. Працює на копії фіду.

ТРИ ДІЇ, КОЖНА З ВЛАСНОЮ ПІДСТАВОЮ

1. **Уніфікація «Форми».** У фіді те саме значення записане двома способами:
   «класична конусна» (282) і «конусна» (20). Для фасетного фільтра це два
   різні значення, тож частина товарів випадає з вибірки покупця.
   Туди ж «анальна пробка-ялинка»: ялинка — це **тип товару**, а за формою
   вона геометрично конусна. Один товар може бути «пробкою-ялинкою» за типом
   і «класичною конусною» за формою — це різні осі, не суперечність.

2. **Країна-виробник із власного фіду.** Бренд→країну не вигадуємо: беремо
   з карток того ж бренду в інших категоріях. Але **лише коли дані одностайні**
   (≥70 % і не менше 5 карток). Nexus має 19 «Великобританія» проти 7 «Китай»,
   Rocks Off — 22 проти 17: тут бренд і виробництво в різних країнах, і
   вгадувати не можна. Такі виводимо списком.

3. **Хибне значення «Тип».** 33 картки мають «Тип = Анальний душ», і лише
   одна справді душ; решта — смарт-вібропробки. Саме цей параметр раніше
   змусив генератор ключів будувати фрази навколо «анального душа».
   Прибираємо там, де назва прямо суперечить.

ЧОГО НЕ РОБИМО. «Зігріваючий=Так» разом із «Охолоджуючий=Так» стоїть на 37
картках і виглядає як суперечність. Це не помилка: скло й метал монолітні та
непористі, вони дозволяють температурні ігри **в обидва боки**. Перевірено на
конкретних картках, чистити не можна.

    python3 tools/prom_params_fill.py --plan
    python3 tools/prom_params_fill.py --write output/noire_prom_step2.xml
"""
import os, re, sys, argparse, collections
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get('STEP_SRC') or os.path.join(BASE, 'output', 'noire_prom.xml')
# Категорії, які проходять постобробку. Розширюється в міру того, як кожна
# наступна проходить аудит і перевірку очима: додавати всі одразу означало б
# застосувати неперевірені правила до всього каталогу.
CATEGORIES = [c.strip() for c in os.environ.get(
    'PROM_CATEGORIES', 'Анальні пробки, Вібратори').split(',') if c.strip()]

FORM_ALIAS = {'конусна': 'класична конусна',
              'анальна пробка-ялинка': 'класична конусна'}
FORM_RULES = [
    ('фалос', r'анатомічн\w+\s+форм|з\s+голівк|з\s+венам|у\s+формі\s+член|реалістичн'),
    ('фігурна', r'кристал|страз|хвостик|з\s+хвостом|сердечк|квітк|спіральн|'
                r'у\s+формі\s+(?:зірк|метелик|тварин)|дизайнерськ|пухнаст|ялинк'),
]
DOUCHE = re.compile(r'душ|спринцівк|клізм|douche|enema', re.I)

# --- Вібратори -------------------------------------------------------------
# «Вібрація» у цій категорії має в фіді рівно одне значення — «Так» (841 з 841
# заповнених). Усі 196 карток без неї — віброяйця й вібромасажери, тобто
# прилади, що вібрують за визначенням. Це не здогадка, а факт про категорію.
DEVICE_RULES = [
    ('набір приладів', r'набір\s+(?:з\s+)?\d|набір\s+приладів'),
    ('насадки до вібратора', r'насадк\w*\s+(?:на|до|для)\s+вібр'),
    ('вібратор для сосків', r'для\s+соск|на\s+соск|nipple'),
    ('вібратор-насадка на палець', r'на\s+палець|на\s+пальц|напальчник'),
    ('вібротрусики', r'вібротрусик|трусик\w*\s+з\s+вібр'),
    ('ороімітатор', r'ороімітатор|язичк|лижуч'),
    ('звуковий стимулятор', r'\bsonic\b|звуков\w+\s+хвил|акустичн'),
    ('вакуумний стимулятор', r'вакуум|air[-\s]?pulse|безконтактн|розтруб'),
    ('вібратор-пульсатор', r'пульсатор|фрикці|поступальн\w+\s+рух|штовхач'),
    ('вібратор-мікрофон', r'мікрофон|\bwand\b|вібромасажер'),
    ('вібратор-кролик', r'кролик|rabbit'),
    ('вібратор для пар', r'для\s+пар\b|u-подібн'),
    ('віброяйця', r'віброяйц|виброяйц|яйцеподібн'),
    ('віброкулі', r'віброкул|\bкул[яі]\b|bullet'),
    ('віброчлен', r'віброчлен|з\s+мошонк'),
    ('міні-вібратор', r'\bміні|мінівібр'),
]
BEND = re.compile(r'вигин|загнут|зігнут|точк\w*\s+g|g-spot', re.I)
CLIT_ARM = re.compile(r'відросток|вушк|кролик|подвійн\w+\s+стимуляц', re.I)
NO_PENETR = re.compile(r'вакуум|безконтактн|мікрофон|\bwand\b|кліторальн|пласк', re.I)
MIN_BRAND_CARDS, MIN_SHARE = 5, 0.7


def txt(o, tag):
    e = o.find(tag)
    return (e.text or '').strip() if e is not None else ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--write')
    a = ap.parse_args()

    tree = ET.parse(SRC); root = tree.getroot()
    cats = {c.get('id'): (c.text or '') for c in root.findall('.//category')}
    offers = root.findall('.//offer')

    # бренд → країна з усього фіду
    bc = collections.defaultdict(collections.Counter)
    for o in offers:
        v = txt(o, 'vendor')
        c = next((p.text or '').strip() for p in o.findall('param')
                 if p.get('name') == 'Країна-виробник') if any(
                     p.get('name') == 'Країна-виробник' for p in o.findall('param')) else ''
        if v and c:
            bc[v][c] += 1
    brand_country, unsure = {}, {}
    for v, cnt in bc.items():
        total = sum(cnt.values()); top, n = cnt.most_common(1)[0]
        if total >= MIN_BRAND_CARDS and n / total >= MIN_SHARE:
            brand_country[v] = top
        elif total >= MIN_BRAND_CARDS:
            unsure[v] = cnt.most_common(3)

    rows = [o for o in offers if cats.get(txt(o, 'categoryId'), '').strip() in {c.strip() for c in CATEGORIES}]
    did = collections.Counter(); left = collections.Counter(); shown = []
    for o in rows:
        name = txt(o, 'name_ua'); vendor = txt(o, 'vendor')
        params = {p.get('name'): p for p in o.findall('param')}
        catname = cats.get(txt(o, 'categoryId'), '').strip()
        full = name + ' ' + re.sub(r'<[^>]+>', ' ', txt(o, 'description_ua'))

        # 1. форма — ЛИШЕ для анальних пробок. Правило писалося під їхній
        # довідник із трьох значень; застосоване до вібраторів, воно приписало
        # «класичну конусну» всім 1037 карткам категорії.


        fp = params.get('Форма')
        if fp is not None:
            cur = (fp.text or '').strip().lower()
            if cur in FORM_ALIAS:
                if a.write:
                    fp.text = FORM_ALIAS[cur]
                did[f'форма уніфікована: {cur} → {FORM_ALIAS[cur]}'] += 1
        elif 'пробк' in catname.lower():
            val = next((v for v, pat in FORM_RULES if re.search(pat, full, re.I)),
                       'класична конусна')
            if a.write:
                e = ET.SubElement(o, 'param'); e.set('name', 'Форма'); e.text = val
            did[f'форму додано: {val}'] += 1
            if len(shown) < 8:
                shown.append(f'ФОРМА={val:18} ← {name[:62]}')

        # 2. країна
        if 'Країна-виробник' not in params:
            c = brand_country.get(vendor)
            if c:
                if a.write:
                    e = ET.SubElement(o, 'param'); e.set('name', 'Країна-виробник'); e.text = c
                did[f'країну додано: {c}'] += 1
                if len(shown) < 14:
                    shown.append(f'КРАЇНА={c:17} ← {name[:62]}')
            else:
                left[f'країна невідома: {vendor or "без бренду"}'] += 1

        # 3. вібратори: властивості, які випливають із самої категорії
        if 'вібратор' in catname.lower():
            if 'Вібрація' not in params:
                if a.write:
                    e = ET.SubElement(o, 'param'); e.set('name', 'Вібрація'); e.text = 'Так'
                did['вібрація = Так'] += 1
            if 'Тип приладу' not in params:
                v = next((val for val, pat in DEVICE_RULES
                          if re.search(pat, name, re.I)), None)
                if v:
                    if a.write:
                        e = ET.SubElement(o, 'param'); e.set('name', 'Тип приладу'); e.text = v
                    did[f'тип приладу = {v}'] += 1
                else:
                    left['тип приладу не визначити з назви'] += 1
            if 'Призначення' not in params:
                v = ('кліторні' if NO_PENETR.search(full) else
                     'вагінально-кліторні' if CLIT_ARM.search(full) else
                     'для точки G' if BEND.search(full) else 'вагінальні')
                if a.write:
                    e = ET.SubElement(o, 'param'); e.set('name', 'Призначення'); e.text = v
                did[f'призначення = {v}'] += 1
            if 'Конструкція' not in params:
                v = 'подвійні' if CLIT_ARM.search(full) else 'односторонні'
                if a.write:
                    e = ET.SubElement(o, 'param'); e.set('name', 'Конструкція'); e.text = v
                did[f'конструкція = {v}'] += 1

        # 4. хибний «Тип»
        tp = params.get('Тип')
        if tp is not None and (tp.text or '').strip().lower() == 'анальний душ' \
           and not DOUCHE.search(name):
            if a.write:
                o.remove(tp)
            did['прибрано хибний «Тип = Анальний душ»'] += 1

    print(f'категорії {CATEGORIES}: {len(rows)} товарів\n')
    for k, v in did.most_common():
        print(f'  {v:5}  {k}')
    if left:
        print('\nПОТРЕБУЄ РІШЕННЯ:')
        for k, v in left.most_common(10):
            print(f'  {v:5}  {k}')
    if unsure:
        print('\nБРЕНДИ З НЕОДНОЗНАЧНОЮ КРАЇНОЮ (бренд і виробництво різні):')
        for v, c in list(unsure.items())[:8]:
            print(f'  {v:18} {c}')
    if shown:
        print('\nПРИКЛАДИ:')
        for x in shown:
            print(f'  {x}')
    if a.write:
        tree.write(a.write, encoding='utf-8', xml_declaration=True)
        print(f'\nкопію збережено: {a.write}')


if __name__ == '__main__':
    main()
