"""Самоперевірка модулів на справжніх даних (лише читання).

Навіщо окремий модуль: зелені тести не доводять, що модуль працює на реальних
даних (пастка 10 скіла `codex-worker`). Перевірки передаються ззовні — тут лише
запуск, лічильник часу й текст для власника.
"""
import time

from tg_dispatcher.privacy import mask_private

DETAIL_LIMIT = 220


def run_checks(checks, *, clock=time.monotonic) -> list[dict]:
    """Виконати перевірки; падіння однієї не спиняє решти."""
    results = []
    for name, fn in checks:
        started = clock()
        try:
            detail, ok = fn(), True
        except Exception as exc:                       # noqa: BLE001 — діагностика
            detail, ok = f'{type(exc).__name__}: {exc}', False
        results.append({'name': name, 'ok': ok, 'detail': str(detail),
                        'ms': int((clock() - started) * 1000)})
    return results


def render(results: list[dict], *, limit=DETAIL_LIMIT) -> str:
    """Текст для власника: підсумок, потім рядок на кожну перевірку."""
    if not results:
        return 'Нема перевірок'
    ok = sum(1 for r in results if r['ok'])
    lines = [f'🔬 Самоперевірка: {ok}/{len(results)} пройшло']
    for r in results:
        detail = mask_private(r['detail']).replace('\n', ' ⏎ ')
        if len(detail) > limit:
            detail = detail[:limit] + '…'
        lines.append(f"{'✅' if r['ok'] else '❌'} {r['name']} · {r['ms']} мс · {detail}")
    failed = [r['name'] for r in results if not r['ok']]
    if failed:
        lines.append('Не пройшли: ' + ', '.join(failed))
    return '\n'.join(lines)
