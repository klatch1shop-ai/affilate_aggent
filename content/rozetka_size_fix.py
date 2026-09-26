"""Звірка розміру в назві з параметром «Розмір» — вимога модератора Rozetka.

Привід (26.09.2026): 536 повернутих карток мають коментар «розмір в назві і
х-ках має бути однаковим». Перевірка даних показала систему: постачальник дає
в назві ДІАПАЗОН (`L/XL`, `XXL/XXXL`), а в параметр іде ОДНЕ значення (`L`,
`2XL`). Плюс різна нотація: `XXL` у назві проти `2XL` у параметрі.

Двоє знань, здобутих на живих даних і важливих для меж застосування:

1. **Моделі тут не потрібні.** Розбіжність визначається розбором рядка, тож
   дефіцитна квота на фото не витрачається на те, що робить регулярний вираз.
2. **Ця розбіжність НЕ є причиною блокування.** Картки, які успішно
   продаються (напр. EL10801), мають рівно такий самий розрив. Головна причина —
   фото; розмір іде причіпом у тому ж коментарі. Тому правимо **лише повернуті
   картки**, а не весь фід: у фіді 4227 оферів із розміром, і глобальна зміна
   зачепила б те, що вже пройшло модерацію.

Модуль нічого не змінює — він лише **пропонує** правку для перевірки власником.
"""
import re

# Rozetka тримає контрольований перелік значень: діапазонів зі слешем у
# параметрі немає ЖОДНОГО серед 4227 оферів фіду — тому в назві теж має
# лишитись одне значення, а не навпаки.
_ALPHA = r'(?:XS|S|M|L|XL|XXL|XXXL|XXXXL|[2-6]XL)'
SIZE_RE = re.compile(rf'(?<![\w/]) ({_ALPHA}) (?: \s*/\s* ({_ALPHA}) )? (?![\w/])',
                     re.IGNORECASE | re.VERBOSE)

_CANON = {'XXL': '2XL', 'XXXL': '3XL', 'XXXXL': '4XL'}


def canon(size):
    """`XXL` і `2XL` — те саме значення, записане по-різному."""
    if not size:
        return ''
    s = size.strip().upper()
    return _CANON.get(s, s)


def size_in_name(name):
    """(повний_знайдений_фрагмент, перший_розмір, другий_розмір|None) або None."""
    if not name:
        return None
    m = SIZE_RE.search(name)
    if not m:
        return None
    return m.group(0), canon(m.group(1)), canon(m.group(2)) if m.group(2) else None


def check(name, param_size):
    """Що не так із цією карткою. Повертає dict із `status`:

    `немає розміру в назві` · `немає параметра` · `збігається` ·
    `діапазон у назві` (перший збігається з параметром) ·
    `розбіжність` (значення справді різні — потрібна людина).
    """
    found = size_in_name(name)
    param = canon(param_size)
    if not param:
        return {'status': 'немає параметра', 'name_size': found[1] if found else None}
    if not found:
        return {'status': 'немає розміру в назві', 'param': param}
    whole, first, second = found
    if second is None:
        return {'status': 'збігається' if first == param else 'розбіжність',
                'name_size': first, 'param': param, 'fragment': whole}
    if param in (first, second):
        return {'status': 'діапазон у назві', 'name_size': f'{first}/{second}',
                'param': param, 'fragment': whole,
                'proposed_name': propose(name, whole, param_size)}
    return {'status': 'розбіжність', 'name_size': f'{first}/{second}',
            'param': param, 'fragment': whole}


def propose(name, fragment, param_size):
    """Назва, де діапазон замінено значенням параметра. Регістр параметра
    лишаємо як у фіді — його бачить покупець."""
    return name.replace(fragment.strip(), param_size.strip(), 1) if fragment else name
