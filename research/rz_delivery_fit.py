"""Відбір товарів для доставки в магазини ROZETKA без зовнішніх дій.

Беремо суворішу межу фактичної ваги 15 кг зі сторінки sellerhelp p787.
Діапазон 0,1–30 кг у rozetka_delivery.md описує поле API, а не цю межу.
"""

import math

from tools.price_engine_toptul import commission_pct, price_item


LIMITS = {'max_side_cm': 120.0, 'max_weight_kg': 15.0,
          'max_volumetric_kg': 30.0, 'divisor': 4000.0}
DELIVERY_FEE = 35.0
STATES = ('fits', 'too_big', 'unknown')
SIDES = ('length', 'width', 'height')


def _positive(value):
    """Додатне скінченне число або невідоме значення."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def volumetric_weight(length, width, height, *, divisor=LIMITS['divisor']):
    """Об’ємна вага за додатними розмірами у сантиметрах."""
    values = [_positive(value) for value in (length, width, height, divisor)]
    if None in values:
        return None
    length, width, height, divisor = values
    return round(length * width * height / divisor, 2)


def fit(dims: dict) -> dict:
    """Перевищення має пріоритет над відсутністю решти вимірів."""
    values = {key: _positive(dims.get(key)) for key in SIDES + ('weight',)}
    missing = [key for key, value in values.items() if value is None]
    reasons = []
    for side in SIDES:
        value = values[side]
        if value is not None and value > LIMITS['max_side_cm']:
            reasons.append(f'сторона {side} {value} см > 120 см')
    weight = values['weight']
    if weight is not None and weight > LIMITS['max_weight_kg']:
        reasons.append(f'вага {weight} кг > 15 кг')
    volumetric = volumetric_weight(*(values[side] for side in SIDES))
    if volumetric is not None and volumetric > LIMITS['max_volumetric_kg']:
        reasons.append(f'об’ємна вага {volumetric} кг > 30 кг')
    state = 'too_big' if reasons else ('unknown' if missing else 'fits')
    return {'state': state, 'reasons': reasons, 'volumetric': volumetric,
            'missing': missing}


def _dims_reason(fitted):
    """Перша причина відмови за габаритами."""
    if fitted['state'] == 'too_big':
        return 'габарити: ' + fitted['reasons'][0]
    if fitted['state'] == 'unknown':
        return 'габарити: нема даних про ' + ', '.join(fitted['missing'])
    return ''


def evaluate(item: dict, ranges, *, fee=DELIVERY_FEE, min_profit=0.0) -> dict:
    """Оцінка габаритів і прибутку з урахуванням доставки."""
    if min_profit < 0:
        raise ValueError('мінімальний прибуток не може бути від’ємним')
    fitted = fit(item.get('dims') or {})
    priced = price_item(item.get('wholesale'), item.get('rrp'), ranges,
                        item.get('competitors', ()), min_profit=min_profit,
                        fixed_costs=fee)
    why = _dims_reason(fitted)
    if not why:
        if priced['price'] is None:
            why = 'ціна: ' + priced['reason']
        elif priced['profit'] < min_profit:
            why = (f'прибуток {priced["profit"]} ₴ менший за мінімум '
                   f'{min_profit} ₴')
        elif priced['status'] == 'uncompetitive':
            why = 'дорожче за конкурента: ' + priced['reason']
    return {'sku': item.get('sku'), 'name': item.get('name'), 'fit': fitted,
            **{key: priced[key] for key in ('price', 'profit', 'status', 'commission')},
            'ok': not why, 'why': why}


def select(items, ranges_by_category, *, fee=DELIVERY_FEE, min_profit=0.0) -> dict:
    """Розподіл за першим відповідним кошиком зі збереженням порядку."""
    if min_profit < 0:
        raise ValueError('мінімальний прибуток не може бути від’ємним')
    selection = {key: [] for key in
                 ('ready', 'too_big', 'unknown_dims', 'no_price', 'overpriced')}
    for item in items:
        ranges = ranges_by_category.get(item.get('category_id'),
                                        ranges_by_category.get(None))
        if not ranges:
            fitted = fit(item.get('dims') or {})
            result = {'sku': item.get('sku'), 'name': item.get('name'),
                      'fit': fitted, 'price': None, 'profit': None,
                      'status': None, 'commission': None, 'ok': False,
                      'why': _dims_reason(fitted) or 'ціна: нема ставки комісії'}
        else:
            result = evaluate(item, ranges, fee=fee, min_profit=min_profit)
        if result['fit']['state'] == 'too_big':
            bucket = 'too_big'
        elif result['fit']['state'] == 'unknown':
            bucket = 'unknown_dims'
        elif not ranges or result['status'] == 'no_data':
            bucket = 'no_price'
        elif result['status'] == 'uncompetitive':
            bucket = 'overpriced'
        else:
            bucket = 'ready'
        selection[bucket].append(result)
    totals = {key: len(rows) for key, rows in selection.items()}
    totals['all'] = sum(totals.values())
    totals['raised'] = sum(row['status'] == 'raised_for_margin'
                           for row in selection['ready'])
    selection['totals'] = totals
    selection['profit_sum'] = round(sum(row['profit'] for row in selection['ready']), 2)
    selection['profit_sum'] = float(selection['profit_sum'])
    return selection


def report(selection: dict) -> str:
    """Короткий український звіт із максимум двадцятьма товарами."""
    totals = selection['totals']
    if not totals['all']:
        return 'Нема даних'
    ready = selection['ready']
    lines = [f'📦 Доставка в магазини ROZETKA: підходить {totals["ready"]} з {totals["all"]}']
    if ready:
        lines.append(f'Прохідні: очікуваний прибуток {selection["profit_sum"]:.2f} ₴ '
                     '(доставка 35 ₴ уже врахована)')
    lines.append(f'Завеликі: {totals["too_big"]} · Дорожчі за конкурентів: '
                 f'{totals["overpriced"]} · Без ціни: {totals["no_price"]} · '
                 f'Без габаритів: {totals["unknown_dims"]}')
    if totals['raised']:
        lines.append('Ціну підняли вище РРЦ заради беззбитковості: '
                     f'{totals["raised"]}')
    if selection['unknown_dims']:
        lines.append('⚠️ Без габаритів не можна вважати прохідними — це '
                     f'{totals["unknown_dims"]} товар')
    for row in ready[:20]:
        lines.append(f'• {row["sku"]} — {row["price"]} ₴, прибуток {row["profit"]:.2f} ₴')
    if len(ready) > 20:
        lines.append(f'… і ще {len(ready) - 20}')
    return '\n'.join(lines)
