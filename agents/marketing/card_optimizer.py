import os, sys, json, re, time
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

def score_card(product: dict) -> dict:
    """Оцінює картку товару від 0 до 100"""
    score = 0
    issues = []
    suggestions = []

    # 1. ФОТО (25 балів)
    pics = product.get('pictures') or []
    if isinstance(pics, str):
        pics = json.loads(pics)
    
    pics_count = len(pics)
    if pics_count == 0:
        issues.append('❌ Немає фото — товар не буде показуватись!')
    elif pics_count == 1:
        score += 5
        suggestions.append('📷 Додайте ще 3-5 фото — збільшить конверсію')
    elif pics_count <= 3:
        score += 12
        suggestions.append('📷 Рекомендовано 5+ фото')
    elif pics_count <= 5:
        score += 18
    else:
        score += 25

    # 2. НАЗВА (20 балів)
    name = product.get('name_uk') or ''
    name_len = len(name)
    
    if name_len < 20:
        issues.append('❌ Назва занадто коротка')
    elif name_len < 40:
        score += 8
        suggestions.append('✏️ Розширте назву: Тип + Бренд + Модель + Характеристики')
    elif name_len <= 80:
        score += 20
    elif name_len <= 120:
        score += 15
    else:
        score += 10
        suggestions.append('✏️ Скоротіть назву до 80 символів')

    vendor = product.get('vendor') or ''
    if vendor and vendor.lower() in name.lower():
        score += 0  # вже рахували
    else:
        suggestions.append(f'✏️ Додайте бренд "{vendor}" в назву')

    # 3. ОПИС (20 балів)
    desc = product.get('description_epicentr') or product.get('description_raw') or ''
    if isinstance(desc, str):
        desc = re.sub(r'<[^>]+>', '', desc).strip()
    
    desc_len = len(desc)
    if desc_len < 50:
        issues.append('❌ Опис відсутній або занадто короткий')
        suggestions.append('📝 Напишіть опис 200-500 символів про технічні характеристики')
    elif desc_len < 200:
        score += 8
        suggestions.append('📝 Розширте опис до 200+ символів')
    elif desc_len < 500:
        score += 15
    else:
        score += 20

    # 4. ХАРАКТЕРИСТИКИ (20 балів)
    params = product.get('params') or {}
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except:
            params = {}
    
    params_count = len(params)
    if params_count == 0:
        issues.append('❌ Немає характеристик — критично для видачі!')
    elif params_count < 3:
        score += 5
        issues.append(f'⚠️ Тільки {params_count} характеристики — потрібно мін. 5')
    elif params_count < 5:
        score += 10
        suggestions.append('📋 Додайте ще характеристики')
    elif params_count < 10:
        score += 15
    else:
        score += 20

    # 5. ЦІНА (15 балів)
    price = float(product.get('price_our') or product.get('price_supplier') or 0)
    if price == 0:
        issues.append('❌ Ціна не встановлена')
    else:
        score += 10  # базово — конкретну оцінку по ринку дасть analyzer

    # Рейтинг
    if score >= 85:
        grade = 'A'
    elif score >= 70:
        grade = 'B'
    elif score >= 50:
        grade = 'C'
    elif score >= 30:
        grade = 'D'
    else:
        grade = 'F'

    return {
        'score': score,
        'grade': grade,
        'issues': issues,
        'suggestions': suggestions,
        'details': {
            'photos': pics_count,
            'name_len': name_len,
            'desc_len': desc_len,
            'params_count': params_count,
            'price': price,
        }
    }

def analyze_all(limit=20):
    """Аналізує всі товари і виводить статистику"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT sku, name_uk, vendor, price_supplier, price_our,
               pictures, params, description_epicentr
        FROM my_products
        WHERE price_supplier > 0
        ORDER BY price_supplier DESC
        LIMIT %s
    """, (limit,))
    products = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()

    scores = []
    for p in products:
        result = score_card(p)
        scores.append({
            'sku': p['sku'],
            'name': (p.get('name_uk') or '')[:50],
            **result
        })

    # Статистика
    avg_score = sum(s['score'] for s in scores) / len(scores)
    grade_dist = {}
    for s in scores:
        grade_dist[s['grade']] = grade_dist.get(s['grade'], 0) + 1

    print(f"\n{'='*60}")
    print(f"АНАЛІЗ КАРТОК ТОВАРІВ (топ {limit} за ціною)")
    print(f"{'='*60}")
    print(f"Середній бал: {avg_score:.1f}/100")
    print(f"Розподіл: {grade_dist}")
    print(f"\nНайгірші картки:")
    worst = sorted(scores, key=lambda x: x['score'])[:5]
    for s in worst:
        print(f"  [{s['grade']}:{s['score']}] {s['sku']} — {s['name']}")
        for issue in s['issues']:
            print(f"    {issue}")

    print(f"\nНайкращі картки:")
    best = sorted(scores, key=lambda x: -x['score'])[:5]
    for s in best:
        print(f"  [{s['grade']}:{s['score']}] {s['sku']} — {s['name']}")

    return scores

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--sku', type=str, default=None)
    args = parser.parse_args()

    if args.sku:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM my_products WHERE sku=%s", (args.sku,))
        p = dict(cur.fetchone())
        cur.close(); conn.close()
        result = score_card(p)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        analyze_all(args.limit)
