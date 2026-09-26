"""Складання дошки завдань — чисті функції, без мережі й файлів.

Головне правило: числа сюди **не вписуються руками**. Той, хто викликає,
зчитує їх із справжніх джерел (черга задач, лог, API) і передає сюди на
складання тексту. 26.09.2026 ми цілий день дивились на лічильник
«1385 з 1790», поки 94% тієї роботи були неперевіреними — дошка має
показувати те, що справді важить, а не те, що приємно зростає.
"""

GREEN, RED, YELLOW = '🟢', '🔴', '🟡'


def health(track):
    """Колір колії: блокована → червоний, є рух → зелений, стоїть → жовтий."""
    if track.get('blocker'):
        return RED
    return GREEN if track.get('moving') else YELLOW


def percent(part, whole):
    if not whole:
        return 0
    return round(part * 100 / whole)


def bar(part, whole, width=16):
    filled = min(width, round(width * (part / whole))) if whole else 0
    return '█' * filled + '░' * (width - filled)


def render_track(track):
    """Один блок дошки. `track`: name, done, total, verified, blocker,
    next_step, moving, notes."""
    lines = [f"## {health(track)} {track['name']}"]
    total, done = track.get('total') or 0, track.get('done') or 0
    if total:
        lines.append(f"`{bar(done, total)}` {done}/{total} ({percent(done, total)} %)")
    verified = track.get('verified')
    if verified is not None and total:
        lines.append(f"**перевірено двома різними вендорами: {verified}** "
                     f"({percent(verified, total)} %)")
    if track.get('blocker'):
        lines.append(f"- заблоковано: {track['blocker']}")
    for note in track.get('notes') or []:
        lines.append(f"- {note}")
    if track.get('next_step'):
        lines.append(f"- далі: {track['next_step']}")
    return '\n'.join(lines)


def render_vendors(vendors):
    """`vendors`: список {name, alive, useful, note}. Живий і придатний —
    різні речі: 26.09 Gemini відповідав за 0.8 с і на всіх картках казав
    «НЕ ВИДНО»."""
    if not vendors:
        return ''
    lines = ['## Провайдери', '', '| вендор | живий | придатний | примітка |',
             '|---|---|---|---|']
    for v in vendors:
        # None — «не питали», і це НЕ те саме, що «мертвий». Без цієї різниці
        # дошка з --no-probe показувала всіх провайдерів як недоступних.
        alive = v.get('alive')
        alive = '—' if alive is None else ('✅' if alive else '✖️')
        useful = v.get('useful')
        useful = '—' if useful is None else ('✅' if useful else '✖️')
        lines.append(f"| {v['name']} | {alive} | {useful} | {v.get('note', '')} |")
    return '\n'.join(lines)


def render(tracks, vendors=None, now='', needs_owner=None):
    parts = [f'# Дошка завдань · {now}'.rstrip(' ·'), '']
    if needs_owner:
        parts.append('## ⚠️ Потребує вашої дії')
        parts += [f'- {item}' for item in needs_owner]
        parts.append('')
    for track in tracks:
        parts.append(render_track(track))
        parts.append('')
    vendors_block = render_vendors(vendors or [])
    if vendors_block:
        parts.append(vendors_block)
    return '\n'.join(parts).rstrip() + '\n'


def render_telegram(tracks, vendors=None, now='', needs_owner=None):
    """Коротке зведення для Telegram — без таблиць, вони там нечитабельні."""
    lines = [f'📊 <b>Дошка</b> {now}'.strip(), '']
    for track in tracks:
        total, done = track.get('total') or 0, track.get('done') or 0
        lines.append(f"{health(track)} <b>{track['name']}</b>")
        if total:
            lines.append(f'  {done}/{total} ({percent(done, total)} %)')
        if track.get('verified') is not None:
            lines.append(f"  перевірено двома: {track['verified']}")
        if track.get('blocker'):
            lines.append(f"  стоїть: {track['blocker']}")
        lines.append('')
    alive = [v['name'] for v in (vendors or []) if v.get('alive')]
    if vendors:
        lines.append(f"провайдери живі: {', '.join(alive) if alive else 'жодного'}")
    if needs_owner:
        lines.append('')
        lines.append('⚠️ <b>Потребує вашої дії:</b>')
        lines += [f'• {item}' for item in needs_owner]
    return '\n'.join(lines).strip()
