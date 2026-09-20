"""Розбиття тексту й формування субтитрів SRT."""

CPS = 15.0
MIN_SEC = 1.2


def split_lines(text: str, width: int = 32) -> list[str]:
    """Переносити слова без розрізання довгих слів."""
    if width <= 0:
        raise ValueError('Ширина має бути додатною')
    lines = []
    for word in text.split():
        if lines and len(lines[-1]) + 1 + len(word) <= width:
            lines[-1] += ' ' + word
        else:
            lines.append(word)
    return lines


def timings(chunks: list[str], *, start: float = 0.0) -> list[tuple[float, float, str]]:
    """Розмістити фрагменти послідовно без проміжків."""
    result = []
    for chunk in chunks:
        end = start + max(MIN_SEC, len(chunk) / CPS)
        result.append((start, end, chunk))
        start = end
    return result


def _timestamp(seconds: float) -> str:
    """Округлити час до мілісекунд перед розбиттям на складові."""
    milliseconds = round(seconds * 1000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}'


def to_srt(items: list[tuple[float, float, str]]) -> str:
    """Сформувати нумеровані блоки стандартного SRT."""
    return ''.join(f'{i}\n{_timestamp(start)} --> {_timestamp(end)}\n{text}\n\n'
                   for i, (start, end, text) in enumerate(items, 1))
