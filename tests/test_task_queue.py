"""Черга задач, 26.09.2026. Стережуть саме ті властивості, яких бракувало
сьогодні: стан переживає обрив, зависле повертається в роботу, головне число —
«перевірено двома РІЗНИМИ вендорами», а не лічильник зроблених.
"""
from shared.utils.task_queue import TaskQueue, NEW, RUNNING, DONE, FAILED


def make(tmp_path, n=3):
    q = TaskQueue(str(tmp_path / 'sub' / 'q.db'))       # теку створює сам
    q.add_many([{'key': f'SKU{i}|Колір', 'kind': 'attr', 'payload': {'sku': f'SKU{i}'}}
                for i in range(n)])
    return q


def test_add_is_idempotent(tmp_path):
    """Повторне наповнення не скидає зробленого — інакше перезапуск губив би роботу."""
    q = make(tmp_path)
    q.finish('SKU0|Колір', verdict='ЗБІГ', vendor_a='openrouter', vendor_b='codex')
    added = q.add_many([{'key': 'SKU0|Колір', 'kind': 'attr', 'payload': {}},
                        {'key': 'НОВА', 'kind': 'attr', 'payload': {}}])
    assert added == 1
    assert q.counts()[DONE] == 1


def test_take_marks_running_and_counts_attempt(tmp_path):
    q = make(tmp_path)
    taken = q.take(2)
    assert len(taken) == 2
    assert all(t['attempts'] == 0 for t in taken)       # значення ДО взяття
    assert q.counts()[RUNNING] == 2 and q.counts()[NEW] == 1


def test_take_does_not_hand_out_same_task_twice(tmp_path):
    q = make(tmp_path)
    first = {t['key'] for t in q.take(2)}
    second = {t['key'] for t in q.take(2)}
    assert not (first & second)


def test_payload_survives_roundtrip(tmp_path):
    q = make(tmp_path)
    assert q.take(1)[0]['payload'] == {'sku': 'SKU0'}


def test_finish_with_error_is_failure_not_done(tmp_path):
    """Мовчазне «готова» без результату — через це зіпсований прогін
    виглядав успішним."""
    q = make(tmp_path)
    q.take(1)
    q.finish('SKU0|Колір', error='RuntimeError: 429')
    assert q.counts()[FAILED] == 1
    assert q.failures()[0]['error'].startswith('RuntimeError')


def test_state_survives_reopen(tmp_path):
    """Обрив або вимкнення не має губити прогрес."""
    path = str(tmp_path / 'q.db')
    q = TaskQueue(path)
    q.add_many([{'key': 'A', 'kind': 'attr', 'payload': {}}])
    q.finish('A', verdict='ЗБІГ', vendor_a='openrouter', vendor_b='gemini')
    q.close()

    again = TaskQueue(path)
    assert again.counts()[DONE] == 1
    assert again.verified_by_two() == 1


def test_stale_running_returns_to_queue(tmp_path):
    q = make(tmp_path)
    q.take(1, now=1000)
    assert q.requeue_stale(older_than_sec=600, now=1000 + 100) == 0   # ще свіжа
    assert q.requeue_stale(older_than_sec=600, now=1000 + 700) == 1   # зависла
    assert q.counts()[NEW] == 3


# ── головна метрика ───────────────────────────────────────────────────

def test_same_vendor_does_not_count_as_verified(tmp_path):
    """Саме це знецінило попередній прогін: 196 із 218 «ЗБІГів» — модель
    погодилась сама з собою."""
    q = make(tmp_path)
    q.finish('SKU0|Колір', verdict='ЗБІГ', vendor_a='codex', vendor_b='codex')
    assert q.verified_by_two() == 0

    q.finish('SKU1|Колір', verdict='ЗБІГ', vendor_a='codex', vendor_b='openrouter')
    assert q.verified_by_two() == 1


def test_single_source_does_not_count_as_verified(tmp_path):
    q = make(tmp_path)
    q.finish('SKU0|Колір', verdict='НЕ ПЕРЕВІРЕНО (одне джерело)', vendor_a='codex')
    assert q.verified_by_two() == 0


def test_vendor_usage_shows_pool_narrowing(tmp_path):
    q = make(tmp_path, n=2)
    q.finish('SKU0|Колір', vendor_a='codex', vendor_b='codex')
    q.finish('SKU1|Колір', vendor_a='openrouter', vendor_b='codex')
    assert q.vendor_usage() == {'codex': 3, 'openrouter': 1}


def test_verdict_counts(tmp_path):
    q = make(tmp_path)
    q.finish('SKU0|Колір', verdict='ЗБІГ', vendor_a='a', vendor_b='b')
    q.finish('SKU1|Колір', verdict='ЗБІГ', vendor_a='a', vendor_b='b')
    q.finish('SKU2|Колір', verdict='РОЗБІЖНІСТЬ', vendor_a='a', vendor_b='b')
    assert q.verdict_counts() == {'ЗБІГ': 2, 'РОЗБІЖНІСТЬ': 1}
