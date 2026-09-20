"""План монтажу й аргументи ffmpeg без запуску процесів."""

FPS, W, H = 30, 1080, 1920
TEMPLATES = ('zoom_in', 'zoom_out', 'pan_right', 'static')
ROTATION = ('zoom_in', 'pan_right', 'zoom_out')
FIT = 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920'


def frames(duration, fps=FPS) -> int:
    """Обчислити кількість кадрів для додатної тривалості."""
    if duration <= 0:
        raise ValueError('Тривалість має бути додатною')
    return max(1, round(duration * fps))


def shot_filter(template, duration, index, *, fps=FPS) -> str:
    """Побудувати фільтр руху одного зображення."""
    if template not in TEMPLATES:
        raise ValueError('Невідомий шаблон руху')
    n = frames(duration, fps)
    movements = {
        'zoom_in': "z='min(zoom+0.0009,1.18)'",
        'zoom_out': "z='if(eq(on,0),1.18,max(zoom-0.0009,1.0))'",
        'pan_right': f"z=1.18:x='iw*0.18*on/{n}'",
        'static': 'z=1',
    }
    movement = f'zoompan={movements[template]}:d={n}:s={W}x{H}:fps={fps}'
    return f'[{index}:v]{FIT},{movement},setsar=1[v{index}]'


def title_filter(text, start, end, *, size=64, position='bottom') -> str:
    """Побудувати титр із заданими часом і положенням."""
    positions = {'bottom': 'h-360', 'top': '240', 'center': '(h-text_h)/2'}
    if position not in positions:
        raise ValueError('Невідоме положення титру')
    if start >= end:
        raise ValueError('Початок титру має передувати завершенню')
    escaped = text.replace('\\', '\\\\')
    for character in ("'", ':', '%'):
        escaped = escaped.replace(character, '\\' + character)
    return (
        f"drawtext=text='{escaped}':fontsize={size}:fontcolor=white:borderw=4:"
        f'bordercolor=black@0.8:x=(w-text_w)/2:y={positions[position]}:'
        f"enable='between(t,{start:.2f},{end:.2f})'"
    )


def plan_shots(images, durations, templates=None) -> list[dict]:
    """Розподілити шаблони по колу між зображеннями."""
    if not images or len(images) != len(durations):
        raise ValueError('Потрібні зображення та відповідні тривалості')
    rotation = ROTATION if templates is None else templates
    if not rotation or any(template not in TEMPLATES for template in rotation):
        raise ValueError('Потрібен непорожній список відомих шаблонів')
    return [
        {'image': image, 'duration': duration,
         'template': rotation[index % len(rotation)], 'index': index}
        for index, (image, duration) in enumerate(zip(images, durations))
    ]


def build_filtergraph(shots, titles=(), *, srt=None) -> str:
    """З'єднати кадри, титри й субтитри у граф із виходом vout."""
    if not shots:
        raise ValueError('План кадрів не може бути порожнім')
    filters = [
        shot_filter(shot['template'], shot['duration'], shot['index'])
        for shot in shots
    ]
    inputs = ''.join(f"[v{shot['index']}]" for shot in shots)
    filters.append(f'{inputs}concat=n={len(shots)}:v=1:a=0[vcat]')
    previous = 'vcat'
    if titles:
        title_filters = []
        for title in titles:
            text, start, end, *position = title
            title_filters.append(title_filter(
                text, start, end, position=position[0] if position else 'bottom',
            ))
        filters.append('[vcat]' + ','.join(title_filters) + '[vtxt]')
        previous = 'vtxt'
    if srt is not None:
        filters.append(
            f"[{previous}]subtitles={srt}:force_style='Fontsize=18,Outline=2'[vout]"
        )
    else:
        filters.append(f'[{previous}]null[vout]')
    return ';'.join(filters)


def command(images, durations, out, *, titles=(), audio=None, music=None,
            srt=None) -> list[str]:
    """Скласти команду монтажу з необов'язковими голосом і музикою."""
    shots = plan_shots(images, durations)
    graph = build_filtergraph(shots, titles, srt=srt)
    args = ['ffmpeg', '-y']
    for shot in shots:
        args.extend(['-loop', '1', '-t', f"{shot['duration']:.3f}", '-i', shot['image']])
    sounds = [path for path in (audio, music) if path is not None]
    for path in sounds:
        args.extend(['-i', path])
    if len(sounds) == 2:
        graph += (
            f';[{len(shots)}:a]volume=1[a0];'
            f'[{len(shots) + 1}:a]volume=0.12[a1];'
            '[a0][a1]amix=inputs=2:duration=first[aout]'
        )
    args.extend(['-filter_complex', graph, '-map', '[vout]'])
    if sounds:
        mapping = '[aout]' if len(sounds) == 2 else f'{len(shots)}:a'
        args.extend(['-map', mapping, '-shortest'])
    args.extend(['-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
                 '-pix_fmt', 'yuv420p', '-r', str(FPS), out])
    return args
