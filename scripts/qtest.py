#!/usr/bin/env python3
"""Тихий прогін перевірки: підсумок і FAILED у вивід, повний лог — у файл.

    venv/bin/python scripts/qtest.py -q                 # усі тести
    venv/bin/python scripts/qtest.py tests/test_voice.py

Навіщо: повний вивід pytest — це сотні рядків, які осідають у контексті агента.
Аудит TASK-36 показав, що це наш реальний запас, а не розмір промптів.
"""
import re
import subprocess
import sys
from pathlib import Path

FAILED_RE = re.compile(r'^(?:FAILED|ERROR) (\S+)', re.M)
SHOW = 15


def summary(text: str) -> str:
    """Останній підсумковий рядок pytest."""
    hits = [l.strip() for l in text.splitlines()
            if re.search(r'\bin [\d.]+s\b', l)
            and re.search(r'\b(passed|failed|errors?|deselected|skipped)\b', l)]
    return hits[-1] if hits else 'підсумкового рядка нема'


def failed(text: str, limit: int = 100) -> list[str]:
    """Ідентифікатори тестів, що впали або не зібрались."""
    return FAILED_RE.findall(text)[:limit]


def render(text: str, code: int, log_path: str, show: int = SHOW) -> str:
    bad = failed(text)
    if not bad and code == 0:
        return f'✅ {summary(text)}'
    lines = [f'{"✅" if code == 0 else "❌"} {summary(text)}']
    lines += [f'• {b}' for b in bad[:show]]
    if len(bad) > show:
        lines.append(f'… і ще {len(bad) - show}')
    lines.append(f'повний лог: {log_path}')
    return '\n'.join(lines)


def main():
    root = Path(__file__).resolve().parent.parent
    log = root / 'logs' / 'last_test_run.txt'
    log.parent.mkdir(exist_ok=True)
    args = sys.argv[1:] or ['tests/', '-q']      # без аргументів — лише наш пакет тестів
    r = subprocess.run([sys.executable, '-m', 'pytest', *args], cwd=root,
                       capture_output=True, text=True)
    out = r.stdout + r.stderr
    log.write_text(out, encoding='utf-8')
    print(render(out, r.returncode, str(log)))
    sys.exit(r.returncode)


if __name__ == '__main__':
    main()
