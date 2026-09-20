"""Збір та порівняння трендів за переданими даними без зовнішніх дій."""

from datetime import date
import re


def collect(queries, searcher, *, per_query=5, limit=20) -> dict:
    """Збирає унікальні ролики, ізолюючи помилки окремих запитів."""
    result = {'videos': [], 'errors': [], 'asked': 0}
    seen_queries = set()
    seen_ids = set()
    for query in queries:
        if len(result['videos']) >= limit:
            break
        query = query.strip()
        normalized = query.lower()
        if not query or normalized in seen_queries:
            continue
        seen_queries.add(normalized)
        result['asked'] += 1
        try:
            videos = searcher(query, per_query)
        except Exception as exc:
            result['errors'].append(f'{query}: {type(exc).__name__}')
            continue
        for video in videos:
            if not video.get('id') or not video.get('title'):
                continue
            if video['id'] in seen_ids:
                continue
            seen_ids.add(video['id'])
            result['videos'].append(video)
            if len(result['videos']) >= limit:
                break
    return result


def parse_date(value) -> date | None:
    """Розбирає календарну дату у форматі YYYYMMDD або YYYY-MM-DD."""
    if not isinstance(value, str):
        return None
    if not re.fullmatch(r'(?:[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2})', value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def velocity(video, now) -> float | None:
    """Обчислює середні перегляди за добу з мінімальним віком один день."""
    uploaded = parse_date(video.get('upload_date'))
    views = video.get('views')
    if uploaded is None or not isinstance(views, (int, float)):
        return None
    return float(views / max((now - uploaded).days, 1))


def fresh(videos, now, *, days=30) -> list[dict]:
    """Відбирає свіжі ролики зі збереженням початкового порядку."""
    return [video for video in videos
            if (uploaded := parse_date(video.get('upload_date'))) is not None
            and (now - uploaded).days <= days]


def rank(videos, now, *, limit=10) -> list[dict]:
    """Повертає копії роликів за спаданням швидкості та дати публікації."""
    if limit <= 0:
        return []
    ranked = []
    for video in videos:
        speed = velocity(video, now)
        if speed is not None:
            ranked.append({**video, 'velocity': speed})
    ranked.sort(key=lambda video: (video['velocity'], parse_date(video['upload_date'])),
                reverse=True)
    return ranked[:limit]


def diff_topics(current, previous) -> dict:
    """Порівнює множини тем після нормалізації регістру та пробілів."""
    current_set = {' '.join(topic.lower().split()) for topic in current}
    previous_set = {' '.join(topic.lower().split()) for topic in previous}
    return {'new': sorted(current_set - previous_set),
            'gone': sorted(previous_set - current_set),
            'kept': sorted(current_set & previous_set)}


def report(ranked, diff, now) -> str:
    """Формує український текст радара без друку та запису на диск."""
    lines = [f'📈 Радар трендів на {now:%d.%m.%Y}',
             f'Свіжих роликів: {len(ranked)}']
    for video in ranked:
        lines.append(f'• {round(video["velocity"])}/день · «{video["title"]}» — '
                     f'{video.get("channel", "")}')
        lines.append(f'  {video["url"]}')
    if not ranked:
        lines.append('Нема свіжих роликів')
    for key, label in (('new', 'Нові теми'), ('gone', 'Зникли')):
        if diff.get(key):
            lines.append(f'{label}: {", ".join(diff[key])}')
    return '\n'.join(lines)
