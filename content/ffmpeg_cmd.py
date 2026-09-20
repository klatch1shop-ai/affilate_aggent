"""Побудова аргументів ffmpeg без запуску процесів."""

import math

SIZE = (1080, 1920)


def total_duration(durations: list[float]) -> float:
    """Повернути сумарну тривалість у секундах."""
    return math.fsum(durations)


def slideshow(images: list[str], durations: list[float], out: str, *, audio: str | None = None,
              srt: str | None = None, size: tuple[int, int] = SIZE, fps: int = 30) -> list[str]:
    """Скласти команду вертикального слайдшоу тривалістю до хвилини."""
    if not images or len(images) != len(durations):
        raise ValueError('Потрібні зображення та відповідні тривалості')
    if any(not math.isfinite(d) or d <= 0 for d in durations):
        raise ValueError('Тривалість має бути додатною та скінченною')
    if total_duration(durations) > 60:
        raise ValueError('Тривалість перевищує 60 секунд')
    command = ['ffmpeg', '-y']
    for path, duration in zip(images, durations):
        command.extend(['-loop', '1', '-t', str(duration), '-i', path])
    if audio is not None:
        command.extend(['-i', audio])
    width, height = size
    filters = [
        f'[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,'
        f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}]'
        for i in range(len(images))
    ]
    concat = ''.join(f'[v{i}]' for i in range(len(images)))
    concat += f'concat=n={len(images)}:v=1:a=0'
    if srt is not None:
        concat += f',subtitles={srt}'
    filters.append(concat + '[video]')
    command.extend(['-filter_complex', ';'.join(filters), '-map', '[video]'])
    if audio is not None:
        command.extend(['-map', f'{len(images)}:a:0'])
    command.extend(['-r', str(fps), '-c:v', 'libx264', '-pix_fmt', 'yuv420p'])
    if audio is not None:
        command.append('-shortest')
    command.append(out)
    return command
