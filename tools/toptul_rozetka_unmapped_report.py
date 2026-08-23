#!/usr/bin/env python3
"""Перелік категорій TOPTUL без відповідника в Rozetka — на рішення власника.

Пункт черги вимагає довести фід до кінця, але частину категорій закрити не
можна власним рішенням: у Rozetka просто немає такого вузла, або категорія
TOPTUL змішана й лягає в кілька різних. Записати «щось близьке» гірше, ніж
лишити порожнім (SKILL-04), тож ці категорії йдуть власникові списком.

Друкує НЕ назви категорій, а назви ТОВАРІВ у кожній: рішення ухвалюється по
тому, що там лежить насправді. «Инструменты для ремонта шин» і «Ключи
серповидные» за назвою здаються різними задачами, а за вмістом — очевидні
обидві; «Система охлаждения» навпаки, за назвою проста, а всередині наполовину
тестери, наполовину знімачі.

    python3 tools/toptul_rozetka_unmapped_report.py > docs/toptul_rozetka_unmapped.md
"""
import collections
import os
import sys
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2.extras  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402

FEED = os.getenv('TOPTUL_FEED_FILE', '/tmp/toptul.xml')
HEAD = """# Категорії TOPTUL без відповідника в Rozetka — на рішення власника

Станом на {date}: **{n} категорій, {g} товарів** (до розбору 23.08.2026 —
96 категорій / 602 товари).

Перевірено по ОФІЦІЙНОМУ каталогу Rozetka — `docs/rozetka_categories_all.json`,
4762 категорії з `market-categories/search`, а не по дереву конкурента `ttul`
на 289 позицій. Тобто «відповідника немає» тут означає, що його немає в
самому майданчику, а не в чужому асортименті. Перевірено пошуком по основах:
«піскостр», «екстрактор», «розвальц», «дозиметр», «твердомір», «тахометр»,
«вакуумметр», «нутромір», «присоск», «цвяхотяг» — жодного влучення у 4762
категоріях.

Чому не записано «щось близьке»: за SKILL-04 хибна категорія гірша за
порожню — товар лягає туди, де його не шукають, і фільтри до нього не
застосовуються. Саме тому відхилені й попередні здогадки рівня `review`:
«Інструмент для пайки → Набори інструментів», «Тестери герметичності →
Тестери кабельні», «Шуруповерт акумуляторний → Біти для шуруповерта».

Три різні причини, і рішення в них теж різні:

* **немає такої категорії** — Rozetka не має вузла під цей вид товару.
  Варіант: не продавати або просити майданчик завести категорію;
* **категорія змішана** — усередині товари, що лягають у РІЗНІ категорії
  Rozetka. Варіант: розбити її на дві-три й змапити кожну окремо;
* **не наш профіль** — товар не роздрібний (виставкові стенди, промислові
  верстати, обладнання СТО за десятки тисяч).
"""


def main():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT toptul_id, toptul_name, goods, tier, rz_name
                     FROM toptul_rozetka_category_map
                    WHERE tier IN ('none','review')
                    ORDER BY goods DESC NULLS LAST""")
    todo = {r['toptul_id']: r for r in cur.fetchall()}

    root = ET.parse(FEED).getroot()
    byc = collections.defaultdict(list)
    for o in root.find('shop').find('offers').findall('offer'):
        cid = (o.findtext('categoryId') or '').strip()
        if cid in todo:
            byc[cid].append((o.findtext('name_ua') or o.findtext('name') or '').strip())

    from datetime import datetime
    print(HEAD.format(date=datetime.now().strftime('%d.%m.%Y'), n=len(todo),
                      g=sum(r['goods'] or 0 for r in todo.values())))
    for cid, r in todo.items():
        # Відхилена здогадка друкується навмисно: без неї власник знову
        # запропонує те саме, вже один раз відкинуте.
        sug = (f" · відхилена здогадка: «{r['rz_name']}»"
               if r['tier'] == 'review' and r['rz_name'] else '')
        print(f"\n### {r['toptul_name']} — {r['goods'] or 0} товарів\n")
        print(f"`{cid}`{sug}\n")
        for n in byc.get(cid, [])[:5]:
            print(f'* {n[:100]}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
