#!/usr/bin/env python3
"""
tools/epicentr_photo_audit.py
==============================
Перевірка головного фото картки на вимоги модерації Єпіцентру.

ЧОМУ САМЕ ЦЕ. Зі 89 коментарів модератора на повернутих картках **86 — про
головне фото**, і жодного про характеристики:

    «На головному фото має бути тільки товар — без написів, додаткових
     елементів та речей.»                                   (74 картки)
    «Товар має бути в єдиному екземплярі та єдиному ракурсі.» (11 карток)

Тобто вся робота з атрибутами приймається, а стримує модерацію зображення.

ЩО ПЕРЕВІРЯЄМО (вимоги суворі лише до ПЕРШОГО фото; у галереї модератор
дозволяє інфографіку, коробку й фото в інтерʼєрі):
  * **текст на зображенні** — написи, логотипи, водяні знаки (OCR);
  * **однорідність тла** — по периметру має бути рівний світлий фон;
  * **кілька предметів** — оцінюємо за кількістю окремих контурів.

ЯК ЦЕ ВИКОРИСТОВУВАТИ. Інструмент не редагує зображень: він лише каже, яке
з наявних 4–7 фото придатне на роль головного. У більшості випадків цього
досить — треба просто поставити першим інше фото, а не робити нове.

Рахує на GPU, якщо він є (RTX 4050 → близько 20 фото/с).

    python3 tools/epicentr_photo_audit.py --skus SO1234,SO5678
    python3 tools/epicentr_photo_audit.py --from-comments --limit 40
"""
import os, sys, io, json, argparse, collections
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, '.env'))
API = 'https://core-api.epicentrm.com.ua'
_READER = None
_POSE = None


def pose():
    global _POSE
    if _POSE is None:
        from ultralytics import YOLO
        _POSE = YOLO('yolov8n-pose.pt')
    return _POSE


def has_person(img, conf=0.35):
    """Людина або частина тіла в кадрі.

    Це виявилось головною ознакою після ручного перегляду: забраковані фото —
    це колажі з моделлю, що тримає товар, а прийняті — сам товар на білому.
    Класичні метрики (яскравість, різкість, тло) на цих групах однакові, бо
    порушення тут смислове, а не піксельне.
    """
    try:
        r = pose()(img, verbose=False)[0]
        kp = r.keypoints
        if kp is None or kp.conf is None:
            return 0
        return int((kp.conf > conf).sum())
    except Exception:
        return 0


def collage_panels(img):
    """Скільки окремих панелей у кадрі.

    Колаж «товар + модель + схема» має суцільні світлі смуги-роздільники між
    панелями. Шукаємо їх проєкцією маски товару на осі: два і більше розриви
    означають, що в кадрі кілька окремих зображень, а не один товар.
    """
    import numpy as np, cv2
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    fg = (g < 235).astype(np.uint8)
    h, w = g.shape
    out = 1
    for axis, size in ((0, w), (1, h)):
        prof = fg.sum(axis=axis)
        empty = prof < size * 0.01
        gaps, run = 0, 0
        for i, e in enumerate(empty):
            if e:
                run += 1
            else:
                if run > size * 0.03 and 0 < i - run:
                    gaps += 1
                run = 0
        out = max(out, gaps + 1)
    return out


def reader():
    global _READER
    if _READER is None:
        import easyocr, torch
        _READER = easyocr.Reader(['uk', 'en'], gpu=torch.cuda.is_available(),
                                 verbose=False)
    return _READER


def login(s):
    r = s.post(f'{API}/v2/users/login',
               json={'login': os.getenv('EPICENTR_EMAIL'),
                     'password': os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status()
    s.headers['Authorization'] = f"Bearer {r.json()['token']['auth']}"


def score_image(url, sess):
    """→ ознаки зображення або None, якщо не вдалось прочитати.

    Перевірки взяті з офіційної довідки «Вимоги до візуального контенту»,
    а не з здогадок. Дослівні вимоги:

      * «мінімальна роздільна здатність 500 x 500 px»;
      * «товар має займати від 80 % зображення»;
      * «фото має бути чітким — ні в якому разі розмитим чи зернистим»;
      * «надавайте перевагу білому фону… допустимий інший однотонний фон
         окрім чорного»;
      * «товар має повністю знаходитись у межах зображення»;
      * «не може містити вотермарок, написів, оверлеїв та жодних
         додаткових елементів».

    Перша версія перевіряла лише текст і давала повноту 27 % на розмічених
    картках. Причина була не в порозі, а в тому, що більшість порушень —
    це взагалі не текст: дрібний товар у кадрі, обрізаний край, розмиття.

    Менший `score` — придатніше на роль головного фото.
    """
    import numpy as np, cv2
    try:
        r = sess.get(url, timeout=30)
        if r.status_code != 200:
            return None
        img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
    except Exception:
        return None

    h, w = img.shape[:2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 1. текст: лише впевнені розпізнавання від трьох символів — інакше OCR
    #    «читає» контури самого товару («(Wkhed», «1111» на реальних фото)
    persons = has_person(img)
    panels = collage_panels(img)
    words = [t for _, t, conf in reader().readtext(img)
             if conf >= 0.6 and len(t.strip()) >= 3 and any(ch.isalpha() for ch in t)]

    # 2. тло по периметру
    b = max(4, int(min(h, w) * 0.06))
    edge = np.concatenate([img[:b].reshape(-1, 3), img[-b:].reshape(-1, 3),
                           img[:, :b].reshape(-1, 3), img[:, -b:].reshape(-1, 3)])
    bg_mean, bg_std = float(edge.mean()), float(edge.std())

    # 3. товар у кадрі: маска всього, що відрізняється від тла
    diff = cv2.absdiff(g, int(np.median(cv2.cvtColor(
        edge.reshape(-1, 1, 3), cv2.COLOR_BGR2GRAY))))
    _, mask = cv2.threshold(diff, 28, 255, cv2.THRESH_BINARY)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    big = [c for c in cnts if cv2.contourArea(c) > h * w * 0.005]
    if big:
        xs = [cv2.boundingRect(c) for c in big]
        x0 = min(x for x, y, ww, hh in xs); y0 = min(y for x, y, ww, hh in xs)
        x1 = max(x + ww for x, y, ww, hh in xs); y1 = max(y + hh for x, y, ww, hh in xs)
        occupancy = (x1 - x0) * (y1 - y0) / (h * w)
        cropped = x0 <= 2 or y0 <= 2 or x1 >= w - 2 or y1 >= h - 2
    else:
        occupancy, cropped = 0.0, False

    blur = float(cv2.Laplacian(g, cv2.CV_64F).var())   # < 100 — розмите

    score = (persons * 4                           # людина в кадрі — головна причина
             + (8 if panels > 1 else 0)            # колаж із кількох панелей
             + len(words) * 10                     # написи — груба відмова
             + (6 if min(h, w) < 500 else 0)       # довідка: мінімум 500×500
             + (5 if occupancy < 0.80 else 0)      # довідка: товар від 80 %
             + (4 if bg_mean < 60 else 0)          # чорний фон заборонено
             + (3 if blur < 100 else 0)            # розмите або зернисте
             + (3 if cropped else 0)               # товар має бути цілком у кадрі
             + min(bg_std / 12, 4)                 # неоднорідне тло
             + max(0, len(big) - 1) * 1.5)         # зайві предмети
    return {'url': url, 'persons': persons, 'panels': panels,
            'text': words[:6], 'n_text': len(words),
            'w': w, 'h': h, 'occupancy': round(occupancy, 2), 'cropped': cropped,
            'blur': round(blur), 'bg_mean': round(bg_mean), 'bg_std': round(bg_std),
            'objects': len(big), 'score': round(score, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skus', help='через кому')
    ap.add_argument('--from-json', help='JSON зі списком {sku,id} — контрольна група')
    ap.add_argument('--from-comments', action='store_true',
                    help='взяти картки зі списку зауважень модератора')
    ap.add_argument('--limit', type=int, default=20)
    ap.add_argument('--out')
    a = ap.parse_args()

    s = requests.Session()
    s.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                      'Accept-Language': 'uk-UA'})
    login(s)

    targets = []
    if a.from_comments:
        path = os.path.join(BASE, 'docs', 'epicentr_moderator_comments.json')
        data = json.load(open(path, encoding='utf-8'))
        rows = data if isinstance(data, list) else data.get('items', [])
        for r in rows:
            pid = r.get('productId') or r.get('id')
            sku = r.get('sku')
            if pid:
                targets.append((sku, pid))
    elif a.from_json:
        for r in json.load(open(a.from_json, encoding='utf-8')):
            targets.append((r.get('sku'), r.get('id')))
    elif a.skus:
        for sku in a.skus.split(','):
            d = s.get(f'{API}/v2/pim/products', params={'limit': 1, 'search': sku.strip()},
                      timeout=40).json()
            it = (d.get('items') or [])
            if it:
                targets.append((sku.strip(), it[0]['id']))
    targets = targets[:a.limit]
    print(f'карток до перевірки: {len(targets)}')

    img_sess = requests.Session()
    results = []
    for i, (sku, pid) in enumerate(targets, 1):
        try:
            d = s.get(f'{API}/v2/pim/products/{pid}', timeout=45)
            if d.status_code == 401:
                login(s); d = s.get(f'{API}/v2/pim/products/{pid}', timeout=45)
            j = d.json()
        except Exception as e:
            print(f'  {sku}: {e}', file=sys.stderr); continue
        media = sorted(j.get('media') or [], key=lambda m: (not m.get('isMain'),
                                                            m.get('order') or 0))
        scored = []
        for m in media[:7]:
            u = m.get('source')
            if not u:
                continue
            sc = score_image(u, img_sess)
            if sc:
                sc['isMain'] = bool(m.get('isMain'))
                scored.append(sc)
        if not scored:
            continue
        cur = next((x for x in scored if x['isMain']), scored[0])
        best = min(scored, key=lambda x: x['score'])
        results.append({'sku': j.get('sku'), 'id': pid, 'photos': len(scored),
                        'current': cur, 'best': best,
                        'swap': best['url'] != cur['url']})
        c = cur
        why = []
        if c.get('persons'): why.append(f"людина ({c['persons']} точок)")
        if c.get('panels', 1) > 1: why.append(f"колаж {c['panels']} панелей")
        if c['n_text']: why.append(f"текст{c['text'][:2]}")
        if c['occupancy'] < 0.80: why.append(f"товар {int(c['occupancy']*100)}%")
        if min(c['w'], c['h']) < 500: why.append(f"{c['w']}x{c['h']}")
        if c['blur'] < 100: why.append(f"розмите {c['blur']}")
        if c['bg_mean'] < 60: why.append('чорний фон')
        if c['cropped']: why.append('обрізаний')
        print(f"  [{i}/{len(targets)}] {j.get('sku'):9} фото {len(scored)} | "
              f"score {c['score']:5} | {', '.join(why) if why else 'зауважень немає'}"
              f" | {'ПЕРЕСТАВИТИ' if best['url'] != cur['url'] else '—'}")

    swap = sum(1 for r in results if r['swap'])
    withtext = sum(1 for r in results if r['current']['n_text'] > 0)
    print(f'\nперевірено: {len(results)}')
    print(f'  поточне головне фото МІСТИТЬ ТЕКСТ: {withtext}')
    print(f'  є краще фото серед наявних: {swap}')
    if a.out:
        json.dump(results, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'  → {a.out}')


if __name__ == '__main__':
    main()
