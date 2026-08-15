#!/usr/bin/env python3
"""Інвентаризація полів фіду: що там НАСПРАВДІ є, перш ніж щось перевіряти.

Навіщо. 15.08.2026 перевірка «чи збігається обʼєм в описі з характеристикою»
дала 0 розбіжностей і виглядала як добра новина. Насправді вона читала тег
<description>, якого у фіді Rozetka немає взагалі — усі 4147 описів лежать
у <description_ua>. Перевірка мовчки міряла порожнечу. Того ж дня той самий
клас помилки повторився з <name> проти <name_ua> і з <keywords> проти
<keywords_ua>.

Назви полів різні в кожного майданчика й міняються між ітераціями. Тому
будь-яка перевірка фіду починається звідси: спершу дивимось перелік, потім
пишемо запит. Окремо друкуємо назви характеристик — там ловляться апострофи
(«Обʼєм» проти «Об'єм»), від яких запит теж мовчки дає нуль.

Запуск:
    python3 tools/feed_fields.py output/noire_rozetka.xml
    python3 tools/feed_fields.py output/noire_prom.xml --params
"""
import argparse
import collections
import sys
import xml.etree.ElementTree as ET


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('feed')
    ap.add_argument('--params', action='store_true',
                    help='повний перелік назв характеристик')
    ap.add_argument('--top', type=int, default=40)
    a = ap.parse_args()

    offers = ET.parse(a.feed).getroot().findall('.//offer')
    if not offers:
        sys.exit('офферів не знайдено — можливо, інша структура файлу')
    print(f'офферів: {len(offers)}\n')

    tags = collections.Counter(c.tag for o in offers for c in o)
    # Скільки ОФФЕРІВ мають тег — окремо від кількості елементів: picture і
    # param повторюються в межах оффера, і без цього поділу «21103 з 4147»
    # виглядає як 508%.
    holders = collections.Counter(t for o in offers
                                  for t in {c.tag for c in o})
    print('── теги оффера ──')
    for t, n in tags.most_common(a.top):
        h = holders[t]
        share = h * 100 // len(offers)
        rep = f', повторюваний ({n} елементів)' if n > h else ''
        flag = '' if share == 100 else f'   ← лише в {share}% офферів'
        print(f'   {t:24} {h:6}{flag}{rep}')

    attrs = collections.Counter(k for o in offers for k in o.attrib)
    print('\n── атрибути оффера ──')
    for k, n in attrs.most_common():
        print(f'   {k:24} {n:6}')

    names = collections.Counter(p.get('name') for o in offers
                                for p in o.findall('param'))
    if names:
        print(f'\n── назви характеристик: {len(names)} різних ──')
        for t, n in names.most_common(None if a.params else 15):
            # апостроф і схожі символи показуємо кодом: саме на них
            # мовчки ламаються запити виду prm.get("Об'єм")
            odd = ''.join(f' [U+{ord(c):04X}]' for c in t
                          if c in '’ʼ`´\'')
            print(f'   {t:34} {n:6}{odd}')

    empty = [t for t, n in tags.items()
             if sum(1 for o in offers
                    if (o.findtext(t) or '').strip()) == 0]
    if empty:
        print('\n── теги, присутні але ПОРОЖНІ в усіх офферах ──')
        for t in empty:
            print(f'   {t}')
    print('\nПеред написанням будь-якої перевірки звірте назви полів із цим '
          'переліком. Нуль знахідок при неправильній назві виглядає точно '
          'так само, як нуль знахідок при чистих даних.')


if __name__ == '__main__':
    main()
