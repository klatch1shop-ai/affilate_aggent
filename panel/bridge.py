"""Посередник: питання з веба → жива сесія Claude Code → одна відповідь.

ЩО ВИПРАВЛЕНО ПІСЛЯ РОЗБОРУ (10.10.2026). Перша версія шукала першу
фінальну відповідь ПІЗНІШЕ ЗА ГОДИННИК. Це давало тихо неправильний
результат: повідомлення з веба стає в чергу, якщо сесія зайнята, і
першим `end_turn` виявлявся фінал ЧУЖОЇ задачі. Власник отримав би
відповідь про щось інше й не дізнався б про це.

Тепер прив'язка до ЯКОРЯ. Спостерігач будить сесію записом, у якому
стоїть номер повідомлення: «ПАНЕЛЬ #10: ...». Перевірено на живому
файлі — такі записи є. Шукаємо фінальну відповідь ПІСЛЯ цього запису,
а не після стінного часу.

ЯК ВІДРІЗНИТИ ФІНАЛЬНУ ВІДПОВІДЬ. `message.stop_reason == 'end_turn'`.
Проміжні тексти між викликами інструментів мають `tool_use`. Окремо
відкидаємо `stop_sequence` — це не відповідь, а службові рядки на кшталт
вичерпаного ліміту.

ЯКИЙ ФАЙЛ ЧИТАТИ. Тек проєктів кілька (`-home-tekken-ai-coding-test`,
`-home-tekken-agentflow-commerce`), і найсвіжіший за часом може належати
ЧУЖІЙ сесії, яка робить іншу роботу. Тому беремо файл, чий `cwd`
збігається з нашим, а свіжість — лише додаткова умова.

ЧОГО ЦЕЙ МІСТ НЕ ВМІЄ. Змусити Claude відповісти. Якщо сесія зупинена,
чекає дозволу в терміналі або хід урвався — відповіді не буде, і це
чесно повертається як «не дочекались», а не вигадується.

ПРИВАТНІСТЬ. Сюди потрапляє текст, який Claude написав власнику в
терміналі. Фільтр секретів нижче — слабка сітка, а не гарантія: він
ловить відомі形и ключів, але не вгадає наперед усе, що може бути
процитоване. Тому обрізаємо довжину і не віддаємо нічого, крім
фінального тексту (ні міркувань, ні викликів інструментів).
"""
import glob
import json
import os
import re
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.expanduser('~/.claude/projects')
CWD = os.getenv('PANEL_SESSION_CWD', '/home/tekken/ai_coding_test')
ВІКНО = 400_000
СТЕЛЯ = 24_000_000
МЕЖА_ТЕКСТУ = 6000

СЕКРЕТИ = re.compile(r'(sk-[A-Za-z0-9_\-]{20,}|AIza[A-Za-z0-9_\-]{20,}'
                     r'|[A-Za-z0-9_\-]{32,}:[A-Za-z0-9_\-]{32,})')
ЯКІР = re.compile(r'ПАНЕЛЬ #(\d+)')


def _час(s):
    """ISO-рядок → datetime. Порівнювати рядками не можна: мітка має
    мікросекунди, транскрипт — мілісекунди, і 'Z' > '9' лексикографічно."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None


def транскрипт():
    """Файл НАШОЇ сесії: збіг за cwd, далі найсвіжіший."""
    свої = []
    for ф in glob.glob(os.path.join(PROJECTS, '*', '*.jsonl')):
        try:
            with open(ф, 'rb') as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 200_000))
                хвіст = f.read().decode('utf-8', 'replace')
        except OSError:
            continue
        cwd = None
        for рядок in reversed(хвіст.splitlines()):
            if '"cwd"' not in рядок or not рядок.startswith('{'):
                continue
            try:
                cwd = json.loads(рядок).get('cwd')
            except Exception:
                continue
            if cwd:
                break
        if cwd == CWD:
            свої.append(ф)
    if not свої:
        return None
    return max(свої, key=os.path.getmtime)


def _записи(шлях, байт):
    with open(шлях, 'rb') as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - байт))
        сирі = f.read().decode('utf-8', 'replace').splitlines()
    out = []
    for рядок in сирі:
        рядок = рядок.strip()
        if рядок.startswith('{'):
            try:
                out.append(json.loads(рядок))
            except Exception:
                continue          # обрізаний перший або ще недописаний рядок
    return out


def _текст(r):
    m = r.get('message') or {}
    if m.get('stop_reason') != 'end_turn':
        return None
    c = m.get('content')
    блоки = c if isinstance(c, list) else []
    т = '\n\n'.join(b.get('text', '') for b in блоки
                    if isinstance(b, dict) and b.get('type') == 'text')
    return т.strip() or None


def відповідь_на(номер, шлях=None):
    """Фінальна відповідь на повідомлення чату #номер, або None.

    Шукаємо запис про підйом із «ПАНЕЛЬ #<номер>», далі перший
    `end_turn` із текстом після нього.
    """
    шлях = шлях or транскрипт()
    if not шлях:
        return None
    байт = ВІКНО
    while байт <= СТЕЛЯ:
        записи = _записи(шлях, байт)
        поз = None
        for i, r in enumerate(записи):
            if r.get('type') != 'user':
                continue
            c = (r.get('message') or {}).get('content')
            txt = c if isinstance(c, str) else ' '.join(
                b.get('text', '') for b in (c or []) if isinstance(b, dict))
            m = ЯКІР.search(txt or '')
            if m and int(m.group(1)) == int(номер) and поз is None:
                # ПЕРШИЙ якір, не останній: спостерігач може підняти сесію
                # на те саме повідомлення двічі, і тоді пошук від останнього
                # якоря проґавив би вже дану відповідь.
                поз = i
        if поз is not None:
            for r in записи[поз + 1:]:
                if r.get('type') != 'assistant' or r.get('isSidechain'):
                    continue
                т = _текст(r)
                if т:
                    return {'текст': СЕКРЕТИ.sub('[приховано]', т[:МЕЖА_ТЕКСТУ]),
                            'час': r.get('timestamp'),
                            'id_відповіді': (r.get('message') or {}).get('id')}
            return None                      # якір є, відповіді ще немає
        байт *= 3
    return None


def стан():
    ф = транскрипт()
    if not ф:
        return {'доступно': False,
                'чому': f'не знайшов сесії з cwd={CWD}'}
    вік = (datetime.now(timezone.utc)
           - datetime.fromtimestamp(os.path.getmtime(ф), timezone.utc))
    сек = round(вік.total_seconds())
    return {'доступно': True, 'файл': os.path.basename(ф),
            'останній_запис_сек_тому': сек,
            'сесія_схоже_жива': сек < 180,
            'застереження': ('час від останнього запису не відрізняє «жива й '
                             'чекає вводу» від «закрита» — це лише підказка')}
