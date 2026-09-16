#!/usr/bin/env python3
"""Замір каналів LLM на справжній задачі: опис товару з назви й характеристик.

Навіщо. «Схоже, що краще» — не результат. Порівнюємо канали
(`shared/utils/llm_router.py`) на тих самих товарах і рахуємо те, що нас
реально ріже на модерації:

  * **вигадані числа** — цифра з одиницею виміру, якої немає у вхідних даних.
    Це головна вада Ollama (пам'ять `ollama-ukrainian-models`) і причина
    правила «LLM не джерело фактів про товар» (SKILL-23);
  * **чужомовні вкраплення** — латиниця всередині кириличного слова
    («Гель-lubрикант») і російські маркери;
  * час відповіді й довжина.

Оцінює не «красу тексту», а дефекти, які можна порахувати.

    venv/bin/python tools/llm_channel_bench.py --n 10
    venv/bin/python tools/llm_channel_bench.py --n 10 --channels omniroute,ollama
"""
import argparse
import os
import re
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from shared.utils.llm_router import ask  # noqa: E402

PROMPT = ("Ти товарознавець інтернет-магазину. Напиши українською 2 речення опису товару "
          "СУВОРО за наведеними даними. Заборонено додавати будь-які числа, розміри, склад "
          "чи властивості, яких немає у даних.\n\nНазва: {name}\nХарактеристики: {params}\n\nОпис:")

NUM_UNIT = re.compile(r'(\d+(?:[.,]\d+)?)\s*(мм|см|м|мл|л|г|кг|шт|°|%|год|хв)', re.I)
MIXED = re.compile(r'[а-яіїєґА-ЯІЇЄҐ][a-zA-Z]|[a-zA-Z][а-яіїєґА-ЯІЇЄҐ]')
RU = re.compile(r'\b(это|или|для\s+того|очень|используется|который|его|можно\s+использовать)\b', re.I)


def _plain(html):
    return ' '.join(re.sub(r'<[^>]+>', ' ', html or '').split())


def facts(text):
    """Числа з одиницями — множина «фактів», які можна звірити."""
    return {(n.replace(',', '.'), u.lower()) for n, u in NUM_UNIT.findall(text or '')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=10)
    ap.add_argument('--channels', default='omniroute,ollama')
    ap.add_argument('--seed', type=int, default=20260916)
    a = ap.parse_args()

    from shared.utils.db import get_connection
    cur = get_connection().cursor()
    # характеристик окремим полем у постачальника немає — вхідні дані це назва
    # плюс його опис; саме з них генератор і робить наш текст
    cur.execute("""select sku, name, vendor, country, description_html from sexopt_products
                   where available = true and length(name) > 25
                     and coalesce(description_html,'') <> ''
                   order by md5(sku || %s) limit %s""", (str(a.seed), a.n))
    rows = cur.fetchall()
    print(f'товарів: {len(rows)}')

    res = {}
    for ch in a.channels.split(','):
        rec = {'ms': [], 'invented': 0, 'mixed': 0, 'ru': 0, 'fail': 0, 'len': [], 'items': []}
        for r in rows:
            src = f"{r['name']} {r['vendor'] or ''} {r['country'] or ''} {_plain(r['description_html'])}"
            try:
                out = ask(PROMPT.format(name=r['name'],
                                        params=f"бренд {r['vendor'] or '—'}, країна {r['country'] or '—'}. "
                                               f"{_plain(r['description_html'])[:500]}"),
                          task='text', chain=[ch], timeout=120, min_len=40)
            except Exception as e:
                rec['fail'] += 1
                rec['items'].append((r['sku'], f'ЗБІЙ {type(e).__name__}'))
                continue
            t = out['text']
            new = facts(t) - facts(src)
            rec['ms'].append(out['ms'])
            rec['len'].append(len(t))
            rec['invented'] += bool(new)
            rec['mixed'] += bool(MIXED.search(t))
            rec['ru'] += bool(RU.search(t))
            rec['items'].append((r['sku'], ('вигадано ' + str(sorted(new))) if new else 'ok'))
        res[ch] = rec

    print(f"\n{'канал':12} {'відповіли':>9} {'збої':>5} {'вигадані числа':>15} "
          f"{'мішанина мов':>13} {'рос.':>5} {'медіана мс':>11} {'символів':>9}")
    for ch, r in res.items():
        n = len(r['ms'])
        print(f"{ch:12} {n:>9} {r['fail']:>5} {r['invented']:>15} {r['mixed']:>13} {r['ru']:>5} "
              f"{statistics.median(r['ms']) if r['ms'] else 0:>11.0f} "
              f"{statistics.median(r['len']) if r['len'] else 0:>9.0f}")
    for ch, r in res.items():
        bad = [x for x in r['items'] if x[1] != 'ok']
        if bad:
            print(f'\n{ch} — проблемні: ' + '; '.join(f'{s}: {v}' for s, v in bad[:6]))


if __name__ == '__main__':
    main()
