"""Приймальні тести TASK-34: відбір TOPTUL під доставку в магазини ROZETKA.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані,
але межі — справжні (p787, p826) і ставки комісії — з `rozetka_cpa_rates`.
"""
import importlib

import pytest

rz = importlib.import_module('tools.rz_delivery_fit')

RANGES = [[0, 4999, 18], [5000, 9999, 10], [10000, 19999, 7], [20000, 999999999, 5]]
DIMS_OK = {'length': 20.0, 'width': 10.0, 'height': 5.0, 'weight': 1.2}


def item(sku='GAAR1002', wholesale=500.0, rrp=800.0, dims=None, competitors=(), **over):
    d = {'sku': sku, 'name': f'Товар {sku}', 'wholesale': wholesale, 'rrp': rrp,
         'category_id': 4628758,
         'competitors': list(competitors), 'dims': dict(DIMS_OK if dims is None else dims)}
    d.update(over)
    return d


# ── межі й об'ємна вага ───────────────────────────────────────────────

def test_limits_are_the_strict_ones():
    assert rz.LIMITS['max_side_cm'] == 120.0
    assert rz.LIMITS['max_weight_kg'] == 15.0          # p787, а не 30 з нашого конспекту
    assert rz.LIMITS['max_volumetric_kg'] == 30.0
    assert rz.LIMITS['divisor'] == 4000.0
    assert rz.DELIVERY_FEE == 35.0


@pytest.mark.parametrize('args,out', [
    ((40, 30, 20), 6.0),
    ((100, 80, 60), 120.0),
    ((20, 10, 5), 0.25),
    ((0, 10, 5), None), ((None, 10, 5), None), ((-1, 10, 5), None), (('довгий', 10, 5), None),
])
def test_volumetric_weight(args, out):
    assert rz.volumetric_weight(*args) == out


# ── три стани габаритів ───────────────────────────────────────────────

def test_fit_ok():
    f = rz.fit(DIMS_OK)
    assert f['state'] == 'fits' and f['reasons'] == [] and f['missing'] == []
    assert f['volumetric'] == 0.25


def test_fit_too_long_side():
    f = rz.fit(dict(DIMS_OK, length=130.0))
    assert f['state'] == 'too_big'
    assert f['reasons'] == ['сторона length 130.0 см > 120 см']


def test_fit_too_heavy():
    f = rz.fit(dict(DIMS_OK, weight=18.0))
    assert f['state'] == 'too_big' and f['reasons'] == ['вага 18.0 кг > 15 кг']


def test_fit_volumetric_over():
    f = rz.fit({'length': 100.0, 'width': 80.0, 'height': 60.0, 'weight': 10.0})
    assert f['state'] == 'too_big'
    assert f['reasons'] == ['об’ємна вага 120.0 кг > 30 кг']


def test_fit_reasons_order():
    f = rz.fit({'length': 130.0, 'width': 125.0, 'height': 60.0, 'weight': 18.0})
    assert f['reasons'][0].startswith('сторона length') and f['reasons'][1].startswith('сторона width')
    assert f['reasons'][2].startswith('вага') and f['reasons'][3].startswith('об’ємна вага')


def test_fit_unknown_when_data_missing():
    f = rz.fit({'weight': 1.2})
    assert f['state'] == 'unknown' and f['reasons'] == []
    assert f['missing'] == ['length', 'width', 'height'] and f['volumetric'] is None
    assert rz.fit({})['missing'] == ['length', 'width', 'height', 'weight']
    assert rz.fit({'length': 20.0, 'width': None, 'height': 5.0, 'weight': 1.2})['missing'] == ['width']


def test_fit_proven_excess_beats_missing_data():
    f = rz.fit({'weight': 18.0})                       # сторін нема, але вага доведено завелика
    assert f['state'] == 'too_big' and f['missing'] == ['length', 'width', 'height']


# ── економіка одного товару ───────────────────────────────────────────

def test_evaluate_ready():
    r = rz.evaluate(item(), RANGES)
    assert r['ok'] is True and r['why'] == ''
    assert r['price'] == 976 and r['status'] == 'ok'
    assert r['commission'] == pytest.approx(175.68)
    assert r['profit'] == pytest.approx(265.32)        # 976 − 175.68 − 500 − 35
    assert r['sku'] == 'GAAR1002' and r['fit']['state'] == 'fits'


def test_evaluate_fee_is_counted():
    with_fee = rz.evaluate(item(), RANGES)['profit']
    no_fee = rz.evaluate(item(), RANGES, fee=0.0)['profit']
    assert pytest.approx(no_fee - with_fee) == 35.0


def test_evaluate_fee_raises_floor():
    # опт 900 + 35 доставки не покриваються РРЦ 910 + комісія → ціну піднято
    r = rz.evaluate(item(wholesale=900.0, rrp=910.0), RANGES)
    assert r['status'] == 'raised_for_margin' and r['price'] == 1141
    assert r['profit'] >= 0 and r['ok'] is True


def test_evaluate_too_big_is_not_ok():
    r = rz.evaluate(item(dims=dict(DIMS_OK, weight=18.0)), RANGES)
    assert r['ok'] is False and r['why'] == 'габарити: вага 18.0 кг > 15 кг'


def test_evaluate_unknown_dims_is_not_ok():
    r = rz.evaluate(item(dims={'weight': 1.2}), RANGES)
    assert r['ok'] is False
    assert r['why'] == 'габарити: нема даних про length, width, height'


def test_evaluate_no_price():
    r = rz.evaluate(item(wholesale=None), RANGES)
    assert r['ok'] is False and r['status'] == 'no_data' and r['price'] is None
    assert r['why'].startswith('ціна: ') and 'оптов' in r['why']


def test_evaluate_uncompetitive():
    r = rz.evaluate(item(competitors=[700.0]), RANGES)
    assert r['status'] == 'uncompetitive' and r['ok'] is False
    assert r['why'].startswith('дорожче за конкурента: ')


def test_evaluate_competitive_is_ok():
    r = rz.evaluate(item(competitors=[900.0]), RANGES)
    assert r['status'] == 'competitive' and r['price'] == 900 and r['ok'] is True


def test_evaluate_min_profit_validation():
    with pytest.raises(ValueError):
        rz.evaluate(item(), RANGES, min_profit=-1)


# ── відбір ────────────────────────────────────────────────────────────

def items_mix():
    return [
        item('A'),                                                   # ready
        item('B', dims=dict(DIMS_OK, weight=18.0)),                  # too_big
        item('C', dims={'weight': 1.2}),                             # unknown_dims
        item('D', wholesale=None),                                   # no_price
        item('E', competitors=[700.0]),                              # overpriced
        item('F', category_id=999),                                  # нема ставки → no_price
    ]


RATES = {4628758: RANGES}


def test_select_buckets():
    s = rz.select(items_mix(), RATES)
    assert [r['sku'] for r in s['too_big']] == ['B']
    assert [r['sku'] for r in s['unknown_dims']] == ['C']
    assert [r['sku'] for r in s['overpriced']] == ['E']
    assert [r['sku'] for r in s['ready']] == ['A']
    assert {r['sku'] for r in s['no_price']} == {'D', 'F'}
    assert 'low_margin' not in s
    assert s['totals']['all'] == 6 and s['totals']['ready'] == 1 and s['totals']['raised'] == 0
    assert s['profit_sum'] == pytest.approx(265.32)


def test_select_uses_category_ranges():
    tools_ranges = [[0, 4999, 18], [5000, 999999999, 10]]
    cheap = [[0, 999999999, 4]]
    a = item('A')
    b = item('B', category_id=4624949)
    s = rz.select([a, b], {4628758: tools_ranges, 4624949: cheap})
    by = {r['sku']: r for r in s['ready']}
    assert by['A']['commission'] > by['B']['commission']


def test_select_missing_rates_without_default():
    s = rz.select([item('X', category_id=777)], RATES)
    assert [r['sku'] for r in s['no_price']] == ['X']
    assert s['no_price'][0]['why'] == 'ціна: нема ставки комісії'
    assert s['no_price'][0]['price'] is None


def test_min_profit_raises_price_instead_of_dropping():
    # price_item сам піднімає ціну під потрібний прибуток — «малої маржі» бути не може
    s = rz.select([item('A')], RATES, min_profit=1000.0)
    assert [r['sku'] for r in s['ready']] == ['A']
    assert s['ready'][0]['profit'] >= 1000.0
    assert s['ready'][0]['price'] > rz.select([item('A')], RATES)['ready'][0]['price']
    assert s['totals']['raised'] == 1


def test_select_empty():
    s = rz.select([], RATES)
    assert s['totals']['all'] == 0 and s['profit_sum'] == 0.0


# ── звіт ──────────────────────────────────────────────────────────────

def test_report():
    lines = rz.report(rz.select(items_mix(), RATES)).splitlines()
    assert lines[0] == '📦 Доставка в магазини ROZETKA: підходить 1 з 6'
    assert lines[1].startswith('Прохідні: очікуваний прибуток 265.32 ₴')
    assert 'доставка 35 ₴ уже врахована' in lines[1]
    assert lines[2] == 'Завеликі: 1 · Дорожчі за конкурентів: 1 · Без ціни: 2 · Без габаритів: 1'
    assert lines[3] == '⚠️ Без габаритів не можна вважати прохідними — це 1 товар'
    assert lines[4] == '• A — 976 ₴, прибуток 265.32 ₴'
    assert not any(l.startswith('Ціну підняли') for l in lines)


def test_report_mentions_raised_price():
    s = rz.select([item('A', wholesale=900.0, rrp=910.0)], RATES)
    lines = rz.report(s).splitlines()
    assert s['totals']['raised'] == 1
    assert 'Ціну підняли вище РРЦ заради беззбитковості: 1' in lines


def test_report_no_ready_and_empty():
    s = rz.select([item('B', dims=dict(DIMS_OK, weight=18.0))], RATES)
    text = rz.report(s)
    assert not any(l.startswith('Прохідні:') for l in text.splitlines())
    assert text.splitlines()[0] == '📦 Доставка в магазини ROZETKA: підходить 0 з 1'
    assert rz.report(rz.select([], RATES)) == 'Нема даних'


def test_report_truncates_long_list():
    s = rz.select([item(f'S{i}') for i in range(25)], RATES)
    lines = rz.report(s).splitlines()
    assert sum(1 for l in lines if l.startswith('• ')) == 20
    assert lines[-1] == '… і ще 5'
