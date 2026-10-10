#!/usr/bin/env python3
"""Внесення експертних ключів у фід Prom: спершу звільнити, потім заповнити.

Порядок має значення. Слоти вже зайняті, і якщо додавати не звільнивши,
найкращі ключі не вміщаються: у першому прогоні так відхилилось 131 з 165
пропозицій.

ЩО ПРИБИРАЄМО. Лише те, що пройшло ПОДВІЙНИЙ фільтр: модель назвала ключ
зайвим І вимір це підтвердив — ключ стоїть на 50+ наших картках або всі
його слова вже є в назві. Думки моделі самої по собі не досить: правило
merge-not-replace лишається чинним, бо заміна за правилами колись убила
довгий хвіст.

ЩО ДОДАЄМО. Лише те, що пройшло перевірку: мова поля, 2-6 слів, немає на
картці, не стоїть уже на 50+ картках каталогу.

Косметична гілка (лубриканти, збуджуючі засоби, догляд, гігієна) — природна
дослідна група. Решта каталогу лишається контролем.

    STEP_SRC=feed.xml venv/bin/python3 tools/prom_kw_expert_apply.py --write out.xml
"""
import argparse
import glob
import json
import os
import re
import xml.etree.ElementTree as ET

# Останній фільтр перед фідом. Ті самі правила, що й у перевірці, але
# застосовані до ВЖЕ ЗБЕРЕЖЕНИХ черг: 04.10 сім ключів зі словами «ціна» і
# «купити» вже лежали в черзі, коли фільтр додали в перевірку.
# Межа слова тільки НА ПОЧАТКУ. 04.10: з \b і в кінці фільтр пропускав
# «недорогой», «украинская» — після стему йде літера, межі там немає, і
# 14 таких ключів дійшли до фіду. Межа в кінці ще й шкідлива: без неї на
# початку «цена» знаходиться всередині «сценариями».
BANNED = re.compile(r'\b(купит|купувати|купити|замовит|заказат|недорог|дешев|'
                    r'цін|цена|київ|киев|україн|украин|доставк)', re.I)


def clean(k):
    """Ключ придатний? Кома ламає ліміт слотів, заборонені слова з'їдають їх."""
    return (',' not in k and ';' not in k and not BANNED.search(k)
            and 2 <= len(k.split()) <= 6)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT = 9
PILOT = os.path.join(BASE, 'data', 'prom', 'kw_expert_pilot.json')


def load_all(variants=('c', 'a'), a_only=('БДСМ-игрушки',)):
    """Результати прогонів, кілька варіантів разом.

    Варіант C — перевірений метод. Варіант A лишився від прогонів Codex
    (категорія БДСМ, 436 карток) і теж іде у фід, щоб робота не пропала.
    Якщо картка є в обох, перемагає C — він вигравав у досліді 04.10.

    04.10: тут був дефект. Для варіанта A суфікс ставав просто «.json» і
    збігався З УСІМА файлами, зокрема «_c.json», тобто варіанти тихо
    змішувались. Тепер «a» — це явно файл БЕЗ літерного суфікса.
    """
    if isinstance(variants, str):
        variants = (variants,)
    cards = {}
    # Зворотний порядок: перший у списку має перемагати, тому кладемо його
    # останнім і він перезаписує попередні.
    for variant in reversed(list(variants)):
        for path in sorted(glob.glob(os.path.join(BASE, 'data', 'kw_queue', '*.json'))):
            base = os.path.basename(path)[:-len('.json')]
            tail = re.search(r'_([a-z])$', base)
            got = tail.group(1) if tail else 'a'
            if got != variant:
                continue
            # Варіант A беремо ВИБІРКОВО. У чергах варіанта A лежить 4349
            # карток зі старих прогонів, і вносити їх гуртом — це інша,
            # ширша зміна, якої ніхто не просив. Сюди пускаємо лише ті
            # категорії, які свідомо доробили.
            if variant == 'a' and a_only is not None and base not in a_only:
                continue
            d = json.load(open(path, encoding='utf-8'))
            for pid, row in (d.get('cards') or {}).items():
                cards[pid] = row
    if cards:
        return cards
    for path in glob.glob(os.path.join(BASE, 'exports', 'prom_kw_expert_*.json')):
        d = json.load(open(path, encoding='utf-8'))
        for pid, row in (d.get('cards') or {}).items():
            cards[pid] = row
    return cards


def shared_and_name_keys(tree):
    """Ключі, які МОЖНА прибрати, пораховані на самому фіді.

    04.10: перелік на видалення зберігався текстом ключа, але фід
    перезбирається з нуля при кожній публікації, і генератор видає трохи
    інші фрази — «вакуумный стимулятор сатисфайер» замість «вакуумный
    клиторальный стимулятор satisfyer». Жоден збережений ключ не збігався,
    і внесення мовчки робило нуль.

    Критерій той самий, що й був, але рахується ТУТ І ЗАРАЗ:
      * ключ стоїть на 50+ картках — внутрішня конкуренція;
      * усі слова ключа вже є в назві — назва важить більше, а за правилом
        Prom часткова відповідність у назві + часткова в ключах виводить
        товар із видачі.
    """
    offers = list(tree.getroot().iter('offer'))
    freq = {t: {} for t in ('keywords', 'keywords_ua')}
    for o in offers:
        for t in freq:
            for k in (o.findtext(t) or '').split(','):
                k = k.strip().lower()
                if k:
                    freq[t][k] = freq[t].get(k, 0) + 1
    return freq


def removable_now(o, key, tag, freq):
    k = key.strip().lower()
    if freq[tag].get(k, 0) >= 50:
        return True
    name = (o.findtext('name' if tag == 'keywords' else 'name_ua') or '').lower()
    words = set(re.findall(r'\w+', k))
    return bool(words) and words <= set(re.findall(r'\w+', name))


def main(src, out, write):
    cards = load_all()
    print(f'карток із експертними ключами: {len(cards)}')
    tree = ET.parse(src)
    freq = shared_and_name_keys(tree)
    removed = added = touched = 0
    for o in tree.getroot().iter('offer'):
        row = cards.get(o.get('id'))
        if not row:
            continue
        changed = False
        for tag in ('keywords', 'keywords_ua'):
            el = o.find(tag)
            have = [k.strip() for k in ((el.text or '') if el is not None else '').split(',')
                    if k.strip()]
            # Скільки місця потрібно під нові ключі — стільки й звільняємо,
            # починаючи з найгірших (найчастіших у каталозі).
            # Звільняти РІВНО стільки, скільки реально зайдемо. Дубль із
            # наявним ключем теж відкидається, інакше 04.10 на 258 картках
            # слот звільнявся під пропозицію, яка потім не проходила, і
            # картка лишалась БІДНІШОЮ, ніж була.
            have_low = {k.lower() for k in have}
            want = len([a for a in row['add'][tag]
                        if clean(a['k']) and a['k'].lower() not in have_low])
            cand = [k for k in have if removable_now(o, k, tag, freq)]
            cand.sort(key=lambda k: -freq[tag].get(k.strip().lower(), 0))
            need = max(0, want - (LIMIT - len(have)))
            drop = {k.lower() for k in cand[:need]}
            kept = [k for k in have if k.lower() not in drop]
            removed += len(have) - len(kept)
            low = {k.lower() for k in kept}
            free = LIMIT - len(kept)
            take = [a['k'] for a in row['add'][tag]
                    if a['k'].lower() not in low and clean(a['k'])][:max(0, free)]
            added += len(take)
            # Останній запобіжник: ліміт рахуємо ПІСЛЯ складання рядка,
            # бо ключ із комою при читанні розпадається на кілька.
            final = [k for k in (kept + take) if ',' not in k and ';' not in k]
            final = final[:LIMIT]
            take = final[len(kept):] if len(kept) < len(final) else []
            kept = final[:min(len(kept), len(final))]
            if kept + take != have:
                if el is None:
                    el = ET.SubElement(o, tag)
                el.text = ', '.join(kept + take)
                changed = True
        touched += bool(changed)

    print(f'ПРИБРАНО сміттєвих ключів: {removed}')
    print(f'ДОДАНО експертних:         {added}')
    print(f'карток змінено:            {touched}')
    if not write:
        print('\n--dry: нічого не записано')
        return
    tree.write(out, encoding='utf-8', xml_declaration=True)
    ET.parse(out)
    print(f'\nзаписано {out} ({os.path.getsize(out)} байт), XML валідний')
    os.makedirs(os.path.dirname(PILOT), exist_ok=True)
    json.dump({'started': '2026-10-03', 'група': sorted(cards),
               'removed': removed, 'added': added,
               'контроль': 'решта каталогу, картки поза косметичною гілкою'},
              open(PILOT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('склад групи:', PILOT)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=os.environ.get('STEP_SRC', '/tmp/prom_live.xml'))
    ap.add_argument('--write', metavar='OUT')
    a = ap.parse_args()
    main(a.src, a.write or '/tmp/prom_expert_applied.xml', bool(a.write))
