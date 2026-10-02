#!/usr/bin/env python3
"""Ключові слова за принципом «слот несе те, чого немає в назві».

Підстава — два незалежні джерела:

* **Довідка Prom для продавців:** пріоритет полів «назва → характеристики →
  ключові слова», і при ранжуванні «враховується тільки ПЕРШЕ входження слів
  із запиту». Отже фраза, всі слова якої вже є в назві, зараховується по
  назві, а слот витрачено намарно.
* **Рекомендація Amazon для продавців:** «Don't repeat words from other
  fields, such as Title or Brand Name» — слово з назви вже проіндексоване.

Вимога менеджера Prom: ключ має бути таким, «як я б шукав свій товар». Тому
у слот іде те, що є **приводом для пошуку** (синонім типу, транслітерація
бренду, призначення, ефект), а не будь-яка заповнена ознака.

Виміряно до змін: у «Вібраторах» 36 % українських слотів покриті назвою,
у «Лубрикантах» — 28 %.
"""
import re

MAX_SLOTS = 9
WORD_RE = re.compile(r'\w+', re.UNICODE)


def words(text):
    return set(WORD_RE.findall((text or '').lower()))


def covered_by(phrase, known):
    """Чи всі слова фрази вже є в назві та характеристиках."""
    w = words(phrase)
    return bool(w) and w <= known


def known_words(card):
    """Слова назви й характеристик — те, що Prom уже зарахує з вищим пріоритетом."""
    parts = [card.get('name_ua', ''), card.get('name', '')]
    for k, v in (card.get('params') or {}).items():
        parts.append(f'{k} {v}')
    return words(' '.join(parts))


def norm(text):
    """Нормалізований рядок для пошуку фрази як суцільного підрядка."""
    return ' ' + ' '.join(WORD_RE.findall((text or '').lower())) + ' '


def wasted(phrase, card):
    """Чи слот справді змарновано.

    Обережніше, ніж «усі слова вже відомі». Довідка Prom каже, що довгий
    запит береться **повним збігом у межах одного ключового слова**, тому
    ціла фраза лишається цінною навіть коли її слова є в назві НАРІЗНО.
    Змарнованою вважаємо лише фразу, яка вже стоїть у назві суцільним
    шматком — її Prom зарахує по назві, з вищим пріоритетом.
    """
    return norm(phrase).strip() and norm(phrase) in norm(card.get('name_ua', ''))


def select(card, candidates, keep_existing=True, limit=MAX_SLOTS):
    """Відбір фраз у слоти.

    Фраза проходить, лише якщо додає бодай одне слово, якого ще немає ні в
    назві, ні в характеристиках, ні у вже відібраних фразах. Так кожен слот
    несе новий пошуковий шлях до товару, а не повторює наявний.
    """
    chosen, dropped = [], []
    source = (list(card.get('kw_ua') or []) if keep_existing else []) + list(candidates)
    for p in source:
        p = re.sub(r'\s+', ' ', (p or '')).strip().lower()
        if not p or p in chosen:
            continue
        if wasted(p, card):
            dropped.append(p)
            continue
        chosen.append(p)
        if len(chosen) >= limit:
            break
    return chosen, dropped
