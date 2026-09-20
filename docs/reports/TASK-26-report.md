# Звіт TASK-26

## Що зроблено

- Повторна перевірка за останнім повідомленням про збій (20.09.2026): причина підтверджена — відсутній модуль `content.ingest`, незалежно від `research.debate`. У цій спробі оновлено лише звіт; `research/debate.py` залишено без змін. Виправлення загальної перевірки в дозволених шляхах не виконано: потрібний файл `content/ingest.py` до них не належить.
- Створено `research/debate.py`: `SIDES`, `build_prompts`, `parse_side`, `merge`, `report`.
- Обидва запити містять однакові докази, протилежні завдання й заборону вигадувати факти. Порожні вхідні дані та дублікати ID доказів відхиляються при побудові запитів.
- Реалізовано розбір JSON з огорткою, нормалізацію аргументів, відкидання непідтверджених тез, облік невикористаних доказів і баланс сторін.
- Модуль використовує лише стандартну бібліотеку, не виконує мережевих викликів, друку чи запису файлів. Тести й інші модулі не змінювалися; коміт не створювався.

## Перевірка

Для запобігання побічним файлам перевірки виконано з `PYTHONDONTWRITEBYTECODE=1` та `PYTEST_ADDOPTS='-p no:cacheprovider'`.

Команда:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' venv/bin/python -m pytest tests/test_debate.py -q
```

Код завершення: `0`. Дослівний вивід:

```text
..............                                                           [100%]
14 passed in 0.02s
```

Команда:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' venv/bin/python -m pytest tests/ -q -k 'not debate'
```

Код завершення: `2`. Дослівний вивід:

```text

==================================== ERRORS ====================================
____________________ ERROR collecting tests/test_ingest.py _____________________
ImportError while importing test module '/home/tekken/agent-system/tests/test_ingest.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.13/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_ingest.py:9: in <module>
    ing = importlib.import_module('content.ingest')
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib/python3.13/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ModuleNotFoundError: No module named 'content.ingest'
=========================== short test summary info ============================
ERROR tests/test_ingest.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
14 deselected, 1 error in 0.16s
```

Окрема перевірка збою без збору тестів TASK-26:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' venv/bin/python -m pytest tests/test_ingest.py -q
```

Код завершення: `2`. Дослівний вивід:

```text

==================================== ERRORS ====================================
____________________ ERROR collecting tests/test_ingest.py _____________________
ImportError while importing test module '/home/tekken/agent-system/tests/test_ingest.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.13/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_ingest.py:9: in <module>
    ing = importlib.import_module('content.ingest')
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib/python3.13/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ModuleNotFoundError: No module named 'content.ingest'
=========================== short test summary info ============================
ERROR tests/test_ingest.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.08s
```

Перевірка пошуку модуля в окремому процесі:

```sh
PYTHONDONTWRITEBYTECODE=1 venv/bin/python -c "import importlib.util; print('content:', importlib.util.find_spec('content').origin); print('content.ingest:', importlib.util.find_spec('content.ingest'))"
```

Код завершення: `0`. Дослівний вивід:

```text
content: /home/tekken/agent-system/content/__init__.py
content.ingest: None
```

## Самостійні рішення

- Відповідно до `test_report`, рядок «Відкинуто без доказу» рахує лише причину `без доказу`; невідомі ID зберігаються окремо в `dropped`.
- Використаними вважаються докази лише із зарахованих аргументів: відкинутий аргумент не впливає на `unused`.
- Елементи JSON-списку, що не є словниками, та `point: null` пропускаються як такі, що не містять тези. Інші значення `point` та ID перетворюються на рядки; тип `refs`, відмінний від рядка чи списку, спричиняє `ValueError`, щоб не приховувати некоректну структуру відповіді.
- Не додавати в `research/debate.py` підміну `content.ingest` чи втручання у збір pytest: це приховало б сторонню проблему та порушило б призначення модуля. Фільтр `-k 'not debate'` не усуває імпортів під час збору тестів.

## Що не вдалося, питання

- Загальна перевірка повторно не пройшла через відсутність `content.ingest` при зборі `tests/test_ingest.py:9`. Пакет `content` знаходиться саме в цьому репозиторії; підмодуль відсутній. Помилка відтворюється окремо без імпорту `research.debate`.
- Усунути причину в межах `research/debate.py` і цього звіту неможливо без підміни стороннього модуля. Менеджеру потрібно відновити або реалізувати `content/ingest.py` у межах TASK-20, після чого повторити загальну перевірку. Приймання TASK-26 загалом залишається заблокованим.
- На початку цієї повторної спроби `git status --short` містив лише два невідстежувані дозволені файли: `docs/reports/TASK-26-report.md` і `research/debate.py`. Інші файли не змінювалися, комітів не створено.
