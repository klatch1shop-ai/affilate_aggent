"""Промпт і локальна перевірка чернетки сценарію."""

import json
import re
from decimal import Decimal

from tg_dispatcher.privacy import mask_private

MAX_HOOK = 90
MAX_POINT = 120
BANNED = ('лікує', 'виліковує', 'гарантує результат', 'найкращий у світі', 'дешевше за всіх',
          'чудодійн', '100% ефектив')
DISCLOSURE = 'Відео створено за допомогою ШІ'
_MEASURE = re.compile(
    r'(?<![\w.,])([+-]?\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?)\s*'
    r'(мл|кг|см|мм|шт|г|%|°)(?![а-яіїєґa-z])', re.IGNORECASE,
)


def build_prompt(topic: dict, facts: dict) -> str:
    """Описати вимоги та передати моделі факти без контактів."""
    return mask_private(
        f'Тема: {json.dumps(topic, ensure_ascii=False)}\n'
        f'Факти: {json.dumps(facts, ensure_ascii=False)}\n'
        f'Напиши українською лише з наведених фактів, без вигадок і обіцянок лікування. '
        f'Гачок до {MAX_HOOK} символів, 3–5 пунктів до {MAX_POINT} символів кожен '
        'і заклик до дії. Поверни JSON: {"hook": str, "points": [str], "cta": str}.'
    )


def parse_script(text: str) -> dict:
    """Прочитати JSON, зокрема в огорожі Markdown, та додати позначку ШІ."""
    fenced = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    raw = fenced.group(1) if fenced else text.strip()
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError('Некоректний JSON сценарію') from None
    if (not isinstance(value, dict)
            or not isinstance(value.get('hook'), str)
            or not isinstance(value.get('cta'), str)
            or not isinstance(value.get('points'), list)
            or not all(isinstance(p, str) for p in value['points'])):
        raise ValueError('Некоректна структура сценарію')
    return {k: value[k] for k in ('hook', 'points', 'cta')} | {'disclosure': DISCLOSURE}


def _measurements(text):
    """Нормалізувати числа та одиниці, зберігши запис для повідомлення."""
    for match in _MEASURE.finditer(text):
        number = re.sub(r'\s', '', match[1]).replace(',', '.')
        yield (Decimal(number), match[2].lower()), match[1]


def check_script(script: dict, facts: dict) -> list[str]:
    """Повернути проблеми без розкриття контактів у діагностиці."""
    problems = []
    points = script['points']
    if len(script['hook']) > MAX_HOOK:
        problems.append('гачок задовгий')
    for point in points:
        if len(point) > MAX_POINT:
            problems.append(f'пункт задовгий: {mask_private(point)[:30]}')
    if len(points) < 3:
        problems.append('мало пунктів')
    if len(points) > 5:
        problems.append('забагато пунктів')
    text = '\n'.join([script['hook'], *points, script['cta'], script.get('disclosure', '')])
    for word in BANNED:
        if word in text.lower():
            problems.append(f'заборонене твердження: {word}')
    known = {key for value in facts.values() for key, _ in _measurements(str(value))}
    for key, original in _measurements(mask_private(text)):
        if key not in known:
            problems.append(f'число не з фактів: {original}')
    if DISCLOSURE not in script.get('disclosure', ''):
        problems.append('нема позначки ШІ')
    if mask_private(text) != text:
        problems.append('контакти у тексті')
    return problems
