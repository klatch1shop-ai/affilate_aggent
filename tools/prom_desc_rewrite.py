#!/usr/bin/env python3
"""Унікальні описи товарів: синтез із фактів, а не переказ чужого тексту.

Замір (`prom_dup_check.py`) показав: наші описи збігаються з картками інших
продавців SexOpt у середньому на 86%, девʼять із вісімнадцяти — дослівно на
100%. Майданчик групує однакові тексти й показує один, тож дослівна копія
працює проти нас.

**Принцип той самий, що в SKILL-09 для характеристик: беремо ФАКТИ, а не
формулювання.** Модель отримує структуровані дані — тип, бренд, матеріал,
розміри, живлення, призначення — і пише текст із них. Це принципово
відрізняється від перефразування: переказ лишає слід оригіналу (той самий
порядок думок, ті самі звороти), синтез дає власний текст.

Чому локальна модель, а не безкоштовний API: асортимент 18+, і хостингові
моделі його відмовляються обробляти — перевірено на NVIDIA NIM. Локальна
не має фільтрів і не відправляє дані назовні.

Запуск:
    python3 tools/prom_desc_rewrite.py --from-report      # позиції з заміру
    python3 tools/prom_desc_rewrite.py --sku SO1446
    python3 tools/prom_desc_rewrite.py --report
"""
import argparse
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import psycopg2.extras
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
from shared.utils.db import get_connection  # noqa: E402
from prom_dup_check import overlap, similarity, flat  # noqa: E402

FEED = os.path.join(BASE_DIR, 'output', 'noire_prom.xml')
REPORT = os.path.join(BASE_DIR, 'docs', 'prom_duplicate_report.json')
OLLAMA = (os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')
          + '/api/generate')
MODEL = os.getenv('NOIRE_REWRITE_MODEL', 'aya-expanse:8b')

# Опис пишемо ЗІ СПИСКУ ФАКТІВ. Прямо забороняємо те, що заборонено
# правилами Prom (посилання, ціни, доставка) — інакше модель охоче додає
# «замовляйте з доставкою по Україні», а це порушення.
# Промпт навмисно позбавлений «художньої» свободи. Перша версія просила
# «напиши опис», і модель охоче добудовувала контекст, якого у фактах не
# було: у AD30400 зʼявились «професійні актори та ентузіасти сцени», у
# 10BBRB — «сфера інтимної гігієни». Це те саме порушення, що й у
# характеристиках: вигадане значення гірше за відсутнє.
#
# Тому формулювання змінене з «напиши» на «склади речення З ЦИХ фактів»,
# додано явну заборону на сценарії, аудиторію й метафори, і знято вимогу
# мінімального обсягу: коротший текст кращий за прикрашений вигадками.
# Третя ітерація промпту. Що виправлено й чому — по порядку.
#
# 1) ДЕДУКЦІЯ. Друга версія прибрала «художність», але модель почала
#    ВИВОДИТИ нові твердження: «Конструкція: двосторонні» → «оснащений
#    двома моторами» (AD108735). Формально не вигадка, фактично — дані,
#    яких у списку немає. Тепер заборонено явно.
#
# 2) ОБСЯГ. Правило «якщо фактів мало — пиши коротко» модель ігнорувала:
#    при бідному наборі (BM-245, 4 факти) вона добирала обсяг
#    загальниками — «високоякісні матеріали», «найвищі стандарти
#    якості», «покращення кровотоку». Тому ліміт тепер не порада, а
#    ЧИСЛО, пораховане з кількості фактів, і валідатор його перевіряє.
#    Немає місця під загальники — немає загальників.
PROMPT = """Перекажи факти про товар українською мовою.

ФАКТИ ({n} шт.):
{facts}

ЖОРСТКІ ПРАВИЛА:
- максимум {limit} символів; це межа, а не мета — коротше можна;
- пиши ТІЛЬКИ те, що прямо написано у фактах;
- НЕ роби висновків із фактів. Якщо написано «двосторонній» — пиши
  «двосторонній», а не «два мотори». Якщо характеристики немає в
  списку — її не існує;
- ЗАБОРОНЕНО: оцінки («високоякісний», «надійний», «унікальний»),
  сценарії використання, кому підійде, для чого купують, відчуття,
  порівняння, метафори, «ідеальний вибір», «забезпечує комфорт»;
- не згадуй ціну, знижки, доставку, оплату, магазин;
- суцільний текст без заголовків, списків, посилань і емодзі.

Перше речення — тип товару, бренд, модель. Далі — характеристики зі
списку підряд.

Виведи лише текст."""

BANNED = re.compile(r'(?i)(достав|оплат|знижк|акці|замовл|магазин|http|www\.)')


def ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS prom_rewritten_desc (
        sku         TEXT PRIMARY KEY,
        original    TEXT,
        rewritten   TEXT,
        overlap_before NUMERIC,
        overlap_after  NUMERIC,
        status      TEXT,
        reason      TEXT,
        model       TEXT,
        seconds     NUMERIC,
        created_at  TIMESTAMPTZ DEFAULT NOW())""")


def facts_for(offer, features: dict) -> str:
    """Структуровані факти: назва, категорія, характеристики фіду й кабінету."""
    out = [f"Назва: {offer.findtext('name_ua')}",
           f"Бренд: {offer.findtext('vendor')}"]
    prm = {p.get('name'): (p.text or '') for p in offer.findall('param')}
    for k, v in prm.items():
        if v:
            out.append(f'{k}: {v}')
    skip = ('Мин. розница', 'Бренд (Страна)', 'Группа товара')
    for k, v in (features or {}).items():
        if v and not any(s in k for s in skip) and k not in prm:
            out.append(f'{k}: {v}')
    return '\n'.join(out[:22])


def limit_for(n_facts: int) -> int:
    """Ліміт символів за кількістю фактів.

    Рішення власника 17.08.2026. Сенс: не дати місця під «добір
    загальниками». Модель, отримавши чотири факти й дозвіл на 800
    символів, гарантовано добудує решту вигадками — це доведено на
    BM-245.
    """
    if n_facts <= 3:
        return 150
    if n_facts <= 6:
        return 300
    return 500


# Ознаки товару, які модель любить приписати, коли фактів мало. Перевіряються
# механічно: якщо ознака є в тексті, вона МУСИТЬ бути у фактах. Просити модель
# не вигадувати виявилось марно — третя ітерація промпту дала «двосторонній» у
# чотирьох картках із десяти в бідній половині, і валідатор пропустив три з них.
CLAIM_WORDS = (
    'двосторонн', 'водонепроникн', 'водостійк', 'реалістичн', 'телескопічн',
    'безшумн', 'підігрів', 'вібрац', 'віброефект', 'надувн', 'кишеньков',
    'перезаряджув', 'акумулятор', 'батарейк', 'пульт', 'дистанційн',
    'силікон', 'метал', 'скло', 'латекс', 'шкір', 'нержавію',
)
# Списки й заголовки промпт забороняє прямо, але модель усе одно їх пише.
LIST_RE = re.compile(r'^\s*[-•*•]\s+\S', re.M)


def claim_check(text: str, facts: str) -> str:
    """Ознака в тексті, якої немає у фактах, — вигадка. Порожньо = чисто."""
    t, f = text.lower(), facts.lower()
    for w in CLAIM_WORDS:
        if w in t and w not in f:
            return w
    # «Країна бренду» ≠ «Країна-виробник»: модель плутала їх і писала
    # «Виробник: Нідерланди» там, де у фактах лише країна бренду.
    if re.search(r'виробник|вироблен|виготовлен(?:ий|а|о)\s+(?:у|в)\s', t) \
            and 'країна-виробник' not in f:
        return 'виробник (у фактах лише країна бренду)'
    return ''


def validate(text: str, original: str, limit: int = 500, facts: str = '') -> str:
    """Порожній рядок = придатний опис, інакше причина відмови."""
    t = (text or '').strip()
    if len(t) < 80:
        return f'закороткий ({len(t)})'
    if len(t) > limit:
        return f'перевищено ліміт {limit} ({len(t)}) — добір загальниками'
    if BANNED.search(t):
        return 'згадка про доставку/ціну/магазин'
    if not re.search(r'[іїєґ]', t):
        return 'не українською'
    if LIST_RE.search(t):
        return 'написано списком (заборонено промптом)'
    if facts:
        bad = claim_check(t, facts)
        if bad:
            return f'ознака «{bad}» відсутня у фактах — вигадка'
    ov = overlap(flat(t), flat(original))
    if ov > 25:
        return f'надто близький до оригіналу ({ov:.0f}%)'
    return ''


def generate(facts: str, n: int, limit: int) -> tuple:
    t0 = time.time()
    r = requests.post(OLLAMA, json={
        'model': MODEL,
        'prompt': PROMPT.format(facts=facts, n=n, limit=limit),
        'stream': False,
        # температура нижча за 0.8: творчість тут не потрібна, потрібен
        # переказ. Висока температура і давала «унікальний дизайн».
        'options': {'temperature': 0.3, 'num_predict': 400}}, timeout=600)
    return (r.json().get('response') or '').strip(), time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from-report', action='store_true')
    ap.add_argument('--sku')
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure(cur)
    conn.commit()

    if a.report:
        cur.execute("""SELECT status, count(*) c, round(avg(overlap_after), 1) o
                       FROM prom_rewritten_desc GROUP BY status""")
        for r in cur.fetchall():
            print(f"   {r['status']:8} {r['c']:4}  збіг після: {r['o']}%")
        return

    if a.from_report:
        skus = [r['sku'] for r in json.load(open(REPORT))
                if r.get('max_similarity', 0) >= 70]
    else:
        skus = (a.sku or '').split(',')
    root = ET.parse(FEED).getroot()
    offers = {o.findtext('vendorCode'): o for o in root.findall('.//offer')}

    cur.execute('SELECT sku, features FROM sexopt_dropship_price')
    feats = {r['sku']: r['features'] for r in cur.fetchall()}

    print(f'до переписування: {len(skus)}   модель: {MODEL}\n')
    ok = bad = 0
    for sku in skus:
        o = offers.get(sku)
        if o is None:
            continue
        original = flat(o.findtext('description_ua') or '')
        facts = facts_for(o, feats.get(sku) or {})
        n_facts = len([x for x in facts.split('\n') if x.strip()])
        limit = limit_for(n_facts)
        try:
            text, sec = generate(facts, n_facts, limit)
        except Exception as e:
            print(f'   {sku}: {type(e).__name__}')
            continue
        why = validate(text, original, limit, facts)
        ov_after = overlap(flat(text), original)
        cur.execute("""INSERT INTO prom_rewritten_desc
            (sku, original, rewritten, overlap_after, status, reason, model, seconds)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (sku) DO UPDATE SET rewritten=EXCLUDED.rewritten,
              overlap_after=EXCLUDED.overlap_after, status=EXCLUDED.status,
              reason=EXCLUDED.reason, seconds=EXCLUDED.seconds""",
                    (sku, original, text, round(ov_after, 1),
                     'ok' if not why else 'manual', why or None, MODEL,
                     round(sec, 1)))
        conn.commit()
        ok += not why
        bad += bool(why)
        print(f"   {sku:10} {n_facts:2} фактів → ≤{limit} | {len(text):4} симв | "
              f"збіг {ov_after:4.1f}%  {'✓' if not why else '✗ ' + why}")
    print(f'\nпридатних: {ok}, на перегляд: {bad}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
