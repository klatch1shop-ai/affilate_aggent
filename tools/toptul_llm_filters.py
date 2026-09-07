#!/usr/bin/env python3
"""
tools/toptul_llm_filters.py
============================
Заповнення фільтрових характеристик «Тип» / «Вид» / «Особливості» для товарів
TOPTUL, які випадають із фіду Rozetka через «менше 3 характеристик».

ЧОМУ МОДЕЛЬ, А НЕ РЕГУЛЯРКА. Правило «за головним словом назви» закрило 241
значення й повернуло у фід 115 офферів. Решта 549 не піддаються шаблону:
«Ремонтний комплект для фарбопультів» треба віднести до «Ремкомплектів», а не
до «Комплектів для чищення», і жодне просте правило цього не робить.

ЩО ЦЕ **НЕ** Є. Модель нічого не вигадує: вона лише **обирає зі списку**
значень довідника Rozetka для цієї категорії. Далі значення все одно
проходить `_keep_known` у генераторі, тож у фід не потрапить нічого, чого
немає в довіднику. Правило 5 черги («не вигадувати значення») лишається
чинним — модель тут виконує роль класифікатора, а не автора.

Результат лягає в `data/toptul_llm_filters.json` **як дані**, а не в код: їх
видно, їх можна переглянути очима й виправити, і вони не ховаються всередині
логіки. Модель, яка їх дала, і дата теж записані.

    python3 tools/toptul_llm_filters.py --limit 20 --dry
    python3 tools/toptul_llm_filters.py
"""
import os, re, sys, csv, json, time, argparse, collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, 'tools'))
from nvidia_nim import ask, KEY   # noqa: E402

# Модель закріплена явно, а не через pick_model: 03.09.2026 із 82 моделей у
# переліку більшість повертає 404 або таймаут (перевірено llama-3.1-nemotron-70b,
# mistral-large-2, gemma-3-12b, phi-3.5-moe, mixtral-8x22b — усі непридатні).
# Ця відповідає за 3 секунди. max_tokens великий: nemotron спершу міркує вголос.
MODEL = 'nvidia/nemotron-3-super-120b-a12b'

DROPS = os.path.join(BASE, 'docs', 'toptul_drops_new.tsv')
REF = os.path.join(BASE, 'data', 'rozetka_filter_values.json')
OUT = os.path.join(BASE, 'data', 'toptul_llm_filters.json')
ATTRS = ('Тип', 'Вид', 'Особливості')
BATCH = 8           # товарів в одному запиті: менше запитів на тому ж ліміті
MAX_VALUES = 40     # довші довідники в підказку не вміщуються осмислено

PROMPT = """Ти — товарознавець інтернет-магазину інструментів.

Для кожного товару обери ОДНЕ значення характеристики «{attr}» зі списку
дозволених. Якщо з назви й характеристик неможливо визначити однозначно —
напиши «—». Вигадувати або писати значення поза списком заборонено.

Категорія: {cat}
Дозволені значення «{attr}»:
{values}

Товари:
{items}

Відповідь — рівно {n} рядків у форматі:
номер|значення

Без пояснень, без заголовків."""


def load_targets():
    ref = json.load(open(REF, encoding='utf-8'))
    rows = list(csv.DictReader(open(DROPS, encoding='utf-8'), delimiter='\t'))
    tasks = collections.defaultdict(list)          # (cat, rz, attr) → [row]
    for r in rows:
        rz = (r.get('rz_id') or '').strip()
        f = ref.get(rz) or {}
        have = {x.strip() for x in (r.get('характеристики') or '').split('|')}
        for a in ATTRS:
            slot = f.get(a)
            if not slot or a in have:
                continue
            vals = list(slot.get('values', {}))
            if not 2 <= len(vals) <= MAX_VALUES:
                continue
            tasks[(r.get('категорія'), rz, a)].append(r)
    return ref, tasks


def parse(reply, batch, allowed):
    """nemotron спершу міркує вголос, тому рядки «номер|значення» шукаємо по
    всьому тексту, а не лише на початку."""
    """Рядки «номер|значення» → {sku: значення}. Приймаємо лише те, що є в
    довіднику: відповідь моделі — пропозиція, а не істина."""
    out, bad = {}, 0
    for line in (reply or '').splitlines():
        m = re.match(r'\s*(\d+)\s*[|:.]\s*(.+?)\s*$', line)
        if not m:
            continue
        i = int(m.group(1)) - 1
        val = m.group(2).strip().strip('"«»')
        if not (0 <= i < len(batch)) or val in ('—', '-', ''):
            continue
        hit = next((a for a in allowed if a.lower() == val.lower()), None)
        if hit is None:
            bad += 1
            continue
        out[batch[i]['sku']] = hit
    return out, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='максимум запитів')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    if not KEY:
        print('NVIDIA_API_KEY порожній — нічого робити'); return

    model = MODEL
    print(f'модель: {model}')
    ref, tasks = load_targets()
    print(f'груп (категорія × характеристика): {len(tasks)}; '
          f'товарів у них: {sum(len(v) for v in tasks.values())}')

    store = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    store.setdefault('_meta', {})
    store['_meta'].update({'модель': model, 'оновлено': time.strftime('%Y-%m-%d %H:%M')})
    done = collections.Counter(); reqs = 0; rejected = 0

    for (cat, rz, attr), rows in sorted(tasks.items(), key=lambda x: -len(x[1])):
        allowed = list((ref[rz][attr].get('values') or {}))
        for i in range(0, len(rows), BATCH):
            if a.limit and reqs >= a.limit:
                break
            batch = rows[i:i + BATCH]
            items = '\n'.join(
                f"{j+1}. {r['назва']}   [характеристики: {r.get('характеристики','—')}]"
                for j, r in enumerate(batch))
            prompt = PROMPT.format(attr=attr, cat=cat, n=len(batch),
                                   values='\n'.join(f'- {v}' for v in allowed),
                                   items=items)
            if a.dry:
                print('─' * 70); print(prompt[:900]); reqs += 1; continue
            reply, dt = ask(model, prompt, max_tokens=3000)
            reqs += 1
            if reply.startswith('__HTTP_') or reply == '__EMPTY__':
                print(f'  [{cat}/{attr}] відмова: {reply[:80]}', file=sys.stderr)
                time.sleep(3); continue
            got, bad = parse(reply, batch, allowed)
            rejected += bad
            for sku, val in got.items():
                store.setdefault(sku, {})[attr] = val
                done[(cat, attr, val)] += 1
            time.sleep(1.6)              # 40 запитів/хв — тримаємось нижче
        if a.limit and reqs >= a.limit:
            break

    print(f'\nзапитів: {reqs} | значень отримано: {sum(done.values())} | '
          f'відхилено як поза довідником: {rejected}')
    for k, v in done.most_common(16):
        print(f'  {v:4}  {k[0]} → {k[1]} = {k[2]}')
    if not a.dry and sum(done.values()):
        json.dump(store, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\nзаписано: {OUT} ({len(store)-1} товарів)')


if __name__ == '__main__':
    main()
