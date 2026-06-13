"""
tools/epicentr_quality_checker.py
Інструмент перевірки якості XML-фіду для Єпіцентр.

CLI:
    python3 tools/epicentr_quality_checker.py --xml exports/carvol_epicentr.xml --report
    python3 tools/epicentr_quality_checker.py --xml exports/carvol_epicentr.xml --top-issues 20
    python3 tools/epicentr_quality_checker.py --xml exports/carvol_epicentr.xml --report --save-db
"""

import os, sys, re, json, argparse
from collections import Counter, defaultdict

import xml.etree.ElementTree as ET

sys.path.insert(0, '/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')

from loguru import logger
from shared.utils.db import get_connection


CAR_BRANDS = [
    'Volkswagen', 'Toyota', 'BMW', 'Mercedes', 'Audi', 'Nissan',
    'Hyundai', 'Kia', 'Ford', 'Opel', 'Renault', 'Skoda',
    'Peugeot', 'Citroen', 'Chevrolet', 'Honda',
]

FORBIDDEN_WORDS = ['телефон', 'сайт', 'http', 'viber', 'telegram']


# ══════════════════════════════════════════════════════════════════════════════
# ProductChecker
# ══════════════════════════════════════════════════════════════════════════════

class ProductChecker:

    def check_vendor(self, offer: ET.Element, brand_cache: dict) -> dict:
        """brand_cache = {name_lower: (valuecode, value_ua)}
        Знайдено:   {ok: True,  score: 20, valuecode: '...', name: '...', issue: ''}
        Не знайдено:{ok: False, score: 0,  valuecode: '',    name: '...', issue: '...'}
        """
        vendor_el = offer.find('vendor')
        if vendor_el is None or not (vendor_el.text or '').strip():
            return {'ok': False, 'score': 0, 'valuecode': '', 'name': '',
                    'issue': 'Відсутній тег vendor'}
        name = vendor_el.text.strip()
        entry = brand_cache.get(name.lower())
        if entry:
            return {'ok': True, 'score': 20, 'valuecode': entry[0], 'name': entry[1], 'issue': ''}
        return {'ok': False, 'score': 0, 'valuecode': '', 'name': name,
                'issue': 'Бренд не зареєстрований'}

    def check_name(self, offer: ET.Element) -> dict:
        """score: 0-25"""
        score = 0
        issues = []
        name_el = offer.find("name[@lang='ua']")
        if name_el is None:
            name_el = offer.find('name')
        name = (name_el.text or '').strip() if name_el is not None else ''

        if not name:
            return {'score': 0, 'issues': ['Назва відсутня']}

        # 50-150 chars → +10
        if 50 <= len(name) <= 150:
            score += 10
        else:
            issues.append(f'Довжина назви {len(name)} симв. (потрібно 50-150)')

        # Car brand → +5
        if any(b.upper() in name.upper() for b in CAR_BRANDS):
            score += 5
        else:
            issues.append('Марка авто не знайдена в назві')

        # Inches or tech spec → +5
        if re.search(r'дюйм|дюймів|inch|"', name, re.IGNORECASE):
            score += 5

        # No ! or ? → +5
        if '!' not in name and '?' not in name:
            score += 5
        else:
            issues.append('Знаки ! або ? в назві')

        return {'score': score, 'issues': issues}

    def check_description(self, offer: ET.Element) -> dict:
        """score: 0-20
        >100 → +5, >300 → +5, >500 → +5, без заборонених слів → +5
        """
        score = 0
        issues = []
        desc_el = offer.find("description[@lang='ua']")
        if desc_el is None:
            desc_el = offer.find('description')
        text = (desc_el.text or '').strip() if desc_el is not None else ''

        if not text:
            return {'score': 0, 'issues': ['Опис відсутній']}

        if len(text) > 100:
            score += 5
        else:
            issues.append(f'Опис короткий ({len(text)} симв., потрібно >100)')
        if len(text) > 300:
            score += 5
        if len(text) > 500:
            score += 5

        text_lower = text.lower()
        found = [w for w in FORBIDDEN_WORDS if w in text_lower]
        if not found:
            score += 5
        else:
            issues.append(f'Заборонені слова в описі: {found}')

        return {'score': min(score, 20), 'issues': issues}

    def check_photos(self, offer: ET.Element) -> dict:
        """1 фото → 5, 2-3 → 10, 4+ → 15; score: 0-15"""
        count = len(offer.findall('picture'))
        if count == 0:
            return {'score': 0, 'count': 0, 'issues': ['Немає фото']}
        elif count == 1:
            return {'score': 5, 'count': 1, 'issues': []}
        elif count <= 3:
            return {'score': 10, 'count': count, 'issues': []}
        return {'score': 15, 'count': count, 'issues': []}

    def check_params(self, offer: ET.Element) -> dict:
        """measure є → +4, ratio є → +3, brand є → +3; score: 0-10"""
        score = 0
        issues = []
        by_code = {p.get('paramcode', ''): p for p in offer.findall('param')}

        m = by_code.get('measure')
        if m is not None and (m.get('valuecode') or '').strip():
            score += 4
        else:
            issues.append('measure відсутній або без valuecode')

        r = by_code.get('ratio')
        if r is not None and (r.text or '').strip():
            score += 3
        else:
            issues.append('ratio відсутній')

        b = by_code.get('brand')
        if b is not None and (b.text or '').strip():
            score += 3
        else:
            issues.append('brand param відсутній')

        return {'score': score, 'issues': issues}

    def check_logistics(self, offer: ET.Element) -> dict:
        """weight>0 → +3, всі габарити → +4, weight 50-50000 → +3; score: 0-10"""
        score = 0
        issues = []

        def num(tag: str) -> float:
            el = offer.find(tag)
            try:
                return float((el.text or '').strip()) if el is not None else 0.0
            except ValueError:
                return 0.0

        weight = num('weight')
        width, height, length = num('width'), num('height'), num('length')

        if weight > 0:
            score += 3
        else:
            issues.append('weight = 0')

        if width > 0 and height > 0 and length > 0:
            score += 4
        else:
            missing = [t for t, v in [('width', width), ('height', height), ('length', length)] if v == 0]
            issues.append(f'Відсутні габарити: {missing}')

        if 50 <= weight <= 50000:
            score += 3
        elif weight > 0:
            issues.append(f'Нереалістична вага {weight:.0f}г (50-50000)')

        return {'score': score, 'issues': issues}

    def calculate_score(self, offer: ET.Element, brand_cache: dict) -> int:
        """Сума всіх check_* методів. Повертає 0-100."""
        v  = self.check_vendor(offer, brand_cache)
        n  = self.check_name(offer)
        d  = self.check_description(offer)
        p  = self.check_photos(offer)
        pm = self.check_params(offer)
        lg = self.check_logistics(offer)
        return v['score'] + n['score'] + d['score'] + p['score'] + pm['score'] + lg['score']


# ══════════════════════════════════════════════════════════════════════════════
# QualityReport
# ══════════════════════════════════════════════════════════════════════════════

class QualityReport:

    def __init__(self):
        self.checker = ProductChecker()

    def load_brand_cache(self, conn) -> dict:
        """SELECT valuecode, value_ua FROM epicentr_brand_cache
        Повертає {value_ua.lower(): (valuecode, value_ua)}
        """
        cache = {}
        cur = conn.cursor()
        cur.execute("SELECT valuecode, value_ua FROM epicentr_brand_cache")
        for row in cur.fetchall():
            key = (row['value_ua'] or '').lower().strip()
            if key:
                cache[key] = (row['valuecode'], row['value_ua'])
        logger.info(f"Brand cache loaded: {len(cache)} entries")
        return cache

    def _init_table(self, conn):
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS epicentr_quality_log")
        cur.execute("""
            CREATE TABLE epicentr_quality_log (
                offer_id        TEXT PRIMARY KEY,
                score           INTEGER,
                vendor_ok       BOOLEAN,
                vendor_issue    TEXT,
                name_score      INTEGER,
                desc_score      INTEGER,
                photo_count     INTEGER,
                params_score    INTEGER,
                logistics_score INTEGER,
                issues          JSONB,
                category        TEXT,
                checked_at      TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        logger.info("epicentr_quality_log — DROP + CREATE done")

    def _save_results(self, conn, results: list):
        sql = """
        INSERT INTO epicentr_quality_log
            (offer_id, score, vendor_ok, vendor_issue, name_score, desc_score,
             photo_count, params_score, logistics_score, issues, category, checked_at)
        VALUES
            (%(offer_id)s, %(score)s, %(vendor_ok)s, %(vendor_issue)s, %(name_score)s,
             %(desc_score)s, %(photo_count)s, %(params_score)s, %(logistics_score)s,
             %(issues)s::jsonb, %(category)s, NOW())
        ON CONFLICT (offer_id) DO UPDATE SET
            score=EXCLUDED.score, vendor_ok=EXCLUDED.vendor_ok,
            vendor_issue=EXCLUDED.vendor_issue, name_score=EXCLUDED.name_score,
            desc_score=EXCLUDED.desc_score, photo_count=EXCLUDED.photo_count,
            params_score=EXCLUDED.params_score, logistics_score=EXCLUDED.logistics_score,
            issues=EXCLUDED.issues, category=EXCLUDED.category, checked_at=NOW()
        """
        cur = conn.cursor()
        for r in results:
            row = dict(r)
            row['issues'] = json.dumps(row['issues'], ensure_ascii=False)
            cur.execute(sql, row)
        conn.commit()
        logger.info(f"Saved {len(results)} rows to epicentr_quality_log")

    def analyze_xml(self, xml_path: str, conn, save_db: bool = True) -> dict:
        """Парсить XML, рахує скори, опційно зберігає в БД (DROP+CREATE).
        Повертає dict зі summary та results.
        """
        brand_cache = self.load_brand_cache(conn)

        logger.info(f"Parsing: {xml_path}")
        tree = ET.parse(xml_path)
        root = tree.getroot()
        offers = root.findall('.//offer')
        logger.info(f"Offers found: {len(offers)}")

        c = self.checker
        results = []

        for offer in offers:
            v  = c.check_vendor(offer, brand_cache)
            n  = c.check_name(offer)
            d  = c.check_description(offer)
            p  = c.check_photos(offer)
            pm = c.check_params(offer)
            lg = c.check_logistics(offer)

            total = v['score'] + n['score'] + d['score'] + p['score'] + pm['score'] + lg['score']

            issues = []
            if not v['ok'] and v['issue']:
                issues.append(v['issue'])
            issues.extend(n['issues'])
            issues.extend(d['issues'])
            issues.extend(p['issues'])
            issues.extend(pm['issues'])
            issues.extend(lg['issues'])

            cat_el = offer.find('category')
            if cat_el is not None:
                category = (cat_el.text or cat_el.get('code', '') or '').strip()
            else:
                category = ''

            results.append({
                'offer_id':        offer.get('id', ''),
                'score':           total,
                'vendor_ok':       v['ok'],
                'vendor_issue':    v['issue'],
                'name_score':      n['score'],
                'desc_score':      d['score'],
                'photo_count':     p['count'],
                'params_score':    pm['score'],
                'logistics_score': lg['score'],
                'issues':          [i for i in issues if i],
                'category':        category,
            })

        if save_db:
            self._init_table(conn)
            self._save_results(conn, results)

        # Aggregation
        scores = [r['score'] for r in results]
        issue_counter: Counter = Counter()
        for r in results:
            for iss in r['issues']:
                issue_counter[iss] += 1

        buckets = {'90-100': 0, '70-89': 0, '50-69': 0, '30-49': 0, '0-29': 0}
        for s in scores:
            if s >= 90:   buckets['90-100'] += 1
            elif s >= 70: buckets['70-89'] += 1
            elif s >= 50: buckets['50-69'] += 1
            elif s >= 30: buckets['30-49'] += 1
            else:         buckets['0-29'] += 1

        cat_scores: dict = defaultdict(list)
        for r in results:
            if r['category']:
                cat_scores[r['category']].append(r['score'])
        cat_avg = {cat: round(sum(v) / len(v), 1) for cat, v in cat_scores.items()}

        return {
            'total':       len(results),
            'avg_score':   round(sum(scores) / len(scores), 1) if scores else 0,
            'min_score':   min(scores) if scores else 0,
            'max_score':   max(scores) if scores else 0,
            'buckets':     buckets,
            'vendor_ok':   sum(1 for r in results if r['vendor_ok']),
            'photo_4plus': sum(1 for r in results if r['photo_count'] >= 4),
            'top_issues':  issue_counter.most_common(50),
            'cat_avg':     dict(sorted(cat_avg.items(), key=lambda x: -x[1])),
            'results':     results,
        }

    def print_report(self, report: dict):
        """Таблиця розподілу + топ-10 проблем + середній score по категоріях."""
        total = report['total']
        print("\n" + "═" * 62)
        print("   ЗВІТ ЯКОСТІ — ЄПІЦЕНТР XML")
        print("═" * 62)
        print(f"  Товарів:          {total}")
        print(f"  Середній score:   {report['avg_score']}/100")
        print(f"  Мін / Макс:       {report['min_score']} / {report['max_score']}")
        print(f"  Бренд знайдено:   {report['vendor_ok']}  |  Не знайдено: {total - report['vendor_ok']}")
        print(f"  4+ фото:          {report['photo_4plus']}")
        print()
        print("  Розподіл score:")
        for bucket in ['90-100', '70-89', '50-69', '30-49', '0-29']:
            cnt = report['buckets'][bucket]
            pct = cnt / total * 100 if total else 0
            bar = '█' * int(pct / 2)
            print(f"    {bucket:7s}: {cnt:5d}  {pct:5.1f}%  {bar}")
        print()
        print("  Топ-10 проблем:")
        for issue, cnt in report['top_issues'][:10]:
            pct = cnt / total * 100 if total else 0
            print(f"    [{cnt:5d}  {pct:4.1f}%]  {issue}")
        if report.get('cat_avg'):
            print()
            print("  Середній score по категоріях (топ-10):")
            for cat, avg in list(report['cat_avg'].items())[:10]:
                print(f"    {avg:5.1f}  {cat}")
        print("═" * 62 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='Epicentr XML Quality Checker')
    parser.add_argument('--xml', required=True, help='Шлях до XML файлу')
    parser.add_argument('--report', action='store_true', help='Показати звіт якості')
    parser.add_argument('--top-issues', type=int, default=0, metavar='N',
                        help='Показати топ-N проблем')
    parser.add_argument('--save-db', action='store_true',
                        help='Зберегти результати в БД (DROP + CREATE таблиці)')
    args = parser.parse_args()

    if not os.path.exists(args.xml):
        print(f"Файл не знайдено: {args.xml}")
        sys.exit(1)

    if not any([args.report, args.top_issues, args.save_db]):
        parser.print_help()
        sys.exit(0)

    conn = get_connection()
    try:
        rpt = QualityReport()
        report = rpt.analyze_xml(args.xml, conn, save_db=args.save_db)

        if args.report:
            rpt.print_report(report)

        if args.top_issues:
            print(f"\nТоп-{args.top_issues} проблем:")
            for issue, cnt in report['top_issues'][:args.top_issues]:
                pct = cnt / report['total'] * 100 if report['total'] else 0
                print(f"  [{cnt:5d}  {pct:4.1f}%]  {issue}")
            print()
    finally:
        conn.close()


if __name__ == '__main__':
    main()
