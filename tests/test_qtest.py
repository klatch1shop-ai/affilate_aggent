"""Тихий прогін тестів: у контекст — підсумок і перелік FAILED, повний лог — у файл.

Причина: коли перевірка падає, мені потрібні ідентифікатори тестів, а не 200 рядків.
"""
import importlib

q = importlib.import_module('scripts.qtest')

GREEN = """....................                                            [100%]
688 passed in 0.41s
"""

RED = """..F..F                                                          [100%]
=================================== FAILURES ===================================
____________________ test_orders_search_filters_by_status ______________________
    assert '906000001' in out
E   AssertionError: assert '906000001' in 'Замовлень немає'
tests/test_commands_v2.py:124: AssertionError
=========================== short test summary info ============================
FAILED tests/test_commands_v2.py::test_orders_search_filters_by_status - Asser...
FAILED tests/test_voice.py::test_align - IndexError: list index out of range
2 failed, 686 passed in 0.44s
"""

ERROR = """==================================== ERRORS ====================================
ERROR tests/test_ingest.py
E   ModuleNotFoundError: No module named 'content.ingest'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
14 deselected, 1 error in 0.12s
"""


def test_summary_line():
    assert q.summary(GREEN) == '688 passed in 0.41s'
    assert q.summary(RED) == '2 failed, 686 passed in 0.44s'
    assert q.summary(ERROR) == '14 deselected, 1 error in 0.12s'
    assert q.summary('зовсім не pytest') == 'підсумкового рядка нема'


def test_failed_ids():
    assert q.failed(GREEN) == []
    assert q.failed(RED) == ['tests/test_commands_v2.py::test_orders_search_filters_by_status',
                             'tests/test_voice.py::test_align']
    assert q.failed(ERROR) == ['tests/test_ingest.py']


def test_failed_ids_are_capped():
    many = '\n'.join(f'FAILED tests/test_x.py::test_{i} - boom' for i in range(30))
    out = q.failed(many, limit=5)
    assert len(out) == 5 and out[0].endswith('::test_0')


def test_render_green_is_one_line():
    text = q.render(GREEN, code=0, log_path='/tmp/x.txt')
    assert text == '✅ 688 passed in 0.41s'


def test_render_red_lists_failures_and_log():
    text = q.render(RED, code=1, log_path='/tmp/x.txt')
    lines = text.splitlines()
    assert lines[0] == '❌ 2 failed, 686 passed in 0.44s'
    assert lines[1] == '• tests/test_commands_v2.py::test_orders_search_filters_by_status'
    assert lines[-1] == 'повний лог: /tmp/x.txt'


def test_render_truncates_and_counts_rest():
    many = '\n'.join(f'FAILED tests/test_x.py::test_{i} - boom' for i in range(25)) + '\n25 failed in 1s'
    lines = q.render(many, code=1, log_path='/tmp/x.txt').splitlines()
    assert sum(1 for l in lines if l.startswith('• ')) == 15
    assert '… і ще 10' in lines
