"""Підготовка озвучки з переданими функціями синтезу та виміру тривалості."""

import os
import re

VOICES = {'male': 'uk-UA-OstapNeural', 'female': 'uk-UA-PolinaNeural'}
PAUSE = 0.35


def plan_lines(script: dict) -> list[str]:
    """Зібрати непорожні репліки сценарію в порядку озвучення."""
    lines = [script['hook'], *script['points'], script['cta']]
    return [line.strip() for line in lines if line.strip()]


def synthesize(lines, synth, probe, *, voice='male', rate='+8%', out_dir='.') -> list[dict]:
    """Озвучити репліки, зберігаючи тип помилки невдалого синтезу."""
    voice_code = VOICES.get(voice, voice)
    if not isinstance(voice_code, str) or not re.fullmatch(
        r'[a-z]{2}-[A-Z]{2}-[A-Za-z]+Neural', voice_code
    ):
        raise ValueError('Некоректний голос')

    segments = []
    for index, text in enumerate(lines):
        path = os.path.join(out_dir, f'line_{index:04d}.mp3')
        try:
            synth(text, voice_code, rate, path)
        except Exception as exc:
            segments.append({
                'text': text, 'path': None, 'duration': 0.0,
                'error': type(exc).__name__,
            })
            continue
        segments.append({'text': text, 'path': path, 'duration': probe(path) + PAUSE})
    return segments


def align(segments: list[dict]) -> list[tuple[float, float, str]]:
    """Розташувати успішні сегменти послідовно без проміжків."""
    intervals = []
    start = 0.0
    for segment in segments:
        if segment['path'] is None:
            continue
        end = start + segment['duration']
        intervals.append((start, end, segment['text']))
        start = end
    return intervals


def concat_list(paths: list[str]) -> str:
    """Сформувати список ffmpeg concat з екрануванням апострофів."""
    return ''.join("file '" + path.replace("'", "'\\''") + "'\n" for path in paths)
