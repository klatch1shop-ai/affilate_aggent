#!/usr/bin/env python3
"""Калькулятор ціни для Rozetka: РРЦ + комісія, нижня межа без збитку, конкуренти.

ЗАВДАННЯ 03 (docs/tasks/TASK-03-price-engine.md), тести tests/test_price_engine.py.
Лише математика: без мережі, файлів і бази. Прайс, конкурентів і звіти
підставляє tools/toptul_pricing.py.

Два незмінні правила:
  * ціна не нижча за РРЦ — це мінімальна ціна продажу за умовами постачальника;
  * прибуток ≥ min_profit — у мінус не йдемо навіть заради конкурента.

Складність, заради якої модуль окремий: комісія Rozetka ступінчаста й залежить
від САМОЇ ціни (у «Інструментах» 18 % до 4 999 грн, 10 % від 5 000 …). Тому
ціну, що покриває потрібну суму після комісії, шукаємо по кожній смузі окремо
й беремо найменшу дійсну: для 4 500 грн це 5 000 (смуга 10 %), а не 5 488.
"""
import math

STATUSES = ('ok', 'raised_for_margin', 'competitive', 'uncompetitive', 'no_data')


def commission_pct(price, ranges):
    """Відсоток комісії для ціни: смуга [від, до, %], межі включно."""
    for lo, hi, pct in ranges:
        if lo <= price <= hi:
            return pct
    # за межами таблиці — найближча смуга (ціна нижча за першу чи вища за останню)
    return ranges[0][2] if price < ranges[0][0] else ranges[-1][2]


def _net(price, ranges):
    """Що лишається продавцю після комісії."""
    return price - price * commission_pct(price, ranges) / 100


def gross_up(need, ranges):
    """Найменша ціла ціна, після комісії з якої лишається не менше `need`."""
    candidates = []
    for lo, hi, pct in ranges:
        p = math.ceil(need / (1 - pct / 100) - 1e-9)
        if lo <= p <= hi:
            candidates.append(p)
        elif p < lo and _net(lo, ranges) >= need:
            # у цій смузі комісія менша: вже її нижня межа покриває потребу
            candidates.append(lo)
    if not candidates:                              # страховка від дірявої таблиці
        return math.ceil(need / (1 - max(r[2] for r in ranges) / 100))
    return min(candidates)


def _empty(reason):
    return {'price': None, 'status': 'no_data', 'commission_pct': None, 'commission': None,
            'profit': None, 'margin_pct': None, 'target': None, 'floor': None,
            'competitor_min': None, 'reason': reason}


def price_item(wholesale, rrp, ranges, competitors=(), min_profit=0.0,
               fixed_costs=0.0, undercut=0):
    """Ціна одного товару з поясненням, чому саме така."""
    if wholesale is None or rrp is None:
        return _empty('немає оптової ціни' if wholesale is None else 'немає РРЦ')
    if wholesale <= 0 or rrp <= 0:
        return _empty('опт або РРЦ не додатні — дані постачальника некоректні')

    target = gross_up(rrp, ranges)                              # правило власника: РРЦ + комісія
    loss_floor = gross_up(wholesale + fixed_costs + min_profit, ranges)
    floor = max(math.ceil(rrp), loss_floor)
    price = max(target, floor)

    if floor > target:
        status = 'raised_for_margin'
        reason = (f'РРЦ + комісія ({target} грн) не покривали опт і мінімальний прибуток — '
                  f'піднято до {floor} грн')
    else:
        status = 'ok'
        reason = f'РРЦ {rrp:g} грн + комісія Rozetka = {target} грн'

    cmin = min(competitors) if competitors else None
    if cmin is not None:
        want = math.ceil(cmin - undercut)
        if want < price:
            if want >= floor:
                price, status = want, 'competitive'
                reason = (f'конкурент {cmin:g} грн' + (f' мінус {undercut} грн' if undercut else '')
                          + f' — нижче нашої межі {floor} грн не йдемо')
            else:
                status = 'uncompetitive'
                reason = (f'конкурент {cmin:g} грн дешевший за нашу межу {floor} грн '
                          f'(РРЦ {rrp:g} або беззбитковість) — лишаємо {price} грн')

    pct = commission_pct(price, ranges)
    commission = round(price * pct / 100, 2)
    profit = round(price - commission - wholesale - fixed_costs, 2)
    return {'price': int(price), 'status': status, 'commission_pct': pct,
            'commission': commission, 'profit': profit,
            'margin_pct': round(profit / price * 100, 1), 'target': target, 'floor': floor,
            'competitor_min': cmin, 'reason': reason}


def summarize(results):
    """Підсумок категорії для звіту."""
    priced = [r for r in results if r['price'] is not None]
    by_status = {}
    for r in results:
        by_status[r['status']] = by_status.get(r['status'], 0) + 1
    return {'total': len(results), 'by_status': by_status, 'priced': len(priced),
            'avg_margin_pct': (round(sum(r['margin_pct'] for r in priced) / len(priced), 1)
                               if priced else None),
            'min_profit': min((r['profit'] for r in priced), default=None),
            'losses': sum(1 for r in priced if r['profit'] < 0)}
