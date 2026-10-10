#!/usr/bin/env python3
"""Стоп-бренди Rozetka: заборона залежить від БРЕНДА **і** КАТЕГОРІЇ.

Джерело — офіційна таблиця `shared/knowledge_base/rozetka/stop_brands_full.csv`
(597 брендів, три колонки: бренд, умови заборони, винятки).

ЧОМУ ОКРЕМИЙ МОДУЛЬ. 06.10.2026 знайдено три розбіжні трактування однієї
таблиці:
  * `tools/katran_category_xml.py` забороняв Philips і Bosch ЦІЛКОМ, але
    пропускав Xiaomi, Dyson, Apple;
  * `agents/orders/katran_xml_generator.py` — той, що реально збирає фід, —
    не мав фільтра ВЗАГАЛІ (116 товарів заборонених брендів пішли б у фід);
  * наша ж довідка `stop_brands_our.txt` читала перелік категорій як
    «дозволено», хоча колонка зветься «умови ЗАБОРОНИ». Через це LG був
    записаний як дозволений у телевізорах (насправді саме там заборонений)
    і заборонений у холодильниках (насправді дозволений).

Тому рішення одне й читається з першоджерела, а не з переказу.

ЯК ЧИТАЄТЬСЯ ТАБЛИЦЯ:
  правило «Для всіх категорій»      → заборона скрізь
  правило «Категорії: А, Б, В»      → заборона ЛИШЕ в А, Б, В
  виняток «Дозволено ... : Г, Д»    → у Г, Д дозволено попри правило
"""
import csv
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(BASE, 'shared', 'knowledge_base', 'rozetka',
                   'stop_brands_full.csv')


def _cats(text):
    """Перелік категорій із клітинки. Порожньо — значить категорій немає."""
    if not text:
        return []
    t = re.sub(r'^[^:]*:', '', text, count=1) if ':' in text else text
    out = []
    for piece in re.split(r'[,\n;•]', t):
        p = piece.strip(' . ')
        # Відкидаємо хвости на кшталт «та інших» і порожні шматки від «, ,»
        if len(p) > 2 and not p.lower().startswith(('та інш', 'і інш', 'тощо')):
            out.append(p.lower())
    return out


def load(path=CSV):
    rules = {}
    with open(path, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            vals = list(row.values())
            brand = (vals[0] or '').strip()
            if not brand:
                continue
            rule = (vals[1] or '').strip()
            exc = (vals[2] or '').strip()
            rules[brand.upper()] = {
                'всюди': 'для всіх категорій' in rule.lower(),
                'заборонені': _cats(rule) if 'категорі' in rule.lower()
                              and 'для всіх' not in rule.lower() else [],
                'дозволені': _cats(exc) if 'дозволено' in exc.lower() else [],
                'сире_правило': rule[:160],
            }
    return rules


STEM_FIX = [
    # Rozetka вживає РІЗНІ слова для тієї самої категорії: у звіті валідації
    # «Мультипічки і аерогрилі», у стоп-таблиці «Мультипечі та аерогрилі».
    # Через це звірка 06.10 дала 0 збігів із 64 і я мало не оголосив, що
    # Rozetka помиляється в усьому. Насправді помилявся зіставляч.
    ('мультипіч', 'мультипеч'), ('пічк', 'печ'), ('пічок', 'печ'),
    ('відстриган', 'стрижк'), ('праск', 'приладукладанн'),
    ('кавовар', 'кавомашин'),
]


def _norm(s):
    t = (s or '').lower().replace('’', "'").replace('ʼ', "'")
    for a, b in STEM_FIX:
        t = t.replace(a, b)
    return t


def _match(cat, listed):
    """Чи згадана наша категорія у переліку. Порівнюємо основами слів.

    Слова коротші за 4 літери відкидаємо як сполучники («та», «і», «для»),
    але якщо після цього не лишилось нічого — порівнюємо рядки цілком:
    порожня множина є підмножиною будь-якої, і без цієї перевірки коротка
    назва («Фени») збігалася б з УСІМА переліками.
    """
    c = _norm(cat)
    if not c:
        return False
    def stems(x):
        return {w[:6] for w in re.findall(r'[а-яїієґa-z]{4,}', x)
                if w not in ('для', 'тощо', 'інші', 'інша')}
    cw = stems(c)
    if not cw:
        return c in [_norm(i).strip() for i in listed]
    for item in listed:
        iw = stems(_norm(item))
        if iw and (iw <= cw or cw <= iw):
            return True
    return False


def banned(vendor, category, rules):
    """→ (заборонено?, причина). `category` — назва категорії Rozetka."""
    v = (vendor or '').upper().strip()
    if not v:
        return False, ''
    for brand, r in rules.items():
        # Бренд шукаємо як ціле слово: «LG» не має ловити «BLAUFISCH».
        if not re.search(rf'(?<![A-ZА-Я0-9]){re.escape(brand)}(?![A-ZА-Я0-9])', v):
            continue
        if _match(category, r['дозволені']):
            return False, f'{brand}: виняток для «{category}»'
        if r['всюди']:
            return True, f'{brand}: заборона для всіх категорій'
        if r['заборонені'] and _match(category, r['заборонені']):
            return True, f'{brand}: заборона в категорії «{category}»'
        return False, f'{brand}: у списку, але не для «{category}»'
    return False, ''


if __name__ == '__main__':
    rules = load()
    print(f'брендів у таблиці: {len(rules)}')
    for v, c in [('Tefal', 'Блендери'), ('Philips', 'Блендери'),
                 ('Philips', 'Фени'), ('Philips', 'Електрочайники'),
                 ('LG', 'Холодильники'), ('LG', 'Телевізори'),
                 ('Bosch', 'Кухонні витяжки'), ('Bosch', 'Кондиціонери'),
                 ('Ardesto', 'Пилососи'), ('Minola', 'Кухонні витяжки'),
                 ('BLAUFISCH', 'Пилососи')]:
        b, why = banned(v, c, rules)
        print(f'  {"❌" if b else "✅"} {v:<12}{c:<20}{why}')
