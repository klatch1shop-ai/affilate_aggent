#!/usr/bin/env python3
"""Завантаження словника перекладів TOPTUL у `toptul_translation`.

Пара до `toptul_translate_export.py`. Навіщо: `toptul_translate.py` ходить у
NVIDIA, але ключа `NVIDIA_API_KEY` на сервері немає — 22.08.2026 прогін дав
41 відповідь HTTP 401 поспіль і жодного запису, причому скрипт при цьому не
падає, а тихо йде далі партіями. Експорт → переклад → завантаження дає той
самий результат і той самий захист від зсуву: кожен рядок несе свій
оригінал, зіставлення за ним, а не за позицією.

Формат входу — TSV `kind<TAB>src<TAB>dst`, `\\n` і `\\t` екрановані.

ТРИ ПЕРЕВІРКИ, без яких завантаження не рахується (правило позитивного
контролю). Кожна відповідає на питання «а перевірка взагалі здатна щось
знайти»:

1. **`src` мусить бути у фіді.** Рядок, якого в `/tmp/toptul.xml` немає, —
   це друкарська помилка в словнику, і мовчки прийнятий він дав би запис,
   що ніколи не спрацює. Такі рядки НЕ пишуться, а перелічуються.
2. **`dst` не мусить впізнаватись строгою `RU`.** «Переклад», який лишився
   російським, — найгірший результат: таблиця виглядає повною, а фід ні.
   Такі пари теж відхиляються поіменно.
3. **Звіт про залишок.** Наприкінці друкується, скільки рядків фіду досі
   без перекладу — щоб «завантажено 594» не читалось як «готово».

    python3 tools/toptul_translate_load.py docs/toptul_translation_22.tsv
    python3 tools/toptul_translate_load.py <файл> --dry
"""
import argparse
import collections
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.append(os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
import psycopg2.extras  # noqa: E402
from loguru import logger  # noqa: E402
from shared.utils.db import get_connection  # noqa: E402
# Ознака мови ІМПОРТУЄТЬСЯ, а не пишеться вдруге: два власні визначення
# «російського» розійшлись би, і перевірка міряла б не те, що виправляють.
from toptul_translate import KINDS, collect  # noqa: E402
from uk_lexicon import ru_words, unknown_words  # noqa: E402


def unesc(s: str) -> str:
    """Зворотне до `esc()` в експортері. Посимвольно, бо послідовні
    `.replace()` на `\\\\n` дали б перенос там, де його не було."""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == 'n':
                out.append('\n'); i += 2; continue
            if nxt == 't':
                out.append('\t'); i += 2; continue
            if nxt == '\\':
                out.append('\\'); i += 2; continue
        out.append(c)
        i += 1
    return ''.join(out)


_CODE = re.compile(r'[A-ZА-ЯІЇЄҐЫЭЪЁ][A-ZА-ЯІЇЄҐЫЭЪЁ0-9./-]{2,}')


def carried_codes(src: str, dst: str) -> set:
    """Слова, які НЕ можна вважати доказом неперекладеного тексту.

    Артикули й моделі перекладати заборонено («бренди, моделі, артикули НЕ
    перекладай»), а серед артикулів TOPTUL трапляються кириличні: `ЭКСТРХ`,
    `РАЗВ9.00`, `КС53-Б`. Літера `Э` в артикулі робила ПРАВИЛЬНИЙ переклад
    «Набір екстракторів для зламаних болтів (4 шт.) (Харків) ЭКСТРХ»
    відхиленим як «російський» — тобто перевірка вимагала зробити те, що
    робити не дозволено, і пара не записувалась узагалі, лишаючи російським
    ВЕСЬ рядок.

    Умова навмисно вузька: слово мусить бути ВЕЛИКИМИ літерами і стояти
    незмінним в оригіналі. Звичайне російське слово в перекладі під неї не
    підпадає — воно або перекладене, або написане не капслоком.
    """
    return {w.lower() for w in _CODE.findall(dst)} & \
           {w.lower() for w in _CODE.findall(src)}


def read_tsv(path: str) -> list:
    rows, seen = [], set()
    with open(path, encoding='utf-8') as f:
        for ln, line in enumerate(f, 1):
            line = line.rstrip('\n')
            if not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) != 3:
                logger.error(f'рядок {ln}: колонок {len(parts)}, а треба 3')
                continue
            kind, src, dst = parts[0].strip(), unesc(parts[1]), unesc(parts[2])
            if kind not in KINDS:
                logger.error(f'рядок {ln}: невідомий kind {kind!r}')
                continue
            if not src or not dst:
                logger.error(f'рядок {ln}: порожній src або dst')
                continue
            if (kind, src) in seen:
                logger.warning(f'рядок {ln}: повтор {kind} {src[:50]!r}')
                continue
            seen.add((kind, src))
            rows.append((kind, src, dst))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tsv')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    rows = read_tsv(a.tsv)
    logger.info(f'у файлі пар: {len(rows)}')

    feed = {k: collect(k) for k in KINDS}
    for k, c in feed.items():
        logger.info(f'у фіді {k}: різних {len(c)}, вживань {sum(c.values())}')

    good, unknown, still_ru, unk_dst = [], [], [], []
    for kind, src, dst in rows:
        if src not in feed[kind]:
            unknown.append((kind, src))
            continue
        # Артикул, перенесений з оригіналу незмінним, доказом російського
        # тексту не є — див. `carried_codes()`.
        hits = [w for w in ru_words(dst) if w not in carried_codes(src, dst)]
        if hits:
            still_ru.append((kind, src, dst, ' '.join(hits)))
            continue
        # Перевірка 2 ловить лише СТРОГО російське — те, що є в лексиконі або
        # має чужу літеру. Слово поза обома словниками вона пропускає мовчки:
        # негативний контроль 25.08.2026 показав, що пара «Медь → Медь»
        # проходить без єдиного слова в лозі, бо `медь` лежить у кошику
        # «непізнане», а не в «ru». Відхиляти такі пари не можна — там же
        # живуть законні «оснастка», «шуруповерт», «штабелер», — але й
        # мовчати не можна: мовчазний прохід і є та хвороба, від якої лікує
        # правило позитивного контролю. Тому попередження, не відмова.
        u = unknown_words(dst)
        if u:
            unk_dst.append((kind, src, dst, u))
        good.append((kind, src, dst, feed[kind][src]))

    if unknown:
        logger.error(f'НЕМАЄ У ФІДІ — не записано: {len(unknown)}')
        for kind, src in unknown[:20]:
            logger.error(f'   {kind}: {src[:70]!r}')
    if still_ru:
        logger.error(f'ПЕРЕКЛАД ЛИШИВСЯ РОСІЙСЬКИМ — не записано: {len(still_ru)}')
        for kind, src, dst, hit in still_ru[:20]:
            logger.error(f'   {kind}: {src[:40]!r} → {dst[:40]!r} ({hit!r})')
    if unk_dst:
        logger.warning(f'У ПЕРЕКЛАДІ СЛОВА ПОЗА ОБОМА СЛОВНИКАМИ — записано, '
                       f'але перегляньте: {len(unk_dst)}')
        for kind, src, dst, u in unk_dst[:20]:
            logger.warning(f'   {kind}: {src[:40]!r} → {dst[:40]!r} {u}')

    covered = sum(u for _, _, _, u in good)
    logger.info(f'до запису: {len(good)} пар, {covered} вживань')
    if a.dry:
        return 1 if (unknown or still_ru) else 0

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    psycopg2.extras.execute_batch(cur, """
        INSERT INTO toptul_translation (kind, src, dst, uses)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT (kind, src) DO UPDATE SET dst=EXCLUDED.dst,
                                              uses=EXCLUDED.uses""",
        [(k, s, d, u) for k, s, d, u in good])
    conn.commit()

    # Крок 3: нуль треба пояснити. Друкуємо не «записано N», а що лишилось.
    left = collections.Counter()
    for kind in KINDS:
        cur.execute('SELECT src FROM toptul_translation WHERE kind=%s', (kind,))
        done = {r['src'] for r in cur.fetchall()}
        rest = {s: c for s, c in feed[kind].items() if s not in done}
        left[kind] = len(rest)
        logger.info(f'{kind}: у таблиці {len(done)}, лишилось без перекладу '
                    f'{len(rest)} різних / {sum(rest.values())} вживань')
        for s, c in sorted(rest.items(), key=lambda x: -x[1])[:10]:
            logger.info(f'      {c:5}  {s[:60]!r}')
    cur.close()
    conn.close()
    logger.success(f'записано {len(good)} пар')
    return 1 if (unknown or still_ru) else 0


if __name__ == '__main__':
    sys.exit(main())
