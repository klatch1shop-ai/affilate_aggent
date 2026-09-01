"""
tools/epicentr_mapping_apply.py
================================
Вносить у БД дві правки, виведені з рішень категорійного менеджера Єпіцентру:

  1. 13 категорій, яких немає в `epicentr_intimate_categories` (гілки
     «Краса та здоров'я», «Побутова техніка», «Спортивні товари»).
     Без них товар нікуди подіти: валідатор відкидає код, якого немає
     в таблиці, тому частина карток мапилась хибно **структурно**.
  2. 21 виправлення `epicentr_category_mapping` (docs/epicentr_mapping_fixes.json).

Джерела істини:
  data/epicentr_products.json        — що менеджер реально призначив карткам
  data/epicentr_categories_live.json — дерево з GET /v2/pim/categories
  docs/epicentr_mapping_fixes.json   — вивід tools/epicentr_mapping_review.py

За замовчуванням — сухий прогін. Запис лише з `--apply`.

Перевірки перед записом (кожна ловила б реальну помилку):
  * перелік відсутніх категорій **рахується з даних**, а не переписується з
    документа — інакше правка робилась би за списком, що застарів;
  * цільовий код мусить існувати в живому дереві й бути **листком**:
    Єпіцентр не приймає товар у вузол із дітьми;
  * поточне значення в БД мусить збігатися з `ours` у файлі правок —
    якщо мапінг уже змінили, наосліп перезаписувати не можна;
  * після запису — повторне читання з БД і звіт по кожному рядку.
"""
import os, sys, json, argparse, collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.db import get_connection

PRODUCTS = os.path.join(BASE, 'data', 'epicentr_products.json')
LIVE     = os.path.join(BASE, 'data', 'epicentr_categories_live.json')
FIXES    = os.path.join(BASE, 'docs', 'epicentr_mapping_fixes.json')
BAK      = 'epicentr_category_mapping_bak_20260823'

# Картки NOIRE завантажені одним імпортом у липні 2026; інші місяці — Carvol/TOPTUL.
NOIRE_MONTH = '2026-07'


def load_live():
    live = json.load(open(LIVE, encoding='utf-8'))

    def title(code, lang='ua'):
        it = live.get(code)
        if not it:
            return None
        for t in it.get('translations', []):
            if t['languageCode'] == lang:
                return t['title']
        return None

    def path(code):
        parts, seen = [], set()
        while code and code in live and code not in seen:
            seen.add(code)
            parts.append(title(code) or code)
            code = str(live[code].get('parentCode') or '')
        return ' › '.join(reversed(parts))

    return live, title, path


def manager_categories():
    """attributeSetCode → кількість карток NOIRE у кабінеті."""
    prods = [x for x in json.load(open(PRODUCTS, encoding='utf-8'))
             if (x.get('createdAt') or '')[:7] == NOIRE_MONTH]
    return collections.Counter(str(p.get('attributeSetCode')) for p in prods), len(prods)


def revert():
    """Повертає epicentr_category_mapping до стану з резервної копії.

    Потрібне тому, що `epicentr_category_mapping` читає не лише генератор
    Єпіцентру, а й `tools/noire_prom_generator.py`, а `noire_stock_sync.py
    --publish-prom` за crontab (40 7,11,15,19) **перезбирає фід Prom із БД і
    пушить його в GitHub**. Тобто правка мапінгу — це зміна опублікованого
    фіду Prom, а вона потребує слова власника.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT to_regclass(%s) t', (f'public.{BAK}',))
    if cur.fetchone()['t'] is None:
        print(f'резервної копії {BAK} немає — відкочувати нічого')
        return 1
    cur.execute(f'SELECT * FROM {BAK}')
    bak = cur.fetchall()
    cur.execute('''UPDATE epicentr_category_mapping m
                   SET epicentr_category_code = b.epicentr_category_code,
                       attribute_set_code     = b.attribute_set_code,
                       confidence             = b.confidence,
                       verified               = b.verified,
                       reasoning              = b.reasoning
                   FROM ''' + BAK + ''' b
                   WHERE m.sexopt_category_id = b.sexopt_category_id''')
    conn.commit()
    cur.execute('SELECT sexopt_category_id, epicentr_category_code '
                'FROM epicentr_category_mapping WHERE sexopt_category_id = ANY(%s)',
                ([r['sexopt_category_id'] for r in bak],))
    now = {r['sexopt_category_id']: r['epicentr_category_code'] for r in cur.fetchall()}
    bad = [r['sexopt_category_id'] for r in bak
           if now.get(r['sexopt_category_id']) != r['epicentr_category_code']]
    print(f'відкочено рядків: {len(bak) - len(bad)}/{len(bak)}')
    if bad:
        print(f'НЕ ВІДКОЧЕНО: {bad}')
    cur.close(); conn.close()
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='записати в БД')
    ap.add_argument('--revert', action='store_true',
                    help=f'повернути мапінг зі щита {BAK} (категорії лишаються)')
    args = ap.parse_args()

    if args.revert:
        return revert()

    live, title, path = load_live()
    used, ncards = manager_categories()
    print(f'карток NOIRE у кабінеті: {ncards} | категорій у менеджера: {len(used)}')
    print(f'дерево Єпіцентру: {len(live)} категорій')

    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT code FROM epicentr_intimate_categories')
    have = {r['code'] for r in cur.fetchall()}
    print(f'epicentr_intimate_categories: {len(have)} записів')

    # ── 1. відсутні категорії ────────────────────────────────────────────────
    missing = sorted((c for c in used if c not in have), key=lambda c: -used[c])
    print(f'\n── Крок 1: категорій менеджера, яких немає в таблиці: {len(missing)}')
    rows, skipped = [], []
    for c in missing:
        it = live.get(c)
        if it is None:
            skipped.append((c, 'немає в живому дереві'))
            continue
        if it.get('hasChild'):
            skipped.append((c, 'вузол із дітьми — Єпіцентр не приймає товар у такий'))
            continue
        atsets = [a['code'] for a in it.get('attributeSets', [])]
        rows.append((c, str(it.get('parentCode') or '') or None,
                     title(c), (atsets[0] if atsets else c), False))
        print(f'  {c:>6} {used[c]:>4} карток  atset={atsets}  {path(c)}')
    for c, why in skipped:
        print(f'  ПРОПУЩЕНО {c}: {why}')

    # ── 2. правки мапінгу ────────────────────────────────────────────────────
    fixes = json.load(open(FIXES, encoding='utf-8'))
    ids = [f['sexopt_category_id'] for f in fixes]
    cur.execute('SELECT sexopt_category_id, epicentr_category_code, attribute_set_code '
                'FROM epicentr_category_mapping WHERE sexopt_category_id = ANY(%s)', (ids,))
    cur_map = {r['sexopt_category_id']: r for r in cur.fetchall()}

    will_have = have | {r[0] for r in rows}
    print(f'\n── Крок 2: правок мапінгу у файлі: {len(fixes)}')
    todo, refused = [], []
    for f in fixes:
        cid = f['sexopt_category_id']
        src, dst = f['ours']['code'], f['manager']['code']
        r = cur_map.get(cid)
        if r is None:
            refused.append((cid, 'немає рядка в epicentr_category_mapping'))
        elif r['epicentr_category_code'] == dst:
            print(f'  {cid:>5} вже {dst} — пропуск (ідемпотентність)')
        elif r['epicentr_category_code'] != src:
            refused.append((cid, f"у БД {r['epicentr_category_code']}, "
                                 f"у файлі очікувалось {src} — мапінг змінили після звірки"))
        elif dst not in will_have:
            refused.append((cid, f'цільовий код {dst} відсутній у таблиці категорій'))
        elif dst in live and live[dst].get('hasChild'):
            refused.append((cid, f'цільовий код {dst} — вузол із дітьми'))
        else:
            todo.append((cid, src, dst, f))
            print(f"  {cid:>5} {f['cards']:>4} карток  {src} {f['ours']['name'][:28]:30}"
                  f" → {dst} {f['manager']['name']}")
    for cid, why in refused:
        print(f'  ВІДМОВА {cid}: {why}')

    if not args.apply:
        print(f'\nсухий прогін: додати {len(rows)} категорій, змінити {len(todo)} мапінгів.'
              f'\nзапис — з --apply')
        cur.close(); conn.close()
        return 0 if not refused else 1

    # ── запис ────────────────────────────────────────────────────────────────
    cur.execute(f'CREATE TABLE IF NOT EXISTS {BAK} AS '
                'SELECT * FROM epicentr_category_mapping WHERE false')
    cur.execute(f'DELETE FROM {BAK} WHERE sexopt_category_id = ANY(%s)', (ids,))
    cur.execute(f'INSERT INTO {BAK} SELECT * FROM epicentr_category_mapping '
                'WHERE sexopt_category_id = ANY(%s)', (ids,))
    print(f'\nрезервна копія {len(ids)} рядків → {BAK}')

    for code, parent, name, atset, haschild in rows:
        cur.execute('''INSERT INTO epicentr_intimate_categories
                       (code, parent_code, name_ua, attribute_set_code, has_child)
                       VALUES (%s,%s,%s,%s,%s) ON CONFLICT (code) DO NOTHING''',
                    (code, parent, name, atset, haschild))
    for cid, src, dst, f in todo:
        cur.execute('''UPDATE epicentr_category_mapping
                       SET epicentr_category_code = %s,
                           attribute_set_code     = %s,
                           confidence             = 1.0,
                           verified               = TRUE,
                           reasoning              = %s
                       WHERE sexopt_category_id = %s''',
                    (dst, dst,
                     f"рішення категорійного менеджера Єпіцентру: {f['cards']} карток, "
                     f"згода {f['agreement']*100:.0f}%; було {src} ({f['ours']['name']}) "
                     f"[epicentr_mapping_apply 23.08.2026]",
                     cid))
    conn.commit()

    # ── перевірка після запису ───────────────────────────────────────────────
    cur.execute('SELECT count(*) c FROM epicentr_intimate_categories')
    print(f"epicentr_intimate_categories: {len(have)} → {cur.fetchone()['c']}")
    cur.execute('SELECT sexopt_category_id, epicentr_category_code '
                'FROM epicentr_category_mapping WHERE sexopt_category_id = ANY(%s)', (ids,))
    after = {r['sexopt_category_id']: r['epicentr_category_code'] for r in cur.fetchall()}
    wrong = [f['sexopt_category_id'] for f in fixes
             if after.get(f['sexopt_category_id']) != f['manager']['code']]
    print(f'мапінгів звірено після запису: {len(fixes) - len(wrong)}/{len(fixes)}')
    if wrong:
        print(f'НЕ ЗАСТОСОВАНО: {wrong}')

    cur.close(); conn.close()
    return 1 if (wrong or refused) else 0


if __name__ == '__main__':
    sys.exit(main())
