"""Розбір фактів з упаковки та звірка з даними постачальника без мережі."""

import json
import re


FIELDS = ('brand', 'name', 'volume', 'weight', 'country', 'ingredients', 'warnings')
UNITS = {
    'г': ('g', 1), 'гр': ('g', 1), 'g': ('g', 1), 'grams': ('g', 1),
    'кг': ('g', 1000), 'kg': ('g', 1000),
    'мл': ('ml', 1), 'ml': ('ml', 1),
    'л': ('ml', 1000), 'l': ('ml', 1000),
    'шт': ('pcs', 1), 'pcs': ('pcs', 1), '%': ('%', 1),
}
QUESTION = (
    'Прочитай лише видимі факти на фото упаковки. Поверни JSON-об’єкт з полями: '
    + ', '.join(FIELDS)
    + '. Не вигадуй: якщо даних не видно на упаковці, значення поля має бути null.'
)
_EMPTY = {'', 'null', '-', 'n/a', 'невідомо'}
_NUMBER = re.compile(
    r'(?<![\w.,])[+-]?\d+(?:[.,]\d+)?\s*('
    + '|'.join(re.escape(unit) for unit in sorted(UNITS, key=len, reverse=True))
    + r')(?!\w)',
    re.IGNORECASE,
)


def _value(value):
    """Зводить значення поля до непорожнього рядка або None."""
    if value is None:
        return None
    if isinstance(value, list):
        parts = [_value(part) for part in value]
        value = ', '.join(part for part in parts if part is not None)
    value = str(value).strip()
    return None if value.lower() in _EMPTY else value


def parse_reading(text: str) -> dict:
    """Розбирає JSON, зокрема в огортці Markdown, у фіксований набір полів."""
    text = text.strip()
    fence = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError('Очікується JSON-об’єкт')
    return {field: _value(data.get(field)) for field in FIELDS}


def numbers(text: str) -> list[tuple[float, str]]:
    """Витягує унікальні величини у грамах, мілілітрах, штуках і відсотках."""
    result = []
    seen = set()
    for match in _NUMBER.finditer(text):
        unit, factor = UNITS[match.group(1).lower()]
        raw = match.group(0)[:match.start(1) - match.start()].strip()
        value = (float(raw.replace(',', '.')) * factor, unit)
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def read_photos(paths, reader, *, limit=4) -> dict:
    """Читає обмежену кількість унікальних фото переданою функцією."""
    result = {'items': [], 'merged': dict.fromkeys(FIELDS), 'errors': []}
    if limit <= 0:
        return result
    seen = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        try:
            reading = parse_reading(reader(path, QUESTION))
        except Exception as exc:
            result['errors'].append(f'{path}: {type(exc).__name__}')
        else:
            result['items'].append({'path': path, **reading})
            for field, value in reading.items():
                if result['merged'][field] is None and value is not None:
                    result['merged'][field] = value
        if len(seen) >= limit:
            break
    return result


def _text(text):
    """Нормалізує регістр, апострофи та пробіли для текстової звірки."""
    return ' '.join(text.lower().replace('’', "'").split())


def compare(supplier: dict, photo: dict) -> dict:
    """Зіставляє поля, зберігаючи порядок і початкові значення розбіжностей."""
    result = {key: [] for key in (
        'match', 'mismatch', 'unreadable', 'only_supplier', 'only_photo',
    )}
    for field, value in supplier.items():
        if value is None:
            continue
        if field not in photo:
            result['only_supplier'].append(field)
            continue
        other = photo[field]
        if other is None:
            result['unreadable'].append(field)
            continue
        left, right = numbers(value), numbers(other)
        equal = left == right if left or right else _text(value) == _text(other)
        if equal:
            result['match'].append(field)
        else:
            result['mismatch'].append({'field': field, 'supplier': value, 'photo': other})
    for field, value in photo.items():
        if value is not None and supplier.get(field) is None:
            result['only_photo'].append(field)
    return result


def report(result: dict) -> str:
    """Формує короткий звіт для власника у визначеному порядку."""
    if not any(result.values()):
        return 'Нема даних'
    mismatches = result['mismatch']
    lines = [f'❗ Розбіжності: {len(mismatches)}' if mismatches
             else '✅ Розбіжностей немає']
    for item in mismatches:
        lines.append(
            f"• {item['field']}: постачальник «{item['supplier']}» / упаковка «{item['photo']}»"
        )
    if result['match']:
        lines.append(f"Збіглося: {len(result['match'])}")
    for key, label in (
        ('unreadable', 'Не прочитано на фото'),
        ('only_supplier', 'Немає на фото'),
        ('only_photo', 'Немає у постачальника'),
    ):
        if result[key]:
            lines.append(f"{label}: {', '.join(result[key])}")
    return '\n'.join(lines)
