"""Реєстр методу Prom API → команда каталогу для Telegram (26.09.2026).

Крок 2 конвеєра: `content/prom_api_registry.py` дає перевірений список методів
з офіційного OpenAPI; тут — генерація природної фрази й короткої назви через
Gemini, за зразком `tg_dispatcher/ai_brain/catalog.py` (title/risk/needs/example/group).

Правило (як у skill-37 для атрибутів): Gemini визначає ФОРМУЛЮВАННЯ, не ФАКТИ.
Ризик (R0/R2/R3) і перелік параметрів — з реєстру, перевірені раніше; текст
Gemini ніколи їх не перебиває (`to_catalog_entry` бере risk з METHODS, а не
з відповіді моделі; `needs_are_real` відкидає вигадані параметри).
"""
import json
import re

TAG_TO_GROUP = {
    'Orders': 'Замовлення',
    'Messages': 'Покупці',
    'Clients': 'Покупці',
    'Products': 'Товари',
    'Groups': 'Товари',
    'PaymentOption': 'Гроші',
    'Delivery': 'Посилки',
}

QUESTION = (
    'Ти складаєш команду для текстового/голосового керування Telegram-ботом продавця '
    'на Prom.ua. Метод API: {mid} ({verb} {path}). Опис: {summary}. Доступні параметри '
    'запиту (лише вони, не вигадуй інших): {params}.\n\n'
    'Поверни JSON з полями:\n'
    '"title" — коротка українська назва команди (2-4 слова, як у меню бота);\n'
    '"example" — одна природна фраза власника українською, якою він попросив би бота '
    'зробити саме це (без слова «бот», без знаків питання);\n'
    '"needs" — список параметрів із переліку вище, які справді потрібні для цієї команди '
    '(може бути порожній). НЕ додавай параметрів, яких нема у переліку.\n\n'
    'Тільки JSON, без пояснень.'
)


def build_prompt(mid: str, method: dict) -> str:
    params = ', '.join(method['params']) or 'немає'
    return QUESTION.format(mid=mid, verb=method['verb'], path=method['path'],
                           summary=method['summary'], params=params)


def parse_command(text: str) -> dict:
    fence = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', text.strip(), re.DOTALL | re.IGNORECASE)
    raw = fence.group(1) if fence else text.strip()
    try:
        d = json.loads(raw)
    except ValueError as e:
        raise ValueError(f'не JSON: {e}') from None
    if not isinstance(d, dict) or not d.get('title'):
        raise ValueError('немає обовʼязкового поля "title"')
    return {'title': str(d['title']).strip(),
           'example': str(d.get('example', '')).strip(),
           'needs': [str(x) for x in (d.get('needs') or [])]}


def needs_are_real(needs: list[str], allowed: set[str]) -> bool:
    return all(n in allowed for n in needs)


def to_catalog_entry(mid: str, cmd: dict, method: dict) -> dict:
    return {'title': cmd['title'], 'risk': method['risk'], 'needs': cmd['needs'],
           'example': cmd['example'], 'group': TAG_TO_GROUP[method['tag']]}
