"""Локальний розбір відповідей аналізатора відео та зведення конкурентів."""

import json
import math
import re
from collections import Counter
from statistics import median

FIELDS = ('hook', 'hook_type', 'length_sec', 'format', 'topic', 'has_face', 'cta', 'claims')
HOOK_TYPES = ('питання', 'цифра', 'проблема', 'демонстрація', 'контраргумент', 'історія', 'інше')
QUESTION = (
    'Проаналізуй відео й відповідай українською. Поверни лише JSON-об’єкт із ключами: '
    'hook — дослівний гачок, hook_type — тип гачка (' + ', '.join(HOOK_TYPES) + '), '
    'length_sec — тривалість у секундах числом, format — формат відео, topic — тема, '
    'has_face — чи є обличчя в кадрі (true/false), cta — заклик до дії, '
    'claims — список озвучених тверджень. Не вигадуй: якщо чогось у відео нема '
    'або неможливо встановити — постав null. Твердження передавай як слова автора, '
    'не як перевірені факти.'
)


def _length(value):
    """Прочитати невід’ємну скінченну тривалість у секундах."""
    if isinstance(value, str):
        match = re.fullmatch(r'\s*(\d+(?:[.,]\d+)?)\s*(?:с|сек\.?|секунд[аи]?|s|sec)?\s*',
                             value, re.IGNORECASE)
        if not match:
            return None
        value = float(match[1].replace(',', '.'))
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or value < 0 or not math.isfinite(value)):
        return None
    return value


def parse_analysis(text: str) -> dict:
    """Прочитати JSON, зокрема в огорожі Markdown, і нормалізувати поля."""
    if not isinstance(text, str):
        raise ValueError('Відповідь має бути текстом JSON')
    fenced = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    try:
        value = json.loads(fenced.group(1) if fenced else text.strip())
    except ValueError:
        raise ValueError('Некоректний JSON аналізу') from None
    if not isinstance(value, dict):
        raise ValueError('Аналіз має бути JSON-об’єктом')
    result = {field: value.get(field) for field in FIELDS}
    if result['hook_type'] not in HOOK_TYPES:
        result['hook_type'] = 'інше'
    result['length_sec'] = _length(result['length_sec'])
    face = result['has_face']
    if isinstance(face, str):
        face = {'так': True, 'ні': False, 'true': True, 'false': False}.get(face.strip().lower())
    result['has_face'] = face if isinstance(face, bool) else None
    claims = result['claims']
    if isinstance(claims, str):
        claims = [claims]
    result['claims'] = [c for c in claims if isinstance(c, str)] if isinstance(claims, list) else []
    return result


def analyze_batch(urls: list[str], analyzer, *, limit: int = 20) -> dict:
    """Обробити обмежений пакет, зберігаючи помилки окремих відео."""
    selected = list(dict.fromkeys(urls))[:max(0, limit)]
    items, errors = [], []
    for url in selected:
        try:
            response = analyzer(url, QUESTION)
        except Exception as exc:
            errors.append(f'{url}: {type(exc).__name__}')
            continue
        try:
            items.append({**parse_analysis(response), 'url': url})
        except ValueError as exc:
            errors.append(f'{url}: {type(exc).__name__}')
    return {'items': items, 'errors': errors, 'asked': len(selected)}


def _label(value):
    """Уніфікувати регістр і пробіли текстової категорії."""
    return ' '.join(value.split()).casefold() if isinstance(value, str) else ''


def summarize(items: list[dict]) -> dict:
    """Порахувати категорії та медіану відомих тривалостей."""
    hooks, formats, topics, claims = Counter(), Counter(), Counter(), Counter()
    lengths = []
    for item in items:
        hook = item.get('hook_type')
        hooks[hook if hook in HOOK_TYPES else 'інше'] += 1
        for field, counts in (('format', formats), ('topic', topics)):
            label = _label(item.get(field))
            if label:
                counts[label] += 1
        for claim in item.get('claims') or []:
            label = _label(claim)
            if label:
                claims[label] += 1
        length = _length(item.get('length_sec'))
        if length is not None:
            lengths.append(length)
    return {'total': len(items), 'hook_types': dict(hooks.most_common()),
            'median_length': float(median(lengths)) if lengths else None,
            'formats': dict(formats.most_common()),
            'with_face': sum(item.get('has_face') is True for item in items),
            'topics': topics.most_common(10), 'claims_top': claims.most_common(10)}


def report(summary: dict) -> str:
    """Скласти український текст зведення без зовнішніх викликів."""
    total = summary['total']
    if not total:
        return 'Нема даних'

    def counted(pairs):
        return ', '.join(f'{label} — {count}' for label, count in pairs) or 'нема даних'

    length = summary['median_length']
    duration = f'{length:g} с' if length is not None else 'невідома'
    hooks = ', '.join(f'{label} — {count} ({count / total:.0%})'
                      for label, count in summary['hook_types'].items()) or 'нема даних'
    return '\n'.join([
        f'Розібрано: {total}', f'Медіана довжини: {duration}', f'Гачки: {hooks}',
        f'Формати: {counted(summary["formats"].items())}',
        f'З обличчям: {summary["with_face"]} з {total}',
        f'Теми: {counted(summary["topics"])}',
        f'Часті твердження: {counted(summary["claims_top"])}',
    ])
