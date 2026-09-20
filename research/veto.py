"""Детерміновані перевірки правил власника перед виконанням дії."""

from decimal import Decimal, InvalidOperation

from tg_dispatcher.privacy import mask_private


FROZEN_FEEDS = ('rozetka', 'epicentr')
READ_ONLY_SOURCES = ('carvol',)
PROTECTED_FILES = ('output/noire_epicentr_phase1.xml',)
AVAILABILITY = ('in_stock', 'under_the_order', 'not_available')
RULES = ('price_floor', 'frozen_content', 'read_only_source', 'protected_file',
         'availability', 'live_without_approval', 'personal_data')


def check(action: dict, context: dict) -> list[dict]:
    """Зібрати всі порушення без зміни плану чи зовнішніх дій."""
    problems = []

    def add(rule: str, level: str, message: str) -> None:
        problems.append({'rule': rule, 'level': level,
                         'message': mask_private(message)})

    fields = action.get('fields', {})
    if 'price' in fields:
        value = fields['price']
        try:
            price = Decimal(str(value))
        except (InvalidOperation, ValueError):
            price = Decimal('NaN')
        if not price.is_finite():
            add('price_floor', 'stop', f'ціна не число: {value}')
        elif action.get('sku') not in context.get('floor', {}):
            add('price_floor', 'ask', 'поріг ціни невідомий')
        else:
            floor = Decimal(str(context['floor'][action.get('sku')]))
            if price < floor:
                add('price_floor', 'stop',
                    f'ціна {price:.2f} нижча за поріг {floor:.2f}')

    marketplace = action.get('marketplace')
    if action.get('kind') == 'feed_content' and marketplace in FROZEN_FEEDS:
        add('frozen_content', 'stop',
            f'зміст фіду {marketplace} заморожений після модерації')

    source = action.get('source')
    if source in READ_ONLY_SOURCES:
        add('read_only_source', 'stop', f'{source} — тільки читання')

    for path in action.get('files', []):
        if path in PROTECTED_FILES:
            add('protected_file', 'stop', f'файл під забороною: {path}')
            break

    if 'availability' in fields:
        availability = fields['availability']
        if availability not in AVAILABILITY:
            add('availability', 'stop',
                f'невідомий стан наявності: {availability}')
        elif availability == 'not_available' and not context.get('evidence'):
            add('availability', 'ask', 'нема доказу відсутності')

    if action.get('mode') == 'live' and context.get('approved') is not True:
        add('live_without_approval', 'ask',
            'режим live без підтвердження власника')

    text = action.get('text', '')
    if text and mask_private(text) != text:
        add('personal_data', 'stop', 'у тексті особисті дані покупця')

    return problems


def verdict(problems: list[dict]) -> str:
    """Обрати найсуворіший рівень серед знайдених порушень."""
    levels = {problem['level'] for problem in problems}
    if 'stop' in levels:
        return 'stop'
    if 'ask' in levels:
        return 'ask'
    return 'ok'


def report(action: dict, problems: list[dict]) -> str:
    """Сформувати стислий звіт із прихованими контактами покупця."""
    titles = {'stop': '🛑 Зупинено', 'ask': '❓ Потрібне підтвердження',
              'ok': '✅ Перешкод немає'}
    lines = [titles[verdict(problems)]]
    parts = [str(action[key]) for key in ('kind', 'sku', 'marketplace')
             if action.get(key) is not None and action[key] != '']
    if parts:
        lines.append(' · '.join(parts))
    for problem in problems:
        lines.append(f"• {problem['rule']}: {problem['message']}")
    return mask_private('\n'.join(lines))
