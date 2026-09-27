#!/usr/bin/env python3
"""Доводить наші картки EVA до рівня карток конкурентів у тій самій категорії.

Схема (ідея власника, 27.09): взяти картку конкурента з тієї самої категорії
EVA як еталон, поряд покласти нашу, і дати моделі завдання підтягнути нашу до
еталона. Це те саме «вчитись на тому, що майданчик уже прийняв», тільки
застосоване не до кодів характеристик, а до якості картки.

Головне обмеження — **модель не має права вигадувати факти**. Вона
переписує й структурує те, що вже є в наших даних, і не додає жодного числа,
якого немає у вихідній картці. Перевіряє це `invented_numbers()` вже після
відповіді: всі числа з результату мусять бути у вхідних даних. Картка, яка
перевірку не пройшла, не приймається.

    python3 tools/eva_card_improve.py --limit 10 --dry-run
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from shared.utils import vendor_pool  # noqa: E402

ITEMS = os.path.join(BASE, 'exports', 'eva_feed_items_cosmetics.json')
BENCH = os.path.join(BASE, 'exports', 'eva_competitors_cards.json')
OUT = os.path.join(BASE, 'exports', 'eva_cards_improved.json')

NUM_RE = re.compile(r'\d+(?:[.,]\d+)?')


def strip_html(text):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', text or '')).strip()


def invented_numbers(source, result):
    """Числа, що зʼявились у результаті, але яких немає у вихідних даних.

    Саме так минулого разу модель вигадала ТТХ: числа виглядають переконливо
    і без цієї перевірки проходять непоміченими.
    """
    src = {n.replace(',', '.') for n in NUM_RE.findall(source)}
    return sorted({n.replace(',', '.') for n in NUM_RE.findall(result)} - src)


def lost_numbers(source, result):
    """Числа з вихідної картки, які зникли в результаті.

    Перший прогін показав, що без цієї перевірки модель підлаштовується під
    короткий еталон конкурента і викидає наші факти: з назви зникло «без
    цукру, їстівний», опис усох з 1458 до 495 символів. Вигадування — не
    єдиний спосіб зіпсувати картку; втрата фактів так само шкідлива.
    """
    src = {n.replace(',', '.') for n in NUM_RE.findall(source)}
    return sorted(src - {n.replace(',', '.') for n in NUM_RE.findall(result)})


def build_prompt(item, benchmarks):
    ours = (f"Назва (укр): {item['name_ua']}\n"
            f"Назва (рос): {item['name_ru']}\n"
            f"Опис (укр): {strip_html(item['description_ua']) or '— немає —'}\n"
            f"Характеристики: {json.dumps(item['params'], ensure_ascii=False) or '—'}\n"
            f"Бренд: {item['vendor']}\nФото: {len(item['pictures'])} шт.")
    ref = '\n\n'.join(
        f"--- Картка конкурента {n} ---\nНазва: {b['name']}\n"
        f"Характеристики: {json.dumps(b.get('params', {}), ensure_ascii=False)}\n"
        f"Опис: {strip_html(b.get('description', ''))[:900]}"
        for n, b in enumerate(benchmarks, 1))
    return f"""Ти готуєш картку товару для українського маркетплейсу EVA.

Нижче картки конкурентів у ТІЙ САМІЙ категорії — це еталон, який майданчик уже прийняв.

{ref}

--- НАША КАРТКА ---
{ours}

Завдання: довести нашу картку до рівня еталона.

Еталон показує СТРУКТУРУ й набір характеристик, а не обсяг тексту. Не
скорочуй нашу картку до розміру еталона.

ЗАБОРОНЕНО вигадувати факти. Не додавай жодного числа, обʼєму, складу,
терміну чи властивості, якого немає в нашій картці вище. Якщо для поля
характеристики в нас немає даних — пропусти це поле, не здогадуйся.

ЗАБОРОНЕНО втрачати факти. Усі властивості з нашої назви й опису мають
лишитись: «без цукру», «їстівний», «з афродизіаками», обʼєм, країна, склад.
Опис не має стати коротшим за наш.

Дозволено: переписати текст, структурувати його, розкрити те, що вже сказано,
перенести факт із назви в характеристики (у назві він теж лишається).

ХАРАКТЕРИСТИКИ. Наші наявні поля перенеси в `params` СЛОВО В СЛОВО — з тими
самими ключами й тими самими значеннями, нічого не перейменовуючи й не
перекладаючи. Нові поля за зразком конкурента додавай ПОРУЧ, лише якщо факт
для них уже є в нашій назві чи описі.

Поверни ЛИШЕ JSON без пояснень:
{{"name_ua": "...", "name_ru": "...", "description_ua": "...", "description_ru": "...", "params": {{...}}}}

Описи — звичайний текст або прості абзаци <p>. Українська й російська версії
мають бути перекладом одна одної, а не різними текстами."""


def parse_json(answer):
    """JSON із відповіді моделі: вона обгортає його в ```json і додає текст."""
    text = re.sub(r'^```(?:json)?|```$', '', (answer or '').strip(), flags=re.M)
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def improve(item, benchmarks, vendors, stats):
    prompt = build_prompt(item, benchmarks)
    source = ' '.join([item['name_ua'], item['name_ru'],
                       strip_html(item['description_ua']),
                       json.dumps(item['params'], ensure_ascii=False)])
    # у пулі за замовчуванням 300 токенів — на дві мови опису відповідь
    # обривалась посеред речення і не розбиралась як JSON
    answer, vendor, errors = vendor_pool.first_ok(vendors, prompt, stats=stats,
                                                  max_tokens=2500, timeout=240)
    if answer is None:
        return None, None, f'жоден вендор не відповів: {errors}'
    data = parse_json(answer)
    if not data:
        return None, vendor, 'відповідь не є JSON'
    result = ' '.join(str(data.get(k, '')) for k in
                      ('name_ua', 'name_ru', 'description_ua', 'description_ru'))
    bad = invented_numbers(source, result)
    if bad:
        return None, vendor, f'вигадані числа: {bad}'
    gone = lost_numbers(item['name_ua'], data.get('name_ua', ''))
    if gone:
        return None, vendor, f'з назви зникли числа: {gone}'

    # Правило власника: «гірше не можна». Тому картка приймається лише якщо
    # вона строго не гірша за нашу — і хоч у чомусь краща. Інакше лишається
    # наша: нічого не робити безпечніше, ніж погіршити.
    was = len(strip_html(item['description_ua']))
    now = len(strip_html(data.get('description_ua', '')))
    # допуск 2 %: переписаний текст природно відрізняється на кілька символів,
    # і відхиляти картку через різницю в один символ безглуздо
    if now < was * 0.98:
        return None, vendor, f'опис скоротився: {was} → {now} символів'
    was_p, now_p = item['params'], data.get('params') or {}
    if not set(was_p).issubset(now_p):
        return None, vendor, f'зникли характеристики: {sorted(set(was_p) - set(now_p))}'
    for k, v in was_p.items():
        if str(now_p[k]).strip().casefold() != str(v).strip().casefold():
            return None, vendor, f'змінено значення «{k}»: {v} → {now_p[k]}'
    if len(now_p) <= len(was_p) and now < was * 1.05:
        return None, vendor, 'без змін на краще'
    return data, vendor, 'ok'


def pick_refs(bench, item):
    """Еталони для категорії товару; якщо їх немає — з найбільшої зібраної."""
    refs = bench.get(item['category_id']) or bench.get(item['category_slug'])
    if refs:
        return refs, item['category_id']
    fallback = max(bench.items(), key=lambda kv: len(kv[1]), default=(None, []))
    return fallback[1], f'{fallback[0]} (запасний)'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=10)
    ap.add_argument('--all', action='store_true', help='усі картки, з продовженням')
    ap.add_argument('--vendors', default='gemini,groq,cerebras,openrouter,codex')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--bench', default=BENCH, help='файл еталонів конкурентів')
    args = ap.parse_args()

    items = json.load(open(ITEMS, encoding='utf-8'))
    bench = json.load(open(args.bench, encoding='utf-8')) if os.path.exists(args.bench) else {}
    if not bench:
        raise SystemExit(f'немає еталонів конкурентів: {args.bench}')

    # продовження після збою: вже зроблене не переробляємо
    done = json.load(open(OUT, encoding='utf-8')) if (args.all and os.path.exists(OUT)) else []
    have = {d['sku'] for d in done}
    queue = [i for i in items if i['sku'] not in have]
    if not args.all:
        queue = queue[:args.limit]

    vendors = args.vendors.split(',')
    stats = vendor_pool.Stats() if hasattr(vendor_pool, 'Stats') else None
    failed = []
    print(f'до обробки: {len(queue)} · уже готових: {len(done)}', flush=True)
    for n, item in enumerate(queue, 1):
        refs, src = pick_refs(bench, item)
        if not refs:
            failed.append((item['sku'], 'немає жодного еталона'))
            continue
        try:
            data, vendor, why = improve(item, refs[:3], vendors, stats)
        except Exception as exc:                       # мережа, ліміт, таймаут
            failed.append((item['sku'], f'{type(exc).__name__}: {exc}'))
            print(f'[збій] {item["sku"]}: {exc}', flush=True)
            continue
        if data:
            data['sku'] = item['sku']
            data['improved_by'] = vendor
            data['benchmark'] = src
            # «було» лишаємо поруч: мета прогону не лише фід, а й порівняння,
            # щоб зрозуміти, що саме дає приріст, а що ні
            data['before'] = {'name_ua': item['name_ua'],
                              'description_ua': item['description_ua'],
                              'params': item['params'],
                              'desc_len': len(strip_html(item['description_ua'])),
                              'params_n': len(item['params'])}
            data['after'] = {'desc_len': len(strip_html(data.get('description_ua', ''))),
                             'params_n': len(data.get('params') or {})}
            done.append(data)
            print(f'[{n}/{len(queue)}] ok {item["sku"]} ← {vendor}', flush=True)
        else:
            failed.append((item['sku'], why))
            print(f'[{n}/{len(queue)}] відхилено {item["sku"]}: {why}', flush=True)
        if not args.dry_run and n % 10 == 0:           # контрольна точка
            json.dump(done, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print(f'\nпокращено: {len(done)} · відхилено: {len(failed)}')
    for sku, why in failed[:20]:
        print('  ', sku, why)
    if not args.dry_run:
        json.dump(done, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        json.dump(failed, open(OUT.replace('.json', '_failed.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print('записано:', OUT)


if __name__ == '__main__':
    main()
