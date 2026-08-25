#!/usr/bin/env python3
"""
tools/toptul_param_rename_check.py
==================================
Звіряє ЗАПРОПОНОВАНІ перейменування характеристик TOPTUL з офіційним
переліком характеристик Rozetka (кеш `data/rozetka_category_options.json`,
збирає `tools/rozetka_category_options.py`).

Навіщо окремий інструмент. Пункт черги «виправити хибні переклади» називає
пари на кшталт «Тип відвертки» → «Тип викрутки». Взяти їх на віру не можна:
перелік складено НЕЧІТКИМ зіставленням, і той самий прогін дав завідомо хибні
пари («Кількість граней» ← «Кількість предметів»). Тому кожна пара має бути
підтверджена фактом, а не схожістю: цільова назва мусить існувати серед
характеристик Rozetka САМЕ В ТИХ категоріях, де лежать наші оффери з
поточною назвою.

Друкує по кожній парі:
  * скільки офферів фіду несуть поточну назву і в скількох категоріях;
  * у скількох із цих категорій Rozetka знає ЦІЛЬОВУ назву (і чи вона фільтр);
  * у скількох Rozetka знає ПОТОЧНУ назву — якщо знає, перейменування зайве
    або й шкідливе.

Код виходу 1, якщо хоч одна пара не підтверджена (ціль не знайдена в жодній
категорії або поточна назва теж законна) — щоб «усе гаразд» не можна було
прочитати з мовчання.

    python3 tools/toptul_param_rename_check.py --feed output/toptul_rozetka.xml
"""
import os, sys, json, argparse, collections
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, 'data', 'rozetka_category_options.json')

# Пари з постановки задачі 25.08. Кожна перевіряється, жодна не застосовується
# цим скриптом — він лише міряє.
PAIRS = [
    ('Тип відвертки', 'Тип викрутки'),
    ('Тип бити', 'Тип біти'),
    ('Діаметр сопла', 'Діаметр форсунки'),
    ('Вид резьби', 'Вид різі'),
    ('Крок резьби', 'Крок різі'),
    ('Кількість відділень/карманів', 'Кількість відділень/кишень'),
    ('Довжина, мм', 'Довжина'),
]

# Пари, які той самий нечіткий прогін видав ПОМИЛКОВО. Тримаються тут не для
# застосування, а як негативний контроль: перевірка мусить відрізняти їх від
# справжніх, інакше вона нічого не доводить.
FALSE_PAIRS = [
    ('Кількість граней', 'Кількість предметів'),
    ('Матеріал головки', 'Матеріал рукоятки'),
]


def load_cache():
    if not os.path.exists(CACHE):
        sys.exit(f'немає {CACHE} — спершу tools/rozetka_category_options.py')
    return json.load(open(CACHE, encoding='utf-8'))


def cat_names(cache, rz_id):
    """назва характеристики -> (is_filter, unit) для категорії Rozetka"""
    items = cache.get(str(rz_id))
    if items is None:
        return None
    if isinstance(items, dict):
        items = items.get('options') or items.get('items') or []
    out = {}
    for x in items:
        if not isinstance(x, dict):
            continue
        nm = str(x.get('name') or '').strip()
        if not nm:
            continue
        is_f = str(x.get('filter_type') or '').lower() not in ('disable', 'none', '')
        unit = (x.get('unit') or '') or ''
        prev = out.get(nm)
        out[nm] = (is_f or (prev[0] if prev else False), unit or (prev[1] if prev else ''))
    return out


def feed_usage(feed):
    """(офферів на назву, назва -> Counter(rz_id -> офферів), rz_id категорій)

    Рахується саме за ОФФЕРАМИ, а не за тегами: повторювані `<param>` з тим
    самим іменем генератор зводить в один, тож теги дали б завищене число.
    """
    root = ET.parse(feed).getroot()
    rz = {}
    for c in root.findall('.//categories/category'):
        if c.get('id') and c.get('rz_id'):
            rz[c.get('id')] = (c.get('rz_id'), (c.text or '').strip())
    where = collections.defaultdict(collections.Counter)
    total = collections.Counter()
    for o in root.findall('.//offer'):
        rz_id = rz.get((o.findtext('categoryId') or '').strip(), (None, ''))[0]
        for nm in {(p.get('name') or '').strip() for p in o.findall('param')}:
            if not nm:
                continue
            total[nm] += 1
            if rz_id:
                where[nm][rz_id] += 1
    return total, where, rz


def suggest(total, where, cache, limit=40):
    """Наші назви, яких Rozetka не знає, поруч із її ПОХОЖОЮ назвою.

    Це той самий нечіткий підбір, що дав хибні пари, тому нічого не
    застосовує й нічим не є, крім матеріалу на перевірку людиною. Різниця з
    тим прогоном одна, але суттєва: кандидат береться лише з тих категорій,
    де реально лежать наші оффери, і лише якщо нашої назви Rozetka не знає.
    """
    import difflib
    rows = []
    for nm, n in total.most_common():
        cand = collections.Counter()
        known = 0
        for rz_id, cnt in where[nm].items():
            names = cat_names(cache, rz_id)
            if names is None:
                continue
            if nm in names:
                known += cnt
                continue
            for m in difflib.get_close_matches(nm, list(names), n=1, cutoff=0.82):
                if m != nm and names[m][0]:
                    cand[m] += cnt
        if known or not cand:
            continue
        top, w = cand.most_common(1)[0]
        rows.append((w, nm, top, n))
    rows.sort(reverse=True)
    print('\n=== кандидати на перевірку (НЕ застосовувати без звірки) ===')
    print(f'{"офф.":>6}  наша назва → похожа назва-ФІЛЬТР Rozetka')
    for w, nm, top, n in rows[:limit]:
        print(f'{w:6}  {nm!r} → {top!r}   (усього у фіді {n})')
    print(f'усього кандидатів: {len(rows)}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--feed', default=os.path.join(BASE, 'output', 'toptul_rozetka.xml'))
    ap.add_argument('--suggest', action='store_true',
                    help='додатково: пошук інших схожих назв (лише перелік)')
    a = ap.parse_args()

    cache = load_cache()
    total, where, rz = feed_usage(a.feed)
    print(f'фід: {sum(1 for _ in ET.parse(a.feed).getroot().iter("offer"))} офферів, '
          f'{len(rz)} категорій з rz_id, кеш Rozetka: {len(cache)} категорій\n')

    def check(old, new):
        offers = total[old]
        cats = where[old]
        ok_cats = bad_cats = nocache = 0
        ok_off = bad_off = 0
        units = collections.Counter()
        filt = 0
        for rz_id, n in cats.items():
            names = cat_names(cache, rz_id)
            if names is None:
                nocache += 1
                continue
            if new in names:
                ok_cats += 1
                ok_off += n
                if names[new][0]:
                    filt += 1
                units[names[new][1]] += 1
            if old in names:
                bad_cats += 1
                bad_off += n
        u = ', '.join(f'{k or "—"}×{v}' for k, v in units.most_common(3))
        print(f'  {old!r} → {new!r}')
        print(f'      офферів у фіді: {offers}, категорій: {len(cats)}'
              + (f' (без кешу: {nocache})' if nocache else ''))
        print(f'      Rozetka знає ЦІЛЬ  у {ok_cats}/{len(cats)} кат. '
              f'({ok_off} офф.), з них фільтр у {filt}; одиниця: {u or "—"}')
        print(f'      Rozetka знає ПОТОЧНУ у {bad_cats}/{len(cats)} кат. ({bad_off} офф.)')
        verdict = 'ПІДТВЕРДЖЕНО' if (ok_cats and not bad_cats) else (
            'НЕ ПІДТВЕРДЖЕНО: ціль невідома Rozetka' if not ok_cats else
            'СПІРНО: Rozetka знає й поточну назву')
        if offers == 0:
            verdict = 'НЕМАЄ У ФІДІ'
        print(f'      → {verdict}\n')
        return verdict

    print('=== пари з постановки ===')
    good = [check(o, n) for o, n in PAIRS]
    print('=== негативний контроль: пари, які нечітке зіставлення дало ХИБНО ===')
    bad = [check(o, n) for o, n in FALSE_PAIRS]

    conf = sum(1 for v in good if v == 'ПІДТВЕРДЖЕНО')
    print(f'підтверджено {conf} з {len(PAIRS)} пар постановки')
    # Негативний контроль має сенс лише тоді, коли хибні пари ВІДРІЗНЯЮТЬСЯ від
    # справжніх. Якщо перевірка підтверджує і їх — вона підтверджує будь-що.
    bad_conf = [f'{o} → {n}' for (o, n), v in zip(FALSE_PAIRS, bad) if v == 'ПІДТВЕРДЖЕНО']
    if bad_conf:
        print('УВАГА: перевірка підтвердила завідомо хибні пари: ' + '; '.join(bad_conf))
        return 1
    print('негативний контроль: жодна хибна пара не підтверджена')
    if a.suggest:
        suggest(total, where, cache)
    return 0 if conf == len(PAIRS) else 1


if __name__ == '__main__':
    sys.exit(main())
