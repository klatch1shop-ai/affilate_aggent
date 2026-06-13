"""
tools/epicentr_quality_checker.py
====================================
Інструмент перевірки якості та SEO для Єпіцентр XML.

CLI:
    python3 tools/epicentr_quality_checker.py --xml exports/carvol_epicentr.xml --report
    python3 tools/epicentr_quality_checker.py --xml exports/carvol_epicentr.xml --fix --output exports/carvol_epicentr_fixed.xml
    python3 tools/epicentr_quality_checker.py --xml exports/carvol_epicentr.xml --enhance-names --limit 100
"""

import os, sys, re, json, argparse, time
from datetime import datetime
from collections import Counter, defaultdict
from typing import Optional

import xml.etree.ElementTree as ET
from xml.dom import minidom

sys.path.insert(0, '/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')

from loguru import logger
from shared.utils.db import get_connection

# ── Константи ──────────────────────────────────────────────────────────────

CAR_BRANDS = [
    'Volkswagen', 'Toyota', 'Nissan', 'Skoda', 'BMW', 'Audi', 'Hyundai', 'Kia',
    'Renault', 'Peugeot', 'Citroen', 'Opel', 'Ford', 'Mercedes', 'Chevrolet',
    'Honda', 'Mazda', 'Mitsubishi', 'Subaru', 'Lexus', 'Jeep', 'Volvo',
    'Land Rover', 'Porsche', 'Seat', 'Fiat', 'Alfa Romeo', 'Chrysler', 'Dodge',
    'Infiniti', 'Acura', 'Cadillac', 'Buick', 'GMC', 'Lincoln', 'Jaguar',
    'Bentley', 'Lamborghini', 'Ferrari', 'Maserati', 'Tesla', 'Lada', 'УАЗ',
    'ВАЗ', 'Chery', 'Geely', 'BYD', 'Great Wall', 'Haval', 'Daewoo', 'Ssangyong',
    'Isuzu', 'Dacia', 'Suzuki', 'Daihatsu', 'Universal',
]

CAR_BRANDS_UPPER = {b.upper() for b in CAR_BRANDS}

FORBIDDEN_WORDS = ['телефон', 'сайт', 'http://', 'https://', 'www.', 'call', 'дзвоніть']

DEFAULT_WEIGHT_FIX = 500


# ── Завантаження brand cache ────────────────────────────────────────────────

_brand_cache: dict[str, str] = {}

def load_brand_cache() -> dict[str, str]:
    """Повертає {UPPER(brand_name): valuecode}."""
    global _brand_cache
    if _brand_cache:
        return _brand_cache
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT valuecode, value_ua FROM epicentr_brand_cache")
        for row in cur.fetchall():
            _brand_cache[row['value_ua'].upper().strip()] = row['valuecode']
        conn.close()
        logger.info(f"Brand cache loaded: {len(_brand_cache)} entries")
    except Exception as e:
        logger.error(f"Brand cache load error: {e}")
    return _brand_cache


# ── DB logging ──────────────────────────────────────────────────────────────

def init_quality_table():
    sql = """
    CREATE TABLE IF NOT EXISTS epicentr_quality_log (
        offer_id    TEXT PRIMARY KEY,
        score       INTEGER,
        vendor_ok   BOOLEAN,
        name_score  INTEGER,
        desc_score  INTEGER,
        photo_count INTEGER,
        params_score INTEGER,
        issues      JSONB,
        checked_at  TIMESTAMP DEFAULT NOW()
    );
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(sql)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"init_quality_table error: {e}")


def save_quality_log(rows: list[dict]):
    if not rows:
        return
    sql = """
    INSERT INTO epicentr_quality_log
        (offer_id, score, vendor_ok, name_score, desc_score, photo_count, params_score, issues, checked_at)
    VALUES (%(offer_id)s, %(score)s, %(vendor_ok)s, %(name_score)s, %(desc_score)s,
            %(photo_count)s, %(params_score)s, %(issues)s, NOW())
    ON CONFLICT (offer_id) DO UPDATE SET
        score=EXCLUDED.score, vendor_ok=EXCLUDED.vendor_ok, name_score=EXCLUDED.name_score,
        desc_score=EXCLUDED.desc_score, photo_count=EXCLUDED.photo_count,
        params_score=EXCLUDED.params_score, issues=EXCLUDED.issues, checked_at=NOW();
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        for row in rows:
            row['issues'] = json.dumps(row['issues'], ensure_ascii=False)
            cur.execute(sql, row)
        conn.commit()
        conn.close()
        logger.info(f"Saved {len(rows)} quality log rows")
    except Exception as e:
        logger.error(f"save_quality_log error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ProductChecker
# ══════════════════════════════════════════════════════════════════════════════

class ProductChecker:
    def __init__(self):
        self.brand_cache = load_brand_cache()
        self._seen_names: set[str] = set()

    # ── VENDOR (20 балів) ──────────────────────────────────────────────────

    def check_vendor(self, offer: ET.Element) -> dict:
        vendor_el = offer.find('vendor')
        if vendor_el is None or not (vendor_el.text or '').strip():
            return {'ok': False, 'score': 0, 'code': '', 'issue': 'Відсутній тег vendor'}

        name = vendor_el.text.strip()
        code = vendor_el.get('code', '').strip()

        # Якщо код вже є і не порожній — вважаємо OK
        if code:
            return {'ok': True, 'score': 20, 'code': code, 'issue': ''}

        # Шукаємо в brand cache (case-insensitive)
        found_code = self.brand_cache.get(name.upper())
        if found_code:
            return {'ok': True, 'score': 20, 'code': found_code, 'issue': ''}

        return {
            'ok': False, 'score': 0, 'code': '',
            'issue': f'Бренд "{name}" не зареєстрований в Єпіцентрі'
        }

    # ── CATEGORY (інформаційна, без балів) ────────────────────────────────

    def check_category(self, offer: ET.Element) -> dict:
        cat = offer.find('category')
        if cat is None or not cat.get('code'):
            return {'ok': False, 'issue': 'Відсутня категорія або code'}
        return {'ok': True, 'issue': ''}

    # ── NAME (25 балів) ────────────────────────────────────────────────────

    def check_name(self, offer: ET.Element) -> dict:
        score = 0
        issues = []

        name_el = offer.find("name[@lang='ua']")
        if name_el is None:
            name_el = offer.find('name')
        name = (name_el.text or '').strip() if name_el is not None else ''

        if not name:
            return {'ok': False, 'score': 0, 'issues': ['Назва відсутня']}

        # Шаблон [Тип] + [Бренд] + [Модель/SKU] — мінімум 3 слова
        words = name.split()
        if len(words) >= 3:
            score += 10
        else:
            issues.append('Назва занадто коротка — очікується шаблон Тип+Бренд+Модель')

        # Довжина 50-150 символів
        if 50 <= len(name) <= 150:
            score += 5
        elif len(name) < 50:
            issues.append(f'Назва коротка ({len(name)} симв., мін. 50)')
        else:
            issues.append(f'Назва довга ({len(name)} симв., макс. 150)')

        # Є марка авто
        name_upper = name.upper()
        if any(b.upper() in name_upper for b in CAR_BRANDS):
            score += 5
        else:
            issues.append('Не знайдена марка авто в назві')

        # Немає зайвих символів (!, ??, ...)
        if not re.search(r'[!?]{2,}|\.{3,}', name):
            score += 5
        else:
            issues.append('Зайві символи в назві (!! або ???)')

        # Унікальність назви
        name_key = name.lower()
        if name_key in self._seen_names:
            issues.append('Дублікат назви')
        else:
            self._seen_names.add(name_key)

        return {'ok': score >= 15, 'score': score, 'issues': issues}

    # ── DESCRIPTION (20 балів) ─────────────────────────────────────────────

    def check_description(self, offer: ET.Element) -> dict:
        score = 0
        issues = []

        desc_el = offer.find("description[@lang='ua']")
        if desc_el is None:
            desc_el = offer.find('description')

        text = ''
        if desc_el is not None and desc_el.text:
            text = desc_el.text.strip()

        if not text:
            return {'ok': False, 'score': 0, 'issues': ['Опис відсутній']}

        # Довжина > 200 → +10, > 500 → ще +5
        if len(text) > 500:
            score += 15
        elif len(text) > 200:
            score += 10
        else:
            issues.append(f'Опис короткий ({len(text)} симв., мін. 200)')

        # Немає заборонених слів
        text_lower = text.lower()
        forbidden_found = [w for w in FORBIDDEN_WORDS if w in text_lower]
        if not forbidden_found:
            score += 5
        else:
            issues.append(f'Заборонені слова в описі: {forbidden_found}')

        # Без знаків оклику
        if '!' not in text:
            score += 5
        else:
            issues.append('Знаки оклику в описі')

        # Перевірка CDATA (шукаємо в сирому тексті XML - тут просто перевіряємо наявність HTML тегів)
        if re.search(r'<[a-zA-Z]', text):
            score += 0  # HTML є — добре, але CDATA не перевірити через ET
            issues.append('Опис містить HTML без CDATA-обгортки (перевірте XML)')

        return {'ok': score >= 10, 'score': min(score, 20), 'issues': issues}

    # ── PHOTOS (15 балів) ──────────────────────────────────────────────────

    def check_photos(self, offer: ET.Element) -> dict:
        pics = offer.findall('picture')
        count = len(pics)
        issues = []

        # Перевірка HTTPS
        non_https = [p.text for p in pics if p.text and not p.text.startswith('https://')]
        if non_https:
            issues.append(f'URL не на HTTPS: {non_https[:3]}')

        if count == 0:
            return {'ok': False, 'score': 0, 'count': 0, 'issues': ['Немає фото']}
        elif count == 1:
            score = 5
            issues.append('Лише 1 фото (оптимально 4+)')
        elif count <= 3:
            score = 10
            if count < 4:
                issues.append(f'Лише {count} фото (оптимально 4+)')
        else:
            score = 15

        if non_https:
            score = 0

        return {'ok': score >= 5, 'score': score, 'count': count, 'issues': issues}

    # ── PARAMS (10 балів) ──────────────────────────────────────────────────

    def check_params(self, offer: ET.Element) -> dict:
        score = 0
        issues = []
        params = offer.findall('param')

        filled = 0
        total = len(params)
        has_measure = has_ratio = has_brand = False

        for p in params:
            code = p.get('paramcode', '')
            val = (p.text or '').strip()
            valuecode = p.get('valuecode', '').strip()

            if code == 'measure':
                has_measure = bool(valuecode)
                if has_measure:
                    score += 3
                    filled += 1
                else:
                    issues.append('measure.valuecode порожній')
            elif code == 'ratio':
                has_ratio = bool(val)
                if has_ratio:
                    score += 3
                    filled += 1
                else:
                    issues.append('ratio порожній')
            elif code == 'brand':
                has_brand = bool(val)
                if has_brand:
                    score += 4
                    filled += 1
                else:
                    issues.append('brand param порожній')

        if not has_measure:
            issues.append('Відсутній param measure')
        if not has_ratio:
            issues.append('Відсутній param ratio')
        if not has_brand:
            issues.append('Відсутній param brand')

        return {
            'ok': score >= 7, 'score': score,
            'filled': filled, 'total': total,
            'issues': issues
        }

    # ── LOGISTICS (10 балів) ───────────────────────────────────────────────

    def check_logistics(self, offer: ET.Element) -> dict:
        score = 0
        issues = []

        def get_num(tag: str) -> float:
            el = offer.find(tag)
            if el is None or not (el.text or '').strip():
                return 0.0
            try:
                return float(el.text.strip())
            except ValueError:
                return 0.0

        weight = get_num('weight')
        width  = get_num('width')
        height = get_num('height')
        length = get_num('length')

        if weight > 0:
            score += 3
        else:
            issues.append('weight = 0')

        if width > 0 and height > 0 and length > 0:
            score += 3
        else:
            missing = [t for t, v in [('width', width), ('height', height), ('length', length)] if v == 0]
            issues.append(f'Відсутні габарити: {missing}')

        if 100 <= weight <= 50000:
            score += 4
        elif weight > 0:
            issues.append(f'Нереалістична вага {weight}г (очікується 100-50000)')

        return {'ok': score >= 6, 'score': score, 'issues': issues}

    # ── TOTAL SCORE ────────────────────────────────────────────────────────

    def calculate_score(self, offer: ET.Element) -> dict:
        v = self.check_vendor(offer)
        n = self.check_name(offer)
        d = self.check_description(offer)
        p = self.check_photos(offer)
        pm = self.check_params(offer)
        l = self.check_logistics(offer)

        total = v['score'] + n['score'] + d['score'] + p['score'] + pm['score'] + l['score']

        all_issues = []
        if not v['ok']:    all_issues.extend([v['issue']] if v['issue'] else [])
        all_issues.extend(n['issues'])
        all_issues.extend(d['issues'])
        all_issues.extend(p['issues'])
        all_issues.extend(pm['issues'])
        all_issues.extend(l['issues'])

        return {
            'offer_id':    offer.get('id', ''),
            'score':       total,
            'vendor_ok':   v['ok'],
            'vendor_code': v['code'],
            'name_score':  n['score'],
            'desc_score':  d['score'],
            'photo_count': p['count'],
            'params_score': pm['score'],
            'logistics_score': l['score'],
            'issues':      [i for i in all_issues if i],
        }


# ══════════════════════════════════════════════════════════════════════════════
# QualityReport
# ══════════════════════════════════════════════════════════════════════════════

class QualityReport:
    def __init__(self):
        self.checker = ProductChecker()

    def analyze_xml(self, xml_path: str) -> dict:
        logger.info(f"Analyzing: {xml_path}")
        tree = ET.parse(xml_path)
        root = tree.getroot()
        offers = root.findall('.//offer')
        logger.info(f"Offers found: {len(offers)}")

        results = []
        for offer in offers:
            r = self.checker.calculate_score(offer)
            results.append(r)

        # Агрегація
        scores = [r['score'] for r in results]
        issue_counter: Counter = Counter()
        for r in results:
            for iss in r['issues']:
                issue_counter[iss] += 1

        buckets = {'90-100': 0, '70-89': 0, '50-69': 0, '30-49': 0, '0-29': 0}
        for s in scores:
            if s >= 90:    buckets['90-100'] += 1
            elif s >= 70:  buckets['70-89'] += 1
            elif s >= 50:  buckets['50-69'] += 1
            elif s >= 30:  buckets['30-49'] += 1
            else:          buckets['0-29'] += 1

        avg = sum(scores) / len(scores) if scores else 0
        vendor_ok = sum(1 for r in results if r['vendor_ok'])
        photo_4plus = sum(1 for r in results if r['photo_count'] >= 4)

        summary = {
            'total': len(results),
            'avg_score': round(avg, 1),
            'min_score': min(scores) if scores else 0,
            'max_score': max(scores) if scores else 0,
            'buckets': buckets,
            'vendor_registered': vendor_ok,
            'vendor_missing': len(results) - vendor_ok,
            'photo_4plus': photo_4plus,
            'top_issues': issue_counter.most_common(15),
        }

        return {'summary': summary, 'results': results}

    def print_report(self, data: dict):
        s = data['summary']
        print("\n" + "═" * 60)
        print("   ЗВІТ ЯКОСТІ — ЄПІЦЕНТР XML")
        print("═" * 60)
        print(f"  Товарів:        {s['total']}")
        print(f"  Середній score: {s['avg_score']}/100")
        print(f"  Мін / Макс:     {s['min_score']} / {s['max_score']}")
        print(f"  Бренд в кеші:   {s['vendor_registered']}  |  Не знайдено: {s['vendor_missing']}")
        print(f"  4+ фото:        {s['photo_4plus']}")
        print()
        print("  Розподіл score:")
        total = s['total']
        for bucket, cnt in sorted(s['buckets'].items(), reverse=True):
            pct = cnt / total * 100 if total else 0
            bar = '█' * int(pct / 2)
            print(f"    {bucket:7s}: {cnt:5d}  {pct:5.1f}%  {bar}")
        print()
        print("  Топ проблем:")
        for issue, cnt in s['top_issues']:
            pct = cnt / total * 100 if total else 0
            print(f"    [{cnt:5d}  {pct:4.1f}%]  {issue}")
        print()
        print("  Рекомендації:")
        if s['vendor_missing'] > 0:
            print(f"   ⚑  {s['vendor_missing']} товарів без valuecode бренду — потрібна реєстрація в Єпіцентрі PIM")
        if s['photo_4plus'] < total * 0.5:
            print(f"   ⚑  Менше половини товарів мають 4+ фото")
        if s['avg_score'] < 60:
            print(f"   ⚑  Середній score низький ({s['avg_score']}) — запустіть --fix")
        print("═" * 60 + "\n")

    def fix_issues(self, xml_path: str, output_path: str):
        logger.info(f"Fixing: {xml_path} → {output_path}")
        brand_cache = load_brand_cache()

        tree = ET.parse(xml_path)
        root = tree.getroot()
        offers = root.findall('.//offer')

        fixed = 0
        for offer in offers:
            changed = False

            # 1. Підставити valuecode бренду
            vendor_el = offer.find('vendor')
            if vendor_el is not None and not vendor_el.get('code', '').strip():
                name = (vendor_el.text or '').strip().upper()
                code = brand_cache.get(name)
                if code:
                    vendor_el.set('code', code)
                    changed = True

            # 2. weight=0 → DEFAULT_WEIGHT_FIX
            weight_el = offer.find('weight')
            if weight_el is not None:
                try:
                    if float(weight_el.text or 0) == 0:
                        weight_el.text = str(DEFAULT_WEIGHT_FIX)
                        changed = True
                except (ValueError, TypeError):
                    weight_el.text = str(DEFAULT_WEIGHT_FIX)
                    changed = True

            # 3. Очистити заборонені слова з опису
            desc_el = offer.find("description[@lang='ua']")
            if desc_el is None:
                desc_el = offer.find('description')
            if desc_el is not None and desc_el.text:
                original = desc_el.text
                cleaned = original
                for w in FORBIDDEN_WORDS:
                    cleaned = re.sub(re.escape(w), '', cleaned, flags=re.IGNORECASE)
                if cleaned != original:
                    desc_el.text = cleaned
                    changed = True

            if changed:
                fixed += 1

        # Зберегти
        ET.indent(root, space='  ')
        tree.write(output_path, encoding='utf-8', xml_declaration=True)
        logger.info(f"Fixed {fixed}/{len(offers)} offers → {output_path}")
        print(f"\n  Виправлено {fixed}/{len(offers)} товарів → {output_path}")

    def enhance_names(self, xml_path: str, output_path: str, limit: int = 100):
        try:
            import anthropic
        except ImportError:
            print("Потрібен пакет anthropic: pip install anthropic")
            return

        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            print("ANTHROPIC_API_KEY не знайдено в .env")
            return

        client = anthropic.Anthropic(api_key=api_key)

        tree = ET.parse(xml_path)
        root = tree.getroot()
        offers = root.findall('.//offer')

        enhanced = 0
        for offer in offers[:limit]:
            name_el = offer.find("name[@lang='ua']")
            if name_el is None:
                name_el = offer.find('name')
            if name_el is None or not name_el.text:
                continue

            original_name = name_el.text.strip()
            vendor_el = offer.find('vendor')
            brand = vendor_el.text.strip() if vendor_el is not None and vendor_el.text else ''

            prompt = (
                f"Перепиши назву товару за шаблоном: [Тип] [Бренд] [Модель] для [Авто] [Рік].\n"
                f"Максимум 100 символів. Тільки факти з оригінальної назви. Без знаків оклику.\n"
                f"Мова: українська.\n"
                f"Оригінал: {original_name}"
            )

            try:
                msg = client.messages.create(
                    model='claude-haiku-4-5-20251001',
                    max_tokens=150,
                    messages=[{'role': 'user', 'content': prompt}]
                )
                new_name = msg.content[0].text.strip().strip('"').strip("'")
                if new_name and len(new_name) <= 150:
                    name_el.text = new_name
                    enhanced += 1
                    logger.debug(f"Enhanced: {original_name[:50]} → {new_name[:50]}")
            except Exception as e:
                logger.warning(f"API error for {offer.get('id')}: {e}")

            time.sleep(0.1)  # rate limit

        ET.indent(root, space='  ')
        tree.write(output_path, encoding='utf-8', xml_declaration=True)
        logger.info(f"Enhanced {enhanced}/{min(limit, len(offers))} names → {output_path}")
        print(f"\n  Покращено {enhanced} назв → {output_path}")

    def enhance_descriptions(self, xml_path: str, output_path: str, limit: int = 50):
        try:
            import anthropic
        except ImportError:
            print("Потрібен пакет anthropic: pip install anthropic")
            return

        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            print("ANTHROPIC_API_KEY не знайдено в .env")
            return

        client = anthropic.Anthropic(api_key=api_key)

        tree = ET.parse(xml_path)
        root = tree.getroot()
        offers = root.findall('.//offer')

        enhanced = 0
        for offer in offers[:limit]:
            desc_el = offer.find("description[@lang='ua']")
            if desc_el is None:
                desc_el = offer.find('description')
            name_el = offer.find("name[@lang='ua']")
            if name_el is None:
                name_el = offer.find('name')
            name = (name_el.text or '').strip() if name_el is not None else ''

            existing_desc = (desc_el.text or '').strip() if desc_el is not None else ''
            if len(existing_desc) > 300:
                continue  # вже нормальний опис

            prompt = (
                f"Напиши унікальний SEO-опис товару 300-500 символів українською.\n"
                f"Без контактів, без знаків оклику, без HTML тегів.\n"
                f"На основі назви товару: {name}"
            )

            try:
                msg = client.messages.create(
                    model='claude-haiku-4-5-20251001',
                    max_tokens=300,
                    messages=[{'role': 'user', 'content': prompt}]
                )
                new_desc = msg.content[0].text.strip()
                if new_desc:
                    if desc_el is None:
                        desc_el = ET.SubElement(offer, 'description')
                        desc_el.set('lang', 'ua')
                    desc_el.text = new_desc
                    enhanced += 1
            except Exception as e:
                logger.warning(f"API error for {offer.get('id')}: {e}")

            time.sleep(0.1)

        ET.indent(root, space='  ')
        tree.write(output_path, encoding='utf-8', xml_declaration=True)
        print(f"\n  Покращено {enhanced} описів → {output_path}")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='Epicentr XML Quality Checker')
    parser.add_argument('--xml', required=True, help='Шлях до XML файлу')
    parser.add_argument('--report', action='store_true', help='Показати звіт якості')
    parser.add_argument('--fix', action='store_true', help='Автовиправлення')
    parser.add_argument('--output', help='Шлях для виправленого XML')
    parser.add_argument('--enhance-names', action='store_true', help='SEO покращення назв через Claude API')
    parser.add_argument('--enhance-descriptions', action='store_true', help='SEO покращення описів через Claude API')
    parser.add_argument('--limit', type=int, default=100, help='Ліміт товарів для enhance (дефолт 100)')
    parser.add_argument('--save-db', action='store_true', help='Зберегти результати в БД')
    parser.add_argument('--top-bad', type=int, default=0, help='Показати N найгірших товарів')
    args = parser.parse_args()

    if not os.path.exists(args.xml):
        print(f"Файл не знайдено: {args.xml}")
        sys.exit(1)

    report = QualityReport()

    if args.report or args.save_db or args.top_bad:
        data = report.analyze_xml(args.xml)
        if args.report:
            report.print_report(data)
        if args.top_bad > 0:
            worst = sorted(data['results'], key=lambda r: r['score'])[:args.top_bad]
            print(f"\nТоп-{args.top_bad} найгірших товарів:")
            for r in worst:
                print(f"  [{r['score']:3d}] {r['offer_id']:<20s}  {'; '.join(r['issues'][:3])}")
        if args.save_db:
            init_quality_table()
            db_rows = [{
                'offer_id':     r['offer_id'],
                'score':        r['score'],
                'vendor_ok':    r['vendor_ok'],
                'name_score':   r['name_score'],
                'desc_score':   r['desc_score'],
                'photo_count':  r['photo_count'],
                'params_score': r['params_score'],
                'issues':       r['issues'],
            } for r in data['results']]
            save_quality_log(db_rows)

    if args.fix:
        out = args.output or args.xml.replace('.xml', '_fixed.xml')
        report.fix_issues(args.xml, out)

    if args.enhance_names:
        out = args.output or args.xml.replace('.xml', '_enhanced.xml')
        report.enhance_names(args.xml, out, limit=args.limit)

    if args.enhance_descriptions:
        out = args.output or args.xml.replace('.xml', '_enhanced.xml')
        report.enhance_descriptions(args.xml, out, limit=args.limit)

    if not any([args.report, args.fix, args.enhance_names, args.enhance_descriptions, args.save_db, args.top_bad]):
        parser.print_help()


if __name__ == '__main__':
    main()
