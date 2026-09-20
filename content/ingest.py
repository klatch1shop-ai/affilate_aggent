"""Підготовка нотаток сховища зі звітів без запису на диск."""

import json
import re
from datetime import date
from pathlib import PurePosixPath

from tg_dispatcher.privacy import mask_private


VAULT = 'wiki'


def slugify(title: str) -> str:
    """Перетворити заголовок на коротке імʼя нотатки."""
    text = ''.join(
        '-' if char.isspace() or char == '_' else char
        for char in title.lower()
        if char.isalpha() or char.isdigit() or char.isspace() or char in '_-'
    )
    slug = re.sub('-+', '-', text).strip('-')[:60].strip('-')
    if not slug:
        raise ValueError('Заголовок не містить літер чи цифр')
    return slug


def parse_report(text: str) -> dict:
    """Розібрати заголовок, дату та секції markdown-звіту."""
    lines = text.splitlines()
    title = next((line[2:].strip() for line in lines if line.startswith('# ')), None)
    if title is None:
        raise ValueError('У звіті немає заголовка')
    report_date = None
    for line in lines:
        match = re.match(r'^\*\*Дата:\*\* (\d{2})\.(\d{2})\.(\d{4})(?!\d)', line)
        if match:
            day, month, year = map(int, match.groups())
            try:
                report_date = date(year, month, day).isoformat()
            except ValueError:
                pass
            break

    sections = []
    heading = 'Вступ'
    body = []
    in_section = False
    for line in lines:
        if line.startswith('## '):
            content = '\n'.join(body).strip()
            if in_section or content:
                sections.append({'heading': heading, 'body': content})
            heading, body, in_section = line[3:].strip(), [], True
        elif in_section or not (line.startswith('# ') or '**Дата:**' in line):
            body.append(line)
    content = '\n'.join(body).strip()
    if in_section or content:
        sections.append({'heading': heading, 'body': content})
    return {'title': title, 'date': report_date, 'sections': sections}


def wikify(text: str, known) -> str:
    """Повʼязати перші згадки, зберігаючи наявні вікіпосилання."""
    names = sorted({name for name in known if name}, key=lambda name: (-len(name), name))
    if not names:
        return text
    pattern = re.compile(
        r'\[\[.*?\]\]|(?<!\w)(?:' + '|'.join(map(re.escape, names)) + r')(?!\w)',
        re.IGNORECASE | re.DOTALL,
    )
    seen = set()

    def replace(match):
        value = match.group()
        if value.startswith('[['):
            return value
        key = value.casefold()
        if key in seen:
            return value
        seen.add(key)
        return f'[[{value}]]'

    return pattern.sub(replace, text)


def _yaml_value(value: str) -> str:
    """Екранувати значення, які YAML може тлумачити як розмітку."""
    if (value != value.strip() or any(char in value for char in ':#\n\r\t"\\')
            or value.startswith(tuple('-?[]{}!&*|>\'%@`'))
            or value.lower() in {'null', 'true', 'false', '~'}):
        return json.dumps(value, ensure_ascii=False)
    return value


def build_note(report: dict, *, source: str, known=()) -> dict:
    """Підготувати вміст нотатки з маскуванням перед вікіпосиланнями."""
    title = report['title']
    report_date = report['date']
    body = '\n\n'.join(
        f"## {section['heading']}\n{section['body']}"
        for section in report['sections']
    )
    body = wikify(mask_private(body), known)
    frontmatter = (
        f'---\ntitle: {_yaml_value(title)}\n'
        f'date: {report_date or ""}\nsource: {_yaml_value(source)}\n---'
    )
    content = (frontmatter + ('\n\n' + body if body else '')).rstrip('\n') + '\n'
    return {'path': f'{VAULT}/{slugify(title)}.md', 'content': content,
            'title': title, 'date': report_date}


def log_line(note: dict) -> str:
    """Сформувати рядок журналу для підготовленої нотатки."""
    line = f"- [[{PurePosixPath(note['path']).stem}]] — {note['title']}"
    return line + (f" ({note['date']})" if note['date'] else '')


def plan(notes: list[dict], existing: dict) -> dict:
    """Розділити нотатки на створення, пропуски та конфлікти."""
    result = {'create': [], 'skip': [], 'conflict': []}
    seen = set()
    for note in notes:
        path = note['path']
        if path in seen:
            result['conflict'].append(path)
        elif path not in existing:
            result['create'].append(note)
        elif existing[path] == note['content']:
            result['skip'].append(path)
        else:
            result['conflict'].append(path)
        seen.add(path)
    return result
