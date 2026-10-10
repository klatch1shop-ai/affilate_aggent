"""Посередник: повідомлення з веба → жива сесія Claude Code → одна відповідь.

ЗАДУМ ВЛАСНИКА (10.10.2026). У веб говорити з відкритою сесією не можна —
це різні процеси. Але відповідь із неї ЗАБРАТИ можна: Claude Code пише
транскрипт сесії у JSONL, і файл дописується живо (перевірено: +9930
байт за 3 секунди). Посередник кладе питання в базу, сесію будить
наявний Monitor, а звідси ми забираємо РІВНО ОДНУ фінальну відповідь.

ЯК ВІДРІЗНИТИ ФІНАЛЬНУ ВІДПОВІДЬ. У кожного асистентського запису є
`message.stop_reason`. Проміжні тексти між викликами інструментів мають
`tool_use`; фінальна відповідь ходу — `end_turn`. Перевірено на живому
файлі: 80 записів `tool_use` і 4 `end_turn`, і саме ці чотири виявились
відповідями власнику. Додатково відсіюємо `isSidechain=true` — це робота
колег-підагентів, не відповідь людині.

ЧОМУ НЕ ЧИТАЄМО ФАЙЛ ЦІЛКОМ. Він 231 МБ і росте. Читаємо хвіст із кінця,
збільшуючи вікно, доки не знайдемо потрібне або не впремось у стелю.

МЕЖА ВІДПОВІДАЛЬНОСТІ. Посередник НЕ вміє змусити Claude відповісти. Якщо
сесія не працює, відповіді не буде — і він так і скаже, а не вигадає.
"""
import glob
import json
import os
import re
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.expanduser('~/.claude/projects')
ВІКНО = 400_000          # з якого хвоста починаємо
СТЕЛЯ = 12_000_000       # далі не лізем: відповідь мала б бути поруч із кінцем

# Якщо у відповідь колись потрапить щось схоже на ключ — не віддаємо.
СЕКРЕТИ = re.compile(r'(sk-[A-Za-z0-9_\-]{20,}|AIza[A-Za-z0-9_\-]{20,}'
                     r'|[A-Za-z0-9_\-]{32,}:[A-Za-z0-9_\-]{32,})')


def транскрипт():
    """Найсвіжіший файл сесії. Сесій буває кілька — беремо той, що пишеться."""
    файли = glob.glob(os.path.join(PROJECTS, '*', '*.jsonl'))
    if not файли:
        return None
    return max(файли, key=os.path.getmtime)


def _записи(шлях, байт):
    with open(шлях, 'rb') as f:
        f.seek(0, os.SEEK_END)
        розмір = f.tell()
        f.seek(max(0, розмір - байт))
        сирі = f.read().decode('utf-8', 'replace').splitlines()
    out = []
    for рядок in сирі:
        рядок = рядок.strip()
        if not рядок.startswith('{'):
            continue
        try:
            out.append(json.loads(рядок))
        except Exception:
            continue          # перший рядок майже завжди обрізаний
    return out


def відповідь_після(мітка, шлях=None):
    """Перша ФІНАЛЬНА відповідь із часом пізніше за `мітка` (ISO-рядок)."""
    шлях = шлях or транскрипт()
    if not шлях:
        return None
    байт = ВІКНО
    while байт <= СТЕЛЯ:
        найдавніший = None
        for r in _записи(шлях, байт):
            ts = r.get('timestamp') or ''
            if найдавніший is None and ts:
                найдавніший = ts
            if r.get('type') != 'assistant' or r.get('isSidechain'):
                continue
            m = r.get('message') or {}
            if m.get('stop_reason') != 'end_turn':
                continue
            if ts <= мітка:
                continue
            тексти = [b.get('text', '') for b in (m.get('content') or [])
                      if isinstance(b, dict) and b.get('type') == 'text']
            текст = '\n\n'.join(t for t in тексти if t.strip())
            if текст.strip():
                return {'текст': СЕКРЕТИ.sub('[приховано]', текст),
                        'час': ts}
        # Не знайшли, але вікно вже накриває час запиту — отже відповіді ще нема.
        if найдавніший and найдавніший <= мітка:
            return None
        байт *= 3
    return None


def чекати(мітка, секунд=180, крок=3):
    """Чекати одну відповідь. Повертає None, якщо не дочекались."""
    кінець = time.time() + секунд
    while time.time() < кінець:
        r = відповідь_після(мітка)
        if r:
            return r
        time.sleep(крок)
    return None
