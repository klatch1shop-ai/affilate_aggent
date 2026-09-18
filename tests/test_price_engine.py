"""Приймальні тести до ЗАВДАННЯ 03 (docs/tasks/TASK-03-price-engine.md).

Написані замовником ДО виконання й виконавцем не редагуються. Головне тут —
інваріанти: ціна не нижча за РРЦ і ніколи не збиткова.
"""
import math
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / 'tools'))
try:
    import price_engine_toptul as E
except ImportError as e:                      # модуля немає — провал, не пропуск
    pytest.fail(f'tools/price_engine_toptul.py не імпортується: {e}', pytrace=False)

TOOLS = [[0, 4999, 18], [5000, 9999, 10], [10000, 19999, 7], [20000, 999999999, 5]]
FLAT = [[0, 999999999, 18]]
KEYS = {'price', 'status', 'commission_pct', 'commission', 'profit', 'margin_pct',
        'target', 'floor', 'competitor_min', 'reason'}


def profit_of(price, wholesale, ranges, fixed=0.0):
    return price - price * E.commission_pct(price, ranges) / 100 - wholesale - fixed


# ── комісія ───────────────────────────────────────────────────────────
@pytest.mark.parametrize('price,pct', [(1, 18), (4999, 18), (5000, 10), (9999, 10),
                                       (10000, 7), (25000, 5)])
def test_commission_bands_inclusive(price, pct):
    assert E.commission_pct(price, TOOLS) == pct


# ── ціна, що покриває суму після комісії ─────────────────────────────
def test_gross_up_flat():
    p = E.gross_up(1000, FLAT)
    assert isinstance(p, int)
    assert p == math.ceil(1000 / 0.82)          # 1220
    assert p - p * 0.18 >= 1000


def test_gross_up_crosses_band():
    """Ключовий випадок ТЗ: 4500 → не 5488 (смуга 18 %), а 5000 (смуга 10 %)."""
    assert E.gross_up(4500, TOOLS) == 5000


def test_gross_up_covers_need_everywhere():
    for need in range(100, 30000, 137):
        p = E.gross_up(need, TOOLS)
        assert p - p * E.commission_pct(p, TOOLS) / 100 >= need - 1e-6, need


def test_gross_up_is_minimal():
    """Гривнею менше вже не покриває потрібну суму (у тій самій смузі)."""
    for need in (500, 1000, 3000, 8000):
        p = E.gross_up(need, TOOLS)
        q = p - 1
        assert q - q * E.commission_pct(q, TOOLS) / 100 < need, need


# ── контракт ──────────────────────────────────────────────────────────
def test_shape():
    r = E.price_item(700, 1000, FLAT)
    assert set(r) == KEYS
    assert isinstance(r['price'], int)
    assert isinstance(r['reason'], str) and r['reason']


@pytest.mark.parametrize('w,rrp', [(None, 1000), (700, None), (0, 1000), (700, 0), (-5, 100)])
def test_no_data(w, rrp):
    r = E.price_item(w, rrp, FLAT)
    assert r['status'] == 'no_data'
    assert r['price'] is None


# ── правило власника: спершу РРЦ + комісія ───────────────────────────
def test_target_is_rrp_plus_commission():
    r = E.price_item(700, 1000, FLAT)
    assert r['status'] == 'ok'
    assert r['price'] == r['target'] == 1220
    assert r['commission_pct'] == 18
    assert r['profit'] == pytest.approx(1220 - 219.6 - 700, abs=0.01)


def test_raised_for_margin():
    """Опт майже дорівнює РРЦ — РРЦ + комісія дає прибуток нижче мінімуму."""
    r = E.price_item(1000, 1000, FLAT, min_profit=50)
    assert r['status'] == 'raised_for_margin'
    assert r['price'] == math.ceil(1050 / 0.82)   # 1281
    assert r['profit'] >= 50


# ── конкуренти ────────────────────────────────────────────────────────
def test_competitive_lowers_to_competitor():
    r = E.price_item(700, 1000, FLAT, competitors=[1150, 1300])
    assert r['status'] == 'competitive'
    assert r['price'] == 1150
    assert r['competitor_min'] == 1150


def test_undercut():
    r = E.price_item(700, 1000, FLAT, competitors=[1150], undercut=10)
    assert r['price'] == 1140


def test_uncompetitive_never_below_floor():
    """Конкурент дешевший за нашу межу — не йдемо ні нижче РРЦ, ні в мінус."""
    r = E.price_item(700, 1000, FLAT, competitors=[900])
    assert r['status'] == 'uncompetitive'
    assert r['price'] >= 1000
    assert r['price'] >= r['floor']


def test_competitor_above_target_keeps_target():
    r = E.price_item(700, 1000, FLAT, competitors=[1500])
    assert r['price'] == 1220
    assert r['status'] in ('ok', 'competitive')


# ── інваріанти: ніколи нижче РРЦ, ніколи збиток ──────────────────────
def test_invariants_grid():
    for w in (50, 400, 900, 3000, 4200, 9000):
        for rrp in (100, 500, 1000, 4600, 12000):
            for comps in ((), (rrp * 0.5,), (rrp * 1.05,), (rrp * 3,)):
                for mp in (0, 30, 200):
                    r = E.price_item(w, rrp, TOOLS, competitors=comps, min_profit=mp, fixed_costs=15)
                    assert r['price'] >= rrp, (w, rrp, comps, mp, r)
                    assert profit_of(r['price'], w, TOOLS, 15) >= mp - 0.01, (w, rrp, comps, mp, r)
                    assert r['profit'] >= mp - 0.01
                    assert r['commission_pct'] == E.commission_pct(r['price'], TOOLS)


def test_margin_pct():
    r = E.price_item(700, 1000, FLAT)
    assert r['margin_pct'] == pytest.approx(round(r['profit'] / r['price'] * 100, 1), abs=0.05)


# ── підсумок категорії ────────────────────────────────────────────────
def test_summarize():
    rs = [E.price_item(700, 1000, FLAT), E.price_item(None, 1000, FLAT),
          E.price_item(700, 1000, FLAT, competitors=[900]),
          E.price_item(1000, 1000, FLAT, min_profit=50)]
    s = E.summarize(rs)
    assert s['total'] == 4
    assert s['priced'] == 3
    assert s['by_status']['no_data'] == 1
    assert s['by_status']['uncompetitive'] == 1
    assert s['losses'] == 0
    assert s['min_profit'] >= 0
    assert isinstance(s['avg_margin_pct'], float)


def test_summarize_empty():
    s = E.summarize([])
    assert s['total'] == 0 and s['priced'] == 0 and s['avg_margin_pct'] is None


def test_pure_module():
    src = (BASE / 'tools' / 'price_engine_toptul.py').read_text(encoding='utf-8')
    for bad in ('requests', 'psycopg2', 'open(', 'subprocess', 'socket', 'urllib'):
        assert bad not in src, f'калькулятор має бути чистою математикою: {bad}'
