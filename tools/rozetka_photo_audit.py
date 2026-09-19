#!/usr/bin/env python3
"""Перевірка фото фіду за вимогами Rozetka — ДО відправки на модерацію. Лише читання.

SKILL-36. Привід: 19.09.2026 Rozetka відхилила 5 рукавичок TOPTUL «Фото не
відповідає вимогам» — серед фото була таблиця розмірів S–XXL (асортимент).
Аудит фіду TOPTUL знайшов ще 386 товарів з проблемними фото, але фід уже був
на модерації й змінювати його не можна. Тому перевірка — до подачі.

Вимоги (sellerhelp «Фото товару», 06.02.2026):
  * розмір 400×400 … 4000×4000 px, RGB, JPEG/PNG/WebP/GIF, ≤ 10 МБ, 1–15 фото;
  * на фото — лише цей товар, без асортименту (таблиці розмірів, кілька моделей);
  * схеми й інфографіка дозволені, але НЕ головним фото.

Що робить автоматично: розміри кожного фото (лише заголовок файлу), замалі й
завеликі, головне фото, фото спільні для ≥3 різних товарів. Що НЕ вміє —
розпізнати таблицю чи логотип: для цього будує аркуші мініатюр витягнутих
фото (≥1.6 або ≤0.6) — їх треба переглянути очима.

    python3 tools/rozetka_photo_audit.py output/<фід>.xml --out docs/<фід>_photo_audit.tsv --sheets /tmp/sheets
"""
import argparse
import collections
import csv
import io
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image, ImageDraw, ImageFile

MIN_SIDE, MAX_SIDE, MAX_PICS = 400, 4000, 15


def load(feed):
    offers = {}
    for _, o in ET.iterparse(feed, events=('end',)):
        if o.tag == 'offer':
            art = (o.findtext('article') or o.findtext('vendorCode') or o.get('id') or '').strip()
            offers[art] = {'name': (o.findtext('name_ua') or o.findtext('name') or '').strip(),
                           'pics': [p.text.strip() for p in o.findall('picture') if p.text]}
            o.clear()
    return offers


def dims_of(urls, threads=16):
    s = requests.Session()

    def one(u):
        for rng in ('bytes=0-8191', 'bytes=0-65535', None):
            try:
                r = s.get(u, headers={'Range': rng} if rng else {}, timeout=20)
                p = ImageFile.Parser(); p.feed(r.content)
                if p.image:
                    return u, p.image.size
            except Exception:
                pass
        return u, None
    with ThreadPoolExecutor(threads) as ex:
        return dict(ex.map(one, urls))


def sheets(urls, folder, per=48, cols=6):
    os.makedirs(folder, exist_ok=True)

    def thumb(u):
        try:
            im = Image.open(io.BytesIO(requests.get(u, timeout=20).content)).convert('RGB')
            im.thumbnail((230, 150)); return im
        except Exception:
            return None
    paths = []
    for k in range(0, len(urls), per):
        chunk = urls[k:k + per]
        with ThreadPoolExecutor(12) as ex:
            ims = list(ex.map(thumb, chunk))
        rows = (len(chunk) + cols - 1) // cols
        S = Image.new('RGB', (cols * 240, rows * 175), 'white'); dr = ImageDraw.Draw(S)
        for i, im in enumerate(ims):
            x, y = (i % cols) * 240, (i // cols) * 175
            if im: S.paste(im, (x + 5, y + 20))
            dr.text((x + 5, y + 3), str(k + i), fill='red')
        path = os.path.join(folder, f'sheet_{k // per}.jpg'); S.save(path, quality=80); paths.append(path)
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('feed')
    ap.add_argument('--out', help='TSV з проблемами')
    ap.add_argument('--sheets', help='тека для аркушів мініатюр витягнутих фото')
    a = ap.parse_args()
    offers = load(a.feed)
    urls = sorted({u for v in offers.values() for u in v['pics']})
    dims = dims_of(urls)
    use = collections.defaultdict(set)
    for art, v in offers.items():
        for u in v['pics']:
            use[u].add(re.sub(r'\d{1,2}$', '', art))
    rows, flags = [], collections.Counter()
    long_urls = []
    for art, v in offers.items():
        ps = v['pics']
        if not ps:
            rows.append((art, v['name'], 0, '', 'немає фото', '')); flags['немає фото'] += 1; continue
        if len(ps) > MAX_PICS:
            rows.append((art, v['name'], len(ps), '', f'фото більше {MAX_PICS}', '')); flags['забагато фото'] += 1
        for i, u in enumerate(ps):
            d = dims.get(u)
            if not d:
                why = 'фото не завантажується'
            elif min(d) < MIN_SIDE:
                why = 'ГОЛОВНЕ фото менше 400 px' if i == 0 else 'фото менше 400 px'
            elif max(d) > MAX_SIDE:
                why = 'фото більше 4000 px'
            elif re.search(r'[а-яіїєґА-ЯІЇЄҐ]', u):
                why = 'кирилиця в посиланні на фото'
            else:
                r = d[0] / d[1]
                if r >= 1.6 or r <= 0.6:
                    long_urls.append(u)
                    why = 'витягнуте — ПЕРЕГЛЯНУТИ (таблиця? банер?)' + (' ГОЛОВНЕ' if i == 0 else '')
                elif len(use[u]) >= 3:
                    why = f'одне фото на {len(use[u])} різних товарів — перевірити, чи це саме цей товар'
                else:
                    continue
            rows.append((art, v['name'][:80], i + 1, f'{d[0]}x{d[1]}' if d else '', why, u))
            flags[re.sub(r'\d+', 'N', why)] += 1
    print(f'офферів {len(offers)} · фото {sum(len(v["pics"]) for v in offers.values())} · унікальних {len(urls)}')
    for k, n in flags.most_common():
        print(f'  {n:5} · {k}')
    no_valid = [a for a, v in offers.items() if v['pics'] and all(not dims.get(u) or min(dims[u]) < MIN_SIDE for u in v['pics'])]
    print(f'  товарів без жодного фото ≥ 400 px: {len(no_valid)}')
    if a.out:
        with open(a.out, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f, delimiter='\t'); w.writerow(['article', 'name', 'photo_no', 'size', 'problem', 'url']); w.writerows(rows)
        print(f'→ {a.out}')
    if a.sheets and long_urls:
        for p in sheets(sorted(set(long_urls)), a.sheets):
            print(f'аркуш: {p}')


if __name__ == '__main__':
    main()
