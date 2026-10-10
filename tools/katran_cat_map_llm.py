#!/usr/bin/env python3
"""Зіставлення категорій KATRAN з офіційним каталогом Rozetka.

Навіщо: 06.10.2026 виміряно, що 3886 з 6427 наявних товарів (60,5 %) падали
в ЗАПАСНУ категорію «Ручний інструмент» — ноутбук опинявся серед ручного
інструменту. Такий фід Rozetka не пропустила б, а якби пропустила, товар
ніхто б не знайшов.

Чому не збігом слів: кандидати добираються збігом, але вибір робить модель.
Для «НЕ ОРИГИНАЛЬНЫЕ картриджи к ЛАЗЕРНЫМ принтерам» збіг слів однаково
пропонує і «Витратні матеріали для принтерів», і «Витратні матеріали» з
розділу автошин — бо слова ті самі, а зміст різний.

Чому не наосліп: модель отримує НЕ весь каталог на 4762 позиції, а 20
кандидатів. Інакше вона вигадує id, яких не існує, — перевіряємо кожен
повернутий rz_id по довіднику й відкидаємо вигадані.

Відповідь «немає відповідника» дозволена і бажана: краще лишити категорію
незіставленою, ніж покласти товар не туди. Такі товари у фід не йдуть.
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from dotenv import load_dotenv                                    # noqa: E402
load_dotenv(os.path.join(BASE, '.env'), override=True)
from shared.utils.llm_router import call_deepseek, DEEPSEEK_PRO   # noqa: E402

SYSTEM = """Ти товарознавець маркетплейсу. Твоє завдання — покласти категорію
постачальника в ПРАВИЛЬНУ категорію каталогу Rozetka.

Правила:
1. Обирай ЛИШЕ з наданого переліку кандидатів, за їхнім rz_id.
2. Якщо жоден кандидат не підходить за змістом — пиши rz_id: null.
   Це нормальна відповідь. Класти товар у приблизно схожу категорію
   ГІРШЕ, ніж не класти взагалі.
3. Дивись на ПОВНИЙ ШЛЯХ кандидата, а не на останнє слово. «Витратні
   матеріали» в розділі автошин і «Витратні матеріали для принтерів» —
   різні речі.
4. Орієнтуйся на приклади товарів: вони кажуть, що це насправді.
Відповідай ЛИШЕ JSON-масивом, без пояснень і без markdown."""


def ask(batch):
    lines = []
    for x in batch:
        cands = '\n'.join(f"      {c['rz']} = {c['path']}" for c in x['candidates'])
        lines.append(
            f"- id: {x['id']}\n"
            f"  категорія постачальника: {x['katran_path']}\n"
            f"  приклади товарів: {' | '.join(e[:70] for e in x['examples'])}\n"
            f"  кандидати:\n{cands}")
    prompt = ('Зістав кожну категорію постачальника з категорією Rozetka.\n\n'
              + '\n'.join(lines)
              + '\n\nФормат: [{"id":"<id>","rz_id":<число або null>,"чому":"<до 12 слів>"}]')
    txt, _, _ = call_deepseek(prompt, system=SYSTEM, model=DEEPSEEK_PRO,
                              effort='max', max_tokens=8000, timeout=600)
    txt = txt.strip()
    if txt.startswith('```'):
        txt = '\n'.join(l for l in txt.split('\n') if not l.strip().startswith('```'))
    return json.loads(txt)


def main(src, out, size=12, workers=4):
    need = json.load(open(src, encoding='utf-8'))
    need = [x for x in need if x.get('candidates')]
    valid = {int(k) for k in json.load(open('/tmp/rz_paths.json', encoding='utf-8'))}
    done = {}
    if os.path.exists(out):
        done = json.load(open(out, encoding='utf-8'))
    todo = [x for x in need if x['id'] not in done]
    print(f'до зіставлення: {len(todo)} (готово {len(done)})', flush=True)
    batches = [todo[i:i + size] for i in range(0, len(todo), size)]

    def run(b):
        for attempt in (1, 2):
            try:
                return b, ask(b)
            except Exception as exc:
                if attempt == 2:
                    print(f'  збій пачки: {type(exc).__name__}: {exc}', flush=True)
                    return b, []
                time.sleep(3)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for b, res in ex.map(run, batches):
            for r in res:
                rz = r.get('rz_id')
                # Вигадані id відкидаємо: модель інколи повертає правдоподібне
                # число, якого в каталозі немає.
                if rz is not None and int(rz) not in valid:
                    r['чому'] = f'ВІДКИНУТО: rz_id {rz} немає в каталозі'
                    rz = None
                done[str(r.get('id'))] = {'rz_id': rz, 'чому': r.get('чому', '')}
            json.dump(done, open(out, 'w'), ensure_ascii=False, indent=1)
            print(f'  зроблено {len(done)} з {len(need)}', flush=True)
    ok = sum(1 for v in done.values() if v['rz_id'])
    print(f'\nзіставлено {ok}, без відповідника {len(done) - ok}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/katran_map_task.json',
         sys.argv[2] if len(sys.argv) > 2 else '/tmp/katran_map_done.json')
