#!/usr/bin/env python3
"""Назви товарів TOPTUL, які у ГОТОВОМУ фіді лишились російськими.

Навіщо окремо від `toptul_translate_export.py`. Експортер віддає рядки,
яких немає в `toptul_translation`, і відбирає їх ШИРОКОЮ ознакою — станом на
25.08.2026 це 2688 назв, переважно вже українських («Набір оправок для
запресовування сальників G.I.KRAFT»). Перекладати їх усі означає витратити
роботу на рядки, які й так чисті, і при цьому НЕ полагодити ті, що вже мають
запис у таблиці, але запис поганий: 46 пар `title` мають російський `dst`
(«Трещотка реверсна», «Удлинитель 3/4"»).

Тут відбір іде з протилежного боку — від заміру, яким пункт черги
закривається. Береться `output/toptul_rozetka.xml`, СТРОГОЮ словниковою
ознакою відбираються офери з російською назвою, і для кожного дістається
СИРА назва постачальника: саме на неї генератор накладає словник
(`toptul_rozetka_generator.py:486`, переклад до `build_name()`).

Через це список рівно такий, як треба: те, що видно у фіді, і нічого понад.

Зв'язок сирої й побудованої назви — через `id` офера, а не через схожість
тексту: `build_name()` викидає бренд, артикул і пунктуацію, тож побудована
назва з сирою не збігається майже ніколи.

Вивід — TSV `kind<TAB>src<TAB>dst`, готовий до `toptul_translate_load.py`:
третя колонка вже заповнена (поточний переклад або сама сира назва), її й
треба виправити. Підсумок і російські слова кожної назви йдуть у stderr,
щоб не потрапити у файл.

    python3 tools/toptul_title_todo.py > /tmp/titles.tsv
    python3 tools/toptul_title_todo.py --show      # лише перелік, без TSV
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.append(os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2.extras  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402
import uk_lexicon as LEX  # noqa: E402
from toptul_ru_audit import strip_article, strip_vendor  # noqa: E402
from toptul_translate import FEED, title_tag  # noqa: E402
from toptul_translate_export import esc  # noqa: E402


def raw_titles() -> dict:
    """`id` офера → сира назва постачальника.

    Тег обирається тим самим `title_tag()`, що й у перекладачі, а не
    вгадується: у фіді TOPTUL є обидва теги, `name` російський у 5688
    оферах, `name_ua` — у 238, і взяти не той означало б зібрати словник,
    який генератор ніколи не знайде.
    """
    root = ET.parse(FEED).getroot()
    offers = root.find('shop').find('offers').findall('offer')
    tag = title_tag(offers)
    print(f'сирий фід {FEED}: {len(offers)} оферів, тег назви <{tag}>',
          file=sys.stderr)
    return {o.get('id'): (o.findtext(tag) or '').strip() for o in offers}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('feed', nargs='?',
                    default=os.path.join(BASE_DIR, 'output',
                                         'toptul_rozetka.xml'))
    ap.add_argument('--show', action='store_true',
                    help='друкувати перелік замість TSV')
    a = ap.parse_args()

    raw = raw_titles()
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT src, dst FROM toptul_translation WHERE kind='title'")
    tr = {r['src']: r['dst'] for r in cur.fetchall()}
    cur.close()
    conn.close()
    print(f'у таблиці перекладів назв: {len(tr)}', file=sys.stderr)

    root = ET.parse(a.feed).getroot()
    offers = list(root.iter('offer'))
    rows, no_raw, total = [], [], 0
    for o in offers:
        total += 1
        built = o.findtext('name_ua') or o.findtext('name') or ''
        clean = strip_article(built, (o.findtext('article') or '').strip())
        clean = strip_vendor(clean, (o.findtext('vendor') or '').strip())
        hits = LEX.ru_words(clean)
        if not hits:
            continue
        src = raw.get(o.get('id'))
        if not src:
            # Офер побудованого фіду без пари в сирому — це розбіжність
            # джерел, а не «нема чого перекладати». Мовчки пропустити її
            # означало б порахувати неповний список повним.
            no_raw.append((o.get('id'), built))
            continue
        rows.append((src, tr.get(src) or src, built, hits))

    print(f'{a.feed}: {total} оферів, з російською назвою {len(rows) + len(no_raw)}',
          file=sys.stderr)
    have = sum(1 for src, _, _, _ in rows if src in tr)
    print(f'   з них уже мають запис у таблиці (і він поганий): {have}',
          file=sys.stderr)
    print(f'   без запису: {len(rows) - have}', file=sys.stderr)
    if no_raw:
        print(f'   БЕЗ ПАРИ В СИРОМУ ФІДІ: {len(no_raw)}', file=sys.stderr)
        for oid, built in no_raw[:10]:
            print(f'      {oid}  {built[:70]}', file=sys.stderr)

    # Дедуп за сирою назвою: словник ключується нею, і два офери з однаковою
    # сирою назвою дали б два однакові рядки на переклад.
    seen = set()
    for src, dst, built, hits in sorted(rows, key=lambda r: r[0]):
        if src in seen:
            continue
        seen.add(src)
        if a.show:
            print(f'{" ".join(hits)}\n   сира: {src}\n   зараз: {dst}\n')
        else:
            print(f'title\t{esc(src)}\t{esc(dst)}')
    print(f'різних сирих назв на переклад: {len(seen)}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
