#!/usr/bin/env python3
"""Вибір головного фото картки за детермінованими ознаками.

Навіщо: 96 % відмов модерації Єпіцентру — одне формулювання, «головне фото
має містити тільки товар, без написів, додаткових елементів та речей».

Чому НЕ вердикт моделі: перевірено 30.09 — та сама картинка у двох прогонах
дала протилежні відповіді. OCR і метрики зображення на тому самому файлі
дають той самий результат завжди.

ГОЛОВНА ВІДМІННІСТЬ ВІД ПОРАДИ КОЛЕГ. Вони пропонували відкидати фото, на
якому OCR знайшов текст. Gemini сам же вказав, де це зламається: у
мастурбаторів і фалоімітаторів чисте студійне фото зняте НА ФІРМОВІЙ КОРОБЦІ
з брендовим написом — алгоритм відкинув би його і підставив гірший кадр.

Тому тут не поріг, а **порівняння**: з наявних 4-5 фото береться те, у якого
найменше тексту й найрівніше тло. Якщо всі погані — картка йде в чергу на
ручний розгляд, а не у фід навмання.

    python3 tools/photo_pick_main.py --skus SO1234,SO5678
    python3 tools/photo_pick_main.py --status banned --limit 50
"""
import argparse
import io
import json
import os
import sys

import numpy as np
import requests
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

_reader = None


def ocr_reader():
    """easyocr вантажить моделі при першому виклику — тримаємо один екземпляр."""
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(['uk', 'en'], gpu=False, verbose=False)
    return _reader


def fetch(url, timeout=30):
    r = requests.get(url, timeout=timeout,
                     headers={'User-Agent': 'Mozilla/5.0'})
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert('RGB')


def text_coverage(img):
    """Частка площі кадру, зайнята текстом (0..1), і кількість блоків."""
    arr = np.array(img)
    try:
        boxes = ocr_reader().readtext(arr, detail=1, paragraph=False)
    except Exception:
        return None, None
    area = img.width * img.height
    covered = 0
    for box, _text, conf in boxes:
        if conf < 0.3:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        covered += max(0, max(xs) - min(xs)) * max(0, max(ys) - min(ys))
    return min(1.0, covered / area), len(boxes)


def background_score(img, band=0.06):
    """Наскільки однорідна рамка кадру: 1.0 — ідеально рівне тло.

    Беремо смугу по периметру, бо товар майже завжди в центрі.
    """
    a = np.array(img).astype(np.int16)
    h, w, _ = a.shape
    bh, bw = max(1, int(h * band)), max(1, int(w * band))
    border = np.concatenate([
        a[:bh].reshape(-1, 3), a[-bh:].reshape(-1, 3),
        a[:, :bw].reshape(-1, 3), a[:, -bw:].reshape(-1, 3)])
    std = border.std(axis=0).mean()
    light = border.mean() / 255.0
    return float(max(0.0, 1.0 - std / 60.0)), float(light)


def collage_score(img):
    """Ознака колажу: різкі суцільні лінії поділу всередині кадру."""
    import cv2
    g = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    h, w = g.shape
    col = np.abs(np.diff(g.astype(np.int16), axis=1)).mean(axis=0)
    row = np.abs(np.diff(g.astype(np.int16), axis=0)).mean(axis=1)
    inner_c = col[int(w * 0.15):int(w * 0.85)]
    inner_r = row[int(h * 0.15):int(h * 0.85)]
    peaks = int((inner_c > inner_c.mean() + 4 * inner_c.std()).sum() +
                (inner_r > inner_r.mean() + 4 * inner_r.std()).sum())
    return peaks


def edge_text(img, band=0.22, conf_min=0.4):
    """Написи по РАМЦІ кадру — вотермарки й логотипи студії.

    Чому не по всьому кадру: Gemini вказав, що у мастурбаторів і
    фалоімітаторів чисте фото зняте на фірмовій коробці з брендовим
    написом — суцільний OCR відкинув би добрий кадр. Вотермарка ж сидить
    у куті або по краю. Перевірено 02.10: 0 на обох прийнятих Єпіцентром
    фото конкурента, 2 на SX1769, який Єпіцентр відхилив за написи.

    Коштує ~2 с на знімок (хвилина з першого виклику — то завантаження моделі).
    """
    a = np.array(img)
    h, w, _ = a.shape
    bh, bw = int(h * band), int(w * band)
    found = 0
    for part in (a[:bh], a[-bh:], a[:, :bw], a[:, -bw:]):
        try:
            boxes = ocr_reader().readtext(part, detail=1, paragraph=False)
        except Exception:
            return None
        found += sum(1 for _b, t, c in boxes if c >= conf_min and len(t.strip()) >= 2)
    return found


def object_count(img, min_frac=0.004):
    """Скільки окремих предметів у кадрі.

    Додано 02.10 після опровергнення: сітка з 9 презервативів на білому тлі
    отримала максимальний бал 6.0, хоча Єпіцентр відхилив її саме за фото
    («товар має бути в єдиному екземплярі»). Лінії поділу там відсутні —
    предмети розділені самим тлом, тому collage_score їх не бачив.

    Тло визначаємо за кольором рамки кадру, рахуємо зв'язні області, що
    відрізняються від нього і займають понад min_frac площі.
    """
    import cv2
    a = np.array(img)
    h, w, _ = a.shape
    bh = max(1, int(h * 0.04))
    bg = np.median(np.concatenate([a[:bh].reshape(-1, 3), a[-bh:].reshape(-1, 3)]),
                   axis=0)
    dist = np.abs(a.astype(np.int16) - bg.astype(np.int16)).sum(axis=2)
    mask = (dist > 40).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(mask, connectivity=8)
    area = h * w
    return sum(1 for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > area * min_frac)


def rate(url, use_ocr=True, use_edge_text=True):
    """use_ocr=False — для масових прогонів.

    Калібрування 02.10 показало, що вирішальна ознака — КОЛАЖ, а не текст:
    у трьох із чотирьох відхилених Єпіцентром фото тексту нуль, а ліній
    поділу 4-10, тоді як у прийнятих — рівно нуль. OCR додає хвилину на
    знімок (19 годин на 1000 фото) і майже не впливає на рішення.
    """
    img = fetch(url)
    cov, blocks = text_coverage(img) if use_ocr else (0.0, 0)
    edges = edge_text(img) if use_edge_text else 0
    bg, light = background_score(img)
    peaks = collage_score(img)
    objects = object_count(img)
    # менше тексту, рівніше й світліше тло, менше ліній поділу — краще
    score = ((1 - (cov or 0)) * 3 + bg * 2 + light
             - min(peaks, 5) * 0.4 - max(0, objects - 1) * 1.2
             - min(edges or 0, 4) * 1.0)
    return {'url': url, 'text': round(cov or 0, 4), 'blocks': blocks,
            'bg': round(bg, 3), 'light': round(light, 3),
            'collage': peaks, 'objects': objects, 'edge_text': edges, 'score': round(score, 3),
            'size': f'{img.width}x{img.height}'}


def pick(urls, min_score=3.9, use_ocr=False):
    rated = []
    for u in urls:
        try:
            rated.append(rate(u, use_ocr=use_ocr))
        except Exception as exc:
            rated.append({'url': u, 'error': f'{type(exc).__name__}'})
    ok = [r for r in rated if 'error' not in r]
    if not ok:
        return None, rated
    best = max(ok, key=lambda r: r['score'])
    return (best if best['score'] >= min_score else None), rated


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--urls', help='фото через кому — для перевірки')
    a = ap.parse_args()
    if a.urls:
        best, rated = pick([u.strip() for u in a.urls.split(',')])
        for r in rated:
            print(json.dumps(r, ensure_ascii=False))
        print('\nОБРАНО:', best['url'] if best else 'жодне не пройшло поріг')
